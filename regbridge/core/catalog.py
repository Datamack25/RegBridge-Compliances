"""Catalogue des services : la seule liste à modifier pour ajouter un produit.

Chaque service déclare :
- `free`  : quotas mensuels gratuits par action (vide = service payant uniquement) ;
- `tabs`  : ses onglets, dans l'ordre (le premier est la page d'accueil) ;
- `free_tabs` : onglets visibles en gratuit (les autres s'affichent verrouillés) ;
- `module`: le module Python qui l'affiche (services/<module>.py).
"""

SERVICES = {
    # --- services ouverts en gratuit avec quota ---------------------------
    "veille_reg": {
        "name": "Veille réglementaire", "icon": "📜", "family": "Veille",
        "pitch": "Nouveaux textes classés par thème, juridiction et impact ; bulletins PDF, Word et image.",
        "free": {"export": 2},
        "tabs": ["Accueil", "Tableau des textes", "Échéances", "Fiches d'impact", "Bulletins et exports"],
        "free_tabs": ["Accueil", "Tableau des textes", "Bulletins et exports"],
        "module": "veille_reglementaire",
    },
    "veille_sanctions": {
        "name": "Sanctions et embargos", "icon": "🛡️", "family": "Veille",
        "pitch": "Ajouts, radiations et modifications des listes UE, ONU, OFAC, SECO et DG Trésor.",
        "free": {"export": 2},
        "tabs": ["Accueil", "Journal des changements", "Régimes et pays", "Alertes portefeuille", "Bulletins et exports"],
        "free_tabs": ["Accueil", "Journal des changements", "Bulletins et exports"],
        "module": "veille_sanctions",
    },
    "entreprise": {
        "name": "Recherche entreprise 360°", "icon": "🏢", "family": "Recherche",
        "pitch": "Identité, finances, dirigeants, relations et cartographie d'une société ou d'une association.",
        "free": {"recherche": 5, "export": 2},
        "tabs": ["Accueil", "Fiche entité", "Cartographie", "Examen renforcé", "Base des entités"],
        "free_tabs": ["Accueil", "Fiche entité", "Cartographie"],
        "module": "entreprise",
    },
    "notoriete": {
        "name": "Notoriété personne", "icon": "🔎", "family": "Recherche",
        "pitch": "Recherche de notoriété par familles de mots (sanctions, fraude, condamnation...) et rapport des liens.",
        "free": {"recherche": 2, "export": 1},
        "tabs": ["Accueil", "Nouvelle recherche", "Historique"],
        "free_tabs": ["Accueil", "Nouvelle recherche"],
        "module": "notoriete",
    },
    # --- services payants uniquement --------------------------------------
    "fraudes": {
        "name": "Typologies de fraude", "icon": "🧭", "family": "Référentiels",
        "pitch": "Référentiel enrichi des fraudes et typologies LCB-FT, signaux d'alerte et secteurs.",
        "free": {}, "tabs": ["Accueil", "Référentiel", "Proposer une typologie", "Exports"],
        "module": "fraudes",
    },
    "dossiers": {
        "name": "Dossiers KYC", "icon": "🗂️", "family": "Dossiers",
        "pitch": "Dossier client, documents, contrôles, décision en deux temps et note d'escalade.",
        "free": {}, "tabs": ["Accueil", "Dossiers", "Documents", "Décisions", "Rapports"],
        "module": "generic",
    },
    "transactions": {
        "name": "Surveillance des transactions", "icon": "📈", "family": "Dossiers",
        "pitch": "Import multi-fichiers, 47 typologies, alertes et paramétrage versionné.",
        "free": {}, "tabs": ["Accueil", "Import", "Alertes", "Règles", "Rapports"],
        "module": "generic",
    },
    "evaluation": {
        "name": "Évaluation du dispositif", "icon": "✅", "family": "Gouvernance",
        "pitch": "Analyse d'écarts face au référentiel, score de maturité et plan d'action.",
        "free": {}, "tabs": ["Accueil", "Questionnaire", "Écarts", "Plan d'action", "Rapports"],
        "module": "generic",
    },
    "gouvernance": {
        "name": "Cartographie et contrôle interne", "icon": "🏛️", "family": "Gouvernance",
        "pitch": "Cartographie des risques, plan de contrôle à trois niveaux, incidents, rapports annuels.",
        "free": {}, "tabs": ["Accueil", "Cartographie", "Plan de contrôle", "Incidents", "Rapports"],
        "module": "generic",
    },
    "listes": {
        "name": "Listes blanches et noires", "icon": "📋", "family": "Référentiels",
        "pitch": "Entités de confiance et entités à risque, avec source, expiration et revue.",
        "free": {}, "tabs": ["Accueil", "Liste blanche", "Liste noire", "Imports et exports"],
        "module": "generic",
    },
    "formation": {
        "name": "Formation et glossaire", "icon": "🎓", "family": "Formation",
        "pitch": "Modules, quiz, certificats vérifiables et glossaire de 600 concepts.",
        "free": {}, "tabs": ["Accueil", "Modules", "Quiz", "Certificats", "Glossaire"],
        "module": "generic",
    },
    "pont": {
        "name": "Pont transfrontalier", "icon": "🌍", "family": "Conseil",
        "pitch": "Corridors Europe, Caraïbes, Afrique : évaluation, de-risking, prestations RegBridge Conseil.",
        "free": {}, "tabs": ["Accueil", "Évaluation", "Corridors", "Prestations"],
        "module": "generic",
    },
}

FAMILY_ORDER = ["Veille", "Recherche", "Dossiers", "Référentiels", "Gouvernance", "Formation", "Conseil"]

ACTION_LABELS = {"export": "exports PDF, Word ou image", "recherche": "recherches"}
