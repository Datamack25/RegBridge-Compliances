"""Ingestion des listes officielles de sanctions vers data/referentiels/sanctions_changes.csv.

À planifier (GitHub Actions, chaque jour). Garde-fous repris de Reg-Insight :
- une extraction de moins de MIN_ROWS lignes est rejetée (source en panne) ;
- une inscription disparue est marquée « radiation », jamais supprimée ;
- les lignes de démonstration (donnee_demo = oui) sont retirées au premier passage réel.

Sources à brancher (formats publiés par chaque autorité, à vérifier au moment du branchement) :
- UE : fichier consolidé des sanctions financières (FSF) de la Commission européenne ;
- ONU : liste consolidée du Conseil de sécurité (XML) ;
- OFAC : liste SDN (CSV ou XML) ;
- SECO : base SESAM ;
- DG Trésor : registre national des gels.
"""
import sys

MIN_ROWS = 50


def diff(previous: dict[str, dict], current: dict[str, dict], regime: str, today: str) -> list[dict]:
    """Compare deux extractions {identifiant: fiche} et produit les lignes du journal des changements."""
    if len(current) < MIN_ROWS:
        raise RuntimeError(f"{regime} : extraction trop courte ({len(current)} lignes), fichier précédent conservé.")
    out = []
    for key, rec in current.items():
        if key not in previous:
            out.append({**rec, "type_changement": "ajout", "date": today, "regime": regime, "donnee_demo": "non"})
        elif rec != previous[key]:
            out.append({**rec, "type_changement": "modification", "date": today, "regime": regime, "donnee_demo": "non"})
    for key, rec in previous.items():
        if key not in current:
            out.append({**rec, "type_changement": "radiation", "date": today, "regime": regime, "donnee_demo": "non"})
    return out


def fetch(regime: str) -> dict[str, dict]:
    raise NotImplementedError(f"Connecteur {regime} à écrire : téléchargement, lecture, normalisation des noms.")


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
