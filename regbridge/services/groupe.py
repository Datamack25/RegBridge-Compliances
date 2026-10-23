"""Groupe, établissements, cotation et relations d'une entité, à partir de sources publiques.

Sources (toutes gratuites, appelées à l'ouverture d'une fiche et mises en cache 24 h) :
- API Recherche d'entreprises : établissements (succursales en France) et sociétés dont l'entité est dirigeante ;
- GLEIF (LEI) : sociétés mères directe et ultime, filiales consolidées, nombre de titres (ISIN) ;
- Wikidata (CC0) : cotation en bourse (place, code, date de radiation éventuelle), filiales, maisons mères.
Les relations d'affaires (clients, fournisseurs, distributeurs, grossistes, détaillants...) ne sont pas publiques :
elles viennent de l'analyste (formulaire) ou des fichiers déposés dans l'examen renforcé.
"""
import unicodedata
from collections import Counter
from datetime import date

import pandas as pd
import requests
import streamlit as st

from core import csvstore, db

API = "https://recherche-entreprises.api.gouv.fr/search"
GLEIF = "https://api.gleif.org/api/v1"
WIKIDATA = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "RegBridge/0.2 (plateforme de conformite; contact via site)"}

REGIONS = {"11": "Île-de-France", "24": "Centre-Val de Loire", "27": "Bourgogne-Franche-Comté", "28": "Normandie",
           "32": "Hauts-de-France", "44": "Grand Est", "52": "Pays de la Loire", "53": "Bretagne",
           "75": "Nouvelle-Aquitaine", "76": "Occitanie", "84": "Auvergne-Rhône-Alpes", "93": "Provence-Alpes-Côte d'Azur",
           "94": "Corse", "01": "Guadeloupe", "02": "Martinique", "03": "Guyane", "04": "La Réunion", "06": "Mayotte"}
CATEGORIES = {"PME": "PME", "ETI": "Entreprise de taille intermédiaire", "GE": "Grande entreprise"}
LABELS = {"achats_responsables": "Achats responsables", "alim_confiance": "Alim'confiance", "finess": "Établissement sanitaire (FINESS)",
          "organisme_formation": "Organisme de formation", "qualiopi": "Qualiopi", "rge": "RGE", "ess": "ESS",
          "societe_mission": "Société à mission", "bio": "Bio", "siae": "Insertion (SIAE)", "patrimoine_vivant": "Patrimoine vivant",
          "uai": "Établissement d'enseignement", "association": "Association", "administration": "Administration",
          "entrepreneur_individuel": "Entrepreneur individuel", "entrepreneur_spectacle": "Entrepreneur de spectacles",
          "avocat": "Avocat"}
BUSINESS_TYPES = ["client", "fournisseur", "distributeur", "grossiste", "détaillant", "sous-traitant", "prestataire",
                  "banque", "assureur", "partenaire", "actionnaire", "filiale", "succursale", "franchisé", "agent"]
UPSTREAM = {"fournisseur", "sous-traitant", "prestataire", "banque", "assureur", "actionnaire"}   # flèche vers l'entité


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


# ------------------------------------------------------------------ collecte (mise en cache)
@st.cache_data(ttl=86400, show_spinner=False)
def etablissements(siren: str, max_pages: int = 3) -> tuple[list[dict], int, str]:
    """Établissements (siège et secondaires) : jusqu'à 300 renvoyés, nombre total exact."""
    out, total, err = [], 0, ""
    try:
        for page in range(1, max_pages + 1):
            r = requests.get(API, params={"q": siren, "per_page": 1, "limite_matching_etablissements": 100,
                                          "page_etablissements": page}, headers=UA, timeout=15)
            r.raise_for_status()
            res = [x for x in r.json().get("results", []) if x.get("siren") == siren]
            if not res:
                break
            total = res[0].get("nombre_etablissements") or total
            batch = res[0].get("matching_etablissements") or []
            out += batch
            if len(batch) < 100:
                break
    except requests.RequestException as e:
        err = f"établissements indisponibles ({e.__class__.__name__})"
    seen, uniq = set(), []
    for e in out:
        if e.get("siret") not in seen:
            seen.add(e.get("siret")); uniq.append(e)
    return uniq, int(total or len(uniq)), err


@st.cache_data(ttl=86400, show_spinner=False)
def registry_controlled(siren: str, name: str) -> tuple[list[dict], str]:
    """Sociétés dont l'entité est dirigeante (président, gérant...) selon le registre : filiales très probables."""
    words = [w for w in _norm(name).split() if len(w) > 2 and w not in {"SAS", "SA", "SARL", "GROUPE", "SOCIETE", "FRANCE"}]
    if not words:
        return [], ""
    found, err = {}, ""
    try:
        for page in (1, 2):
            r = requests.get(API, params={"q": " ".join(words[:3]), "per_page": 25, "page": page}, headers=UA, timeout=15)
            r.raise_for_status()
            for x in r.json().get("results", []):
                if x.get("siren") == siren:
                    continue
                for d in x.get("dirigeants") or []:
                    if d.get("type_dirigeant") == "personne morale" and d.get("siren") == siren:
                        found[x["siren"]] = {"siren": x["siren"], "nom": x.get("nom_complet", ""), "qualite": d.get("qualite", ""),
                                             "etat": x.get("etat_administratif", ""), "naf": x.get("activite_principale", ""),
                                             "commune": (x.get("siege") or {}).get("libelle_commune", "")}
    except requests.RequestException as e:
        err = f"recherche des sociétés dirigées indisponible ({e.__class__.__name__})"
    return list(found.values()), err


def _gleif_get(path: str, params=None):
    r = requests.get(f"{GLEIF}{path}", params=params, headers={**UA, "Accept": "application/vnd.api+json"}, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _lei_summary(rec: dict) -> dict:
    a = rec.get("attributes", {})
    e = a.get("entity", {})
    return {"lei": a.get("lei") or rec.get("id"), "nom": (e.get("legalName") or {}).get("name", ""),
            "pays": (e.get("legalAddress") or {}).get("country", ""), "statut": e.get("status", ""),
            "registre": e.get("registeredAs", "")}


@st.cache_data(ttl=86400, show_spinner=False)
def gleif(siren: str) -> dict:
    """LEI de l'entité, sociétés mères, filiales consolidées (niveau 2 du GLEIF) et nombre d'ISIN."""
    out = {"lei": "", "parents": [], "children": [], "children_total": 0, "isin_total": 0, "err": ""}
    try:
        j = _gleif_get("/lei-records", {"filter[entity.registeredAs]": siren, "filter[entity.legalAddress.country]": "FR",
                                        "page[size]": 5})
        recs = [r for r in (j or {}).get("data", []) if _lei_summary(r)["registre"].replace(" ", "") == siren]
        if not recs:
            return out
        me = _lei_summary(recs[0])
        out["lei"] = me["lei"]
        for kind, label in (("direct-parent", "mère directe"), ("ultimate-parent", "mère ultime")):
            p = _gleif_get(f"/lei-records/{me['lei']}/{kind}")
            if p and p.get("data"):
                s = _lei_summary(p["data"])
                if s["lei"] not in {x["lei"] for x in out["parents"]}:
                    out["parents"].append({**s, "lien": label})
        c = _gleif_get(f"/lei-records/{me['lei']}/direct-children", {"page[size]": 100})
        if c:
            out["children"] = [_lei_summary(x) for x in c.get("data", [])]
            out["children_total"] = ((c.get("meta") or {}).get("pagination") or {}).get("total", len(out["children"]))
        i = _gleif_get(f"/lei-records/{me['lei']}/isins", {"page[size]": 1})
        if i:
            out["isin_total"] = ((i.get("meta") or {}).get("pagination") or {}).get("total", 0)
    except (requests.RequestException, ValueError) as e:
        out["err"] = f"GLEIF indisponible ({e.__class__.__name__})"
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def wikidata(siren: str) -> dict:
    """Cotation (place, code, éventuelle date de fin), filiales et maisons mères déclarées dans Wikidata."""
    out = {"qid": "", "label": "", "cotations": [], "filiales": [], "meres": [], "site": "", "err": ""}
    q = f"""
SELECT ?item ?itemLabel ?rel ?obj ?objLabel ?ticker ?end ?site WHERE {{
  ?item wdt:P1616 "{siren}" .
  OPTIONAL {{ ?item wdt:P856 ?site . }}
  OPTIONAL {{
    {{ ?item p:P414 ?stmt . ?stmt ps:P414 ?obj . OPTIONAL {{ ?stmt pq:P249 ?ticker . }} OPTIONAL {{ ?stmt pq:P582 ?end . }} BIND("cotation" AS ?rel) }}
    UNION {{ ?item wdt:P355 ?obj . BIND("filiale" AS ?rel) }}
    UNION {{ ?item wdt:P749 ?obj . BIND("mere" AS ?rel) }}
    UNION {{ ?item wdt:P127 ?obj . BIND("proprietaire" AS ?rel) }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
}} LIMIT 300"""
    try:
        r = requests.get(WIKIDATA, params={"query": q, "format": "json"}, headers=UA, timeout=20)
        r.raise_for_status()
        rows = r.json().get("results", {}).get("bindings", [])
    except (requests.RequestException, ValueError) as e:
        out["err"] = f"Wikidata indisponible ({e.__class__.__name__})"
        return out
    v = lambda b, k: (b.get(k) or {}).get("value", "")
    seen = set()
    for b in rows:
        out["qid"] = out["qid"] or v(b, "item").rsplit("/", 1)[-1]
        out["label"] = out["label"] or v(b, "itemLabel")
        out["site"] = out["site"] or v(b, "site")
        rel, name = v(b, "rel"), v(b, "objLabel")
        if not rel or (rel, name) in seen:
            continue
        seen.add((rel, name))
        if rel == "cotation":
            out["cotations"].append({"place": name, "code": v(b, "ticker"), "fin": v(b, "end")[:10]})
        elif rel == "filiale":
            out["filiales"].append(name)
        else:
            out["meres"].append({"nom": name, "lien": "maison mère" if rel == "mere" else "propriétaire"})
    return out


def listing_status(wd: dict, gl: dict) -> tuple[str, str, str]:
    """(statut, détail, source) sur la cotation en bourse."""
    active = [c for c in wd.get("cotations", []) if not c["fin"]]
    ended = [c for c in wd.get("cotations", []) if c["fin"]]
    if active:
        det = " · ".join(f"{c['place']}" + (f" ({c['code']})" if c["code"] else "") for c in active)
        return "Cotée", det, "Wikidata (à confirmer sur le site de la bourse)"
    if ended:
        det = " · ".join(f"{c['place']} jusqu'au {c['fin']}" for c in ended)
        return "Anciennement cotée", det, "Wikidata"
    if gl.get("isin_total"):
        return "Non cotée selon les sources consultées", f"émetteur de {gl['isin_total']} titre(s) avec code ISIN (obligations possibles)", "GLEIF"
    return "Non cotée selon les sources consultées", "aucune cotation trouvée", "Wikidata, GLEIF"


# ------------------------------------------------------------------ relations saisies par l'analyste
def ensure_table() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS private_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, siren TEXT NOT NULL, organisation TEXT NOT NULL, type_relation TEXT NOT NULL,
        contrepartie TEXT NOT NULL, contrepartie_siren TEXT DEFAULT '', pays TEXT DEFAULT '', part_pct TEXT DEFAULT '',
        source TEXT DEFAULT '', note TEXT DEFAULT '', ajoute_par TEXT NOT NULL, ts TEXT NOT NULL)""")


def org_key(user: dict) -> str:
    return user.get("organisation") or user["email"]


def business_relations(siren: str, user: dict) -> list[dict]:
    """Relations d'affaires visibles par l'utilisateur : publiques (CSV) + privées de son organisation + examen renforcé."""
    ensure_table()
    out = []
    rel = csvstore.read("entity_relations.csv")
    if not rel.empty:
        mine = rel[((rel["cible_entity_id"] == f"FR-{siren}") | (rel["source_entity_id"] == f"FR-{siren}")) &
                   (~rel["type_relation"].isin(["dirige", "detient", "filiale", "mere"]))]
        for r in mine.to_dict("records"):
            other = r["source_nom"] if r["cible_entity_id"] == f"FR-{siren}" else r["cible_nom"]
            out.append({"type": r["type_relation"], "nom": other, "pays": "", "part": r.get("part_pct", ""),
                        "source": r.get("source_donnee", ""), "portee": "publique", "statut": r.get("statut", "")})
    for r in db.query("SELECT * FROM private_relations WHERE siren=? AND organisation=? ORDER BY id DESC", (siren, org_key(user))):
        out.append({"type": r["type_relation"], "nom": r["contrepartie"], "pays": r["pays"], "part": r["part_pct"],
                    "source": r["source"] or "saisie analyste", "portee": "privée", "statut": "déclaré"})
    for r in st.session_state.get("exam_counterparties", {}).get(siren, []):
        out.append({**r, "portee": "session", "statut": "déduit des flux"})
    return out


def relation_form(siren: str, name: str, user: dict) -> None:
    ensure_table()
    with st.form(f"rel_{siren}", clear_on_submit=True):
        st.markdown(f"**Ajouter une relation d'affaires de {name}**")
        c = st.columns([1.2, 2, 1, 0.8])
        typ = c[0].selectbox("Type", BUSINESS_TYPES)
        cp = c[1].text_input("Contrepartie (nom)")
        pays = c[2].text_input("Pays", "FR")
        part = c[3].text_input("Part (%)", placeholder="ex. 22")
        c2 = st.columns([2, 2, 1.2])
        cp_siren = c2[0].text_input("SIREN de la contrepartie (facultatif)")
        source = c2[1].text_input("Source (lien, document, entretien)")
        scope = c2[2].radio("Visibilité", ["privée", "publique"], horizontal=True,
                            help="Privée : visible par votre organisation seulement. Publique : ajoutée au référentiel partagé "
                                 "(uniquement si la source est publique).")
        note = st.text_input("Note")
        if st.form_submit_button("Ajouter la relation", type="primary") and cp.strip():
            if scope == "publique":
                rid = f"FR-{siren}>{_norm(cp)[:40]}:{typ}"
                src_is_entity = typ in UPSTREAM
                csvstore.upsert("entity_relations.csv", "relation_id", {
                    "relation_id": rid,
                    "source_entity_id": f"FR-{cp_siren}" if src_is_entity and cp_siren else ("EXT" if src_is_entity else f"FR-{siren}"),
                    "source_nom": cp if src_is_entity else name,
                    "cible_entity_id": f"FR-{siren}" if src_is_entity else (f"FR-{cp_siren}" if cp_siren else "EXT"),
                    "cible_nom": name if src_is_entity else cp, "type_relation": typ, "part_pct": part,
                    "source_donnee": source or "saisie analyste", "methode": "humain", "confiance": "0.7",
                    "statut": "proposé", "derniere_observation": date.today().isoformat()})
            else:
                db.execute("INSERT INTO private_relations (siren, organisation, type_relation, contrepartie, contrepartie_siren, pays, "
                           "part_pct, source, note, ajoute_par, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (siren, org_key(user), typ, cp.strip(), cp_siren, pays, part, source, note, user["email"], db.now()))
            db.audit(user["email"], "relation_ajoutee", {"siren": siren, "type": typ, "portee": scope})
            st.success("Relation ajoutée au schéma.")


# ------------------------------------------------------------------ synthèse des données
def collect(siren: str, name: str) -> dict:
    with st.spinner("Recherche des établissements, du groupe et de la cotation..."):
        etabs, etab_total, e1 = etablissements(siren)
        ctrl, e2 = registry_controlled(siren, name)
        gl = gleif(siren)
        wd = wikidata(siren)
    errs = [e for e in (e1, e2, gl.get("err"), wd.get("err")) if e]
    return {"etabs": etabs, "etab_total": etab_total, "controlled": ctrl, "gleif": gl, "wikidata": wd, "errors": errs,
            "listing": listing_status(wd, gl)}


def subsidiaries(data: dict) -> list[dict]:
    """Fusion des filiales : registre (dirigée par l'entité), GLEIF (consolidation), Wikidata."""
    subs, seen = [], set()
    for c in data["controlled"]:
        subs.append({"nom": c["nom"], "pays": "FR", "source": f"Registre : {c['qualite'] or 'dirigeant'}", "id": c["siren"],
                     "fiabilite": "officiel"})
        seen.add(_norm(c["nom"]))
    for c in data["gleif"]["children"]:
        if _norm(c["nom"]) not in seen:
            subs.append({"nom": c["nom"], "pays": c["pays"], "source": "GLEIF (consolidée)", "id": c["lei"], "fiabilite": "officiel"})
            seen.add(_norm(c["nom"]))
    for n in data["wikidata"]["filiales"]:
        if _norm(n) not in seen:
            subs.append({"nom": n, "pays": "", "source": "Wikidata", "id": "", "fiabilite": "à vérifier"})
            seen.add(_norm(n))
    return subs


def parents(data: dict, dirigeants: list[dict]) -> list[dict]:
    out, seen = [], set()
    for p in data["gleif"]["parents"]:
        out.append({"nom": p["nom"], "pays": p["pays"], "lien": p["lien"], "source": "GLEIF", "fiabilite": "officiel"})
        seen.add(_norm(p["nom"]))
    for p in data["wikidata"]["meres"]:
        if _norm(p["nom"]) not in seen:
            out.append({"nom": p["nom"], "pays": "", "lien": p["lien"], "source": "Wikidata", "fiabilite": "à vérifier"})
            seen.add(_norm(p["nom"]))
    return out


def etab_by_region(etabs: list[dict]) -> list[tuple[str, int]]:
    c = Counter(REGIONS.get(str(e.get("region") or ""), "Autre / étranger") for e in etabs if e.get("etat_administratif") == "A")
    return c.most_common()


def persist(siren: str, name: str, data: dict, actor: str) -> None:
    """Enregistre dans les CSV partagés les liens publics trouvés (groupe, filiales, cotation)."""
    today = date.today().isoformat()
    for s in subsidiaries(data):
        if s["fiabilite"] != "officiel":
            continue
        cid = f"FR-{s['id']}" if s["source"].startswith("Registre") else f"LEI-{s['id']}"
        csvstore.upsert("entity_relations.csv", "relation_id", {
            "relation_id": f"FR-{siren}>{cid}:filiale", "source_entity_id": f"FR-{siren}", "source_nom": name,
            "cible_entity_id": cid, "cible_nom": s["nom"], "type_relation": "filiale", "qualite": s["source"],
            "source_donnee": s["source"], "methode": "api", "confiance": "0.95", "statut": "officiel", "derniere_observation": today})
    for p in data["gleif"]["parents"]:
        csvstore.upsert("entity_relations.csv", "relation_id", {
            "relation_id": f"LEI-{p['lei']}>FR-{siren}:mere", "source_entity_id": f"LEI-{p['lei']}", "source_nom": p["nom"],
            "cible_entity_id": f"FR-{siren}", "cible_nom": name, "type_relation": "mere", "qualite": p["lien"],
            "source_donnee": "GLEIF", "methode": "api", "confiance": "0.95", "statut": "officiel", "derniere_observation": today})
    status, detail, src = data["listing"]
    csvstore.update_where("entities.csv", "siren", siren, {
        "lei": data["gleif"]["lei"], "cotation": status, "cotation_detail": detail,
        "nb_filiales_connues": str(len(subsidiaries(data))), "nb_etablissements_total": str(data["etab_total"])})


# ------------------------------------------------------------------ cartographie
def _q(s) -> str:
    return str(s or "").replace('"', "'").replace("\n", " ")[:60]


def dot(row: dict, dirigeants: list[dict], data: dict, biz: list[dict], max_items: int = 14) -> str:
    """Schéma relationnel complet (Graphviz) : groupe à gauche, entité au centre, filiales, sites et affaires à droite."""
    risk = int(float(row.get("score_risque_indicatif") or 0))
    border = "#2E8B57" if risk < 35 else "#E0A100" if risk < 60 else "#C0392B"
    status, detail, _ = data["listing"]
    L = ['digraph G {', 'rankdir=LR; bgcolor="transparent"; compound=true; nodesep=0.25; ranksep=0.9;',
         'node [fontname="Helvetica", fontsize=10, style="rounded,filled", fillcolor="white", color="#0B2545"];',
         'edge [fontname="Helvetica", fontsize=8.5, color="#6B7480", arrowsize=0.7];',
         f'C [label="{_q(row["denomination"])}\\nSIREN {row["siren"]} · NAF {row.get("naf_code", "")}\\n{_q(status)}", shape=box, '
         f'fillcolor="#FFF4D6", color="{border}", penwidth=2.4, fontsize=12];']

    def cluster(name, label, color):
        return [f'subgraph cluster_{name} {{ label="{label}"; style="rounded,dashed"; color="{color}"; fontcolor="{color}"; fontname="Helvetica-Bold"; fontsize=10;']

    # gauche : maisons mères et dirigeants
    par = parents(data, dirigeants)
    if par:
        L += cluster("parents", "Groupe : sociétés mères", "#0B2545")
        for i, p in enumerate(par[:6]):
            sub = " · ".join(x for x in (p["pays"], p["lien"]) if x)
            L.append(f'P{i} [label="{_q(p["nom"])}\\n{_q(sub)}", shape=box, fillcolor="#E8EEF6"];')
        L.append("}")
        for i, p in enumerate(par[:6]):
            st_ = "solid" if p["fiabilite"] == "officiel" else "dashed"
            L.append(f'P{i} -> C [label="{_q(p["lien"])}", color="#0B2545", style={st_}, penwidth=1.6];')
    if dirigeants:
        L += cluster("gouv", "Gouvernance (registre)", "#0E7C86")
        for i, d in enumerate(dirigeants[:10]):
            shape = "box" if d["type"] == "personne morale" else "ellipse"
            L.append(f'D{i} [label="{_q(d["nom"])}\\n{_q(d["qualite"])}", shape={shape}, fillcolor="#E6F4F5", color="#0E7C86"];')
        if len(dirigeants) > 10:
            L.append(f'Dplus [label="+ {len(dirigeants) - 10} autres", shape=note, fillcolor="#F4F6F8"];')
        L.append("}")
        for i, d in enumerate(dirigeants[:10]):
            lab = "contrôle légal" if "commissaire" in (d["qualite"] or "").lower() else (d["qualite"] or "dirige")
            L.append(f'D{i} -> C [label="{_q(lab)}", color="#0E7C86"];')
    # fournisseurs et partenaires en amont
    up = [b for b in biz if b["type"] in UPSTREAM]
    down = [b for b in biz if b["type"] not in UPSTREAM]
    if up:
        L += cluster("amont", "Amont : fournisseurs, prestataires, banques", "#A86A00")
        for i, b in enumerate(up[:max_items]):
            L.append(f'U{i} [label="{_q(b["nom"])}\\n{_q(b["type"])}' + (f' · {_q(b["pays"])}' if b.get("pays") else "") +
                     '", shape=box, fillcolor="#FFF7E6", color="#A86A00"];')
        L.append("}")
        for i, b in enumerate(up[:max_items]):
            lab = b["type"] + (f" · {b['part']} %" if b.get("part") else "")
            st_ = "solid" if b["portee"] == "publique" and b["statut"] == "officiel" else "dashed"
            L.append(f'U{i} -> C [label="{_q(lab)}", color="#A86A00", style={st_}];')
    # droite : cotation, filiales, établissements, clients et distribution
    if status.startswith("Cotée") or status.startswith("Anciennement"):
        L.append(f'M [label="Marché financier\\n{_q(detail)}", shape=cylinder, fillcolor="#EEE8FB", color="#5B3FA8"];')
        L.append(f'C -> M [label="{"cotée" if status == "Cotée" else "anciennement cotée"}", color="#5B3FA8", '
                 f'style={"solid" if status == "Cotée" else "dashed"}];')
    subs = subsidiaries(data)
    if subs:
        L += cluster("filiales", f"Filiales et participations ({len(subs)})", "#1F6B45")
        for i, s in enumerate(subs[:max_items]):
            sub = " · ".join(x for x in (s["pays"], s["source"]) if x)
            L.append(f'F{i} [label="{_q(s["nom"])}\\n{_q(sub)}", shape=box, fillcolor="#E9F6EF", color="#1F6B45"];')
        if len(subs) > max_items:
            L.append(f'Fplus [label="+ {len(subs) - max_items} autres filiales", shape=note, fillcolor="#F4F6F8"];')
        L.append("}")
        for i, s in enumerate(subs[:max_items]):
            st_ = "solid" if s["fiabilite"] == "officiel" else "dashed"
            L.append(f'C -> F{i} [label="filiale", color="#1F6B45", style={st_}];')
        if len(subs) > max_items:
            L.append('C -> Fplus [color="#1F6B45", style=dotted];')
    regions = etab_by_region(data["etabs"])
    if regions:
        L += cluster("sites", f"Établissements en France : {data['etab_total']} au total (répartition sur {len(data['etabs'])} lus)", "#5B6770")
        for i, (reg, n) in enumerate(regions[:8]):
            L.append(f'E{i} [label="{_q(reg)}\\n{n} établissement(s) ouvert(s)", shape=folder, fillcolor="#F4F6F8", color="#5B6770"];')
        L.append("}")
        for i, (reg, n) in enumerate(regions[:8]):
            L.append(f'C -> E{i} [label="exploite", color="#5B6770"];')
    if down:
        L += cluster("aval", "Aval : clients, distributeurs, grossistes, détaillants", "#B42318")
        for i, b in enumerate(down[:max_items]):
            L.append(f'V{i} [label="{_q(b["nom"])}\\n{_q(b["type"])}' + (f' · {_q(b["pays"])}' if b.get("pays") else "") +
                     '", shape=box, fillcolor="#FDEDEC", color="#B42318"];')
        L.append("}")
        for i, b in enumerate(down[:max_items]):
            lab = b["type"] + (f" · {b['part']} %" if b.get("part") else "")
            st_ = "solid" if b["portee"] == "publique" and b["statut"] == "officiel" else "dashed"
            L.append(f'C -> V{i} [label="{_q(lab)}", color="#B42318", style={st_}];')
    L.append("}")
    return "\n".join(L)


LEGEND = ("**Lecture du schéma** : à gauche, ce qui contrôle l'entité (sociétés mères, dirigeants) et l'amont (fournisseurs, "
          "prestataires, banques) ; à droite, ce qu'elle contrôle ou dessert (cotation, filiales, établissements, clients, "
          "distributeurs, grossistes, détaillants). Trait plein : source officielle. Pointillés : lien à vérifier ou déclaré. "
          "Cadre de l'entité : vert, orange ou rouge selon le risque indicatif.")
