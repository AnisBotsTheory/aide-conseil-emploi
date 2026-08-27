"""
espace_recruteur.py
---------------------
Page "Espace Recruteur" — réservée aux agences (authentification à venir,
cf. priorité 3 de la synthèse technique). Réutilise exactement les mêmes
fonctions de calcul que l'Espace Candidat (moteur_recherche.py), appliquées
à PLUSIEURS profils candidats simultanément plutôt qu'à un seul.

Les profils candidats sont désormais persistés en base PostgreSQL (Neon —
DATABASE_URL) via stockage_recruteur.py, avec repli automatique sur
st.session_state (perdu à la fermeture) si la base n'est pas configurée.

Parcours utilisateur (mis à jour) :
  1. Onglet "🏢 Besoin des entreprises" — le champ "Nom de la société" est
     affiché en premier (avec une option "Toutes les sociétés" pour ne
     filtrer sur aucun nom et afficher tous les besoins), ainsi qu'un filtre
     secteur d'activité optionnel avec analyse de la répartition par secteur.
     Le résultat est une liste de sociétés avec leur nombre d'offres
     publiées ; cliquer sur une société ouvre la sous-liste de ses offres ;
     cliquer sur une offre affiche sa fiche de poste et un bouton pour
     lancer le matching sur cette offre (les 0% ne sont pas affichés — un
     message l'indique si aucun profil ne correspond).
  2. Onglet "🎯 Poste ciblé" — recherche d'un poste précis (référentiel ROME
     + suggestions) et comparaison globale : score moyen des profils
     candidats sur toutes les offres disponibles pour ce poste.
  3. Onglet "👥 Profils candidats" — gestion dédiée des profils (ajout
     manuel, import Excel/CSV, édition, suppression), séparée de la
     recherche/matching.
"""

import streamlit as st
import pandas as pd
from io import BytesIO
from collections import Counter

from moteur_recherche import (
    get_referentiel_appellations,
    suggerer_postes,
    _extraire_code_rome,
    resoudre_codes_rome,
    offres_par_ville,
    rechercher_offres_completes,
    calculer_correspondance_offre,
    calculer_correspondance_recruteur,
    get_secteurs_activite,
)
import stockage_recruteur as db

secteurs_recruteur = get_secteurs_activite()
options_secteurs_recruteur = {"Peu importe": ""}
for s in secteurs_recruteur:
    code = s.get("code")
    libelle = s.get("libelle")
    if code and libelle:
        options_secteurs_recruteur[f"{libelle} ({code})"] = code

st.title("🏢 Espace Recruteur")
st.info(
    "🔒 Espace réservé aux agences partenaires — l'authentification multi-comptes "
    "n'est pas encore développée (voir feuille de route). Cette page est un premier "
    "aperçu fonctionnel : elle réutilise exactement le même moteur de calcul que "
    "l'Espace Candidat, appliqué à plusieurs profils à la fois."
)

appellations = get_referentiel_appellations()

# ---------------------------------------------------------------------------
# Profils candidats : chargement en session (nécessaire dans les deux onglets,
# donc initialisé ici, avant la répartition en onglets).
# ---------------------------------------------------------------------------
db.initialiser_table()

if "recruteur_profils" not in st.session_state:
    st.session_state["recruteur_profils"] = db.charger_profils() if db.base_disponible() else []

if "recruteur_recherche_compteur" not in st.session_state:
    st.session_state["recruteur_recherche_compteur"] = 0

# Département : commun aux deux onglets "Besoin des entreprises" et "Poste
# ciblé" (comparaison globale) — un seul champ, affiché avant les onglets.
departement_recruteur = st.text_input("Département", value="13", key="recruteur_departement")

tab_besoin_entreprises, tab_poste_cible, tab_profils = st.tabs(
    ["🏢 Besoin des entreprises", "📊 Vivier de talents", "👥 Profils candidats"]
)

# ===========================================================================
# ONGLET 1 — Besoin des entreprises : société -> offres -> fiche de poste -> matching
# ===========================================================================
with tab_besoin_entreprises:
    st.markdown(
        "**Principe** : recherche la société qui recrute (ou affiche tous les besoins), "
        "explore ses offres jusqu'à la fiche de poste, puis lance le matching contre ta "
        "base de profils candidats (gérée dans l'onglet « Profils candidats »)."
    )

    # -----------------------------------------------------------------
    # Nom de la société affiché en premier.
    # -----------------------------------------------------------------
    toutes_les_societes = st.checkbox(
        "🔘 Toutes les sociétés — afficher tous les besoins, sans filtrer sur un nom",
        key="recruteur_toutes_societes",
    )
    nom_societe_recherche = st.text_input(
        "Nom de la société qui recrute",
        key="recruteur_nom_societe",
        placeholder="ex: Airbus Helicopters, BNP Paribas...",
        disabled=toutes_les_societes,
    )
    libelles_secteurs_recherche = list(options_secteurs_recruteur.keys())
    secteur_choisi_recherche = st.selectbox(
        "Secteur d'activité (optionnel — pour cibler ou analyser les offres par secteur)",
        libelles_secteurs_recherche,
        key="recruteur_secteur_recherche",
    )
    secteur_code_recherche = options_secteurs_recruteur[secteur_choisi_recherche]

    recherche_possible = toutes_les_societes or bool(nom_societe_recherche.strip())

    if not recherche_possible:
        st.info("Saisis le nom d'une société, ou coche « Toutes les sociétés », pour lancer la recherche.")
    else:
        label_bouton = "🔍 Afficher tous les besoins" if toutes_les_societes else "🔍 Rechercher cette société"
        if st.button(label_bouton, key="btn_charger_entreprises"):
            with st.spinner("Recherche des offres..."):
                if toutes_les_societes:
                    st.session_state["recruteur_offres_entreprises"] = rechercher_offres_completes(
                        "TOUS", departement_recruteur, max_pages=5, secteur_activite=secteur_code_recherche
                    )
                else:
                    offres_brutes = rechercher_offres_completes(
                        "TOUS", departement_recruteur, max_pages=3,
                        mots_cles=nom_societe_recherche, secteur_activite=secteur_code_recherche,
                    )
                    # Filtre de précision côté client : motsCles peut remonter des offres
                    # dont le texte mentionne la société sans qu'elle soit l'employeur —
                    # on ne garde que celles où le nom de l'entreprise correspond vraiment.
                    terme = nom_societe_recherche.strip().lower()
                    st.session_state["recruteur_offres_entreprises"] = [
                        o for o in offres_brutes
                        if terme in ((o.get("entreprise", {}) or {}).get("nom") or "").strip().lower()
                    ]
                # Nouvelle recherche : les tables de sélection ci-dessous sont recréées
                # (clé incluant ce compteur), pour ne pas garder une sélection obsolète.
                st.session_state["recruteur_recherche_compteur"] += 1

        if "recruteur_offres_entreprises" in st.session_state:
            offres_disponibles = st.session_state["recruteur_offres_entreprises"]
            compteur_recherche = st.session_state["recruteur_recherche_compteur"]

            if not offres_disponibles:
                st.info("Aucune offre trouvée pour cette recherche dans ce département.")
            else:
                # --- Analyse par secteur : répartition des offres trouvées ---
                compteur_secteurs = Counter()
                for o in offres_disponibles:
                    libelle_secteur = o.get("secteurActiviteLibelle") or "Secteur non précisé"
                    compteur_secteurs[libelle_secteur] += 1
                df_secteurs = pd.DataFrame(
                    compteur_secteurs.items(), columns=["Secteur", "Nombre d'offres"]
                ).sort_values("Nombre d'offres", ascending=False).reset_index(drop=True)
                with st.expander("📊 Répartition des offres par secteur"):
                    st.dataframe(df_secteurs, use_container_width=True, hide_index=True)

                # --- Étape 1 : liste des sociétés + nombre d'offres — cliquer sur une ligne ---
                offres_par_entreprise = {}
                for o in offres_disponibles:
                    nom_entreprise = (o.get("entreprise", {}) or {}).get("nom") or "Entreprise non précisée"
                    offres_par_entreprise.setdefault(nom_entreprise, []).append(o)

                df_entreprises_compte = pd.DataFrame(
                    [
                        {"Société": nom, "Offres publiées": len(offres)}
                        for nom, offres in offres_par_entreprise.items()
                    ]
                ).sort_values("Offres publiées", ascending=False).reset_index(drop=True)

                st.caption("👇 Clique sur une société pour voir ses offres.")
                selection_entreprise = st.dataframe(
                    df_entreprises_compte,
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"table_entreprises_besoin_{compteur_recherche}",
                )

                lignes_entreprise_sel = selection_entreprise["selection"]["rows"]
                entreprise_choisie = (
                    df_entreprises_compte.iloc[lignes_entreprise_sel[0]]["Société"]
                    if lignes_entreprise_sel else None
                )

                # --- Étape 2 : sous-liste des offres de la société choisie — cliquer sur une ligne ---
                if entreprise_choisie:
                    offres_de_lentreprise = offres_par_entreprise[entreprise_choisie]
                    st.markdown(f"##### 📋 Offres chez {entreprise_choisie}")

                    df_offres_entreprise = pd.DataFrame([
                        {
                            "Intitulé": o.get("intitule", "(sans titre)"),
                            "Ville": (o.get("lieuTravail", {}) or {}).get("libelle", "—"),
                            "Type de contrat": o.get("typeContratLibelle") or o.get("typeContrat") or "—",
                        }
                        for o in offres_de_lentreprise
                    ])

                    st.caption("👇 Clique sur une offre pour voir la fiche de poste.")
                    selection_offre = st.dataframe(
                        df_offres_entreprise,
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"table_offres_besoin_{compteur_recherche}_{entreprise_choisie}",
                    )

                    lignes_offre_sel = selection_offre["selection"]["rows"]

                    # --- Étape 3 : fiche de poste + bouton de matching ---
                    if lignes_offre_sel:
                        offre_selectionnee = offres_de_lentreprise[lignes_offre_sel[0]]

                        st.markdown(f"##### 📄 Fiche de poste — {offre_selectionnee.get('intitule', '')}")
                        type_contrat = offre_selectionnee.get("typeContratLibelle") or offre_selectionnee.get("typeContrat")
                        if type_contrat:
                            st.markdown(f"**Type de contrat :** {type_contrat}")
                        salaire_offre = (offre_selectionnee.get("salaire", {}) or {}).get("libelle")
                        if salaire_offre:
                            st.markdown(f"**Salaire :** {salaire_offre}")
                        if offre_selectionnee.get("description"):
                            st.markdown("**Description :**")
                            st.write(offre_selectionnee["description"])
                        competences_offre = offre_selectionnee.get("competences", [])
                        if competences_offre:
                            libelles_comp = ", ".join(c.get("libelle", "") for c in competences_offre if c.get("libelle"))
                            if libelles_comp:
                                st.markdown(f"**Compétences demandées :** {libelles_comp}")

                        if st.button("🎯 Faire un matching pour cette offre", type="primary", key="btn_matching_offre"):
                            if not st.session_state["recruteur_profils"]:
                                st.warning(
                                    "Aucun profil candidat enregistré — ajoute-en dans l'onglet "
                                    "« 👥 Profils candidats » avant de lancer le matching."
                                )
                            else:
                                lignes_resultat = []
                                for profil in st.session_state["recruteur_profils"]:
                                    competences_liste = [c.strip() for c in profil.get("competences", "").split(",") if c.strip()]
                                    outils_liste = [c.strip() for c in profil.get("outils", "").split(",") if c.strip()]
                                    langages_liste = [c.strip() for c in profil.get("langages", "").split(",") if c.strip()]

                                    score, detail = calculer_correspondance_recruteur(
                                        offre_selectionnee,
                                        profil.get("poste_souhaite", ""),
                                        competences_liste, outils_liste, langages_liste,
                                        profil.get("secteur_souhaite", ""),
                                    )
                                    score_valeur = score if score is not None else 0
                                    lignes_resultat.append((
                                        score_valeur,
                                        {
                                            "Candidat": profil.get("nom") or "(sans nom)",
                                            "Score": f"{score}%" if score is not None else "N/C",
                                            **detail,
                                        },
                                    ))

                                lignes_resultat.sort(key=lambda x: x[0], reverse=True)
                                # On ne garde que les candidats avec un score strictement positif —
                                # un 0% (ou N/C compté comme 0) n'apporte rien à afficher.
                                lignes_pertinentes = [ligne for score_valeur, ligne in lignes_resultat if score_valeur > 0]

                                st.markdown(f"###### 🏆 Classement des candidats pour « {offre_selectionnee.get('intitule', '')} »")
                                if not lignes_pertinentes:
                                    st.info("Aucun profil ne correspond à cette offre.")
                                else:
                                    df_resultat_offre = pd.DataFrame(lignes_pertinentes)
                                    st.dataframe(df_resultat_offre, use_container_width=True, hide_index=True)
                                    st.caption(
                                        "Score pondéré sur 3 critères (poste 50% · compétences 30% · secteur 20%), "
                                        "calculé pour cette offre précise — pas une moyenne sur plusieurs offres."
                                    )

    st.divider()

# ===========================================================================
# ONGLET 2 — Poste ciblé : recherche d'un poste précis + comparaison globale
# ===========================================================================
with tab_poste_cible:
    st.markdown(
        "**Principe** : cible un poste précis (référentiel ROME), puis compare le score "
        "moyen de chaque profil candidat sur toutes les offres actuellement disponibles "
        "pour ce poste dans le département."
    )

    # -----------------------------------------------------------------
    # Poste ciblé
    # -----------------------------------------------------------------
    st.markdown("#### 🎯 Poste ciblé")

    poste_texte = st.text_input(
        "Intitulé du poste recherché par l'agence pour ses clients",
        key="recruteur_poste_texte",
        placeholder="ex: Chef de projet, Data Analyst...",
    )

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

    # -----------------------------------------------------------------
    # Comparaison globale — score moyen sur toutes les offres du poste ciblé.
    # -----------------------------------------------------------------
    st.markdown("#### 📊 Comparaison globale")
    if st.button("🚀 Comparer les profils sur ce poste", type="primary", key="btn_comparaison_globale"):
        if not poste_confirme_label:
            st.warning("Sélectionne d'abord un poste ciblé (section 🎯 ci-dessus).")
        elif not st.session_state["recruteur_profils"]:
            st.warning(
                "Aucun profil candidat enregistré — ajoute-en dans l'onglet "
                "« 👥 Profils candidats » avant de lancer la comparaison."
            )
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
                    offres_completes = rechercher_offres_completes(code_rome, departement_recruteur)

                    resultats_classement = []
                    for profil in st.session_state["recruteur_profils"]:
                        competences_liste = [c.strip() for c in profil.get("competences", "").split(",") if c.strip()]
                        outils_liste = [c.strip() for c in profil.get("outils", "").split(",") if c.strip()]
                        langages_liste = [c.strip() for c in profil.get("langages", "").split(",") if c.strip()]
                        poste_souhaite = profil.get("poste_souhaite", "")
                        secteur_souhaite = profil.get("secteur_souhaite", "")

                        scores = []
                        for offre in offres_completes:
                            score, _ = calculer_correspondance_recruteur(
                                offre, poste_souhaite, competences_liste, outils_liste, langages_liste, secteur_souhaite
                            )
                            if score is not None:
                                scores.append(score)

                        score_moyen = round(sum(scores) / len(scores)) if scores else None
                        score_moyen_valeur = score_moyen if score_moyen is not None else 0
                        resultats_classement.append((
                            score_moyen_valeur,
                            {
                                "Candidat": profil.get("nom") or "(sans nom)",
                                "Poste recherché": poste_souhaite or "—",
                                "Score moyen de correspondance": f"{score_moyen}%" if score_moyen is not None else "N/C",
                                "Offres analysées": len(offres_completes),
                            },
                        ))

                st.markdown(f"##### 📊 Classement — {total_region} offre(s) trouvée(s) dans le département {departement_recruteur}")
                if not offres_completes:
                    st.info("Aucune offre trouvée pour ce poste/département — comparaison non calculable.")
                else:
                    # On ne garde que les candidats avec un score moyen strictement positif.
                    resultats_pertinents = [ligne for score_valeur, ligne in resultats_classement if score_valeur > 0]
                    if not resultats_pertinents:
                        st.info("Aucun profil ne correspond à ce poste.")
                    else:
                        df_classement = pd.DataFrame(resultats_pertinents)
                        st.dataframe(df_classement, use_container_width=True, hide_index=True)
                        st.caption(
                            "Score pondéré sur 3 critères : intitulé du poste souhaité (50%), "
                            "compétences/outils/langages déclarés (30%), secteur d'activité souhaité "
                            "(20%) — une dimension sans donnée à comparer est retirée du calcul et le "
                            "poids des autres est réajusté en conséquence."
                        )

# ===========================================================================
# ONGLET 3 — Profils candidats : gestion dédiée (ajout, import, édition, suppression)
# ===========================================================================
with tab_profils:
    st.markdown("#### 👥 Profils candidats")

    if db.base_disponible():
        st.caption("✅ Profils enregistrés de façon persistante (base PostgreSQL).")
    else:
        st.warning(
            "⚠️ DATABASE_URL non configurée — les profils ajoutés ici seront perdus à la "
            "fermeture de la session. Ajoute ce secret pour activer la persistance."
        )

    # --- Import Excel/CSV (import de données internes du client — version simple) ---
    with st.expander("📥 Importer plusieurs profils depuis un fichier Excel/CSV"):
        st.caption(
            "Colonnes attendues : **Nom**, **Poste souhaité**, **Compétences**, **Outils**, "
            "**Langages** — plusieurs valeurs par cellule séparées par une virgule. Le secteur "
            "souhaité se choisit ensuite manuellement sur chaque profil importé. Télécharge le "
            "modèle si besoin."
        )

        modele = pd.DataFrame([
            {
                "Nom": "Jean Dupont",
                "Poste souhaité": "Chef de projet IT",
                "Compétences": "Gestion de projet, Communication",
                "Outils": "Excel, SAP",
                "Langages": "SQL, Python",
            }
        ])
        buffer_modele = BytesIO()
        modele.to_excel(buffer_modele, index=False, sheet_name="Profils")
        st.download_button(
            "⬇️ Télécharger le modèle Excel",
            data=buffer_modele.getvalue(),
            file_name="modele_import_profils.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        fichier_importe = st.file_uploader(
            "Fichier à importer (.xlsx ou .csv)", type=["xlsx", "csv"], key="recruteur_import_fichier"
        )
        if fichier_importe and st.button("Importer les profils de ce fichier", key="recruteur_btn_import"):
            try:
                if fichier_importe.name.endswith(".csv"):
                    df_import = pd.read_csv(fichier_importe)
                else:
                    df_import = pd.read_excel(fichier_importe)

                # Correspondance des colonnes insensible à la casse/aux accents simples
                colonnes_normalisees = {c.strip().lower(): c for c in df_import.columns}
                correspondances = {
                    "nom": ["nom", "candidat", "name"],
                    "poste_souhaite": ["poste souhaité", "poste recherché", "poste", "job title"],
                    "competences": ["compétences", "competences", "skills"],
                    "outils": ["outils", "outils informatiques", "tools"],
                    "langages": ["langages", "langages informatiques", "languages"],
                }

                def _colonne(cle):
                    for variante in correspondances[cle]:
                        if variante in colonnes_normalisees:
                            return colonnes_normalisees[variante]
                    return None

                col_nom = _colonne("nom")
                col_poste = _colonne("poste_souhaite")
                col_comp = _colonne("competences")
                col_outils = _colonne("outils")
                col_langages = _colonne("langages")

                profils_importes = []
                for _, ligne in df_import.iterrows():
                    profils_importes.append({
                        "nom": str(ligne[col_nom]) if col_nom and pd.notna(ligne[col_nom]) else "",
                        "poste_souhaite": str(ligne[col_poste]) if col_poste and pd.notna(ligne[col_poste]) else "",
                        "competences": str(ligne[col_comp]) if col_comp and pd.notna(ligne[col_comp]) else "",
                        "outils": str(ligne[col_outils]) if col_outils and pd.notna(ligne[col_outils]) else "",
                        "langages": str(ligne[col_langages]) if col_langages and pd.notna(ligne[col_langages]) else "",
                        "secteur_souhaite": "",
                    })

                if db.base_disponible():
                    db.ajouter_profils_en_masse(profils_importes)
                    st.session_state["recruteur_profils"] = db.charger_profils()
                else:
                    st.session_state["recruteur_profils"].extend(profils_importes)

                st.success(f"{len(profils_importes)} profil(s) importé(s) avec succès.")
                st.rerun()
            except Exception as e:
                st.error(f"Impossible de lire ce fichier : {e}")

    a_supprimer = None
    for i, profil in enumerate(st.session_state["recruteur_profils"]):
        with st.container(border=True):
            c1, c2 = st.columns(2)
            profil["nom"] = c1.text_input("Nom / repère candidat", value=profil.get("nom", ""), key=f"rec_nom_{i}")
            profil["poste_souhaite"] = c2.text_input(
                "Poste recherché par ce candidat", value=profil.get("poste_souhaite", ""), key=f"rec_poste_{i}",
                placeholder="ex: Chef de projet IT",
            )
            c3, c4 = st.columns(2)
            profil["competences"] = c3.text_input(
                "Compétences (séparées par une virgule)", value=profil.get("competences", ""), key=f"rec_comp_{i}"
            )
            secteur_valeur_actuelle = profil.get("secteur_souhaite", "")
            libelles_secteurs = list(options_secteurs_recruteur.keys())
            index_secteur = 0
            for idx, libelle in enumerate(libelles_secteurs):
                if options_secteurs_recruteur[libelle] == secteur_valeur_actuelle:
                    index_secteur = idx
                    break
            secteur_choisi = c4.selectbox(
                "Secteur souhaité", libelles_secteurs, index=index_secteur, key=f"rec_secteur_{i}"
            )
            profil["secteur_souhaite"] = options_secteurs_recruteur[secteur_choisi]
            c5, c6 = st.columns(2)
            profil["outils"] = c5.text_input(
                "Outils (séparés par une virgule)", value=profil.get("outils", ""), key=f"rec_outils_{i}"
            )
            profil["langages"] = c6.text_input(
                "Langages informatiques (séparés par une virgule)", value=profil.get("langages", ""), key=f"rec_lang_{i}"
            )
            c7, c8 = st.columns(2)
            if db.base_disponible() and c7.button("💾 Enregistrer", key=f"rec_save_{i}"):
                if profil.get("id") is None:
                    profil["id"] = db.ajouter_profil(
                        profil.get("nom", ""), profil.get("competences", ""),
                        profil.get("outils", ""), profil.get("langages", ""),
                        profil.get("poste_souhaite", ""), profil.get("secteur_souhaite", ""),
                    )
                else:
                    db.mettre_a_jour_profil(
                        profil["id"], profil.get("nom", ""), profil.get("competences", ""),
                        profil.get("outils", ""), profil.get("langages", ""),
                        profil.get("poste_souhaite", ""), profil.get("secteur_souhaite", ""),
                    )
                st.toast(f"Profil « {profil.get('nom') or 'sans nom'} » enregistré.")
            if c8.button("🗑️ Retirer ce profil", key=f"rec_suppr_{i}"):
                a_supprimer = i

    if a_supprimer is not None:
        profil_vise = st.session_state["recruteur_profils"][a_supprimer]
        if db.base_disponible() and profil_vise.get("id") is not None:
            db.supprimer_profil(profil_vise["id"])
        st.session_state["recruteur_profils"].pop(a_supprimer)
        st.rerun()

    if st.button("➕ Ajouter un profil candidat", key="btn_ajouter_profil"):
        nouveau_profil = {}
        if db.base_disponible():
            nouveau_profil["id"] = db.ajouter_profil()
        st.session_state["recruteur_profils"].append(nouveau_profil)
        st.rerun()
