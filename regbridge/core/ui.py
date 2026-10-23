"""Éléments d'interface partagés : thème, lanceur de services, en-tête, exports, onglets verrouillés."""
import importlib

import streamlit as st

from core import entitlements as ent
from core import reports
from core.catalog import ACTION_LABELS, FAMILY_ORDER, SERVICES

CSS = """
<style>
:root { --navy:#0B2545; --teal:#0E7C86; --light:#EEF3F8; --line:#D5DCE4; --grey:#5B6770; }
.block-container { padding-top: 1.6rem; max-width: 1250px; }
.rb-brand { font-weight:800; color:var(--navy); font-size:1.35rem; letter-spacing:.2px; }
.rb-sub { color:var(--grey); font-size:.86rem; }
.rb-tile-icon { font-size:1.9rem; line-height:1; }
.rb-tile-name { font-weight:700; color:var(--navy); margin-top:.35rem; }
.rb-tile-pitch { color:var(--grey); font-size:.8rem; min-height:2.6rem; }
.rb-badge { display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.72rem; font-weight:700; }
.rb-full { background:#E3F4EC; color:#1F6B45; }
.rb-free { background:#FFF3D6; color:#8A6100; }
.rb-locked { background:#EEF0F3; color:#5B6770; }
.rb-admin { background:#0B2545; color:#fff; }
.rb-family { color:var(--teal); font-weight:700; text-transform:uppercase; font-size:.75rem; letter-spacing:.08em; margin:.6rem 0 .2rem; }
.rb-kpi { background:var(--light); border-left:4px solid var(--teal); padding:.6rem .8rem; border-radius:6px; }
.rb-kpi b { font-size:1.45rem; color:var(--navy); display:block; }
.rb-kpi span { color:var(--grey); font-size:.8rem; }
</style>
"""


def setup_page() -> None:
    st.set_page_config(page_title="RegBridge", page_icon="🛡️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def kpis(items: list[tuple[str, str]]) -> None:
    cols = st.columns(len(items))
    for c, (v, l) in zip(cols, items):
        c.markdown(f"<div class='rb-kpi'><b>{v}</b><span>{l}</span></div>", unsafe_allow_html=True)


def badge(user: dict, sid: str) -> str:
    if user["role"] == "admin":
        return "<span class='rb-badge rb-admin'>Administrateur</span>"
    lvl = ent.access_level(user, sid)
    if lvl == "full":
        return "<span class='rb-badge rb-full'>Abonné</span>"
    if lvl == "free":
        parts = []
        for action in SERVICES[sid]["free"]:
            _, used, limit = ent.quota_status(user, sid, action)
            parts.append(f"{used}/{limit} {ACTION_LABELS.get(action, action).split()[0]}")
        return "<span class='rb-badge rb-free'>Gratuit · " + " · ".join(parts) + "</span>"
    return "<span class='rb-badge rb-locked'>🔒 Sur abonnement</span>"


def open_service(sid: str) -> None:
    st.session_state.service = sid
    st.query_params["service"] = sid


@st.dialog("Demander l'accès")
def request_dialog(user: dict, sid: str) -> None:
    s = SERVICES[sid]
    st.markdown(f"**{s['icon']} {s['name']}**  \n{s['pitch']}")
    st.caption("Votre demande est transmise à l'administrateur, qui active l'accès après accord sur l'offre.")
    msg = st.text_area("Message (facultatif)", placeholder="Besoin, nombre d'utilisateurs, échéance...")
    if st.button("Envoyer la demande", type="primary", width="stretch"):
        ent.request_access(user, sid, msg)
        st.success("Demande envoyée. Vous serez prévenu dès l'activation.")


def launcher(user: dict, compact: bool = False) -> None:
    """Grille de services façon Microsoft 365 : tous les services visibles, accès selon les droits."""
    for fam in FAMILY_ORDER:
        sids = [k for k, v in SERVICES.items() if v["family"] == fam]
        if not sids:
            continue
        st.markdown(f"<div class='rb-family'>{fam}</div>", unsafe_allow_html=True)
        ncol = 4 if not compact else 3
        cols = st.columns(ncol)
        for i, sid in enumerate(sids):
            s = SERVICES[sid]
            lvl = ent.access_level(user, sid)
            with cols[i % ncol].container(border=True):
                st.markdown(f"<div class='rb-tile-icon'>{s['icon']}</div><div class='rb-tile-name'>{s['name']}</div>",
                            unsafe_allow_html=True)
                if not compact:
                    st.markdown(f"<div class='rb-tile-pitch'>{s['pitch']}</div>", unsafe_allow_html=True)
                st.markdown(badge(user, sid), unsafe_allow_html=True)
                key = f"tile_{'c' if compact else 'g'}_{sid}"
                if lvl == "locked":
                    if st.button("Demander l'accès", key=key, width="stretch"):
                        request_dialog(user, sid)
                elif st.button("Ouvrir", key=key, type="primary" if lvl == "full" else "secondary",
                               width="stretch"):
                    open_service(sid)
                    st.rerun()


def locked_panel(user: dict, sid: str, tab: str) -> None:
    st.info(f"🔒 L'onglet **{tab}** fait partie de l'abonnement {SERVICES[sid]['name']}.")
    if st.button("Demander l'accès complet", key=f"lock_{sid}_{tab}"):
        request_dialog(user, sid)


def quota_line(user: dict, sid: str, action: str) -> None:
    ok, used, limit = ent.quota_status(user, sid, action)
    if limit is None:
        return
    label = ACTION_LABELS.get(action, action)
    if ok:
        st.caption(f"Offre gratuite : {used}/{limit} {label} utilisés ce mois-ci.")
    else:
        st.warning(f"Quota gratuit atteint ({limit} {label} ce mois-ci). La consultation reste possible ; "
                   "l'abonnement lève la limite.")


def export_panel(user: dict, sid: str, report_ctx: dict, key: str, formats=("PDF", "Word", "Image PNG", "Image JPEG", "CSV")):
    """Bloc d'export commun à tous les services : un clic sur Générer consomme 1 export du quota."""
    free = ent.access_level(user, sid) == "free"
    report_ctx = {**report_ctx, "free": free, "author": user["name"]}
    c1, c2 = st.columns([2, 1])
    fmt = c1.selectbox("Format", formats, key=f"fmt_{key}")
    quota_line(user, sid, "export")
    if c2.button("Générer", key=f"gen_{key}", type="primary", width="stretch"):
        if not ent.consume(user, sid, "export"):
            st.error("Quota d'exports atteint pour ce mois.")
            return
        fn, ext, mime = reports.FORMATS[fmt]
        with st.spinner("Génération du document..."):
            st.session_state[f"file_{key}"] = (fn(report_ctx), reports.filename(report_ctx, ext), mime)
    if f"file_{key}" in st.session_state:
        data, name, mime = st.session_state[f"file_{key}"]
        st.download_button(f"Télécharger {name}", data, file_name=name, mime=mime, key=f"dl_{key}",
                           width="stretch")


def render_service(user: dict, sid: str) -> None:
    s = SERVICES[sid]
    lvl = ent.access_level(user, sid)
    head, grid = st.columns([5, 1])
    head.markdown(f"<span class='rb-brand'>{s['icon']} {s['name']}</span> &nbsp; {badge(user, sid)}",
                  unsafe_allow_html=True)
    head.caption(s["pitch"])
    with grid.popover("⊞ Services", width="stretch"):
        launcher(user, compact=True)
    if lvl == "locked":
        st.info("🔒 Ce service est disponible sur abonnement.")
        if st.button("Demander l'accès", type="primary"):
            request_dialog(user, sid)
        return
    module = importlib.import_module(f"services.{s['module']}")
    labels = [t if ent.tab_allowed(user, sid, t) else f"🔒 {t}" for t in s["tabs"]]
    for tab, label, container in zip(s["tabs"], labels, st.tabs(labels)):
        with container:
            if ent.tab_allowed(user, sid, tab):
                module.render(tab, user, sid)
            else:
                locked_panel(user, sid, tab)
