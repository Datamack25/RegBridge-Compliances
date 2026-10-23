"""Console d'administration : comptes, accès payants, demandes, quotas gratuits, référentiels, journal d'audit."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import auth, csvstore, db
from core import entitlements as ent
from core import ui
from core.catalog import SERVICES


def users_df() -> pd.DataFrame:
    return pd.DataFrame(db.query("SELECT id, email, name, organisation, role, active, created_at FROM users ORDER BY id"))


def render(admin: dict) -> None:
    st.markdown("<span class='rb-brand'>⚙️ Console d'administration</span>", unsafe_allow_html=True)
    tabs = st.tabs(["Tableau de bord", "Utilisateurs", "Accès et abonnements", "Demandes d'accès", "Quotas gratuits",
                    "Référentiels CSV", "Journal d'audit"])
    users = users_df()
    label = {r["id"]: f"{r['name']} · {r['email']}" for _, r in users.iterrows()}

    with tabs[0]:
        pend = db.query("SELECT COUNT(*) n FROM access_requests WHERE status='en_attente'")[0]["n"]
        act = db.query("SELECT COUNT(DISTINCT user_id) n FROM entitlements WHERE revoked=0 AND (end_date IS NULL OR end_date>=?)",
                       (date.today().isoformat(),))[0]["n"]
        month = date.today().strftime("%Y-%m")
        use = pd.DataFrame(db.query("SELECT service_id, action, COUNT(*) n FROM usage WHERE substr(ts,1,7)=? GROUP BY 1,2", (month,)))
        ui.kpis([(str(len(users)), "comptes"), (str(act), "comptes abonnés"), (str(pend), "demandes en attente"),
                 (str(int(use["n"].sum()) if not use.empty else 0), "actions ce mois-ci")])
        if not use.empty:
            st.markdown("**Usage du mois par service**")
            use["service"] = use["service_id"].map(lambda s: SERVICES.get(s, {}).get("name", s))
            st.dataframe(use[["service", "action", "n"]], hide_index=True, width="stretch")

    with tabs[1]:
        st.dataframe(users, hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1.form("new_user", clear_on_submit=True):
            st.markdown("**Créer un compte**")
            email = st.text_input("E-mail")
            name = st.text_input("Nom")
            org = st.text_input("Organisation")
            pwd = st.text_input("Mot de passe provisoire", type="password", help="10 caractères, une majuscule, un chiffre")
            role = st.selectbox("Rôle", ["user", "admin"], format_func=lambda r: "Utilisateur" if r == "user" else "Administrateur")
            if st.form_submit_button("Créer", type="primary"):
                try:
                    auth.create_user(email, name, pwd, role, org)
                    db.audit(admin["email"], "compte_cree_par_admin", {"email": email, "role": role})
                    st.success("Compte créé."); st.rerun()
                except ValueError as e:
                    st.error(str(e))
        with c2.container(border=True):
            st.markdown("**Modifier un compte**")
            if not users.empty:
                uid = st.selectbox("Compte", users["id"].tolist(), format_func=lambda i: label[i], key="adm_mod")
                r = users[users["id"] == uid].iloc[0]
                new_role = st.selectbox("Rôle", ["user", "admin"], index=0 if r["role"] == "user" else 1, key="adm_role")
                active = st.checkbox("Compte actif", value=bool(r["active"]), key="adm_act")
                newpwd = st.text_input("Nouveau mot de passe (facultatif)", type="password", key="adm_pwd")
                if st.button("Enregistrer", key="adm_save"):
                    if uid == admin["id"] and (new_role != "admin" or not active):
                        st.error("Vous ne pouvez pas retirer vos propres droits d'administrateur.")
                    else:
                        db.execute("UPDATE users SET role=?, active=? WHERE id=?", (new_role, int(active), uid))
                        if newpwd:
                            try:
                                auth.set_password(uid, newpwd, admin["email"])
                            except ValueError as e:
                                st.error(str(e)); st.stop()
                        db.audit(admin["email"], "compte_modifie", {"id": uid, "role": new_role, "actif": active})
                        st.success("Compte mis à jour."); st.rerun()

    with tabs[2]:
        st.markdown("**Activer un service pour un utilisateur**")
        clients = users[users["role"] == "user"]
        if clients.empty:
            st.info("Aucun compte utilisateur.")
        else:
            c = st.columns([3, 3, 2, 2])
            uid = c[0].selectbox("Utilisateur", clients["id"].tolist(), format_func=lambda i: label[i], key="g_user")
            sids = c[1].multiselect("Services", list(SERVICES), format_func=lambda s: f"{SERVICES[s]['icon']} {SERVICES[s]['name']}", placeholder="Choisir")
            plan = c[2].selectbox("Offre", ["pro", "equipe", "entreprise", "essai"])
            dur = c[3].selectbox("Durée", ["1 mois", "3 mois", "12 mois", "7 jours (essai)", "sans échéance"])
            if st.button("Activer l'accès", type="primary", disabled=not sids):
                days = {"1 mois": 31, "3 mois": 92, "12 mois": 366, "7 jours (essai)": 7}.get(dur)
                end = (date.today() + timedelta(days=days)).isoformat() if days else None
                for s in sids:
                    ent.grant(uid, s, admin["email"], end, plan)
                st.success("Accès activé."); st.rerun()
        rows = db.query("SELECT e.id, u.email, e.service_id, e.plan, e.start_date, e.end_date, e.granted_by, e.revoked "
                        "FROM entitlements e JOIN users u ON u.id=e.user_id ORDER BY e.id DESC")
        if rows:
            df = pd.DataFrame(rows)
            df["service"] = df["service_id"].map(lambda s: SERVICES.get(s, {}).get("name", s))
            st.dataframe(df[["id", "email", "service", "plan", "start_date", "end_date", "granted_by", "revoked"]],
                         hide_index=True, width="stretch")
            live = df[df["revoked"] == 0]
            if not live.empty:
                rid = st.selectbox("Retirer un accès", live["id"].tolist(),
                                   format_func=lambda i: f"#{i} · {live.set_index('id').loc[i, 'email']} · {live.set_index('id').loc[i, 'service']}")
                if st.button("Retirer"):
                    ent.revoke(rid, admin["email"]); st.rerun()

    with tabs[3]:
        reqs = db.query("SELECT r.id, u.id uid, u.email, u.organisation, r.service_id, r.message, r.ts FROM access_requests r "
                        "JOIN users u ON u.id=r.user_id WHERE r.status='en_attente' ORDER BY r.ts")
        if not reqs:
            st.caption("Aucune demande en attente.")
        for r in reqs:
            with st.container(border=True):
                st.markdown(f"**{r['email']}** ({r['organisation'] or 'sans organisation'}) demande "
                            f"**{SERVICES[r['service_id']]['name']}** · {r['ts'][:16]}")
                if r["message"]:
                    st.caption(r["message"])
                c = st.columns([2, 2, 1, 1])
                dur = c[0].selectbox("Durée", ["7 jours (essai)", "1 mois", "12 mois"], key=f"rq_d_{r['id']}")
                plan = c[1].selectbox("Offre", ["essai", "pro", "equipe", "entreprise"], key=f"rq_p_{r['id']}")
                if c[2].button("Accorder", key=f"rq_ok_{r['id']}", type="primary"):
                    days = {"7 jours (essai)": 7, "1 mois": 31, "12 mois": 366}[dur]
                    ent.grant(r["uid"], r["service_id"], admin["email"], (date.today() + timedelta(days=days)).isoformat(), plan)
                    db.execute("UPDATE access_requests SET status='accordee' WHERE id=?", (r["id"],)); st.rerun()
                if c[3].button("Refuser", key=f"rq_ko_{r['id']}"):
                    db.execute("UPDATE access_requests SET status='refusee' WHERE id=?", (r["id"],))
                    db.audit(admin["email"], "demande_refusee", r["id"]); st.rerun()

    with tabs[4]:
        st.caption("Quotas mensuels des services ouverts en gratuit. Mettre 0 ferme l'action en gratuit.")
        for sid, s in SERVICES.items():
            if not s["free"]:
                continue
            cols = st.columns([3] + [2] * len(s["free"]) + [1])
            cols[0].markdown(f"**{s['icon']} {s['name']}**")
            vals = {}
            for i, action in enumerate(s["free"]):
                vals[action] = cols[i + 1].number_input(action, 0, 1000, ent.free_limit(sid, action), key=f"q_{sid}_{action}")
            if cols[-1].button("OK", key=f"q_ok_{sid}"):
                for action, v in vals.items():
                    db.execute("INSERT OR REPLACE INTO quota_overrides (service_id, action, monthly_limit) VALUES (?,?,?)",
                               (sid, action, int(v)))
                db.audit(admin["email"], "quotas_modifies", {"service": sid, **vals}); st.success("Enregistré.")

    with tabs[5]:
        m = csvstore.manifest()
        if not m.empty:
            m["integrite"] = m["fichier"].map(lambda f: "✅" if csvstore.verify(f) else "⚠️")
        st.dataframe(m, hide_index=True, width="stretch")
        names = m["fichier"].tolist() if not m.empty else []
        if names:
            name = st.selectbox("Fichier", names)
            df = csvstore.read(name)
            st.dataframe(df, hide_index=True, width="stretch", height=260)
            st.download_button("Télécharger le CSV", df.to_csv(sep=";", index=False).encode("utf-8-sig"), file_name=name)
            up = st.file_uploader("Ajouter des lignes (CSV ; mêmes colonnes, ajout seulement)", type=["csv"], key="ref_up")
            if up and st.button("Ajouter au référentiel"):
                new = pd.read_csv(up, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
                missing = set(df.columns) - set(new.columns)
                if missing:
                    st.error(f"Colonnes manquantes : {', '.join(sorted(missing))}")
                else:
                    csvstore.append(name, new[df.columns].to_dict("records"))
                    db.audit(admin["email"], "referentiel_complete", {"fichier": name, "lignes": len(new)})
                    st.success(f"{len(new)} ligne(s) ajoutée(s)."); st.rerun()

    with tabs[6]:
        a = pd.DataFrame(db.query("SELECT ts, actor, action, detail FROM audit ORDER BY id DESC LIMIT 500"))
        q = st.text_input("Filtrer (acteur, action)")
        if q and not a.empty:
            a = a[a["actor"].str.contains(q, case=False) | a["action"].str.contains(q, case=False)]
        st.dataframe(a, hide_index=True, width="stretch")
