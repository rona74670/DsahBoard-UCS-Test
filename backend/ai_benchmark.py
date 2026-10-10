"""
Mini benchmark for the dashboard's AI assistant: does the configured Ollama model reason well enough about
server performance, or is a stronger model needed?

It builds four synthetic servers with a known right answer, runs them through the same rule engine as the
"Analyze server" button (perf_diagnose), sends the resulting structured data to the model with the same prompt
the dashboard uses, and records: reply, seconds, tokens/s and any NUMBERS the model invented (not present in the
data it was given). A human (or Claude) then judges the replies against the "expected" line.

Runs in a background thread (a 30B model on CPU can need minutes per answer). Admin-only endpoints in app.py:
  GET /api/ai/models                       installed / running models
  GET /api/ai/benchmark/start?model=NAME   start a run (one at a time)
  GET /api/ai/benchmark/results[?format=text]
"""

import re
import threading
import time

import ollama_client
import perf_diagnose

_NUM_RE = re.compile(r"[0-9]+(?:[.][0-9]+)?")

_QUESTION = ("Using only the structured server data above, explain in plain English: (1) is there a real performance "
             "problem, (2) the most likely cause, (3) the actions in priority order. Do not invent numbers. About 150 words. If the verdict says no resource problem was found, answer in two sentences that no action is needed and do not list actions.")

_BASE = dict(
    samples=10080, num_cpu=8, mem_gb=16, max_cpu_pct=40, max_cpu_ts="2026-10-06 10:00", avg_cpu_pct=15,
    max_mem_pct=45, max_mem_ts="2026-10-06 10:00", avg_mem_pct=30,
    cpu_n_mid=0, cpu_n_high=0, cpu_hot_buckets=0, mem_n_mid=0, mem_n_high=0, mem_hot_buckets=0, buckets=7,
    ready_samples=10000, ready_n_warn=0, ready_n_crit=0, ready_hot_buckets=0, ready_max_pct=0.5, ready_avg_pct=0.1,
    cs_samples=9000, cs_n_warn=0, cs_max_pct=0.2, lim_n=0, lim_max_pct=0,
    mp_swap_max_mb=0, mp_balloon_max_mb=0, mp_lat_max_pct=0, mp_n_swap=0, mp_n_balloon=0, mp_samples=9000,
)
_HOST_OK = dict(name="esx-01", level="ok", cpu_pct=27, mem_pct=60, ready_avg=0.1, ready_max=0.4, vcpu_ratio=3.2, cores=28,
                vms=28, reasons=[], top_vms=[{"name": "other-vm", "cpu_pct": 17}])
_DISKS_OK = dict(powered_on=True, disks=[dict(label="Hard disk 1", datastore="DS-1", read_ms=0.7, write_ms=0.2,
                                              read_ms_max=2, write_ms_max=1, level="ok")])

SCENARIOS = [
    dict(id="A", title="Runaway process (CPU 100% bursts, no contention)",
         expected="No more vCPUs. Cause is inside the guest (a process or scheduled job); find it. Host and disks are fine.",
         env="TC", name="WEB-IIS-02", summary=dict(_BASE, num_cpu=32, mem_gb=8, max_cpu_pct=100, avg_cpu_pct=15.8, cpu_n_mid=900,
                                                   cpu_n_high=700, cpu_hot_buckets=4, ready_max_pct=2, ready_n_warn=2),
         host=_HOST_OK, disks=_DISKS_OK),
    dict(id="B", title="Host contention (sustained CPU Ready, busy ESXi)",
         expected="Do NOT add vCPUs. Move the VM to a quieter host (vMotion) / relieve the host.",
         env="TC8", name="APP-04", summary=dict(_BASE, max_cpu_pct=95, avg_cpu_pct=55, cpu_n_mid=3000, cpu_n_high=800, cpu_hot_buckets=5,
                                                ready_n_warn=900, ready_n_crit=300, ready_hot_buckets=6, ready_max_pct=14, ready_avg_pct=6.5),
         host=dict(_HOST_OK, level="crit", cpu_pct=93, ready_avg=6.1, ready_max=14, vcpu_ratio=6.4,
                   reasons=["ESXi CPU 93%", "CPU Ready average 6.1% per vCPU", "vCPU:core ratio 6.4:1"]),
         disks=_DISKS_OK),
    dict(id="C", title="Memory squeezed by the host (swap)",
         expected="Host-side memory problem: check for a VM memory limit, then ESXi memory; urgent because of swap.",
         env="PT", name="FILE-01", summary=dict(_BASE, max_mem_pct=88, avg_mem_pct=60, mem_n_mid=2000, mem_n_high=300, mem_hot_buckets=3,
                                                mp_swap_max_mb=350, mp_n_swap=120, mp_balloon_max_mb=900, mp_n_balloon=400, mp_lat_max_pct=6),
         host=dict(_HOST_OK, level="crit", mem_pct=96, reasons=["ESXi RAM 96%", "3 VMs with swap on the host"]), disks=_DISKS_OK),
    dict(id="D", title="Healthy server",
         expected="No problem. Should NOT invent issues or recommend changes.",
         env="TC", name="OK-03", summary=dict(_BASE), host=_HOST_OK, disks=_DISKS_OK),
]

_state = {"running": None, "results": {}}
_lock = threading.Lock()


def _context(sc: dict) -> str:
    r = perf_diagnose.diagnose(sc["env"], sc["name"], "7d", sc["summary"], sc["host"], sc["disks"], None)
    lines = ["VM %s (%s), range 7d" % (sc["name"], sc["env"]), "FACTS: %s" % r["facts"], "VERDICT: %s" % r["verdict"]["en"]]
    if r.get("cpu_answer"):
        lines.append("NEEDS MORE CPU?: %s" % r["cpu_answer"]["en"])
    for f in r["findings"]:
        lines.append("- [%s] %s: %s | %s%s" % (f["sev"], f["area"], f["title"]["en"], f["detail"]["en"],
                                                (" | ACTION: " + f["action"]["en"]) if f["action"]["en"] else ""))
    return "\n".join(lines)


def _invented(reply: str, context: str) -> list:
    known = set(_NUM_RE.findall(context))
    out = []
    for n in _NUM_RE.findall(reply):
        if n in known:
            continue
        if "." not in n and int(n) <= 9:        # list numbering / small counts
            continue
        out.append(n)
    return sorted(set(out))


def _run(model: str, system_prompt: str) -> None:
    res = {"model": model, "status": "running", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "scenarios": []}
    with _lock:
        _state["results"][model] = res
    try:
        for sc in SCENARIOS:
            ctx = _context(sc)
            messages = [{"role": "system", "content": system_prompt + "\n\nCurrent dashboard data provided by the user:\nSTRUCTURED SERVER DATA:\n" + ctx},
                        {"role": "user", "content": _QUESTION}]
            item = {"id": sc["id"], "title": sc["title"], "expected": sc["expected"]}
            try:
                out = ollama_client.chat_ex(messages, model=model, num_predict=500, temperature=0.2, keep_alive="2m")
                item.update(reply=out["text"], seconds=out["seconds"], tokens_per_s=out["tokens_per_s"],
                            invented_numbers=_invented(out["text"], ctx))
            except Exception as exc:
                item["error"] = "%s: %s" % (type(exc).__name__, exc)
            res["scenarios"].append(item)
        res["status"] = "done"
    except Exception as exc:
        res["status"] = "error: %s" % exc
    finally:
        res["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")


def _run_many(models: list, system_prompt: str) -> None:
    try:
        for m in models:
            with _lock:
                _state["running"] = m
            _run(m, system_prompt)
    finally:
        with _lock:
            _state["running"] = None


def start(models, system_prompt: str) -> dict:
    """models: one name or a list; several models are benchmarked one after the other."""
    models = [models] if isinstance(models, str) else list(models)
    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "a benchmark is already running: %s" % _state["running"]}
        _state["running"] = models[0]
    threading.Thread(target=_run_many, args=(models, system_prompt), daemon=True, name="ai-benchmark").start()
    return {"started": True, "models": models, "note": "poll /api/ai/benchmark/results?format=text (4 answers per model; a big model can take several minutes each)"}


def results() -> dict:
    with _lock:
        return {"running": _state["running"], "results": _state["results"]}


def as_text(data: dict) -> str:
    lines = ["Running now: %s" % data["running"], ""]
    for model, r in data["results"].items():
        lines.append("=== MODEL %s  [%s]  started %s  finished %s ===" % (model, r["status"], r.get("started"), r.get("finished", "-")))
        for it in r["scenarios"]:
            lines.append("")
            lines.append("--- %s: %s" % (it["id"], it["title"]))
            lines.append("EXPECTED: %s" % it["expected"])
            if "error" in it:
                lines.append("ERROR: %s" % it["error"])
                continue
            lines.append("TIME: %ss   SPEED: %s tok/s   INVENTED NUMBERS: %s" % (it["seconds"], it["tokens_per_s"], it["invented_numbers"] or "none"))
            lines.append("REPLY:")
            lines.append(it["reply"])
        lines.append("")
    return "\n".join(lines)
