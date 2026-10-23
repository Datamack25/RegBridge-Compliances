"""Stockage des données vivantes (comptes, droits, usage, demandes, audit) avec sauvegarde persistante.

Problème résolu : sur Streamlit Community Cloud, le disque est effacé à chaque redémarrage
(mise à jour du dépôt, mise en veille, « Reboot app »). Sans sauvegarde, les comptes disparaissent
et l'utilisateur obtient « Identifiants incorrects ».

Fonctionnement :
1. Chaque écriture (INSERT, UPDATE, DELETE) exporte la table modifiée en CSV dans data/backup/.
2. Si un dépôt GitHub PRIVÉ est configuré dans les secrets, le CSV y est aussi envoyé.
3. Au démarrage, si la base est vide, les tables sont rechargées depuis GitHub (ou data/backup/).

Les mots de passe ne sont jamais enregistrés en clair : users.csv contient l'empreinte
(PBKDF2-SHA256) et le sel. La plateforme vérifie le mot de passe saisi sans le connaître.

Secrets Streamlit à ajouter (Settings > Secrets) :
    GITHUB_TOKEN  = "github_pat_..."          # jeton à accès limité : Contents en lecture/écriture sur ce dépôt seul
    GITHUB_REPO   = "votre-compte/regbridge-data"   # dépôt PRIVÉ, distinct du dépôt de l'application
    GITHUB_BRANCH = "main"                     # facultatif
"""
import base64
import csv
import io
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

DATA_DIR = os.environ.get("REGBRIDGE_DATA", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "app.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")
_lock = threading.Lock()

# Tables sauvegardées. Les critiques partent sur GitHub à chaque écriture ;
# les volumineuses (usage, audit) au plus toutes les 5 minutes.
CRITICAL = {"users", "entitlements", "access_requests", "quota_overrides", "private_relations"}
DEFERRED = {"usage", "audit"}
DEFER_SECONDS = 300
NULL = "\\N"                      # marque une valeur NULL dans les CSV (différente d'une chaîne vide)

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
CREATE TABLE IF NOT EXISTS private_relations ( -- relations d'affaires privées d'une organisation
    id INTEGER PRIMARY KEY AUTOINCREMENT, siren TEXT NOT NULL, organisation TEXT NOT NULL, type_relation TEXT NOT NULL,
    contrepartie TEXT NOT NULL, contrepartie_siren TEXT DEFAULT '', pays TEXT DEFAULT '', part_pct TEXT DEFAULT '',
    source TEXT DEFAULT '', note TEXT DEFAULT '', ajoute_par TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT DEFAULT ''
);
"""
TABLES = ["users", "entitlements", "access_requests", "quota_overrides", "private_relations", "usage", "audit"]
_WRITE_RE = re.compile(r"^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", re.IGNORECASE)
_last_push: dict[str, float] = {}
_last_hash: dict[str, str] = {}
_restored = False


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ------------------------------------------------------------------ configuration GitHub
def _settings() -> dict:
    """Lit les secrets Streamlit, puis les variables d'environnement."""
    cfg = {}
    try:
        import streamlit as st
        for k in ("GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH", "GITHUB_DIR"):
            if k in st.secrets:
                cfg[k] = str(st.secrets[k])
    except Exception:  # pas de secrets.toml en local
        pass
    for k in ("GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH", "GITHUB_DIR"):
        cfg.setdefault(k, os.environ.get(k, ""))
    cfg["GITHUB_BRANCH"] = cfg["GITHUB_BRANCH"] or "main"
    cfg["GITHUB_DIR"] = (cfg["GITHUB_DIR"] or "backup").strip("/")
    return cfg


def github_enabled() -> bool:
    c = _settings()
    return bool(c["GITHUB_TOKEN"] and c["GITHUB_REPO"])


def _gh(method: str, path: str, **kw):
    import requests
    c = _settings()
    url = f"https://api.github.com/repos/{c['GITHUB_REPO']}/contents/{c['GITHUB_DIR']}/{path}"
    headers = {"Authorization": f"Bearer {c['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    return requests.request(method, url, headers=headers, timeout=15, **kw), c


def _gh_read(name: str) -> str | None:
    try:
        r, _ = _gh("GET", name, params={"ref": c_branch()})
        if r.status_code == 200:
            return base64.b64decode(r.json()["content"]).decode("utf-8")
    except Exception as e:  # réseau, jeton invalide : on continue sans sauvegarde distante
        print(f"[sauvegarde] lecture GitHub impossible pour {name} : {e}")
    return None


def c_branch() -> str:
    return _settings()["GITHUB_BRANCH"]


def _gh_write(name: str, text: str) -> None:
    try:
        r, _ = _gh("GET", name, params={"ref": c_branch()})
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": f"Sauvegarde {name} ({now()})", "branch": c_branch(),
                "content": base64.b64encode(text.encode("utf-8")).decode()}
        if sha:
            body["sha"] = sha
        r, _ = _gh("PUT", name, data=json.dumps(body))
        if r.status_code not in (200, 201):
            print(f"[sauvegarde] envoi GitHub refusé pour {name} : {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[sauvegarde] envoi GitHub impossible pour {name} : {e}")


# ------------------------------------------------------------------ export / restauration
def _export(table: str) -> str:
    with connect() as con:
        cur = con.execute(f"SELECT * FROM {table} ORDER BY rowid")
        cols = [d[0] for d in cur.description]
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(cols)
        for row in cur.fetchall():
            w.writerow([NULL if v is None else v for v in row])
    return out.getvalue()


def backup(table: str, force_remote: bool = False) -> None:
    """Écrit la table en CSV local, puis sur GitHub (immédiatement ou de façon différée)."""
    if table not in TABLES:
        return
    text = _export(table)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(os.path.join(BACKUP_DIR, f"{table}.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if not github_enabled():
        return
    digest = str(hash(text))
    if _last_hash.get(table) == digest:
        return
    due = force_remote or table in CRITICAL or time.time() - _last_push.get(table, 0) >= DEFER_SECONDS
    if due:
        _gh_write(f"{table}.csv", text)
        _last_push[table], _last_hash[table] = time.time(), digest


def flush() -> None:
    """Envoie toutes les tables (à appeler avant un arrêt prévu ou depuis la console d'administration)."""
    for t in TABLES:
        backup(t, force_remote=True)


def _load_csv(text: str) -> tuple[list[str], list[list]]:
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rows:
        return [], []
    return rows[0], [[None if v == NULL else v for v in r] for r in rows[1:]]


def restore() -> int:
    """Recharge les tables depuis GitHub (prioritaire) ou data/backup si la base est vide. Retourne le nombre de lignes."""
    total = 0
    with _lock, connect() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return 0
        for t in TABLES:
            text = _gh_read(f"{t}.csv") if github_enabled() else None
            local = os.path.join(BACKUP_DIR, f"{t}.csv")
            if text is None and os.path.exists(local):
                with open(local, encoding="utf-8") as f:
                    text = f.read()
            if not text:
                continue
            cols, rows = _load_csv(text)
            known = {r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()}
            keep = [i for i, c in enumerate(cols) if c in known]
            if not keep or not rows:
                continue
            names = ", ".join(cols[i] for i in keep)
            marks = ", ".join("?" for _ in keep)
            con.executemany(f"INSERT OR IGNORE INTO {t} ({names}) VALUES ({marks})",
                            [[r[i] if i < len(r) else None for i in keep] for r in rows])
            total += len(rows)
        con.commit()
    if total:
        print(f"[sauvegarde] {total} ligne(s) restaurée(s) au démarrage.")
    return total


# ------------------------------------------------------------------ API utilisée par le reste du code
def init() -> None:
    global _restored
    with _lock, connect() as con:
        con.executescript(SCHEMA)
    if not _restored:          # une seule tentative de restauration par démarrage du serveur
        _restored = True
        restore()


def query(sql: str, params=()) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def execute(sql: str, params=()) -> int:
    with _lock, connect() as con:
        cur = con.execute(sql, params)
        con.commit()
        last = cur.lastrowid
    m = _WRITE_RE.match(sql)
    if m:
        backup(m.group(1).lower())
    return last


def audit(actor: str, action: str, detail=None) -> None:
    """Journal d'audit en ajout seulement (jamais modifié ni supprimé)."""
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    execute("INSERT INTO audit (ts, actor, action, detail) VALUES (?,?,?,?)", (now(), actor, action, detail or ""))
