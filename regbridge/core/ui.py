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
.rb-tile-family { color:#0E7C86; font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; margin-bottom:.35rem; }
.rb-tile-icon { font-size:1.9rem; line-height:1; }
.rb-tile-name { font-weight:700; color:#14A3AE; margin-top:.35rem; }
.rb-tile-pitch { color:#8A96A3; font-size:.8rem; min-height:3.9rem; }
/* Écran d'accueil : formulaire compact dans une carte */
/* Boutons principaux aux couleurs de la marque, même sans .streamlit/config.toml */
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background:#0E7C86 !important; border-color:#0E7C86 !important; color:#fff !important; }
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background:#0B6870 !important; border-color:#0B6870 !important; }
/* Tableau de veille (style bulletin) : fond propre, lisible quel que soit le thème */
.rbw { background:#FFFFFF; color:#1B2733; border:1px solid #E6E1D3; border-radius:12px; padding:4px 0 6px;
       font-family:'Source Sans Pro',Helvetica,Arial,sans-serif; overflow-x:auto; }
.rbw-inner { min-width:940px; }
.rbw-grid { display:grid; grid-template-columns: 78px minmax(200px,2fr) minmax(200px,2.1fr) 108px 88px 66px 80px 56px; gap:10px;
            gap:12px; align-items:start; padding:11px 16px; }
.rbw-head { font-size:11.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#1B2733;
            border-bottom:2px solid #C9A227; padding-top:8px; padding-bottom:9px; }
.rbw details { border-bottom:1px solid #EEEBE3; }
.rbw details:nth-of-type(even) { background:#FAF8F2; }
.rbw details[open] { background:#F2F8F9; }
.rbw summary { list-style:none; cursor:pointer; }
.rbw summary::-webkit-details-marker { display:none; }
.rbw summary:hover .rbw-title { text-decoration:underline; }
.rbw-title { color:#0B2545; font-weight:700; font-size:14.5px; line-height:1.3; }
.rbw-caret { display:inline-block; color:#0E7C86; margin-right:6px; transition:transform .15s; }
.rbw details[open] .rbw-caret { transform:rotate(90deg); }
.rbw-ref { color:#6B7480; font-size:12px; margin-top:3px; }
.rbw-cell { font-size:13.5px; line-height:1.35; color:#1B2733; }
.rbw-short { font-size:13.5px; line-height:1.4; color:#33404D; }
.rbw-flag { display:flex; align-items:center; gap:7px; font-size:13.5px; }
.rbw-flag img { width:22px; height:15px; border-radius:2px; box-shadow:0 0 0 1px rgba(0,0,0,.12); }
.rbw-imp { font-weight:800; font-size:13.5px; }
.rbw-new { display:inline-block; margin-left:6px; padding:1px 6px; border-radius:4px; background:#0E7C86; color:#fff;
           font-size:10px; font-weight:700; letter-spacing:.05em; vertical-align:2px; }
.rbw a { color:#0E7C86; font-weight:600; text-decoration:none; }
.rbw a:hover { text-decoration:underline; }
.rbw-body { padding:2px 24px 16px 116px; color:#1B2733; }
.rbw-body p { font-size:14.5px; line-height:1.6; margin:4px 0 10px; max-width:980px; }
.rbw-meta { font-size:12.5px; color:#5B6770; margin:6px 0 10px; }
.rbw-action { font-size:13.5px; margin:0 0 12px; }
.rbw-btn { display:inline-block; padding:7px 14px; border-radius:8px; background:#0E7C86; color:#FFFFFF !important; font-size:13px; }
.rbw-banner { background:#FBF7EA; border:1px solid #E8DDB5; border-radius:12px; padding:14px 20px; margin-bottom:12px; }
.rbw-banner b { color:#B8901B; font-size:24px; font-weight:800; display:block; }
.rbw-banner span { color:#5B6770; font-size:14px; }
.rbw-foot { color:#8A96A3; font-size:11.5px; padding:10px 16px 2px; }
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


FLAGS = {
    "France": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect width="1" height="2" fill="#002395"/><rect x="1" width="1" height="2" fill="#fff"/><rect x="2" width="1" height="2" fill="#ED2939"/></svg>',
    "UE": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#003399"/>' + "".join(
        f'<circle cx="{15 + 6 * __import__("math").cos(i * 0.5236):.2f}" cy="{10 + 6 * __import__("math").sin(i * 0.5236):.2f}" r="1" fill="#FFCC00"/>' for i in range(12)) + '</svg>',
    "États-Unis": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 38 20"><rect width="38" height="20" fill="#fff"/>' + "".join(
        f'<rect y="{i * 20 / 13:.2f}" width="38" height="{20 / 13:.2f}" fill="#B22234"/>' for i in range(0, 13, 2)) + '<rect width="16" height="10.8" fill="#3C3B6E"/></svg>',
    "Suisse": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#D52B1E"/><rect x="13" y="4" width="4" height="12" fill="#fff"/><rect x="9" y="8" width="12" height="4" fill="#fff"/></svg>',
    "Luxembourg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 18"><rect width="30" height="6" fill="#ED2939"/><rect y="6" width="30" height="6" fill="#fff"/><rect y="12" width="30" height="6" fill="#00A1DE"/></svg>',
    "Royaume-Uni": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#012169"/><path d="M0 0L30 20M30 0L0 20" stroke="#fff" stroke-width="4"/><path d="M15 0V20M0 10H30" stroke="#fff" stroke-width="6"/><path d="M15 0V20M0 10H30" stroke="#C8102E" stroke-width="3"/></svg>',
    "International": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"><rect width="30" height="20" fill="#5B92E5"/><circle cx="15" cy="10" r="6" fill="none" stroke="#fff" stroke-width="1.4"/><path d="M9 10H21M15 4V16" stroke="#fff" stroke-width="1"/></svg>',
}
IMPACT_COLORS = {"critique": "#B42318", "élevé": "#C2410C", "moyen": "#A86A00", "faible": "#2F7D5B"}


def esc_html(s) -> str:
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def flag_html(jur: str) -> str:
    svg = FLAGS.get(jur, FLAGS["International"])
    return f"<span class='rbw-flag'><img src='{svg_uri(svg)}' alt=''>{esc_html(jur)}</span>"


def watch_table(rows: list[dict], footnote: str = "") -> None:
    """Tableau de veille cliquable : un clic sur le titre déplie le résumé développé et le lien vers le texte.
    Chaque ligne : date, titre, reference, theme, resume (court), juridiction, type, impact, application,
    nouveau (bool), resume_long, action, secteurs, statut, lien, verifie."""
    head = ("<div class='rbw-grid rbw-head'><div>Date</div><div>Texte</div><div>Description</div><div>Juridiction</div>"
            "<div>Type</div><div>Impact</div><div>Application</div><div>Source</div></div>")
    items = []
    for r in rows:
        link = r.get("lien") or ""
        src = (f"<a href='{esc_html(link)}' target='_blank' rel='noopener'>Ouvrir ↗</a>" if link else "—")
        imp = r.get("impact", "")
        new = "<span class='rbw-new'>NOUVEAU</span>" if r.get("nouveau") else ""
        body_link = (f"<a class='rbw-btn' href='{esc_html(link)}' target='_blank' rel='noopener'>Lire le texte complet ↗</a>"
                     if link else "<span class='rbw-meta'>Lien officiel non renseigné.</span>")
        items.append(f"""<details><summary class='rbw-grid'>
<div class='rbw-cell'>{esc_html(r.get('date', ''))}</div>
<div><div class='rbw-title'><span class='rbw-caret'>▸</span>{esc_html(r.get('titre', ''))}{new}</div>
<div class='rbw-ref'>{esc_html(r.get('reference', ''))}</div></div>
<div class='rbw-short'><div style='color:#0E7C86;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em'>{esc_html(r.get('theme', ''))}</div>{esc_html(r.get('resume', ''))}</div>
<div>{flag_html(r.get('juridiction', ''))}</div>
<div class='rbw-cell'>{esc_html(r.get('type', ''))}<br><span style='color:#6B7480;font-size:12px'>{esc_html(r.get('statut', ''))}</span></div>
<div class='rbw-imp' style='color:{IMPACT_COLORS.get(imp, "#1B2733")}'>{esc_html(imp.capitalize())}</div>
<div class='rbw-cell'>{esc_html(r.get('application', '') or '—')}</div>
<div class='rbw-cell'>{src}</div>
</summary>
<div class='rbw-body'>
<p>{esc_html(r.get('resume_long') or r.get('resume', ''))}</p>
<div class='rbw-action'><b>Action recommandée :</b> {esc_html(r.get('action', ''))}</div>
<div class='rbw-meta'>Secteurs : {esc_html(r.get('secteurs', ''))} · Référence : {esc_html(r.get('reference', ''))} ·
Vérifié sur le texte officiel : {esc_html(r.get('verifie', 'non'))}</div>
{body_link}
</div></details>""")
    foot = f"<div class='rbw-foot'>{esc_html(footnote)}</div>" if footnote else ""
    st.html(f"<div class='rbw'><div class='rbw-inner'>{head}{''.join(items)}{foot}</div></div>")


def watch_banner(title: str, subtitle: str) -> None:
    st.html(f"<div class='rbw-banner'><b>{esc_html(title)}</b><span>{esc_html(subtitle)}</span></div>")


def welcome_banner(title: str, subtitle: str, stats: list[tuple[str, str]]) -> None:
    stats_html = "".join(
        f"<div style='background:rgba(255,255,255,.1);border:1px solid rgba(95,211,218,.35);border-radius:10px;"
        f"padding:8px 16px;min-width:120px'><div style='font-size:22px;font-weight:800'>{esc_html(v)}</div>"
        f"<div style='font-size:12px;color:#C9DDE6'>{esc_html(l)}</div></div>" for v, l in stats)
    st.html(f"""<div style="background:linear-gradient(120deg,#0B2545 0%,#0F3A5C 60%,#0E7C86 130%);border-radius:16px;
padding:22px 26px;color:#fff;font-family:'Source Sans Pro',Helvetica,Arial,sans-serif;display:flex;flex-wrap:wrap;
align-items:center;gap:18px;margin-bottom:6px">
<img src="{svg_uri(LOGO_SVG)}" width="44" height="44" alt="">
<div style="flex:1;min-width:220px"><div style="font-size:26px;font-weight:800">{esc_html(title)}</div>
<div style="color:#C9DDE6;font-size:14px">{esc_html(subtitle)}</div></div>
<div style="display:flex;gap:10px;flex-wrap:wrap">{stats_html}</div></div>""")


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


def _tile(user: dict, sid: str, compact: bool) -> None:
    s = SERVICES[sid]
    lvl = ent.access_level(user, sid)
    with st.container(border=True):
        tag = "" if compact else f"<div class='rb-tile-family'>{s['family']}</div>"
        st.markdown(f"{tag}<div class='rb-tile-icon'>{s['icon']}</div><div class='rb-tile-name'>{s['name']}</div>",
                    unsafe_allow_html=True)
        if not compact:
            st.markdown(f"<div class='rb-tile-pitch'>{s['pitch']}</div>", unsafe_allow_html=True)
        st.markdown(badge(user, sid), unsafe_allow_html=True)
        key = f"tile_{'c' if compact else 'g'}_{sid}"
        if lvl == "locked":
            if st.button("Demander l'accès", key=key, width="stretch"):
                request_dialog(user, sid)
        elif st.button("Ouvrir", key=key, type="primary" if lvl == "full" else "secondary", width="stretch"):
            open_service(sid)
            st.rerun()


def launcher(user: dict, compact: bool = False) -> None:
    """Grille de services façon Microsoft 365 : tous les services visibles, accès selon les droits.
    Page d'accueil : grille continue sur 4 colonnes (la famille est indiquée sur chaque tuile) ;
    menu « Services » : regroupement par famille."""
    order = [sid for fam in FAMILY_ORDER for sid, v in SERVICES.items() if v["family"] == fam]
    if not compact:
        # abonnements et services gratuits d'abord, services verrouillés ensuite
        rank = {"full": 0, "free": 1, "locked": 2}
        order = sorted(order, key=lambda sid: rank[ent.access_level(user, sid)])
        ncol = 4
        for i in range(0, len(order), ncol):
            cols = st.columns(ncol)
            for c, sid in zip(cols, order[i:i + ncol]):
                with c:
                    _tile(user, sid, compact=False)
        return
    for fam in FAMILY_ORDER:
        sids = [k for k, v in SERVICES.items() if v["family"] == fam]
        if not sids:
            continue
        st.markdown(f"<div class='rb-family'>{fam}</div>", unsafe_allow_html=True)
        cols = st.columns(3)
        for i, sid in enumerate(sids):
            with cols[i % 3]:
                _tile(user, sid, compact=True)


def go_home() -> None:
    """Retour à l'accueil de la plateforme (grille des services), depuis n'importe quel écran."""
    st.session_state.service = None
    st.session_state.mode = "user"
    st.query_params.clear()


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
    head, home_col, grid = st.columns([5, 1, 1])
    head.markdown(f"<span class='rb-brand'>{s['icon']} {s['name']}</span> &nbsp; {badge(user, sid)}",
                  unsafe_allow_html=True)
    head.caption(s["pitch"])
    if home_col.button("🏠 Accueil", key=f"home_{sid}", width="stretch"):
        go_home(); st.rerun()
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
