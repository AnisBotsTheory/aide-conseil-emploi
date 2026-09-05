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
from datetime import datetime  # noqa: F401 — utilisé dans l'onglet KPIs avancés ;
# moteur_recherche.py importe aussi datetime mais son __all__ ne le réexporte pas
import plotly.express as px
import plotly.graph_objects as go

from cv_builder import afficher_generateur_cv
from moteur_recherche import *  # noqa: F401,F403 — fonctions de calcul partagées

st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")


st.divider()

tab_cv, tab_profil, tab_entreprises, tab_avance = st.tabs(
    ["🧾 Créer mon CV", "🎯 Tendance par profil", "📇 Fiches entreprises", "🧩 KPIs avancés"]
)


def _afficher_fiche_entreprise(nom_entreprise):
    """
    Affiche la fiche complète d'une entreprise, un accordéon par source (repliés
    par défaut — le libellé de chaque accordéon sert de résumé visible sans tout
    dérouler), puis la liste des sources réellement utilisées. Structure pensée
    pour rester lisible même si d'autres sources s'ajoutent plus tard (Pappers,
    INPI...). Appelée à la fois depuis "Tendance par profil" (onglet Recruteurs)
    et depuis l'onglet "Fiches entreprises" (recherche libre).
    """
    with st.spinner(f"Récupération des informations sur {nom_entreprise}..."):
        fiche = rechercher_entreprise_siren(nom_entreprise)
        offres_entreprise = rechercher_offres_entreprise(nom_entreprise)
        infos_entretien = infos_entretien_entreprise(nom_entreprise, offres_entreprise)
        wikipedia = rechercher_wikipedia_entreprise(nom_entreprise)
        wikidata = rechercher_wikidata_entreprise(wikipedia["wikidata_id"]) if wikipedia else None

    if not fiche and not infos_entretien and not wikipedia:
        st.info(
            f"Aucune information trouvée pour « {nom_entreprise} » — vérifie l'orthographe, "
            "ou l'entreprise n'est pas répertoriée dans les sources disponibles."
        )
        return

    st.markdown(f"**{nom_entreprise}**")
    sources_utilisees = []

    if wikipedia:
        with st.expander(f"📖 Wikipédia — {wikipedia['titre']}"):
            st.markdown(wikipedia["extrait"])
            if wikipedia["url"]:
                st.markdown(f"[Lire l'article complet]({wikipedia['url']})")
        sources_utilisees.append(f"Wikipédia (article « {wikipedia['titre']} »)")

    if wikidata:
        with st.expander("📊 Wikidata — secteurs, effectif, filiales"):
            if wikidata["secteurs"]:
                st.markdown(f"**Secteurs d'intervention :** {', '.join(wikidata['secteurs'])}")
            if wikidata["effectif"]:
                st.markdown(f"**Effectif :** {wikidata['effectif']:,}".replace(",", " ") + " salarié(s)")
            if wikidata["filiales"]:
                st.markdown(f"**Filiales :** {', '.join(wikidata['filiales'])}")
        sources_utilisees.append("Wikidata")

    if infos_entretien and (infos_entretien["description"] or infos_entretien["secteur_libelle"]):
        with st.expander("💼 France Travail — présentation par l'entreprise"):
            if infos_entretien["secteur_libelle"]:
                st.markdown(f"**Domaine d'activité :** {infos_entretien['secteur_libelle']}")
            if infos_entretien["description"]:
                st.markdown(f"**Présentation (par l'entreprise elle-même) :** {infos_entretien['description']}")
            if infos_entretien.get("tranche_effectif"):
                st.markdown(
                    f"**Effectif (déclaré sur l'offre) :** {infos_entretien['tranche_effectif']} "
                    "— déclaratif, présent sur ~20% des offres seulement."
                )
            if infos_entretien.get("entreprise_adaptee"):
                st.markdown("♿ Entreprise adaptée")
            if infos_entretien.get("employeur_handi_engage"):
                st.markdown("🏅 Employeur reconnu \"Handi-engagé\"")
        sources_utilisees.append("France Travail (offre publiée par l'entreprise)")

    if fiche:
        with st.expander("🏛️ Informations administratives (SIRENE)"):
            st.caption(
                "⚠️ Correspondance approximative sur le nom (à vérifier via le lien "
                "ci-dessous), surtout pour un nom court ou courant."
            )
            if fiche["secteur_libelle"]:
                st.markdown(f"**Secteur (NAF) :** {fiche['secteur_libelle']} ({fiche['naf']})")
            elif fiche["naf"]:
                st.markdown(f"**Secteur (code NAF) :** {fiche['naf']}")
            st.markdown(f"**Effectif :** {fiche['tranche_effectif_libelle']}")
            st.markdown(f"**Catégorie :** {fiche['categorie_entreprise'] or 'Non renseignée'}")
            st.markdown(
                "**Présence géographique :** "
                + (
                    f"{fiche['nombre_etablissements_ouverts']} établissement(s) ouvert(s)"
                    if fiche["nombre_etablissements_ouverts"] else "Non renseignée"
                )
            )
            if fiche["adresse"]:
                st.markdown(f"📍 Siège : {fiche['adresse']}")
            if fiche["date_creation"]:
                st.markdown(f"🗓️ Créée le {fiche['date_creation']}")
            if fiche["siret_siege"]:
                st.markdown(f"🔢 SIREN {fiche['siren']} — SIRET (siège) {fiche['siret_siege']}")
            if fiche["est_qualiopi"]:
                st.markdown("🏅 Organisme certifié Qualiopi")
            if fiche["url_annuaire"]:
                st.markdown(f"🔗 [Vérifier sur l'Annuaire des Entreprises]({fiche['url_annuaire']})")
        sources_utilisees.append("Recherche d'entreprises (DINUM — données SIRENE/INSEE)")
    else:
        st.caption(
            "ℹ️ Aucune fiche administrative trouvée pour ce nom dans le répertoire "
            "des entreprises françaises (nom trop générique, entreprise étrangère, "
            "ou diffusion restreinte)."
        )

    if sources_utilisees:
        st.caption("📚 Sources : " + " · ".join(sources_utilisees) + ".")


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
    st.caption(
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
            # Tension et villes qui recrutent partagent la même base de temps : depuis
            # le début du semestre EN COURS (celui qui contient la date d'aujourd'hui).
            aujourdhui = datetime.now()
            if aujourdhui.month <= 6:
                debut_periode = datetime(aujourdhui.year, 1, 1)
                libelle_periode_offres = f"1er semestre {aujourdhui.year}"
            else:
                debut_periode = datetime(aujourdhui.year, 7, 1)
                libelle_periode_offres = f"2e semestre {aujourdhui.year}"
            jours_max_periode_offres = (aujourdhui - debut_periode).days
            titre_libre_cv = st.session_state.get("cv_titre", "").strip()

            sous_tab_tension, sous_tab_recruteurs, sous_tab_certifs, sous_tab_villes = st.tabs(
                ["⚖️ Tension", "🏢 Recruteurs", "🎓 Certifications", "📍 Répartition géographique"]
            )

            with sous_tab_tension:
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
                    with st.spinner("Récupération des offres et demandeurs d'emploi..."):
                        offres_pour_tension = rechercher_offres_completes_elargi(
                            codes_resolus_cv, titre_libre_cv, departement_actif,
                            jours_max=jours_max_periode_offres,
                        )
                        total_dep_offres = len(offres_pour_tension)
                        nb_postes_ouverts = sum(o.get("nombrePostes") or 1 for o in offres_pour_tension)
                        nb_offres_manque_candidats = sum(
                            1 for o in offres_pour_tension if o.get("offresManqueCandidats")
                        )
                        detail_par_poste = []
                        total_offres_officielles = 0
                        periode_offres_officielles = None
                        erreur_offres_officielles = None
                        for label, code in codes_par_poste_cv.items():
                            if not code:
                                continue
                            demandeurs_i, periode_i, erreur_i = demandeurs_emploi_departement(
                                code, departement_actif
                            )
                            detail_par_poste.append((label, demandeurs_i, periode_i, erreur_i))
                            off_i, periode_off_i, erreur_off_i = offres_officielles_departement(code, departement_actif)
                            if erreur_off_i:
                                erreur_offres_officielles = erreur_off_i
                            else:
                                total_offres_officielles += off_i or 0
                                periode_offres_officielles = periode_offres_officielles or periode_off_i
                        total_embauches = 0
                        periode_embauches = None
                        erreur_embauches = None
                        for label, code in codes_par_poste_cv.items():
                            if not code:
                                continue
                            emb_i, periode_emb_i, erreur_emb_i = embauches_departement(code, departement_actif)
                            if erreur_emb_i:
                                erreur_embauches = erreur_emb_i
                            else:
                                total_embauches += emb_i or 0
                                periode_embauches = periode_embauches or periode_emb_i
                        # Indicateur qualitatif (paliers), pas une somme : affiché seulement
                        # pour un poste unique — additionner des paliers de plusieurs postes
                        # n'aurait pas de sens.
                        libelle_tension_officielle, periode_tension_officielle, erreur_tension_officielle = (
                            (None, None, "plusieurs postes sélectionnés")
                            if len(codes_resolus_cv) != 1
                            else perspective_recrutement_departement(codes_resolus_cv[0], departement_actif)
                        )
                    demandeurs_valides = [d for _, d, _, e in detail_par_poste if not e]
                    total_dep_demandeurs = sum(demandeurs_valides) if demandeurs_valides else 0
                    # Période affichée seulement pour un poste unique (ambigu à résumer en
                    # une seule période quand plusieurs postes aux périodes potentiellement
                    # différentes sont sommés).
                    periode_demandeurs = (
                        detail_par_poste[0][2] if len(detail_par_poste) == 1 and not detail_par_poste[0][3] else None
                    )
                    erreur_demandeurs = (
                        None if demandeurs_valides else "toutes les requêtes demandeurs ont échoué"
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

                    if libelle_tension_officielle:
                        st.caption(
                            f"⚖️ Indicateur officiel France Travail de difficulté de recrutement "
                            f"({periode_tension_officielle}) : **{libelle_tension_officielle}** — "
                            "méthode de calcul différente de notre indice ci-dessus (offres/demandeurs), "
                            "présenté en complément qualitatif, pas en remplacement."
                        )

                    if total_dep_offres:
                        c3, c4 = st.columns(2)
                        c3.metric(
                            "Postes ouverts (cumulé)", nb_postes_ouverts,
                            help="Une offre peut proposer plusieurs postes — total réel de postes à pourvoir.",
                        )
                        pct_manque_candidats = round(100 * nb_offres_manque_candidats / total_dep_offres)
                        c4.metric(
                            "Offres signalées difficiles à pourvoir", f"{pct_manque_candidats}%",
                            help=(
                                f"{nb_offres_manque_candidats} offre(s) sur {total_dep_offres} signalée(s) "
                                "par France Travail comme manquant de candidats (champ officiel "
                                "'offresManqueCandidats') — indicateur de tension directement sur ces "
                                "offres, sans dépendre d'une nomenclature différente (contrairement au BMO)."
                            ),
                        )

                    if not erreur_offres_officielles:
                        st.caption(
                            f"📊 Repère officiel France Travail (statistique trimestrielle, {periode_offres_officielles}) : "
                            f"**{total_offres_officielles}** offre(s) enregistrée(s) sur la période — à ne pas confondre "
                            f"avec les **{total_dep_offres}** offres actuellement actives comptées ci-dessus : une offre "
                            "enregistrée peut avoir déjà été pourvue et retirée, l'écart entre les deux n'est donc pas "
                            "une erreur."
                        )
                    if not erreur_embauches:
                        st.metric(
                            f"Embauches réalisées — {periode_embauches}", total_embauches,
                            help=(
                                "Nombre RÉEL de prises de poste (pas des offres publiées) sur ce métier "
                                "dans ce département, source France Travail — le repère le plus concret "
                                "sur la réalité du marché, au-delà du nombre d'offres."
                            ),
                        )

            with sous_tab_recruteurs:
                with st.spinner("Récupération des recruteurs actifs..."):
                    _, _, _, _, df_entreprises, _ = offres_par_ville_elargi(
                        codes_resolus_cv, titre_libre_cv, departement_actif,
                        jours_max=jours_max_periode_offres,
                    )

                st.markdown("##### 🕒 Recruteurs du moment")
                st.caption(
                    f"ℹ️ Recruteurs actifs {libelle_periode_offres} (même base que la tension du "
                    "marché) — ont publié une offre récemment."
                )
                if df_entreprises.empty:
                    st.info(
                        "Aucun nom d'entreprise exploitable — soit aucune offre, soit toutes "
                        "les offres sont diffusées de façon anonyme."
                    )
                else:
                    st.caption(
                        "💡 Les entreprises ou les candidatures spontanées peuvent être pertinentes — "
                        "même sans offre publiée actuellement, ces recruteurs actifs sur ce métier "
                        "peuvent valoir une candidature directe. Pour la fiche complète d'une "
                        "entreprise (secteur, effectif, présentation...), direction l'onglet "
                        "**📇 Fiches entreprises**."
                    )
                    df_entreprises_affiche = df_entreprises.copy()
                    total_offres_entreprises = df_entreprises_affiche["nombre_offres"].sum()
                    df_entreprises_affiche["% des offres"] = (
                        (100 * df_entreprises_affiche["nombre_offres"] / total_offres_entreprises).round(1)
                        if total_offres_entreprises else 0
                    )
                    st.dataframe(
                        df_entreprises_affiche.rename(columns={"entreprise": "Entreprise"})
                        .drop(columns=["villes", "nombre_offres"]),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.divider()
                st.markdown("##### 🚀 Recruteurs à fort potentiel")
                st.caption(
                    "ℹ️ Entreprises susceptibles de recruter dans les 6 prochains mois pour ce métier "
                    "et ce département — MÊME SANS offre publiée actuellement (modèle prédictif basé "
                    "sur l'historique de recrutement). Source : La Bonne Boîte (France Travail). "
                    "Argument de candidature spontanée, à ne pas confondre avec le tableau ci-dessus."
                )
                if len(codes_resolus_cv) != 1:
                    st.info("Disponible pour un seul poste sélectionné à la fois.")
                else:
                    entreprises_potentiel = rechercher_entreprises_potentiel_embauche(
                        codes_resolus_cv[0], departement_actif
                    )
                    if entreprises_potentiel is None:
                        st.info("Aucune donnée disponible pour ces critères.")
                    elif not entreprises_potentiel:
                        st.info("Aucune entreprise à fort potentiel identifiée pour ces critères.")
                    else:
                        df_potentiel = pd.DataFrame(
                            [
                                {
                                    "Entreprise": e.get("company_name") or "N/C",
                                    "Ville": e.get("city") or "N/C",
                                    "Secteur": e.get("naf_label") or "N/C",
                                    "Effectif": (
                                        f"{e.get('headcount_min', 'N/C')} à {e.get('headcount_max', 'N/C')}"
                                    ),
                                    "Score de potentiel": e.get("hiring_potential"),
                                }
                                for e in entreprises_potentiel
                            ]
                        )
                        st.dataframe(df_potentiel, use_container_width=True, hide_index=True)

            with sous_tab_certifs:
                if "cv_suggestions_apercu" not in st.session_state:
                    st.info("Aucune suggestion disponible pour l'instant.")
                else:
                    _, _, _, df_certifs, df_savoir_etre, nb_total_suggestions = st.session_state["cv_suggestions_apercu"]
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
                    st.markdown("##### 🤝 Savoir-être les plus demandés")
                    st.caption(
                        "ℹ️ Champ structuré dédié de l'API Offres d'emploi (qualitesProfessionnelles) — "
                        "pas un repérage par mot-clé, contrairement aux certifications."
                    )
                    if df_savoir_etre.empty:
                        st.info("Aucun savoir-être identifié dans les offres de cet échantillon.")
                    else:
                        st.dataframe(
                            df_savoir_etre.rename(
                                columns={"libelle": "Savoir-être", "nombre_offres": "Nombre d'offres", "pourcentage": "% des offres"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                st.divider()
                st.markdown("##### 📖 Référentiel officiel du métier (ROME)")
                st.caption(
                    "ℹ️ Compétences, savoir-faire et savoir-être TELS QUE DÉFINIS par le "
                    "répertoire officiel — complémentaire des listes ci-dessus (qui reflètent la "
                    "demande réelle des recruteurs, là maintenant). Une fiche par poste sélectionné, "
                    "pas fusionnée en cas de multi-poste."
                )
                for label, code in codes_par_poste_cv.items():
                    if not code:
                        continue
                    fiche_metier = recuperer_fiche_metier(code)
                    with st.expander(f"{label} ({code})"):
                        if not fiche_metier:
                            st.info("Aucune donnée disponible pour ce métier.")
                        else:
                            if fiche_metier["competences"]:
                                st.markdown("**Compétences :** " + ", ".join(fiche_metier["competences"]))
                            if fiche_metier["savoir_faire"]:
                                st.markdown("**Savoir-faire :** " + ", ".join(fiche_metier["savoir_faire"]))
                            if fiche_metier["savoir_etre"]:
                                st.markdown("**Savoir-être :** " + ", ".join(fiche_metier["savoir_etre"]))
                            if fiche_metier["savoirs"]:
                                st.markdown("**Savoirs :** " + ", ".join(fiche_metier["savoirs"]))

            with sous_tab_villes:
                st.caption(
                    f"ℹ️ Répartition {libelle_periode_offres} (même base que la tension et le top "
                    "recruteurs). Basée sur le lieu tel qu'indiqué par l'offre — la plupart n'ont pas "
                    "de géolocalisation précise côté France Travail, les positions approximatives "
                    "sont signalées séparément ci-dessous."
                )

                valeur_dyn, nom_dyn, periode_dyn, erreur_dyn = dynamisme_territoire(departement_actif)
                if not erreur_dyn and valeur_dyn is not None:
                    st.metric(
                        f"Dynamisme de l'emploi — département {departement_actif}", valeur_dyn,
                        help=(
                            f"{nom_dyn or 'Indicateur de dynamisme'} ({periode_dyn}) — indicateur "
                            "territorial officiel France Travail (méthode IA prospective sur le "
                            "trimestre à venir), pas spécifique au poste recherché."
                        ),
                    )

                with st.spinner("Récupération des offres par ville..."):
                    df_villes, total_region, date_min_pub, date_max_pub, _, _ = offres_par_ville_elargi(
                        codes_resolus_cv, titre_libre_cv, departement_actif,
                        jours_max=jours_max_periode_offres,
                    )
                st.metric("Total offres dans la région", total_region)
                # Note (non affichée à l'écran, à la demande) : date_min_pub/date_max_pub
                # donnent la plage de publication réelle des offres renvoyées par l'API —
                # ex: "Offres publiées entre le {date_min_pub[:10]} et le {date_max_pub[:10]}
                # (format AAAA-MM-JJ)". L'API ne filtre pas par ancienneté par défaut : ces
                # offres sont simplement celles encore actives aujourd'hui.
                if df_villes.empty:
                    st.info("Aucune offre trouvée pour ces critères.")
                else:
                    df_carte = df_villes.dropna(subset=["latitude", "longitude"]).copy()
                    nb_offres_approx = (
                        int(df_carte.loc[df_carte["approximatif"], "nombre_offres"].sum())
                        if not df_carte.empty else 0
                    )
                    if not df_carte.empty:
                        if nb_offres_approx > 0:
                            st.caption(
                                f"📍 {nb_offres_approx} offre(s) sur {total_region} n'ont pas de "
                                "coordonnées GPS précises côté France Travail (lieu renseigné au niveau "
                                "département seulement, ou télétravail) — positionnées sur la plus "
                                "grande ville du département, à titre indicatif."
                            )
                        df_carte["latitude"] = df_carte["latitude"].astype(float)
                        df_carte["longitude"] = df_carte["longitude"].astype(float)
                        df_carte["pourcentage"] = (
                            (100 * df_carte["nombre_offres"] / total_region).round(1) if total_region else 0
                        )
                        fig_carte = px.scatter_mapbox(
                            df_carte,
                            lat="latitude", lon="longitude",
                            size="nombre_offres", size_max=30,
                            color="approximatif",
                            color_discrete_map={False: "#0066cc", True: "#e67e22"},
                            hover_name="ville",
                            hover_data={
                                "nombre_offres": True, "pourcentage": ":.1f",
                                "latitude": False, "longitude": False, "approximatif": False,
                            },
                            labels={
                                "nombre_offres": "Nombre d'offres", "pourcentage": "% des offres",
                                "approximatif": "Position approximative",
                            },
                            zoom=8, height=450,
                        )
                        fig_carte.update_layout(
                            mapbox_style="carto-darkmatter",
                            margin=dict(t=0, l=0, r=0, b=0),
                            showlegend=False,
                        )
                        st.plotly_chart(fig_carte, use_container_width=True)
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
# Onglet "Fiches entreprises" — recherche libre par nom, indépendante du poste
# sélectionné dans le CV. Utile pour préparer un entretien ou une candidature
# spontanée sur une entreprise précise, ou pour une agence qui veut qualifier
# un prospect avant de le démarcher.
# ---------------------------------------------------------------------------
with tab_entreprises:
    st.caption(
        "Tape le nom d'une entreprise pour voir sa fiche : secteur, taille, adresse, et — si "
        "elle recrute actuellement sur le poste de ton CV — sa présentation et son domaine "
        "d'activité tels qu'elle les décrit elle-même."
    )

    nom_recherche = st.text_input(
        "Nom de l'entreprise", key="entreprises_nom_recherche", placeholder="ex: Capgemini, Signe+..."
    )
    bouton_rechercher_entreprise = st.button("Rechercher")

    if bouton_rechercher_entreprise:
        if not nom_recherche.strip():
            st.error("Tape un nom d'entreprise avant de lancer la recherche.")
        else:
            _afficher_fiche_entreprise(nom_recherche.strip())

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
        titre_libre_cv_avance = st.session_state.get("cv_titre", "").strip()

        # Auto-déclenchement : se relance seul dès que le poste/département actif change
        # (mis à jour automatiquement par "Tendance par profil"), résultats conservés en
        # session pour rester affichés en revenant sur cet onglet.
        cle_signature_avance = "avance_auto_signature"
        signature_avance_actuelle = (code_rome_actif, tuple(codes_rome_choisis_avance), departement_actif)

        if st.session_state.get(cle_signature_avance) != signature_avance_actuelle:
            with st.spinner("Analyse en cours (contrats, salaires, expérience)..."):
                df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                    repartition_contrats_et_salaires_elargi(
                        codes_rome_choisis_avance, titre_libre_cv_avance, departement_actif,
                    )
                )
            st.session_state["avance_resultats"] = (
                df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience,
            )
            st.session_state[cle_signature_avance] = signature_avance_actuelle

        if "avance_resultats" in st.session_state:
            df_contrats, df_salaires, nb_avec_salaire, nb_total_offres, df_experience = (
                st.session_state["avance_resultats"]
            )

            st.divider()
            st.markdown("#### 📋 Répartition par type de contrat")
            if df_contrats.empty:
                st.info("Aucune donnée de type de contrat disponible pour ces critères.")
            else:
                df_contrats_tri = df_contrats.sort_values("nombre_offres", ascending=False).reset_index(drop=True)
                # Palette distincte par type de contrat (au lieu d'un dégradé de bleu par
                # volume, qui rendait les petites sphères ternes/grises) — une couleur vive
                # propre à chaque type, cycle si plus de types que de couleurs prévues.
                palette_contrats = ["#2E86DE", "#EE5A6F", "#10AC84", "#F9A826", "#8854D0", "#01A3A4"]
                couleurs_contrats = [
                    palette_contrats[i % len(palette_contrats)] for i in range(len(df_contrats_tri))
                ]
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
                            color=couleurs_contrats,
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

            st.divider()
            st.markdown("#### 💰 Fourchette de salaire proposée")
            if code_rome_actif != "MULTI" and code_rome_actif != "TOUS":
                valeur_sal, nom_sal, periode_sal, erreur_sal = salaires_officiels_metier(
                    code_rome_actif, code_territoire=departement_actif, code_type_territoire="DEP",
                )
                if not erreur_sal and valeur_sal is not None:
                    st.caption(
                        f"📊 Repère officiel France Travail — **{nom_sal or 'salaire en poste'}** "
                        f"({periode_sal}) : **{valeur_sal}** — salaires réels des salariés déjà en "
                        "poste (pas des salaires proposés sur une offre), à titre de comparaison "
                        "avec la fourchette ci-dessous."
                    )
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
                df_experience_tri = df_experience.sort_values("nombre_offres", ascending=False)
                fig_experience = px.treemap(
                    df_experience_tri,
                    path=[px.Constant(""), "experience"],
                    values="nombre_offres",
                    color="nombre_offres",
                    color_continuous_scale="Tealgrn",
                )
                fig_experience.update_traces(
                    textinfo="label+value", texttemplate="%{label}<br>%{value}",
                    marker=dict(line=dict(width=2, color="#0e1117")),
                )
                fig_experience.update_layout(
                    height=280, margin=dict(t=10, l=10, r=10, b=10), coloraxis_showscale=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_experience, use_container_width=True)

            st.divider()
            st.markdown("#### 🎯 Difficulté de recrutement (BMO)")
            st.info(
                "⚠️ Pas encore branché — c'est un indicateur annuel et déclaratif (enquête "
                "employeurs), différent des données d'offres réelles utilisées ailleurs dans "
                "l'app. Dis-moi si tu veux qu'on l'ajoute."
            )
