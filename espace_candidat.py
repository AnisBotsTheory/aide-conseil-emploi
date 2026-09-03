"""
espace_candidat.py
--------------------
Page "Espace Candidat" — 3 onglets (Créer mon CV, Tendance par profil, KPIs
avancés), accès gratuit et public. Toute la logique de calcul vient de
moteur_recherche.py (aucune duplication).

L'onglet "Offres d'emploi" a été retiré : lister des offres n'a pas d'avantage
face aux plateformes dédiées (France Travail, LinkedIn, Indeed...) — pas
d'alertes, pas de candidature en un clic, pas de sauvegarde de recherche. Ce
qui reste différenciant, c'est la lecture de marché (tension, évolution,
répartition contrats/salaires, villes/recruteurs actifs) — pas le listing
d'offres lui-même. "Villes qui recrutent"/"Top recruteurs" deviennent des
pistes de candidature spontanée plutôt qu'un moteur de recherche d'offres.
"""

import streamlit as st
import pandas as pd
import folium
from datetime import datetime  # noqa: F401 — utilisé dans l'onglet KPIs avancés ;
# moteur_recherche.py importe aussi datetime mais son __all__ ne le réexporte pas
import altair as alt
import plotly.express as px
import plotly.graph_objects as go
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from cv_builder import afficher_generateur_cv
from moteur_recherche import *  # noqa: F401,F403 — fonctions de calcul partagées

st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

appellations = get_referentiel_appellations()
labels_appellations = sorted({a.get("libelle", "").strip() for a in appellations if a.get("libelle")})


def _selecteur_departement(cle_prefixe):
    """
    Sélecteur de département en MULTI-sélection, avec option "Toute la France"
    (recherche nationale — l'API le permet nativement en omettant le paramètre
    département). Plusieurs départements sont envoyés à l'API sous forme de
    codes séparés par une virgule (accepté nativement par l'API Offres d'emploi
    France Travail).

    Retourne une valeur de paramètre département :
    - None -> "Toute la France" (aucun filtre)
    - ""   -> rien sélectionné (état invalide, à gérer par l'appelant)
    - "13" ou "13,75" -> un ou plusieurs codes
    """
    cle_checkbox = f"{cle_prefixe}_checkbox_toute_france"
    cle_multiselect = f"{cle_prefixe}_departements_multiselect"

    # Valeur du run précédent pour désactiver le multiselect si "Toute la France" est
    # cochée — la case est rendue APRÈS le multiselect (demande UX), donc on ne connaît
    # sa valeur pour CE run qu'après l'avoir affichée ; celle du run précédent suffit
    # pour l'état "disabled" (même trick que pour d'autres sélecteurs de l'app).
    toute_la_france_precedente = st.session_state.get(cle_checkbox, False)

    if cle_multiselect not in st.session_state:
        # Préremplit depuis le département renseigné dans "Créer mon CV" (cv_departement),
        # sinon retombe sur le département par défaut de l'app.
        code_departement_cv = st.session_state.get("cv_departement")
        nom_departement_cv = DEPARTEMENTS_VERS_NOM.get(code_departement_cv) if code_departement_cv else None
        if code_departement_cv and nom_departement_cv:
            st.session_state[cle_multiselect] = [f"{code_departement_cv} - {nom_departement_cv}"]
        else:
            st.session_state[cle_multiselect] = ["13 - Bouches-du-Rhône"]

    options_departements = sorted(f"{code} - {nom}" for code, nom in DEPARTEMENTS_VERS_NOM.items())
    labels_choisis = st.multiselect(
        "Département(s) (région d'intérêt)",
        options=options_departements,
        key=cle_multiselect,
        disabled=toute_la_france_precedente,
    )

    toute_la_france = st.checkbox("🇫🇷 Toute la France (aucun filtre département)", key=cle_checkbox)
    if toute_la_france:
        return None

    if not labels_choisis:
        st.info("Sélectionne au moins un département ci-dessus, ou coche « Toute la France ».")
        return ""
    return ",".join(label.split(" - ")[0] for label in labels_choisis)


def _libelle_departement_affiche(departement_param):
    """Libellé lisible pour un titre de section ('département 13', 'départements
    13, 75', 'toute la France')."""
    if not departement_param:
        return "toute la France"
    codes = departement_param.split(",")
    if len(codes) == 1:
        return f"département {codes[0]}"
    return "départements " + ", ".join(codes)


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

    # Un nouveau terme de recherche efface la sélection précédente : sans ça, les
    # postes choisis lors d'une recherche antérieure (ex: "big data") continuaient
    # à apparaître cochés en changeant complètement de sujet (ex: "réceptionniste"),
    # ce qui prêtait à confusion sur ce qui allait réellement être recherché.
    cle_terme_precedent = f"{cle_prefixe}_poste_terme_precedent"
    terme_precedent = st.session_state.get(cle_terme_precedent, poste_texte_libre)
    if poste_texte_libre != terme_precedent and st.session_state[cle_selection]:
        st.session_state[cle_selection] = []
    st.session_state[cle_terme_precedent] = poste_texte_libre

    if recherche_tous_postes:
        st.success("Poste sélectionné : **🌐 Tous les postes**")
        return ["🌐 Tous les postes"], {}

    suggestions = suggerer_postes(poste_texte_libre) if poste_texte_libre.strip() else []

    # Auto-sélectionne la meilleure suggestion pour ce terme, une seule fois (pour
    # que "Créer mon CV" alimente automatiquement l'analyse sans clic supplémentaire).
    # Ne se redéclenche pas si l'utilisateur retire ensuite volontairement ce choix.
    cle_auto_poste_pour_terme = f"{cle_prefixe}_auto_poste_pour_terme"
    if (
        suggestions
        and not st.session_state[cle_selection]
        and st.session_state.get(cle_auto_poste_pour_terme) != poste_texte_libre
    ):
        st.session_state[cle_selection].append(suggestions[0])
    st.session_state[cle_auto_poste_pour_terme] = poste_texte_libre

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

tab_cv, tab_profil, tab_avance = st.tabs(
    ["🧾 Créer mon CV", "🎯 Tendance par profil", "🧩 KPIs avancés"]
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
        "Analyse du marché pour le poste renseigné dans votre CV : où sont les offres près de "
        "chez vous, le volume national, et le niveau de tension du marché sur ce métier."
    )

    titre_poste_cv = st.session_state.get("cv_titre", "").strip()
    departement_cv = st.session_state.get("cv_departement") or "13"

    if not titre_poste_cv:
        st.info(
            "👉 Renseigne un poste recherché dans l'onglet **🧾 Créer mon CV** — l'analyse se "
            "lance automatiquement dès qu'il est rempli, pas besoin de le ressaisir ici."
        )
    else:
        # Résolution silencieuse du poste (texte du CV) vers un code ROME — plus de champ
        # affiché ici : poste et département viennent uniquement de "Créer mon CV".
        cle_auto_signature = "profil_auto_analyse_signature"
        signature_actuelle = (titre_poste_cv, departement_cv)

        if st.session_state.get(cle_auto_signature) != signature_actuelle:
            with st.spinner("Analyse du marché en cours..."):
                suggestions = suggerer_postes(titre_poste_cv)
                if suggestions:
                    libelle_resolu = suggestions[0]
                    item_poste = next(
                        (a for a in appellations if a.get("libelle", "").strip() == libelle_resolu), None
                    )
                    code_resolu = _extraire_code_rome(item_poste) if item_poste else None
                    if not code_resolu:
                        df_resolu_apercu = resoudre_codes_rome(mots_cles=libelle_resolu, departement=departement_cv)
                        code_resolu = (
                            df_resolu_apercu.iloc[0]["code_rome"] if not df_resolu_apercu.empty else None
                        )
                else:
                    libelle_resolu, code_resolu = titre_poste_cv, None

                if not code_resolu:
                    st.session_state["df_rome_profil"] = pd.DataFrame()
                else:
                    st.session_state["df_rome_profil"] = pd.DataFrame(
                        [{"code_rome": code_resolu, "libelle": libelle_resolu, "nb_offres_echantillon": None}]
                    )
                    st.session_state["code_rome_choisi"] = code_resolu
                    st.session_state["codes_rome_choisis"] = [code_resolu]
                    st.session_state["mots_cles_profil_actif"] = libelle_resolu

                st.session_state["departement_profil_actif"] = departement_cv
                st.session_state[cle_auto_signature] = signature_actuelle

    if "df_rome_profil" in st.session_state:
        df_rome = st.session_state["df_rome_profil"]
        departement_actif = st.session_state["departement_profil_actif"]
        mots_cles_actifs = st.session_state.get("mots_cles_profil_actif", "")
        code_rome_choisi = st.session_state.get("code_rome_choisi")
        codes_rome_choisis = st.session_state.get("codes_rome_choisis", [])
        recherche_multi = code_rome_choisi == "MULTI"

        if df_rome.empty:
            st.error("Aucune offre trouvée pour ce département. Essaie d'élargir les critères.")
        else:
            # Tous les indicateurs de cet onglet (tension, top recruteurs, top villes)
            # partagent désormais la même base de temps : depuis le 1er janvier de l'année
            # en cours. Poste et secteur restent les mêmes filtres que partout ailleurs.
            aujourdhui = datetime.now()
            debut_annee = datetime(aujourdhui.year, 1, 1)
            libelle_periode_offres = f"depuis janvier {aujourdhui.year}"
            jours_max_periode_offres = (aujourdhui - debut_annee).days

            st.markdown("#### ⚖️ Tension du marché")
            if code_rome_choisi == "TOUS":
                st.info(
                    "⚖️ La tension du marché nécessite un ou plusieurs postes précis (l'indicateur "
                    "officiel raisonne par métier). Sélectionne au moins un poste ci-dessus pour "
                    "voir ce calcul."
                )
            elif departement_est_multiple(departement_actif):
                st.info(
                    "⚖️ La tension du marché nécessite un seul département sélectionné (statistique "
                    "officielle trimestrielle, un appel par territoire) — indisponible pour « Toute "
                    "la France » ou une sélection de plusieurs départements. Choisis un seul "
                    "département ci-dessus pour voir ce calcul."
                )
            else:
                st.caption(
                    f"ℹ️ Le nombre d'offres porte sur le {libelle_periode_offres} (même base que "
                    "le top recruteurs et le top villes plus bas) ; les demandeurs d'emploi "
                    "restent une statistique officielle trimestrielle (non filtrable par date)."
                    + (
                        " Plusieurs postes sélectionnés : tension calculée sur la somme des offres "
                        "et des demandeurs d'emploi de l'ensemble des postes retenus, pas sur un "
                        "indicateur officiel par métier unique."
                        if recherche_multi else ""
                    )
                )
                if recherche_multi:
                    with st.spinner("Récupération des demandeurs d'emploi..."):
                        total_dep_offres = volumes_departement_offres_multi(
                            codes_rome_choisis, departement_actif, jours_max=jours_max_periode_offres,
                        )
                        total_dep_demandeurs, periode_demandeurs, erreur_demandeurs = (
                            demandeurs_emploi_departement_multi(codes_rome_choisis, departement_actif)
                        )
                else:
                    with st.spinner("Récupération des demandeurs d'emploi..."):
                        total_dep_offres = volumes_departement_offres(
                            code_rome_choisi, departement_actif, jours_max=jours_max_periode_offres,
                        )
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
                    c1.metric(f"Offres — {libelle_periode_offres}", total_dep_offres)
                    c2.metric(
                        f"Demandeurs d'emploi{' — ' + periode_demandeurs if periode_demandeurs else ''}",
                        total_dep_demandeurs,
                    )

                tension = calculer_tension(total_dep_offres, total_dep_demandeurs)
                if tension is not None:
                    st.metric("Indice de tension (offres / demandeurs)", tension)
                    st.info(interpreter_tension(tension))
                    conseils = conseils_tension(tension)
                    if conseils:
                        with st.expander("💡 Conseils pour ce niveau de tension"):
                            for conseil in conseils:
                                st.markdown(f"- {conseil}")
                else:
                    st.info("Donnée de demandeurs insuffisante pour calculer la tension.")

            st.divider()

            mots_cles_recherche_large = (
                "" if postes_choisis_profil == ["🌐 Tous les postes"] else " ".join(postes_choisis_profil)
            )

            with st.spinner("Récupération des recruteurs actifs..."):
                _, _, _, _, df_entreprises, _ = offres_par_ville(
                    "TOUS", departement_actif,
                    jours_max=jours_max_periode_offres, mots_cles=mots_cles_recherche_large,
                )

            st.markdown("#### 🏢 Top recruteurs")
            st.caption(f"ℹ️ Recruteurs actifs {libelle_periode_offres} (même base que la tension du marché).")
            if df_entreprises.empty:
                st.info(
                    "Aucun nom d'entreprise exploitable — soit aucune offre, soit toutes "
                    "les offres sont diffusées de façon anonyme."
                )
            else:
                st.caption(
                    "💡 Les entreprises ou les candidatures spontanées peuvent être pertinentes — "
                    "même sans offre publiée actuellement, ces recruteurs actifs sur ce métier "
                    "peuvent valoir une candidature directe."
                )
                st.dataframe(
                    df_entreprises.rename(
                        columns={
                            "entreprise": "Entreprise",
                            "nombre_offres": "Nombre d'offres",
                        }
                    ).drop(columns=["villes"]),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()

            st.markdown("#### 📍 Villes qui recrutent")
            st.caption(f"ℹ️ Répartition {libelle_periode_offres} (même base que la tension et le top recruteurs).")
            with st.spinner("Récupération des offres par ville..."):
                df_villes, total_region, date_min_pub, date_max_pub, _, _ = offres_par_ville(
                    "TOUS", departement_actif,
                    jours_max=jours_max_periode_offres, mots_cles=mots_cles_recherche_large,
                )
            st.metric("Total offres dans la région", total_region)
            # Note (non affichée à l'écran, à la demande) : date_min_pub/date_max_pub
            # donnent la plage de publication réelle des offres renvoyées par l'API —
            # ex: "Offres publiées entre le {date_min_pub[:10]} et le {date_max_pub[:10]}
            # (format AAAA-MM-JJ)". L'API ne filtre pas par ancienneté par défaut : ces
            # offres sont simplement celles encore actives aujourd'hui.
            if not df_villes.empty:
                df_carte = df_villes.dropna(subset=["latitude", "longitude"]).copy()
                nb_offres_approx = int(df_carte.loc[df_carte["approximatif"], "nombre_offres"].sum()) if not df_carte.empty else 0
                if nb_offres_approx > 0:
                    st.caption(
                        f"📍 {nb_offres_approx} offre(s) sur {total_region} n'ont pas de coordonnées GPS "
                        "précises côté France Travail (lieu renseigné au niveau département seulement, ou "
                        "télétravail) — elles sont positionnées sur la plus grande ville du département "
                        "(marqueurs oranges ci-dessous), à titre indicatif."
                    )
                ville_cliquee = None
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
                        # CartoDB dark_matter exige désormais une clé API (changement récent
                        # de Carto) — OpenStreetMap reste gratuit et sans clé, en thème clair.
                        tiles="OpenStreetMap",
                    )
                    cluster = MarkerCluster(
                        options={"maxClusterRadius": 60, "disableClusteringAtZoom": 15}
                    ).add_to(carte)

                    for _, row in df_carte.iterrows():
                        couleur = "#e67e22" if row["approximatif"] else "#0066cc"
                        tooltip_texte = f"{row['ville']} : {int(row['nombre_offres'])} offre(s)"
                        if row["approximatif"]:
                            tooltip_texte += " (position approximative)"
                        for _ in range(int(row["nombre_offres"])):
                            folium.CircleMarker(
                                location=[row["latitude"], row["longitude"]],
                                radius=8,
                                tooltip=tooltip_texte,
                                color=couleur,
                                fill=True,
                                fill_color=couleur,
                                fill_opacity=0.8,
                                weight=1,
                            ).add_to(cluster)

                    # Carte purement visuelle (tendance) : pas de listing d'offres cliquables —
                    # l'app ne cherche plus à concurrencer les plateformes de recrutement dédiées,
                    # seule la lecture de marché (villes qui recrutent) est montrée ici.
                    # returned_objects=[] évite les allers-retours serveur au zoom/déplacement
                    # (meilleure stabilité, notamment sur mobile).
                    st_folium(
                        carte,
                        use_container_width=True,
                        height=500,
                        key="carte_offres_ville",
                        returned_objects=[],
                    )
                else:
                    st.info("Coordonnées GPS non disponibles pour ces offres, carte non affichée.")

            st.divider()
            st.info(
                "📊 Repère général (indépendant de la recherche ci-dessus) : la durée moyenne "
                "d'un recrutement de cadre en France est stable à 12 semaines depuis 2022 "
                "(source : Apec, « Pratiques de recrutement des cadres » 2026). Nous n'avons pas "
                "trouvé de repère aussi solidement sourcé pour les postes non-cadres — à prendre "
                "avec prudence si tu cherches un point de comparaison sur ce type de poste."
            )

# ---------------------------------------------------------------------------
# Onglet "KPIs avancés"
# ---------------------------------------------------------------------------
with tab_avance:
    if "code_rome_choisi" not in st.session_state:
        st.info(
            "👉 Renseigne un poste dans l'onglet **🧾 Créer mon CV** — les KPIs avancés "
            "s'appuient sur l'analyse automatique de l'onglet Tendance par profil."
        )
    else:
        code_rome_actif = st.session_state["code_rome_choisi"]
        codes_rome_choisis_avance = st.session_state.get("codes_rome_choisis", [])
        departement_actif = st.session_state["departement_profil_actif"]
        mots_cles_actifs_avance = st.session_state.get("mots_cles_profil_actif", "")
        recherche_multi_avance = code_rome_actif == "MULTI"

        # Auto-déclenchement : se relance seul dès que le poste/département actif change
        # (mis à jour automatiquement par "Tendance par profil"), résultats conservés en
        # session pour rester affichés en revenant sur cet onglet.
        cle_signature_avance = "avance_auto_signature"
        signature_avance_actuelle = (code_rome_actif, tuple(codes_rome_choisis_avance), departement_actif)

        if st.session_state.get(cle_signature_avance) != signature_avance_actuelle:
            with st.spinner("Analyse en cours (évolution, contrats, salaires, expérience)..."):
                if recherche_multi_avance:
                    df_evolution = evolution_offres_annuelle_multi(codes_rome_choisis_avance, departement_actif)
                    df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                        repartition_contrats_et_salaires_multi(codes_rome_choisis_avance, departement_actif)
                    )
                else:
                    df_evolution = evolution_offres_annuelle(
                        code_rome_actif, departement_actif, mots_cles=mots_cles_actifs_avance,
                    )
                    df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                        repartition_contrats_et_salaires(
                            code_rome_actif, departement_actif, mots_cles=mots_cles_actifs_avance,
                        )
                    )
            st.session_state["avance_resultats"] = (
                df_evolution, df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience,
            )
            st.session_state[cle_signature_avance] = signature_avance_actuelle

        if "avance_resultats" in st.session_state:
            df_evolution, df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                st.session_state["avance_resultats"]
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
                df_contrats_tri = df_contrats.sort_values("nombre_offres", ascending=False).reset_index(drop=True)
                fig_contrats = go.Figure(
                    go.Scatter(
                        x=list(range(len(df_contrats_tri))),
                        y=[0] * len(df_contrats_tri),
                        mode="markers+text",
                        marker=dict(
                            # sizemode="area" + cette formule standard Plotly rend l'AIRE du
                            # cercle proportionnelle à nombre_offres (pas le diamètre, qui
                            # exagérerait visuellement les écarts entre types de contrat).
                            size=df_contrats_tri["nombre_offres"],
                            sizemode="area",
                            sizeref=2.0 * df_contrats_tri["nombre_offres"].max() / (110.0 ** 2),
                            sizemin=18,
                            color=df_contrats_tri["nombre_offres"],
                            colorscale="Blues",
                            line=dict(width=2, color="white"),
                        ),
                        text=[
                            f"{row.type_contrat}<br>{row.nombre_offres}"
                            for row in df_contrats_tri.itertuples()
                        ],
                        textposition="middle center",
                        textfont=dict(size=13, color="white"),
                        hoverinfo="skip",
                    )
                )
                fig_contrats.update_xaxes(visible=False, range=[-1, len(df_contrats_tri)])
                fig_contrats.update_yaxes(visible=False, range=[-1.2, 1.2])
                fig_contrats.update_layout(
                    height=280, margin=dict(t=10, l=10, r=10, b=10), showlegend=False,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                )
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
                st.metric("Offres indiquant un salaire (tous contrats)", f"{nb_avec_salaire} / {nb_total_offres} ({pct}%)")

                df_salaires_cdi = (
                    df_salaires[df_salaires["Type de contrat"] == "CDI"]
                    if "Type de contrat" in df_salaires.columns
                    else df_salaires.iloc[0:0]
                )
                if df_salaires_cdi.empty:
                    st.info("Aucune offre en CDI avec salaire indiqué pour ces critères.")
                else:
                    groupement_choisi = st.radio(
                        "Regrouper les salaires (CDI uniquement) par",
                        ["Poste", "Entreprise"],
                        horizontal=True,
                        key="salaire_groupement",
                    )
                    df_salaires_groupes = (
                        df_salaires_cdi.groupby(groupement_choisi, as_index=False)
                        .agg(
                            nombre_offres=(groupement_choisi, "count"),
                            salaires=("Salaire indiqué", lambda s: " · ".join(sorted(set(s)))),
                        )
                        .sort_values("nombre_offres", ascending=False)
                        .reset_index(drop=True)
                    )
                    st.dataframe(
                        df_salaires_groupes.rename(
                            columns={"nombre_offres": "Nombre d'offres CDI", "salaires": "Salaires indiqués"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

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
