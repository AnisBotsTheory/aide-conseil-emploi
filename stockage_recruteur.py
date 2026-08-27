"""
stockage_recruteur.py
-----------------------
Persistance des profils candidats ET du suivi des candidatures de l'Espace
Recruteur, via PostgreSQL (Neon — DATABASE_URL dans les Secrets Streamlit).
Module isolé, propre à l'Espace Recruteur (pas partagé avec l'Espace
Candidat).

Dégrade proprement si DATABASE_URL n'est pas configurée : les fonctions
d'écriture ne font rien et le chargement renvoie une liste vide, plutôt que
de faire planter l'app — à l'appelant de basculer sur st.session_state dans
ce cas (voir espace_recruteur.py).
"""

import os
import psycopg2
import psycopg2.extras

STATUTS_CANDIDATURE = [
    "Candidature envoyée",
    "En cours",
    "Clôturée - retenue",
    "Clôturée - non retenue",
]


def base_disponible():
    return bool(os.environ.get("DATABASE_URL"))


def _connexion():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def initialiser_table():
    """
    Crée la table si elle n'existe pas encore, et ajoute les colonnes
    poste_souhaite/secteur_souhaite/cv_lien/langues_parlees/mobilite si la
    table existait déjà sans elles (migration légère, sans effet si déjà
    en place).
    """
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
                    poste_souhaite TEXT DEFAULT '',
                    secteur_souhaite TEXT DEFAULT '',
                    cv_lien TEXT DEFAULT '',
                    langues_parlees TEXT DEFAULT '',
                    mobilite TEXT DEFAULT '',
                    date_creation TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE profils_candidats ADD COLUMN IF NOT EXISTS poste_souhaite TEXT DEFAULT ''")
            cur.execute("ALTER TABLE profils_candidats ADD COLUMN IF NOT EXISTS secteur_souhaite TEXT DEFAULT ''")
            cur.execute("ALTER TABLE profils_candidats ADD COLUMN IF NOT EXISTS cv_lien TEXT DEFAULT ''")
            cur.execute("ALTER TABLE profils_candidats ADD COLUMN IF NOT EXISTS langues_parlees TEXT DEFAULT ''")
            cur.execute("ALTER TABLE profils_candidats ADD COLUMN IF NOT EXISTS mobilite TEXT DEFAULT ''")
        conn.commit()


def charger_profils():
    """Retourne la liste des profils enregistrés, triés par date de création."""
    if not base_disponible():
        return []
    with _connexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, nom, competences, outils, langages, poste_souhaite, secteur_souhaite, "
                "cv_lien, langues_parlees, mobilite FROM profils_candidats ORDER BY id"
            )
            return [dict(ligne) for ligne in cur.fetchall()]


def ajouter_profil(
    nom="", competences="", outils="", langages="", poste_souhaite="", secteur_souhaite="",
    cv_lien="", langues_parlees="", mobilite="",
):
    """Insère un nouveau profil et retourne son id."""
    if not base_disponible():
        return None
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO profils_candidats "
                "(nom, competences, outils, langages, poste_souhaite, secteur_souhaite, cv_lien, "
                "langues_parlees, mobilite) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (nom, competences, outils, langages, poste_souhaite, secteur_souhaite, cv_lien, langues_parlees, mobilite),
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
                    "INSERT INTO profils_candidats "
                    "(nom, competences, outils, langages, poste_souhaite, secteur_souhaite, cv_lien, "
                    "langues_parlees, mobilite) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        p.get("nom", ""), p.get("competences", ""), p.get("outils", ""),
                        p.get("langages", ""), p.get("poste_souhaite", ""), p.get("secteur_souhaite", ""),
                        p.get("cv_lien", ""), p.get("langues_parlees", ""), p.get("mobilite", ""),
                    ),
                )
        conn.commit()
    return len(profils)


def mettre_a_jour_profil(
    id_profil, nom, competences, outils, langages, poste_souhaite="", secteur_souhaite="",
    cv_lien="", langues_parlees="", mobilite="",
):
    if not base_disponible() or id_profil is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE profils_candidats SET nom=%s, competences=%s, outils=%s, langages=%s, "
                "poste_souhaite=%s, secteur_souhaite=%s, cv_lien=%s, langues_parlees=%s, mobilite=%s "
                "WHERE id=%s",
                (
                    nom, competences, outils, langages, poste_souhaite, secteur_souhaite,
                    cv_lien, langues_parlees, mobilite, id_profil,
                ),
            )
        conn.commit()


def supprimer_profil(id_profil):
    if not base_disponible() or id_profil is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profils_candidats WHERE id=%s", (id_profil,))
        conn.commit()


# ---------------------------------------------------------------------------
# Suivi des candidatures : quel candidat a été présenté à quelle offre, et
# avec quel statut (Présenté / Entretien prévu / Retenu / Refusé / ...).
# Table indépendante des profils (candidat_id peut être NULL si le profil
# d'origine a depuis été supprimé — on garde alors juste son nom en texte).
# ---------------------------------------------------------------------------
def initialiser_table_candidatures():
    if not base_disponible():
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candidatures (
                    id SERIAL PRIMARY KEY,
                    candidat_id INTEGER,
                    candidat_nom TEXT DEFAULT '',
                    candidat_poste_souhaite TEXT DEFAULT '',
                    candidat_cv_lien TEXT DEFAULT '',
                    offre_id TEXT DEFAULT '',
                    offre_intitule TEXT DEFAULT '',
                    entreprise_nom TEXT DEFAULT '',
                    statut TEXT DEFAULT 'Candidature envoyée',
                    date_creation TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE candidatures ADD COLUMN IF NOT EXISTS candidat_poste_souhaite TEXT DEFAULT ''")
            cur.execute("ALTER TABLE candidatures ADD COLUMN IF NOT EXISTS candidat_cv_lien TEXT DEFAULT ''")
        conn.commit()


def charger_candidatures():
    """Retourne la liste des candidatures suivies, les plus récentes en premier."""
    if not base_disponible():
        return []
    with _connexion() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, candidat_id, candidat_nom, candidat_poste_souhaite, candidat_cv_lien, "
                "offre_id, offre_intitule, entreprise_nom, statut, date_creation "
                "FROM candidatures ORDER BY date_creation DESC"
            )
            return [dict(ligne) for ligne in cur.fetchall()]


def ajouter_candidature(
    candidat_id, candidat_nom, candidat_poste_souhaite, offre_id, offre_intitule,
    entreprise_nom, statut="Candidature envoyée", candidat_cv_lien="",
):
    """Enregistre la présentation d'un candidat à une offre. Retourne l'id créé."""
    if not base_disponible():
        return None
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO candidatures "
                "(candidat_id, candidat_nom, candidat_poste_souhaite, candidat_cv_lien, offre_id, "
                "offre_intitule, entreprise_nom, statut) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    candidat_id, candidat_nom, candidat_poste_souhaite, candidat_cv_lien,
                    offre_id, offre_intitule, entreprise_nom, statut,
                ),
            )
            id_nouveau = cur.fetchone()[0]
        conn.commit()
    return id_nouveau


def candidature_existe(candidat_id, candidat_nom, offre_id):
    """
    Évite les doublons : vérifie si ce candidat a déjà été présenté à cette
    offre. Le rapprochement se fait sur candidat_id si disponible, sinon sur
    le nom (profils non persistés, sans id).
    """
    if not base_disponible():
        return False
    with _connexion() as conn:
        with conn.cursor() as cur:
            if candidat_id is not None:
                cur.execute(
                    "SELECT 1 FROM candidatures WHERE candidat_id=%s AND offre_id=%s LIMIT 1",
                    (candidat_id, offre_id),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM candidatures WHERE candidat_id IS NULL AND candidat_nom=%s AND offre_id=%s LIMIT 1",
                    (candidat_nom, offre_id),
                )
            return cur.fetchone() is not None


def mettre_a_jour_statut_candidature(id_candidature, statut):
    if not base_disponible() or id_candidature is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE candidatures SET statut=%s WHERE id=%s", (statut, id_candidature))
        conn.commit()


def supprimer_candidature(id_candidature):
    if not base_disponible() or id_candidature is None:
        return
    with _connexion() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM candidatures WHERE id=%s", (id_candidature,))
        conn.commit()
