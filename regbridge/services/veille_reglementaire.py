"""Veille réglementaire : textes classés, résumés développés, liens vers les textes officiels, historique sur 3 ans."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import csvstore, db
from core import entitlements as ent
from core import ui

FILE = "regulations.csv"
MAX_YEARS = 3                 # profondeur maximale de la veille (abonnés et administrateur)
FREE_MAX_DAYS = 365           # profondeur maximale en offre gratuite
IMPACT_ORDER = {"critique": 0, "élevé": 1, "moyen": 2, "faible": 3}
PERIODS = {"1 mois": 31, "3 mois": 92, "6 mois": 183, "1 an": 365, "2 ans": 730, "3 ans": 1096}


def _data() -> pd.DataFrame:
    df = csvstore.read(FILE)
    if df.empty:
        return df
    for c in ("resume_long", "action_requise", "secteurs", "verifie", "lien", "reference"):
        if c not in df.columns:
            df[c] = ""
    df["_pub"] = pd.to_datetime(df["date_publication"], errors="coerce")
    df["_app"] = pd.to_datetime(df["date_application"], errors="coerce")
    df["_imp"] = df["impact"].map(IMPACT_ORDER).fillna(9)
    return df.sort_values(["_pub", "_imp"], ascending=[False, True])


def _max_days(user, sid) -> int:
    return FREE_MAX_DAYS if ent.access_level(user, sid) == "free" else PERIODS["3 ans"]


def _period(df, user, sid, key: str, default: str = "1 an"):
    """Sélecteur de période : 1 mois à 3 ans, ou dates personnalisées (bornées à 3 ans)."""
    max_days = _max_days(user, sid)
    options = [k for k, v in PERIODS.items() if v <= max_days + 1] + ["Personnalisée"]
    c1, c2, c3 = st.columns([1.2, 1, 1])
    choice = c1.selectbox("Période", options, index=options.index(default) if default in options else 0, key=f"{key}_per")
    today = date.today()
    floor = today - timedelta(days=max_days)
    if choice == "Personnalisée":
        start = c2.date_input("Du", today - timedelta(days=365), min_value=floor, max_value=today, key=f"{key}_s")
        end = c3.date_input("Au", today, min_value=floor, max_value=today, key=f"{key}_e")
    else:
        start, end = today - timedelta(days=PERIODS[choice]), today
        c2.caption(f"Du {start:%d/%m/%Y}")
        c3.caption(f"au {end:%d/%m/%Y}")
    if ent.access_level(user, sid) == "free":
        st.caption(f"Offre gratuite : historique limité à 12 mois. Les abonnés remontent jusqu'à {MAX_YEARS} ans.")
    f = df[(df["_pub"] >= pd.Timestamp(start)) & (df["_pub"] <= pd.Timestamp(end) + pd.Timedelta(days=1))]
    return f, start, end


def _filters(df: pd.DataFrame, key: str) -> pd.DataFrame:
    c = st.columns(5)
    for i, (col, label) in enumerate([("theme", "Thème"), ("juridiction", "Juridiction"), ("impact", "Impact"),
                                      ("statut", "Statut"), ("type_texte", "Type")]):
        opts = sorted(v for v in df[col].unique() if v)
        sel = c[i].multiselect(label, opts, key=f"{key}_{col}", placeholder="Tous")
        if sel:
            df = df[df[col].isin(sel)]
    q = st.text_input("Rechercher (titre, référence, résumé)", key=f"{key}_q")
    if q:
        m = (df["titre"].str.contains(q, case=False) | df["resume"].str.contains(q, case=False) |
             df["resume_long"].str.contains(q, case=False) | df["reference"].str.contains(q, case=False))
        df = df[m]
    return df


def _rows(df: pd.DataFrame) -> list[dict]:
    def fmt(d):
        try:
            return pd.Timestamp(d).strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return ""
    return [{"date": fmt(r["date_publication"]), "titre": r["titre"], "reference": r["reference"], "theme": r["theme"],
             "resume": r["resume"], "resume_long": r["resume_long"], "juridiction": r["juridiction"], "type": r["type_texte"],
             "statut": r["statut"], "impact": r["impact"], "application": fmt(r["date_application"]) if r["date_application"] else "",
             "nouveau": r.get("nouveaute") == "nouveau", "action": r["action_requise"], "secteurs": r["secteurs"],
             "lien": r["lien"], "verifie": r["verifie"]} for _, r in df.iterrows()]


FOOT = ("Résumés rédigés pour la veille : à vérifier sur le texte officiel (EUR-Lex, Légifrance, GAFI, autorités) "
        "avant toute décision. Cliquez sur un titre pour lire le résumé développé.")


def _report(df: pd.DataFrame, title: str, subtitle: str) -> dict:
    d = df.sort_values(["_imp", "_pub"], ascending=[True, False])
    sections = [{"heading": "Vue d'ensemble",
                 "table": {"columns": ["Publication", "Texte", "Juridiction", "Thème", "Impact", "Application"],
                           "rows": d[["date_publication", "titre", "juridiction", "theme", "impact", "date_application"]].values.tolist()}}]
    for _, r in d.iterrows():
        sections.append({
            "heading": r["titre"],
            "paragraphs": [f"{r['reference']} · {r['juridiction']} · {r['type_texte']} · {r['statut']} · impact {r['impact']}"
                           + (f" · application {r['date_application']}" if r["date_application"] else ""),
                           r["resume_long"] or r["resume"],
                           f"Action recommandée : {r['action_requise']}"],
            "links": [("Lire le texte complet", r["lien"])] if r["lien"] else [],
        })
    return {"title": title, "subtitle": subtitle,
            "kpis": [(str(len(d)), "textes"), (str((d["impact"] == "critique").sum()), "impact critique"),
                     (str((d["nouveaute"] == "nouveau").sum()), "nouveaux"),
                     (str((d["_app"] > pd.Timestamp(date.today())).sum()), "échéances à venir")],
            "sections": sections,
            "sources": ["Résumés rédigés pour la veille ; textes officiels accessibles par les liens de chaque fiche."]}


def render(tab: str, user: dict, sid: str) -> None:
    df = _data()
    if df.empty:
        st.info("Aucun texte dans le référentiel pour le moment.")
        return

    if tab == "Accueil":
        recent = df[df["_pub"] >= pd.Timestamp(date.today() - timedelta(days=_max_days(user, sid)))]
        today = pd.Timestamp(date.today())
        ui.kpis([(str(len(recent)), "textes sur la période"), (str((recent["impact"] == "critique").sum()), "impact critique"),
                 (str((recent["nouveaute"] == "nouveau").sum()), "nouveaux textes"),
                 (str(((df["_app"] > today) & (df["_app"] < today + pd.Timedelta(days=365))).sum()), "échéances sous 12 mois")])
        st.write("")
        ui.watch_banner("Dernières publications", "Les 10 textes les plus récents · cliquez sur un titre pour lire le résumé et ouvrir le texte")
        ui.watch_table(_rows(recent.head(10)), FOOT)
        crit = df[(df["_app"] >= today) & (df["impact"].isin(["critique", "élevé"]))].sort_values("_app").head(5)
        if not crit.empty:
            st.write("")
            ui.watch_banner("Prochaines échéances importantes", "Textes à impact critique ou élevé dont l'application approche")
            ui.watch_table(_rows(crit), "")

    elif tab == "Tableau des textes":
        f, start, end = _period(df, user, sid, "vr_tab", default="3 ans" if _max_days(user, sid) > 400 else "1 an")
        f = _filters(f, "vr_tab")
        ui.watch_banner("Veille réglementaire — Sécurité financière",
                        f"{len(f)} texte(s) · du {start:%d/%m/%Y} au {end:%d/%m/%Y} · classés du plus récent au plus ancien")
        if f.empty:
            st.info("Aucun texte sur cette période avec ces filtres.")
        else:
            ui.watch_table(_rows(f), FOOT)
        if user["role"] == "admin":
            with st.expander("Ajouter un texte au référentiel (administrateur)"):
                _admin_add(user)

    elif tab == "Échéances":
        today = pd.Timestamp(date.today())
        up = df[df["_app"] >= today].sort_values("_app").copy()
        ui.watch_banner("Échéances à venir", "Textes dont la date d'application est future, de la plus proche à la plus lointaine")
        rows = _rows(up)
        for r, (_, x) in zip(rows, up.iterrows()):
            r["application"] = f"{r['application']} (J-{(x['_app'] - today).days})"
        ui.watch_table(rows, FOOT)

    elif tab == "Fiches d'impact":
        choice = st.selectbox("Texte", df["titre"].tolist())
        r = df[df["titre"] == choice].iloc[0]
        ui.watch_table(_rows(df[df["titre"] == choice]), "")
        st.markdown(f"#### {r['titre']}")
        st.write(r["resume_long"] or r["resume"])
        st.markdown(f"**Action recommandée :** {r['action_requise']}")
        if r["lien"]:
            st.link_button("Lire le texte complet ↗", r["lien"])
        ui.export_panel(user, sid, {
            "title": f"Fiche d'impact : {r['titre']}", "subtitle": f"{r['reference']} · {r['juridiction']}",
            "sections": [{"heading": "Résumé", "paragraphs": [r["resume_long"] or r["resume"]],
                          "links": [("Lire le texte complet", r["lien"])] if r["lien"] else []},
                         {"heading": "Qui est concerné", "paragraphs": [r["secteurs"]]},
                         {"heading": "Action recommandée", "paragraphs": [r["action_requise"]]},
                         {"heading": "Caractéristiques", "table": {"columns": ["Statut", "Impact", "Application", "Vérifié"],
                                                                    "rows": [[r["statut"], r["impact"], r["date_application"], r["verifie"]]]}}],
            "sources": [r["lien"]] if r["lien"] else []}, key="vr_fiche")

    elif tab == "Bulletins et exports":
        f, start, end = _period(df, user, sid, "vr_exp", default="3 mois")
        f = _filters(f, "vr_exp")
        st.write(f"**{len(f)} texte(s)** retenus pour le bulletin : vue d'ensemble, puis une fiche par texte avec résumé développé et lien.")
        ui.watch_table(_rows(f.head(15)), "Aperçu des 15 premiers textes du bulletin." if len(f) > 15 else "")
        ui.export_panel(user, sid, _report(f, "Bulletin de veille réglementaire",
                                           f"Période du {start:%d/%m/%Y} au {end:%d/%m/%Y}"), key="vr_bulletin")


def _admin_add(user: dict) -> None:
    with st.form("vr_add", clear_on_submit=True):
        c = st.columns(3)
        titre = st.text_input("Titre")
        ref = c[0].text_input("Référence")
        jur = c[1].selectbox("Juridiction", ["UE", "France", "Suisse", "Luxembourg", "États-Unis", "Royaume-Uni", "International"])
        theme = c[2].text_input("Thème", "LCB-FT")
        typ = c[0].text_input("Type de texte", "règlement")
        statut = c[1].selectbox("Statut", ["projet", "adopté", "publié", "en vigueur", "abrogé"])
        impact = c[2].selectbox("Impact", ["critique", "élevé", "moyen", "faible"])
        pub = c[0].date_input("Publication", min_value=date.today() - timedelta(days=PERIODS["3 ans"] + 365))
        app = c[1].date_input("Application")
        secteurs = c[2].text_input("Secteurs", "banque; paiement")
        resume = st.text_input("Résumé court (une phrase)")
        resume_long = st.text_area("Résumé développé (5 à 8 phrases, vos mots, pas de copie du texte)", height=160)
        action = st.text_input("Action recommandée")
        lien = st.text_input("Lien vers le texte officiel (https://...)")
        if st.form_submit_button("Ajouter", type="primary") and titre:
            n = len(csvstore.read(FILE)) + 1
            csvstore.append(FILE, [{"id": f"REG-{n:05d}", "date_publication": pub.isoformat(), "titre": titre, "reference": ref,
                                    "juridiction": jur, "theme": theme, "type_texte": typ, "statut": statut, "secteurs": secteurs,
                                    "impact": impact, "date_application": app.isoformat(), "nouveaute": "nouveau", "resume": resume,
                                    "resume_long": resume_long, "action_requise": action, "lien": lien, "verifie": "non",
                                    "date_collecte": date.today().isoformat()}])
            db.audit(user["email"], "veille_texte_ajoute", {"titre": titre})
            st.success("Texte ajouté.")
