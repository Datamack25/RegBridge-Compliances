# RegBridge : plateforme de conformité (noyau commun)

Plateforme Streamlit modulaire : un seul noyau (comptes, droits, quotas, exports, référentiels CSV, audit) et des services ouverts selon l'abonnement.

## Ce qui fonctionne

- **Connexion en deux espaces** : *Utilisateur* ou *Administration* (réservé aux comptes administrateurs). Création de compte gratuite.
- **Lanceur de services façon Microsoft 365** : tous les services sont visibles, avec leur statut :
  - « Abonné » : tous les onglets ouverts ;
  - « Gratuit » : quota mensuel affiché ;
  - « 🔒 Sur abonnement » : bouton *Demander l'accès*, la demande arrive dans la console d'administration.
- **Lien direct vers un produit** : `https://votre-app/?service=entreprise`. Le visiteur voit la page du produit, se connecte et arrive dessus.
- **Quatre services en gratuit avec quota** :
  - Veille réglementaire ;
  - Sanctions et embargos ;
  - Recherche entreprise 360° ;
  - Notoriété personne.
- **Moteur d'export unique** : PDF, Word, PNG, JPEG et CSV, depuis n'importe quel service. Chaque document porte une date, une empreinte SHA-256 et un avertissement ; les exports gratuits portent un filigrane.
- **Console d'administration** :
  - comptes et rôles ;
  - activation des services (durée, offre) ;
  - demandes d'accès ;
  - quotas gratuits modifiables ;
  - référentiels CSV avec contrôle d'intégrité ;
  - journal d'audit.
- **Aperçu « Voir la plateforme comme »** : l'administrateur voit exactement les droits d'un client, sans consommer ses quotas.
- **Enrichissement continu des CSV** :
  - chaque recherche d'entreprise ajoute ou met à jour `entities.csv`, `entity_financials.csv` et `entity_relations.csv` ;
  - chaque champ modifié est journalisé dans `entity_enrichment_log.csv` ;
  - les entités découvertes (par exemple une holding dirigeante) entrent dans une file d'attente, traitée au niveau 1 seulement.
- **Référentiel des typologies de fraude** (42 typologies au départ) : les utilisateurs proposent, l'administrateur valide ; import CSV possible.

## Installation locale

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # puis renseigner ADMIN_EMAIL et ADMIN_PASSWORD
streamlit run app.py
```

Sans secrets, un écran d'installation demande de créer l'administrateur au premier lancement. Aucun compte par défaut n'est publié.

## Déploiement sur Streamlit Community Cloud

1. Pousser le dépôt sur GitHub. Le dossier `data/` et `secrets.toml` sont exclus par `.gitignore`.
2. Créer l'application en pointant sur `app.py`.
3. Coller `ADMIN_EMAIL` et `ADMIN_PASSWORD` dans *Settings > Secrets*.

⚠️ **Le disque de Streamlit Cloud est effacé à chaque redémarrage.** Comptes, abonnements et CSV enrichis seraient perdus. Avant d'avoir de vrais clients :
- remplacer `core/db.py` par une base PostgreSQL gérée dans l'UE (Supabase, par exemple) ;
- stocker les référentiels sur un stockage objet ou dans une branche « données » du dépôt.

Seules `connect()` et `csvstore.REF_DIR` sont à changer.

## Structure

```
app.py                  entrée : installation, connexion, lanceur, routage
core/
  catalog.py            LA liste des services (nom, icône, onglets, quotas gratuits)
  entitlements.py       droits : full / free / locked, quotas, activation, demandes
  auth.py               comptes, mots de passe hachés (PBKDF2), administrateur initial
  db.py                 SQLite (à remplacer par PostgreSQL), journal d'audit
  reports.py            moteur PDF / Word / PNG / JPEG / CSV
  csvstore.py           référentiels CSV : ajout, mise à jour, manifeste, intégrité
  ui.py                 thème, lanceur, onglets verrouillés, bloc d'export
services/
  veille_reglementaire.py  veille_sanctions.py  entreprise.py  notoriete.py
  fraudes.py            typologies de fraude
  generic.py            gabarit des services en construction
  admin.py              console d'administration
seed/                   référentiels de départ (copiés dans data/referentiels au 1er lancement)
scripts/ingest_sanctions.py   squelette d'ingestion des listes officielles (garde-fous inclus)
```

## Ajouter ou personnaliser un service

1. Ajouter une entrée dans `core/catalog.py` :
   - `free: {}` pour un service payant uniquement ;
   - `free: {"export": 2}` pour ouvrir un quota gratuit.
2. Copier `services/generic.py` en `services/mon_service.py`, puis renseigner `"module": "mon_service"`.
3. Dans chaque onglet, appeler `ui.export_panel(user, sid, contexte, key="...")` pour obtenir les exports PDF, Word et image.

Les droits, le verrouillage des onglets, les quotas et la page d'accueil fonctionnent automatiquement.

## À brancher avant un usage réel

- **Sanctions** : `seed/sanctions_changes.csv` ne contient que des lignes **fictives** (marquées `donnee_demo = oui`). Il faut écrire les connecteurs de `scripts/ingest_sanctions.py` et les planifier, par exemple avec GitHub Actions.
- **Veille réglementaire** :
  - les 14 textes de départ sont marqués `verifie = non` et sont à contrôler sur les textes officiels ;
  - la profondeur gratuite est réglée à 365 jours pour la démonstration, à ramener à 30 jours quand la veille sera alimentée chaque jour.
- **Notoriété** :
  - le prototype utilise le flux RSS de Google News (titres et liens seulement) ;
  - pour un service payant, il faut une API presse sous contrat ;
  - les recherches nominatives ne sont pas conservées sur le serveur.
- **Recherche entreprise** :
  - elle repose sur l'API Recherche d'entreprises (gratuite, Licence Ouverte 2.0, mention de la source obligatoire) ;
  - les bénéficiaires effectifs du RBE ne sont pas collectés (accès restreint).
- **Paiement** : l'activation est manuelle depuis la console. Stripe peut venir plus tard, en appelant `entitlements.grant()` depuis un webhook.
- **Juridique** : CGU, politique de confidentialité, registre des traitements et accord de traitement, à faire relire avant ouverture.
