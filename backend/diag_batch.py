"""
Batch run of the "Analyze server" diagnosis over many VMs, optionally with the Ollama explanation, written to a
text file under logs/ so the rules can be reviewed and calibrated at scale instead of server by server.

Admin endpoints (app.py):
  GET /api/vcenter/perf/diagnose/batch/start?range=7d&min_level=3&ai=1&limit=80
  GET /api/vcenter/perf/diagnose/batch/status

Selection: VMs whose CPU or RAM load level (the page's load meter) is >= min_level (3 = "problematic").
Uses the live ESXi data from the collector; skips the slow live disk / Veeam lookups.
"""

import json
import os
import threading
import time
from collections import Counter

import ollama_client
import perf_collector
import perf_diagnose
import perf_store

_QUESTION = ("Using only the structured server data above, explain in plain English: (1) is there a real performance "
             "problem, (2) the most likely cause, (3) the actions in priority order. Do not invent numbers. About 150 words.")

_state = {"running": False, "progress": "", "file": "", "error": ""}
_lock = threading.Lock()
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")


def context_from(r: dict) -> str:
    """The same compact context the dashboard sends to the AI after 'Analyze server'."""
    lines = ["VM %s (%s), range %s" % (r["facts"].get("vm"), r["facts"].get("environment"), r["facts"].get("range")),
             "FACTS: %s" % json.dumps(r["facts"], ensure_ascii=False), "VERDICT: %s" % r["verdict"]["en"]]
    if r.get("cpu_answer"):
        lines.append("NEEDS MORE CPU?: %s" % r["cpu_answer"]["en"])
    for f in r["findings"]:
        lines.append("- [%s] %s: %s | %s%s" % (f["sev"], f["area"], f["title"]["en"], f["detail"]["en"],
                                                (" | ACTION: " + f["action"]["en"]) if f["action"]["en"] else ""))
    return "\n".join(lines)


def _levels(s: dict):
    n, b = s.get("samples") or 0, s.get("buckets") or 0
    return (perf_diagnose._load_level(n, s.get("cpu_n_mid") or 0, s.get("cpu_n_high") or 0, s.get("cpu_hot_buckets") or 0, b),
            perf_diagnose._load_level(n, s.get("mem_n_mid") or 0, s.get("mem_n_high") or 0, s.get("mem_hot_buckets") or 0, b))


def _run(range_key, since, table, min_level, with_ai, limit, system_prompt):
    try:
        rows = perf_store.get_summary(since, table, None, None)
        picked = [s for s in rows if max(_levels(s)) >= min_level]
        picked.sort(key=lambda s: (s["environment"], s["vm_name"]))
        picked = picked[:limit]
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.abspath(os.path.join(LOG_DIR, "diagnose_batch_%s.txt" % time.strftime("%Y%m%d_%H%M%S")))
        with _lock:
            _state["file"] = path
        blocks, verdicts, cpu_answers = [], Counter(), Counter()
        for i, s in enumerate(picked, 1):
            with _lock:
                _state["progress"] = "%d / %d" % (i, len(picked))
            env, name = s["environment"], s["vm_name"]
            live = perf_collector.live.get(env)
            host = None
            if live:
                hn = live["vm_host"].get(name)
                host = live["hosts"].get(hn) if hn else None
            try:
                series = perf_store.get_series(env, name, time.strftime("%Y-%m-%d %H:00", time.localtime(time.time() - 48 * 3600)), "vm_perf_hourly")
            except Exception:
                series = None
            r = perf_diagnose.diagnose(env, name, range_key, s, host, {"disks": []}, None, ((live or {}).get("vm_cfg") or {}).get(name), series)
            verdicts[r["level"]] += 1
            cpu_answers[(r.get("cpu_answer") or {}).get("en", "")[:60]] += 1
            n = max(s["samples"], 1)
            b = ["### %s / %s  (%s vCPU, %s GB)  verdict=%s" % (env, name, s.get("num_cpu"), s.get("mem_gb"), r["level"]),
                 "  CPU avg %.0f%% peak %.0f%% (>=85%%: %.1f%%, hot %s/%s) | RAM avg %.0f%% peak %.0f%% (>=85%%: %.1f%%) | Ready avg %.2f%% peak %.1f%% | Co-Stop peak %.1f%% | limit %s min | swap %s balloon %s lat %s%%" % (
                     s.get("avg_cpu_pct") or 0, s.get("max_cpu_pct") or 0, 100.0 * (s.get("cpu_n_high") or 0) / n, s.get("cpu_hot_buckets"), s.get("buckets"),
                     s.get("avg_mem_pct") or 0, s.get("max_mem_pct") or 0, 100.0 * (s.get("mem_n_high") or 0) / n,
                     s.get("ready_avg_pct") or 0, s.get("ready_max_pct") or 0, s.get("cs_max_pct") or 0, s.get("lim_n") or 0,
                     s.get("mp_swap_max_mb"), s.get("mp_balloon_max_mb"), s.get("mp_lat_max_pct")),
                 "  host: %s" % ("%s level=%s cpu %s%% ram %s%% ready %s ratio %s:1 reasons=%s" % (
                     host.get("name"), host.get("level"), host.get("cpu_pct"), host.get("mem_pct"), host.get("ready_avg"), host.get("vcpu_ratio"), host.get("reasons_en") or host.get("reasons")) if host else "n/a"),
                 "  VERDICT: %s" % r["verdict"]["en"]]
            if r.get("cpu_answer"):
                b.append("  CPU ANSWER: %s" % r["cpu_answer"]["en"])
            for f in r["findings"]:
                b.append("  - [%s] %s: %s -- %s" % (f["sev"], f["area"], f["title"]["en"], f["detail"]["en"]))
                if f["action"]["en"]:
                    b.append("      ACTION: %s" % f["action"]["en"])
            if with_ai:
                ctx = context_from(r)
                try:
                    out = ollama_client.chat_ex(
                        [{"role": "system", "content": system_prompt + "\n\nCurrent dashboard data provided by the user:\nSTRUCTURED SERVER DATA:\n" + ctx},
                         {"role": "user", "content": _QUESTION}], num_predict=400, temperature=0.2)
                    b.append("  AI (%ss): %s" % (out["seconds"], out["text"].replace("\n", " ")))
                except Exception as exc:
                    b.append("  AI ERROR: %s: %s" % (type(exc).__name__, exc))
            blocks.append("\n".join(b))
        head = ["Diagnosis batch %s | range %s | min load level %s | %d VMs | AI=%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), range_key, min_level, len(picked), with_ai),
                "Verdict levels: %s" % dict(verdicts), "CPU answers: %s" % dict(cpu_answers), ""]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(head) + "\n\n".join(blocks) + "\n")
        with _lock:
            _state["progress"] = "done (%d VMs)" % len(picked)
    except Exception as exc:
        with _lock:
            _state["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        with _lock:
            _state["running"] = False


def start(range_key: str, since: str, table: str, min_level: int, with_ai: bool, limit: int, system_prompt: str) -> dict:
    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "a batch is already running", **_state}
        _state.update(running=True, progress="starting", file="", error="")
    threading.Thread(target=_run, args=(range_key, since, table, min_level, with_ai, limit, system_prompt),
                     daemon=True, name="diag-batch").start()
    return {"started": True, "note": "poll /api/vcenter/perf/diagnose/batch/status; the result is written to logs/diagnose_batch_*.txt"}


def status() -> dict:
    with _lock:
        return dict(_state)
