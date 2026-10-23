"""Recherche entreprise 360° : fiche entité, cartographie, examen renforcé, base des entités.

Chaque recherche enrichit les CSV publics (entities.csv, entity_financials.csv,
entity_relations.csv) et journalise chaque changement dans entity_enrichment_log.csv.
Les fichiers déposés pour l'examen renforcé restent dans la session : ils
n'alimentent jamais les CSV partagés.
"""
import difflib
import io
from datetime import date, datetime, timezone

import pandas as pd
import requests
import streamlit as st

from core import csvstore, db
from core import entitlements as ent
from core import ui
from services.veille_sanctions import norm

API = "https://recherche-entreprises.api.gouv.fr/search"
ENT, FIN, REL, LOG, QUEUE = ("entities.csv", "entity_financials.csv", "entity_relations.csv",
                             "entity_enrichment_log.csv", "entity_queue.csv")

FORMES = {"5710": "SAS", "5720": "SASU", "5499": "SARL", "5498": "EURL", "5599": "SA à conseil d'administration",
          "5699": "SA à directoire", "6540": "SCI", "9220": "Association déclarée", "9221": "Association d'insertion",
          "9300": "Fondation", "1000": "Entrepreneur individuel", "5202": "SNC", "6599": "Société civile"}
EFFECTIFS = {"NN": "non renseigné", "00": "0", "01": "1-2", "02": "3-5", "03": "6-9", "11": "10-19", "12": "20-49",
             "21": "50-99", "22": "100-199", "31": "200-249", "32": "250-499", "41": "500-999", "42": "1000-1999",
             "51": "2000-4999", "52": "5000-9999", "53": "10000+"}
# Activités souvent citées comme exposées (espèces, valeur, opacité) : indicatif, à calibrer.
NAF_SENSIBLES = {"45.11Z": "commerce de véhicules", "47.77Z": "bijouterie", "68.31Z": "agence immobilière",
                 "92.00Z": "jeux d'argent", "64.99Z": "services financiers divers", "66.12Z": "courtage",
                 "46.72Z": "commerce de métaux", "56.30Z": "débits de boissons", "49.32Z": "taxis"}
# Liste noire GAFI (appel à l'action) : à resynchroniser après chaque plénière via countries.csv.
PAYS_LISTE_NOIRE = {"KP", "IR", "MM"}


# ------------------------------------------------------------------ collecte
def search_api(q: str) -> list[dict]:
    r = requests.get(API, params={"q": q, "per_page": 10, "page": 1}, timeout=12,
                     headers={"User-Agent": "RegBridge/0.1 (veille conformite)"})
    r.raise_for_status()
    return r.json().get("results", [])


def search_local(q: str) -> list[dict]:
    df = csvstore.read(ENT)
    if df.empty:
        return []
    m = df["denomination"].str.contains(q, case=False) | (df["siren"] == q.replace(" ", ""))
    return [{"_local": True, **r} for r in df[m].head(10).to_dict("records")]


def entity_type(r: dict) -> str:
    nj = str(r.get("nature_juridique") or "")
    if (r.get("complements") or {}).get("est_association") or nj.startswith("92"):
        return "association"
    if nj.startswith("93"):
        return "fondation"
    if nj.startswith("7"):
        return "organisme public"
    return "societe"


def normalize(r: dict) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """Résultat API -> (ligne entité, exercices, relations PM, dirigeants pour affichage)."""
    siege = r.get("siege") or {}
    comp = r.get("complements") or {}
    fin = r.get("finances") or {}
    years = sorted(fin.keys())
    last = fin[years[-1]] if years else {}
    nj = str(r.get("nature_juridique") or "")
    siren = r.get("siren", "")
    row = {
        "entity_id": f"FR-{siren}", "type_entite": entity_type(r),
        "denomination": r.get("nom_complet") or r.get("nom_raison_sociale") or "", "sigle": r.get("sigle") or "",
        "siren": siren, "siret_siege": siege.get("siret", ""), "rna": comp.get("identifiant_association") or "",
        "pays": "FR", "forme_juridique": FORMES.get(nj, nj), "date_creation": r.get("date_creation") or "",
        "statut": "actif" if r.get("etat_administratif") == "A" else "cessé",
        "naf_code": r.get("activite_principale") or siege.get("activite_principale") or "",
        "tranche_effectif": EFFECTIFS.get(str(r.get("tranche_effectif_salarie") or "NN"), ""),
        "categorie": r.get("categorie_entreprise") or "",
        "adresse_siege": siege.get("adresse") or "", "code_postal": siege.get("code_postal") or "",
        "commune": siege.get("libelle_commune") or "",
        "nb_etablissements": str(r.get("nombre_etablissements_ouverts") or ""),
        "ca_dernier_eur": str(last.get("ca") or ""), "resultat_dernier_eur": str(last.get("resultat_net") or ""),
        "exercice_dernier": years[-1] if years else "",
        "labels": ";".join(k.replace("est_", "") for k, v in comp.items() if k.startswith("est_") and v is True),
        "latitude": siege.get("latitude") or "", "longitude": siege.get("longitude") or "",
    }
    fins = [{"cle": f"{siren}_{y}", "entity_id": row["entity_id"], "exercice": y,
             "chiffre_affaires_eur": str(fin[y].get("ca") or ""), "resultat_net_eur": str(fin[y].get("resultat_net") or ""),
             "source": "api_recherche_entreprises", "date_collecte": date.today().isoformat()} for y in years]
    dirigeants, rels = [], []
    for d in r.get("dirigeants") or []:
        if d.get("type_dirigeant") == "personne morale":
            name = d.get("denomination") or ""
            dirigeants.append({"type": "personne morale", "nom": name, "qualite": d.get("qualite") or "", "siren": d.get("siren") or ""})
            if d.get("siren"):
                rels.append({"relation_id": f"FR-{d['siren']}>{row['entity_id']}:dirige", "source_entity_id": f"FR-{d['siren']}",
                             "source_nom": name, "cible_entity_id": row["entity_id"], "cible_nom": row["denomination"],
                             "type_relation": "dirige", "qualite": d.get("qualite") or "", "source_donnee": "api_recherche_entreprises",
                             "methode": "api", "confiance": "0.98", "statut": "officiel", "derniere_observation": date.today().isoformat()})
        else:
            nom = " ".join(x for x in [d.get("prenoms"), d.get("nom")] if x)
            dirigeants.append({"type": "personne physique", "nom": nom, "qualite": d.get("qualite") or "",
                               "annee_naissance": (d.get("date_de_naissance") or "")[:4]})
    return row, fins, rels, dirigeants


# ------------------------------------------------------------------ scores
def risk_signals(row: dict) -> list[tuple[str, str]]:
    sig = []
    if row.get("statut") != "actif":
        sig.append(("élevé", "Entité cessée ou radiée"))
    try:
        age = (date.today() - date.fromisoformat(row["date_creation"])).days / 365
        if age < 2:
            sig.append(("moyen", f"Création récente ({age:.1f} an)"))
    except (ValueError, KeyError, TypeError):
        pass
    if row.get("naf_code") in NAF_SENSIBLES:
        sig.append(("moyen", f"Activité exposée : {NAF_SENSIBLES[row['naf_code']]}"))
    if row.get("type_entite") == "association":
        sig.append(("info", "Association : vérifier l'origine des dons et la destination des fonds"))
    sanc = csvstore.read("sanctions_changes.csv")
    if not sanc.empty:
        n = norm(row.get("denomination", ""))
        for s in sanc["nom"]:
            if difflib.SequenceMatcher(None, n, norm(s)).ratio() > 0.9:
                sig.append(("élevé", f"Nom proche d'une désignation : {s} (à revoir)"))
    return sig


def score(row: dict, signals) -> tuple[float, int]:
    keys = ["siren", "denomination", "forme_juridique", "date_creation", "naf_code", "adresse_siege",
            "tranche_effectif", "ca_dernier_eur", "statut"]
    completude = sum(1 for k in keys if row.get(k)) / len(keys)
    pts = {"élevé": 30, "moyen": 12, "info": 3}
    return round(completude, 2), min(100, 15 + sum(pts.get(g, 0) for g, _ in signals))


# ------------------------------------------------------------------ enrichissement des CSV
def enrich(row, fins, rels, actor: str) -> dict:
    """Écrit l'entité et ses exercices/relations, journalise chaque champ modifié."""
    old = csvstore.read(ENT)
    prev = old[old["siren"] == row["siren"]].iloc[0].to_dict() if not old.empty and row["siren"] in set(old["siren"]) else {}
    signals = risk_signals(row)
    comp, risk = score(row, signals)
    row = {**row, "score_completude": comp, "score_risque_indicatif": risk, "nb_relations": len(rels),
           "derniere_maj": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sources": "api_recherche_entreprises", "version_fiche": str(int(prev.get("version_fiche", "0") or 0) + 1)}
    status = csvstore.upsert(ENT, "siren", row)
    changes = []
    for k, v in row.items():
        if k in ("derniere_maj", "version_fiche"):
            continue
        if str(prev.get(k, "")) != str(v) and str(v) != "":
            changes.append({"horodatage": row["derniere_maj"], "entity_id": row["entity_id"], "champ": k,
                            "ancienne_valeur": prev.get(k, ""), "nouvelle_valeur": v, "source": "api_recherche_entreprises",
                            "methode": "api", "confiance": "0.98", "statut": "applique", "valide_par": f"auto ({actor})"})
    if status == "inchange":
        csvstore.update_where(ENT, "siren", row["siren"], {"derniere_maj": row["derniere_maj"]})
    if changes and status != "inchange":
        csvstore.append(LOG, changes)
    for f in fins:
        csvstore.upsert(FIN, "cle", f)
    known = set(old["entity_id"]) if not old.empty else set()
    for r in rels:
        csvstore.upsert(REL, "relation_id", r)
        if r["source_entity_id"] not in known:     # entité découverte : file d'attente, niveau 1 seulement
            csvstore.upsert(QUEUE, "entity_id", {"entity_id": r["source_entity_id"], "siren": r["source_entity_id"][3:],
                                                 "decouverte_via": row["entity_id"], "statut": "a_traiter",
                                                 "date": date.today().isoformat()})
    return {"status": status, "changes": len(changes), "signals": signals, "row": row}


# ------------------------------------------------------------------ affichage
def fmt_eur(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(x) >= 1e9:
        return f"{x / 1e9:,.1f} Md€".replace(",", " ").replace(".", ",")
    if abs(x) >= 1e6:
        return f"{x / 1e6:,.1f} M€".replace(",", " ").replace(".", ",")
    return f"{x:,.0f} €".replace(",", " ")


def _identity_card(row: dict, raw: dict, data: dict) -> None:
    """Fiche d'identité lisible (remplace l'affichage JSON)."""
    from services.groupe import CATEGORIES, LABELS
    siege = raw.get("siege") or {}
    tva = raw.get("tva")
    if isinstance(tva, dict):
        tva = tva.get("tva_intra") or tva.get("numero") or next((v for v in tva.values() if isinstance(v, str)), "")
    status, detail, src = data["listing"]
    fields = [
        ("Dénomination", row["denomination"]), ("Sigle", row.get("sigle")), ("Type d'entité", row["type_entite"]),
        ("SIREN", row["siren"]), ("SIRET du siège", row["siret_siege"]), ("N° TVA intracommunautaire", tva or ""),
        ("LEI", data["gleif"]["lei"]), ("N° RNA (association)", row.get("rna")),
        ("Forme juridique", row["forme_juridique"]), ("Date de création", row["date_creation"]),
        ("État", row["statut"]), ("Catégorie", CATEGORIES.get(row.get("categorie", ""), row.get("categorie", ""))),
        ("Activité principale (NAF)", row["naf_code"]), ("Effectif salarié", row["tranche_effectif"]),
        ("Adresse du siège", row["adresse_siege"]), ("Enseignes", ", ".join(siege.get("liste_enseignes") or [])),
        ("Établissements", f"{data['etab_total']} au total, {row.get('nb_etablissements') or '?'} ouverts"),
        ("Cotation", f"{status} · {detail}"),
    ]
    cells = "".join(
        f"<div style='padding:10px 12px;border-bottom:1px solid #EEF0F3'><div style='color:#6B7480;font-size:11.5px;"
        f"text-transform:uppercase;letter-spacing:.05em'>{ui.esc_html(k)}</div><div style='color:#1B2733;font-size:14.5px;"
        f"font-weight:600;margin-top:2px'>{ui.esc_html(v)}</div></div>" for k, v in fields if v)
    labels = [LABELS.get(x, x) for x in (row.get("labels") or "").split(";") if x]
    chips = "".join(f"<span style='display:inline-block;margin:3px 6px 3px 0;padding:3px 10px;border-radius:999px;"
                    f"background:#E6F4F5;color:#0B5D64;font-size:12.5px;font-weight:600'>{ui.esc_html(l)}</span>" for l in labels)
    st.html(f"<div style='background:#fff;border:1px solid #E3E7EC;border-radius:12px;overflow:hidden'>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))'>{cells}</div>"
            + (f"<div style='padding:10px 12px'><div style='color:#6B7480;font-size:11.5px;text-transform:uppercase;"
               f"letter-spacing:.05em;margin-bottom:4px'>Labels et qualités</div>{chips}</div>" if chips else "") + "</div>")


def _finances(fins: list[dict]) -> None:
    import altair as alt
    if not fins:
        st.info("Comptes non publiés ou déclarés confidentiels.")
        return
    f = pd.DataFrame(fins)
    f["ca"] = pd.to_numeric(f["chiffre_affaires_eur"], errors="coerce")
    f["rn"] = pd.to_numeric(f["resultat_net_eur"], errors="coerce")
    big = f["ca"].abs().max() >= 1e9
    div, unit = (1e9, "Md€") if big else (1e6, "M€")
    long = pd.concat([pd.DataFrame({"Exercice": f["exercice"], "Indicateur": "Chiffre d'affaires", "Valeur": f["ca"] / div}),
                      pd.DataFrame({"Exercice": f["exercice"], "Indicateur": "Résultat net", "Valeur": f["rn"] / div})])
    chart = (alt.Chart(long).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
             .encode(x=alt.X("Exercice:N", title=None, axis=alt.Axis(labelAngle=0), scale=alt.Scale(paddingInner=0.35)),
                     xOffset=alt.XOffset("Indicateur:N", scale=alt.Scale(paddingInner=0.08)),
                     y=alt.Y("Valeur:Q", title=unit),
                     color=alt.Color("Indicateur:N", scale=alt.Scale(range=["#0E7C86", "#E0A100"]), legend=alt.Legend(orient="top", title=None)),
                     tooltip=["Exercice", "Indicateur", alt.Tooltip("Valeur:Q", format=",.2f", title=unit)])
             .properties(height=280))
    c1, c2 = st.columns([1.3, 1], gap="large")
    c1.altair_chart(chart, width="stretch")
    t = pd.DataFrame({"Exercice": f["exercice"], "Chiffre d'affaires": f["ca"].map(fmt_eur), "Résultat net": f["rn"].map(fmt_eur),
                      "Marge nette": (100 * f["rn"] / f["ca"]).map(lambda x: f"{x:.1f} %" if pd.notna(x) else "-")})
    if len(f) > 1:
        t["Évolution du CA"] = (100 * f["ca"].pct_change()).map(lambda x: f"{x:+.1f} %" if pd.notna(x) else "-")
    c2.markdown("**Comptes publiés**")
    c2.dataframe(t, hide_index=True, width="stretch")
    st.caption("Source : comptes publiés (INPI, DGFiP) via l'API Recherche d'entreprises. Les comptes consolidés d'un groupe "
               "peuvent différer des comptes sociaux affichés ici.")


def fiche(user, sid, r: dict) -> None:
    from services import groupe as G
    row, fins, rels, dirigeants = normalize(r)
    st.session_state.ent_current = (row, fins, rels, dirigeants)
    st.session_state.ent_raw = r
    if st.session_state.get("ent_enriched") != row["siren"]:
        res = enrich(row, fins, rels, user["email"])
        st.session_state.ent_enriched = row["siren"]
        st.session_state.ent_res = res
        db.audit(user["email"], "fiche_entite_consultee", {"siren": row["siren"], "maj": res["status"]})
    res = st.session_state.ent_res
    row = res["row"]
    data = G.collect(row["siren"], row["denomination"])
    st.session_state.ent_data = data
    if st.session_state.get("ent_persisted") != row["siren"]:
        G.persist(row["siren"], row["denomination"], data, user["email"])
        st.session_state.ent_persisted = row["siren"]
    status, detail, src = data["listing"]
    subs = G.subsidiaries(data)
    biz = G.business_relations(row["siren"], user)

    st.markdown(f"### {row['denomination']}")
    chips = [row["forme_juridique"], f"SIREN {row['siren']}", f"NAF {row['naf_code']}", f"créée le {row['date_creation']}",
             row["statut"], row["commune"], f"{status}" + (f" · {detail}" if status != "Non cotée selon les sources consultées" else "")]
    st.caption(" · ".join(c for c in chips if c))
    msg = {"ajout": "Nouvelle entité ajoutée à la base.", "maj": f"Fiche mise à jour ({res['changes']} champ(s) modifié(s)).",
           "inchange": "Aucun changement depuis la dernière mise à jour."}[res["status"] if res["changes"] or res["status"] == "ajout" else "inchange"]
    st.caption(f"🔄 {msg} Complétude {int(float(row['score_completude']) * 100)} % · risque indicatif {row['score_risque_indicatif']}/100"
               + (f" · ⚠️ {' ; '.join(data['errors'])}" if data["errors"] else ""))
    ui.kpis([(fmt_eur(row["ca_dernier_eur"]), f"Chiffre d'affaires {row['exercice_dernier']}"),
             (fmt_eur(row["resultat_dernier_eur"]), "Résultat net"), (row["tranche_effectif"] or "-", "Effectif salarié"),
             (str(data["etab_total"] or row["nb_etablissements"] or "-"), "Établissements"),
             (str(len(subs)), "Filiales identifiées"), ("Oui" if status == "Cotée" else "Non" if status.startswith("Non") else "Ex-cotée", "Cotée en bourse")])
    st.write("")
    tabs = st.tabs(["Synthèse", "Cartographie des relations", "Identité", "Finances", "Gouvernance", "Groupe et filiales",
                    "Établissements", "Relations d'affaires", "Rapport"])
    with tabs[0]:
        c1, c2 = st.columns([3, 2], gap="large")
        with c1:
            st.markdown("**En bref**")
            st.markdown("\n".join([
                f"- **Activité** : NAF {row['naf_code']} · {row['tranche_effectif'] or 'effectif non renseigné'} salariés",
                f"- **Taille** : {G.CATEGORIES.get(row.get('categorie', ''), row.get('categorie') or 'non renseignée')} · "
                f"CA {fmt_eur(row['ca_dernier_eur'])} ({row['exercice_dernier'] or 'n.c.'})",
                f"- **Cotation** : {status} · {detail} (source : {src})",
                f"- **Groupe** : {len(G.parents(data, dirigeants))} société(s) mère(s) · {len(subs)} filiale(s) identifiée(s)"
                + (f" · LEI {data['gleif']['lei']}" if data["gleif"]["lei"] else " · pas de LEI trouvé"),
                f"- **Implantation** : {data['etab_total']} établissement(s), principalement "
                + (", ".join(f"{r} ({n})" for r, n in G.etab_by_region(data['etabs'])[:3]) or "non renseigné"),
                f"- **Gouvernance** : {sum(d['type'] == 'personne physique' for d in dirigeants)} dirigeant(s) personne(s) physique(s), "
                f"{sum(d['type'] == 'personne morale' for d in dirigeants)} personne(s) morale(s)",
                f"- **Relations d'affaires connues** : {len(biz)} (clients, fournisseurs, distributeurs...)",
            ]))
        with c2:
            st.markdown("**Points d'attention**")
            if not res["signals"]:
                st.success("Aucun signal automatique. L'absence de signal ne prouve pas l'absence de risque.")
            for g, t in res["signals"]:
                (st.error if g == "élevé" else st.warning if g == "moyen" else st.info)(t)
            if status == "Anciennement cotée":
                st.info(f"Anciennement cotée : {detail}. Vérifier l'actionnariat actuel.")
    with tabs[1]:
        st.markdown(G.LEGEND)
        st.graphviz_chart(G.dot(row, dirigeants, data, biz), width="stretch")
        st.caption("Ajoutez clients, fournisseurs, distributeurs, grossistes ou détaillants dans l'onglet Relations d'affaires : "
                   "ils apparaîtront dans ce schéma.")
    with tabs[2]:
        _identity_card(row, r, data)
    with tabs[3]:
        _finances(fins)
    with tabs[4]:
        pp = [d for d in dirigeants if d["type"] == "personne physique"]
        pm = [d for d in dirigeants if d["type"] == "personne morale"]
        c1, c2 = st.columns(2)
        c1.markdown(f"**Personnes physiques ({len(pp)})**")
        c1.dataframe(pd.DataFrame(pp)[["nom", "qualite", "annee_naissance"]].rename(columns={
            "nom": "Nom", "qualite": "Fonction", "annee_naissance": "Année de naissance"}) if pp else pd.DataFrame(),
            hide_index=True, width="stretch")
        c2.markdown(f"**Personnes morales ({len(pm)})**")
        c2.dataframe(pd.DataFrame(pm)[["nom", "qualite", "siren"]].rename(columns={
            "nom": "Dénomination", "qualite": "Fonction", "siren": "SIREN"}) if pm else pd.DataFrame(),
            hide_index=True, width="stretch")
        st.caption("Les commissaires aux comptes figurent parmi les personnes morales. Bénéficiaires effectifs : accès restreint "
                   "au RBE (intérêt légitime), non collectés automatiquement.")
    with tabs[5]:
        par = G.parents(data, dirigeants)
        st.markdown(f"**Sociétés mères ({len(par)})**")
        st.dataframe(pd.DataFrame(par), hide_index=True, width="stretch") if par else st.caption(
            "Aucune société mère publiée (GLEIF, Wikidata). L'entité peut être tête de groupe ou non déclarée.")
        st.markdown(f"**Filiales et participations ({len(subs)})**")
        if subs:
            st.dataframe(pd.DataFrame(subs).rename(columns={"nom": "Société", "pays": "Pays", "source": "Source",
                                                             "id": "SIREN / LEI", "fiabilite": "Fiabilité"}),
                         hide_index=True, width="stretch", height=min(420, 40 + 35 * len(subs)))
            if data["gleif"]["children_total"] > len(data["gleif"]["children"]):
                st.caption(f"GLEIF déclare {data['gleif']['children_total']} filiales directes ; les 100 premières sont affichées.")
        else:
            st.caption("Aucune filiale trouvée dans les sources publiques consultées.")
        st.markdown("**Cotation en bourse**")
        (st.success if status == "Cotée" else st.info)(f"{status} · {detail} · source : {src}")
    with tabs[6]:
        etabs = data["etabs"]
        if not etabs:
            st.caption("Établissements indisponibles.")
        else:
            reg = pd.DataFrame(G.etab_by_region(etabs), columns=["Région", "Établissements ouverts"]).set_index("Région")
            c1, c2 = st.columns([1, 1.3])
            c1.bar_chart(reg, horizontal=True, color="#0E7C86")
            pts = pd.DataFrame([{"lat": pd.to_numeric(e.get("latitude"), errors="coerce"),
                                 "lon": pd.to_numeric(e.get("longitude"), errors="coerce")} for e in etabs]).dropna()
            if not pts.empty:
                c2.map(pts, size=40, color="#0E7C86")
            t = pd.DataFrame([{"SIRET": e.get("siret"), "Siège": "oui" if e.get("est_siege") else "",
                               "Nom / enseigne": e.get("nom_commercial") or ", ".join(e.get("liste_enseignes") or []),
                               "Adresse": e.get("adresse"), "Activité": e.get("activite_principale"),
                               "État": "ouvert" if e.get("etat_administratif") == "A" else "fermé",
                               "Créé le": e.get("date_creation")} for e in etabs])
            st.dataframe(t, hide_index=True, width="stretch", height=360)
            st.caption(f"{len(etabs)} établissement(s) affiché(s) sur {data['etab_total']}. Les succursales à l'étranger "
                       "n'apparaissent pas dans Sirene : voir les filiales GLEIF.")
    with tabs[7]:
        if biz:
            st.dataframe(pd.DataFrame(biz).rename(columns={"type": "Relation", "nom": "Contrepartie", "pays": "Pays",
                                                            "part": "Part %", "source": "Source", "portee": "Visibilité",
                                                            "statut": "Statut"}), hide_index=True, width="stretch")
        else:
            st.caption("Aucune relation d'affaires enregistrée. Les clients, fournisseurs, distributeurs, grossistes et détaillants "
                       "ne sont pas publics : ajoutez-les ci-dessous ou déduisez-les des flux dans l'onglet Examen renforcé.")
        G.relation_form(row["siren"], row["denomination"], user)
    with tabs[8]:
        ui.export_panel(user, sid, report(row, fins, dirigeants, res["signals"], data, biz), key=f"ent_{row['siren']}")


def report(row, fins, dirigeants, signals, data=None, biz=None) -> dict:
    from services import groupe as G
    extra = []
    if data:
        status, detail, src = data["listing"]
        subs = G.subsidiaries(data)
        extra = [
            {"heading": "Cotation et groupe", "bullets": [f"Cotation : {status} · {detail} (source : {src})",
                                                         f"LEI : {data['gleif']['lei'] or 'non trouvé'}"]},
            {"heading": "Sociétés mères", "table": {"columns": ["Société", "Pays", "Lien", "Source"],
                                                     "rows": [[p["nom"], p["pays"], p["lien"], p["source"]] for p in G.parents(data, dirigeants)]}},
            {"heading": f"Filiales et participations ({len(subs)})",
             "table": {"columns": ["Société", "Pays", "Source", "Fiabilité"],
                       "rows": [[x["nom"], x["pays"], x["source"], x["fiabilite"]] for x in subs[:60]]}},
            {"heading": f"Établissements ({data['etab_total']})",
             "table": {"columns": ["Région", "Établissements ouverts"], "rows": [[r, n] for r, n in G.etab_by_region(data["etabs"])]}},
        ]
    if biz:
        extra.append({"heading": "Relations d'affaires", "table": {"columns": ["Relation", "Contrepartie", "Pays", "Part %", "Source"],
                      "rows": [[b["type"], b["nom"], b.get("pays", ""), b.get("part", ""), b.get("source", "")] for b in biz]}})
    return {
        "title": f"Fiche entité : {row['denomination']}",
        "subtitle": f"SIREN {row['siren']} · {row['forme_juridique']} · NAF {row['naf_code']} · {row['statut']}",
        "kpis": [(fmt_eur(row["ca_dernier_eur"]), f"CA {row['exercice_dernier']}"), (fmt_eur(row["resultat_dernier_eur"]), "résultat net"),
                 (row["tranche_effectif"] or "-", "effectif"), (f"{row['score_risque_indicatif']}/100", "risque indicatif")],
        "sections": [
            {"heading": "Identité", "table": {"columns": ["Champ", "Valeur"], "rows": [[k, row.get(k, "")] for k in
                ["denomination", "type_entite", "siren", "siret_siege", "rna", "forme_juridique", "date_creation", "statut",
                 "naf_code", "adresse_siege", "code_postal", "commune", "categorie", "labels"]]}},
            {"heading": "Finances publiées", "table": {"columns": ["Exercice", "CA (€)", "Résultat net (€)"],
                                                        "rows": [[f["exercice"], f["chiffre_affaires_eur"], f["resultat_net_eur"]] for f in fins]}},
            {"heading": "Dirigeants", "table": {"columns": ["Type", "Nom", "Qualité"],
                                                "rows": [[d["type"], d["nom"], d["qualite"]] for d in dirigeants]}},
            {"heading": "Points d'attention", "bullets": [f"[{g}] {t}" for g, t in signals] or ["Aucun signal automatique."]},
        ] + extra,
        "sources": ["API Recherche d'entreprises (DINUM, annuaire-entreprises.data.gouv.fr), Licence Ouverte 2.0 : "
                    "données INSEE Sirene, INPI RNE et autres registres publics.",
                    "GLEIF (LEI, relations de consolidation), Wikidata (CC0) pour la cotation et les filiales déclarées."],
    }


def esc(s) -> str:
    return str(s or "").replace('"', "'")


# ------------------------------------------------------------------ examen renforcé
def examen(user, sid) -> None:
    st.write("Déposez des relevés, un grand livre ou un FEC (CSV ou Excel). Les données restent dans votre session "
             "et ne sont jamais ajoutées aux référentiels partagés.")
    up = st.file_uploader("Fichier de transactions", type=["csv", "xlsx", "xls", "txt"])
    if not up:
        return
    if up.name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(up)
    else:
        raw = up.getvalue()
        df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding="utf-8-sig", dtype=str)
    st.caption(f"{len(df)} lignes, {len(df.columns)} colonnes lues.")
    cols = ["(aucune)"] + list(df.columns)

    def guess(*words):
        for i, c in enumerate(df.columns):
            if any(w in c.lower() for w in words):
                return i + 1
        return 0
    c = st.columns(5)
    m_date = c[0].selectbox("Date", cols, index=guess("date"))
    m_lib = c[1].selectbox("Libellé", cols, index=guess("libell", "label", "désign", "design"))
    m_amt = c[2].selectbox("Montant", cols, index=guess("montant", "amount", "debit", "crédit", "credit"))
    m_cp = c[3].selectbox("Contrepartie", cols, index=guess("contrepartie", "tiers", "beneficiaire", "bénéficiaire", "compauxlib"))
    m_iban = c[4].selectbox("IBAN contrepartie", cols, index=guess("iban"))
    if m_amt == "(aucune)" or m_lib == "(aucune)":
        st.info("Indiquez au moins la colonne du libellé et celle du montant.")
        return
    t = pd.DataFrame({
        "date": pd.to_datetime(df[m_date], errors="coerce", dayfirst=True) if m_date != "(aucune)" else pd.NaT,
        "libelle": df[m_lib].astype(str),
        "montant": pd.to_numeric(df[m_amt].astype(str).str.replace(" ", "").str.replace(",", "."), errors="coerce"),
        "contrepartie": df[m_cp].astype(str) if m_cp != "(aucune)" else df[m_lib].astype(str).str[:30],
        "iban": df[m_iban].astype(str) if m_iban != "(aucune)" else "",
    }).dropna(subset=["montant"])
    if t.empty:
        st.error("Aucun montant lisible dans la colonne choisie.")
        return
    t["pays_iban"] = t["iban"].str.replace(" ", "").str[:2].str.upper().where(t["iban"].str.len() > 10, "")
    credits, debits = t[t["montant"] > 0]["montant"].sum(), -t[t["montant"] < 0]["montant"].sum()
    by_cp = t.groupby("contrepartie")["montant"].agg(total=lambda s: s.abs().sum(), operations="count").sort_values("total", ascending=False)
    by_cp["part_%"] = (100 * by_cp["total"] / by_cp["total"].sum()).round(1)
    # rapprochement des contreparties avec la base des entités (similarité de noms)
    base = csvstore.read(ENT)
    if not base.empty:
        names = {norm(n): (n, s) for n, s in zip(base["denomination"], base["siren"])}

        def match(cp):
            best = difflib.get_close_matches(norm(cp), list(names), n=1, cutoff=0.82)
            return f"{names[best[0]][0]} ({names[best[0]][1]})" if best else ""
        by_cp["entite_rapprochee"] = [match(x) for x in by_cp.index]
    signals = []
    top = by_cp.iloc[0]
    if top["part_%"] >= 30:
        signals.append(("moyen", f"Concentration : {top.name} représente {top['part_%']} % des flux"))
    rounds = t[(t["montant"].abs() >= 1000) & (t["montant"].abs() % 1000 == 0)]
    if len(rounds) >= 3:
        signals.append(("moyen", f"{len(rounds)} opérations à montant rond (multiples de 1 000 €)"))
    near = t[(t["montant"].abs() >= 9000) & (t["montant"].abs() < 10000)]
    if len(near) >= 2:
        signals.append(("élevé", f"{len(near)} opérations entre 9 000 et 10 000 € : fractionnement possible"))
    cash = t[t["libelle"].str.upper().str.contains("ESPECE|ESPÈCE|DAB|RETRAIT GAB|VERSEMENT ESP", regex=True)]
    if len(cash):
        signals.append(("moyen", f"{len(cash)} opérations en espèces pour {cash['montant'].abs().sum():,.0f} €".replace(",", " ")))
    foreign = t[(t["pays_iban"] != "") & (t["pays_iban"] != "FR")]
    if len(foreign):
        signals.append(("info", f"Flux avec {foreign['pays_iban'].nunique()} pays étrangers : {', '.join(sorted(foreign['pays_iban'].unique()))}"))
    black = t[t["pays_iban"].isin(PAYS_LISTE_NOIRE)]
    if len(black):
        signals.append(("élevé", f"{len(black)} opérations avec un pays sur liste noire du GAFI"))
    cur = st.session_state.get("ent_current")
    if cur and cur[0].get("ca_dernier_eur"):
        ca = float(cur[0]["ca_dernier_eur"])
        if ca > 0 and credits > 1.3 * ca:
            signals.append(("élevé", f"Encaissements ({credits:,.0f} €) supérieurs de plus de 30 % au CA publié de "
                                     f"{cur[0]['denomination']}".replace(",", " ")))
    ui.kpis([(f"{credits:,.0f} €".replace(",", " "), "encaissements"), (f"{debits:,.0f} €".replace(",", " "), "décaissements"),
             (str(len(by_cp)), "contreparties"), (str(len(signals)), "signaux")])
    for g, s in signals:
        (st.error if g == "élevé" else st.warning if g == "moyen" else st.info)(s)
    st.markdown("**Contreparties principales**")
    st.dataframe(by_cp.head(25), width="stretch")
    cur_e = st.session_state.get("ent_current")
    if cur_e and st.button(f"Ajouter ces contreparties au schéma de {cur_e[0]['denomination']} (session uniquement)"):
        found = []
        for name, r in by_cp.head(20).iterrows():
            net = t[t["contrepartie"] == name]["montant"].sum()
            found.append({"type": "client" if net > 0 else "fournisseur", "nom": str(name)[:40],
                          "pays": ", ".join(sorted(set(t[t["contrepartie"] == name]["pays_iban"]) - {""})),
                          "part": r["part_%"], "source": f"flux {up.name}"})
        st.session_state.setdefault("exam_counterparties", {})[cur_e[0]["siren"]] = found
        st.success("Contreparties ajoutées au schéma (onglet Fiche entité > Cartographie), sans enregistrement serveur.")
    st.markdown("**Graphe des flux (10 premières contreparties)**")
    dot = ['digraph F { rankdir=LR; node [fontname="Helvetica", fontsize=9, shape=box, style=rounded]; "E" [label="Entité examinée", style="rounded,filled", fillcolor="#FFF6E0"];']
    for i, (name, r) in enumerate(by_cp.head(10).iterrows()):
        net = t[t["contrepartie"] == name]["montant"].sum()
        a, b = (f"N{i}", "E") if net > 0 else ("E", f"N{i}")
        dot.append(f'"N{i}" [label="{esc(name)[:28]}"]; "{a}" -> "{b}" [label="{abs(net):,.0f} €", penwidth={1 + 4 * r["part_%"] / 100:.1f}];'.replace(",", " "))
    st.graphviz_chart("\n".join(dot) + "}")
    ui.export_panel(user, sid, {
        "title": "Note d'examen renforcé des transactions",
        "subtitle": f"Fichier {up.name} · {len(t)} opérations" + (f" · entité {cur[0]['denomination']}" if cur else ""),
        "kpis": [(f"{credits:,.0f} €".replace(",", " "), "encaissements"), (f"{debits:,.0f} €".replace(",", " "), "décaissements"),
                 (str(len(by_cp)), "contreparties"), (str(len(signals)), "signaux")],
        "sections": [{"heading": "Signaux", "bullets": [f"[{g}] {s}" for g, s in signals] or ["Aucun signal automatique."]},
                     {"heading": "Contreparties principales",
                      "table": {"columns": ["Contrepartie", "Total (€)", "Opérations", "Part %"] + (["Entité rapprochée"] if "entite_rapprochee" in by_cp else []),
                                "rows": [[i, f"{r['total']:,.0f}".replace(",", " "), int(r["operations"]), r["part_%"]] +
                                         ([r["entite_rapprochee"]] if "entite_rapprochee" in by_cp else []) for i, r in by_cp.head(25).iterrows()]}},
                     {"heading": "Conclusion de l'analyste", "paragraphs": ["À compléter par l'analyste avant transmission."]}],
    }, key="ent_examen")


# ------------------------------------------------------------------ onglets
def render(tab, user, sid):
    if tab == "Accueil":
        base = csvstore.read(ENT)
        ui.kpis([(str(len(base)), "entités dans la base"), (str(len(csvstore.read(REL))), "relations connues"),
                 (str(len(csvstore.read(LOG))), "changements journalisés"), (str(len(csvstore.read(QUEUE))), "entités découvertes en attente")])
        st.markdown("Recherchez une société, une association ou un organisme par **nom, SIREN ou SIRET** dans l'onglet *Fiche entité*. "
                    "Chaque recherche met à jour la base : nouvelle entité ajoutée, champs modifiés journalisés.")
        if not base.empty:
            st.markdown("**Dernières fiches mises à jour**")
            st.dataframe(base.sort_values("derniere_maj", ascending=False).head(8)[
                ["denomination", "siren", "type_entite", "naf_code", "statut", "score_risque_indicatif", "derniere_maj"]],
                hide_index=True, width="stretch")

    elif tab == "Fiche entité":
        with st.form("ent_search"):
            q = st.text_input("Nom, SIREN ou SIRET", placeholder="ex. 552 100 554 ou nom de l'association")
            go = st.form_submit_button("Rechercher", type="primary")
        ui.quota_line(user, sid, "recherche")
        if go and q.strip():
            if not ent.consume(user, sid, "recherche"):
                st.error("Quota de recherches atteint pour ce mois.")
            else:
                try:
                    st.session_state.ent_results = search_api(q.strip())
                    st.session_state.ent_source = "api"
                except requests.RequestException as e:
                    st.warning(f"API publique injoignable ({e.__class__.__name__}) : recherche dans la base locale.")
                    st.session_state.ent_results = search_local(q.strip())
                    st.session_state.ent_source = "local"
                st.session_state.pop("ent_enriched", None)
        results = st.session_state.get("ent_results", [])
        if results:
            if st.session_state.get("ent_source") == "local":
                st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
                return
            labels = [f"{r.get('nom_complet', '')} · {r.get('siren', '')} · {(r.get('siege') or {}).get('libelle_commune', '')}" for r in results]
            idx = st.radio("Résultats", range(len(results)), format_func=lambda i: labels[i], key="ent_pick")
            if st.session_state.get("ent_pick_prev") != idx:
                st.session_state.ent_pick_prev = idx
                st.session_state.pop("ent_enriched", None)
            c1, c2 = st.columns([1, 4])
            if c1.button("🔄 Mettre à jour la fiche"):
                st.session_state.pop("ent_enriched", None)
            st.divider()
            fiche(user, sid, results[idx])

    elif tab == "Cartographie":
        cur = st.session_state.get("ent_current")
        if not cur or "ent_data" not in st.session_state:
            st.info("Ouvrez d'abord une fiche dans l'onglet Fiche entité.")
            return
        from services import groupe as G
        row, fins, rels, dirigeants = cur
        row = st.session_state.ent_res["row"]
        st.markdown(G.LEGEND)
        n = st.slider("Nombre maximal d'éléments par groupe", 5, 40, 14)
        d = G.dot(row, dirigeants, st.session_state.ent_data, G.business_relations(row["siren"], user), max_items=n)
        st.graphviz_chart(d, width="stretch")
        st.download_button("Télécharger le schéma (format DOT, ouvrable dans Graphviz)", d, file_name=f"cartographie_{row['siren']}.dot")

    elif tab == "Examen renforcé":
        examen(user, sid)

    elif tab == "Base des entités":
        t1, t2, t3, t4 = st.tabs(["Entités", "Relations", "Journal d'enrichissement", "File des entités découvertes"])
        t1.dataframe(csvstore.read(ENT), hide_index=True, width="stretch")
        t2.dataframe(csvstore.read(REL), hide_index=True, width="stretch")
        t3.dataframe(csvstore.read(LOG), hide_index=True, width="stretch")
        q = csvstore.read(QUEUE)
        t4.dataframe(q, hide_index=True, width="stretch")
        if user["role"] == "admin" and not q.empty and t4.button("Traiter 10 entités de la file (niveau 1)"):
            done = 0
            for rec in q[q["statut"] == "a_traiter"].head(10).to_dict("records"):
                try:
                    res = search_api(rec["siren"])
                    if res:
                        r, f, rl, _ = normalize(res[0])
                        enrich(r, f, [], user["email"])     # niveau 1 : pas de nouvelles découvertes en cascade
                    csvstore.update_where(QUEUE, "entity_id", rec["entity_id"], {"statut": "traite"})
                    done += 1
                except requests.RequestException:
                    break
            t4.success(f"{done} entité(s) enrichie(s).")
        for name in (ENT, REL, LOG):
            st.caption(f"{name} : intégrité {'✅ vérifiée' if csvstore.verify(name) else '⚠️ modifié hors procédure ou absent du manifeste'}")
