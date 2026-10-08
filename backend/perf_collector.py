"""
Per-minute CPU/RAM sampler for the vCenter Performance page.

One daemon thread. Every SAMPLE_INTERVAL seconds it asks each configured vCenter for the live
CPU/RAM quick-stats of every powered-on VM (a single lightweight PropertyCollector pass over a
kept-open session - not the heavy inventory scan the dashboard cache uses). Samples are folded
into in-memory accumulators and flushed to SQLite as hourly + daily roll-ups every
FLUSH_INTERVAL seconds (and once more on a clean shutdown), so the DB only receives a few
thousand rows per flush.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pyVim.connect import Disconnect

import perf_store
from vcenter_client import collect_cpu_ready, collect_perf_samples, open_session

SAMPLE_INTERVAL = 60      # seconds between samples
FLUSH_INTERVAL = 180      # seconds between DB flushes (<= this many seconds lost on a hard crash)
PRUNE_EVERY = 3600

_lock = threading.Lock()
# (env, vm) -> {"hour": bucket, "day": bucket, "num_cpu", "mem_gb", "h": acc, "d": acc}
# acc = [max_cpu, max_cpu_ts, max_mem, max_mem_ts, cpu_sum, mem_sum, samples,
#        cpu_n_mid, cpu_n_high, mem_n_mid, mem_n_high,
#        ready_max, ready_max_ts, ready_sum, ready_n, ready_n_warn, ready_n_crit]   (same order as the DB columns)
_acc: dict = {}
_sessions: dict = {}      # env -> ServiceInstance
status: dict = {}         # env -> {"last_ok": epoch, "last_error": str, "vms": int}


def _new_acc():
    return [0.0, "", 0.0, "", 0.0, 0.0, 0, 0, 0, 0, 0, 0.0, "", 0.0, 0, 0, 0]


def _fold(acc, cpu, mem, ts, ready=None):
    if cpu > acc[0]:
        acc[0], acc[1] = cpu, ts
    if mem > acc[2]:
        acc[2], acc[3] = mem, ts
    acc[4] += cpu
    acc[5] += mem
    acc[6] += 1
    if cpu >= perf_store.BAND_MID:
        acc[7] += 1
        if cpu >= perf_store.BAND_HIGH:
            acc[8] += 1
    if mem >= perf_store.BAND_MID:
        acc[9] += 1
        if mem >= perf_store.BAND_HIGH:
            acc[10] += 1
    if ready is not None:
        if ready > acc[11]:
            acc[11], acc[12] = ready, ts
        acc[13] += ready
        acc[14] += 1
        if ready >= perf_store.READY_WARN:
            acc[15] += 1
            if ready >= perf_store.READY_CRIT:
                acc[16] += 1


def _sample_env(env: str, host: str, user: str, pwd: str) -> None:
    if not host or not user:
        return
    st = status.setdefault(env, {})
    try:
        si = _sessions.get(env)
        if si is None:
            si = _sessions[env] = open_session(host, user, pwd)
        try:
            samples = collect_perf_samples(si)
        except Exception:
            # Session probably expired - reconnect once and retry.
            try:
                Disconnect(si)
            except Exception:
                pass
            si = _sessions[env] = open_session(host, user, pwd)
            samples = collect_perf_samples(si)
        try:
            collect_cpu_ready(si, samples)
        except Exception as exc:
            print(f"[perf] {env} cpu-ready error: {exc}")
        now =datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M")
        hour = now.strftime("%Y-%m-%d %H:00")
        day = now.strftime("%Y-%m-%d")
        with _lock:
            for s in samples:
                key = (env, s["name"])
                e = _acc.get(key)
                if e is None:
                    e = _acc[key] = {"hour": hour, "day": day, "h": _new_acc(), "d": _new_acc()}
                if e["hour"] != hour:           # bucket rolled over between flushes
                    _queue_closed_bucket(key, e, "h")
                    e["hour"], e["h"] = hour, _new_acc()
                if e["day"] != day:
                    _queue_closed_bucket(key, e, "d")
                    e["day"], e["d"] = day, _new_acc()
                e["num_cpu"], e["mem_gb"] = s["num_cpu"], round(s["mem_mb"] / 1024, 1)
                _fold(e["h"], s["cpu_pct"], s["mem_pct"], ts, s.get("ready_pct"))
                _fold(e["d"], s["cpu_pct"], s["mem_pct"], ts, s.get("ready_pct"))
        st.update(last_ok=time.time(), last_error="", vms=len(samples))
    except Exception as exc:
        _sessions.pop(env, None)
        st.update(last_error=f"{type(exc).__name__}: {exc}")
        print(f"[perf] {env} sample error: {exc}")


_pending_h: list = []     # rows of buckets that closed (hour/day rollover) since the last flush
_pending_d: list = []


def _queue_closed_bucket(key, e, which) -> None:
    acc = e[which]
    if not acc[6]:
        return
    row = (key[0], key[1], e["hour"] if which == "h" else e["day"],
           e.get("num_cpu", 0), e.get("mem_gb", 0), *acc)
    (_pending_h if which == "h" else _pending_d).append(row)


def _flush() -> None:
    with _lock:
        hourly, daily = list(_pending_h), list(_pending_d)
        _pending_h.clear()
        _pending_d.clear()
        for key, e in _acc.items():
            if e["h"][6]:
                hourly.append((key[0], key[1], e["hour"], e.get("num_cpu", 0), e.get("mem_gb", 0), *e["h"]))
                e["h"] = _new_acc()
            if e["d"][6]:
                daily.append((key[0], key[1], e["day"], e.get("num_cpu", 0), e.get("mem_gb", 0), *e["d"]))
                e["d"] = _new_acc()
    try:
        perf_store.save_rollups(hourly, daily)
    except Exception as exc:
        print(f"[perf] flush error: {exc}")


def _loop(envs) -> None:
    time.sleep(20)                       # let the service finish starting
    perf_store.init_perf_tables()
    last_flush = last_prune = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(envs))) as pool:
        while True:
            started = time.time()
            futures = []
            for env, cfg_fn in envs:
                host, user, pwd = cfg_fn()
                futures.append(pool.submit(_sample_env, env, host, user, pwd))
            for f in futures:
                f.result()
            if time.time() - last_flush >= FLUSH_INTERVAL:
                _flush()
                last_flush = time.time()
            if time.time() - last_prune >= PRUNE_EVERY:
                try:
                    perf_store.prune()
                except Exception as exc:
                    print(f"[perf] prune error: {exc}")
                last_prune = time.time()
            time.sleep(max(1.0, SAMPLE_INTERVAL - (time.time() - started)))


def start(envs) -> None:
    """envs = [(env_name, lambda: (host, user, pwd)), ...]. Idempotent (one thread per process)."""
    if any(t.name == "vc-perf-collector" for t in threading.enumerate()):
        return
    threading.Thread(target=_loop, args=(envs,), daemon=True, name="vc-perf-collector").start()


def shutdown() -> None:
    """Write whatever is still buffered in memory and close the vCenter sessions.

    Called on a clean service stop/restart so no samples are lost; safe to call twice
    (the accumulators are reset after each flush)."""
    _flush()
    for si in list(_sessions.values()):
        try:
            Disconnect(si)
        except Exception:
            pass
    _sessions.clear()
