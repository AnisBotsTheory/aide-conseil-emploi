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
        "Analyse du marché pour le(s) poste(s) sélectionné(s) dans votre CV : où sont les offres "
        "près de chez vous, le volume national, et le niveau de tension du marché sur ce métier."
    )

    postes_cv = st.session_state.get("cv_postes_recherche", [])
    codes_par_poste_cv = st.session_state.get("cv_codes_par_poste", {})
    codes_resolus_cv = [c for c in codes_par_poste_cv.values() if c]
    departement_cv = st.session_state.get("cv_departement") or "13"

    if not postes_cv:
        st.info(
            "👉 Renseigne un poste recherché dans l'onglet **🧾 Créer mon CV**, puis sélectionne au "
            "moins une suggestion parmi les étiquettes proposées — l'analyse se lance ensuite "
            "automatiquement, pas besoin de ressaisir quoi que ce soit ici."
        )
    else:
        # Poste(s) et département viennent uniquement de "Créer mon CV" (étiquettes de
        # suggestion + champ département) — plus aucun champ affiché ici.
        cle_auto_signature = "profil_auto_analyse_signature"
        signature_actuelle = (tuple(postes_cv), departement_cv)

        if st.session_state.get(cle_auto_signature) != signature_actuelle:
            with st.spinner("Analyse du marché en cours..."):
                if not codes_resolus_cv:
                    st.session_state["df_rome_profil"] = pd.DataFrame()
                else:
                    st.session_state["df_rome_profil"] = pd.DataFrame(
                        [
                            {"code_rome": code, "libelle": label, "nb_offres_echantillon": None}
                            for label, code in codes_par_poste_cv.items()
                            if code
                        ]
                    )
                    if len(codes_resolus_cv) == 1:
                        st.session_state["code_rome_choisi"] = codes_resolus_cv[0]
                    else:
                        st.session_state["code_rome_choisi"] = "MULTI"
                    st.session_state["codes_rome_choisis"] = codes_resolus_cv
                    st.session_state["mots_cles_profil_actif"] = " / ".join(postes_cv)

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
            # Tous les indicateurs de cet onglet (tension, top recruteurs, top villes)
            # partagent désormais la même base de temps : depuis le début du semestre EN
            # COURS (celui qui contient la date d'aujourd'hui). Poste et secteur restent
            # les mêmes filtres que partout ailleurs.
            aujourdhui = datetime.now()
            if aujourdhui.month <= 6:
                debut_periode = datetime(aujourdhui.year, 1, 1)
                libelle_periode_offres = f"1er semestre {aujourdhui.year}"
            else:
                debut_periode = datetime(aujourdhui.year, 7, 1)
                libelle_periode_offres = f"2e semestre {aujourdhui.year}"
            jours_max_periode_offres = (aujourdhui - debut_periode).days

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
                    f"ℹ️ Les offres comptent depuis le début du semestre en cours (actuellement le "
                    f"{libelle_periode_offres}) ; les demandeurs d'emploi restent une statistique "
                    "officielle trimestrielle (non filtrable par date)."
                    + (
                        " Plusieurs postes sélectionnés : tension calculée sur la somme des offres "
                        "et des demandeurs d'emploi de l'ensemble des postes retenus, pas sur un "
                        "indicateur officiel par métier unique — détail par poste ci-dessous."
                        if recherche_multi else ""
                    )
                )
                detail_par_poste = []
                if recherche_multi:
                    with st.spinner("Récupération des demandeurs d'emploi..."):
                        for label, code in codes_par_poste_cv.items():
                            if not code:
                                continue
                            offres_i = volumes_departement_offres(
                                code, departement_actif, jours_max=jours_max_periode_offres
                            )
                            demandeurs_i, periode_i, erreur_i = demandeurs_emploi_departement(
                                code, departement_actif
                            )
                            detail_par_poste.append((label, offres_i, demandeurs_i, erreur_i))
                    total_dep_offres = sum(o for _, o, _, _ in detail_par_poste)
                    demandeurs_valides = [d for _, _, d, e in detail_par_poste if not e]
                    total_dep_demandeurs = sum(demandeurs_valides) if demandeurs_valides else 0
                    periode_demandeurs = None  # non affiché en multi (périodes potentiellement différentes par poste)
                    erreur_demandeurs = (
                        None if demandeurs_valides else "toutes les requêtes demandeurs ont échoué"
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
                    c1.metric("Offres", total_dep_offres)
                    c2.metric(
                        f"Demandeurs d'emploi{' — ' + periode_demandeurs if periode_demandeurs else ''}",
                        total_dep_demandeurs,
                    )

                if recherche_multi and detail_par_poste:
                    with st.expander("🔎 Détail par poste (pour repérer un éventuel poste hors-sujet)"):
                        for label, offres_i, demandeurs_i, erreur_i in detail_par_poste:
                            if erreur_i:
                                st.caption(f"**{label}** — demandeurs indisponibles ({erreur_i})")
                            else:
                                st.caption(f"**{label}** — {offres_i} offre(s), {demandeurs_i} demandeur(s)")

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

            if "cv_suggestions_apercu" in st.session_state:
                _, _, _, df_certifs, nb_total_suggestions = st.session_state["cv_suggestions_apercu"]
                st.markdown("#### 🎓 Certifications les plus demandées")
                st.caption(
                    "ℹ️ France Travail n'a pas de champ dédié aux certifications — repérées par "
                    "mot-clé dans les offres réelles (même échantillon que les suggestions de "
                    "compétences de « Créer mon CV »), couverture partielle par construction."
                )
                if df_certifs.empty:
                    st.info("Aucune certification identifiée dans les offres de cet échantillon.")
                else:
                    st.dataframe(
                        df_certifs.rename(
                            columns={"libelle": "Certification", "nombre_offres": "Nombre d'offres", "pourcentage": "% des offres"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.divider()

            with st.spinner("Récupération des recruteurs actifs..."):
                if recherche_multi:
                    _, _, _, _, df_entreprises, _ = offres_par_ville_multi(
                        codes_resolus_cv, departement_actif, jours_max=jours_max_periode_offres,
                    )
                else:
                    _, _, _, _, df_entreprises, _ = offres_par_ville(
                        code_rome_choisi, departement_actif, jours_max=jours_max_periode_offres,
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
                if recherche_multi:
                    df_villes, total_region, date_min_pub, date_max_pub, _, _ = offres_par_ville_multi(
                        codes_resolus_cv, departement_actif, jours_max=jours_max_periode_offres,
                    )
                else:
                    df_villes, total_region, date_min_pub, date_max_pub, _, _ = offres_par_ville(
                        code_rome_choisi, departement_actif, jours_max=jours_max_periode_offres,
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
