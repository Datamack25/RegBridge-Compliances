"""Éléments d'interface partagés : thème, lanceur de services, en-tête, exports, onglets verrouillés."""
import importlib

import streamlit as st

from core import entitlements as ent
from core import reports
from core.catalog import ACTION_LABELS, FAMILY_ORDER, SERVICES

CSS = """
<style>
:root { --navy:#0B2545; --teal:#0E7C86; --light:#EEF3F8; --line:#D5DCE4; --grey:#5B6770; }
.block-container { padding-top: 3.2rem; max-width: 1250px; }
/* Couleurs lisibles en thème clair comme en thème sombre */
.rb-brand { font-weight:800; color:#14A3AE; font-size:1.35rem; letter-spacing:.2px; }
.rb-sub { color:#8A96A3; font-size:.86rem; }
.rb-tile-icon { font-size:1.9rem; line-height:1; }
.rb-tile-name { font-weight:700; color:#14A3AE; margin-top:.35rem; }
.rb-tile-pitch { color:#8A96A3; font-size:.8rem; min-height:2.6rem; }
/* Écran d'accueil : formulaire compact dans une carte */
/* Boutons principaux aux couleurs de la marque, même sans .streamlit/config.toml */
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background:#0E7C86 !important; border-color:#0E7C86 !important; color:#fff !important; }
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background:#0B6870 !important; border-color:#0B6870 !important; }
.rb-auth-title { font-weight:800; font-size:1.25rem; margin:0 0 .15rem; }
.rb-auth-sub { color:#8A96A3; font-size:.85rem; margin-bottom:.6rem; }
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


HERO_SVG = """
<svg viewBox="0 0 560 300" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="rbglow" cx="50%" cy="45%" r="55%">
      <stop offset="0%" stop-color="#14A3AE" stop-opacity=".35"/><stop offset="100%" stop-color="#14A3AE" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="rbshield" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1FC7D1"/><stop offset="100%" stop-color="#0E7C86"/>
    </linearGradient>
  </defs>
  <circle cx="280" cy="140" r="150" fill="url(#rbglow)"/>
  <g fill="none" stroke="#5FD3DA" stroke-opacity=".18">
    <ellipse cx="280" cy="140" rx="200" ry="70"/><ellipse cx="280" cy="140" rx="120" ry="125"/><ellipse cx="280" cy="140" rx="40" ry="125"/>
    <line x1="80" y1="140" x2="480" y2="140"/>
  </g>
  <g fill="none" stroke="#5FD3DA" stroke-width="1.6" stroke-dasharray="4 5" stroke-opacity=".75">
    <path d="M110 75 Q200 10 280 70"/><path d="M280 70 Q410 40 455 120"/><path d="M110 75 Q120 190 175 230"/>
    <path d="M175 230 Q300 280 410 225"/><path d="M455 120 Q470 190 410 225"/>
  </g>
  <g font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#DCEFF1">
    <circle cx="110" cy="75" r="6" fill="#1FC7D1"/><text x="72" y="60">Caraïbes</text>
    <circle cx="280" cy="70" r="6" fill="#1FC7D1"/><text x="262" y="54">Europe</text>
    <circle cx="455" cy="120" r="6" fill="#1FC7D1"/><text x="430" y="104">Moyen-Orient</text>
    <circle cx="175" cy="230" r="6" fill="#1FC7D1"/><text x="140" y="254">Amériques</text>
    <circle cx="410" cy="225" r="6" fill="#1FC7D1"/><text x="392" y="250">Afrique</text>
  </g>
  <path d="M280 98 L322 114 V146 C322 172 304 190 280 200 C256 190 238 172 238 146 V114 Z" fill="url(#rbshield)" stroke="#BFF3F6" stroke-width="1.5"/>
  <path d="M262 148 L276 162 L300 134" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <g font-family="Helvetica, Arial, sans-serif" font-size="10.5" font-weight="700">
    <rect x="20" y="150" rx="8" width="92" height="26" fill="#FFFFFF" fill-opacity=".1" stroke="#5FD3DA" stroke-opacity=".5"/>
    <text x="32" y="167" fill="#FFFFFF">Sanctions ✓</text>
    <rect x="452" y="160" rx="8" width="90" height="26" fill="#FFFFFF" fill-opacity=".1" stroke="#5FD3DA" stroke-opacity=".5"/>
    <text x="466" y="177" fill="#FFFFFF">KYC · KYB</text>
    <rect x="330" y="20" rx="8" width="104" height="26" fill="#FFFFFF" fill-opacity=".1" stroke="#5FD3DA" stroke-opacity=".5"/>
    <text x="342" y="37" fill="#FFFFFF">Veille AMLR</text>
  </g>
</svg>
"""


LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><path d="M20 3 L35 9 V20 C35 29 28 35 20 38 C12 35 5 29 5 20 V9 Z" fill="#14A3AE"/><path d="M13 20 L18 25 L27 15" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/></svg>"""


def svg_uri(svg: str) -> str:
    """Les balises <svg> sont filtrées par Streamlit : on les passe en image (data URI)."""
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svg.strip().encode("utf-8")).decode()


def hero(title: str, text: str, chips: list[str], footnote: str = "") -> None:
    """Panneau visuel de la page d'accueil : fond propre, lisible en thème clair comme sombre."""
    chips_html = "".join(
        f"<span style='display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border-radius:999px;"
        f"background:rgba(255,255,255,.1);border:1px solid rgba(95,211,218,.45);color:#E6F6F7;font-size:12px'>{c}</span>"
        for c in chips)
    st.html(f"""
<div style="background:linear-gradient(140deg,#0B2545 0%,#0F3A5C 55%,#0E7C86 130%);border-radius:18px;
            padding:26px 30px 22px;color:#fff;font-family:'Source Sans Pro',Helvetica,Arial,sans-serif;
            box-shadow:0 10px 30px rgba(0,0,0,.25)">
  <div style="display:flex;align-items:center;gap:10px">
    <img src="{svg_uri(LOGO_SVG)}" width="34" height="34" alt="">
    <span style="font-size:26px;font-weight:800;letter-spacing:.3px">Reg<span style="color:#5FD3DA">Bridge</span></span>
    <span style="margin-left:auto;font-size:11px;letter-spacing:.12em;color:#9FDDE2;text-transform:uppercase">Conformité · LCB-FT</span>
  </div>
  <div style="margin:18px 0 4px;font-size:25px;font-weight:700;line-height:1.25">{title}</div>
  <div style="color:#C9DDE6;font-size:14.5px;line-height:1.5;max-width:560px">{text}</div>
  <img src="{svg_uri(HERO_SVG)}" alt="Corridors de conformité" style="width:100%;height:auto;display:block;margin:14px 0 6px">
  <div>{chips_html}</div>
  <div style="color:#8FB3C2;font-size:11.5px;margin-top:8px">{footnote}</div>
</div>""")


def brand_mark() -> None:
    """Logo et nom de la plateforme (barre latérale)."""
    st.html(f"""<div style="display:flex;align-items:center;gap:8px;margin:-6px 0 10px">
<img src="{svg_uri(LOGO_SVG)}" width="28" height="28" alt="">
<span style="font-size:21px;font-weight:800;color:#14A3AE;font-family:'Source Sans Pro',Helvetica,Arial,sans-serif">
Reg<span style="color:#5FD3DA">Bridge</span></span></div>""")


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
