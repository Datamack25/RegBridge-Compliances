"""Recherche de notoriété (personne physique ou morale) par familles de mots, avec rapport des liens.

Prototype : flux RSS de Google News (titres et liens seulement, pas d'aspiration de pages).
Pour un service payant, remplacer `fetch_news` par une API presse sous contrat.
Les résultats restent dans la session : ils ne sont pas écrits dans les CSV partagés (RGPD).
"""
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests
import streamlit as st

from core import db
from core import entitlements as ent
from core import ui

FAMILIES = {
    "Sanctions et embargos": ["sanction", "embargo", "\"gel des avoirs\"", "sanctions", "\"asset freeze\""],
    "Corruption et fraude": ["corruption", "fraude", "détournement", "\"abus de biens sociaux\"", "bribery", "fraud"],
    "Blanchiment et terrorisme": ["blanchiment", "\"financement du terrorisme\"", "\"money laundering\""],
    "Arnaque et escroquerie": ["arnaque", "escroquerie", "plainte", "scam", "Ponzi"],
    "Condamnation et procédure": ["condamné", "\"mis en examen\"", "procès", "amende", "perquisition", "convicted"],
    "Santé de l'entreprise": ["faillite", "liquidation", "redressement", "scandale"],
    "Personnes exposées": ["ministre", "élu", "\"personne politiquement exposée\""],
}
LEADS = {
    "OpenSanctions": "https://www.opensanctions.org/search/?q={q}",
    "ICIJ Offshore Leaks": "https://offshoreleaks.icij.org/search?q={q}",
    "BODACC": "https://www.bodacc.fr/pages/annonces-commerciales/?q={q}",
    "Judilibre (Cour de cassation)": "https://www.courdecassation.fr/recherche-judilibre?search_api_fulltext={q}",
    "Annuaire des entreprises": "https://annuaire-entreprises.data.gouv.fr/rechercher?terme={q}",
}


def build_queries(name: str, aliases: list[str], families: list[str], extra: list[str], exclude: list[str]) -> list[tuple[str, str]]:
    names = " OR ".join(f'"{n}"' for n in [name] + aliases if n)
    excl = " ".join(f"-{w}" for w in exclude if w)
    qs = []
    for fam in families:
        words = " OR ".join(FAMILIES[fam])
        qs.append((fam, f"({names}) ({words}) {excl}".strip()))
    if extra:
        qs.append(("Mots ajoutés", f"({names}) ({' OR '.join(extra)}) {excl}".strip()))
    return qs


def fetch_news(query: str, lang: str = "fr") -> list[dict]:
    gl, ceid = ("FR", "FR:fr") if lang == "fr" else ("US", "US:en")
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl={lang}&gl={gl}&ceid={ceid}"
    r = requests.get(url, timeout=12, headers={"User-Agent": "RegBridge/0.1"})
    r.raise_for_status()
    out = []
    for item in ET.fromstring(r.content).iter("item"):
        src = item.find("source")
        out.append({"titre": item.findtext("title", ""), "lien": item.findtext("link", ""),
                    "date": item.findtext("pubDate", "")[:16], "media": src.text if src is not None else ""})
    return out


def render(tab, user, sid):
    if tab == "Accueil":
        st.markdown("Combinez le nom d'une personne ou d'une société avec des **familles de mots** (sanctions, corruption, "
                    "arnaque, condamnation...) ; la plateforme lance une requête par famille, dédoublonne et vous laisse "
                    "qualifier chaque lien avant le rapport PDF.")
        st.warning("Une recherche sur une personne physique est un traitement de données personnelles. Les condamnations relèvent "
                   "de l'encadrement renforcé du RGPD : base légale documentée, accès restreint, conservation limitée.")
        ui.quota_line(user, sid, "recherche")

    elif tab == "Nouvelle recherche":
        with st.form("noto"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Nom de la cible (personne ou société)")
            kind = c2.selectbox("Type", ["Personne physique", "Personne morale"])
            aliases = c1.text_input("Alias ou variantes (séparés par des virgules)")
            exclude = c2.text_input("Mots à exclure (homonymes)", placeholder="ex. footballeur, chanteur")
            fams = st.multiselect("Familles de mots", list(FAMILIES), default=list(FAMILIES)[:5])
            extra = st.text_input("Mots ajoutés (virgules)")
            langs = st.multiselect("Langues", ["fr", "en"], default=["fr", "en"])
            basis = st.checkbox("Je confirme une base légale pour cette recherche (obligation LCB-FT ou intérêt légitime documenté).")
            go = st.form_submit_button("Lancer la recherche", type="primary")
        ui.quota_line(user, sid, "recherche")
        if go:
            if not name.strip() or not basis:
                st.error("Indiquez un nom et confirmez la base légale.")
            elif not ent.consume(user, sid, "recherche"):
                st.error("Quota de recherches atteint pour ce mois.")
            else:
                qs = build_queries(name.strip(), [a.strip() for a in aliases.split(",") if a.strip()], fams,
                                   [e.strip() for e in extra.split(",") if e.strip()],
                                   [e.strip() for e in exclude.split(",") if e.strip()])
                rows, errors = [], 0
                with st.spinner("Interrogation des sources..."):
                    for fam, q in qs:
                        for lang in langs:
                            try:
                                for it in fetch_news(q, lang):
                                    rows.append({**it, "famille": fam, "langue": lang})
                            except (requests.RequestException, ET.ParseError):
                                errors += 1
                df = pd.DataFrame(rows, columns=["titre", "media", "date", "famille", "langue", "lien"])
                df = df.drop_duplicates(subset=["lien"]).drop_duplicates(subset=["titre"])
                df.insert(0, "statut", "à vérifier")
                st.session_state.noto = {"name": name.strip(), "kind": kind, "queries": qs, "df": df, "errors": errors,
                                         "exclude": exclude, "date": date.today().isoformat()}
                st.session_state.setdefault("noto_hist", []).append({"date": date.today().isoformat(), "cible": name.strip(),
                                                                     "resultats": len(df)})
                db.audit(user["email"], "recherche_notoriete", {"type": kind, "familles": fams})
        res = st.session_state.get("noto")
        if not res:
            return
        if res["errors"]:
            st.warning(f"{res['errors']} requête(s) sans réponse (source injoignable).")
        st.markdown(f"**{len(res['df'])} liens trouvés pour {res['name']}.** Qualifiez chaque lien : seul un humain décide.")
        edited = st.data_editor(
            res["df"], hide_index=True, width="stretch", key="noto_ed",
            column_config={"statut": st.column_config.SelectboxColumn("Statut", options=["à vérifier", "retenu", "homonyme", "hors sujet"]),
                           "lien": st.column_config.LinkColumn("Lien")},
            disabled=["titre", "media", "date", "famille", "langue", "lien"])
        with st.expander("Requêtes exécutées et pistes complémentaires"):
            for fam, q in res["queries"]:
                st.code(q, language=None)
            for label, url in LEADS.items():
                st.markdown(f"- [{label}]({url.format(q=urllib.parse.quote(res['name']))})")
        kept = edited[edited["statut"].isin(["retenu", "à vérifier"])]
        dropped = edited[edited["statut"].isin(["homonyme", "hors sujet"])]
        free = ent.access_level(user, sid) == "free"
        if free:
            kept = kept.head(10)
        ui.export_panel(user, sid, {
            "title": f"Recherche de notoriété : {res['name']}",
            "subtitle": f"{res['kind']} · recherche du {res['date']} · demandeur {user['name']}",
            "kpis": [(str(len(edited)), "liens trouvés"), (str((edited['statut'] == 'retenu').sum()), "retenus"),
                     (str((edited['statut'] == 'à vérifier').sum()), "à vérifier"), (str(len(dropped)), "écartés")],
            "sections": [
                {"heading": "Synthèse", "paragraphs": ["Niveau de vigilance indicatif à apprécier par l'analyste. "
                                                        "L'absence de résultat ne prouve pas l'absence de risque."]},
                {"heading": "Méthodologie", "bullets": [q for _, q in res["queries"]] + [f"Mots exclus : {res['exclude'] or 'aucun'}"]},
                {"heading": "Liens retenus ou à vérifier", "table": {"columns": ["Statut", "Titre", "Média", "Date", "Famille", "Lien"],
                    "rows": kept[["statut", "titre", "media", "date", "famille", "lien"]].values.tolist()}},
                {"heading": "Liens écartés", "table": {"columns": ["Statut", "Titre", "Lien"],
                    "rows": dropped[["statut", "titre", "lien"]].values.tolist()}},
                {"heading": "Pistes complémentaires", "bullets": [f"{k} : {v.format(q=urllib.parse.quote(res['name']))}" for k, v in LEADS.items()]},
            ],
            "sources": ["Google News RSS (titres et liens uniquement)"]}, key="noto_exp", formats=("PDF", "Word", "CSV", "Image PNG"))

    elif tab == "Historique":
        st.caption("Historique de la session uniquement : les recherches nominatives ne sont pas conservées sur le serveur.")
        st.dataframe(pd.DataFrame(st.session_state.get("noto_hist", [])), hide_index=True, width="stretch")
