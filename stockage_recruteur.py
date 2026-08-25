"""
stockage_recruteur.py
-----------------------
Persistance des profils candidats de l'Espace Recruteur, via PostgreSQL
(Neon — DATABASE_URL dans les Secrets Streamlit). Module isolé, propre à
l'Espace Recruteur (pas partagé avec l'Espace Candidat).

Dégrade proprement si DATABASE_URL n'est pas configurée : les fonctions
d'écriture ne font rien et le chargement renvoie une liste vide, plutôt que
de faire planter l'app — à l'appelant de basculer sur st.session_state dans
ce cas (voir espace_recruteur.py).
"""

import os
import psycopg2
import psycopg2.extras


def base_disponible():
    return bool(os.environ.get("DATABASE_URL"))


def _connexion():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def initialiser_table():
    """Crée la table si elle n'existe pas encore. Sans effet si déjà en place."""
    if not base_disponible():
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS profils_candidats (
                    id SERIAL PRIMARY KEY,
                    nom TEXT DEFAULT '',
                    competences TEXT DEFAULT '',
                    outils TEXT DEFAULT '',
                    langages TEXT DEFAULT '',
                    date_creation TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()


def charger_profils():
    """Retourne la liste des profils enregistrés, triés par date de création."""
    if not base_disponible():
        return []
    with _connexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, nom, competences, outils, langages FROM profils_candidats ORDER BY id"
            )
            return [dict(ligne) for ligne in cur.fetchall()]


def ajouter_profil(nom="", competences="", outils="", langages=""):
    """Insère un nouveau profil et retourne son id."""
    if not base_disponible():
        return None
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO profils_candidats (nom, competences, outils, langages) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (nom, competences, outils, langages),
            )
            id_nouveau = cur.fetchone()[0]
        conn.commit()
    return id_nouveau


def ajouter_profils_en_masse(profils):
    """Insère plusieurs profils d'un coup (import Excel/CSV). Retourne le nombre inséré."""
    if not base_disponible() or not profils:
        return 0
    with _connexion() as conn:
        with conn.cursor() as cur:
            for p in profils:
                cur.execute(
                    "INSERT INTO profils_candidats (nom, competences, outils, langages) "
                    "VALUES (%s, %s, %s, %s)",
                    (p.get("nom", ""), p.get("competences", ""), p.get("outils", ""), p.get("langages", "")),
                )
        conn.commit()
    return len(profils)


def mettre_a_jour_profil(id_profil, nom, competences, outils, langages):
    if not base_disponible() or id_profil is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE profils_candidats SET nom=%s, competences=%s, outils=%s, langages=%s WHERE id=%s",
                (nom, competences, outils, langages, id_profil),
            )
        conn.commit()


def supprimer_profil(id_profil):
    if not base_disponible() or id_profil is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profils_candidats WHERE id=%s", (id_profil,))
        conn.commit()
