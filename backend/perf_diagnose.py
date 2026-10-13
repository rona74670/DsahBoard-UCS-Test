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
_DB_NAME_RE = re.compile(r"(sql|db|oracle|hana|mysql|maria|postgres|pgsql|mongo|redis|sybase|cache|(^|[^a-z])dc[0-9]*([^a-z]|$))", re.I)

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
    if sh >= 3:
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


def _recent_saturation(series):
    """(hours, since_bucket, avg_cpu, cs_peak, ready_peak) when the VM's hourly average CPU has been high (>= 75%) for most of the
    hours ending right now: at least 3 hours, the latest bucket no older than 3 hours, and a single dip hour (60-75%) inside the
    run does not break it. None otherwise. The 7-day figures dilute such a run."""
    if not series:
        return None
    rows = [r for r in series if (r.get("samples") or 0) >= 20]
    if not rows:
        return None
    try:
        last = datetime.strptime(rows[-1]["bucket"][:13], "%Y-%m-%d %H")
    except Exception:
        return None
    if datetime.now() - last > timedelta(hours=3):
        return None
    avg = [(r.get("avg_cpu_pct") or 0) for r in rows]
    if avg[-1] < 75:
        return None
    i = len(rows) - 1
    start = i
    while i >= 0:
        if avg[i] >= 75:
            start = i
            i -= 1
        elif avg[i] >= 60 and i - 1 >= 0 and avg[i - 1] >= 75:     # one dip hour inside the run
            i -= 1
        else:
            break
    run = rows[start:]
    if len(run) < 3:
        return None
    return (len(run), run[0]["bucket"], sum((r.get("avg_cpu_pct") or 0) for r in run) / len(run),
            max(r.get("cs_max_pct") or 0 for r in run), max(r.get("ready_max_pct") or 0 for r in run))


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


def diagnose(env: str, name: str, range_key: str, s: dict, host: dict, disks: dict, backups: dict, vm_cfg=None, series=None, events=None) -> dict:
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
    # A few MB of static swap is a leftover (swapped pages stay swapped until touched), not pressure.
    swap_min = max(50.0, 0.005 * (ram_gb or 0) * 1024.0)
    swap = (s.get("mp_swap_max_mb") or 0) >= swap_min
    swap_tiny = 0 < (s.get("mp_swap_max_mb") or 0) < swap_min
    balloon = (s.get("mp_balloon_max_mb") or 0) > 0
    mlat = s.get("mp_lat_max_pct") or 0
    host_bad = bool(host) and host.get("level") in ("warn", "crit", "down")
    # "Busy" = real CPU/RAM load, Ready or swap on the host. A warning caused only by the vCPU:core ratio is a
    # capacity-planning flag, not contention (Ready shows whether VMs actually wait), so it must not be blamed
    # for this VM's CPU.
    host_cpu_busy = bool(host) and (host.get("level") == "down" or (host.get("cpu_pct") or 0) >= 75
                                    or (host.get("ready_avg") or 0) >= 3)
    # A busy host CPU is not contention: contention means VMs wait for a core, which shows as Ready. A host can run at 80%
    # with ~0% Ready (nobody waits). So the host is blamed for this VM's CPU only when Ready says so.
    host_contended = bool(host) and (host.get("level") == "down" or (host.get("ready_avg") or 0) >= 3
                                     or ((host.get("cpu_pct") or 0) >= 90 and (s.get("ready_max_pct") or 0) >= 5))
    host_busy = bool(host) and (host.get("level") == "down" or (host.get("cpu_pct") or 0) >= 75
                                or (host.get("ready_avg") or 0) >= 3 or (host.get("mem_pct") or 0) >= 85)
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
    avg_cpu = s.get("avg_cpu_pct") or 0
    share_hi = _pct(s.get("cpu_n_high"), n)
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
        elif rdy_lv >= 2 or host_contended:
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
            if avg_cpu >= 90 and share_hi >= 80:
                sev = "crit"
                title = _t("CPU is pegged at 100%", "ה-CPU תקוע על 100%")
                act = _t("The VM sits at about 100%% CPU almost all the time (average %s%%, >=85%% for %s%% of the time) with no contention. That is not a normal "
                         "workload: look for a stuck or looping process or a service in a retry loop (Task Manager/top, application logs). A restored or cloned VM "
                         "may also be running a duplicate job. Add vCPUs only if the load is proven legitimate." % (round(avg_cpu, 1), share_hi),
                         "השרת כמעט כל הזמן על כ-100%% CPU (ממוצע %s%%, מעל 85%% במשך %s%% מהזמן) ללא תחרות. זה לא עומס עבודה רגיל: לחפש תהליך תקוע או בלולאה, "
                         "או שירות שנתקע ב-retry (Task Manager/top, לוגים של האפליקציה). שרת ששוחזר/שוכפל עלול להריץ גם משימה כפולה. "
                         "להוסיף vCPUs רק אם הוכח שהעומס לגיטימי." % (round(avg_cpu, 1), share_hi))
                cpu_answer = _t("No - first find out why it is pegged at 100% (likely a stuck process); more vCPUs may just feed it.",
                                "לא - קודם להבין למה הוא תקוע על 100% (כנראה תהליך תקוע); תוספת vCPUs רק תזין אותו.")
            elif avg_cpu >= 60 or (avg_cpu >= 50 and share_hi >= 10):
                sev = "crit" if (avg_cpu >= 70 or share_hi >= 20) else "warn"
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
            elif share_hi >= 3:
                sev = "warn"
                title = _t("Bursty high CPU load", "עומס CPU גבוה וקופצני")
                share = _pct(s.get("cpu_n_high"), n)
                room_en = " The host has CPU headroom (CPU %s%%)." % host.get("cpu_pct") if host and not host_cpu_busy else ""
                room_he = " ל-host יש מקום ב-CPU (CPU %s%%)." % host.get("cpu_pct") if host and not host_cpu_busy else ""
                # a VM wider than one physical socket (assumed: half the host's cores) spans NUMA nodes
                node_cores = int((host.get("cores") or 0) // 2) if host and host.get("cores") else 24
                big = (vcpu or 0) > node_cores
                numa_en = (" (%s vCPUs is more than one physical socket (about %s cores), so the VM spans NUMA nodes and adding vCPUs can add Co-Stop)" % (vcpu, node_cores)) if big else ""
                numa_he = (" (%s vCPUs זה יותר מסוקט פיזי אחד (כ-%s ליבות), ולכן השרת פרוס על כמה צמתי NUMA ותוספת vCPUs עלולה להגדיל Co-Stop)" % (vcpu, node_cores)) if big else ""
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
                if (s.get("cs_max_pct") or 0) >= 3 and (vcpu or 0) >= 16:
                    cs_pk, cs_ts = s.get("cs_max_pct"), s.get("cs_max_ts")
                    act = _t(act["en"] + " Note: Co-Stop reached %s%% (at %s) during a burst. With this many vCPUs a VM needs all its cores free at once, so adding more vCPUs would likely make it worse: prefer moving/spreading the heavy jobs or scaling out." % (cs_pk, cs_ts),
                             act["he"] + " שים לב: Co-Stop הגיע ל-%s%% (ב-%s) בזמן קפיצה. לשרת עם כל כך הרבה vCPUs צריך שכל הליבות יתפנו בו-זמנית, ולכן תוספת vCPUs כנראה תחמיר: עדיף להזיז/לפזר את המשימות הכבדות או לעשות scale-out." % (cs_pk, cs_ts))
                    cpu_answer = _t("Probably not - the load is bursty (average %s%%) and Co-Stop reached %s%% during a burst, so more vCPUs would likely hurt." % (round(s.get("avg_cpu_pct") or 0, 1), cs_pk),
                                    "כנראה שלא - העומס קופצני (ממוצע %s%%) ו-Co-Stop הגיע ל-%s%% בזמן קפיצה, ולכן תוספת vCPUs כנראה תזיק." % (round(s.get("avg_cpu_pct") or 0, 1), cs_pk))
            else:
                # short recurring bursts: >=85% for under 3% of the time, but on several days/hours (a nightly job, a scan)
                sev = "info"
                unit1_en, unit1_he = ("hour", "שעה") if range_key == "24h" else ("day", "יום")
                per_bucket = int(round((s.get("cpu_n_high") or 0) / float(buckets or 1)))
                title = _t("Short recurring CPU bursts", "קפיצות CPU קצרות וחוזרות")
                detail = _t("CPU >=85%% for only %s%% of the time (about %s min per %s) but on %s of %s %s; peak %s%% at %s, average %s%%, %s vCPUs." % (
                                share_hi, per_bucket, unit1_en, s.get("cpu_hot_buckets") or 0, buckets, unit_en, s.get("max_cpu_pct"), s.get("max_cpu_ts"), round(avg_cpu, 1), vcpu),
                            "CPU מעל 85%% רק %s%% מהזמן (כ-%s דקות ל%s) אבל ב-%s מתוך %s %s; שיא %s%% ב-%s, ממוצע %s%%, %s vCPUs." % (
                                share_hi, per_bucket, unit1_he, s.get("cpu_hot_buckets") or 0, buckets, unit_he, s.get("max_cpu_pct"), s.get("max_cpu_ts"), round(avg_cpu, 1), vcpu))
                act = _t("Looks like a scheduled job (backup, antivirus scan, report, batch) that runs at about the same time. This is not a sizing problem: find the job "
                         "from the peak time (%s) and decide whether it can be moved. No change to vCPUs is needed." % s.get("max_cpu_ts"),
                         "נראה כמו משימה מתוזמנת (גיבוי, סריקת אנטי-וירוס, דוח, batch) שרצה בערך באותה שעה. זו לא בעיית גודל: לאתר את המשימה לפי זמן השיא (%s) "
                         "ולהחליט אם אפשר להזיז אותה. אין צורך לשנות vCPUs." % s.get("max_cpu_ts"))
                cpu_answer = _t("No - short scheduled bursts, not a capacity problem.", "לא - קפיצות קצרות ומתוזמנות, לא בעיית קיבולת.")
        findings.append(_f(sev, "CPU", title, detail, act))
    elif cpu_lv == 1:
        findings.append(_f("info", "CPU", _t("CPU: one-off peak", "CPU: פיק חד-פעמי"),
                           _t("Touched high CPU (peak %s%% at %s) but not repeatedly." % (s.get("max_cpu_pct"), s.get("max_cpu_ts")),
                              "נגע בעומס CPU גבוה (שיא %s%% ב-%s) אך לא באופן חוזר." % (s.get("max_cpu_pct"), s.get("max_cpu_ts"))),
                           _t("No action; keep an eye on it.", "אין צורך בפעולה; לעקוב.")))

    # ---- What is happening NOW: a saturated run that ends at the latest hours ------------------------
    run = _recent_saturation(series)
    if run:
        hrs, since_b, run_avg, run_cs, run_rdy = run
        facts["saturated_hours_now"] = hrs
        findings.append(_f("crit" if hrs >= 3 else "warn", "CPU now",
                           _t("CPU has been saturated for %s%s hours" % ("at least " if hrs >= 47 else "the last ", 48 if hrs >= 47 else hrs),
                              "ה-CPU רווי %s%s שעות" % ("לפחות " if hrs >= 47 else "ב-", 48 if hrs >= 47 else hrs)),
                           _t("Hourly average CPU mostly >=75%% over the last %s hours up to now (since %s, average %s%%); in that period Ready peaked at %s%% and Co-Stop at %s%%. "
                              "The 7-day figures above dilute this." % (hrs, since_b, round(run_avg, 1), round(run_rdy, 1), round(run_cs, 1)),
                              "ממוצע ה-CPU השעתי בעיקר מעל 75%% ב-%s השעות האחרונות עד עכשיו (מ-%s, ממוצע %s%%); בתקופה הזו Ready הגיע ל-%s%% ו-Co-Stop ל-%s%%. "
                              "נתוני 7 הימים למעלה מטשטשים את זה." % (hrs, since_b, round(run_avg, 1), round(run_rdy, 1), round(run_cs, 1))),
                           _t("It is happening now: look inside the guest at what started at about %s (a stuck process, or a job that did not finish). %s" % (
                                  since_b[11:16], "Ready/Co-Stop stayed low, so it is the VM's own load, not the host." if run_rdy < 5 and run_cs < 3 else
                                  "Ready/Co-Stop were high at times, so also check the host (see the ESXi card)."),
                              "זה קורה עכשיו: לבדוק בתוך השרת מה התחיל בערך ב-%s (תהליך תקוע, או משימה שלא הסתיימה). %s" % (
                                  since_b[11:16], "Ready/Co-Stop נשארו נמוכים, ולכן זה העומס של השרת עצמו ולא ה-host." if run_rdy < 5 and run_cs < 3 else
                                  "Ready/Co-Stop היו גבוהים לעיתים, ולכן לבדוק גם את ה-host (כרטיס ה-ESXi)."))))
        if cpu_answer["en"].startswith("Yes"):
            cpu_answer = _t(cpu_answer["en"] + " It is also saturated right now.", cpu_answer["he"] + " והוא גם רווי עכשיו.")
        else:
            hrs_en = "at least 48 hours" if hrs >= 47 else "the last %s hours" % hrs
            hrs_he = "לפחות 48 שעות" if hrs >= 47 else "%s שעות" % hrs
            cpu_answer = _t("No - the VM has been saturated for %s; first find out what is running now (it may be a stuck process)." % hrs_en,
                            "לא - השרת רווי %s; קודם לברר מה רץ עכשיו (אולי תהליך תקוע)." % hrs_he)

    # ---- Ready / Co-Stop / Limit -----------------------------------------------------------------
    spike_rdy, spike_cs = (s.get("ready_max_pct") or 0), (s.get("cs_max_pct") or 0)
    if (spike_rdy >= 10 or spike_cs >= 10) and rdy_lv < 2 and not cs_bad:
        many = (s.get("ready_n_crit") or 0) >= 3
        findings.append(_f("warn" if many else "info", "Contention spike",
                           _t("A severe, short contention spike", "קפיצת תחרות חמורה וקצרה"),
                           _t("In a single minute CPU Ready peaked at %s%% (at %s) and Co-Stop at %s%% (at %s) - far above the 5%% / 3%% warning levels - but it did not repeat enough to count as a sustained problem." % (
                                  round(spike_rdy, 1), s.get("ready_max_ts"), round(spike_cs, 1), s.get("cs_max_ts")),
                              "בדקה אחת CPU Ready הגיע ל-%s%% (ב-%s) ו-Co-Stop ל-%s%% (ב-%s), הרבה מעל רמות האזהרה (5%% / 3%%), אבל זה לא חזר מספיק כדי להיחשב בעיה מתמשכת." % (
                                  round(spike_rdy, 1), s.get("ready_max_ts"), round(spike_cs, 1), s.get("cs_max_ts"))),
                           _t("Check what happened on the host at that minute: a vMotion/DRS move, a backup snapshot (stun), or another VM bursting. If it repeats at the same time, look at the host and the jobs scheduled then.",
                              "לבדוק מה קרה ב-host באותה דקה: vMotion/DRS, snapshot של גיבוי (stun), או שרת אחר שקפץ. אם זה חוזר באותה שעה - לבדוק את ה-host ואת המשימות שמתוזמנות אז.")))
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
        # Is it happening now (hourly series, last 3 hours) and how big is it? swap/balloon are STATES (swapped pages stay
        # swapped until the guest touches them, the balloon deflates slowly), so a small leftover from an earlier episode is common.
        last_press, recent_press = None, False
        for r in (series or []):
            if (r.get("mp_swap_max_mb") or 0) >= swap_min or (r.get("mp_balloon_max_mb") or 0) > 0 or (r.get("mp_lat_max_pct") or 0) >= 1:
                last_press = r.get("bucket")
        try:
            if last_press and datetime.now() - datetime.strptime(last_press[:13], "%Y-%m-%d %H") <= timedelta(hours=3):
                recent_press = True
        except Exception:
            pass
        ram_mb = (ram_gb or 0) * 1024.0
        balloon_mb = s.get("mp_balloon_max_mb") or 0
        mp_big = (s.get("mp_swap_max_mb") or 0) >= 100 or mlat >= 5 or bool(ram_mb and balloon_mb >= 0.10 * ram_mb)
        sev = "crit" if (recent_press and (swap or mlat >= 5)) else ("warn" if (recent_press or mp_big) else "info")
        host_mem = (host.get("mem_pct") if host else None)
        host_roomy = host_mem is not None and host_mem < 85 and not host.get("mp_swap_vms")
        when_en = (" It is happening now." if recent_press else (" Not seen in the last 3 hours (last hourly bucket with pressure: %s)." % last_press if last_press else
                   (" Not visible in the last 48 hours of hourly data." if series else "")))
        when_he = (" זה קורה עכשיו." if recent_press else (" לא נראה ב-3 השעות האחרונות (הבאקט האחרון עם לחץ: %s)." % last_press if last_press else
                   (" לא נראה ב-48 השעות האחרונות של נתוני השעה." if series else "")))
        if host_roomy:
            act_en = ("The host itself has free memory (RAM %s%%), so this is not a general host shortage. Likely causes: (1) a memory limit on the Resource Pool or vApp the VM is in "
                      "(not only on the VM itself); (2) pressure that happened earlier - swapped pages stay swapped until the guest touches them and the balloon deflates slowly, "
                      "for example after the VM was restored or moved onto a busy host. Check vCenter events and the memory charts around the time of the peak%s. "
                      "If it is not ongoing and small, no action is needed." % (host_mem, (" (latency peak at %s)" % s.get("mp_lat_max_ts")) if s.get("mp_lat_max_ts") else ""))
            act_he = ("ל-host עצמו יש זיכרון פנוי (RAM %s%%), ולכן זו לא מצוקה כללית של ה-host. סיבות סבירות: (1) Memory Limit על ה-Resource Pool או ה-vApp שהשרת נמצא בהם "
                      "(לא רק על השרת עצמו); (2) לחץ שהיה קודם - דפים שנזרקו ל-swap נשארים שם עד שהשרת נוגע בהם וה-balloon משתחרר לאט, "
                      "למשל אחרי ששרת שוחזר או הועבר ל-host עמוס. לבדוק אירועים ב-vCenter וגרפי זיכרון סביב זמן השיא%s. "
                      "אם זה לא נמשך וקטן - אין צורך בפעולה." % (host_mem, (" (שיא ה-latency ב-%s)" % s.get("mp_lat_max_ts")) if s.get("mp_lat_max_ts") else ""))
        else:
            act_en = ("First check whether the VM has a Memory Limit in vCenter (it causes balloon/swap even on a free host) and remove it, and the Resource Pool / vApp limits. "
                      "Otherwise the ESXi itself is short of memory: see the ESXi card, move VMs away or add host memory.")
            act_he = ("קודם לבדוק אם הוגדר ל-VM Memory Limit ב-vCenter (גורם ל-balloon/swap גם ב-host פנוי) ולהסיר, וגם Limit על Resource Pool / vApp. "
                      "אחרת ל-ESXi עצמו חסר זיכרון: לראות את כרטיס ה-ESXi, להעביר שרתים או להוסיף זיכרון ל-host.")
        findings.append(_f(sev, "Memory pressure",
                           _t("The host is squeezing this VM's memory" if sev != "info" else "Past host memory pressure on this VM",
                              "ה-host מצר את הזיכרון של השרת" if sev != "info" else "לחץ זיכרון מצד ה-host בעבר על השרת"),
                           _t("Swap max %s MB (%s min), balloon max %s MB (%s min), memory latency max %s%%.%s" % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0, s.get("mp_balloon_max_mb"), s.get("mp_n_balloon") or 0, mlat, when_en),
                              "swap מקס' %s MB (%s דק'), balloon מקס' %s MB (%s דק'), Memory Latency מקס' %s%%.%s" % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0, s.get("mp_balloon_max_mb"), s.get("mp_n_balloon") or 0, mlat, when_he)),
                           _t(act_en, act_he)))
    elif swap_tiny:
        findings.append(_f("info", "Memory pressure",
                           _t("Tiny static swap (no pressure)", "swap קטן וסטטי (אין לחץ)"),
                           _t("%s MB of this VM's memory is swapped out (%s min of samples), with no balloon and no memory latency. That is a leftover from an earlier episode, not current pressure." % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0),
                              "%s MB מהזיכרון של השרת נמצאים ב-swap (%s דקות דגימה), בלי balloon ובלי Memory Latency. זה שריד מאירוע קודם ולא לחץ נוכחי." % (
                                  s.get("mp_swap_max_mb"), s.get("mp_n_swap") or 0)),
                           _t("No action needed. The pages stay swapped until the guest touches them; a vMotion or reboot clears it.",
                              "אין צורך בפעולה. הדפים נשארים ב-swap עד שהשרת נוגע בהם; vMotion או אתחול מנקים את זה.")))
    if mem_lv >= 2:
        db_en = " This looks like a database/cache/directory (Active Directory DC) server: they keep memory as cache on purpose, so high RAM is normal and the number cannot tell whether more RAM is needed (check Page Life Expectancy / paging inside the guest)." if is_db else ""
        db_he = " נראה שזה שרת DB/Cache/Active Directory (DC): שרתים כאלה מחזיקים זיכרון כ-cache בכוונה, ולכן RAM גבוה תקין והמספר לא אומר אם צריך עוד (לבדוק Page Life Expectancy / paging בתוך השרת)." if is_db else ""
        has_press = swap or balloon or mlat >= 1
        mem_sustained = (s.get("avg_mem_pct") or 0) >= 60 or _pct(s.get("mem_n_high"), n) >= 10
        findings.append(_f("info" if (is_db or not mem_sustained) else "warn", "Memory",
                           _t("Guest memory usage is high" if mem_sustained else "Brief memory spikes",
                              "ניצול הזיכרון בשרת גבוה" if mem_sustained else "קפיצות זיכרון קצרות"),
                           _t("Active RAM >=85%% for %s%% of the time (peak %s%% at %s) of %s GB.%s" % (
                                  _pct(s.get("mem_n_high"), n), s.get("max_mem_pct"), s.get("max_mem_ts"), ram_gb, db_en),
                              "RAM פעיל מעל 85%% במשך %s%% מהזמן (שיא %s%% ב-%s) מתוך %s GB.%s" % (
                                  _pct(s.get("mem_n_high"), n), s.get("max_mem_pct"), s.get("max_mem_ts"), ram_gb, db_he)),
                           _t("Active memory is a sampled estimate. Check pagefile/swap use inside the guest at the peak time; if it pages heavily, add RAM. "
                              "No host-side starvation was seen." if not has_press else "Host-side memory pressure is present too (see above).",
                              "זיכרון פעיל הוא הערכה מדגימה. לבדוק שימוש ב-pagefile/swap בתוך השרת בזמן השיא; אם יש paging כבד - להוסיף RAM. "
                              "לא נראתה מצוקת זיכרון מצד ה-host." if not has_press else "יש גם לחץ זיכרון מצד ה-host (ראה למעלה).")))
        if not mem_sustained and not has_press:
            findings[-1]["action"] = _t("Average RAM is low (%s%%) and the spikes are short, which is typical for updates or antivirus scans: no action unless users complain." % round(s.get("avg_mem_pct") or 0, 1),
                                        "ממוצע ה-RAM נמוך (%s%%) והקפיצות קצרות, דבר אופייני לעדכונים או סריקות אנטי-וירוס: אין צורך בפעולה אלא אם יש תלונות משתמשים." % round(s.get("avg_mem_pct") or 0, 1))

    # ---- ESXi host -------------------------------------------------------------------------------
    if host is None:
        findings.append(_f("info", "ESXi", _t("No live ESXi data", "אין נתון חי על ה-ESXi"),
                           _t("The host could not be determined (VM off, or the collector just restarted).", "לא ניתן לקבוע את ה-host (השרת כבוי, או שהאיסוף הופעל מחדש לאחרונה)."),
                           _t("Try again in a minute.", "לנסות שוב בעוד דקה.")))
    elif host_bad:
        reasons_he = host.get("reasons") or []
        reasons_en = host.get("reasons_en") or reasons_he
        crit = (host.get("level") == "down" or (host.get("cpu_pct") or 0) >= 90 or (host.get("ready_avg") or 0) >= 5
                or (host.get("mem_pct") or 0) >= 95)
        sev = ("crit" if crit else "warn") if host_busy else "info"
        top_en = ", ".join("%s %s%%" % (t.get("name"), t.get("cpu_pct")) for t in (host.get("top_vms") or []))
        swapv = host.get("mp_swap_vms") or 0
        swap_en = (" %s other VM(s) on this host are swapping memory (often caused by a Memory Limit set on them)." % swapv) if swapv and not swap else ""
        swap_he = (" ב-host יש עוד %s שרתים עם swap (לעיתים בגלל Memory Limit שהוגדר להם)." % swapv) if swapv and not swap else ""
        base_en = "%s. CPU %s%%, RAM %s%%, %s VMs, vCPU:core %s:1." % ("; ".join(reasons_en), host.get("cpu_pct"), host.get("mem_pct"), host.get("vms"), host.get("vcpu_ratio"))
        base_he = "%s. CPU %s%%, RAM %s%%, %s שרתים, יחס vCPU:ליבה %s:1." % ("; ".join(reasons_he), host.get("cpu_pct"), host.get("mem_pct"), host.get("vms"), host.get("vcpu_ratio"))
        if host_busy and host_contended:
            findings.append(_f(sev, "ESXi",
                               _t("The ESXi host %s is under load" % host.get("name"), "ה-ESXi %s תחת עומס" % host.get("name")),
                               _t(base_en + swap_en, base_he + swap_he),
                               _t("Rebalance: vMotion busy VMs to quieter hosts (check DRS). Top consumers on this host: %s." % top_en,
                                  "לאזן: vMotion של שרתים עמוסים ל-hosts שקטים (לבדוק DRS). הצרכנים הגדולים על ה-host: %s." % top_en)))
        elif host_busy:
            findings.append(_f("warn" if crit else "info", "ESXi",
                               _t("ESXi %s is busy but not contended" % host.get("name"), "ה-ESXi %s עסוק אבל בלי תחרות" % host.get("name")),
                               _t(base_en + swap_en + " CPU Ready on the host is low, so the VMs are not waiting for CPU: a busy host (high utilisation) is not the same as contention.",
                                  base_he + swap_he + " ה-CPU Ready ב-host נמוך, כלומר השרתים לא ממתינים למעבד: host עסוק (ניצול גבוה) הוא לא תחרות."),
                               _t("No action for this VM. Keep an eye on the headroom: if the host stays this busy, spread the heavy VMs (top consumers: %s)." % top_en,
                                  "אין צורך בפעולה לשרת הזה. לשמור על מרווח: אם ה-host נשאר עסוק כך, לפזר את השרתים הכבדים (הצרכנים הגדולים: %s)." % top_en)))
        else:
            findings.append(_f("info", "ESXi",
                               _t("ESXi %s: no contention affecting this VM" % host.get("name"), "ESXi %s: אין תחרות שמשפיעה על השרת הזה" % host.get("name")),
                               _t(base_en + swap_en + " The host's CPU, RAM and Ready are low, so this is a capacity-planning note and not the cause of this VM's problem.",
                                  base_he + swap_he + " ה-CPU, ה-RAM וה-Ready של ה-host נמוכים, ולכן זו הערת תכנון קיבולת ולא הסיבה לבעיה בשרת הזה."),
                               _t("", "")))   # no action text on purpose: it only made the AI pad healthy servers with "capacity planning" advice

    # ---- VM CPU topology: CPU hot add and cores per socket ----------------------------------------
    # vm_cfg = (cores per socket, CPU hot add). Physical sockets are assumed to be 2 per host (half the cores = one NUMA node).
    if vm_cfg and vcpu:
        cps, hot_add = int(vm_cfg[0] or 0), bool(vm_cfg[1])
        node_cores = int((host.get("cores") or 0) // 2) if host and host.get("cores") else 0
        vsockets = (vcpu // cps) if cps else 0
        wide = bool(node_cores) and vcpu > node_cores
        facts["topology"] = {"cores_per_socket": cps, "virtual_sockets": vsockets, "cpu_hot_add": hot_add,
                             "physical_cores_per_socket": node_cores or None, "spans_numa_nodes": wide}
        if hot_add and vcpu > 8:
            findings.append(_f("warn" if wide else "info", "Topology",
                               _t("CPU Hot Add is enabled (vNUMA is disabled)", "CPU Hot Add מופעל (ה-vNUMA מושבת)"),
                               _t("With CPU Hot Add on, ESXi does not present a virtual NUMA topology to the guest. This VM has %s vCPUs%s." % (
                                      vcpu, " - more than one physical socket (about %s cores), so it spans NUMA nodes without the guest knowing it" % node_cores if wide else
                                      " (it fits in one socket, so the impact is small)"),
                                  "כש-CPU Hot Add מופעל, ESXi לא חושף לשרת טופולוגיית NUMA וירטואלית. לשרת הזה %s vCPUs%s." % (
                                      vcpu, " - יותר מסוקט פיזי אחד (כ-%s ליבות), ולכן הוא פרוס על כמה צמתי NUMA בלי שהמערכת יודעת" % node_cores if wide else
                                      " (הוא נכנס בסוקט אחד, ולכן ההשפעה קטנה)")),
                               _t("If you do not need to add CPUs while the VM runs, turn CPU Hot Add off (Edit Settings > CPU; needs a power-off).%s" % (
                                      " Especially for NUMA-aware workloads (SQL Server, Oracle)." if wide else ""),
                                  "אם אין צורך להוסיף CPU בזמן שהשרת פועל - לכבות את CPU Hot Add (Edit Settings ← CPU; דורש כיבוי).%s" % (
                                      " במיוחד ליישומים שמודעים ל-NUMA (SQL Server, Oracle)." if wide else ""))))
        if wide and cps and node_cores:
            nodes = -(-vcpu // node_cores)
            if vsockets != nodes:
                findings.append(_f("info", "Topology",
                                   _t("Virtual CPU layout does not match the host", "מבנה הסוקטים הווירטואלי לא מתאים ל-host"),
                                   _t("%s vCPUs are presented as %s socket(s) x %s core(s), but a physical socket here has about %s cores, so the VM needs %s socket(s)." % (
                                          vcpu, vsockets, cps, node_cores, nodes),
                                      "%s vCPUs מוצגים כ-%s סוקטים × %s ליבות, אבל לסוקט פיזי כאן יש כ-%s ליבות, ולכן השרת צריך %s סוקטים." % (
                                          vcpu, vsockets, cps, node_cores, nodes)),
                                   _t("For NUMA-aware applications set Cores per Socket so the virtual sockets equal the physical sockets used (here %s x %s); for ordinary workloads it matters little." % (nodes, -(-vcpu // nodes)),
                                      "ליישומים שמודעים ל-NUMA להגדיר Cores per Socket כך שמספר הסוקטים הווירטואליים יהיה כמו הפיזיים בשימוש (כאן %s × %s); לעומס רגיל ההשפעה קטנה." % (nodes, -(-vcpu // nodes)))))
        if vsockets > 4 and _DB_NAME_RE.search(name or ""):
            express = "express" in (name or "").lower()
            findings.append(_f("warn" if express else "info", "Topology",
                               _t("Many virtual sockets on a database server", "הרבה סוקטים וירטואליים בשרת DB"),
                               _t("%s vCPUs are presented as %s sockets x %s core(s). SQL Server limits by sockets: Standard uses at most 4 sockets (or 24 cores), Express 1 socket (or 4 cores), so with this layout it may use only some of the vCPUs." % (vcpu, vsockets, cps),
                                  "%s vCPUs מוצגים כ-%s סוקטים × %s ליבות. SQL Server מוגבל לפי סוקטים: Standard עד 4 סוקטים (או 24 ליבות), Express סוקט אחד (או 4 ליבות), ולכן במבנה הזה הוא עלול לנצל רק חלק מה-vCPUs." % (vcpu, vsockets, cps)),
                               _t("If this is SQL Server Standard/Express, regroup the vCPUs into fewer sockets (for example 2 sockets x %s cores). Check the edition first." % (vcpu // 2),
                                  "אם זה SQL Server Standard/Express - לקבץ את ה-vCPUs לפחות סוקטים (למשל 2 סוקטים × %s ליבות). לבדוק קודם איזו מהדורה." % (vcpu // 2))))

    # ---- VM events (reboot / power / HA / vMotion) right before a peak ---------------------------------
    if events:
        notable = [ev for ev in events if ev.get("kind") in ("poweron", "reboot", "reset", "ha", "vmotion", "poweroff")]
        facts["vm_events"] = [{"time": ev["time"], "kind": ev["kind"], "user": ev.get("user", "")} for ev in notable[-8:]]
        hit = None
        # a spike that stands out from the VM's usual level (a reboot rarely reaches 85%, but 36% on a 5% VM is a spike)
        for label, ts, val, usual, floor, delta in (("CPU peak", s.get("max_cpu_ts"), s.get("max_cpu_pct"), s.get("avg_cpu_pct"), 30, 20),
                                                    ("RAM peak", s.get("max_mem_ts"), s.get("max_mem_pct"), s.get("avg_mem_pct"), 40, 20),
                                                    ("Ready peak", s.get("ready_max_ts"), s.get("ready_max_pct"), 0, 3, 0),
                                                    ("Co-Stop peak", s.get("cs_max_ts"), s.get("cs_max_pct"), 0, 2, 0)):
            t0 = _parse(ts)
            if not t0 or (val or 0) < floor or (val or 0) - (usual or 0) < delta:
                continue
            for ev in notable:
                te = _parse(ev["time"])
                if te and te - timedelta(minutes=10) <= t0 <= te + timedelta(minutes=60):
                    hit = (label, ts, ev)
                    break
            if hit:
                break
        if hit:
            label, ts, ev = hit
            findings.append(_f("info", "Event",
                               _t("A peak follows a server event (%s)" % ev["kind"], "פיק אחרי אירוע בשרת (%s)" % ev["kind"]),
                               _t("The %s (%s) is within an hour of: %s at %s%s. A reboot, power-on or move makes the VM load disks, caches and services, "
                                  "which looks like a CPU/RAM/Ready spike." % (label, ts, ev.get("label_en") or ev["kind"], ev["time"], (" (by %s)" % ev["user"]) if ev.get("user") else ""),
                                  "ה-%s (%s) קרוב (עד שעה) לאירוע: %s ב-%s%s. אתחול, הפעלה או העברה גורמים לשרת לטעון דיסקים, cache ושירותים, וזה נראה כקפיצה ב-CPU/RAM/Ready." % (
                                      label, ts, ev.get("label") or ev["kind"], ev["time"], (" (על ידי %s)" % ev["user"]) if ev.get("user") else "")),
                               _t("Usually expected and no action is needed; if it repeats without a planned event, look for unplanned restarts (patching, crashes, HA).",
                                  "בדרך כלל צפוי ואין צורך בפעולה; אם זה חוזר בלי אירוע מתוכנן, לחפש אתחולים לא מתוכננים (עדכונים, קריסות, HA).")))

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
        for label, ts, val, floor in (("CPU peak", s.get("max_cpu_ts"), s.get("max_cpu_pct"), 85),
                                      ("RAM peak", s.get("max_mem_ts"), s.get("max_mem_pct"), 85),
                                      ("Ready peak", s.get("ready_max_ts"), s.get("ready_max_pct"), 5),
                                      ("Co-Stop peak", s.get("cs_max_ts"), s.get("cs_max_pct"), 3)):
            if (val or 0) < floor:
                continue                      # only a peak that is high enough to matter can be blamed on a backup
            p = _near_backup(ts, backups)
            if p:
                hits.append((label, ts, p))
        if hits:
            label, ts, p = hits[0]
            t0, st, en = _parse(ts), _parse(p.get("start")), _parse(p.get("end"))
            inside = bool(t0 and st and en and st <= t0 <= en)        # inside the backup window, not "after" it
            if inside:
                when_en = "falls inside the window of a %s backup (%s to %s, job '%s')" % (p.get("server"), p.get("start", "")[11:16], p.get("end", "")[11:16], p.get("job"))
                when_he = "נופל בתוך חלון של גיבוי %s (%s עד %s, job '%s')" % (p.get("server"), p.get("start", "")[11:16], p.get("end", "")[11:16], p.get("job"))
            else:
                when_en = "falls shortly after the start of a %s backup (restore point %s, job '%s')" % (p.get("server"), p.get("time"), p.get("job"))
                when_he = "נופל זמן קצר אחרי תחילת גיבוי %s (נקודת שחזור %s, job '%s')" % (p.get("server"), p.get("time"), p.get("job"))
            findings.append(_f("info", "Backup",
                               _t("A peak coincides with a backup", "פיק מתיישר עם גיבוי"),
                               _t("The %s (%s) %s. A backup snapshot (create / remove) briefly freezes the VM, which shows up as a short Ready / Co-Stop spike." % (label, ts, when_en),
                                  "ה-%s (%s) %s. snapshot של גיבוי (יצירה / מחיקה) מקפיא את השרת לרגע, וזה נראה כקפיצת Ready / Co-Stop קצרה." % (label, ts, when_he)),
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
        verdict = _t("No resource problem found on the hypervisor side. If users report slowness, look inside the guest (application, OS, network).",
                     "לא נמצאה בעיית משאבים מצד ה-hypervisor. אם יש תלונות על איטיות, לבדוק בתוך השרת (אפליקציה, מערכת הפעלה, רשת).")
        level = "ok"
    out = {"verdict": verdict, "level": level, "findings": findings, "facts": facts}
    if cpu_answer:
        out["cpu_answer"] = cpu_answer
    return out
