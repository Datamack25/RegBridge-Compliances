"""Comptes et authentification.

- Mots de passe hachés (PBKDF2-SHA256, 200 000 itérations, sel aléatoire).
- Aucun compte administrateur par défaut publié : le premier administrateur
  est créé au premier lancement, à partir des secrets Streamlit
  (ADMIN_EMAIL, ADMIN_PASSWORD) ou via l'écran d'installation.
"""
import hashlib
import hmac
import os
import secrets

from core import db

ITERATIONS = 200_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "10 caractères minimum."
    if password.lower() == password or not any(ch.isdigit() for ch in password):
        return "Il faut au moins une majuscule et un chiffre."
    return None


def create_user(email: str, name: str, password: str, role: str = "user", organisation: str = "") -> int:
    email = email.strip().lower()
    if db.query("SELECT id FROM users WHERE email=?", (email,)):
        raise ValueError("Un compte existe déjà avec cette adresse.")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    salt = secrets.token_hex(16)
    uid = db.execute(
        "INSERT INTO users (email, name, organisation, pwd_hash, salt, role, created_at) VALUES (?,?,?,?,?,?,?)",
        (email, name.strip(), organisation.strip(), _hash(password, salt), salt, role, db.now()),
    )
    db.audit(email, "compte_cree", {"role": role})
    return uid


def authenticate(email: str, password: str) -> dict | None:
    rows = db.query("SELECT * FROM users WHERE email=? AND active=1", (email.strip().lower(),))
    if not rows:
        return None
    u = rows[0]
    if hmac.compare_digest(u["pwd_hash"], _hash(password, u["salt"])):
        db.audit(u["email"], "connexion")
        return {k: u[k] for k in ("id", "email", "name", "organisation", "role")}
    db.audit(email, "echec_connexion")
    return None


def set_password(user_id: int, password: str, actor: str) -> None:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    salt = secrets.token_hex(16)
    db.execute("UPDATE users SET pwd_hash=?, salt=? WHERE id=?", (_hash(password, salt), salt, user_id))
    db.audit(actor, "mot_de_passe_change", {"user_id": user_id})


def admin_exists() -> bool:
    return bool(db.query("SELECT id FROM users WHERE role='admin' AND active=1"))


def bootstrap_admin_from_secrets(secrets_obj) -> None:
    """Crée l'administrateur à partir des secrets s'il n'existe pas encore."""
    if admin_exists():
        return
    try:
        email = secrets_obj.get("ADMIN_EMAIL") or os.environ.get("ADMIN_EMAIL")
        pwd = secrets_obj.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    except Exception:  # pas de fichier secrets.toml
        email, pwd = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if email and pwd:
        create_user(email, "Administrateur", pwd, role="admin")
