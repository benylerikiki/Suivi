import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from db_sync import get_connection, init_db, pull_db_from_github, push_db_to_github

st.set_page_config(page_title="CRM Affaires", layout="wide")

# Chargement initial depuis GitHub une seule fois par session
if "db_loaded" not in st.session_state:
    pull_db_from_github()
    init_db()
    st.session_state.db_loaded = True

STATUTS = ["À chiffrer", "Offre envoyée", "En négo", "Gagné", "Perdu", "Stand-by"]
TYPES_MAT = [
    "Groupe froid",
    "CTA",
    "PAC",
    "Rooftop",
    "Ventilo-convecteurs",
    "Autre",
]

st.title("Suivi des Affaires Commerciales")

# Barre latérale : synchro manuelle & export Excel
with st.sidebar:
    st.header("Synchronisation")
    if st.button("Forcer rechargement GitHub", use_container_width=True):
        if pull_db_from_github():
            st.success("Base rechargée depuis GitHub.")
            st.rerun()
        else:
            st.warning("Mode local actif (secrets GitHub absents).")

    conn = get_connection()
    df_aff_exp = pd.read_sql("SELECT * FROM affaires", conn)
    df_cli_exp = pd.read_sql("SELECT * FROM clients", conn)
    df_his_exp = pd.read_sql("SELECT * FROM historique", conn)
    conn.close()

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_aff_exp.to_excel(writer, sheet_name="Affaires", index=False)
        df_cli_exp.to_excel(writer, sheet_name="Clients", index=False)
        df_his_exp.to_excel(writer, sheet_name="Historique", index=False)

    st.download_button(
        label="Exporter en Excel (.xlsx)",
        data=buffer.getvalue(),
        file_name=f"export_crm_{date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

tab1, tab2, tab3, tab4 = st.tabs([
    "Cockpit & Relances",
    "Pipe Commercial",
    "Nouvelle Affaire",
    "Clients & Historique",
])

# --- ONGLET 1 : COCKPIT & RELANCES ---
with tab1:
    conn = get_connection()
    df_aff = pd.read_sql("SELECT * FROM affaires", conn)
    conn.close()

    en_cours = df_aff[
        df_aff["statut"].isin(["À chiffrer", "Offre envoyée", "En négo"])
    ]
    gagne = df_aff[df_aff["statut"] == "Gagné"]

    ca_pipe = en_cours["montant_ht"].sum()
    ca_pondere = (en_cours["montant_ht"] * en_cours["probabilite"] / 100).sum()
    marge_moy = en_cours["marge_pct"].mean() if not en_cours.empty else 0
    ca_gagne = gagne["montant_ht"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pipe en cours", f"{ca_pipe:,.0f} €".replace(",", " "))
    c2.metric("CA pondéré", f"{ca_pondere:,.0f} €".replace(",", " "))
    c3.metric("Marge moy. pipe", f"{marge_moy:.1f} %")
    c4.metric("CA Gagné", f"{ca_gagne:,.0f} €".replace(",", " "))

    st.divider()
    st.subheader("Relances prioritaires (aujourd'hui ou en retard)")

    today_str = date.today().isoformat()
    a_relancer = en_cours[
        (en_cours["date_relance"].notna())
        & (en_cours["date_relance"] != "")
        & (en_cours["date_relance"] <= today_str)
    ].sort_values("date_relance")

    if a_relancer.empty:
        st.info("Aucune relance en retard aujourd'hui.")
    else:
        for _, row in a_relancer.iterrows():
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.markdown(
                    f"**{row['num_offre']}** — {row['client']} | *{row['intitule']}* "
                    f"({row['montant_ht']:,.0f} € HT - Marge {row['marge_pct']}%) — "
                    f"Relance prévue : `{row['date_relance']}`"
                )
            with col_btn:
                if st.button("+7 jours", key=f"rel_{row['id']}"):
                    nouvelle_date = (date.today() + timedelta(days=7)).isoformat()
                    conn = get_connection()
                    conn.execute(
                        "UPDATE affaires SET date_relance = ? WHERE id = ?",
                        (nouvelle_date, row["id"]),
                    )
                    conn.commit()
                    conn.close()
                    push_db_to_github(f"Report relance {row['num_offre']}")
                    st.rerun()

# --- ONGLET 2 : PIPE COMMERCIAL ---
with tab2:
    conn = get_connection()
    df_pipe = pd.read_sql("SELECT * FROM affaires ORDER BY id DESC", conn)
    conn.close()

    f1, f2 = st.columns(2)
    filtre_statut = f1.multiselect(
        "Filtrer par statut",
        STATUTS,
        default=["À chiffrer", "Offre envoyée", "En négo"],
    )
    filtre_client = f2.text_input("Rechercher client ou intitulé")

    df_filtre = df_pipe.copy()
    if filtre_statut:
        df_filtre = df_filtre[df_filtre["statut"].isin(filtre_statut)]
    if filtre_client:
        mask = df_filtre["client"].str.contains(
            filtre_client, case=False, na=False
        ) | df_filtre["intitule"].str.contains(
            filtre_client, case=False, na=False
        )
        df_filtre = df_filtre[mask]

    edited_df = st.data_editor(
        df_filtre,
        use_container_width=True,
        hide_index=True,
        disabled=["id", "num_offre", "date_creation"],
        column_config={
            "statut": st.column_config.SelectboxColumn(
                "Statut", options=STATUTS, required=True
            ),
            "typologie_materiel": st.column_config.SelectboxColumn(
                "Matériel", options=TYPES_MAT
            ),
            "montant_ht": st.column_config.NumberColumn(
                "Montant HT (€)", format="%.0f €"
            ),
            "marge_pct": st.column_config.NumberColumn(
                "Marge (%)", format="%.1f %%"
            ),
            "probabilite": st.column_config.NumberColumn(
                "Proba (%)", min_value=0, max_value=100, step=10
            ),
        },
    )

    if st.button("Enregistrer les modifications du pipe", type="primary"):
        conn = get_connection()
        cur = conn.cursor()
        for _, row in edited_df.iterrows():
            cur.execute(
                """
                UPDATE affaires
                SET client=?, contact=?, intitule=?, typologie_materiel=?,
                    montant_ht=?, marge_pct=?, statut=?, probabilite=?,
                    date_relance=?, lien_dossier=?
                WHERE id=?
            """,
                (
                    row["client"],
                    row["contact"],
                    row["intitule"],
                    row["typologie_materiel"],
                    row["montant_ht"],
                    row["marge_pct"],
                    row["statut"],
                    row["probabilite"],
                    row["date_relance"],
                    row["lien_dossier"],
                    row["id"],
                ),
            )
        conn.commit()
        conn.close()
        push_db_to_github("Mise à jour pipe commercial")
        st.success("Modifications enregistrées et synchronisées sur GitHub.")

# --- ONGLET 3 : NOUVELLE AFFAIRE ---
with tab3:
    conn = get_connection()
    liste_clients = pd.read_sql(
        "SELECT raison_sociale FROM clients ORDER BY raison_sociale", conn
    )["raison_sociale"].tolist()
    conn.close()

    with st.form("form_nouvelle_affaire", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        num_offre = col1.text_input("N° d'offre *", placeholder="ex: DEV-2026-042")
        client_existant = col2.selectbox(
            "Client existant", ["-- Nouveau client --"] + liste_clients
        )
        nouveau_client = col3.text_input("Ou saisir nouveau client")

        col4, col5 = st.columns(2)
        intitule = col4.text_input(
            "Intitulé du projet *", placeholder="ex: Groupe froid R1234ze agroalimentaire"
        )
        contact = col5.text_input("Contact affaire")

        col6, col7, col8, col9 = st.columns(4)
        typologie = col6.selectbox("Typologie matériel", TYPES_MAT)
        montant_ht = col7.number_input("Montant HT (€)", min_value=0.0, step=500.0)
        marge_pct = col8.number_input(
            "Marge brute (%)", min_value=0.0, max_value=100.0, value=11.0, step=0.5
        )
        statut_init = col9.selectbox("Statut initial", STATUTS)

        col10, col11, col12 = st.columns(3)
        proba = col10.slider("Probabilité (%)", 0, 100, 50, step=10)
        date_relance = col11.date_input(
            "Date de relance", value=date.today() + timedelta(days=7)
        )
        lien_dossier = col12.text_input("Chemin dossier / lien")

        submitted = st.form_submit_button("Créer l'affaire", type="primary")
        if submitted:
            client_final = (
                nouveau_client.strip()
                if nouveau_client.strip()
                else (
                    client_existant
                    if client_existant != "-- Nouveau client --"
                    else ""
                )
            )
            if not num_offre or not intitule or not client_final:
                st.error("N° d'offre, client et intitulé obligatoires.")
            else:
                conn = get_connection()
                cur = conn.cursor()
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO clients (raison_sociale) VALUES (?)",
                        (client_final,),
                    )
                    cur.execute(
                        """
                        INSERT INTO affaires (
                            num_offre, date_creation, client, contact, intitule,
                            typologie_materiel, montant_ht, marge_pct, statut,
                            probabilite, date_relance, lien_dossier
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            num_offre.strip(),
                            date.today().isoformat(),
                            client_final,
                            contact,
                            intitule,
                            typologie,
                            montant_ht,
                            marge_pct,
                            statut_init,
                            proba,
                            date_relance.isoformat(),
                            lien_dossier,
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO historique (num_offre, date_action, type_action, note)
                        VALUES (?, ?, 'Création', ?)
                    """,
                        (
                            num_offre.strip(),
                            datetime.now().strftime("%Y-%m-%d %H:%M"),
                            f"Création affaire ({statut_init})",
                        ),
                    )
                    conn.commit()
                    push_db_to_github(f"Nouvelle affaire {num_offre.strip()}")
                    st.success(f"Affaire {num_offre} créée et synchronisée.")
                except Exception as e:
                    st.error(f"Erreur (N° d'offre déjà existant ?) : {e}")
                finally:
                    conn.close()

# --- ONGLET 4 : CLIENTS & HISTORIQUE ---
with tab4:
    c_left, c_right = st.columns([1, 1])

    with c_left:
        st.subheader("Journal d'actions par affaire")
        conn = get_connection()
        offres = pd.read_sql(
            "SELECT num_offre, client, intitule FROM affaires ORDER BY id DESC", conn
        )
        conn.close()

        if not offres.empty:
            choix = st.selectbox(
                "Sélectionner une affaire",
                offres["num_offre"]
                + " — "
                + offres["client"]
                + " ("
                + offres["intitule"]
                + ")",
            )
            num_sel = choix.split(" — ")[0]

            with st.form("form_note", clear_on_submit=True):
                type_act = st.selectbox(
                    "Type", ["Appel", "Mail", "Visite", "Révision prix", "Autre"]
                )
                note_txt = st.text_area("Compte-rendu")
                if st.form_submit_button("Ajouter au journal"):
                    if note_txt.strip():
                        conn = get_connection()
                        conn.execute(
                            """
                            INSERT INTO historique (num_offre, date_action, type_action, note)
                            VALUES (?, ?, ?, ?)
                        """,
                            (
                                num_sel,
                                datetime.now().strftime("%Y-%m-%d %H:%M"),
                                type_act,
                                note_txt.strip(),
                            ),
                        )
                        conn.commit()
                        conn.close()
                        push_db_to_github(f"Note sur {num_sel}")
                        st.rerun()

            conn = get_connection()
            df_hist = pd.read_sql(
                "SELECT date_action, type_action, note FROM historique WHERE num_offre = ? ORDER BY id DESC",
                conn,
                params=(num_sel,),
            )
            conn.close()
            st.dataframe(df_hist, use_container_width=True, hide_index=True)

    with c_right:
        st.subheader("Base Clients")
        conn = get_connection()
        df_clients = pd.read_sql("SELECT * FROM clients ORDER BY raison_sociale", conn)
        conn.close()

        edited_clients = st.data_editor(
            df_clients,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            disabled=["id"],
        )
        if st.button("Sauvegarder base clients"):
            conn = get_connection()
            cur = conn.cursor()
            for _, r in edited_clients.iterrows():
                if pd.notna(r.get("id")):
                    cur.execute(
                        """
                        UPDATE clients
                        SET raison_sociale=?, typologie=?, contact_principal=?,
                            telephone=?, email=?, conditions_remise=?
                        WHERE id=?
                    """,
                        (
                            r["raison_sociale"],
                            r["typologie"],
                            r["contact_principal"],
                            r["telephone"],
                            r["email"],
                            r["conditions_remise"],
                            r["id"],
                        ),
                    )
                elif pd.notna(r.get("raison_sociale")) and str(r["raison_sociale"]).strip():
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO clients (
                            raison_sociale, typologie, contact_principal,
                            telephone, email, conditions_remise
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            r["raison_sociale"],
                            r["typologie"],
                            r["contact_principal"],
                            r["telephone"],
                            r["email"],
                            r["conditions_remise"],
                        ),
                    )
            conn.commit()
            conn.close()
            push_db_to_github("Mise à jour base clients")
            st.success("Clients enregistrés.")