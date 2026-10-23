"""Stockage des données vivantes (comptes, droits, usage, demandes, audit).

SQLite pour démarrer. Sur Streamlit Community Cloud le disque est effacé au
redémarrage : en production, remplacer `connect()` par une connexion
PostgreSQL (section 5 du cadrage). Le reste du code ne change pas.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get("REGBRIDGE_DATA", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "app.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    organisation TEXT DEFAULT '',
    pwd_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',          -- 'user' ou 'admin'
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entitlements (      -- accès payants activés par l'admin
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_id TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'pro',
    start_date TEXT NOT NULL,
    end_date TEXT,                              -- NULL = sans échéance
    granted_by TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (             -- consommation des quotas
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_id TEXT NOT NULL,
    action TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    service_id TEXT NOT NULL,
    message TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'en_attente',  -- en_attente, accordee, refusee
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_overrides (   -- quotas gratuits modifiés par l'admin
    service_id TEXT NOT NULL,
    action TEXT NOT NULL,
    monthly_limit INTEGER NOT NULL,
    PRIMARY KEY (service_id, action)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT DEFAULT ''
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    with _lock, connect() as con:
        con.executescript(SCHEMA)


def query(sql: str, params=()) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def execute(sql: str, params=()) -> int:
    with _lock, connect() as con:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid


def audit(actor: str, action: str, detail=None) -> None:
    """Journal d'audit en ajout seulement (jamais modifié ni supprimé)."""
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    execute("INSERT INTO audit (ts, actor, action, detail) VALUES (?,?,?,?)", (now(), actor, action, detail or ""))
