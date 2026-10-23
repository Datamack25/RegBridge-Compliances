"""Référentiel des typologies de fraude et de blanchiment, enrichi en continu.

Enrichissement :
- un utilisateur propose une typologie (statut « proposé ») ;
- l'administrateur valide ou rejette (jamais de suppression : statut « rejeté ») ;
- l'administrateur peut importer un CSV de typologies (fusion par identifiant, nouvelles lignes en « proposé »).
"""
from datetime import date

import pandas as pd
import streamlit as st

from core import csvstore, db
from core import ui

FILE = "fraud_typologies.csv"
COLS = ["id", "categorie", "typologie", "description", "signaux", "secteurs", "canal", "gravite", "references", "statut",
        "date_ajout", "ajoute_par", "valide_par"]


def render(tab, user, sid):
    df = csvstore.read(FILE)
    valid = df[df["statut"] == "validé"] if not df.empty else df

    if tab == "Accueil":
        ui.kpis([(str(len(valid)), "typologies validées"), (str(valid["categorie"].nunique()), "catégories"),
                 (str((df["statut"] == "proposé").sum()), "propositions en attente"),
                 (str((valid["gravite"] == "élevée").sum()), "gravité élevée")])
        st.bar_chart(valid["categorie"].value_counts())

    elif tab == "Référentiel":
        c = st.columns(3)
        cat = c[0].multiselect("Catégorie", sorted(valid["categorie"].unique()), placeholder="Choisir")
        sec = c[1].text_input("Secteur contient")
        q = c[2].text_input("Mot-clé (typologie, signal)")
        f = valid
        if cat:
            f = f[f["categorie"].isin(cat)]
        if sec:
            f = f[f["secteurs"].str.contains(sec, case=False)]
        if q:
            f = f[f["typologie"].str.contains(q, case=False) | f["signaux"].str.contains(q, case=False) |
                  f["description"].str.contains(q, case=False)]
        st.dataframe(f[COLS[:9]], hide_index=True, width="stretch")
        if user["role"] == "admin":
            st.divider()
            st.markdown("**Validation des propositions (administrateur)**")
            pend = df[df["statut"] == "proposé"]
            if pend.empty:
                st.caption("Aucune proposition en attente.")
            for _, r in pend.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{r['typologie']}** · {r['categorie']} · proposé par {r['ajoute_par']}")
                    st.caption(r["description"])
                    a, b = st.columns(2)
                    if a.button("Valider", key=f"ok_{r['id']}"):
                        csvstore.update_where(FILE, "id", r["id"], {"statut": "validé", "valide_par": user["email"]})
                        db.audit(user["email"], "typologie_validee", r["id"]); st.rerun()
                    if b.button("Rejeter", key=f"ko_{r['id']}"):
                        csvstore.update_where(FILE, "id", r["id"], {"statut": "rejeté", "valide_par": user["email"]})
                        db.audit(user["email"], "typologie_rejetee", r["id"]); st.rerun()
            st.markdown("**Importer un CSV de typologies**")
            up = st.file_uploader("CSV (mêmes colonnes, séparateur ;)", type=["csv"], key="fr_up")
            if up and st.button("Fusionner"):
                new = pd.read_csv(up, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
                n = 0
                for rec in new.to_dict("records"):
                    rec.setdefault("statut", "proposé")
                    rec["statut"] = rec["statut"] or "proposé"
                    rec["ajoute_par"] = rec.get("ajoute_par") or user["email"]
                    rec["date_ajout"] = rec.get("date_ajout") or date.today().isoformat()
                    if csvstore.upsert(FILE, "id", rec) != "inchange":
                        n += 1
                db.audit(user["email"], "typologies_importees", {"lignes": n})
                st.success(f"{n} ligne(s) ajoutée(s) ou mise(s) à jour, à valider.")

    elif tab == "Proposer une typologie":
        with st.form("fr_new", clear_on_submit=True):
            c = st.columns(3)
            cat = c[0].selectbox("Catégorie", sorted(set(df["categorie"])) + ["Autre"])
            grav = c[1].selectbox("Gravité", ["faible", "moyenne", "élevée"])
            canal = c[2].text_input("Canal", "virement")
            typ = st.text_input("Nom de la typologie")
            desc = st.text_area("Description (vos mots)")
            sig = st.text_input("Signaux d'alerte (séparés par |)")
            secteurs = st.text_input("Secteurs concernés (séparés par ;)")
            refs = st.text_input("Références (Tracfin, GAFI, ACPR...)")
            if st.form_submit_button("Proposer", type="primary") and typ:
                nid = f"FRD-{len(df) + 1:04d}"
                csvstore.append(FILE, [{"id": nid, "categorie": cat, "typologie": typ, "description": desc, "signaux": sig,
                                        "secteurs": secteurs, "canal": canal, "gravite": grav, "references": refs,
                                        "statut": "validé" if user["role"] == "admin" else "proposé",
                                        "date_ajout": date.today().isoformat(), "ajoute_par": user["email"],
                                        "valide_par": user["email"] if user["role"] == "admin" else ""}])
                db.audit(user["email"], "typologie_proposee", nid)
                st.success("Typologie enregistrée" + (" et validée." if user["role"] == "admin" else ", en attente de validation."))

    elif tab == "Exports":
        cat = st.multiselect("Catégories à exporter", sorted(valid["categorie"].unique()), placeholder="Choisir")
        f = valid[valid["categorie"].isin(cat)] if cat else valid
        ui.export_panel(user, sid, {
            "title": "Référentiel des typologies de fraude et de blanchiment",
            "subtitle": f"{len(f)} typologies validées · état au {date.today():%d/%m/%Y}",
            "kpis": [(str(len(f)), "typologies"), (str(f["categorie"].nunique()), "catégories"),
                     (str((f["gravite"] == "élevée").sum()), "gravité élevée")],
            "sections": [{"heading": "Typologies", "table": {"columns": ["Id", "Catégorie", "Typologie", "Signaux", "Secteurs", "Gravité"],
                          "rows": f[["id", "categorie", "typologie", "signaux", "secteurs", "gravite"]].values.tolist()}}],
            "sources": sorted(set(x for r in f["references"] for x in r.split(";") if x.strip()))}, key="fr_exp")
