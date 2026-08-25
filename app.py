"""
app.py
-------
Point d'entrée de l'application. Route entre les deux espaces décrits dans
la synthèse technique ("Architecture retenue") :
- Espace Candidat : les 4 onglets existants, accès gratuit et public.
- Espace Recruteur : nouvelle page réservée aux agences, réutilisant le même
  moteur de calcul (moteur_recherche.py) appliqué à plusieurs profils.

st.set_page_config() doit être appelé ici, avant st.navigation(...).run() —
jamais dans les fichiers de page eux-mêmes.
"""

import streamlit as st

st.set_page_config(page_title="Aide Conseil Emploi", layout="centered")

page_candidat = st.Page("espace_candidat.py", title="Espace Candidat", icon="🎯", default=True)
page_recruteur = st.Page("espace_recruteur.py", title="Espace Recruteur", icon="🏢")

navigation = st.navigation([page_candidat, page_recruteur])
navigation.run()
