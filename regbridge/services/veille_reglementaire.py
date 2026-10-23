"""Veille réglementaire : tableau classé des textes, échéances, fiches d'impact, bulletins."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import csvstore, db
from core import entitlements as ent
from core import ui

FILE = "regulations.csv"
FREE_WINDOW_DAYS = 365          # profondeur d'historique visible en gratuit (30 jours une fois la veille alimentée chaque jour)
IMPACT_ORDER = {"critique": 0, "élevé": 1, "moyen": 2, "faible": 3}
COLS = ["date_publication", "titre", "juridiction", "theme", "type_texte", "statut", "impact", "nouveaute", "date_application"]


def _data(user, sid) -> pd.DataFrame:
    df = csvstore.read(FILE)
    if df.empty:
        return df
    df["_pub"] = pd.to_datetime(df["date_publication"], errors="coerce")
    df["_app"] = pd.to_datetime(df["date_application"], errors="coerce")
    df["_imp"] = df["impact"].map(IMPACT_ORDER).fillna(9)
    if ent.access_level(user, sid) == "free":
        df = df[df["_pub"] >= pd.Timestamp(date.today() - timedelta(days=FREE_WINDOW_DAYS))]
    return df.sort_values(["_pub", "_imp"], ascending=[False, True])


def _filters(df: pd.DataFrame, key: str) -> pd.DataFrame:
    c = st.columns(5)
    for i, col in enumerate(["theme", "juridiction", "impact", "statut", "nouveaute"]):
        opts = sorted(v for v in df[col].unique() if v)
        sel = c[i].multiselect(col.replace("_", " ").capitalize(), opts, key=f"{key}_{col}")
        if sel:
            df = df[df[col].isin(sel)]
    q = st.text_input("Recherche dans les titres et résumés", key=f"{key}_q")
    if q:
        m = df["titre"].str.contains(q, case=False) | df["resume"].str.contains(q, case=False)
        df = df[m]
    return df


def _report(df: pd.DataFrame, title: str, subtitle: str) -> dict:
    return {
        "title": title, "subtitle": subtitle,
        "kpis": [(str(len(df)), "textes"), (str((df["impact"] == "critique").sum()), "impact critique"),
                 (str((df["nouveaute"] == "nouveau").sum()), "nouveaux"),
                 (str((df["_app"] > pd.Timestamp(date.today())).sum()), "échéances à venir")],
        "sections": [{"heading": "Textes de la période, classés par impact",
                      "table": {"columns": ["Publication", "Texte", "Juridiction", "Thème", "Impact", "Nouveauté", "Application", "Action requise"],
                                "rows": df.sort_values("_imp")[["date_publication", "titre", "juridiction", "theme", "impact",
                                                                "nouveaute", "date_application", "action_requise"]].values.tolist()}}],
        "sources": sorted(set(df["lien"]) - {""})[:25],
    }


def render(tab: str, user: dict, sid: str) -> None:
    df = _data(user, sid)
    if df.empty:
        st.info("Aucun texte dans le référentiel pour le moment.")
        return
    if ent.access_level(user, sid) == "free":
        st.caption(f"Offre gratuite : textes des {FREE_WINDOW_DAYS} derniers jours.")

    if tab == "Accueil":
        today = pd.Timestamp(date.today())
        ui.kpis([(str(len(df)), "textes suivis"), (str((df["impact"] == "critique").sum()), "impact critique"),
                 (str((df["nouveaute"] == "nouveau").sum()), "nouveaux textes"),
                 (str(((df["_app"] > today) & (df["_app"] < today + pd.Timedelta(days=365))).sum()), "échéances sous 12 mois")])
        st.subheader("Dernières publications")
        for _, r in df.head(6).iterrows():
            with st.container(border=True):
                st.markdown(f"**{r['titre']}**  \n{r['juridiction']} · {r['theme']} · impact **{r['impact']}** · {r['nouveaute']}")
                st.caption(r["resume"])

    elif tab == "Tableau des textes":
        f = _filters(df, "vr_tab")
        st.dataframe(f[COLS + ["lien"]], hide_index=True, width="stretch",
                     column_config={"lien": st.column_config.LinkColumn("Source")})
        if user["role"] == "admin":
            with st.expander("Ajouter un texte au référentiel (administrateur)"):
                _admin_add(user)

    elif tab == "Échéances":
        today = pd.Timestamp(date.today())
        up = df[df["_app"] >= today].sort_values("_app").copy()
        up["jours_restants"] = (up["_app"] - today).dt.days
        st.dataframe(up[["date_application", "jours_restants", "titre", "juridiction", "impact", "action_requise"]],
                     hide_index=True, width="stretch")

    elif tab == "Fiches d'impact":
        choice = st.selectbox("Texte", df["titre"].tolist())
        r = df[df["titre"] == choice].iloc[0]
        st.markdown(f"### {r['titre']}")
        st.markdown(f"**Référence :** {r['reference']}  \n**Juridiction :** {r['juridiction']} · **Type :** {r['type_texte']} · "
                    f"**Statut :** {r['statut']}  \n**Secteurs :** {r['secteurs']}  \n**Impact :** {r['impact']} · "
                    f"**Application :** {r['date_application']}")
        st.write(r["resume"])
        st.markdown(f"**Action requise :** {r['action_requise']}")
        st.markdown(f"[Source officielle]({r['lien']}) · vérifié : {r['verifie']} · collecté le {r['date_collecte']}")
        ui.export_panel(user, sid, {
            "title": f"Fiche d'impact : {r['titre']}", "subtitle": f"{r['reference']} · {r['juridiction']}",
            "sections": [{"heading": "Résumé", "paragraphs": [r["resume"]]},
                         {"heading": "Qui est concerné", "paragraphs": [r["secteurs"]]},
                         {"heading": "Action requise", "paragraphs": [r["action_requise"]]},
                         {"heading": "Caractéristiques", "table": {"columns": ["Statut", "Impact", "Application", "Vérifié"],
                                                                    "rows": [[r["statut"], r["impact"], r["date_application"], r["verifie"]]]}}],
            "sources": [r["lien"]]}, key="vr_fiche")

    elif tab == "Bulletins et exports":
        c1, c2 = st.columns(2)
        start = c1.date_input("Du", date.today() - timedelta(days=90))
        end = c2.date_input("Au", date.today())
        f = df[(df["_pub"] >= pd.Timestamp(start)) & (df["_pub"] <= pd.Timestamp(end))]
        f = _filters(f, "vr_exp")
        st.write(f"{len(f)} textes retenus pour le bulletin.")
        st.dataframe(f[COLS], hide_index=True, width="stretch", height=240)
        ui.export_panel(user, sid, _report(f, "Bulletin de veille réglementaire",
                                           f"Période du {start:%d/%m/%Y} au {end:%d/%m/%Y}"), key="vr_bulletin")


def _admin_add(user: dict) -> None:
    with st.form("vr_add", clear_on_submit=True):
        c = st.columns(3)
        titre = st.text_input("Titre")
        ref = c[0].text_input("Référence")
        jur = c[1].selectbox("Juridiction", ["UE", "France", "Suisse", "Luxembourg", "États-Unis", "International"])
        theme = c[2].text_input("Thème", "LCB-FT")
        typ = c[0].text_input("Type de texte", "règlement")
        statut = c[1].selectbox("Statut", ["projet", "adopté", "publié", "en vigueur", "abrogé"])
        impact = c[2].selectbox("Impact", ["critique", "élevé", "moyen", "faible"])
        pub = c[0].date_input("Publication")
        app = c[1].date_input("Application")
        secteurs = c[2].text_input("Secteurs", "banque; paiement")
        resume = st.text_area("Résumé (vos mots, pas de copie du texte)")
        action = st.text_input("Action requise")
        lien = st.text_input("Lien officiel")
        if st.form_submit_button("Ajouter", type="primary") and titre:
            n = len(csvstore.read(FILE)) + 1
            csvstore.append(FILE, [{"id": f"REG-{n:05d}", "date_publication": pub.isoformat(), "titre": titre, "reference": ref,
                                    "juridiction": jur, "theme": theme, "type_texte": typ, "statut": statut, "secteurs": secteurs,
                                    "impact": impact, "date_application": app.isoformat(), "nouveaute": "nouveau", "resume": resume,
                                    "action_requise": action, "lien": lien, "verifie": "non", "date_collecte": date.today().isoformat()}])
            db.audit(user["email"], "veille_texte_ajoute", {"titre": titre})
            st.success("Texte ajouté.")
