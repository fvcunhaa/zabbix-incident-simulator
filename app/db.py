import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.lock = threading.RLock()
        self.init()

    @contextmanager
    def connect(self):
        with self.lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def init(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    host TEXT PRIMARY KEY,
                    hostid TEXT NOT NULL,
                    client TEXT NOT NULL,
                    device_type TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bindings (
                    host TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    itemid TEXT NOT NULL,
                    triggerid TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    PRIMARY KEY (host, scenario_id)
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    client TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    scenario_name TEXT NOT NULL,
                    eventid TEXT,
                    triggerid TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    analyst TEXT NOT NULL,
                    state TEXT NOT NULL,
                    problem_value REAL NOT NULL,
                    recovery_value REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    ack_due_at TEXT NOT NULL,
                    treatment_due_at TEXT NOT NULL,
                    resolve_due_at TEXT NOT NULL,
                    ack_at TEXT,
                    treatment_at TEXT,
                    resolved_at TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents(state);
                CREATE INDEX IF NOT EXISTS idx_incidents_host_state ON incidents(host, state);
                """
            )

    @staticmethod
    def now_iso():
        return datetime.now(timezone.utc).isoformat()

    def upsert_asset(self, host, hostid, client, device_type):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO assets(host,hostid,client,device_type) VALUES(?,?,?,?)
                ON CONFLICT(host) DO UPDATE SET hostid=excluded.hostid, client=excluded.client,
                device_type=excluded.device_type""",
                (host, hostid, client, device_type),
            )

    def upsert_binding(self, host, scenario_id, itemid, triggerid, item_key):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO bindings(host,scenario_id,itemid,triggerid,item_key) VALUES(?,?,?,?,?)
                ON CONFLICT(host,scenario_id) DO UPDATE SET itemid=excluded.itemid,
                triggerid=excluded.triggerid,item_key=excluded.item_key""",
                (host, scenario_id, itemid, triggerid, item_key),
            )

    def list_assets(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM assets ORDER BY host")]

    def get_binding(self, host, scenario_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bindings WHERE host=? AND scenario_id=?", (host, scenario_id)
            ).fetchone()
            return dict(row) if row else None

    def active_hosts(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT host FROM incidents WHERE state NOT IN ('resolved','failed')"
            ).fetchall()
            return {r[0] for r in rows}

    def active_count(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE state NOT IN ('resolved','failed')"
            ).fetchone()[0]

    def insert_incident(self, data: dict) -> int:
        keys = list(data.keys())
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO incidents({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
                [data[k] for k in keys],
            )
            return int(cur.lastrowid)

    def update_incident(self, incident_id: int, **fields):
        if not fields:
            return
        assignments = ",".join(f"{k}=?" for k in fields)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE incidents SET {assignments} WHERE id=?",
                list(fields.values()) + [incident_id],
            )

    def get_incident(self, incident_id: int):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
            return dict(row) if row else None

    def list_incidents(self, active_only=False, limit=100):
        where = "WHERE state NOT IN ('resolved','failed')" if active_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM incidents {where} ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
