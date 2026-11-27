def get_objectif_annee(annee: int, defaut: float = 4000000.0) -> float:
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT montant_objectif FROM objectifs WHERE annee = ?", (annee,))
    row = cur.fetchone()
    conn.close()
    return float(row[0]) if row else defaut


def set_objectif_annee(annee: int, montant: float):
    init_db()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO objectifs (annee, montant_objectif)
        VALUES (?, ?)
        ON CONFLICT(annee) DO UPDATE SET montant_objectif = excluded.montant_objectif
        """,
        (annee, montant),
    )
    conn.commit()
    conn.close()
