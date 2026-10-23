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
def fiche(user, sid, r: dict) -> None:
    row, fins, rels, dirigeants = normalize(r)
    st.session_state.ent_current = (row, fins, rels, dirigeants)
    if st.session_state.get("ent_enriched") != row["siren"]:
        res = enrich(row, fins, rels, user["email"])
        st.session_state.ent_enriched = row["siren"]
        st.session_state.ent_res = res
        db.audit(user["email"], "fiche_entite_consultee", {"siren": row["siren"], "maj": res["status"]})
    res = st.session_state.ent_res
    row = res["row"]
    st.markdown(f"### {row['denomination']}")
    st.caption(f"SIREN {row['siren']} · {row['forme_juridique']} · NAF {row['naf_code']} · créée le {row['date_creation']} · "
               f"{row['statut']} · {row['commune']}")
    msg = {"ajout": "Nouvelle entité ajoutée à la base.", "maj": f"Fiche mise à jour ({res['changes']} champ(s) modifié(s)).",
           "inchange": "Aucun changement depuis la dernière mise à jour."}[res["status"]]
    st.caption(f"🔄 {msg} Complétude {int(float(row['score_completude']) * 100)} % · risque indicatif {row['score_risque_indicatif']}/100")
    ui.kpis([(fmt_eur(row["ca_dernier_eur"]), f"Chiffre d'affaires {row['exercice_dernier']}"),
             (fmt_eur(row["resultat_dernier_eur"]), "Résultat net"), (row["tranche_effectif"] or "-", "Effectif salarié"),
             (row["nb_etablissements"] or "-", "Établissements ouverts")])
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Finances publiées**")
        if fins:
            f = pd.DataFrame(fins).set_index("exercice")[["chiffre_affaires_eur", "resultat_net_eur"]].apply(pd.to_numeric, errors="coerce")
            st.bar_chart(f / 1e6, y_label="M€")
        else:
            st.caption("Comptes non publiés ou confidentiels.")
        st.markdown("**Dirigeants (registre public)**")
        st.dataframe(pd.DataFrame(dirigeants), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Points d'attention**")
        if not res["signals"]:
            st.success("Aucun signal automatique. L'absence de signal ne prouve pas l'absence de risque.")
        for g, t in res["signals"]:
            (st.error if g == "élevé" else st.warning if g == "moyen" else st.info)(t)
        st.markdown("**Identité**")
        st.write({k: row[k] for k in ["type_entite", "rna", "siret_siege", "adresse_siege", "categorie", "labels"] if row.get(k)})
    st.markdown("**Rapport de la fiche**")
    ui.export_panel(user, sid, report(row, fins, dirigeants, res["signals"]), key=f"ent_{row['siren']}")


def fmt_eur(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{x / 1e6:,.1f} M€".replace(",", " ").replace(".", ",") if abs(x) >= 1e5 else f"{x:,.0f} €".replace(",", " ")


def report(row, fins, dirigeants, signals) -> dict:
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
        ],
        "sources": ["API Recherche d'entreprises (DINUM, annuaire-entreprises.data.gouv.fr), Licence Ouverte 2.0 : "
                    "données INSEE Sirene, INPI RNE et autres registres publics."],
    }


def graph_dot(row, rels, dirigeants) -> str:
    risk = int(row.get("score_risque_indicatif") or 0)
    color = "#2E8B57" if risk < 35 else "#E0A100" if risk < 60 else "#C0392B"
    lines = ['digraph G { rankdir=TB; bgcolor="transparent"; node [fontname="Helvetica", fontsize=10]; edge [fontname="Helvetica", fontsize=8, color="#8A96A3"];',
             f'"C" [label="{esc(row["denomination"])}\\nSIREN {row["siren"]} · {row["naf_code"]}", shape=box, style="rounded,filled,bold", fillcolor="#FFF6E0", color="{color}", penwidth=2];']
    for i, d in enumerate(dirigeants[:12]):
        shape = "box" if d["type"] == "personne morale" else "ellipse"
        lines.append(f'"D{i}" [label="{esc(d["nom"])}\\n{esc(d["qualite"])}", shape={shape}, style="rounded", color="#0B2545"];')
        lines.append(f'"D{i}" -> "C" [label="{esc(d["qualite"] or "dirige")}", color="#0E7C86"];')
    allrels = csvstore.read(REL)
    if not allrels.empty:
        mine = allrels[(allrels["cible_entity_id"] == row["entity_id"]) | (allrels["source_entity_id"] == row["entity_id"])]
        for j, r in enumerate(mine.to_dict("records")):
            if r["type_relation"] == "dirige":
                continue          # déjà dessiné avec les dirigeants
            other = r["source_nom"] if r["cible_entity_id"] == row["entity_id"] else r["cible_nom"]
            style = "dashed" if r.get("statut") in ("propose", "proposé") else "solid"
            node = f"R{j}"
            lines.append(f'"{node}" [label="{esc(other)}", shape=box, style="rounded"];')
            a, b = (node, "C") if r["cible_entity_id"] == row["entity_id"] else ("C", node)
            lines.append(f'"{a}" -> "{b}" [label="{esc(r["type_relation"])} {esc(r.get("part_pct", ""))}", style={style}];')
    if row.get("nb_etablissements"):
        lines.append(f'"E" [label="{row["nb_etablissements"]} établissement(s)\\n{esc(row["commune"])}", shape=folder, color="#8A96A3"];')
        lines.append('"C" -> "E" [label="exploite"];')
    return "\n".join(lines) + "}"


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
        if not cur:
            st.info("Ouvrez d'abord une fiche dans l'onglet Fiche entité.")
            return
        row, fins, rels, dirigeants = cur
        st.caption("Flèches pleines : registre officiel. Pointillés : lien proposé, à valider. Couleur du cadre : risque indicatif.")
        dot = graph_dot(st.session_state.ent_res["row"], rels, dirigeants)
        st.graphviz_chart(dot, width="stretch")
        st.download_button("Télécharger le schéma (DOT, ouvrable dans Graphviz)", dot, file_name=f"cartographie_{row['siren']}.dot")

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
