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
  1. Onglet "🏢 Besoin des entreprises" — le secteur d'activité est affiché
     en premier (souvent identifiable même sans connaître le nom exact de
     la société), avec le nom de société en filtre optionnel en dessous
     (laissé vide = tout le secteur). Le résultat est une liste de sociétés
     avec leur nombre d'offres publiées, une répartition par secteur avec
     drill-down (secteur → postes → offres), les postes les plus recherchés
     et les top recruteurs. Cliquer sur une société ouvre la sous-liste de
     ses offres ; cliquer sur une offre affiche sa fiche de poste, un
     bouton pour lancer le matching, puis pour présenter un ou plusieurs
     candidats à cette offre (suivi dans l'onglet "Candidature envoyée").
  2. Onglet "📊 Vivier de talents" — recherche d'un poste précis (référentiel
     ROME + suggestions) et comparaison globale : score moyen des profils
     candidats sur toutes les offres disponibles pour ce poste, avec
     filtre secteur et vue "tous les postes" recherchés par nos candidats.
  3. Onglet "📤 Candidature envoyée" — suivi de qui a été présenté à quelle
     offre, avec statut (Candidature envoyée / En cours / Clôturée -
     retenue / Clôturée - non retenue).
  4. Onglet "🤝 Comptes actifs" — sociétés où l'on a au moins une candidature
     "En cours" ou "Clôturée - retenue" : vue calculée dynamiquement sur le
     suivi des candidatures, pour repérer où l'on peut essayer de placer
     davantage de candidats.
  5. Onglet "📥 Import & Profils" — gestion dédiée des profils (ajout
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
    rechercher_offres_completes,
    calculer_correspondance_offre,
    calculer_correspondance_recruteur,
    get_secteurs_activite,
)
import stockage_recruteur as db


def afficher_fiche_offre_et_matching(offre, entreprise_nom, key_suffix):
    """
    Affiche la fiche de poste d'une offre, un bouton pour lancer le matching
    contre les profils candidats, le classement obtenu (persistant en session
    via key_suffix, pour survivre au rerun du bouton "Enregistrer la
    présentation") et la présentation d'un ou plusieurs candidats à cette
    offre (avec suivi dans la table candidatures). Réutilisée par les deux
    parcours de découverte d'offres : société -> offres, et
    secteur -> poste -> offres.
    """
    st.markdown(f"##### 📄 Fiche de poste — {offre.get('intitule', '')}")
    type_contrat = offre.get("typeContratLibelle") or offre.get("typeContrat")
    if type_contrat:
        st.markdown(f"**Type de contrat :** {type_contrat}")
    salaire_offre = (offre.get("salaire", {}) or {}).get("libelle")
    if salaire_offre:
        st.markdown(f"**Salaire :** {salaire_offre}")
    if offre.get("description"):
        st.markdown("**Description :**")
        st.write(offre["description"])
    competences_offre = offre.get("competences", [])
    if competences_offre:
        libelles_comp = ", ".join(c.get("libelle", "") for c in competences_offre if c.get("libelle"))
        if libelles_comp:
            st.markdown(f"**Compétences demandées :** {libelles_comp}")

    offre_id = offre.get("id") or f"{offre.get('intitule', '')}_{entreprise_nom}"
    cle_matching = f"recruteur_dernier_matching_{key_suffix}"

    if st.button("🎯 Faire un matching pour cette offre", type="primary", key=f"btn_matching_{key_suffix}"):
        if not st.session_state["recruteur_profils"]:
            st.warning(
                "Aucun profil candidat enregistré — ajoute-en dans l'onglet "
                "« 📥 Import & Profils » avant de lancer le matching."
            )
        else:
            lignes_resultat = []
            for profil in st.session_state["recruteur_profils"]:
                competences_liste = [c.strip() for c in profil.get("competences", "").split(",") if c.strip()]
                outils_liste = [c.strip() for c in profil.get("outils", "").split(",") if c.strip()]
                langages_liste = [c.strip() for c in profil.get("langages", "").split(",") if c.strip()]

                score, detail = calculer_correspondance_recruteur(
                    offre, profil.get("poste_souhaite", ""),
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

            st.session_state[cle_matching] = {
                "offre_id": offre_id,
                "offre_intitule": offre.get("intitule", ""),
                "entreprise_nom": entreprise_nom,
                "lignes": lignes_pertinentes,
            }

    # --- Affichage du dernier matching (persiste hors du clic du bouton) ---
    dernier_matching = st.session_state.get(cle_matching)
    if dernier_matching and dernier_matching["offre_id"] == offre_id:
        st.markdown(f"###### 🏆 Classement des candidats pour « {dernier_matching['offre_intitule']} »")
        if not dernier_matching["lignes"]:
            st.info("Aucun profil ne correspond à cette offre.")
        else:
            df_resultat_offre = pd.DataFrame(dernier_matching["lignes"])
            st.dataframe(df_resultat_offre, use_container_width=True, hide_index=True)
            st.caption(
                "Score pondéré sur 3 critères (poste 50% · compétences 30% · secteur 20%), "
                "calculé pour cette offre précise — pas une moyenne sur plusieurs offres."
            )

            # --- Présentation d'un ou plusieurs candidats à cette offre ---
            noms_candidats_pertinents = [l["Candidat"] for l in dernier_matching["lignes"]]
            liens_cv_candidats = {
                p.get("nom") or "(sans nom)": p.get("cv_lien", "")
                for p in st.session_state["recruteur_profils"]
            }
            liens_cv_a_afficher = [
                (nom, liens_cv_candidats.get(nom, "")) for nom in noms_candidats_pertinents
                if liens_cv_candidats.get(nom, "").strip()
            ]
            if liens_cv_a_afficher:
                with st.expander("📄 CV des candidats pertinents"):
                    for nom, lien in liens_cv_a_afficher:
                        st.link_button(f"📄 {nom}", lien.strip())

            candidats_a_presenter = st.multiselect(
                "Candidat(s) à présenter pour cette offre",
                options=noms_candidats_pertinents,
                key=f"recruteur_candidats_a_presenter_{key_suffix}",
            )
            if st.button("📤 Enregistrer la présentation", key=f"btn_enregistrer_presentation_{key_suffix}"):
                if not candidats_a_presenter:
                    st.warning("Sélectionne au moins un candidat.")
                else:
                    nb_ajoutes, nb_deja_presentes = 0, 0
                    for nom_candidat in candidats_a_presenter:
                        profil_correspondant = next(
                            (
                                p for p in st.session_state["recruteur_profils"]
                                if (p.get("nom") or "(sans nom)") == nom_candidat
                            ),
                            None,
                        )
                        candidat_id = profil_correspondant.get("id") if profil_correspondant else None
                        poste_souhaite_candidat = (
                            profil_correspondant.get("poste_souhaite", "") if profil_correspondant else ""
                        )
                        cv_lien_candidat = (
                            profil_correspondant.get("cv_lien", "") if profil_correspondant else ""
                        )

                        if db.base_disponible():
                            if db.candidature_existe(candidat_id, nom_candidat, dernier_matching["offre_id"]):
                                nb_deja_presentes += 1
                                continue
                            nouvel_id = db.ajouter_candidature(
                                candidat_id, nom_candidat, poste_souhaite_candidat,
                                dernier_matching["offre_id"], dernier_matching["offre_intitule"],
                                dernier_matching["entreprise_nom"], candidat_cv_lien=cv_lien_candidat,
                            )
                            st.session_state["recruteur_candidatures"].insert(0, {
                                "id": nouvel_id,
                                "candidat_id": candidat_id,
                                "candidat_nom": nom_candidat,
                                "candidat_poste_souhaite": poste_souhaite_candidat,
                                "candidat_cv_lien": cv_lien_candidat,
                                "offre_id": dernier_matching["offre_id"],
                                "offre_intitule": dernier_matching["offre_intitule"],
                                "entreprise_nom": dernier_matching["entreprise_nom"],
                                "statut": db.STATUTS_CANDIDATURE[0],
                            })
                        else:
                            deja_presente = any(
                                c.get("candidat_nom") == nom_candidat
                                and c.get("offre_id") == dernier_matching["offre_id"]
                                for c in st.session_state["recruteur_candidatures"]
                            )
                            if deja_presente:
                                nb_deja_presentes += 1
                                continue
                            st.session_state["recruteur_candidatures"].insert(0, {
                                "id": None,
                                "candidat_id": candidat_id,
                                "candidat_nom": nom_candidat,
                                "candidat_poste_souhaite": poste_souhaite_candidat,
                                "candidat_cv_lien": cv_lien_candidat,
                                "offre_id": dernier_matching["offre_id"],
                                "offre_intitule": dernier_matching["offre_intitule"],
                                "entreprise_nom": dernier_matching["entreprise_nom"],
                                "statut": db.STATUTS_CANDIDATURE[0],
                            })
                        nb_ajoutes += 1

                    if nb_ajoutes:
                        st.success(
                            f"{nb_ajoutes} candidature(s) enregistrée(s) — à suivre dans l'onglet "
                            "« 📤 Candidature envoyée »."
                        )
                    if nb_deja_presentes:
                        st.info(
                            f"{nb_deja_presentes} candidat(s) déjà présenté(s) à cette offre, non dupliqué(s)."
                        )


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
# Profils candidats + suivi des candidatures : chargement en session
# (nécessaire dans plusieurs onglets, donc initialisé ici, avant la
# répartition en onglets).
# ---------------------------------------------------------------------------
db.initialiser_table()
db.initialiser_table_candidatures()

if "recruteur_profils" not in st.session_state:
    st.session_state["recruteur_profils"] = db.charger_profils() if db.base_disponible() else []

if "recruteur_candidatures" not in st.session_state:
    st.session_state["recruteur_candidatures"] = db.charger_candidatures() if db.base_disponible() else []

if "recruteur_recherche_compteur" not in st.session_state:
    st.session_state["recruteur_recherche_compteur"] = 0

# Département : commun aux onglets "Besoin des entreprises" et "Vivier de
# talents" (comparaison globale) — un seul champ, affiché avant les onglets.
departement_recruteur = st.text_input("Département", value="13", key="recruteur_departement")

tab_besoin_entreprises, tab_poste_cible, tab_comptes_actifs, tab_candidatures, tab_profils = st.tabs(
    ["🏢 Besoin des entreprises", "📊 Vivier de talents", "🤝 Comptes actifs", "📤 Candidature envoyée", "📥 Import & Profils"]
)

# ===========================================================================
# ONGLET 1 — Besoin des entreprises : société -> offres -> fiche de poste -> matching
# ===========================================================================
with tab_besoin_entreprises:
    st.markdown(
        "**Principe** : recherche la société qui recrute (ou affiche tous les besoins), "
        "explore ses offres jusqu'à la fiche de poste, puis lance le matching contre ta "
        "base de profils candidats (gérée dans l'onglet « Import & Profils »)."
    )

    # -----------------------------------------------------------------
    # Secteur d'activité affiché en premier — souvent identifiable même
    # sans connaître le nom de la société (via le poste ou le marché visé).
    # -----------------------------------------------------------------
    libelles_secteurs_recherche = list(options_secteurs_recruteur.keys())
    secteur_choisi_recherche = st.selectbox(
        "Secteur d'activité",
        libelles_secteurs_recherche,
        key="recruteur_secteur_recherche",
    )
    secteur_code_recherche = options_secteurs_recruteur[secteur_choisi_recherche]

    nom_societe_recherche = st.text_input(
        "Nom de la société (optionnel — laisse vide pour voir tout le secteur)",
        key="recruteur_nom_societe",
        placeholder="ex: Airbus Helicopters, BNP Paribas...",
    )

    if st.button("🔍 Rechercher", key="btn_charger_entreprises", type="primary"):
        with st.spinner("Recherche des offres..."):
            if nom_societe_recherche.strip():
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
            else:
                st.session_state["recruteur_offres_entreprises"] = rechercher_offres_completes(
                    "TOUS", departement_recruteur, max_pages=5, secteur_activite=secteur_code_recherche
                )
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
                st.caption("👇 Clique sur un secteur pour voir les postes recherchés dans ce secteur.")
                selection_secteur = st.dataframe(
                    df_secteurs,
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"table_secteurs_{compteur_recherche}",
                )
                lignes_secteur_sel = selection_secteur["selection"]["rows"]
                secteur_choisi_analyse = (
                    df_secteurs.iloc[lignes_secteur_sel[0]]["Secteur"] if lignes_secteur_sel else None
                )

                if secteur_choisi_analyse:
                    offres_du_secteur = [
                        o for o in offres_disponibles
                        if (o.get("secteurActiviteLibelle") or "Secteur non précisé") == secteur_choisi_analyse
                    ]

                    compteur_postes_secteur = Counter()
                    for o in offres_du_secteur:
                        intitule = (o.get("intitule") or "").strip()
                        if intitule:
                            compteur_postes_secteur[intitule] += 1
                    df_postes_secteur = pd.DataFrame(
                        compteur_postes_secteur.most_common(), columns=["Poste", "Nombre d'offres"]
                    )

                    st.markdown(f"###### 🧑‍💼 Postes recherchés — {secteur_choisi_analyse}")
                    st.caption("👇 Clique sur un poste pour voir ses offres.")
                    selection_poste_secteur = st.dataframe(
                        df_postes_secteur,
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"table_postes_secteur_{compteur_recherche}_{secteur_choisi_analyse}",
                    )
                    lignes_poste_secteur_sel = selection_poste_secteur["selection"]["rows"]
                    poste_choisi_analyse = (
                        df_postes_secteur.iloc[lignes_poste_secteur_sel[0]]["Poste"]
                        if lignes_poste_secteur_sel else None
                    )

                    if poste_choisi_analyse:
                        offres_du_poste_secteur = [
                            o for o in offres_du_secteur
                            if (o.get("intitule") or "").strip() == poste_choisi_analyse
                        ]

                        st.markdown(f"###### 📋 Offres — {poste_choisi_analyse} ({secteur_choisi_analyse})")
                        df_offres_poste_secteur = pd.DataFrame([
                            {
                                "Société": (o.get("entreprise", {}) or {}).get("nom") or "Entreprise non précisée",
                                "Ville": (o.get("lieuTravail", {}) or {}).get("libelle", "—"),
                                "Type de contrat": o.get("typeContratLibelle") or o.get("typeContrat") or "—",
                            }
                            for o in offres_du_poste_secteur
                        ])
                        st.caption("👇 Clique sur une offre pour voir la fiche de poste.")
                        selection_offre_secteur = st.dataframe(
                            df_offres_poste_secteur,
                            use_container_width=True,
                            hide_index=True,
                            on_select="rerun",
                            selection_mode="single-row",
                            key=f"table_offres_secteur_{compteur_recherche}_{secteur_choisi_analyse}_{poste_choisi_analyse}",
                        )
                        lignes_offre_secteur_sel = selection_offre_secteur["selection"]["rows"]

                        if lignes_offre_secteur_sel:
                            offre_secteur_selectionnee = offres_du_poste_secteur[lignes_offre_secteur_sel[0]]
                            entreprise_offre_secteur = (
                                (offre_secteur_selectionnee.get("entreprise", {}) or {}).get("nom")
                                or "Entreprise non précisée"
                            )
                            afficher_fiche_offre_et_matching(
                                offre_secteur_selectionnee, entreprise_offre_secteur,
                                key_suffix=f"secteur_{compteur_recherche}",
                            )

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

            # --- Analyse : postes les plus recherchés + top recruteurs ---
            st.markdown("##### 🏆 Top recruteurs")
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
                    afficher_fiche_offre_et_matching(
                        offre_selectionnee, entreprise_choisie, key_suffix=f"entreprise_{compteur_recherche}"
                    )

            st.divider()

            # --- Postes les plus recherchés : s'adapte à la recherche en cours
            # (secteur et/ou société), calculé sur les offres trouvées ci-dessus. ---
            compteur_postes_recherche = Counter()
            for o in offres_disponibles:
                intitule = (o.get("intitule") or "").strip()
                if intitule:
                    compteur_postes_recherche[intitule] += 1
            df_postes_recherche = pd.DataFrame(
                compteur_postes_recherche.most_common(15), columns=["Poste", "Nombre d'offres"]
            )
            with st.expander("🏆 Postes les plus recherchés"):
                st.dataframe(df_postes_recherche, use_container_width=True, hide_index=True)

    st.divider()

# ===========================================================================
# ONGLET 2 — Vivier de talents : recherche d'un poste précis + comparaison globale
# ===========================================================================
with tab_poste_cible:
    st.markdown(
        "**Principe** : cible un poste précis (référentiel ROME), puis compare le score "
        "moyen de chaque profil candidat sur toutes les offres actuellement disponibles "
        "pour ce poste dans le département."
    )

    # -----------------------------------------------------------------
    # Filtre secteur — s'applique aux profils du vivier pris en compte
    # plus bas (tableau "Tous les postes" et comparaison globale).
    # -----------------------------------------------------------------
    libelles_secteurs_vivier = list(options_secteurs_recruteur.keys())
    secteur_choisi_vivier = st.selectbox(
        "Filtrer le vivier par secteur souhaité (optionnel)",
        libelles_secteurs_vivier,
        key="recruteur_secteur_vivier",
    )
    secteur_code_vivier = options_secteurs_recruteur[secteur_choisi_vivier]

    profils_vivier = st.session_state["recruteur_profils"]
    if secteur_code_vivier:
        profils_vivier = [p for p in profils_vivier if p.get("secteur_souhaite") == secteur_code_vivier]

    # -----------------------------------------------------------------
    # Poste ciblé
    # -----------------------------------------------------------------
    st.markdown("#### 🎯 Poste ciblé")

    tous_les_postes = st.checkbox(
        "🔘 Tous les postes — afficher la répartition des postes recherchés par nos candidats",
        key="recruteur_tous_les_postes",
    )

    poste_texte = st.text_input(
        "Intitulé du poste recherché par l'agence pour ses clients",
        key="recruteur_poste_texte",
        placeholder="ex: Chef de projet, Data Analyst...",
        disabled=tous_les_postes,
    )

    poste_confirme_label = None

    if tous_les_postes:
        compteur_postes_candidats = Counter()
        for p in profils_vivier:
            poste = (p.get("poste_souhaite") or "").strip()
            compteur_postes_candidats[poste or "(non renseigné)"] += 1

        st.markdown(f"##### 📋 Postes recherchés par nos candidats ({len(profils_vivier)} profil(s))")
        if not profils_vivier:
            st.info("Aucun profil candidat ne correspond à ce filtre.")
        else:
            df_postes_candidats = pd.DataFrame(
                compteur_postes_candidats.most_common(), columns=["Poste recherché", "Nombre de candidats"]
            )
            st.dataframe(df_postes_candidats, use_container_width=True, hide_index=True)
    else:
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
        elif not profils_vivier:
            st.warning(
                "Aucun profil candidat ne correspond au filtre secteur actuel — ajuste le filtre "
                "ou ajoute des profils dans l'onglet « 📥 Import & Profils »."
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
                    offres_completes = rechercher_offres_completes(code_rome, departement_recruteur)

                    resultats_classement = []
                    for profil in profils_vivier:
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

                st.markdown("##### 📊 Classement des profils candidats")
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
# ONGLET 3 — Candidature envoyée : suivi de qui a été présenté à quelle
# offre, et statut de chaque candidature. Alimenté depuis le bouton
# "📤 Enregistrer la présentation" dans l'onglet "Besoin des entreprises".
# ===========================================================================
with tab_candidatures:
    st.markdown("#### 📤 Candidature envoyée")
    st.caption(
        "Qui a été présenté à quelle offre, avec le poste qu'il recherche et où en est "
        "chaque candidature."
    )

    if db.base_disponible():
        st.caption("✅ Suivi enregistré de façon persistante (base PostgreSQL).")
    else:
        st.warning(
            "⚠️ DATABASE_URL non configurée — le suivi ajouté ici sera perdu à la fermeture "
            "de la session."
        )

    if not st.session_state["recruteur_candidatures"]:
        st.info(
            "Aucune candidature enregistrée pour l'instant — présente un candidat depuis "
            "l'onglet « 🏢 Besoin des entreprises » après un matching sur une offre."
        )
    else:
        a_supprimer_candidature = None
        for i, candidature in enumerate(st.session_state["recruteur_candidatures"]):
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 3, 2])
                c1.markdown(
                    f"**{candidature.get('candidat_nom') or '(sans nom)'}**  \n"
                    f"🎯 {candidature.get('candidat_poste_souhaite') or '—'}"
                )
                c2.markdown(
                    f"{candidature.get('offre_intitule') or '(offre sans titre)'}  \n"
                    f"🏢 {candidature.get('entreprise_nom') or '—'}"
                )

                statuts = db.STATUTS_CANDIDATURE
                statut_actuel = candidature.get("statut") or statuts[0]
                index_statut = statuts.index(statut_actuel) if statut_actuel in statuts else 0
                nouveau_statut = c3.selectbox(
                    "Statut", statuts, index=index_statut, key=f"cand_statut_{i}"
                )

                c4, c5, c6 = st.columns(3)
                if c4.button("💾 Mettre à jour", key=f"cand_save_{i}"):
                    candidature["statut"] = nouveau_statut
                    if db.base_disponible() and candidature.get("id") is not None:
                        db.mettre_a_jour_statut_candidature(candidature["id"], nouveau_statut)
                    st.toast("Statut mis à jour.")
                if candidature.get("candidat_cv_lien", "").strip():
                    c5.link_button("📄 Voir le CV", candidature["candidat_cv_lien"].strip())
                if c6.button("🗑️ Retirer", key=f"cand_suppr_{i}"):
                    a_supprimer_candidature = i

        if a_supprimer_candidature is not None:
            candidature_visee = st.session_state["recruteur_candidatures"][a_supprimer_candidature]
            if db.base_disponible() and candidature_visee.get("id") is not None:
                db.supprimer_candidature(candidature_visee["id"])
            st.session_state["recruteur_candidatures"].pop(a_supprimer_candidature)
            st.rerun()

# ===========================================================================
# ONGLET 4 — Comptes actifs : sociétés où l'on a au moins une candidature
# "En cours" ou "Clôturée - retenue". Vue calculée dynamiquement sur le
# suivi des candidatures (pas de donnée propre à stocker) — une candidature
# qui passe en "Clôturée - non retenue" ne compte plus, et la société sort
# de la liste si elle n'a plus aucune candidature active.
# ===========================================================================
with tab_comptes_actifs:
    st.markdown("#### 🤝 Comptes actifs")
    st.caption(
        "Sociétés où l'on a déjà des candidats en cours ou placés — pour repérer où "
        "essayer d'en présenter d'autres."
    )

    STATUTS_COMPTE_ACTIF = ("En cours", "Clôturée - retenue")
    candidatures_actives = [
        c for c in st.session_state["recruteur_candidatures"]
        if c.get("statut") in STATUTS_COMPTE_ACTIF
    ]

    if not candidatures_actives:
        st.info(
            "Aucun compte actif pour l'instant — une société apparaît ici dès qu'une "
            "candidature y est « En cours » ou « Clôturée - retenue »."
        )
    else:
        candidatures_par_entreprise = {}
        for c in candidatures_actives:
            nom_entreprise = c.get("entreprise_nom") or "Entreprise non précisée"
            candidatures_par_entreprise.setdefault(nom_entreprise, []).append(c)

        df_comptes_actifs = pd.DataFrame(
            [
                {"Société": nom, "Candidat(s) actif(s)": len(liste)}
                for nom, liste in candidatures_par_entreprise.items()
            ]
        ).sort_values("Candidat(s) actif(s)", ascending=False).reset_index(drop=True)

        st.caption("👇 Clique sur une société pour voir le détail de ses candidatures actives.")
        selection_compte = st.dataframe(
            df_comptes_actifs,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="table_comptes_actifs",
        )
        lignes_compte_sel = selection_compte["selection"]["rows"]
        entreprise_compte_choisie = (
            df_comptes_actifs.iloc[lignes_compte_sel[0]]["Société"] if lignes_compte_sel else None
        )

        if entreprise_compte_choisie:
            st.markdown(f"##### 📋 Candidatures actives chez {entreprise_compte_choisie}")
            df_detail_compte = pd.DataFrame([
                {
                    "Candidat": c.get("candidat_nom") or "(sans nom)",
                    "Poste recherché": c.get("candidat_poste_souhaite") or "—",
                    "Offre": c.get("offre_intitule") or "—",
                    "Statut": c.get("statut") or "—",
                }
                for c in candidatures_par_entreprise[entreprise_compte_choisie]
            ])
            st.dataframe(df_detail_compte, use_container_width=True, hide_index=True)

# ===========================================================================
# ONGLET 5 — Import & Profils : gestion dédiée (ajout, import, édition, suppression)
# ===========================================================================
with tab_profils:
    st.markdown("#### 📥 Import & Profils")

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
            "**Langages** (informatiques), **Langues parlées**, **Secteur souhaité**, "
            "**Mobilité**, **Lien CV** — plusieurs valeurs par cellule séparées par une "
            "virgule (sauf Lien CV et Mobilité). Le lien CV pointe vers le fichier déjà "
            "stocké sur votre Drive/SharePoint — pas d'upload de fichier ici. Le secteur "
            "souhaité est rapproché automatiquement du référentiel officiel (libellé "
            "approchant) ; s'il n'est pas reconnu, il reste à choisir manuellement sur le "
            "profil importé. Télécharge le modèle si besoin."
        )

        modele = pd.DataFrame([
            {
                "Nom": "Jean Dupont",
                "Poste souhaité": "Chef de projet IT",
                "Compétences": "Gestion de projet, Communication",
                "Outils": "Excel, SAP",
                "Langages": "SQL, Python",
                "Langues parlées": "Anglais courant",
                "Secteur souhaité": "Conseil en systèmes et logiciels informatiques",
                "Mobilité": "Paris",
                "Lien CV": "https://drive.google.com/...",
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
                    "langues_parlees": ["langues parlées", "langues parlees", "langues", "spoken languages"],
                    "secteur_souhaite": ["secteur souhaité", "secteur souhaite", "secteur d'activité", "secteur"],
                    "mobilite": ["mobilité", "mobilite", "ville", "localisation"],
                    "cv_lien": ["lien cv", "cv", "lien du cv", "cv link", "url cv"],
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
                col_langues = _colonne("langues_parlees")
                col_secteur = _colonne("secteur_souhaite")
                col_mobilite = _colonne("mobilite")
                col_cv = _colonne("cv_lien")

                # Rapprochement du secteur importé (libellé texte) avec le référentiel
                # officiel (déjà chargé pour le sélecteur secteur) — recherche exacte
                # puis, à défaut, sous-chaîne dans un sens ou dans l'autre.
                secteur_libelle_vers_code = {}
                for libelle_avec_code, code in options_secteurs_recruteur.items():
                    if not code:
                        continue
                    libelle_seul = libelle_avec_code.rsplit(" (", 1)[0].strip().lower()
                    secteur_libelle_vers_code[libelle_seul] = code

                def _resoudre_secteur(texte_secteur):
                    if not texte_secteur:
                        return ""
                    texte_normalise = texte_secteur.strip().lower()
                    if texte_normalise in secteur_libelle_vers_code:
                        return secteur_libelle_vers_code[texte_normalise]
                    for libelle_seul, code in secteur_libelle_vers_code.items():
                        if texte_normalise in libelle_seul or libelle_seul in texte_normalise:
                            return code
                    return ""

                profils_importes = []
                nb_secteurs_non_reconnus = 0
                for _, ligne in df_import.iterrows():
                    texte_secteur_brut = str(ligne[col_secteur]).strip() if col_secteur and pd.notna(ligne[col_secteur]) else ""
                    code_secteur_resolu = _resoudre_secteur(texte_secteur_brut)
                    if texte_secteur_brut and not code_secteur_resolu:
                        nb_secteurs_non_reconnus += 1

                    profils_importes.append({
                        "nom": str(ligne[col_nom]) if col_nom and pd.notna(ligne[col_nom]) else "",
                        "poste_souhaite": str(ligne[col_poste]) if col_poste and pd.notna(ligne[col_poste]) else "",
                        "competences": str(ligne[col_comp]) if col_comp and pd.notna(ligne[col_comp]) else "",
                        "outils": str(ligne[col_outils]) if col_outils and pd.notna(ligne[col_outils]) else "",
                        "langages": str(ligne[col_langages]) if col_langages and pd.notna(ligne[col_langages]) else "",
                        "langues_parlees": str(ligne[col_langues]) if col_langues and pd.notna(ligne[col_langues]) else "",
                        "mobilite": str(ligne[col_mobilite]).strip() if col_mobilite and pd.notna(ligne[col_mobilite]) else "",
                        "cv_lien": str(ligne[col_cv]).strip() if col_cv and pd.notna(ligne[col_cv]) else "",
                        "secteur_souhaite": code_secteur_resolu,
                    })

                if db.base_disponible():
                    db.ajouter_profils_en_masse(profils_importes)
                    st.session_state["recruteur_profils"] = db.charger_profils()
                else:
                    st.session_state["recruteur_profils"].extend(profils_importes)

                st.success(f"{len(profils_importes)} profil(s) importé(s) avec succès.")
                if nb_secteurs_non_reconnus:
                    st.info(
                        f"{nb_secteurs_non_reconnus} secteur(s) saisi(s) n'ont pas été reconnus "
                        "automatiquement — à choisir manuellement sur les profils concernés."
                    )
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
            c9, c10 = st.columns(2)
            profil["langues_parlees"] = c9.text_input(
                "Langues parlées (séparées par une virgule)", value=profil.get("langues_parlees", ""),
                key=f"rec_langues_{i}", placeholder="ex: Anglais courant, Espagnol",
            )
            profil["mobilite"] = c10.text_input(
                "Mobilité (ville / zone)", value=profil.get("mobilite", ""), key=f"rec_mobilite_{i}",
                placeholder="ex: Aix-en-Provence",
            )
            profil["cv_lien"] = st.text_input(
                "Lien CV (Drive/SharePoint...)", value=profil.get("cv_lien", ""), key=f"rec_cv_{i}",
                placeholder="https://drive.google.com/...",
            )
            if profil.get("cv_lien", "").strip():
                st.link_button("📄 Voir le CV", profil["cv_lien"].strip())
            c7, c8 = st.columns(2)
            if db.base_disponible() and c7.button("💾 Enregistrer", key=f"rec_save_{i}"):
                if profil.get("id") is None:
                    profil["id"] = db.ajouter_profil(
                        nom=profil.get("nom", ""), competences=profil.get("competences", ""),
                        outils=profil.get("outils", ""), langages=profil.get("langages", ""),
                        poste_souhaite=profil.get("poste_souhaite", ""), secteur_souhaite=profil.get("secteur_souhaite", ""),
                        cv_lien=profil.get("cv_lien", ""), langues_parlees=profil.get("langues_parlees", ""),
                        mobilite=profil.get("mobilite", ""),
                    )
                else:
                    db.mettre_a_jour_profil(
                        profil["id"], nom=profil.get("nom", ""), competences=profil.get("competences", ""),
                        outils=profil.get("outils", ""), langages=profil.get("langages", ""),
                        poste_souhaite=profil.get("poste_souhaite", ""), secteur_souhaite=profil.get("secteur_souhaite", ""),
                        cv_lien=profil.get("cv_lien", ""), langues_parlees=profil.get("langues_parlees", ""),
                        mobilite=profil.get("mobilite", ""),
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
