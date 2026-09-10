"""
app.py
-------
Point d'entrée de l'application. Un seul espace exposé pour l'instant :
- Espace Candidat : les 4 onglets existants, accès gratuit et public.

L'Espace Recruteur (espace_recruteur.py) a été retiré de la navigation à la
demande explicite — le fichier peut rester sur le disque sans être exposé,
ou être supprimé séparément si besoin.

La liste de pages automatique de st.navigation est masquée (position="hidden")
plutôt que simplement réduite à une seule page : avec une seule page, elle
n'apporterait plus rien à afficher, et le bandeau latéral rétractable est
maintenant utilisé par espace_candidat.py pour un contenu différent (le
parcours de l'application), pas pour un menu de navigation entre espaces.

st.set_page_config() doit être appelé ici, avant st.navigation(...).run() —
jamais dans les fichiers de page eux-mêmes.
"""

import streamlit as st

st.set_page_config(page_title="Aide Conseil Emploi", layout="centered")

page_candidat = st.Page("espace_candidat.py", title="Espace Candidat", icon="🎯", default=True)

navigation = st.navigation([page_candidat], position="hidden")
navigation.run()
