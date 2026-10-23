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


def first_run_setup() -> None:
    st.markdown("<span class='rb-brand'>🛡️ RegBridge · installation</span>", unsafe_allow_html=True)
    st.info("Aucun administrateur n'existe. Créez le compte administrateur (ou définissez ADMIN_EMAIL et "
            "ADMIN_PASSWORD dans les secrets Streamlit).")
    with st.form("setup"):
        email = st.text_input("E-mail administrateur")
        name = st.text_input("Nom")
        pwd = st.text_input("Mot de passe", type="password", help="10 caractères, une majuscule, un chiffre")
        if st.form_submit_button("Créer l'administrateur", type="primary"):
            try:
                auth.create_user(email, name or "Administrateur", pwd, role="admin")
                st.success("Administrateur créé. Connectez-vous."); st.rerun()
            except ValueError as e:
                st.error(str(e))


def login_page() -> None:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("<span class='rb-brand'>🛡️ RegBridge</span>", unsafe_allow_html=True)
        landing = st.session_state.get("landing")
        if landing:
            s = SERVICES[landing]
            st.markdown(f"## {s['icon']} {s['name']}")
            st.write(s["pitch"])
            if s["free"]:
                st.success("Disponible gratuitement avec quota mensuel : créez un compte pour essayer.")
            else:
                st.info("Service sur abonnement : créez un compte puis demandez l'accès.")
        else:
            st.markdown("## Conformité LCB-FT, sanctions et fraude")
            st.write("Veille réglementaire et sanctions, recherche d'entreprises et de notoriété, dossiers KYC, "
                     "typologies de fraude, rapports PDF, Word et image.")
        st.caption("Outil d'aide à la décision : chaque résultat se vérifie sur les sources officielles.")
    with right:
        t_login, t_signup = st.tabs(["Se connecter", "Créer un compte gratuit"])
        with t_login, st.form("login"):
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
        with t_signup, st.form("signup"):
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
