"""Droits d'accès et quotas : un seul point de décision pour toute l'application.

Niveaux d'accès d'un utilisateur à un service :
- "full"   : administrateur, ou abonnement actif activé par l'administrateur ;
- "free"   : le service a des quotas gratuits ;
- "locked" : service payant non activé (visible dans le lanceur, mais fermé).
"""
from datetime import date, datetime, timezone

from core import db
from core.catalog import SERVICES


def _today() -> str:
    return date.today().isoformat()


def active_entitlements(user_id: int) -> list[dict]:
    return db.query(
        "SELECT * FROM entitlements WHERE user_id=? AND revoked=0 AND start_date<=? AND (end_date IS NULL OR end_date>=?)",
        (user_id, _today(), _today()),
    )


def access_level(user: dict, service_id: str) -> str:
    if user["role"] == "admin":
        return "full"
    if any(e["service_id"] == service_id for e in active_entitlements(user["id"])):
        return "full"
    if SERVICES[service_id].get("free"):
        return "free"
    return "locked"


def free_limit(service_id: str, action: str) -> int:
    o = db.query("SELECT monthly_limit FROM quota_overrides WHERE service_id=? AND action=?", (service_id, action))
    if o:
        return o[0]["monthly_limit"]
    return SERVICES[service_id].get("free", {}).get(action, 0)


def used_this_month(user_id: int, service_id: str, action: str) -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r = db.query(
        "SELECT COUNT(*) AS n FROM usage WHERE user_id=? AND service_id=? AND action=? AND substr(ts,1,7)=?",
        (user_id, service_id, action, month),
    )
    return r[0]["n"]


def quota_status(user: dict, service_id: str, action: str) -> tuple[bool, int, int | None]:
    """(autorisé, utilisé, limite) ; limite None = illimité."""
    if access_level(user, service_id) == "full":
        return True, used_this_month(user["id"], service_id, action), None
    limit = free_limit(service_id, action)
    used = used_this_month(user["id"], service_id, action)
    return used < limit, used, limit


def consume(user: dict, service_id: str, action: str) -> bool:
    """Vérifie puis enregistre une utilisation. Retourne False si le quota est atteint."""
    ok, _, _ = quota_status(user, service_id, action)
    if not ok:
        return False
    if user.get("preview"):          # aperçu de l'administrateur : ne consomme pas le quota du client
        return True
    db.execute("INSERT INTO usage (user_id, service_id, action, ts) VALUES (?,?,?,?)",
               (user["id"], service_id, action, db.now()))
    return True


def tab_allowed(user: dict, service_id: str, tab: str) -> bool:
    lvl = access_level(user, service_id)
    if lvl == "full":
        return True
    if lvl == "free":
        return tab in SERVICES[service_id].get("free_tabs", [])
    return False


def grant(user_id: int, service_id: str, actor: str, end_date: str | None = None, plan: str = "pro") -> None:
    db.execute(
        "INSERT INTO entitlements (user_id, service_id, plan, start_date, end_date, granted_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, service_id, plan, _today(), end_date, actor, db.now()),
    )
    db.audit(actor, "acces_active", {"user_id": user_id, "service": service_id, "fin": end_date, "offre": plan})


def revoke(entitlement_id: int, actor: str) -> None:
    db.execute("UPDATE entitlements SET revoked=1 WHERE id=?", (entitlement_id,))
    db.audit(actor, "acces_retire", {"entitlement_id": entitlement_id})


def request_access(user: dict, service_id: str, message: str = "") -> None:
    pending = db.query("SELECT id FROM access_requests WHERE user_id=? AND service_id=? AND status='en_attente'",
                       (user["id"], service_id))
    if pending:
        return
    db.execute("INSERT INTO access_requests (user_id, service_id, message, ts) VALUES (?,?,?,?)",
               (user["id"], service_id, message, db.now()))
    db.audit(user["email"], "demande_acces", {"service": service_id})
