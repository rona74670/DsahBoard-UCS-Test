"""
SQLite database layer for UCS Dashboard.
Handles:
  - manual_data  (replaces per-farm JSON files)
  - devices      (device registry: UCS, InfiniBand, Host, Storage, …)
  - customers    (SAP number → customer name mapping)
"""

import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "dashboard.db")


# ------------------------------------------------------------------ #
#  Connection helper                                                   #
# ------------------------------------------------------------------ #

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------ #
#  Schema initialisation                                               #
# ------------------------------------------------------------------ #

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS manual_data (
                farm        TEXT    NOT NULL,
                server_key  TEXT    NOT NULL,
                assignment  TEXT    DEFAULT '',
                cabinet     TEXT    DEFAULT '',
                vcenter     TEXT    DEFAULT '',
                notes       TEXT    DEFAULT '',
                updated_at  TEXT    DEFAULT (datetime('now')),
                PRIMARY KEY (farm, server_key)
            );

            CREATE TABLE IF NOT EXISTS devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                farm        TEXT    NOT NULL DEFAULT 'ALL',
                name        TEXT    NOT NULL,
                type        TEXT    NOT NULL DEFAULT 'Generic',
                role        TEXT    DEFAULT '',
                host        TEXT    DEFAULT '',
                ip_address  TEXT    DEFAULT '',
                ilo_address TEXT    DEFAULT '',
                username    TEXT    DEFAULT '',
                password    TEXT    DEFAULT '',
                port        INTEGER DEFAULT 443,
                protocol    TEXT    DEFAULT 'https',
                notes       TEXT    DEFAULT '',
                enabled     INTEGER DEFAULT 1,
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ibox_capacity_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ibox_id         TEXT    NOT NULL,
                recorded_at     INTEGER NOT NULL,
                phys_free_tb    REAL    NOT NULL,
                phys_total_tb   REAL    NOT NULL,
                phys_pct        REAL    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ibox_cap_hist
                ON ibox_capacity_history (ibox_id, recorded_at);

            CREATE TABLE IF NOT EXISTS customers (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sap_number    TEXT    NOT NULL UNIQUE,
                customer_name TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now')),
                updated_at    TEXT    DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_customers_sap
                ON customers (sap_number);

            CREATE TABLE IF NOT EXISTS vm_notes (
                environment TEXT NOT NULL,
                vm_name     TEXT NOT NULL,
                note        TEXT DEFAULT '',
                updated_at  TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (environment, vm_name)
            );

            CREATE TABLE IF NOT EXISTS auth_settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL DEFAULT '',
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS authz_users (
                identity    TEXT PRIMARY KEY,
                username    TEXT NOT NULL DEFAULT '',
                role        TEXT NOT NULL DEFAULT 'readonly',
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );
        """)

        # vcenter_events – change tracking (append-only, 1-year retention)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS vcenter_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    environment TEXT    NOT NULL,
                    event_key   INTEGER NOT NULL,
                    event_type  TEXT    NOT NULL,
                    vm_name     TEXT    DEFAULT '',
                    user_name   TEXT    DEFAULT '',
                    timestamp   TEXT    NOT NULL,
                    change_info TEXT    DEFAULT '',
                    description TEXT    DEFAULT '',
                    created_at  TEXT    DEFAULT (datetime('now'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_vc_evt_key
                    ON vcenter_events(environment, event_key);
                CREATE INDEX IF NOT EXISTS idx_vc_evt_ts
                    ON vcenter_events(environment, timestamp);
                CREATE TABLE IF NOT EXISTS vm_sap_cache (
                    vm_name     TEXT    NOT NULL,
                    environment TEXT    NOT NULL,
                    sap_number  TEXT    DEFAULT '',
                    updated_at  TEXT    DEFAULT (datetime('now')),
                    PRIMARY KEY (vm_name, environment)
                );
            """)
        except Exception:
            pass

        # customer_billing_config – optional per-customer free-growth allowance + per-resource
        # pricing, used by the History change report to compute billable growth (see
        # billing_config.html / /api/billing/config). Keyed by customer_name (matches
        # groupReportByCustomer's grouping key in the report, not sap_number).
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS customer_billing_config (
                    customer_name    TEXT    PRIMARY KEY,
                    enabled          INTEGER DEFAULT 1,
                    free_pct_cpu     REAL    DEFAULT 5,
                    free_pct_ram     REAL    DEFAULT 5,
                    free_pct_stor    REAL    DEFAULT 5,
                    price_vcpu       REAL    DEFAULT 0,
                    price_ram_gb     REAL    DEFAULT 0,
                    price_storage_gb REAL    DEFAULT 0,
                    updated_at       TEXT    DEFAULT (datetime('now'))
                );
            """)
        except Exception:
            pass

        # vm_snapshots – point-in-time full VM inventory captures (History page)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS vm_snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    taken_at    TEXT    NOT NULL,
                    taken_by    TEXT    DEFAULT '',
                    note        TEXT    DEFAULT '',
                    vm_count    INTEGER DEFAULT 0,
                    envs_ok     TEXT    DEFAULT '',
                    protected   INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_vm_snap_taken_at
                    ON vm_snapshots(taken_at);
                CREATE TABLE IF NOT EXISTS vm_snapshot_items (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    environment TEXT    NOT NULL,
                    vm_name     TEXT    NOT NULL,
                    sap_number  TEXT    DEFAULT '',
                    cluster     TEXT    DEFAULT '',
                    power_state TEXT    DEFAULT '',
                    num_cpu     INTEGER DEFAULT 0,
                    memory_gb   REAL    DEFAULT 0,
                    storage_committed_gb   REAL DEFAULT 0,
                    storage_uncommitted_gb REAL DEFAULT 0,
                    data_json   TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_vm_snap_items_snap
                    ON vm_snapshot_items(snapshot_id);
                CREATE TABLE IF NOT EXISTS vm_snapshot_env_data (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id  INTEGER NOT NULL,
                    environment  TEXT    NOT NULL,
                    summary_json TEXT    NOT NULL,   -- full VCenterClient.get_summary() dict:
                                                      -- total_vms, powered_on/off, suspended,
                                                      -- active_vcpu, active_ram_gb, total_storage_gb,
                                                      -- clusters, hosts, vms, datastores, affinity_rules
                    UNIQUE(snapshot_id, environment)
                );
            """)
        except Exception:
            pass

        # Migration: add new columns if they don't exist yet
        for col, definition in [
            ("role",        "TEXT DEFAULT ''"),
            ("ip_address",  "TEXT DEFAULT ''"),
            ("ilo_address", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {definition}")
            except Exception:
                pass  # column already exists

        try:
            conn.execute("ALTER TABLE vm_notes ADD COLUMN classification TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists

        try:
            conn.execute("ALTER TABLE vm_snapshots ADD COLUMN protected INTEGER DEFAULT 0")
        except Exception:
            pass  # column already exists


# ------------------------------------------------------------------ #
#  Migration: JSON files → SQLite                                      #
# ------------------------------------------------------------------ #

def migrate_json_if_needed(farm_id: str, json_path: str):
    """Import an existing manual-data JSON file into SQLite (once)."""
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        with get_db() as conn:
            for key, vals in data.items():
                conn.execute(
                    """INSERT OR IGNORE INTO manual_data
                       (farm, server_key, assignment, cabinet, vcenter)
                       VALUES (?,?,?,?,?)""",
                    (farm_id, key,
                     vals.get("assignment", ""),
                     vals.get("cabinet",    ""),
                     vals.get("vcenter",    "")),
                )
        # Keep the JSON as a backup
        os.rename(json_path, json_path + ".migrated.bak")
        print(f"[DB] Migrated {json_path} → SQLite (farm={farm_id})")
    except Exception as e:
        print(f"[DB] Migration warning for {json_path}: {e}")


# ------------------------------------------------------------------ #
#  manual_data CRUD                                                    #
# ------------------------------------------------------------------ #

def load_manual(farm_id: str) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT server_key, assignment, cabinet, vcenter, notes FROM manual_data WHERE farm=?",
            (farm_id,)
        ).fetchall()
    return {
        row["server_key"]: {
            "assignment": row["assignment"],
            "cabinet":    row["cabinet"],
            "vcenter":    row["vcenter"],
            "notes":      row["notes"],
        }
        for row in rows
    }


def save_manual(farm_id: str, server_key: str,
                assignment: str = "", cabinet: str = "",
                vcenter: str = "", notes: str = ""):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO manual_data (farm, server_key, assignment, cabinet, vcenter, notes, updated_at)
               VALUES (?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(farm, server_key) DO UPDATE SET
                   assignment = excluded.assignment,
                   cabinet    = excluded.cabinet,
                   vcenter    = excluded.vcenter,
                   notes      = excluded.notes,
                   updated_at = datetime('now')""",
            (farm_id, server_key, assignment, cabinet, vcenter, notes),
        )


# ------------------------------------------------------------------ #
#  vm_notes CRUD (per-VM role/description, keyed by vCenter env)      #
# ------------------------------------------------------------------ #

def get_vm_notes(environment: str) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT vm_name, note FROM vm_notes WHERE environment=?",
            (environment,)
        ).fetchall()
    return {row["vm_name"]: row["note"] for row in rows}


def save_vm_note(environment: str, vm_name: str, note: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO vm_notes (environment, vm_name, note, updated_at)
               VALUES (?,?,?,datetime('now'))
               ON CONFLICT(environment, vm_name) DO UPDATE SET
                   note       = excluded.note,
                   updated_at = datetime('now')""",
            (environment, vm_name, note),
        )


def get_vm_classifications(environment: str) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT vm_name, classification FROM vm_notes WHERE environment=?",
            (environment,)
        ).fetchall()
    return {row["vm_name"]: row["classification"] for row in rows}


def save_vm_classification(environment: str, vm_name: str, classification: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO vm_notes (environment, vm_name, classification, updated_at)
               VALUES (?,?,?,datetime('now'))
               ON CONFLICT(environment, vm_name) DO UPDATE SET
                   classification = excluded.classification,
                   updated_at     = datetime('now')""",
            (environment, vm_name, classification),
        )


# ------------------------------------------------------------------ #
#  devices CRUD                                                        #
# ------------------------------------------------------------------ #

def _row_to_dict(row) -> dict:
    return dict(row)


_DEVICE_COLS = "id, farm, name, type, role, host, ip_address, ilo_address, username, port, protocol, notes, enabled, created_at, updated_at"


# ─────────────────────────────────────────────────────────────────────────── #
#  Password encryption at rest (Fernet / AES-128-CBC)                        #
#  Set DB_ENCRYPT_KEY env var to enable. Leave unset to keep plaintext.       #
# ─────────────────────────────────────────────────────────────────────────── #
def _pw_fernet():
    """Return a Fernet cipher from DB_ENCRYPT_KEY env, or None if not set."""
    key = os.getenv("DB_ENCRYPT_KEY", "").strip()
    if not key:
        return None
    import hashlib, base64
    from cryptography.fernet import Fernet
    raw = hashlib.sha256(key.encode()).digest()        # 32 bytes
    return Fernet(base64.urlsafe_b64encode(raw))       # Fernet requires 32-byte url-safe b64 key


def _encrypt_pw(pw: str) -> str:
    """Encrypt a plaintext password. Returns plaintext if key not configured."""
    f = _pw_fernet()
    if not f or not pw:
        return pw
    return f.encrypt(pw.encode()).decode()


def _decrypt_pw(pw: str) -> str:
    """Decrypt a password. Falls back to returning as-is for legacy plaintext."""
    f = _pw_fernet()
    if not f or not pw:
        return pw
    try:
        return f.decrypt(pw.encode()).decode()
    except Exception:
        return pw   # Legacy plaintext value — return unchanged


def list_devices(farm: Optional[str] = None) -> list[dict]:
    with get_db() as conn:
        if farm:
            rows = conn.execute(
                f"SELECT {_DEVICE_COLS} FROM devices WHERE farm=? ORDER BY type, name", (farm,)
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_DEVICE_COLS} FROM devices ORDER BY farm, type, name"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_device(device_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            f"SELECT {_DEVICE_COLS} FROM devices WHERE id=?", (device_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_device(farm: str, name: str, dtype: str, host: str = "",
                  username: str = "", password: str = "", port: int = 443,
                  protocol: str = "https", notes: str = "", enabled: bool = True,
                  role: str = "", ip_address: str = "", ilo_address: str = "") -> dict:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO devices (farm, name, type, role, host, ip_address, ilo_address,
               username, password, port, protocol, notes, enabled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (farm, name, dtype, role, host, ip_address, ilo_address,
             username, _encrypt_pw(password), port, protocol, notes, 1 if enabled else 0),
        )
        device_id = cur.lastrowid
    return get_device(device_id)


def update_device(device_id: int, **fields) -> Optional[dict]:
    allowed = {"farm","name","type","role","host","ip_address","ilo_address",
               "username","password","port","protocol","notes","enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "password" in updates and updates["password"]:
        updates["password"] = _encrypt_pw(updates["password"])
    if not updates:
        return get_device(device_id)
    updates["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [device_id]
    with get_db() as conn:
        conn.execute(f"UPDATE devices SET {set_clause} WHERE id=?", values)
    return get_device(device_id)


def delete_device(device_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
    return cur.rowcount > 0


# ------------------------------------------------------------------ #
#  iBox capacity history (for "days until full" projection)            #
# ------------------------------------------------------------------ #

def record_ibox_capacity(ibox_id: str, phys_free_tb: float,
                         phys_total_tb: float, phys_pct: float) -> None:
    """Store one capacity reading. Keep only last 90 days."""
    import time
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - (90 * 86_400_000)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO ibox_capacity_history
               (ibox_id, recorded_at, phys_free_tb, phys_total_tb, phys_pct)
               VALUES (?,?,?,?,?)""",
            (ibox_id, now_ms, phys_free_tb, phys_total_tb, phys_pct),
        )
        conn.execute(
            "DELETE FROM ibox_capacity_history WHERE ibox_id=? AND recorded_at<?",
            (ibox_id, cutoff),
        )


def get_ibox_capacity_history(ibox_id: str, days: int = 30) -> list:
    """Return capacity readings for the last N days, one per day (latest per day)."""
    import time
    cutoff = int(time.time() * 1000) - (days * 86_400_000)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT recorded_at, phys_free_tb, phys_total_tb, phys_pct
               FROM ibox_capacity_history
               WHERE ibox_id=? AND recorded_at>=?
               ORDER BY recorded_at ASC""",
            (ibox_id, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def compute_days_until_full(history: list) -> Optional[float]:
    """Linear regression on phys_free_tb over time → days until 0."""
    if len(history) < 2:
        return None
    # x = hours since first reading, y = phys_free_tb
    t0 = history[0]["recorded_at"]
    xs = [(r["recorded_at"] - t0) / 3_600_000 for r in history]  # hours
    ys = [r["phys_free_tb"] for r in history]
    n  = len(xs)
    sx, sy   = sum(xs), sum(ys)
    sx2      = sum(x*x for x in xs)
    sxy      = sum(x*y for x,y in zip(xs, ys))
    denom    = n * sx2 - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom      # TB/hour (negative = shrinking free)
    if slope >= 0:
        return None                           # growing free space → not filling
    intercept  = (sy - slope * sx) / n
    # current free = intercept + slope * (now - t0 in hours)
    now_x      = (history[-1]["recorded_at"] - t0) / 3_600_000
    current_free = intercept + slope * now_x
    if current_free <= 0:
        return 0.0
    hours_left   = -current_free / slope     # hours until free==0
    return round(hours_left / 24, 1)         # convert to days


# ------------------------------------------------------------------ #
#  customers CRUD                                                      #
# ------------------------------------------------------------------ #

def list_customers() -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, sap_number, customer_name, created_at, updated_at FROM customers ORDER BY sap_number"
        ).fetchall()
    return [dict(r) for r in rows]


def get_customers_map() -> dict:
    """Return {sap_number: customer_name} for all customers."""
    with get_db() as conn:
        rows = conn.execute("SELECT sap_number, customer_name FROM customers").fetchall()
    return {r["sap_number"]: r["customer_name"] for r in rows}


def get_customer(customer_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    return dict(row) if row else None


def create_customer(sap_number: str, customer_name: str) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO customers (sap_number, customer_name) VALUES (?,?)",
            (sap_number.strip(), customer_name.strip()),
        )
        cid = cur.lastrowid
    return get_customer(cid)


def update_customer(customer_id: int, sap_number: str, customer_name: str) -> Optional[dict]:
    with get_db() as conn:
        conn.execute(
            "UPDATE customers SET sap_number=?, customer_name=?, updated_at=datetime('now') WHERE id=?",
            (sap_number.strip(), customer_name.strip(), customer_id),
        )
    return get_customer(customer_id)


def delete_customer(customer_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    return cur.rowcount > 0


def upsert_customers_bulk(pairs: list) -> int:
    """Insert or update customers by sap_number. Returns count of rows processed."""
    count = 0
    with get_db() as conn:
        for sap, name in pairs:
            if not sap or not name:
                continue
            conn.execute(
                """INSERT INTO customers (sap_number, customer_name)
                   VALUES (?, ?)
                   ON CONFLICT(sap_number) DO UPDATE SET
                       customer_name = excluded.customer_name,
                       updated_at    = datetime('now')""",
                (str(sap).strip(), str(name).strip()),
            )
            count += 1
    return count


# ─── vCenter event log ────────────────────────────────────────────────────────

def insert_vcenter_events(events: list, environment: str) -> int:
    """Bulk-insert events; skip duplicates. Returns count inserted."""
    inserted = 0
    with get_db() as conn:
        for e in events:
            if not e:
                continue
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO vcenter_events
                       (environment, event_key, event_type, vm_name, user_name,
                        timestamp, change_info, description)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (environment, int(e.get("key", 0)),
                     e.get("event_type", ""), e.get("vm_name", ""),
                     e.get("user_name", ""), e.get("timestamp", ""),
                     e.get("change_info", ""), e.get("description", "")),
                )
                inserted += cur.rowcount
            except Exception:
                pass
    return inserted


def get_vcenter_events(environment: str | None = None,
                       from_dt: str | None = None,
                       to_dt:   str | None = None,
                       limit: int = 2000) -> list:
    with get_db() as conn:
        where, params = [], []
        if environment and environment != "ALL":
            where.append("e.environment = ?")
            params.append(environment)
        if from_dt:
            where.append("e.timestamp >= ?")
            params.append(from_dt)
        if to_dt:
            where.append("e.timestamp <= ?")
            params.append(to_dt + "T23:59:59" if len(to_dt) == 10 else to_dt)
        sql = """
            SELECT e.*,
                   COALESCE(c.customer_name, '') AS customer_name
            FROM vcenter_events e
            LEFT JOIN vm_sap_cache s
                ON lower(s.vm_name) = lower(e.vm_name) AND lower(s.environment) = lower(e.environment)
            LEFT JOIN customers c
                ON c.sap_number = s.sap_number AND s.sap_number != ''
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.timestamp DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def upsert_vm_sap_batch(vms: list, environment: str) -> None:
    """Store vm_name -> sap_number mapping from a vCenter summary fetch."""
    if not vms:
        return
    with get_db() as conn:
        for vm in vms:
            name = vm.get("name", "")
            sap  = vm.get("sap_number", "")
            if not name:
                continue
            conn.execute(
                """INSERT INTO vm_sap_cache (vm_name, environment, sap_number, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(vm_name, environment) DO UPDATE SET
                       sap_number = excluded.sap_number,
                       updated_at = datetime('now')""",
                (name, environment, sap or ""),
            )


def count_vcenter_events_by_env() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT environment, COUNT(*) AS n FROM vcenter_events GROUP BY environment"
        ).fetchall()
        return {r["environment"]: r["n"] for r in rows}


# ------------------------------------------------------------------ #
#  Authentication / SSO settings                                      #
# ------------------------------------------------------------------ #

def get_auth_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM auth_settings WHERE key=?",
            (key,),
        ).fetchone()
    return str(row["value"]) if row and row["value"] is not None else default


def set_auth_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO auth_settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = datetime('now')""",
            (key, value),
        )


def get_microsoft_auth_config() -> dict:
    secret_enc = get_auth_setting("ms_client_secret", "")
    return {
        "enabled": get_auth_setting("ms_enabled", "false").lower() in ("1", "true", "yes", "on"),
        "tenant_id": get_auth_setting("ms_tenant_id", ""),
        "client_id": get_auth_setting("ms_client_id", ""),
        "client_secret": _decrypt_pw(secret_enc) if secret_enc else "",
        "redirect_uri": get_auth_setting("ms_redirect_uri", ""),
        "scope": get_auth_setting("ms_scope", "openid profile email User.Read"),
        "ssl_enabled": get_auth_setting("ssl_enabled", "true").lower() in ("1", "true", "yes", "on"),
        "ssl_mode": get_auth_setting("ssl_mode", "https_only"),
    }


def save_microsoft_auth_config(cfg: dict) -> None:
    set_auth_setting("ms_enabled", "true" if cfg.get("enabled") else "false")
    set_auth_setting("ms_tenant_id", str(cfg.get("tenant_id", "")).strip())
    set_auth_setting("ms_client_id", str(cfg.get("client_id", "")).strip())
    set_auth_setting("ms_redirect_uri", str(cfg.get("redirect_uri", "")).strip())
    set_auth_setting("ms_scope", str(cfg.get("scope", "openid profile email User.Read")).strip())
    set_auth_setting("ssl_enabled", "true" if cfg.get("ssl_enabled", True) else "false")
    set_auth_setting("ssl_mode", str(cfg.get("ssl_mode", "https_only")).strip())

    client_secret = str(cfg.get("client_secret", "")).strip()
    if client_secret:
        set_auth_setting("ms_client_secret", _encrypt_pw(client_secret))


# ------------------------------------------------------------------ #
#  Authorization allow-list                                           #
# ------------------------------------------------------------------ #

def _normalize_identity(identity: str) -> str:
    s = str(identity or "").strip().lower()
    if "\\" in s:
        s = s.split("\\", 1)[1].strip()
    return s


def _normalize_role(role: str) -> str:
    r = str(role or "").strip().lower()
    return "admin" if r == "admin" else "readonly"


def list_authz_users() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT identity, username, role, created_at, updated_at
               FROM authz_users
               ORDER BY identity ASC"""
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_authz_user(identity: str, role: str = "readonly") -> dict:
    ident = _normalize_identity(identity)
    if not ident:
        raise ValueError("identity is required")

    username = ident.split("@", 1)[0].strip()
    role_n = _normalize_role(role)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO authz_users (identity, username, role, created_at, updated_at)
               VALUES (?, ?, ?, datetime('now'), datetime('now'))
               ON CONFLICT(identity) DO UPDATE SET
                   username = excluded.username,
                   role = excluded.role,
                   updated_at = datetime('now')""",
            (ident, username, role_n),
        )
        row = conn.execute(
            "SELECT identity, username, role, created_at, updated_at FROM authz_users WHERE identity=?",
            (ident,),
        ).fetchone()
    return dict(row) if row else {}


def delete_authz_user(identity: str) -> bool:
    ident = _normalize_identity(identity)
    if not ident:
        return False
    with get_db() as conn:
        cur = conn.execute("DELETE FROM authz_users WHERE identity=?", (ident,))
        return cur.rowcount > 0


def resolve_authz_user(identity: str) -> Optional[dict]:
    ident = _normalize_identity(identity)
    if not ident:
        return None

    short = ident.split("@", 1)[0].strip()
    candidates = [ident]
    if short and short != ident:
        candidates.append(short)

    with get_db() as conn:
        for c in candidates:
            row = conn.execute(
                """SELECT identity, username, role, created_at, updated_at
                   FROM authz_users
                   WHERE identity=? OR username=?
                   LIMIT 1""",
                (c, c),
            ).fetchone()
            if row:
                return dict(row)
    return None


def authz_counts() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, COUNT(*) AS n FROM authz_users GROUP BY role"
        ).fetchall()
        total_row = conn.execute("SELECT COUNT(*) AS n FROM authz_users").fetchone()

    counts = {"admin": 0, "readonly": 0}
    for r in rows:
        role = _normalize_role(str(r["role"]))
        counts[role] = int(r["n"])
    counts["total"] = int(total_row["n"]) if total_row else 0
    return counts


# ------------------------------------------------------------------ #
#  VM inventory snapshots (History page)                               #
# ------------------------------------------------------------------ #

def create_vm_snapshot(taken_by: str = "", note: str = "", protected: bool = False) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO vm_snapshots (taken_at, taken_by, note, protected)
               VALUES (datetime('now'), ?, ?, ?)""",
            (taken_by, note, 1 if protected else 0),
        )
        return cur.lastrowid


def insert_snapshot_items(snapshot_id: int, environment: str, vms: list) -> int:
    if not vms:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT INTO vm_snapshot_items
               (snapshot_id, environment, vm_name, sap_number, cluster, power_state,
                num_cpu, memory_gb, storage_committed_gb, storage_uncommitted_gb, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    snapshot_id, environment,
                    vm.get("name", ""), vm.get("sap_number", ""), vm.get("cluster", ""),
                    vm.get("power_state", ""), vm.get("num_cpu", 0) or 0,
                    vm.get("memory_gb", 0) or 0, vm.get("storage_committed_gb", 0) or 0,
                    vm.get("storage_uncommitted_gb", 0) or 0, json.dumps(vm, ensure_ascii=False),
                )
                for vm in vms
            ],
        )
    return len(vms)


def insert_snapshot_env_data(snapshot_id: int, environment: str, summary: dict) -> None:
    """Stores the FULL get_summary() dict for one environment (vms, hosts, clusters,
    datastores, affinity_rules, counts) — a superset of what insert_snapshot_items() stores
    (which is VM rows only, used by the History comparison report). This is for external
    read-only consumers that need the complete point-in-time picture, not just VM deltas."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO vm_snapshot_env_data (snapshot_id, environment, summary_json)
               VALUES (?, ?, ?)
               ON CONFLICT(snapshot_id, environment) DO UPDATE SET summary_json=excluded.summary_json""",
            (snapshot_id, environment, json.dumps(summary, ensure_ascii=False)),
        )


def get_snapshot_env_data(snapshot_id: int, environment: Optional[str] = None) -> list:
    with get_db() as conn:
        if environment and environment != "ALL":
            rows = conn.execute(
                "SELECT environment, summary_json FROM vm_snapshot_env_data WHERE snapshot_id = ? AND environment = ?",
                (snapshot_id, environment),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT environment, summary_json FROM vm_snapshot_env_data WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()
    return [{"environment": r["environment"], "summary": json.loads(r["summary_json"])} for r in rows]


def finalize_snapshot(snapshot_id: int, vm_count: int, envs_ok: list) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE vm_snapshots SET vm_count = ?, envs_ok = ? WHERE id = ?",
            (vm_count, ",".join(envs_ok), snapshot_id),
        )


def list_snapshots(limit: int = 100) -> list:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, taken_at, taken_by, note, vm_count, envs_ok, protected
               FROM vm_snapshots ORDER BY taken_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_snapshot(snapshot_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, taken_at, taken_by, note, vm_count, envs_ok, protected
               FROM vm_snapshots WHERE id = ?""",
            (snapshot_id,),
        ).fetchone()
    return dict(row) if row else None


def get_snapshot_items(snapshot_id: int, environment: Optional[str] = None) -> list:
    with get_db() as conn:
        if environment and environment != "ALL":
            rows = conn.execute(
                """SELECT environment, data_json FROM vm_snapshot_items
                   WHERE snapshot_id = ? AND environment = ?""",
                (snapshot_id, environment),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT environment, data_json FROM vm_snapshot_items WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()
    items = []
    for r in rows:
        vm = json.loads(r["data_json"])
        vm["_vc"] = r["environment"]
        items.append(vm)
    return items


def delete_snapshot(snapshot_id: int) -> bool:
    with get_db() as conn:
        conn.execute("DELETE FROM vm_snapshot_items WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM vm_snapshot_env_data WHERE snapshot_id = ?", (snapshot_id,))
        cur = conn.execute("DELETE FROM vm_snapshots WHERE id = ?", (snapshot_id,))
        return cur.rowcount > 0


def prune_old_snapshots(keep: int = 50) -> int:
    """Keep only the `keep` most recent NON-protected snapshots; delete older ones (and their
    items). Protected snapshots (e.g. the automatic monthly archive) are never counted here and
    never auto-deleted — they only come out via delete_snapshot(), which the caller must gate
    behind the protected-delete password."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM vm_snapshots WHERE protected = 0 ORDER BY taken_at DESC LIMIT -1 OFFSET ?",
            (keep,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM vm_snapshot_items WHERE snapshot_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM vm_snapshot_env_data WHERE snapshot_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM vm_snapshots WHERE id IN ({placeholders})", ids)
        return len(ids)


def has_protected_snapshot_today() -> bool:
    """True if a protected snapshot was already taken today — guards the monthly-snapshot
    scheduler against creating a duplicate if the service restarts more than once during the
    1st-of-month 00:01 window."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM vm_snapshots WHERE protected = 1 AND date(taken_at) = date('now') LIMIT 1"
        ).fetchone()
    return row is not None


def has_snapshot_today_by(taken_by: str) -> bool:
    """True if a snapshot with this exact taken_by value was already created today — guards
    the daily-snapshot scheduler against duplicates on repeated same-day restarts."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM vm_snapshots WHERE taken_by = ? AND date(taken_at) = date('now') LIMIT 1",
            (taken_by,),
        ).fetchone()
    return row is not None


# ------------------------------------------------------------------ #
#  customer_billing_config CRUD                                        #
# ------------------------------------------------------------------ #

_BILLING_COLS = (
    "customer_name, enabled, free_pct_cpu, free_pct_ram, free_pct_stor, "
    "price_vcpu, price_ram_gb, price_storage_gb, updated_at"
)


def list_billing_configs() -> list:
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {_BILLING_COLS} FROM customer_billing_config ORDER BY customer_name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_billing_config(customer_name: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            f"SELECT {_BILLING_COLS} FROM customer_billing_config WHERE customer_name = ?",
            (customer_name,),
        ).fetchone()
    return dict(row) if row else None


def upsert_billing_config(
    customer_name: str, enabled: bool,
    free_pct_cpu: float, free_pct_ram: float, free_pct_stor: float,
    price_vcpu: float, price_ram_gb: float, price_storage_gb: float,
) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO customer_billing_config
                   (customer_name, enabled, free_pct_cpu, free_pct_ram, free_pct_stor,
                    price_vcpu, price_ram_gb, price_storage_gb, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(customer_name) DO UPDATE SET
                   enabled=excluded.enabled,
                   free_pct_cpu=excluded.free_pct_cpu,
                   free_pct_ram=excluded.free_pct_ram,
                   free_pct_stor=excluded.free_pct_stor,
                   price_vcpu=excluded.price_vcpu,
                   price_ram_gb=excluded.price_ram_gb,
                   price_storage_gb=excluded.price_storage_gb,
                   updated_at=datetime('now')""",
            (customer_name, 1 if enabled else 0, free_pct_cpu, free_pct_ram, free_pct_stor,
             price_vcpu, price_ram_gb, price_storage_gb),
        )


def delete_billing_config(customer_name: str) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM customer_billing_config WHERE customer_name = ?", (customer_name,))
        return cur.rowcount > 0
