"""RegBridge : point d'entrée Streamlit.

Lancement local :  streamlit run app.py
Lien direct vers un produit : https://<votre-app>/?service=entreprise
(le client arrive sur la page d'accueil de ce produit après connexion).
"""
import os
import shutil

import streamlit as st

from core import auth, csvstore, db
from core import ui
from core.catalog import SERVICES

ui.setup_page()
db.init()

# Référentiels de départ : copiés une seule fois depuis seed/ vers data/referentiels/
SEED = os.path.join(os.path.dirname(__file__), "seed")
os.makedirs(csvstore.REF_DIR, exist_ok=True)
for f in os.listdir(SEED):
    if f.endswith(".csv") and not os.path.exists(csvstore.path(f)):
        shutil.copy(os.path.join(SEED, f), csvstore.path(f))
        csvstore._update_manifest(f, len(csvstore.read(f)))

try:
    auth.bootstrap_admin_from_secrets(st.secrets)
except FileNotFoundError:
    auth.bootstrap_admin_from_secrets({})

# Produit demandé dans l'URL : mémorisé jusqu'à la connexion
wanted = st.query_params.get("service")
if wanted in SERVICES and "service" not in st.session_state:
    st.session_state.landing = wanted


CHIPS = ["Veille réglementaire", "Sanctions et embargos", "Recherche entreprise 360°", "Notoriété",
         "Typologies de fraude", "Rapports PDF · Word · image"]
FOOTNOTE = "Outil d'aide à la décision : chaque résultat se vérifie sur les sources officielles."


def two_panes():
    """Visuel à gauche, formulaire compact à droite (centré verticalement par un espace)."""
    left, _, right, _ = st.columns([1.55, 0.12, 0.95, 0.15], vertical_alignment="center")
    return left, right


def first_run_setup() -> None:
    left, right = two_panes()
    with left:
        ui.hero("Installation de la plateforme",
                "Créez le compte administrateur. Il gère les comptes clients, active les services payants "
                "et règle les quotas gratuits.", CHIPS, FOOTNOTE)
    with right, st.container(border=True):
        st.markdown("<div class='rb-auth-title'>Premier administrateur</div>"
                    "<div class='rb-auth-sub'>Ou définissez ADMIN_EMAIL et ADMIN_PASSWORD dans les secrets.</div>",
                    unsafe_allow_html=True)
        with st.form("setup", border=False):
            email = st.text_input("E-mail", placeholder="vous@exemple.fr")
            name = st.text_input("Nom", placeholder="Prénom Nom")
            pwd = st.text_input("Mot de passe", type="password", help="10 caractères, une majuscule, un chiffre")
            if st.form_submit_button("Créer l'administrateur", type="primary", width="stretch"):
                try:
                    auth.create_user(email, name or "Administrateur", pwd, role="admin")
                    st.success("Administrateur créé. Connectez-vous."); st.rerun()
                except ValueError as e:
                    st.error(str(e))


def login_page() -> None:
    left, right = two_panes()
    with left:
        landing = st.session_state.get("landing")
        if landing:
            s = SERVICES[landing]
            extra = (" Disponible gratuitement avec un quota mensuel." if s["free"]
                     else " Service sur abonnement : créez un compte puis demandez l'accès.")
            ui.hero(f"{s['icon']} {s['name']}", s["pitch"] + extra, CHIPS, FOOTNOTE)
        else:
            ui.hero("Conformité LCB-FT, sanctions et fraude, sur une seule plateforme",
                    "Veillez, recherchez, analysez et documentez : de la veille réglementaire au rapport prêt à "
                    "transmettre, pour les flux entre l'Europe, l'Afrique et les Caraïbes.", CHIPS, FOOTNOTE)
    with right, st.container(border=True):
        st.markdown("<div class='rb-auth-title'>Bienvenue</div>"
                    "<div class='rb-auth-sub'>Connectez-vous ou créez un compte gratuit.</div>", unsafe_allow_html=True)
        t_login, t_signup = st.tabs(["Se connecter", "Créer un compte"])
        with t_login, st.form("login", border=False):
            space = st.radio("Espace", ["Utilisateur", "Administration"], horizontal=True)
            email = st.text_input("E-mail")
            pwd = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Connexion", type="primary", width="stretch"):
                u = auth.authenticate(email, pwd)
                if not u:
                    st.error("Identifiants incorrects.")
                elif space == "Administration" and u["role"] != "admin":
                    st.error("Ce compte n'a pas accès à l'administration.")
                else:
                    st.session_state.user = u
                    st.session_state.mode = "admin" if space == "Administration" else "user"
                    if st.session_state.get("landing") and space == "Utilisateur":
                        st.session_state.service = st.session_state.pop("landing")
                    st.rerun()
        with t_signup, st.form("signup", border=False):
            name = st.text_input("Nom et prénom")
            org = st.text_input("Organisation")
            email = st.text_input("E-mail professionnel")
            pwd = st.text_input("Mot de passe", type="password", help="10 caractères, une majuscule, un chiffre")
            ok = st.checkbox("J'accepte les conditions d'utilisation et la politique de confidentialité.")
            if st.form_submit_button("Créer mon compte", width="stretch"):
                if not ok:
                    st.error("Merci d'accepter les conditions.")
                else:
                    try:
                        auth.create_user(email, name, pwd, "user", org)
                        st.success("Compte créé : connectez-vous.")
                    except ValueError as e:
                        st.error(str(e))


def sidebar(user: dict) -> dict:
    """Barre latérale ; retourne l'utilisateur « effectif » (aperçu possible pour l'administrateur)."""
    with st.sidebar:
        ui.brand_mark()
        st.markdown(f"**{user['name']}**  \n{user['email']}")
        st.caption(user.get("organisation") or "")
        eff = user
        if user["role"] == "admin":
            mode = st.radio("Mode", ["Utilisateur", "Administrateur"],
                            index=0 if st.session_state.get("mode") == "user" else 1)
            st.session_state.mode = "user" if mode == "Utilisateur" else "admin"
            if st.session_state.mode == "user":
                others = db.query("SELECT id, email, name, organisation, role FROM users WHERE role='user' AND active=1")
                choice = st.selectbox("Voir la plateforme comme", ["Moi (accès complet)"] + [o["email"] for o in others])
                if choice != "Moi (accès complet)":
                    eff = {**next(o for o in others if o["email"] == choice), "preview": True}
                    st.info("Aperçu : vous voyez exactement les droits de ce client. Ses quotas ne sont pas consommés.")
        if st.session_state.get("service") and st.session_state.get("mode") == "user":
            if st.button("⊞ Tous les services", width="stretch"):
                st.session_state.service = None
                st.query_params.clear(); st.rerun()
        st.divider()
        if st.button("Se déconnecter", width="stretch"):
            db.audit(user["email"], "deconnexion")
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.query_params.clear(); st.rerun()
    return eff


def home(user: dict) -> None:
    st.markdown(f"<span class='rb-brand'>Bonjour {user['name'].split()[0]}</span>", unsafe_allow_html=True)
    st.caption("Vos services : abonnés, gratuits avec quota, ou sur demande d'accès.")
    ui.launcher(user)


if not auth.admin_exists():
    first_run_setup()
elif "user" not in st.session_state:
    login_page()
else:
    me = st.session_state.user
    eff = sidebar(me)
    if st.session_state.get("mode") == "admin" and me["role"] == "admin":
        from services import admin
        admin.render(me)
    elif st.session_state.get("service") in SERVICES:
        ui.render_service(eff, st.session_state.service)
    else:
        home(eff)
