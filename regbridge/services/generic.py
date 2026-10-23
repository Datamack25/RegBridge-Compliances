"""Gabarit des services en construction : page d'accueil, onglets et exports déjà branchés.

Pour développer un service, copiez ce fichier en services/<nom>.py, changez
`module` dans core/catalog.py, puis remplacez le contenu de chaque onglet.
"""
from datetime import date

import streamlit as st

from core import ui
from core.catalog import SERVICES


def render(tab, user, sid):
    s = SERVICES[sid]
    if tab == "Accueil":
        st.markdown(f"### {s['icon']} {s['name']}")
        st.write(s["pitch"])
        st.info("Module en cours de construction : la structure, les droits et les exports sont en place.")
        st.markdown("**Onglets prévus :** " + " · ".join(s["tabs"][1:]))
    elif tab in ("Rapports", "Prestations", "Imports et exports", "Certificats"):
        st.write("Exemple de livrable généré par le moteur commun (PDF, Word, image, CSV).")
        ui.export_panel(user, sid, {
            "title": f"{s['name']} : rapport de démonstration",
            "subtitle": f"Généré le {date.today():%d/%m/%Y} pour {user.get('organisation') or user['name']}",
            "kpis": [("3", "éléments"), ("1", "point critique"), ("67 %", "avancement")],
            "sections": [{"heading": "Synthèse", "paragraphs": ["Contenu de démonstration : à remplacer par les données du module."]},
                         {"heading": "Tableau", "table": {"columns": ["Élément", "Statut", "Échéance"],
                                                          "rows": [["Exemple A", "conforme", "2026-12-31"],
                                                                   ["Exemple B", "partiel", "2027-03-31"],
                                                                   ["Exemple C", "non conforme", "2027-06-30"]]}}]},
            key=f"gen_{sid}_{tab}")
    else:
        st.caption(f"Onglet « {tab} » : à construire.")
