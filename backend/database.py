"""
SQLite database layer for UCS Dashboard.
Handles:
  - manual_data  (replaces per-farm JSON files)
  - devices      (device registry: UCS, InfiniBand, Host, Storage, …)
"""

import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime
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
                host        TEXT    DEFAULT '',
                username    TEXT    DEFAULT '',
                password    TEXT    DEFAULT '',
                port        INTEGER DEFAULT 443,
                protocol    TEXT    DEFAULT 'https',
                notes       TEXT    DEFAULT '',
                enabled     INTEGER DEFAULT 1,
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );
        """)


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
#  devices CRUD                                                        #
# ------------------------------------------------------------------ #

def _row_to_dict(row) -> dict:
    return dict(row)


def list_devices(farm: Optional[str] = None) -> list[dict]:
    with get_db() as conn:
        if farm:
            rows = conn.execute(
                "SELECT * FROM devices WHERE farm=? ORDER BY type, name", (farm,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM devices ORDER BY farm, type, name"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_device(device_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    return _row_to_dict(row) if row else None


def create_device(farm: str, name: str, dtype: str, host: str = "",
                  username: str = "", password: str = "", port: int = 443,
                  protocol: str = "https", notes: str = "", enabled: bool = True) -> dict:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO devices (farm, name, type, host, username, password,
               port, protocol, notes, enabled)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (farm, name, dtype, host, username, password,
             port, protocol, notes, 1 if enabled else 0),
        )
        device_id = cur.lastrowid
    return get_device(device_id)


def update_device(device_id: int, **fields) -> Optional[dict]:
    allowed = {"farm","name","type","host","username","password",
               "port","protocol","notes","enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_device(device_id)
    updates["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [device_id]
    with get_db() as conn:
        conn.execute(f"UPDATE devices SET {set_clause} WHERE id=?", values)
    return get_device(device_id)


def delete_device(device_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
    return cur.rowcount > 0
