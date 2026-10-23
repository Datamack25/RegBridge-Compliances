"""Recherche de notoriété (personne physique ou morale) avec une base automatique de 15 mots à risque.

- La base de 15 mots (sanctions, blanchiment, fraude, corruption, condamnation...) est appliquée automatiquement :
  l'utilisateur n'a qu'à saisir le nom. Les mots ajoutés et les mots exclus sont facultatifs.
- Les mots sont regroupés en 5 thèmes : une requête par thème et par langue (français, anglais).
- Prototype : flux RSS de Google News (titres et liens seulement, pas d'aspiration de pages).
  Pour un service payant, remplacer `fetch_news` par une API presse sous contrat.
- Les résultats restent dans la session : ils ne sont pas écrits dans les CSV partagés (RGPD).
"""
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests
import streamlit as st

from core import db
from core import entitlements as ent
from core import ui

# Base automatique : 15 mots à risque (français) et leur équivalent anglais, regroupés en 5 thèmes.
BASE_WORDS = {
    "Sanctions et embargos": [("sanction", "sanctions"), ("embargo", "embargo"), ("gel des avoirs", "asset freeze")],
    "Blanchiment et terrorisme": [("blanchiment", "money laundering"), ("financement du terrorisme", "terrorist financing"),
                                  ("trafic", "trafficking")],
    "Fraude et escroquerie": [("fraude", "fraud"), ("escroquerie", "scam"), ("détournement", "embezzlement")],
    "Corruption": [("corruption", "corruption"), ("pot-de-vin", "bribery"), ("abus de biens sociaux", "misappropriation")],
    "Justice et enquêtes": [("condamné", "convicted"), ("mis en examen", "indicted"), ("enquête", "investigation")],
}
GRAVITE = {"Sanctions et embargos": "élevée", "Blanchiment et terrorisme": "élevée", "Corruption": "élevée",
           "Fraude et escroquerie": "moyenne", "Justice et enquêtes": "moyenne", "Mots ajoutés": "à apprécier"}
LEADS = {
    "OpenSanctions": "https://www.opensanctions.org/search/?q={q}",
    "ICIJ Offshore Leaks": "https://offshoreleaks.icij.org/search?q={q}",
    "BODACC": "https://www.bodacc.fr/pages/annonces-commerciales/?q={q}",
    "Judilibre (Cour de cassation)": "https://www.courdecassation.fr/recherche-judilibre?search_api_fulltext={q}",
    "Annuaire des entreprises": "https://annuaire-entreprises.data.gouv.fr/rechercher?terme={q}",
}
STATUTS = ["à vérifier", "retenu", "homonyme", "hors sujet"]


def _plain(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _quote(w: str) -> str:
    return f'"{w}"' if " " in w else w


def build_queries(name: str, aliases: list[str], extra: list[str], exclude: list[str], langs: list[str]) -> list[dict]:
    """Une requête par thème et par langue, avec la base automatique ; les mots ajoutés forment une requête de plus."""
    names = " OR ".join(f'"{n}"' for n in [name] + aliases if n)
    excl = " ".join(f"-{_quote(w)}" for w in exclude if w)
    qs = []
    for theme, pairs in BASE_WORDS.items():
        for lang in langs:
            words = [fr if lang == "fr" else en for fr, en in pairs]
            qs.append({"theme": theme, "lang": lang, "words": words,
                       "q": f"({names}) ({' OR '.join(_quote(w) for w in words)}) {excl}".strip()})
    if extra:
        for lang in langs:
            qs.append({"theme": "Mots ajoutés", "lang": lang, "words": extra,
                       "q": f"({names}) ({' OR '.join(_quote(w) for w in extra)}) {excl}".strip()})
    return qs


def fetch_news(query: str, lang: str = "fr") -> list[dict]:
    gl, ceid = ("FR", "FR:fr") if lang == "fr" else ("US", "US:en")
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl={lang}&gl={gl}&ceid={ceid}"
    r = requests.get(url, timeout=12, headers={"User-Agent": "RegBridge/0.2"})
    r.raise_for_status()
    out = []
    for item in ET.fromstring(r.content).iter("item"):
        src = item.find("source")
        out.append({"titre": item.findtext("title", ""), "lien": item.findtext("link", ""),
                    "date": item.findtext("pubDate", "")[:16], "media": src.text if src is not None else ""})
    return out


def detected_words(title: str, words: list[str]) -> str:
    t = _plain(title)
    return ", ".join(w for w in words if _plain(w) in t)


def run_search(name: str, kind: str, aliases: list[str], extra: list[str], exclude: list[str], langs: list[str]) -> dict:
    qs = build_queries(name, aliases, extra, exclude, langs)
    rows, errors = [], 0
    with st.spinner(f"Interrogation des sources ({len(qs)} requêtes)..."):
        for q in qs:
            try:
                for it in fetch_news(q["q"], q["lang"]):
                    rows.append({**it, "theme": q["theme"], "langue": q["lang"],
                                 "gravite": GRAVITE.get(q["theme"], "à apprécier"),
                                 "mots_detectes": detected_words(it["titre"], q["words"])})
            except (requests.RequestException, ET.ParseError):
                errors += 1
    df = pd.DataFrame(rows, columns=["titre", "media", "date", "theme", "gravite", "mots_detectes", "langue", "lien"])
    df = df.drop_duplicates(subset=["lien"]).drop_duplicates(subset=["titre"]).reset_index(drop=True)
    # Après dédoublonnage, on recherche dans chaque titre les 15 mots (et les mots ajoutés) pour fixer thème et gravité
    lexicon = [(t, w) for t, pairs in BASE_WORDS.items() for pair in pairs for w in pair] + [("Mots ajoutés", w) for w in extra]
    for i, title in df["titre"].items():
        hits = [(t, w) for t, w in lexicon if _plain(w) in _plain(title)]
        if hits:
            words = list(dict.fromkeys(w for _, w in hits))
            words = [w for w in words if not any(w != o and _plain(w) in _plain(o) for o in words)]   # « fraud » inclus dans « fraude »
            df.at[i, "mots_detectes"] = ", ".join(words)
            df.at[i, "theme"] = hits[0][0]
            df.at[i, "gravite"] = GRAVITE.get(hits[0][0], "à apprécier")
    df.insert(0, "statut", "à vérifier")
    return {"name": name, "kind": kind, "queries": qs, "df": df, "errors": errors, "exclude": exclude,
            "extra": extra, "date": date.today().isoformat(), "run_id": f"{name}-{pd.Timestamp.now().value}"}


def render(tab, user, sid):
    if tab == "Accueil":
        st.markdown("Saisissez seulement le **nom** de la personne ou de la société : la plateforme le combine automatiquement "
                    "avec une **base de 15 mots à risque**, en français et en anglais, puis dédoublonne les résultats. "
                    "Vous qualifiez ensuite chaque lien avant de produire le rapport.")
        st.dataframe(pd.DataFrame([{"Thème": t, "Mots (français)": ", ".join(fr for fr, _ in p),
                                    "Mots (anglais)": ", ".join(en for _, en in p), "Gravité": GRAVITE[t]}
                                   for t, p in BASE_WORDS.items()]), hide_index=True, width="stretch")
        st.warning("Une recherche sur une personne physique est un traitement de données personnelles. Les condamnations relèvent "
                   "de l'encadrement renforcé du RGPD : base légale documentée, accès restreint, conservation limitée.")
        ui.quota_line(user, sid, "recherche")

    elif tab == "Nouvelle recherche":
        # Clé du formulaire distincte de la clé des résultats (sinon StreamlitWidgetAlreadyInstantiatedError)
        with st.form("noto_form"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Nom de la cible (personne ou société)")
            kind = c2.selectbox("Type", ["Personne physique", "Personne morale"])
            with st.expander("Options facultatives : alias, mots ajoutés, exclusions, langues"):
                o1, o2 = st.columns(2)
                aliases = o1.text_input("Alias ou variantes (séparés par des virgules)")
                exclude = o2.text_input("Mots à exclure pour écarter un homonyme", placeholder="ex. footballeur, chanteur")
                extra = o1.text_input("Mots ajoutés à la base (virgules)", placeholder="ex. Ponzi, cartel")
                langs = o2.multiselect("Langues", ["fr", "en"], default=["fr", "en"], placeholder="Choisir")
            st.caption("Base automatique : sanction, embargo, gel des avoirs, blanchiment, financement du terrorisme, trafic, "
                       "fraude, escroquerie, détournement, corruption, pot-de-vin, abus de biens sociaux, condamné, "
                       "mis en examen, enquête.")
            basis = st.checkbox("Je confirme une base légale pour cette recherche (obligation LCB-FT ou intérêt légitime documenté).")
            go = st.form_submit_button("Lancer la recherche", type="primary")
        ui.quota_line(user, sid, "recherche")
        if go:
            split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
            if not name.strip() or not basis:
                st.error("Indiquez un nom et confirmez la base légale.")
            elif not langs:
                st.error("Choisissez au moins une langue.")
            elif not ent.consume(user, sid, "recherche"):
                st.error("Quota de recherches atteint pour ce mois.")
            else:
                res = run_search(name.strip(), kind, split(aliases), split(extra), split(exclude), langs)
                st.session_state.noto_res = res
                st.session_state.setdefault("noto_hist", []).append(
                    {"date": res["date"], "cible": res["name"], "type": kind, "resultats": len(res["df"])})
                db.audit(user["email"], "recherche_notoriete", {"type": kind, "requetes": len(res["queries"])})
        res = st.session_state.get("noto_res")
        if not res:
            return
        if res["errors"]:
            st.warning(f"{res['errors']} requête(s) sans réponse (source injoignable).")
        df = res["df"]
        ui.kpis([(str(len(df)), "liens trouvés"), (str((df["gravite"] == "élevée").sum()), "thèmes à gravité élevée"),
                 (str(df["theme"].nunique() if len(df) else 0), "thèmes touchés"), (str(len(res["queries"])), "requêtes lancées")])
        if df.empty:
            st.success(f"Aucun article trouvé pour {res['name']} avec la base de 15 mots. "
                       "L'absence de résultat ne prouve pas l'absence de risque.")
        st.markdown(f"**Résultats pour {res['name']}** : qualifiez chaque lien, seul un humain décide.")
        edited = st.data_editor(
            df, hide_index=True, width="stretch", key=f"noto_ed_{res['run_id']}",
            column_config={"statut": st.column_config.SelectboxColumn("Statut", options=STATUTS),
                           "lien": st.column_config.LinkColumn("Lien"), "theme": "Thème", "gravite": "Gravité",
                           "mots_detectes": "Mots détectés dans le titre", "titre": "Titre", "media": "Média"},
            disabled=["titre", "media", "date", "theme", "gravite", "mots_detectes", "langue", "lien"])
        with st.expander("Requêtes exécutées et pistes complémentaires"):
            for q in res["queries"]:
                st.code(f"[{q['theme']} · {q['lang']}] {q['q']}", language=None)
            for label, url in LEADS.items():
                st.markdown(f"- [{label}]({url.format(q=urllib.parse.quote(res['name']))})")
        kept = edited[edited["statut"].isin(["retenu", "à vérifier"])]
        dropped = edited[edited["statut"].isin(["homonyme", "hors sujet"])]
        if ent.access_level(user, sid) == "free":
            kept = kept.head(10)
        ui.export_panel(user, sid, {
            "title": f"Recherche de notoriété : {res['name']}",
            "subtitle": f"{res['kind']} · recherche du {res['date']} · demandeur {user['name']}",
            "kpis": [(str(len(edited)), "liens trouvés"), (str((edited['statut'] == 'retenu').sum()), "retenus"),
                     (str((edited['statut'] == 'à vérifier').sum()), "à vérifier"), (str(len(dropped)), "écartés")],
            "sections": [
                {"heading": "Synthèse", "paragraphs": ["Niveau de vigilance indicatif à apprécier par l'analyste. "
                                                        "L'absence de résultat ne prouve pas l'absence de risque."]},
                {"heading": "Méthodologie", "bullets": [
                    "Base automatique de 15 mots à risque en 5 thèmes, en français et en anglais.",
                    f"Mots ajoutés : {', '.join(res['extra']) or 'aucun'} · Mots exclus : {', '.join(res['exclude']) or 'aucun'}",
                    f"{len(res['queries'])} requêtes sur Google News (titres et liens uniquement)."]},
                {"heading": "Liens retenus ou à vérifier", "table": {
                    "columns": ["Statut", "Titre", "Média", "Date", "Thème", "Gravité", "Lien"],
                    "rows": kept[["statut", "titre", "media", "date", "theme", "gravite", "lien"]].values.tolist()}},
                {"heading": "Liens écartés", "table": {"columns": ["Statut", "Titre", "Lien"],
                                                        "rows": dropped[["statut", "titre", "lien"]].values.tolist()}},
                {"heading": "Pistes complémentaires",
                 "bullets": [f"{k} : {v.format(q=urllib.parse.quote(res['name']))}" for k, v in LEADS.items()]},
            ],
            "sources": ["Google News RSS (titres et liens uniquement)"]}, key="noto_exp", formats=("PDF", "Word", "CSV", "Image PNG"))

    elif tab == "Historique":
        st.caption("Historique de la session uniquement : les recherches nominatives ne sont pas conservées sur le serveur.")
        st.dataframe(pd.DataFrame(st.session_state.get("noto_hist", [])), hide_index=True, width="stretch")
