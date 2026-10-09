"""
Performance history storage for the vCenter Performance page.

The collector samples CPU/RAM per VM every minute, but only rolled-up buckets are stored:
  - vm_perf_hourly : one row per (env, VM, hour)  - kept PERF_HOURLY_RETENTION_DAYS
  - vm_perf_daily  : one row per (env, VM, day)   - kept PERF_DAILY_RETENTION_DAYS (~6 months)
Each row keeps the peak (with the minute it happened) plus sums/sample-count for averages.
"""

from typing import Optional

from database import get_db

PERF_HOURLY_RETENTION_DAYS = 30
PERF_DAILY_RETENTION_DAYS = 183   # ~6 months

# Load bands (% utilisation) counted per bucket, so the page can tell a one-off spike from
# recurring load: a sample counts as "medium" at >= BAND_MID and "high" at >= BAND_HIGH
# (cumulative - every high sample is also a medium one).
BAND_MID = 70
BAND_HIGH = 85
# A bucket is "hot" when it holds at least this many high-load minutes (hourly / daily bucket).
# CPU Ready is stored per vCPU (%): < 5 normal, 5-10 warning, >= 10 critical (VMware/industry guidance).
READY_WARN = 5
READY_CRIT = 10
# Host-side memory pressure (per VM): mem.latency is the % of time the VM waits for memory.
# CPU Co-Stop (% per vCPU): above ~3% the VM has more vCPUs than it can use efficiently.
COSTOP_WARN = 3
COSTOP_CRIT = 5
LIMITED_MIN = 1       # a minute counts as "limited" when held back >= 1% by a CPU limit
MEM_LAT_WARN = 1
MEM_LAT_CRIT = 5
HOT_MIN_HOURLY = 5
HOT_MIN_DAILY = 10

_COLS = """
    environment TEXT NOT NULL, vm_name TEXT NOT NULL, bucket TEXT NOT NULL,
    num_cpu INTEGER DEFAULT 0, mem_gb REAL DEFAULT 0,
    max_cpu_pct REAL DEFAULT 0, max_cpu_ts TEXT DEFAULT '',
    max_mem_pct REAL DEFAULT 0, max_mem_ts TEXT DEFAULT '',
    cpu_sum REAL DEFAULT 0, mem_sum REAL DEFAULT 0, samples INTEGER DEFAULT 0,
    cpu_n_mid INTEGER DEFAULT 0, cpu_n_high INTEGER DEFAULT 0,
    mem_n_mid INTEGER DEFAULT 0, mem_n_high INTEGER DEFAULT 0,
    ready_max_pct REAL DEFAULT 0, ready_max_ts TEXT DEFAULT '',
    ready_sum REAL DEFAULT 0, ready_samples INTEGER DEFAULT 0,
    ready_n_warn INTEGER DEFAULT 0, ready_n_crit INTEGER DEFAULT 0,
    mp_swap_max_mb REAL DEFAULT 0, mp_balloon_max_mb REAL DEFAULT 0,
    mp_lat_max_pct REAL DEFAULT 0, mp_lat_max_ts TEXT DEFAULT '',
    mp_samples INTEGER DEFAULT 0, mp_n_balloon INTEGER DEFAULT 0,
    mp_n_swap INTEGER DEFAULT 0, mp_n_lat INTEGER DEFAULT 0,
    cs_max_pct REAL DEFAULT 0, cs_max_ts TEXT DEFAULT '', cs_sum REAL DEFAULT 0,
    cs_samples INTEGER DEFAULT 0, cs_n_warn INTEGER DEFAULT 0,
    lim_max_pct REAL DEFAULT 0, lim_n INTEGER DEFAULT 0,
    PRIMARY KEY (environment, vm_name, bucket)
"""


def init_perf_tables() -> None:
    with get_db() as conn:
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS vm_perf_hourly ({_COLS}) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS vm_perf_daily  ({_COLS}) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS idx_perf_hourly_bucket ON vm_perf_hourly(bucket);
            CREATE INDEX IF NOT EXISTS idx_perf_daily_bucket  ON vm_perf_daily(bucket);
        """)
        # Tables created by the first version of this feature lack the band-count columns.
        for table in ("vm_perf_hourly", "vm_perf_daily"):
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in (("cpu_n_mid", "INTEGER DEFAULT 0"), ("cpu_n_high", "INTEGER DEFAULT 0"),
                             ("mem_n_mid", "INTEGER DEFAULT 0"), ("mem_n_high", "INTEGER DEFAULT 0"),
                             ("ready_max_pct", "REAL DEFAULT 0"), ("ready_max_ts", "TEXT DEFAULT ''"),
                             ("ready_sum", "REAL DEFAULT 0"), ("ready_samples", "INTEGER DEFAULT 0"),
                             ("ready_n_warn", "INTEGER DEFAULT 0"), ("ready_n_crit", "INTEGER DEFAULT 0"),
                             ("mp_swap_max_mb", "REAL DEFAULT 0"), ("mp_balloon_max_mb", "REAL DEFAULT 0"),
                             ("mp_lat_max_pct", "REAL DEFAULT 0"), ("mp_lat_max_ts", "TEXT DEFAULT ''"),
                             ("mp_samples", "INTEGER DEFAULT 0"), ("mp_n_balloon", "INTEGER DEFAULT 0"),
                             ("mp_n_swap", "INTEGER DEFAULT 0"), ("mp_n_lat", "INTEGER DEFAULT 0"),
                             ("cs_max_pct", "REAL DEFAULT 0"), ("cs_max_ts", "TEXT DEFAULT ''"),
                             ("cs_sum", "REAL DEFAULT 0"), ("cs_samples", "INTEGER DEFAULT 0"),
                             ("cs_n_warn", "INTEGER DEFAULT 0"), ("lim_max_pct", "REAL DEFAULT 0"),
                             ("lim_n", "INTEGER DEFAULT 0")):
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def _upsert(conn, table: str, rows: list) -> None:
    # The collector flushes partial buckets every few minutes, so the same
    # (env, vm, bucket) row is updated repeatedly: keep the max, add the sums/samples.
    conn.executemany(f"""
        INSERT INTO {table} (environment, vm_name, bucket, num_cpu, mem_gb,
                             max_cpu_pct, max_cpu_ts, max_mem_pct, max_mem_ts,
                             cpu_sum, mem_sum, samples,
                             cpu_n_mid, cpu_n_high, mem_n_mid, mem_n_high,
                             ready_max_pct, ready_max_ts, ready_sum, ready_samples,
                             ready_n_warn, ready_n_crit,
                             mp_swap_max_mb, mp_balloon_max_mb, mp_lat_max_pct, mp_lat_max_ts,
                             mp_samples, mp_n_balloon, mp_n_swap, mp_n_lat,
                             cs_max_pct, cs_max_ts, cs_sum, cs_samples, cs_n_warn, lim_max_pct, lim_n)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(environment, vm_name, bucket) DO UPDATE SET
            num_cpu     = excluded.num_cpu,
            mem_gb      = excluded.mem_gb,
            max_cpu_ts  = CASE WHEN excluded.max_cpu_pct > {table}.max_cpu_pct
                               THEN excluded.max_cpu_ts ELSE {table}.max_cpu_ts END,
            max_cpu_pct = MAX({table}.max_cpu_pct, excluded.max_cpu_pct),
            max_mem_ts  = CASE WHEN excluded.max_mem_pct > {table}.max_mem_pct
                               THEN excluded.max_mem_ts ELSE {table}.max_mem_ts END,
            max_mem_pct = MAX({table}.max_mem_pct, excluded.max_mem_pct),
            cpu_sum     = {table}.cpu_sum + excluded.cpu_sum,
            mem_sum     = {table}.mem_sum + excluded.mem_sum,
            samples     = {table}.samples + excluded.samples,
            cpu_n_mid   = {table}.cpu_n_mid  + excluded.cpu_n_mid,
            cpu_n_high  = {table}.cpu_n_high + excluded.cpu_n_high,
            mem_n_mid   = {table}.mem_n_mid  + excluded.mem_n_mid,
            mem_n_high  = {table}.mem_n_high + excluded.mem_n_high,
            ready_max_ts  = CASE WHEN excluded.ready_max_pct > {table}.ready_max_pct
                                 THEN excluded.ready_max_ts ELSE {table}.ready_max_ts END,
            ready_max_pct = MAX({table}.ready_max_pct, excluded.ready_max_pct),
            ready_sum     = {table}.ready_sum + excluded.ready_sum,
            ready_samples = {table}.ready_samples + excluded.ready_samples,
            ready_n_warn  = {table}.ready_n_warn + excluded.ready_n_warn,
            ready_n_crit  = {table}.ready_n_crit + excluded.ready_n_crit,
            mp_lat_max_ts = CASE WHEN excluded.mp_lat_max_pct > {table}.mp_lat_max_pct
                                 THEN excluded.mp_lat_max_ts ELSE {table}.mp_lat_max_ts END,
            mp_lat_max_pct   = MAX({table}.mp_lat_max_pct, excluded.mp_lat_max_pct),
            mp_swap_max_mb   = MAX({table}.mp_swap_max_mb, excluded.mp_swap_max_mb),
            mp_balloon_max_mb = MAX({table}.mp_balloon_max_mb, excluded.mp_balloon_max_mb),
            mp_samples   = {table}.mp_samples   + excluded.mp_samples,
            mp_n_balloon = {table}.mp_n_balloon + excluded.mp_n_balloon,
            mp_n_swap    = {table}.mp_n_swap    + excluded.mp_n_swap,
            mp_n_lat     = {table}.mp_n_lat     + excluded.mp_n_lat,
            cs_max_ts    = CASE WHEN excluded.cs_max_pct > {table}.cs_max_pct
                                THEN excluded.cs_max_ts ELSE {table}.cs_max_ts END,
            cs_max_pct   = MAX({table}.cs_max_pct, excluded.cs_max_pct),
            cs_sum       = {table}.cs_sum + excluded.cs_sum,
            cs_samples   = {table}.cs_samples + excluded.cs_samples,
            cs_n_warn    = {table}.cs_n_warn + excluded.cs_n_warn,
            lim_max_pct  = MAX({table}.lim_max_pct, excluded.lim_max_pct),
            lim_n        = {table}.lim_n + excluded.lim_n
    """, rows)


def save_rollups(hourly_rows: list, daily_rows: list) -> None:
    """Row = (env, vm, bucket, num_cpu, mem_gb, max_cpu_pct, max_cpu_ts, max_mem_pct,
    max_mem_ts, cpu_sum, mem_sum, samples, cpu_n_mid, cpu_n_high, mem_n_mid, mem_n_high).
    One transaction per flush."""
    if not hourly_rows and not daily_rows:
        return
    with get_db() as conn:
        _upsert(conn, "vm_perf_hourly", hourly_rows)
        _upsert(conn, "vm_perf_daily", daily_rows)


def prune() -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM vm_perf_hourly WHERE bucket < datetime('now','localtime',?)",
                     (f"-{PERF_HOURLY_RETENTION_DAYS} days",))
        conn.execute("DELETE FROM vm_perf_daily WHERE bucket < date('now','localtime',?)",
                     (f"-{PERF_DAILY_RETENTION_DAYS} days",))


def get_summary(since_bucket: str, table: str = "vm_perf_daily", env: Optional[str] = None) -> list:
    """Per-VM aggregate over [since_bucket, now]: peak CPU/RAM (and when), averages, sample count."""
    assert table in ("vm_perf_daily", "vm_perf_hourly")
    where, params = ["p.bucket >= ?"], [since_bucket]
    if env:
        where.append("p.environment = ?")
        params.append(env)
    hot_min = HOT_MIN_HOURLY if table == "vm_perf_hourly" else HOT_MIN_DAILY
    sql = f"""
        SELECT p.environment, p.vm_name,
               MAX(p.num_cpu) AS num_cpu, MAX(p.mem_gb) AS mem_gb,
               MAX(p.max_cpu_pct) AS max_cpu_pct,
               (SELECT q.max_cpu_ts FROM {table} q WHERE q.environment=p.environment
                  AND q.vm_name=p.vm_name AND q.bucket >= ? ORDER BY q.max_cpu_pct DESC LIMIT 1) AS max_cpu_ts,
               MAX(p.max_mem_pct) AS max_mem_pct,
               (SELECT q.max_mem_ts FROM {table} q WHERE q.environment=p.environment
                  AND q.vm_name=p.vm_name AND q.bucket >= ? ORDER BY q.max_mem_pct DESC LIMIT 1) AS max_mem_ts,
               SUM(p.cpu_sum) * 1.0 / NULLIF(SUM(p.samples), 0) AS avg_cpu_pct,
               SUM(p.mem_sum) * 1.0 / NULLIF(SUM(p.samples), 0) AS avg_mem_pct,
               SUM(p.samples) AS samples,
               SUM(p.cpu_n_mid) AS cpu_n_mid, SUM(p.cpu_n_high) AS cpu_n_high,
               SUM(p.mem_n_mid) AS mem_n_mid, SUM(p.mem_n_high) AS mem_n_high,
               MAX(p.ready_max_pct) AS ready_max_pct,
               (SELECT q.ready_max_ts FROM {table} q WHERE q.environment=p.environment
                  AND q.vm_name=p.vm_name AND q.bucket >= ? ORDER BY q.ready_max_pct DESC LIMIT 1) AS ready_max_ts,
               SUM(p.ready_sum) * 1.0 / NULLIF(SUM(p.ready_samples), 0) AS ready_avg_pct,
               SUM(p.ready_samples) AS ready_samples,
               SUM(p.ready_n_warn) AS ready_n_warn, SUM(p.ready_n_crit) AS ready_n_crit,
               SUM(CASE WHEN p.ready_n_warn >= {hot_min} THEN 1 ELSE 0 END) AS ready_hot_buckets,
               MAX(p.mp_swap_max_mb) AS mp_swap_max_mb, MAX(p.mp_balloon_max_mb) AS mp_balloon_max_mb,
               MAX(p.mp_lat_max_pct) AS mp_lat_max_pct,
               (SELECT q.mp_lat_max_ts FROM {table} q WHERE q.environment=p.environment
                  AND q.vm_name=p.vm_name AND q.bucket >= ? ORDER BY q.mp_lat_max_pct DESC LIMIT 1) AS mp_lat_max_ts,
               SUM(p.mp_samples) AS mp_samples, SUM(p.mp_n_balloon) AS mp_n_balloon,
               SUM(p.mp_n_swap) AS mp_n_swap, SUM(p.mp_n_lat) AS mp_n_lat,
               MAX(p.cs_max_pct) AS cs_max_pct,
               (SELECT q.cs_max_ts FROM {table} q WHERE q.environment=p.environment
                  AND q.vm_name=p.vm_name AND q.bucket >= ? ORDER BY q.cs_max_pct DESC LIMIT 1) AS cs_max_ts,
               SUM(p.cs_sum) * 1.0 / NULLIF(SUM(p.cs_samples), 0) AS cs_avg_pct,
               SUM(p.cs_samples) AS cs_samples, SUM(p.cs_n_warn) AS cs_n_warn,
               MAX(p.lim_max_pct) AS lim_max_pct, SUM(p.lim_n) AS lim_n,
               COUNT(*) AS buckets,
               SUM(CASE WHEN p.cpu_n_high >= {hot_min} THEN 1 ELSE 0 END) AS cpu_hot_buckets,
               SUM(CASE WHEN p.mem_n_high >= {hot_min} THEN 1 ELSE 0 END) AS mem_hot_buckets,
               COALESCE(s.sap_number, '') AS sap_number
        FROM {table} p
        LEFT JOIN vm_sap_cache s ON s.vm_name = p.vm_name AND LOWER(s.environment) = LOWER(p.environment)
        WHERE {' AND '.join(where)}
        GROUP BY p.environment, p.vm_name
    """
    with get_db() as conn:
        rows = conn.execute(sql, [since_bucket] * 5 + params).fetchall()
    return [dict(r) for r in rows]


def get_series(env: str, vm_name: str, since_bucket: str, table: str = "vm_perf_hourly") -> list:
    assert table in ("vm_perf_daily", "vm_perf_hourly")
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT bucket, num_cpu, max_cpu_pct, max_cpu_ts, max_mem_pct, max_mem_ts,
                       cpu_sum * 1.0 / NULLIF(samples, 0) AS avg_cpu_pct,
                       mem_sum * 1.0 / NULLIF(samples, 0) AS avg_mem_pct, samples,
                       cpu_n_mid, cpu_n_high, mem_n_mid, mem_n_high,
                       ready_max_pct, ready_sum * 1.0 / NULLIF(ready_samples, 0) AS ready_avg_pct,
                       mp_swap_max_mb, mp_balloon_max_mb, mp_lat_max_pct
                FROM {table} WHERE environment=? AND vm_name=? AND bucket >= ? ORDER BY bucket""",
            (env, vm_name, since_bucket)).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_db() as conn:
        h = conn.execute("SELECT COUNT(*) c, MIN(bucket) a, MAX(bucket) b FROM vm_perf_hourly").fetchone()
        d = conn.execute("SELECT COUNT(*) c, MIN(bucket) a, MAX(bucket) b FROM vm_perf_daily").fetchone()
    return {"hourly_rows": h["c"], "hourly_from": h["a"], "hourly_to": h["b"],
            "daily_rows": d["c"], "daily_from": d["a"], "daily_to": d["b"]}
