"""Référentiels publics en CSV versionnés (section 20 du cadrage).

Règles : UTF-8 avec BOM, séparateur point-virgule, dates ISO, ajout seulement
(on marque « radié » ou « rejeté », on n'efface pas), manifeste avec empreinte.
Les données privées des clients ne passent jamais par ce module.
"""
import hashlib
import os
import threading
from datetime import datetime, timezone

import pandas as pd

from core.db import DATA_DIR

REF_DIR = os.path.join(DATA_DIR, "referentiels")
MANIFEST = os.path.join(REF_DIR, "manifest.csv")
_lock = threading.Lock()


def path(name: str) -> str:
    return os.path.join(REF_DIR, name)


def read(name: str) -> pd.DataFrame:
    p = path(name)
    if not os.path.exists(p):
        return pd.DataFrame()
    return pd.read_csv(p, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _write(name: str, df: pd.DataFrame) -> None:
    os.makedirs(REF_DIR, exist_ok=True)
    tmp = path(name) + ".tmp"
    df.to_csv(tmp, sep=";", index=False, encoding="utf-8-sig")
    os.replace(tmp, path(name))   # écriture atomique : jamais de fichier à moitié écrit
    _update_manifest(name, len(df))


def append(name: str, rows: list[dict]) -> None:
    with _lock:
        df = read(name)
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True).fillna("")
        _write(name, df)


def upsert(name: str, key: str, row: dict) -> str:
    """Met à jour la ligne `key` ou l'ajoute. Retourne 'ajout', 'maj' ou 'inchange'."""
    with _lock:
        df = read(name)
        row = {k: ("" if v is None else str(v)) for k, v in row.items()}
        if not df.empty and key in df.columns and row[key] in set(df[key]):
            idx = df.index[df[key] == row[key]][0]
            changed = {c: v for c, v in row.items() if v != "" and str(df.at[idx, c] if c in df.columns else "") != v}
            if not changed:
                return "inchange"
            for c, v in changed.items():
                if c not in df.columns:
                    df[c] = ""
                df.at[idx, c] = v
            _write(name, df)
            return "maj"
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True).fillna("")
        _write(name, df)
        return "ajout"


def update_where(name: str, key: str, value: str, changes: dict) -> None:
    with _lock:
        df = read(name)
        mask = df[key] == value
        for c, v in changes.items():
            if c not in df.columns:
                df[c] = ""
            df.loc[mask, c] = v
        _write(name, df)


def _update_manifest(name: str, nrows: int) -> None:
    with open(path(name), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    m = pd.read_csv(MANIFEST, sep=";", encoding="utf-8-sig", dtype=str) if os.path.exists(MANIFEST) else pd.DataFrame(
        columns=["fichier", "lignes", "empreinte_sha256", "mis_a_jour"])
    m = m[m["fichier"] != name]
    m = pd.concat([m, pd.DataFrame([{"fichier": name, "lignes": nrows, "empreinte_sha256": digest,
                                     "mis_a_jour": datetime.now(timezone.utc).isoformat(timespec="seconds")}])])
    m.sort_values("fichier").to_csv(MANIFEST, sep=";", index=False, encoding="utf-8-sig")


def manifest() -> pd.DataFrame:
    if not os.path.exists(MANIFEST):
        return pd.DataFrame()
    return pd.read_csv(MANIFEST, sep=";", encoding="utf-8-sig", dtype=str)


def verify(name: str) -> bool:
    """Vérifie que le fichier n'a pas été modifié hors procédure."""
    m = manifest()
    if m.empty or name not in set(m["fichier"]):
        return False
    with open(path(name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest() == m.loc[m["fichier"] == name, "empreinte_sha256"].iloc[0]
