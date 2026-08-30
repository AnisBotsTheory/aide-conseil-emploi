"""
espace_candidat.py
--------------------
Page "Espace Candidat" — les 4 onglets existants (Créer mon CV, Tendance par
profil, Offres d'emploi, KPIs avancés), accès gratuit et public. Toute la
logique de calcul vient de moteur_recherche.py (aucune duplication).
"""

import streamlit as st
import pandas as pd
import folium
from datetime import datetime  # noqa: F401 — utilisé dans l'onglet KPIs avancés ;
# moteur_recherche.py importe aussi datetime mais son __all__ ne le réexporte pas
import altair as alt
import plotly.express as px
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from cv_builder import afficher_generateur_cv
from moteur_recherche import *  # noqa: F401,F403 — fonctions de calcul partagées

st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

secteurs = get_secteurs_activite()
options_secteurs = {"Tous secteurs": None}
for s in secteurs:
    code = s.get("code")
    libelle = s.get("libelle")
    if code and libelle:
        options_secteurs[f"{libelle} ({code})"] = code

appellations = get_referentiel_appellations()
labels_appellations = sorted({a.get("libelle", "").strip() for a in appellations if a.get("libelle")})


# ---------------------------------------------------------------------------
# Sélecteur de poste partagé entre "Tendance par profil" et "Offres d'emploi" :
# case à cocher "Tous les postes" (facultative, recherche large) au-dessus du
# champ de saisie libre, puis SÉLECTION MULTIPLE parmi les suggestions ROME —
# plusieurs intitulés proches peuvent être combinés dans une même recherche
# (ex: "Consultant" + "Consultant ERP" + "Consultant IT"). Préremplit la saisie
# depuis le titre de poste renseigné dans "Créer mon CV" (champ cv_titre) si
# l'utilisateur n'a encore rien tapé sur cet onglet.
#
# Retourne (postes_choisis: list[str], codes_par_poste: dict[str, str|None]).
# Cas particulier : (["🌐 Tous les postes"], {}) si la case est cochée.
# ---------------------------------------------------------------------------
def _selecteur_poste(cle_prefixe, departement_pour_resolution):
    cle_checkbox = f"{cle_prefixe}_checkbox_tous_postes"
    cle_texte = f"{cle_prefixe}_poste_texte_libre"
    cle_selection = f"{cle_prefixe}_postes_selectionnes"  # liste de labels, bascule multi-sélection

    if not labels_appellations:
        st.caption("⚠️ Référentiel des postes indisponible pour le moment — recherche par mot-clé en secours.")
        poste_texte_secours = st.text_input("Poste recherché (mot-clé)", key=f"{cle_prefixe}_poste_texte_secours")
        poste_choisi = poste_texte_secours.strip() if poste_texte_secours.strip() else "🌐 Tous les postes"
        return [poste_choisi], {}

    if cle_texte not in st.session_state:
        st.session_state[cle_texte] = st.session_state.get("cv_titre", "")
    if cle_selection not in st.session_state:
        st.session_state[cle_selection] = []

    col_texte, col_checkbox = st.columns([3, 1])
    recherche_tous_postes = col_checkbox.checkbox(
        "🌐 Tous les postes (analyse globale, sans poste précis)",
        key=cle_checkbox,
    )
    poste_texte_libre = col_texte.text_input(
        "Poste recherché (tape même un intitulé moderne ou en anglais : "
        "'Data Analyst', 'Product Owner'...)",
        key=cle_texte,
        disabled=recherche_tous_postes,
    )

    if recherche_tous_postes:
        st.success("Poste sélectionné : **🌐 Tous les postes**")
        return ["🌐 Tous les postes"], {}

    suggestions = suggerer_postes(poste_texte_libre) if poste_texte_libre.strip() else []
    # Union avec la sélection déjà en cours, pour ne pas perdre visuellement un poste
    # sélectionné si l'utilisateur retape un mot-clé différent entre deux sélections.
    tous_les_tags = list(dict.fromkeys(suggestions + st.session_state[cle_selection]))

    if tous_les_tags:
        st.caption("💡 Suggestions — clique pour ajouter/retirer de ta sélection :")
        colonnes_tags = st.columns(2)
        for i, label in enumerate(tous_les_tags):
            est_selectionne = label in st.session_state[cle_selection]
            texte_bouton = f"✅ {label}" if est_selectionne else label
            col_tag = colonnes_tags[i % 2]
            if col_tag.button(texte_bouton, key=f"{cle_prefixe}_tag_{i}_{label}"):
                if est_selectionne:
                    st.session_state[cle_selection].remove(label)
                else:
                    st.session_state[cle_selection].append(label)
                st.rerun()
    elif poste_texte_libre.strip():
        st.caption("Aucune suggestion trouvée pour ce terme — essaie une autre formulation.")

    postes_choisis = st.session_state[cle_selection]

    if not postes_choisis:
        st.info("Sélectionne au moins un poste ci-dessus (ou coche « Tous les postes »).")
        return [], {}

    codes_par_poste = {}
    for label in postes_choisis:
        item_poste = next((a for a in appellations if a.get("libelle", "").strip() == label), None)
        code = _extraire_code_rome(item_poste) if item_poste else None
        if not code:
            with st.spinner(f"Résolution de « {label} »..."):
                df_resolu = resoudre_codes_rome(mots_cles=label, departement=departement_pour_resolution)
            code = df_resolu.iloc[0]["code_rome"] if not df_resolu.empty else None
        codes_par_poste[label] = code

    postes_non_resolus = [label for label, code in codes_par_poste.items() if not code]
    if postes_non_resolus:
        st.warning(
            "⚠️ Impossible de résoudre pour l'instant : " + ", ".join(postes_non_resolus) +
            " — ce(s) poste(s) seront ignorés dans la recherche."
        )

    st.success("Poste(s) sélectionné(s) : **" + " · ".join(postes_choisis) + "**")
    return postes_choisis, codes_par_poste


st.divider()

tab_cv, tab_profil, tab_offres, tab_avance = st.tabs(
    ["🧾 Créer mon CV", "🎯 Tendance par profil", "📋 Offres d'emploi", "🧩 KPIs avancés"]
)

# ---------------------------------------------------------------------------
# Onglet 0 : Créer mon CV (exécuté en premier : sa synchronisation vers
# "Métier recherché" doit être en place avant que ce champ ne soit affiché)
# ---------------------------------------------------------------------------
with tab_cv:
    afficher_generateur_cv(fonction_analyse_competences=analyser_competences)

# ---------------------------------------------------------------------------
# Onglet 1 : Tendance par profil
# ---------------------------------------------------------------------------
with tab_profil:
    st.write(
        "Choisissez le(s) poste(s) que vous ciblez : nous calculons pour vous où sont les offres "
        "près de chez vous, le volume national, et le niveau de tension du marché sur ce métier."
    )
    st.caption(
        "Cette recherche s'appuie sur la nomenclature officielle des métiers de France Travail "
        "(ROME). Choisis un ou plusieurs postes précis dans la liste pour une analyse ciblée "
        "(combinable) — ou coche **🌐 Tous les postes** pour une analyse globale sur tout un "
        "secteur, sans poste précis. La tension du marché reste toutefois un indicateur par "
        "métier unique : elle nécessite un seul poste sélectionné."
    )

    # Valeur du département utilisée pour la résolution de poste : celle du run précédent
    # (le widget lui-même est rendu plus bas, sur la même ligne que le secteur). Cette
    # résolution ne s'en sert qu'en dernier recours (la plupart des suggestions sont déjà
    # dans le référentiel), un décalage d'un run est donc sans incidence pratique.
    departement_pour_resolution_profil = st.session_state.get("dep_profil", "13")
    postes_choisis_profil, codes_par_poste_profil = _selecteur_poste("profil", departement_pour_resolution_profil)

    codes_resolus_profil = [c for c in codes_par_poste_profil.values() if c]
    # secteurs_pour_poste() attend un code ROME unique : résolution précise seulement
    # quand un seul poste (résolu) est sélectionné, sinon liste NAF générique complète.
    code_rome_pour_secteurs = codes_resolus_profil[0] if len(codes_resolus_profil) == 1 else None

    aide_secteur = (
        "Filtre sur le secteur d'activité de l'ENTREPRISE qui recrute, pas sur le type de "
        "poste — une entreprise du secteur assurance peut par exemple recruter des postes "
        "très variés (médical, IT, RH...)."
    )

    col_sect, col_dep = st.columns(2)
    departement_profil = col_dep.text_input("Département (région d'intérêt)", value="13", key="dep_profil")

    if code_rome_pour_secteurs:
        with st.spinner("Recherche des secteurs qui recrutent pour ce poste..."):
            df_secteurs_poste = secteurs_pour_poste(code_rome_pour_secteurs, departement_profil)

        options_secteurs_poste = {"Tous secteurs": None}
        for _, ligne in df_secteurs_poste.iterrows():
            libelle_option = f"{ligne['libelle']} ({ligne['code']}) — {ligne['nombre_offres']} offre(s)"
            options_secteurs_poste[libelle_option] = ligne["code"]

        if len(options_secteurs_poste) <= 1:
            options_secteurs_poste = dict(options_secteurs)

        secteur_choisi_profil = col_sect.selectbox(
            "Secteur d'activité de l'entreprise",
            list(options_secteurs_poste.keys()),
            key="secteur_profil",
            help=aide_secteur,
        )
        code_secteur_profil = options_secteurs_poste[secteur_choisi_profil]
    else:
        # "Tous les postes", plusieurs postes, ou poste pas encore résolvable :
        # liste NAF générique complète
        secteur_choisi_profil = col_sect.selectbox(
            "Secteur d'activité de l'entreprise",
            list(options_secteurs.keys()),
            key="secteur_profil",
            help=aide_secteur,
        )
        code_secteur_profil = options_secteurs[secteur_choisi_profil]

    if st.button("Lancer l'analyse de mon profil"):
        with st.spinner("Préparation de l'analyse..."):
            if postes_choisis_profil == ["🌐 Tous les postes"]:
                df_rome = resoudre_codes_rome(
                    mots_cles=None, departement=departement_profil, secteur_activite=code_secteur_profil
                )
                st.session_state["df_rome_profil"] = df_rome
                st.session_state["code_rome_choisi"] = "TOUS"
                st.session_state["codes_rome_choisis"] = []
                st.session_state["mots_cles_profil_actif"] = ""
            elif not postes_choisis_profil:
                st.error("Sélectionne au moins un poste avant de lancer l'analyse (ou coche « Tous les postes »).")
                st.session_state.pop("df_rome_profil", None)
            elif not codes_resolus_profil:
                st.error(
                    "Impossible de résoudre ce(s) poste(s) pour l'instant (aucune offre trouvée pour "
                    "les recouper). Essaie un autre poste ou élargis le département."
                )
                st.session_state.pop("df_rome_profil", None)
            else:
                st.session_state["df_rome_profil"] = pd.DataFrame(
                    [
                        {"code_rome": code, "libelle": label, "nb_offres_echantillon": None}
                        for label, code in codes_par_poste_profil.items()
                        if code
                    ]
                )
                if len(codes_resolus_profil) == 1:
                    st.session_state["code_rome_choisi"] = codes_resolus_profil[0]
                else:
                    st.session_state["code_rome_choisi"] = "MULTI"
                st.session_state["codes_rome_choisis"] = codes_resolus_profil
                st.session_state["mots_cles_profil_actif"] = " / ".join(postes_choisis_profil)

            st.session_state["departement_profil_actif"] = departement_profil
            st.session_state["secteur_profil_actif"] = code_secteur_profil
            # Force la valeur du sélecteur secteur de l'onglet "Offres d'emploi" — doit être
            # fait AVANT que ce widget soit instancié plus bas dans le script (même rerun).
            # Uniquement si le libellé correspond au format générique attendu là-bas (le
            # sélecteur filtré par poste a un format différent, avec le nombre d'offres).
            if secteur_choisi_profil in options_secteurs:
                st.session_state["secteur_offres"] = secteur_choisi_profil

    if "df_rome_profil" in st.session_state:
        df_rome = st.session_state["df_rome_profil"]
        departement_actif = st.session_state["departement_profil_actif"]
        mots_cles_actifs = st.session_state.get("mots_cles_profil_actif", "")
        secteur_actif = st.session_state.get("secteur_profil_actif")
        code_rome_choisi = st.session_state.get("code_rome_choisi")
        codes_rome_choisis = st.session_state.get("codes_rome_choisis", [])
        recherche_multi = code_rome_choisi == "MULTI"

        if df_rome.empty:
            st.error("Aucune offre trouvée pour ce secteur/département. Essaie d'élargir les critères.")
        else:
            st.markdown(f"#### ⚖️ Tension du marché — département {departement_actif}")
            if code_rome_choisi == "TOUS":
                st.info(
                    "⚖️ La tension du marché nécessite un ou plusieurs postes précis (l'indicateur "
                    "officiel raisonne par métier). Sélectionne au moins un poste ci-dessus pour "
                    "voir ce calcul."
                )
            else:
                if recherche_multi:
                    st.caption(
                        "ℹ️ Plusieurs postes sélectionnés : tension calculée sur la somme des offres "
                        "et des demandeurs d'emploi de l'ensemble des postes retenus, pas sur un "
                        "indicateur officiel par métier unique."
                    )
                    with st.spinner("Récupération des demandeurs d'emploi..."):
                        total_dep_offres = volumes_departement_offres_multi(codes_rome_choisis, departement_actif)
                        total_dep_demandeurs, periode_demandeurs, erreur_demandeurs = (
                            demandeurs_emploi_departement_multi(codes_rome_choisis, departement_actif)
                        )
                else:
                    with st.spinner("Récupération des demandeurs d'emploi..."):
                        total_dep_offres = volumes_departement_offres(code_rome_choisi, departement_actif)
                        total_dep_demandeurs, periode_demandeurs, erreur_demandeurs = demandeurs_emploi_departement(
                            code_rome_choisi, departement_actif
                        )

                if erreur_demandeurs:
                    st.warning(
                        f"Impossible de récupérer les demandeurs d'emploi automatiquement ({erreur_demandeurs}). "
                        "Saisis une valeur manuelle en attendant."
                    )
                    total_dep_demandeurs = st.number_input(
                        "Demandeurs d'emploi (saisie manuelle)", min_value=0, value=0, key="demandeurs_manuel"
                    )
                else:
                    c1, c2 = st.columns(2)
                    c1.metric(f"Offres — département {departement_actif}", total_dep_offres)
                    c2.metric(
                        f"Demandeurs d'emploi{' — ' + periode_demandeurs if periode_demandeurs else ''}",
                        total_dep_demandeurs,
                    )

                tension = calculer_tension(total_dep_offres, total_dep_demandeurs)
                if tension is not None:
                    st.metric("Indice de tension (offres / demandeurs)", tension)
                    st.info(interpreter_tension(tension))
                else:
                    st.info("Donnée de demandeurs insuffisante pour calculer la tension.")

            st.divider()

            st.markdown(f"#### 📍 Offres par ville — département {departement_actif}")
            fraicheur_choisie = st.selectbox(
                "Publiées depuis",
                ["Toutes les offres actives", "7 derniers jours", "30 derniers jours", "90 derniers jours"],
                key="fraicheur_offres_ville",
            )
            jours_max = {
                "Toutes les offres actives": None,
                "7 derniers jours": 7,
                "30 derniers jours": 30,
                "90 derniers jours": 90,
            }[fraicheur_choisie]

            with st.spinner("Récupération des offres par ville..."):
                if recherche_multi:
                    df_villes, total_region, date_min_pub, date_max_pub, df_entreprises, nb_offres_anonymes = (
                        offres_par_ville_multi(
                            codes_rome_choisis, departement_actif, jours_max=jours_max, secteur_activite=secteur_actif
                        )
                    )
                else:
                    df_villes, total_region, date_min_pub, date_max_pub, df_entreprises, nb_offres_anonymes = (
                        offres_par_ville(
                            code_rome_choisi,
                            departement_actif,
                            jours_max=jours_max,
                            mots_cles=mots_cles_actifs,
                            secteur_activite=secteur_actif,
                        )
                    )
            st.metric("Total offres dans la région", total_region)
            if date_min_pub and date_max_pub:
                st.caption(
                    f"📅 Offres publiées entre le {date_min_pub[:10]} et le {date_max_pub[:10]} "
                    "(format AAAA-MM-JJ) — l'API ne filtre pas par ancienneté par défaut, "
                    "ces offres sont simplement celles encore actives aujourd'hui."
                )
            if not df_villes.empty:
                df_carte = df_villes.dropna(subset=["latitude", "longitude"]).copy()
                if not df_carte.empty:
                    df_carte["latitude"] = df_carte["latitude"].astype(float)
                    df_carte["longitude"] = df_carte["longitude"].astype(float)

                    etendue_lat = df_carte["latitude"].max() - df_carte["latitude"].min()
                    etendue_lon = df_carte["longitude"].max() - df_carte["longitude"].min()
                    etendue = max(etendue_lat, etendue_lon)
                    if etendue < 0.03:
                        zoom_auto = 12
                    elif etendue < 0.1:
                        zoom_auto = 11
                    elif etendue < 0.3:
                        zoom_auto = 10
                    elif etendue < 0.8:
                        zoom_auto = 9
                    else:
                        zoom_auto = 8

                    carte = folium.Map(
                        location=[df_carte["latitude"].mean(), df_carte["longitude"].mean()],
                        zoom_start=zoom_auto,
                        tiles="CartoDB dark_matter",
                    )
                    cluster = MarkerCluster(
                        options={"maxClusterRadius": 60, "disableClusteringAtZoom": 15}
                    ).add_to(carte)

                    for _, row in df_carte.iterrows():
                        for _ in range(int(row["nombre_offres"])):
                            folium.CircleMarker(
                                location=[row["latitude"], row["longitude"]],
                                radius=8,
                                tooltip=f"{row['ville']} : {int(row['nombre_offres'])} offre(s)",
                                color="#0066cc",
                                fill=True,
                                fill_color="#0066cc",
                                fill_opacity=0.8,
                                weight=1,
                            ).add_to(cluster)

                    st_folium(
                        carte,
                        use_container_width=True,
                        height=500,
                        key="carte_offres_ville",
                        returned_objects=[],
                    )
                else:
                    st.info("Coordonnées GPS non disponibles pour ces offres, carte non affichée.")

                st.markdown("#### 🏢 Top recruteurs")
                if df_entreprises.empty:
                    st.info(
                        "Aucun nom d'entreprise exploitable — soit aucune offre, soit toutes "
                        "les offres sont diffusées de façon anonyme."
                    )
                else:
                    st.caption("👇 Clique sur une entreprise pour consulter ses offres.")
                    selection_top_recruteur = st.dataframe(
                        df_entreprises.rename(
                            columns={
                                "entreprise": "Entreprise",
                                "nombre_offres": "Nombre d'offres",
                                "villes": "Ville",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key="table_top_recruteurs",
                    )
                    if nb_offres_anonymes:
                        st.caption(
                            f"ℹ️ {nb_offres_anonymes} offre(s) supplémentaire(s) diffusée(s) sans "
                            "nom d'entreprise visible (recrutement anonyme), non comptabilisée(s) ci-dessus."
                        )

                    lignes_top_recruteur_sel = selection_top_recruteur["selection"]["rows"]
                    if lignes_top_recruteur_sel:
                        entreprise_choisie_top = df_entreprises.iloc[lignes_top_recruteur_sel[0]]["entreprise"]
                        with st.spinner(f"Récupération des offres de {entreprise_choisie_top}..."):
                            if recherche_multi:
                                offres_top_recruteur = rechercher_offres_completes_multi(
                                    codes_rome_choisis, departement_actif, max_pages=5, secteur_activite=secteur_actif,
                                )
                            else:
                                offres_top_recruteur = rechercher_offres_completes(
                                    code_rome_choisi, departement_actif, max_pages=5,
                                    mots_cles=mots_cles_actifs, secteur_activite=secteur_actif,
                                )
                        offres_de_cette_entreprise = [
                            o for o in offres_top_recruteur
                            if (o.get("entreprise", {}) or {}).get("nom") == entreprise_choisie_top
                        ]

                        st.markdown(f"##### 📋 Offres chez {entreprise_choisie_top}")
                        if not offres_de_cette_entreprise:
                            st.info(
                                "Aucune offre retrouvée pour cette entreprise pour l'instant — les "
                                "résultats peuvent varier légèrement entre deux recherches successives."
                            )
                        else:
                            for o in offres_de_cette_entreprise:
                                lieu_o = o.get("lieuTravail", {}).get("libelle", "N/C")
                                date_pub_o = o.get("dateCreation", "")[:10]
                                with st.expander(f"**{o.get('intitule', '')}** — {lieu_o} — publiée le {date_pub_o}"):
                                    type_contrat_o = o.get("typeContratLibelle") or o.get("typeContrat")
                                    if type_contrat_o:
                                        st.markdown(f"**Type de contrat :** {type_contrat_o}")
                                    salaire_o = o.get("salaire", {}).get("libelle")
                                    if salaire_o:
                                        st.markdown(f"**Salaire :** {salaire_o}")
                                    description_o = o.get("description")
                                    if description_o:
                                        st.markdown("**Description :**")
                                        st.write(description_o)
                                    competences_offre_o = o.get("competences", [])
                                    if competences_offre_o:
                                        libelles_o = ", ".join(
                                            c.get("libelle", "") for c in competences_offre_o if c.get("libelle")
                                        )
                                        if libelles_o:
                                            st.markdown(f"**Compétences demandées :** {libelles_o}")
                                    url_offre_o = o.get("origineOffre", {}).get("urlOrigine")
                                    if url_offre_o:
                                        st.markdown(
                                            f"🔗 [Voir l'offre complète et postuler sur France Travail]({url_offre_o})"
                                        )

            st.divider()
            st.info(
                "💡 Pour le top entreprises, la comparaison multi-département, le "
                "dynamisme du territoire, les embauches et les établissements, direction "
                "l'onglet **🧩 KPIs avancés**."
            )

# ---------------------------------------------------------------------------
# Onglet 2 : Offres d'emploi — autonome, même principe de sélection de poste
# (multi-sélection incluse) que "Tendance par profil".
# ---------------------------------------------------------------------------
with tab_offres:
    st.write(
        "Recherchez directement des offres correspondant à un ou plusieurs postes précis "
        "(combinables), ou coche « Tous les postes » pour une recherche large."
    )

    departement_pour_resolution_offres = st.session_state.get("dep_offres", "13")
    postes_choisis_offres, codes_par_poste_offres = _selecteur_poste("offres", departement_pour_resolution_offres)

    codes_resolus_offres = [c for c in codes_par_poste_offres.values() if c]

    col_sect_off, col_dep_off = st.columns(2)
    departement = col_dep_off.text_input(
        "Département (ex: 13 = Bouches-du-Rhône)",
        value=st.session_state.get("departement_profil_actif", "13"),
        key="dep_offres",
    )
    secteur_choisi_offres = col_sect_off.selectbox("Secteur d'activité", list(options_secteurs.keys()), key="secteur_offres")
    secteur_naf = options_secteurs[secteur_choisi_offres]
    fraicheur_choisie_offres = st.selectbox(
        "Publiées depuis",
        ["Toutes les offres actives", "7 derniers jours", "30 derniers jours", "90 derniers jours"],
        key="fraicheur_offres",
    )
    jours_max_offres = {
        "Toutes les offres actives": None,
        "7 derniers jours": 7,
        "30 derniers jours": 30,
        "90 derniers jours": 90,
    }[fraicheur_choisie_offres]

    if st.button("Chercher des offres"):
        resultats, total = [], 0
        recherche_ok = True

        if postes_choisis_offres == ["🌐 Tous les postes"]:
            with st.spinner("Recherche en cours..."):
                resultats, total = chercher_offres(
                    "TOUS", departement, secteur_naf, jours_max_offres, mots_cles=""
                )
        elif not postes_choisis_offres:
            st.error("Sélectionne au moins un poste (ou coche « Tous les postes »).")
            recherche_ok = False
        elif not codes_resolus_offres:
            st.error(
                "Impossible de résoudre ce(s) poste(s) pour l'instant (aucune offre trouvée pour "
                "les recouper). Essaie un autre poste, élargis le département, ou coche "
                "\"Tous les postes\"."
            )
            recherche_ok = False
        elif len(codes_resolus_offres) == 1:
            with st.spinner("Recherche en cours..."):
                resultats, total = chercher_offres(
                    codes_resolus_offres[0], departement, secteur_naf, jours_max_offres,
                    mots_cles=postes_choisis_offres[0],
                )
        else:
            with st.spinner("Recherche en cours..."):
                resultats, total = chercher_offres_multi(
                    codes_resolus_offres, departement, secteur_naf, jours_max_offres
                )

        if recherche_ok:
            if not resultats:
                st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
            else:
                st.success(f"{len(resultats)} offres affichées sur {total} au total")

                competences_utilisateur = st.session_state.get("cv_competences_select", [])
                outils_utilisateur = st.session_state.get("cv_outils_select", [])
                langages_utilisateur = st.session_state.get("cv_langages_select", [])
                mots_cles_secteur = st.session_state.get("cv_mots_cles_secteur", "")

                if not competences_utilisateur and not mots_cles_secteur:
                    st.info(
                        "💡 Renseigne tes compétences et/ou tes mots-clés sectoriels dans "
                        "**🧾 Créer mon CV** pour activer le % de correspondance sur ces offres."
                    )

                for o in resultats:
                    entreprise = o.get("entreprise", {}).get("nom", "N/C")
                    lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                    date_pub = o.get("dateCreation", "")[:10]

                    score, detail = calculer_correspondance_offre(
                        o, competences_utilisateur, outils_utilisateur, langages_utilisateur, mots_cles_secteur
                    )
                    ligne_titre = f"**{o['intitule']}** — {entreprise} — {lieu} — publiée le {date_pub}"
                    if score is not None:
                        ligne_titre += f"  \n🎯 Correspondance : **{score}%**"
                        if detail:
                            ligne_titre += " (" + " · ".join(f"{k} {n}/{d}" for k, (n, d) in detail.items()) + ")"

                    with st.expander(ligne_titre):
                        type_contrat = o.get("typeContratLibelle") or o.get("typeContrat")
                        if type_contrat:
                            st.markdown(f"**Type de contrat :** {type_contrat}")
                        salaire = o.get("salaire", {}).get("libelle")
                        if salaire:
                            st.markdown(f"**Salaire :** {salaire}")
                        description = o.get("description")
                        if description:
                            st.markdown("**Description :**")
                            st.write(description)
                        competences_offre = o.get("competences", [])
                        if competences_offre:
                            libelles = ", ".join(c.get("libelle", "") for c in competences_offre if c.get("libelle"))
                            if libelles:
                                st.markdown(f"**Compétences demandées :** {libelles}")
                        url_offre = o.get("origineOffre", {}).get("urlOrigine")
                        if url_offre:
                            st.markdown(f"🔗 [Voir l'offre complète et postuler sur France Travail]({url_offre})")

# ---------------------------------------------------------------------------
# Onglet "KPIs avancés"
# ---------------------------------------------------------------------------
with tab_avance:
    if "code_rome_choisi" not in st.session_state:
        st.info(
            "👉 Lance d'abord une analyse dans l'onglet **🎯 Tendance par profil** "
            "pour choisir ton métier — les KPIs avancés s'appuient dessus."
        )
    else:
        code_rome_actif = st.session_state["code_rome_choisi"]
        codes_rome_choisis_avance = st.session_state.get("codes_rome_choisis", [])
        departement_actif = st.session_state["departement_profil_actif"]
        mots_cles_actifs_avance = st.session_state.get("mots_cles_profil_actif", "")
        secteur_actif_avance = st.session_state.get("secteur_profil_actif")
        recherche_multi_avance = code_rome_actif == "MULTI"

        if st.button("🚀 Lancer l'analyse complète", type="primary", key="btn_analyse_complete"):
            with st.spinner("Analyse en cours (évolution, contrats, salaires, expérience)..."):
                if recherche_multi_avance:
                    df_evolution = evolution_offres_annuelle_multi(
                        codes_rome_choisis_avance, departement_actif, secteur_activite=secteur_actif_avance,
                    )
                    df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                        repartition_contrats_et_salaires_multi(
                            codes_rome_choisis_avance, departement_actif, secteur_activite=secteur_actif_avance,
                        )
                    )
                else:
                    df_evolution = evolution_offres_annuelle(
                        code_rome_actif,
                        departement_actif,
                        mots_cles=mots_cles_actifs_avance,
                        secteur_activite=secteur_actif_avance,
                    )
                    df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                        repartition_contrats_et_salaires(
                            code_rome_actif,
                            departement_actif,
                            mots_cles=mots_cles_actifs_avance,
                            secteur_activite=secteur_actif_avance,
                        )
                    )

            st.divider()
            annee_courante = datetime.now().year
            st.markdown(f"#### 📈 Nombre d'offres d'emploi - {annee_courante}")
            if df_evolution.empty or df_evolution["nombre_offres"].sum() == 0:
                st.info("Aucune donnée d'évolution disponible pour ces critères.")
            else:
                df_evolution_affiche = df_evolution.copy()
                df_evolution_affiche["mois_label"] = df_evolution_affiche["mois"].apply(_formater_mois_fr)
                ordre_mois = list(df_evolution_affiche["mois_label"])

                base_evolution = alt.Chart(df_evolution_affiche).encode(
                    x=alt.X(
                        "mois_label:N",
                        sort=ordre_mois,
                        title=None,
                        axis=alt.Axis(labelAngle=-45),
                    ),
                    y=alt.Y("nombre_offres:Q", title="Nombre d'offres"),
                )
                courbe = base_evolution.mark_line(point=True, color="#0066cc")
                etiquettes = base_evolution.mark_text(dy=-12, fontSize=12).encode(text="nombre_offres:Q")
                st.altair_chart((courbe + etiquettes).properties(height=350), use_container_width=True)

            st.divider()
            st.markdown("#### 📋 Répartition par type de contrat")
            if df_contrats.empty:
                st.info("Aucune donnée de type de contrat disponible pour ces critères.")
            else:
                fig_contrats = px.treemap(
                    df_contrats,
                    path=["type_contrat"],
                    values="nombre_offres",
                    color="nombre_offres",
                    color_continuous_scale="Blues",
                )
                fig_contrats.update_traces(
                    textinfo="label+value",
                    textfont_size=16,
                    marker=dict(line=dict(width=2, color="white")),
                )
                fig_contrats.update_layout(margin=dict(t=10, l=10, r=10, b=10))
                st.plotly_chart(fig_contrats, use_container_width=True)

                st.dataframe(
                    df_contrats.rename(columns={"type_contrat": "Type de contrat", "nombre_offres": "Nombre d'offres"}),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()
            st.markdown("#### 💰 Fourchette de salaire proposée")
            if nb_total_offres == 0:
                st.info("Aucune offre trouvée pour ces critères.")
            elif nb_avec_salaire == 0:
                st.info("Aucune des offres trouvées n'indique de salaire.")
            else:
                pct = round(100 * nb_avec_salaire / nb_total_offres)
                st.metric("Offres indiquant un salaire", f"{nb_avec_salaire} / {nb_total_offres} ({pct}%)")
                st.dataframe(df_salaires, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("#### 🎓 Répartition par niveau d'expérience demandé")
            if df_experience.empty:
                st.info("Aucune donnée de niveau d'expérience disponible pour ces critères.")
            else:
                base_experience = alt.Chart(df_experience).encode(
                    x=alt.X("nombre_offres:Q", title="Nombre d'offres"),
                    y=alt.Y("experience:N", title=None, sort="-x"),
                )
                barres_experience = base_experience.mark_bar(color="#0066cc")
                etiquettes_experience = base_experience.mark_text(
                    align="left", dx=4, fontSize=11
                ).encode(text="nombre_offres:Q")
                st.altair_chart(
                    (barres_experience + etiquettes_experience).properties(height=140),
                    use_container_width=True,
                )

            st.divider()
            st.markdown("#### 🎯 Difficulté de recrutement (BMO)")
            st.info(
                "⚠️ Pas encore branché — c'est un indicateur annuel et déclaratif (enquête "
                "employeurs), différent des données d'offres réelles utilisées ailleurs dans "
                "l'app. Dis-moi si tu veux qu'on l'ajoute."
            )
