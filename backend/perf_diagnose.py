"""
Rule-based diagnosis of one VM for the vCenter Performance page ("Analyze server" button).

Deterministic on purpose: it applies the same levels/thresholds the page shows (load meter, Ready meter,
Co-Stop, CPU limit, memory pressure, ESXi host load, disk latency, backup timing) and returns findings with a
recommended action. Every text is provided in English and Hebrew ({"en": ..., "he": ...}) so the UI can
show either; the structured "facts" are also what the AI assistant gets as context to explain the result.

Inputs are plain dicts already produced elsewhere:
  summary : one row of perf_store.get_summary (None if the VM has no data in the range)
  host    : the live ESXi entry from perf_collector.live (None if unknown)
  disks   : result of /api/vcenter/perf/disks (None if unavailable)
  backups : result of /api/vcenter/perf/backups (None if unavailable)
"""

import math
import re
from datetime import datetime, timedelta

# Same idea as the right-sizing protection: database servers keep memory as cache on purpose.
_DB_NAME_RE = re.compile(r"(sql|db|oracle|hana|mysql|maria|postgres|pgsql|mongo|redis|sybase|cache)", re.I)

# Lookup order for sorting / verdicts
_SEV_ORDER = {"crit": 3, "warn": 2, "info": 1, "ok": 0}


def _t(en: str, he: str) -> dict:
    return {"en": en, "he": he}


def _f(sev: str, area: str, title: dict, detail: dict, action: dict = None) -> dict:
    return {"sev": sev, "area": area, "title": title, "detail": detail, "action": action or _t("", "")}


def _pct(a, b) -> float:
    return round((a or 0) * 100.0 / b, 1) if b else 0.0


def _load_level(n, n_mid, n_high, hot, buckets) -> int:
    """Same rule as the page's load meter: -1 no data, 0 ok, 1 one-off, 2 attention, 3 problematic."""
    if not n or n < 30:
        return -1
    sh, sm = n_high * 100.0 / n, n_mid * 100.0 / n
    hp = hot * 100.0 / buckets if buckets else 0
    if sh >= 3 or (hot >= 3 and hp >= 20):
        return 3
    if sm >= 20 or hot >= 2 or sh >= 0.5:
        return 2
    if n_high >= 1:
        return 1
    return 0


def _ready_level(s: dict) -> int:
    """Same rule as the page's Ready meter (sustained, not a single peak)."""
    n = s.get("ready_samples") or 0
    if n < 30:
        return -1
    nw, nc = s.get("ready_n_warn") or 0, s.get("ready_n_crit") or 0
    pw, pc = nw * 100.0 / n, nc * 100.0 / n
    hb, bk = s.get("ready_hot_buckets") or 0, s.get("buckets") or 0
    hp = hb * 100.0 / bk if bk else 0
    if pc > 1 or pw > 5 or (hb >= 3 and hp >= 20):
        return 3
    if pw > 1 or hb >= 2:
        return 2
    if nw >= 1:
        return 1
    return 0


def _parse(ts):
    try:
        return datetime.strptime((ts or "")[:16], "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _near_backup(ts, backups):
    """The backup point (kind 'backup') that started within the ~90 minutes before ts, or None."""
    t = _parse(ts)
    if not t or not backups:
        return None
    for p in backups.get("points") or []:
        if p.get("kind") != "backup":
            continue
        start = _parse(p.get("start") or p.get("time"))
        end = _parse(p.get("end") or p.get("time")) or start
        if start and start - timedelta(minutes=10) <= t <= end + timedelta(minutes=90):
            return p
    return None


def diagnose(env: str, name: str, range_key: str, s: dict, host: dict, disks: dict, backups: dict) -> dict:
    findings = []
    facts = {"vm": name, "environment": env, "range": range_key}

    if not s or (s.get("samples") or 0) < 30:
        findings.append(_f("info", "Data",
                           _t("Not enough data for this VM", "אין מספיק נתונים לשרת הזה"),
                           _t("Less than 30 minutes of samples in the selected range (VM off, new, or collector not running yet).",
                              "פחות מ-30 דקות דגימה בטווח שנבחר (השרת כבוי, חדש, או שהאיסוף עוד לא רץ)."),
                           _t("Choose a longer range or try again later.", "בחר טווח ארוך יותר או נסה מאוחר יותר.")))
        return _result(findings, facts, None)

    n = s["samples"]
    vcpu, ram_gb = s.get("num_cpu"), s.get("mem_gb")
    facts.update({
        "vcpu": vcpu, "ram_gb": ram_gb, "samples_minutes": n,
        "cpu_peak_pct": s.get("max_cpu_pct"), "cpu_peak_at": s.get("max_cpu_ts"), "cpu_avg_pct": round(s.get("avg_cpu_pct") or 0, 1),
        "ram_peak_pct": s.get("max_mem_pct"), "ram_peak_at": s.get("max_mem_ts"), "ram_avg_pct": round(s.get("avg_mem_pct") or 0, 1),
    })
    unit_en = "hours" if range_key == "24h" else "days"
    unit_he = "שעות" if range_key == "24h" else "ימים"
    buckets = s.get("buckets") or 0

    # ---- levels -------------------------------------------------------------------------------
    cpu_lv = _load_level(n, s.get("cpu_n_mid") or 0, s.get("cpu_n_high") or 0, s.get("cpu_hot_buckets") or 0, buckets)
    mem_lv = _load_level(n, s.get("mem_n_mid") or 0, s.get("mem_n_high") or 0, s.get("mem_hot_buckets") or 0, buckets)
    rdy_lv = _ready_level(s)
    cs_n = s.get("cs_samples") or 0
    cs_share = _pct(s.get("cs_n_warn"), cs_n)
    cs_bad = cs_n >= 30 and (s.get("cs_max_pct") or 0) >= 3 and cs_share >= 1
    lim_bad = (s.get("lim_n") or 0) > 0
    swap = (s.get("mp_swap_max_mb") or 0) > 0
    balloon = (s.get("mp_balloon_max_mb") or 0) > 0
    mlat = s.get("mp_lat_max_pct") or 0
    host_bad = bool(host) and host.get("level") in ("warn", "crit", "down")
    # "Busy" = real CPU/RAM load, Ready or swap on the host. A warning caused only by the vCPU:core ratio is a
    # capacity-planning flag, not contention (Ready shows whether VMs actually wait), so it must not be blamed
    # for this VM's CPU.
    host_cpu_busy = bool(host) and (host.get("level") == "down" or (host.get("cpu_pct") or 0) >= 75
                                    or (host.get("ready_avg") or 0) >= 3)
    host_busy = bool(host) and (host.get("level") == "down" or (host.get("cpu_pct") or 0) >= 75
                                or (host.get("ready_avg") or 0) >= 3 or (host.get("mem_pct") or 0) >= 85
                                or bool(host.get("mp_swap_vms")))
    facts.update({
        "cpu_load_level": cpu_lv, "ram_load_level": mem_lv, "ready_level": rdy_lv,
        "cpu_pct_time_ge85": _pct(s.get("cpu_n_high"), n), "ram_pct_time_ge85": _pct(s.get("mem_n_high"), n),
        "ready_peak_pct": s.get("ready_max_pct"), "ready_avg_pct": round(s.get("ready_avg_pct") or 0, 2),
        "ready_pct_time_ge5": _pct(s.get("ready_n_warn"), s.get("ready_samples")),
        "costop_peak_pct": s.get("cs_max_pct"), "costop_pct_time_ge3": cs_share,
        "cpu_limit_minutes": s.get("lim_n") or 0,
        "mem_swap_max_mb": s.get("mp_swap_max_mb"), "mem_balloon_max_mb": s.get("mp_balloon_max_mb"), "mem_latency_max_pct": mlat,
    })
    if host:
        facts["esxi"] = {k: host.get(k) for k in ("name", "level", "cpu_pct", "mem_pct", "ready_avg", "vcpu_ratio", "cores", "vms", "reasons")}
    if disks and disks.get("disks"):
        facts["disks"] = [{k: d.get(k) for k in ("label", "datastore", "read_ms", "write_ms", "read_ms_max", "write_ms_max", "level")}
                          for d in disks["disks"]]

    # ---- CPU ----------------------------------------------------------------------------------
    cpu_answer = _t("No - CPU is not a sustained problem.", "לא - ה-CPU אינו בעיה מתמשכת.")
    if cpu_lv >= 2:
        sev = "crit" if cpu_lv == 3 else "warn"
        title = _t("CPU is %s" % ("saturated" if cpu_lv == 3 else "often high"),
                   "ה-CPU %s" % ("רווי" if cpu_lv == 3 else "גבוה לעיתים קרובות"))
        detail = _t("CPU >=85%% for %s%% of the time (peak %s%% at %s, average %s%%) on %s vCPUs; high load in %s of %s %s." % (
                        _pct(s.get("cpu_n_high"), n), s.get("max_cpu_pct"), s.get("max_cpu_ts"), round(s.get("avg_cpu_pct") or 0, 1),
                        vcpu, s.get("cpu_hot_buckets") or 0, buckets, unit_en),
                    "CPU מעל 85%% במשך %s%% מהזמן (שיא %s%% ב-%s, ממוצע %s%%) על %s vCPUs; עומס גבוה ב-%s מתוך %s %s." % (
                        _pct(s.get("cpu_n_high"), n), s.get("max_cpu_pct"), s.get("max_cpu_ts"), round(s.get("avg_cpu_pct") or 0, 1),
                        vcpu, s.get("cpu_hot_buckets") or 0, buckets, unit_he))
        if lim_bad:
            act = _t("A CPU limit is holding the VM back - remove it first (see 'CPU limit' below). More vCPUs will not help.",
                     "יש Limit על ה-CPU שחוסם את השרת - להסיר אותו קודם (ראה 'CPU Limit' למטה). מעבדים נוספים לא יעזרו.")
            cpu_answer = _t("No - remove the CPU limit first.", "לא - להסיר קודם את ה-Limit על ה-CPU.")
        elif cs_bad:
            act = _t("Recurring Co-Stop means too many vCPUs: reduce vCPUs (start with 1-2) instead of adding.",
                     "Co-Stop חוזר מעיד על יותר מדי vCPUs: להפחית vCPUs (להתחיל ב-1-2) ולא להוסיף.")
            cpu_answer = _t("No - it already has too many vCPUs (Co-Stop).", "לא - יש לו כבר יותר מדי vCPUs (Co-Stop).")
        elif rdy_lv >= 2 or host_cpu_busy:
            act = _t("The VM waits for physical CPU (Ready / busy host): move it to a quieter host (vMotion) or relieve the host. Do not add vCPUs.",
                     "השרת מחכה למעבד פיזי (Ready / host עמוס): להעביר ל-host שקט יותר (vMotion) או לפנות את ה-host. לא להוסיף vCPUs.")
            cpu_answer = _t("No - the cause is host contention, not VM size.", "לא - הסיבה היא עומס על ה-host ולא גודל השרת.")
        else:
            act = _t("No contention on the hypervisor side, so the VM itself is using all its CPU. Inside the guest find the process "
                     "(Task Manager/top; for IIS the w3wp app pool) and the hours it happens. If the load is legitimate and multi-threaded "
                     "consider scaling out or adding vCPUs carefully; a sudden step to 100% usually points to one runaway process or a job.",
                     "אין תחרות מצד ה-hypervisor, כלומר השרת עצמו מנצל את כל ה-CPU. בתוך השרת למצוא את התהליך (Task Manager/top; ב-IIS ה-App Pool של w3wp) "
                     "ואת השעות. אם העומס לגיטימי ומרובה threads לשקול scale-out או תוספת vCPUs בזהירות; קפיצה חדה ל-100% מעידה בדרך כלל על תהליך תקוע או משימה.")
            cpu_answer = _t("Maybe - only if the load is legitimate; first find the cause inside the server.",
                            "אולי - רק אם העומס לגיטימי; קודם לאתר את הסיבה בתוך השרת.")
            if (s.get("avg_cpu_pct") or 0) >= 50:
                avg = s.get("avg_cpu_pct") or 0
                need = min(int(vcpu or 2) * 2, max(int(vcpu or 2) + 1, int(math.ceil((vcpu or 2) * avg / 55.0))))
                if need >= 4:
                    need += need % 2
                room_en = " The host has CPU headroom (CPU %s%%, Ready %s%%)." % (host.get("cpu_pct"), host.get("ready_avg")) if host and not host_cpu_busy else ""
                room_he = " ל-host יש מקום ב-CPU (CPU %s%%, Ready %s%%)." % (host.get("cpu_pct"), host.get("ready_avg")) if host and not host_cpu_busy else ""
                act = _t("The VM keeps a high CPU average (%s%% on %s vCPUs) with no contention (Ready, Co-Stop and the host are fine), so it genuinely "
                         "needs more CPU or its workload is heavy. For a database/application server first check the top CPU consumers inside it "
                         "(heaviest queries, missing indexes, scheduled jobs). If the load is legitimate add vCPUs in small steps (about %s vCPUs as a "
                         "first step) and re-check after a few days.%s" % (round(avg, 1), vcpu, need, room_en),
                         "לשרת ממוצע CPU גבוה (%s%% על %s vCPUs) ללא תחרות (Ready, Co-Stop וה-host תקינים), כלומר הוא באמת צריך יותר CPU או שהעומס כבד. "
                         "בשרת DB/אפליקציה קודם לבדוק מה צורך הכי הרבה CPU בתוכו (שאילתות כבדות, אינדקסים חסרים, משימות מתוזמנות). "
                         "אם העומס לגיטימי - להוסיף vCPUs בצעדים קטנים (כ-%s vCPUs כצעד ראשון) ולבדוק שוב אחרי כמה ימים.%s" % (round(avg, 1), vcpu, need, room_he))
                cpu_answer = _t("Yes, probably - sustained high CPU (average %s%%) with no contention. Check the heaviest workload first, then add vCPUs "
                                "in small steps (about %s)." % (round(avg, 1), need),
                                "כנראה כן - CPU גבוה באופן מתמשך (ממוצע %s%%) ללא תחרות. קודם לבדוק מה העומס הכבד, ואז להוסיף vCPUs בצעדים קטנים (כ-%s)." % (round(avg, 1), need))
            elif (vcpu or 0) >= 16 and (s.get("avg_cpu_pct") or 0) < 30:
                act = _t(act["en"] + " Note: average CPU is low for %s vCPUs - spiky load, not a capacity shortage." % vcpu,
                         act["he"] + " שים לב: ממוצע ה-CPU נמוך ביחס ל-%s vCPUs - עומס קופצני, לא חוסר קיבולת." % vcpu)
                cpu_answer = _t("Probably not - 100% bursts on an otherwise idle VM point to a runaway process or job.",
                                "כנראה שלא - קפיצות ל-100% בשרת שברוב הזמן פנוי מעידות על תהליך תקוע או משימה.")
            elif _pct(s.get("cpu_n_high"), n) >= 5:
                share = _pct(s.get("cpu_n_high"), n)
                room_en = " The host has CPU headroom (CPU %s%%)." % host.get("cpu_pct") if host and not host_cpu_busy else ""
                room_he = " ל-host יש מקום ב-CPU (CPU %s%%)." % host.get("cpu_pct") if host and not host_cpu_busy else ""
                big = (vcpu or 0) >= 16
                numa_en = " (a VM with this many vCPUs may already span NUMA nodes, so more vCPUs can add Co-Stop)" if big else ""
                numa_he = " (לשרת עם כל כך הרבה vCPUs ייתכן שכבר יש פריסה על כמה צמתי NUMA, ותוספת עלולה להגדיל Co-Stop)" if big else ""
                act = _t("Bursty load: the average is only %s%% but the VM is at >=85%% for %s%% of the time, with no contention (Ready, Co-Stop and the host CPU are fine). "
                         "This looks like batch / ETL / reporting jobs that use all vCPUs for a while. First check whether the bursts hurt (jobs overrun their window, "
                         "users complain). If not, no change is needed. If they do, more vCPUs can shorten the bursts only when the work is parallel; add in small steps "
                         "(a few at a time)%s, or move/spread the heavy jobs.%s" % (round(s.get("avg_cpu_pct") or 0, 1), share, numa_en, room_en),
                         "עומס קופצני: הממוצע רק %s%% אבל השרת מעל 85%% במשך %s%% מהזמן, ללא תחרות (Ready, Co-Stop וה-CPU של ה-host תקינים). "
                         "נראה כמו משימות batch / ETL / דוחות שמנצלות את כל ה-vCPUs לזמן מה. קודם לבדוק אם הקפיצות פוגעות (משימות חורגות מהחלון, "
                         "תלונות משתמשים). אם לא - אין צורך בשינוי. אם כן - תוספת vCPUs מקצרת את הקפיצות רק אם העבודה מקבילית; להוסיף בצעדים קטנים "
                         "(כמה בכל פעם)%s, או להזיז/לפזר את המשימות הכבדות.%s" % (round(s.get("avg_cpu_pct") or 0, 1), share, numa_he, room_he))
                cpu_answer = _t("Not necessarily - the load is bursty (average %s%%). Only if the bursts hurt (jobs overrun, users complain); then add vCPUs in small steps." % round(s.get("avg_cpu_pct") or 0, 1),
                                "לא בהכרח - העומס קופצני (ממוצע %s%%). רק אם הקפיצות פוגעות (משימות חורגות, תלונות משתמשים); אז להוסיף vCPUs בצעדים קטנים." % round(s.get("avg_cpu_pct") or 0, 1))
        findings.append(_f(sev, "CPU", title, detail, act))
    elif cpu_lv == 1:
        findings.append(_f("info", "CPU", _t("CPU: one-off peak", "CPU: פיק חד-פעמי"),
                           _t("Touched high CPU (peak %s%% at %s) but not repeatedly." % (s.get("max_cpu_pct"), s.get("max_cpu_ts")),
                              "נגע בעומס CPU גבוה (שיא %s%% ב-%s) אך לא באופן חוזר." % (s.get("max_cpu_pct"), s.get("max_cpu_ts"))),
                           _t("No action; keep an eye on it.", "אין צורך בפעולה; לעקוב.")))

    # ---- Ready / Co-Stop / Limit -----------------------------------------------------------------
    if rdy_lv >= 2:
        findings.append(_f("crit" if rdy_lv == 3 else "warn", "CPU Ready",
                           _t("The VM waits for physical CPU (Ready)", "השרת ממתין למעבד פיזי (Ready)"),
                           _t("CPU Ready >=5%% for %s%% of the time (>=10%% for %s%%), peak %s%%, in %s of %s %s." % (
                                  _pct(s.get("ready_n_warn"), s.get("ready_samples")), _pct(s.get("ready_n_crit"), s.get("ready_samples")),
                                  s.get("ready_max_pct"), s.get("ready_hot_buckets") or 0, buckets, unit_en),
                              "CPU Ready מעל 5%% במשך %s%% מהזמן (מעל 10%% במשך %s%%), שיא %s%%, ב-%s מתוך %s %s." % (
                                  _pct(s.get("ready_n_warn"), s.get("ready_samples")), _pct(s.get("ready_n_crit"), s.get("ready_samples")),
                                  s.get("ready_max_pct"), s.get("ready_hot_buckets") or 0, buckets, unit_he)),
                           _t("Check the ESXi card: if the host is busy, vMotion the VM to a quieter host or move noisy neighbours away. Do not add vCPUs.",
                              "לבדוק את כרטיס ה-ESXi: אם ה-host עמוס, להעביר את השרת (vMotion) ל-host שקט או להרחיק שכנים רועשים. לא להוסיף vCPUs.")))
    if cs_bad:
        findings.append(_f("warn", "Co-Stop",
                           _t("Too many vCPUs (Co-Stop)", "יותר מדי vCPUs (Co-Stop)"),
                           _t("Co-Stop >=3%% for %s%% of the time, peak %s%% - the vCPUs wait for each other to be scheduled." % (cs_share, s.get("cs_max_pct")),
                              "Co-Stop מעל 3%% במשך %s%% מהזמן, שיא %s%% - ה-vCPUs ממתינים זה לזה." % (cs_share, s.get("cs_max_pct"))),
                           _t("Reduce vCPUs (start with 1-2) and re-check after a few days; this usually improves performance.",
                              "להפחית vCPUs (להתחיל ב-1-2) ולבדוק שוב אחרי כמה ימים; בדרך כלל זה משפר ביצועים.")))
    if lim_bad:
        findings.append(_f("crit", "CPU limit",
                           _t("A CPU limit is throttling the VM", "Limit על ה-CPU חונק את השרת"),
                           _t("The VM was held back by a configured CPU limit for %s minutes (up to %s%%)." % (s.get("lim_n"), s.get("lim_max_pct")),
                              "השרת נחסם על ידי Limit שהוגדר ל-CPU במשך %s דקות (עד %s%%)." % (s.get("lim_n"), s.get("lim_max_pct"))),
                           _t("In vCenter: Edit Settings > CPU > Limit = Unlimited. Also check the Resource Pool limit.",
                              "ב-vCenter: Edit Settings ← CPU ← Limit = Unlimited. לבדוק גם Limit על ה-Resource Pool.")))

    # ---- Memory ----------------------------------------------------------------------------------
    is_db = bool(_DB_NAME_RE.search(name or ""))
    if swap or balloon or mlat >= 1:
        sev = "crit" if (swap or mlat >= 5) else "warn"
        findings.append(_f(sev, "Memory pressure",
                           _t("The host is squeezing this VM's memory", "ה-host מצר את הזיכרון של השרת"),
                           _t("Swap max %s MB (%s min), balloon max %s MB (%s min), memory latency max %s%%." % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0, s.get("mp_balloon_max_mb"), s.get("mp_n_balloon") or 0, mlat),
                              "swap מקס' %s MB (%s דק'), balloon מקס' %s MB (%s דק'), Memory Latency מקס' %s%%." % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0, s.get("mp_balloon_max_mb"), s.get("mp_n_balloon") or 0, mlat)),
                           _t("First check whether the VM has a Memory Limit in vCenter (it causes balloon/swap even on a free host) and remove it. "
                              "Otherwise the ESXi itself is short of memory: see the ESXi card, move VMs away or add host memory.",
                              "קודם לבדוק אם הוגדר ל-VM Memory Limit ב-vCenter (גורם ל-balloon/swap גם ב-host פנוי) ולהסיר. "
                              "אחרת ל-ESXi עצמו חסר זיכרון: לראות את כרטיס ה-ESXi, להעביר שרתים או להוסיף זיכרון ל-host.")))
    if mem_lv >= 2:
        db_en = " This looks like a database/cache server: they keep memory as cache on purpose, so high RAM is normal and the number cannot tell whether more RAM is needed (check Page Life Expectancy / paging inside the guest)." if is_db else ""
        db_he = " נראה שזה שרת DB/Cache: שרתים כאלה מחזיקים זיכרון כ-cache בכוונה, ולכן RAM גבוה תקין והמספר לא אומר אם צריך עוד (לבדוק Page Life Expectancy / paging בתוך השרת)." if is_db else ""
        has_press = swap or balloon or mlat >= 1
        findings.append(_f("info" if is_db else ("warn" if not has_press else "warn"), "Memory",
                           _t("Guest memory usage is high", "ניצול הזיכרון בשרת גבוה"),
                           _t("Active RAM >=85%% for %s%% of the time (peak %s%% at %s) of %s GB.%s" % (
                                  _pct(s.get("mem_n_high"), n), s.get("max_mem_pct"), s.get("max_mem_ts"), ram_gb, db_en),
                              "RAM פעיל מעל 85%% במשך %s%% מהזמן (שיא %s%% ב-%s) מתוך %s GB.%s" % (
                                  _pct(s.get("mem_n_high"), n), s.get("max_mem_pct"), s.get("max_mem_ts"), ram_gb, db_he)),
                           _t("Active memory is a sampled estimate. Check pagefile/swap use inside the guest at the peak time; if it pages heavily, add RAM. "
                              "No host-side starvation was seen." if not has_press else "Host-side memory pressure is present too (see above).",
                              "זיכרון פעיל הוא הערכה מדגימה. לבדוק שימוש ב-pagefile/swap בתוך השרת בזמן השיא; אם יש paging כבד - להוסיף RAM. "
                              "לא נראתה מצוקת זיכרון מצד ה-host." if not has_press else "יש גם לחץ זיכרון מצד ה-host (ראה למעלה).")))

    # ---- ESXi host -------------------------------------------------------------------------------
    if host is None:
        findings.append(_f("info", "ESXi", _t("No live ESXi data", "אין נתון חי על ה-ESXi"),
                           _t("The host could not be determined (VM off, or the collector just restarted).", "לא ניתן לקבוע את ה-host (השרת כבוי, או שהאיסוף הופעל מחדש לאחרונה)."),
                           _t("Try again in a minute.", "לנסות שוב בעוד דקה.")))
    elif host_bad:
        findings.append(_f(("crit" if host.get("level") in ("crit", "down") else "warn") if host_busy else "info", "ESXi",
                           _t("The ESXi host %s is under load" % host.get("name"), "ה-ESXi %s תחת עומס" % host.get("name")),
                           _t("%s. CPU %s%%, RAM %s%%, %s VMs, vCPU:core %s:1." % ("; ".join(host.get("reasons") or []), host.get("cpu_pct"), host.get("mem_pct"), host.get("vms"), host.get("vcpu_ratio")),
                              "%s. CPU %s%%, RAM %s%%, %s שרתים, יחס vCPU:ליבה %s:1." % ("; ".join(host.get("reasons") or []), host.get("cpu_pct"), host.get("mem_pct"), host.get("vms"), host.get("vcpu_ratio"))),
                           _t("Rebalance: vMotion busy VMs to quieter hosts (check DRS). Top consumers on this host: %s." % ", ".join(
                                  "%s %s%%" % (t.get("name"), t.get("cpu_pct")) for t in (host.get("top_vms") or [])),
                              "לאזן: vMotion של שרתים עמוסים ל-hosts שקטים (לבדוק DRS). הצרכנים הגדולים על ה-host: %s." % ", ".join(
                                  "%s %s%%" % (t.get("name"), t.get("cpu_pct")) for t in (host.get("top_vms") or [])))))
        if not host_busy:
            fnd = findings[-1]
            fnd["title"] = _t("ESXi %s: high vCPU:core ratio (no contention in practice)" % host.get("name"),
                              "ESXi %s: יחס vCPU:ליבה גבוה (ללא תחרות בפועל)" % host.get("name"))
            fnd["detail"] = _t(fnd["detail"]["en"] + " Note: the host's CPU, RAM and Ready are low, so this is a capacity-planning flag (vCPU:core ratio) and not the cause of this VM's problem.",
                               fnd["detail"]["he"] + " שים לב: ה-CPU, ה-RAM וה-Ready של ה-host נמוכים, ולכן זו התראת תכנון קיבולת (יחס vCPU:ליבה) ולא הסיבה לבעיה בשרת הזה.")

    # ---- Disks -----------------------------------------------------------------------------------
    if disks and disks.get("disks"):
        bad = [d for d in disks["disks"] if d.get("level") in ("warn", "crit")]
        if bad:
            worst = max(bad, key=lambda d: max(d.get("read_ms") or 0, d.get("write_ms") or 0))
            findings.append(_f("crit" if any(d.get("level") == "crit" for d in bad) else "warn", "Disk",
                               _t("High disk latency", "לייטנסי דיסק גבוה"),
                               _t("%s on %s: read %s ms, write %s ms (as seen by the ESXi, last 5 minutes)." % (
                                      worst.get("label"), worst.get("datastore"), worst.get("read_ms"), worst.get("write_ms")),
                                  "%s על %s: Read %s ms, Write %s ms (כפי שה-ESXi רואה, 5 דקות אחרונות)." % (
                                      worst.get("label"), worst.get("datastore"), worst.get("read_ms"), worst.get("write_ms"))),
                               _t("Compare with other VMs on the same datastore (all slow = storage/fabric, only this VM = the VM). "
                                  "Check for open snapshots on the VM, backup running now, and the iBox load.",
                                  "להשוות לשרתים אחרים על אותו datastore (כולם איטיים = אחסון/רשת, רק הוא = השרת עצמו). "
                                  "לבדוק Snapshots פתוחים, גיבוי שרץ כרגע, ועומס ב-iBox.")))
    elif disks is None:
        findings.append(_f("info", "Disk", _t("Disk latency not available", "לייטנסי דיסק לא זמין"),
                           _t("The live disk query did not answer (VM off or vCenter slow).", "שאילתת הדיסקים החיה לא ענתה (השרת כבוי או vCenter איטי)."),
                           _t("Try again.", "לנסות שוב.")))

    # ---- Backup correlation ----------------------------------------------------------------------
    if backups and (backups.get("points") is not None):
        hits = []
        for label, ts in (("CPU peak", s.get("max_cpu_ts")), ("RAM peak", s.get("max_mem_ts")),
                          ("Ready peak", s.get("ready_max_ts")), ("Co-Stop peak", s.get("cs_max_ts"))):
            p = _near_backup(ts, backups)
            if p:
                hits.append((label, ts, p))
        if hits:
            label, ts, p = hits[0]
            findings.append(_f("info", "Backup",
                               _t("A peak coincides with a backup", "פיק מתיישר עם גיבוי"),
                               _t("The %s (%s) falls shortly after a %s backup (%s, job '%s')." % (label, ts, p.get("server"), p.get("time"), p.get("job")),
                                  "ה-%s (%s) נופל זמן קצר אחרי גיבוי %s (%s, job '%s')." % (label, ts, p.get("server"), p.get("time"), p.get("job"))),
                               _t("Consider moving the backup window, throttling it in Veeam, or spreading heavy VMs across different times.",
                                  "לשקול להזיז את חלון הגיבוי, להגביל אותו ב-Veeam, או לפזר שרתים כבדים לזמנים שונים.")))
        nb = len([p for p in backups.get("points") or [] if p.get("kind") == "backup"])
        facts["backups_in_range"] = nb
        if nb == 0:
            findings.append(_f("info", "Backup", _t("No backup found in the range", "לא נמצא גיבוי בטווח"),
                               _t("No Veeam backup point for this VM in the selected range (may be backed up weekly, by another tool, or under a different name).",
                                  "לא נמצאה נקודת גיבוי של Veeam לשרת בטווח שנבחר (ייתכן שהגיבוי שבועי, בכלי אחר, או בשם אחר)."),
                               _t("Use a longer range to confirm.", "לבדוק בטווח ארוך יותר.")))

    return _result(findings, facts, cpu_answer)


def _result(findings: list, facts: dict, cpu_answer) -> dict:
    findings.sort(key=lambda f: -_SEV_ORDER[f["sev"]])
    top = findings[0]["sev"] if findings else "ok"
    real = [f for f in findings if f["sev"] in ("crit", "warn")]
    if real:
        verdict = _t("Needs attention (%d issue%s). Most important: %s" % (len(real), "" if len(real) == 1 else "s", real[0]["title"]["en"]),
                     "דורש תשומת לב (%d ממצאים). החשוב ביותר: %s" % (len(real), real[0]["title"]["he"]))
        level = real[0]["sev"]
    elif top == "info" and findings and findings[0]["area"] == "Data":
        verdict, level = findings[0]["title"], "info"
    else:
        verdict = _t("No resource problem found on the hypervisor side. If users still report slowness, look inside the guest (application, OS, network).",
                     "לא נמצאה בעיית משאבים מצד ה-hypervisor. אם עדיין יש תלונות על איטיות, לבדוק בתוך השרת (אפליקציה, מערכת הפעלה, רשת).")
        level = "ok"
    out = {"verdict": verdict, "level": level, "findings": findings, "facts": facts}
    if cpu_answer:
        out["cpu_answer"] = cpu_answer
    return out
