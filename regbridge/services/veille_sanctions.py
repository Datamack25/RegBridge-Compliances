"""Veille sanctions et embargos : journal des changements, régimes, alertes sur un portefeuille, bulletins."""
import difflib
import unicodedata
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import csvstore
from core import entitlements as ent
from core import ui

FILE = "sanctions_changes.csv"
FREE_WINDOW_DAYS = 90


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s).split())


def _data(user, sid):
    df = csvstore.read(FILE)
    if df.empty:
        return df
    df["_d"] = pd.to_datetime(df["date"], errors="coerce")
    if ent.access_level(user, sid) == "free":
        df = df[df["_d"] >= pd.Timestamp(date.today() - timedelta(days=FREE_WINDOW_DAYS))]
    return df.sort_values("_d", ascending=False)


def _filters(df, key):
    c = st.columns(4)
    for i, col in enumerate(["regime", "type_changement", "type_entite", "pays"]):
        opts = sorted(v for v in df[col].unique() if v)
        sel = c[i].multiselect(col.replace("_", " ").capitalize(), opts, key=f"{key}_{col}")
        if sel:
            df = df[df[col].isin(sel)]
    return df


def _report(df, start, end):
    return {
        "title": "Veille sanctions et embargos",
        "subtitle": f"Période du {start:%d/%m/%Y} au {end:%d/%m/%Y}",
        "kpis": [(str((df["type_changement"] == "ajout").sum()), "ajouts"),
                 (str((df["type_changement"] == "radiation").sum()), "radiations"),
                 (str((df["type_changement"] == "modification").sum()), "modifications"),
                 (str(df["regime"].nunique()), "régimes")],
        "sections": [
            {"heading": "Répartition par régime",
             "table": {"columns": ["Régime", "Changements"],
                       "rows": df["regime"].value_counts().reset_index().values.tolist()}},
            {"heading": "Journal des changements",
             "table": {"columns": ["Date", "Régime", "Programme", "Changement", "Nom", "Type", "Pays", "Référence"],
                       "rows": df[["date", "regime", "programme", "type_changement", "nom", "type_entite", "pays",
                                   "reference_officielle"]].values.tolist()}},
            {"heading": "Avertissement",
             "paragraphs": ["Un gel d'avoirs se vérifie sur le registre officiel (DG Trésor, journal officiel de l'UE, OFAC, SECO) "
                            "avant toute décision."]}],
        "sources": sorted(set(df["lien"]) - {""})[:20],
    }


def render(tab, user, sid):
    df = _data(user, sid)
    if df.empty:
        st.info("Aucun changement enregistré.")
        return
    if (df.get("donnee_demo", pd.Series(dtype=str)) == "oui").any():
        st.warning("Le fichier contient des lignes de démonstration (fictives). Branchez l'ingestion des listes officielles "
                   "(scripts/ingest_sanctions.py) avant tout usage réel.")

    if tab == "Accueil":
        last30 = df[df["_d"] >= pd.Timestamp(date.today() - timedelta(days=30))]
        ui.kpis([(str((last30["type_changement"] == "ajout").sum()), "ajouts sur 30 jours"),
                 (str((last30["type_changement"] == "radiation").sum()), "radiations sur 30 jours"),
                 (str(df["regime"].nunique()), "régimes suivis"), (str(df["pays"].nunique()), "pays concernés")])
        st.subheader("Derniers changements")
        st.dataframe(df.head(10)[["date", "regime", "type_changement", "nom", "type_entite", "pays"]],
                     hide_index=True, width="stretch")

    elif tab == "Journal des changements":
        f = _filters(df, "vs_j")
        st.dataframe(f[["date", "regime", "programme", "type_changement", "nom", "type_entite", "pays", "motif_resume", "lien"]],
                     hide_index=True, width="stretch", column_config={"lien": st.column_config.LinkColumn("Source")})

    elif tab == "Régimes et pays":
        c1, c2 = st.columns(2)
        c1.markdown("**Changements par régime**")
        c1.bar_chart(df["regime"].value_counts())
        c2.markdown("**Pays les plus concernés**")
        c2.bar_chart(df[df["pays"] != ""]["pays"].value_counts().head(12))

    elif tab == "Alertes portefeuille":
        st.write("Collez les noms de votre portefeuille (un par ligne). Le rapprochement est approximatif : "
                 "chaque correspondance doit être revue par un analyste.")
        names = st.text_area("Portefeuille", height=140)
        seuil = st.slider("Seuil de similarité", 0.70, 1.00, 0.86, 0.01)
        if st.button("Rapprocher", type="primary") and names.strip():
            listed = {norm(n): n for n in df["nom"]}
            hits = []
            for raw in [x for x in names.splitlines() if x.strip()]:
                for k, orig in listed.items():
                    score = difflib.SequenceMatcher(None, norm(raw), k).ratio()
                    if score >= seuil:
                        row = df[df["nom"] == orig].iloc[0]
                        hits.append({"nom_portefeuille": raw, "nom_liste": orig, "score": round(score, 2),
                                     "regime": row["regime"], "changement": row["type_changement"], "date": row["date"]})
            st.session_state.vs_hits = pd.DataFrame(hits)
        if "vs_hits" in st.session_state:
            h = st.session_state.vs_hits
            st.write(f"{len(h)} correspondance(s) à revoir.")
            st.dataframe(h, hide_index=True, width="stretch")

    elif tab == "Bulletins et exports":
        c1, c2 = st.columns(2)
        start = c1.date_input("Du", date.today() - timedelta(days=30), key="vs_s")
        end = c2.date_input("Au", date.today(), key="vs_e")
        f = df[(df["_d"] >= pd.Timestamp(start)) & (df["_d"] <= pd.Timestamp(end))]
        f = _filters(f, "vs_x")
        st.write(f"{len(f)} changements retenus.")
        ui.export_panel(user, sid, _report(f, start, end), key="vs_bulletin")
