"""
espace_recruteur.py
---------------------
Page "Espace Recruteur" — réservée aux agences (authentification à venir,
cf. priorité 3 de la synthèse technique). Réutilise exactement les mêmes
fonctions de calcul que l'Espace Candidat (moteur_recherche.py), appliquées
à PLUSIEURS profils candidats simultanément plutôt qu'à un seul.

Ceci est un MVP volontairement minimal pour valider l'architecture (page
séparée + moteur partagé) — le stockage reste en session (non persistant :
priorité 2 de la synthèse) et l'accès n'est pas encore protégé (priorité 3).
"""

import streamlit as st
import pandas as pd

from moteur_recherche import (
    get_referentiel_appellations,
    suggerer_postes,
    _extraire_code_rome,
    resoudre_codes_rome,
    offres_par_ville,
    calculer_correspondance_offre,
)

st.title("🏢 Espace Recruteur")
st.info(
    "🔒 Espace réservé aux agences partenaires — l'authentification multi-comptes "
    "n'est pas encore développée (voir feuille de route). Cette page est un premier "
    "aperçu fonctionnel : elle réutilise exactement le même moteur de calcul que "
    "l'Espace Candidat, appliqué à plusieurs profils à la fois."
)

st.markdown(
    "**Principe** : indique un poste ciblé et un département, ajoute les profils de "
    "tes candidats (compétences, outils, langages), puis compare leur score de "
    "correspondance moyen sur les offres réelles actuellement disponibles pour ce poste."
)

# ---------------------------------------------------------------------------
# 1. Poste ciblé (même mécanique que l'Espace Candidat : référentiel ROME +
#    suggestions hybrides dictionnaire/recherche floue)
# ---------------------------------------------------------------------------
st.markdown("#### 🎯 Poste ciblé")

appellations = get_referentiel_appellations()
col1, col2 = st.columns(2)
with col1:
    poste_texte = st.text_input(
        "Intitulé du poste recherché par l'agence pour ses clients",
        key="recruteur_poste_texte",
        placeholder="ex: Chef de projet, Data Analyst...",
    )
with col2:
    departement_recruteur = st.text_input("Département", value="13", key="recruteur_departement")

poste_confirme_label = None
if poste_texte.strip():
    suggestions = suggerer_postes(poste_texte)
    if suggestions:
        st.caption("💡 Suggestions — clique pour sélectionner :")
        colonnes_tags = st.columns(2)
        for i, suggestion in enumerate(suggestions):
            col_tag = colonnes_tags[i % 2]
            if col_tag.button(suggestion, key=f"recruteur_tag_{i}_{suggestion}"):
                st.session_state["recruteur_poste_confirme"] = suggestion
                st.rerun()

if "recruteur_poste_confirme" in st.session_state:
    poste_confirme_label = st.session_state["recruteur_poste_confirme"]
    st.success(f"Poste sélectionné : **{poste_confirme_label}**")

st.divider()

# ---------------------------------------------------------------------------
# 2. Profils candidats (stockage en session — non persistant pour l'instant)
# ---------------------------------------------------------------------------
st.markdown("#### 👥 Profils candidats")
st.caption(
    "⚠️ Stockage temporaire (session en cours uniquement) — la gestion multi-profils "
    "persistante est prévue en priorité 2 de la feuille de route."
)

if "recruteur_profils" not in st.session_state:
    st.session_state["recruteur_profils"] = []

a_supprimer = None
for i, profil in enumerate(st.session_state["recruteur_profils"]):
    with st.container(border=True):
        c1, c2 = st.columns(2)
        profil["nom"] = c1.text_input("Nom / repère candidat", value=profil.get("nom", ""), key=f"rec_nom_{i}")
        profil["competences"] = c2.text_input(
            "Compétences (séparées par une virgule)", value=profil.get("competences", ""), key=f"rec_comp_{i}"
        )
        c3, c4 = st.columns(2)
        profil["outils"] = c3.text_input(
            "Outils (séparés par une virgule)", value=profil.get("outils", ""), key=f"rec_outils_{i}"
        )
        profil["langages"] = c4.text_input(
            "Langages informatiques (séparés par une virgule)", value=profil.get("langages", ""), key=f"rec_lang_{i}"
        )
        if st.button("🗑️ Retirer ce profil", key=f"rec_suppr_{i}"):
            a_supprimer = i

if a_supprimer is not None:
    st.session_state["recruteur_profils"].pop(a_supprimer)
    st.rerun()

if st.button("➕ Ajouter un profil candidat"):
    st.session_state["recruteur_profils"].append({})
    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# 3. Comparaison — réutilisation directe de calculer_correspondance_offre,
#    la même fonction que celle utilisée dans l'onglet Offres d'emploi côté
#    Espace Candidat, appliquée ici à chaque profil sur chaque offre trouvée.
# ---------------------------------------------------------------------------
if st.button("🚀 Comparer les profils sur ce poste", type="primary"):
    if not poste_confirme_label:
        st.warning("Sélectionne d'abord un poste ciblé (via les suggestions ci-dessus).")
    elif not st.session_state["recruteur_profils"]:
        st.warning("Ajoute au moins un profil candidat avant de lancer la comparaison.")
    else:
        item_poste = next(
            (a for a in appellations if a.get("libelle", "").strip() == poste_confirme_label), None
        )
        code_rome = _extraire_code_rome(item_poste) if item_poste else None
        if not code_rome:
            with st.spinner("Résolution du poste..."):
                df_resolu = resoudre_codes_rome(mots_cles=poste_confirme_label, departement=departement_recruteur)
            code_rome = df_resolu.iloc[0]["code_rome"] if not df_resolu.empty else None

        if not code_rome:
            st.error("Impossible de résoudre ce poste pour l'instant. Essaie un autre intitulé.")
        else:
            with st.spinner("Récupération des offres et calcul des scores..."):
                df_villes, total_region, _, _, _, _ = offres_par_ville(code_rome, departement_recruteur)

                # Ré-appelle la recherche brute pour avoir les offres complètes (avec le
                # détail des compétences par offre), nécessaires au scoring détaillé.
                from moteur_recherche import get_token, SCOPE_OFFRES
                import requests as _requests

                token = get_token(SCOPE_OFFRES)
                url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                params = {"codeROME": code_rome, "departement": departement_recruteur, "range": "0-149"}
                r = _requests.get(url, headers=headers, params=params)
                offres_completes = r.json().get("resultats", []) if r.status_code in (200, 206) else []

                resultats_classement = []
                for profil in st.session_state["recruteur_profils"]:
                    competences_liste = [c.strip() for c in profil.get("competences", "").split(",") if c.strip()]
                    outils_liste = [c.strip() for c in profil.get("outils", "").split(",") if c.strip()]
                    langages_liste = [c.strip() for c in profil.get("langages", "").split(",") if c.strip()]

                    scores = []
                    for offre in offres_completes:
                        score, _ = calculer_correspondance_offre(
                            offre, competences_liste, outils_liste, langages_liste, ""
                        )
                        if score is not None:
                            scores.append(score)

                    score_moyen = round(sum(scores) / len(scores)) if scores else None
                    resultats_classement.append({
                        "Candidat": profil.get("nom") or "(sans nom)",
                        "Score moyen de correspondance": f"{score_moyen}%" if score_moyen is not None else "N/C",
                        "Offres analysées": len(offres_completes),
                    })

            st.markdown(f"#### 📊 Classement — {total_region} offre(s) trouvée(s) dans le département {departement_recruteur}")
            if not offres_completes:
                st.info("Aucune offre trouvée pour ce poste/département — comparaison non calculable.")
            else:
                df_classement = pd.DataFrame(resultats_classement)
                st.dataframe(df_classement, use_container_width=True, hide_index=True)
                st.caption(
                    "Score calculé avec la même fonction que le score de correspondance de "
                    "l'Espace Candidat (compétences/outils/langages déclarés vs compétences "
                    "demandées par les offres réelles)."
                )
