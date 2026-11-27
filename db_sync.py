import base64
import os
import shutil
import sqlite3
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

DB_FILE = "crm_affaires.db"


def get_github_config():
    try:
        return {
            "token": st.secrets["GITHUB_TOKEN"],
            "repo": st.secrets["GITHUB_REPO"],  # ex: "tonpseudo/crm-pro"
            "branch": st.secrets.get("GITHUB_BRANCH", "main"),
        }
    except Exception:
        return None


def pull_db_from_github():
    """Télécharge crm_affaires.db depuis GitHub au lancement."""
    cfg = get_github_config()
    if not cfg:
        return False

    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{DB_FILE}?ref={cfg['branch']}"
    headers = {"Authorization": f"token {cfg['token']}"}
    r = requests.get(url, headers=headers)

    if r.status_code == 200:
        content = base64.b64decode(r.json()["content"])
        with open(DB_FILE, "wb") as f:
            f.write(content)
        return True
    return False


def push_db_to_github(commit_msg="Mise à jour CRM"):
    """Pousse crm_affaires.db sur GitHub et crée un backup horodaté."""
    cfg = get_github_config()
    if not cfg or not os.path.exists(DB_FILE):
        return False

    with open(DB_FILE, "rb") as f:
        encoded_content = base64.b64encode(f.read()).decode("utf-8")

    headers = {
        "Authorization": f"token {cfg['token']}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 1. Mise à jour du fichier principal
    url_main = f"https://api.github.com/repos/{cfg['repo']}/contents/{DB_FILE}"
    r_get = requests.get(url_main, headers=headers)
    sha = r_get.json().get("sha") if r_get.status_code == 200 else None

    payload = {
        "message": commit_msg,
        "content": encoded_content,
        "branch": cfg["branch"],
    }
    if sha:
        payload["sha"] = sha

    r_put = requests.put(url_main, json=payload, headers=headers)

    # 2. Backup horodaté dans backups/
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    url_bkp = f"https://api.github.com/repos/{cfg['repo']}/contents/backups/crm_{ts}.db"
    payload_bkp = {
        "message": f"Backup {ts}",
        "content": encoded_content,
        "branch": cfg["branch"],
    }
    requests.put(url_bkp, json=payload_bkp, headers=headers)

    return r_put.status_code in (200, 201)


def init_db():
    """Crée les tables SQLite si inexistantes."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raison_sociale TEXT UNIQUE NOT NULL,
            typologie TEXT,
            contact_principal TEXT,
            telephone TEXT,
            email TEXT,
            conditions_remise TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS affaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_offre TEXT UNIQUE NOT NULL,
            date_creation TEXT,
            client TEXT,
            contact TEXT,
            intitule TEXT,
            typologie_materiel TEXT,
            montant_ht REAL DEFAULT 0,
            marge_pct REAL DEFAULT 0,
            statut TEXT DEFAULT 'À chiffrer',
            probabilite INTEGER DEFAULT 50,
            date_relance TEXT,
            lien_dossier TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS historique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_offre TEXT NOT NULL,
            date_action TEXT,
            type_action TEXT,
            note TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_connection():
    return sqlite3.connect(DB_FILE)