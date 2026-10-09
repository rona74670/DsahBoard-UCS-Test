"""
Right-sizing recommendations (add / remove vCPU and RAM) from the collected peak history.

Sizing is based on PEAKS, never averages: for every VM we take its daily peak (the highest
per-minute sample of each day) and size to the 95th percentile of those daily peaks, i.e. the
peak that keeps recurring - a single freak day (e.g. one backup/patch night) doesn't inflate
the recommendation. The absolute maximum is still reported next to it.

Reliability: a recommendation is only issued once the VM has at least `min_days` days of data
(and was running for a meaningful part of each day). Days recorded before the VM was last
resized are ignored, since their peaks describe a different size.
"""

import math
import re
from typing import Optional

from database import get_db

DEFAULTS = {
    "days": 30,          # look-back window
    "min_days": 14,      # days of data required before a recommendation is trusted
    "cpu_target": 70.0,  # size so the recurring CPU peak lands at this % of capacity
    "mem_target": 80.0,  # ... and the recurring RAM peak at this %
    "min_samples_per_day": 360,   # >= 6 h of 1-minute samples for a day to count
}

# CPU contention signals (collected from the day the feature went live, so they usually cover fewer
# days than the CPU/RAM peaks - they only act once they have at least CS_MIN_DAYS of data).
CS_MIN_DAYS = 3
CS_P95_WARN = 3.0      # P95 of the daily Co-Stop peak (% per vCPU) above which the VM has too many vCPUs
LIMIT_MIN_DAYS = 2     # days with a CPU limit holding the VM back before we flag it


# Database-style servers deliberately use every GB they are given (SQL buffer pool, Oracle SGA,
# caches ...), so a low "active memory" peak says nothing about how much RAM they need - cutting
# it would hurt performance. Such VMs are never recommended for a RAM *reduction* (they can still
# be recommended for an increase). Detected from the server role set in the dashboard, and from
# the VM name (substring match on purpose: names like ATHADOPEPRDB01 / IS-OPTDB09 have no separator;
# a false positive only means "don't shrink", the safe direction).
PROTECTED_ROLE_WORDS = ("sql", "db", "oracle", "hana", "סאפ", "מסד", "דאטה")
PROTECTED_NAME_RE = re.compile(r"(sql|db|oracle|hana|mysql|maria|postgres|pgsql|mongo|redis|sybase|cache)", re.I)


def _protect_reason(vm_name: str, role: str) -> str:
    r = (role or "").lower()
    if any(w in r for w in PROTECTED_ROLE_WORDS):
        return f"תפקיד השרת: {role} — שרתי DB מנצלים את כל הזיכרון שהוקצה להם"
    if PROTECTED_NAME_RE.search(vm_name or ""):
        return "שם השרת מצביע על שרת DB/Cache — שרתים כאלה מנצלים את כל הזיכרון שהוקצה להם"
    return ""


def _load_roles() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT LOWER(environment) AS e, vm_name, note FROM vm_notes").fetchall()
    return {(r["e"], r["vm_name"]): r["note"] for r in rows}


def _p95(values: list) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def _round_mem_up(gb: float) -> float:
    """Round a RAM size up to a sensible VM size: 1 GB steps below 8, 2 GB up to 32, then 4 GB."""
    if gb <= 8:
        return float(math.ceil(gb))
    if gb <= 32:
        return float(math.ceil(gb / 2) * 2)
    return float(math.ceil(gb / 4) * 4)


def _round_cpu_up(n: int, cur: int) -> int:
    n = max(1, n)
    return n if (n < 4 or cur < 4) else n + (n % 2)   # even counts from 4 vCPU up


def _load_rows(days: int, env: Optional[str]) -> list:
    where, params = ["p.bucket >= date('now','localtime',?)"], [f"-{days - 1} days"]
    if env:
        where.append("p.environment = ?")
        params.append(env)
    sql = f"""
        SELECT p.environment, p.vm_name, p.bucket, p.num_cpu, p.mem_gb,
               p.max_cpu_pct, p.max_mem_pct, p.samples, p.cs_max_pct, p.cs_samples, p.lim_n,
               COALESCE(s.sap_number,'') AS sap_number
        FROM vm_perf_daily p
        LEFT JOIN vm_sap_cache s ON s.vm_name = p.vm_name AND LOWER(s.environment) = LOWER(p.environment)
        WHERE {' AND '.join(where)}
        ORDER BY p.environment, p.vm_name, p.bucket
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _cpu_contention(cur, out, days_rows):
    """Applies the Co-Stop / CPU-limit signals to a trusted CPU recommendation (mutates out).

    - A CPU *limit* that held the VM back on LIMIT_MIN_DAYS+ days: no vCPU change helps -> action "limited".
    - Recurring Co-Stop (P95 of daily peaks >= CS_P95_WARN) on a VM with >= 3 vCPUs: it has more vCPUs than
      it can use. If CPU peaks already said "add", adding vCPUs would make it worse -> action "contention";
      otherwise recommend fewer vCPUs (about -25%)."""
    lim_days = sum(1 for d in days_rows if (d.get("lim_n") or 0) > 0)
    cs_vals = [d.get("cs_max_pct") or 0.0 for d in days_rows if (d.get("cs_samples") or 0) > 0]
    out["limited_days"] = lim_days
    out["costop_days"] = len(cs_vals)
    out["costop_p95"] = round(_p95(cs_vals), 1) if cs_vals else None
    if lim_days >= LIMIT_MIN_DAYS:
        out.update(action="limited", recommended=cur, delta=0,
                   reason="הוגדר Limit על ה-CPU של השרת (נחסם ב-%d ימים). להסיר את ה-Limit לפני כל שינוי ב-vCPU" % lim_days)
        return
    if len(cs_vals) >= CS_MIN_DAYS and out["costop_p95"] >= CS_P95_WARN and cur >= 3:
        if out["action"] == "add":
            out.update(action="contention", recommended=cur, delta=0,
                       reason="CPU גבוה אבל גם Co-Stop חוזר (P95 %s%%): יש יותר מדי vCPUs, הוספה תחמיר. לבדוק את עומס ה-host במקום" % out["costop_p95"])
        else:
            rec = max(2, cur - max(1, cur // 4))
            if rec >= 3:
                rec -= rec % 2             # keep an even vCPU count (NUMA friendly)
            if out["action"] == "reduce" and out["recommended"] <= rec:
                out["reason"] = "Co-Stop חוזר (P95 %s%%) מחזק את ההמלצה להפחית vCPUs" % out["costop_p95"]
                return
            if rec < cur:
                out.update(action="reduce", recommended=rec, delta=round(rec - cur, 1),
                           reason="Co-Stop חוזר (P95 %s%%): יותר vCPUs ממה שהשרת מנצל, וזה מאט אותו" % out["costop_p95"])


def _resource(cur, days_rows, key, target, min_days, kind, protect_reason=""):
    """Recommendation for one resource. days_rows = rows recorded at the current size."""
    n = len(days_rows)
    peaks = [r[key] or 0.0 for r in days_rows]
    out = {"days": n, "current": cur, "peak_max": round(max(peaks), 1) if peaks else None,
           "peak_p95": round(_p95(peaks), 1) if peaks else None,
           "recommended": None, "delta": 0, "action": "insufficient"}
    if n < min_days or not cur:
        return out
    p95 = _p95(peaks)
    if kind == "cpu":
        rec = _round_cpu_up(math.ceil(cur * p95 / target), cur)
        if cur >= 2:
            rec = max(rec, 2)          # never recommend dropping a multi-vCPU VM to 1
        if rec < cur and max(peaks) >= 90:
            rec = cur                  # it did touch saturation - don't shrink on a quiet P95 alone
    else:
        rec = _round_mem_up(max(cur * p95 / target, 2.0))
        if rec < cur and max(peaks) >= 95:
            rec = cur
    # Hysteresis: ignore changes smaller than 15% of the current size (and under 1 unit) -
    # a VM sitting near its target isn't worth touching.
    if abs(rec - cur) < max(1, 0.15 * cur):
        rec = cur
    if rec < cur and protect_reason:
        out["would_be"] = rec                  # what the numbers alone would suggest
        out["protected_reason"] = protect_reason
        rec = cur
        out["recommended"] = rec
        out["delta"] = 0
        out["action"] = "protected"
        return out
    out["recommended"] = rec
    out["delta"] = round(rec - cur, 1)
    out["action"] = "add" if rec > cur else ("reduce" if rec < cur else "ok")
    if kind == "cpu":
        _cpu_contention(cur, out, days_rows)
    return out


def get_recommendations(env: Optional[str] = None, **overrides) -> dict:
    cfg = {**DEFAULTS, **{k: v for k, v in overrides.items() if v is not None}}
    rows = _load_rows(int(cfg["days"]), env)
    roles = _load_roles()
    vms: dict = {}
    for r in rows:
        if (r["samples"] or 0) < cfg["min_samples_per_day"]:
            continue                               # VM was mostly off that day
        vms.setdefault((r["environment"], r["vm_name"]), []).append(r)

    out = []
    for (e, name), drs in vms.items():
        last = drs[-1]
        cpu_rows = [d for d in drs if d["num_cpu"] == last["num_cpu"]]    # days at the current size
        mem_rows = [d for d in drs if abs((d["mem_gb"] or 0) - (last["mem_gb"] or 0)) < 0.05]
        cpu = _resource(last["num_cpu"], cpu_rows, "max_cpu_pct", cfg["cpu_target"], cfg["min_days"], "cpu")
        role = roles.get((e.lower(), name), "")
        mem = _resource(last["mem_gb"], mem_rows, "max_mem_pct", cfg["mem_target"], cfg["min_days"], "mem",
                        protect_reason=_protect_reason(name, role))
        days = min(cpu["days"], mem["days"])
        out.append({
            "environment": e, "vm_name": name, "sap_number": last["sap_number"],
            "days": days, "role": role,
            "confidence": "none" if days < cfg["min_days"] else ("medium" if days < 30 else "high"),
            "cpu": cpu, "mem": mem,
        })
    return {"config": cfg, "data": out}
