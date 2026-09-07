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
import re
import random
from collections import Counter
from datetime import datetime  # noqa: F401 — utilisé dans l'onglet Compléments d'analyse ;
# moteur_recherche.py importe aussi datetime mais son __all__ ne le réexporte pas
import plotly.express as px
import plotly.graph_objects as go

from cv_builder import afficher_generateur_cv
from moteur_recherche import *  # noqa: F401,F403 — fonctions de calcul partagées

st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")


st.divider()

tab_cv, tab_profil, tab_avance, tab_evenements = st.tabs(
    ["🧾 Créer mon CV", "🎯 Analyse principale", "📊 Compléments d'analyse", "📅 Événements"]
)


_RE_ARRONDISSEMENT_PARIS_LYON_MARSEILLE = re.compile(
    r"^(paris|lyon|marseille)\b\s*\d{0,2}\s*(er|ème|e)?\s*(arrondissement)?\s*$", re.IGNORECASE
)
_RE_ARRONDISSEMENT_GENERIQUE = re.compile(r"\s+\d+\s*(er|e|ème)?\s+arrondissement.*$", re.IGNORECASE)
_RE_SUFFIXE_DEPARTEMENT = re.compile(r"\s*\((?:dept\.?|dépt\.?|département|departement)\)\s*$", re.IGNORECASE)


def _nom_ville_simplifie(libelle_brut):
    """
    Simplifie un libellé de lieu France Travail (souvent "code - Nom commune",
    parfois avec un arrondissement) en un nom de ville regroupable — utilisé
    pour le classement des villes : sans ça, plusieurs variantes d'un même
    lieu comptaient comme des villes séparées dans le classement (constaté en
    usage réel : "Paris", "PARIS", "PARIS 10", "PARIS 15", "PARIS 18" et
    "Paris (Dept.)" apparaissaient comme 6 lignes distinctes au lieu d'une
    seule "Paris"). Gère : préfixe "code - ", suffixe "(Dept.)"/"(Département)",
    arrondissement de Paris/Lyon/Marseille (avec ou sans le mot "Arrondissement"
    explicite, ex: "PARIS 10" comme "Paris 10ème Arrondissement"), variante
    générique "Ville Nème Arrondissement" pour tout autre nom de ville, et
    normalisation de casse pour une ville renvoyée tout en majuscules.
    """
    nom = libelle_brut.split(" - ", 1)[-1].strip() if " - " in libelle_brut else libelle_brut.strip()
    nom = _RE_SUFFIXE_DEPARTEMENT.sub("", nom).strip()

    correspondance_grande_ville = _RE_ARRONDISSEMENT_PARIS_LYON_MARSEILLE.match(nom)
    if correspondance_grande_ville:
        return correspondance_grande_ville.group(1).capitalize()

    nom = _RE_ARRONDISSEMENT_GENERIQUE.sub("", nom).strip()
    if nom.isupper():
        # Ville renvoyée tout en majuscules (ex: "PARIS") : normalisée en casse standard
        # pour se regrouper avec sa variante correctement casée ("Paris"). Pas de
        # capitalisation "intelligente" mot par mot (les particules "sur", "en", "la"
        # devraient rester en minuscule dans l'orthographe correcte, ce qu'un .title()
        # ne sait pas faire) — au moins la première lettre de chaque mot est juste pour
        # les cas simples les plus courants.
        nom = nom.title()
    return nom.strip() or libelle_brut


# ---------------------------------------------------------------------------
# Onglet 0 : Créer mon CV (exécuté en premier : sa synchronisation vers
# "Métier recherché" doit être en place avant que ce champ ne soit affiché)
# ---------------------------------------------------------------------------
with tab_cv:
    afficher_generateur_cv(fonction_analyse_competences=analyser_competences_elargi)

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
    departement_cv = st.session_state.get("cv_departement")

    if not postes_cv:
        st.info(
            "👉 Renseigne un poste recherché dans l'onglet **🧾 Créer mon CV**, puis sélectionne au "
            "moins une suggestion parmi les étiquettes proposées — l'analyse se lance ensuite "
            "automatiquement, pas besoin de ressaisir quoi que ce soit ici."
        )
    elif not departement_cv:
        # Cas de bord : le département a été effacé après la sélection du poste (retour à
        # "Non renseigné" dans "Créer mon CV") — pas de repli silencieux sur un département
        # arbitraire, on redemande explicitement.
        st.info(
            "👉 Ton département de résidence n'est plus renseigné — retourne dans l'onglet "
            "**🧾 Créer mon CV** pour le sélectionner avant de relancer l'analyse."
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

    # Guard "and departement_cv" : évite d'afficher une analyse en cache (calculée lors
    # d'un run précédent où le département était bien renseigné) si l'utilisateur a
    # depuis effacé son département — sinon le message "renseigne ton département"
    # ci-dessus s'affichait juste au-dessus d'une analyse quand même visible en dessous.
    if "df_rome_profil" in st.session_state and departement_cv:
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

            sous_tab_recruteurs, sous_tab_certifs, sous_tab_villes = st.tabs(
                ["🏢 Top Recruteurs", "🎓 Compétences", "📍 Dynamisme géographique"]
            )

            with sous_tab_recruteurs:
                with st.spinner("Récupération des recruteurs actifs..."):
                    _, _, _, _, df_entreprises, _ = offres_par_ville_elargi(
                        codes_resolus_cv, titre_libre_cv, departement_actif,
                        jours_max=jours_max_periode_offres,
                    )

                st.markdown("##### 🕒 Recruteurs du moment")
                st.caption(
                    f"ℹ️ Recruteurs actifs {libelle_periode_offres} — ont publié une offre "
                    "récemment sur le métier et le département sélectionnés. Argument de "
                    "candidature ciblée."
                )
                if df_entreprises.empty:
                    st.info(
                        "Aucun nom d'entreprise exploitable — soit aucune offre, soit toutes "
                        "les offres sont diffusées de façon anonyme."
                    )
                else:
                    df_entreprises_affiche = df_entreprises.copy()
                    total_offres_entreprises = df_entreprises_affiche["nombre_offres"].sum()
                    df_entreprises_affiche["Part des offres"] = (
                        (100 * df_entreprises_affiche["nombre_offres"] / total_offres_entreprises).round(1)
                        if total_offres_entreprises else 0
                    )
                    st.dataframe(
                        df_entreprises_affiche.rename(columns={"entreprise": "Entreprise"})
                        .drop(columns=["villes", "nombre_offres"]),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Part des offres": st.column_config.NumberColumn(
                                "Part d'occurrence", format="%.1f%%"
                            )
                        },
                    )

                st.divider()
                st.markdown("##### 🚀 Recruteurs à fort potentiel")
                st.caption(
                    "ℹ️ Entreprises susceptibles de recruter dans les 6 prochains mois pour ce "
                    "métier et ce département — MÊME SANS offre publiée actuellement (modèle "
                    "prédictif basé sur l'historique de recrutement). Argument de candidature "
                    "spontanée. Source : La Bonne Boîte (France Travail)."
                )
                if not codes_resolus_cv:
                    st.info("Sélectionne au moins un poste ci-dessus.")
                else:
                    # Un ou plusieurs postes désormais acceptés en un seul appel (le
                    # paramètre "rome" de l'API est déjà un tableau) — l'ancienne
                    # restriction "un seul poste à la fois" bloquait l'affichage même
                    # quand l'API avait bel et bien des résultats pour le premier poste
                    # sélectionné (constaté : le diagnostic, qui ignorait cette règle,
                    # montrait des hits alors que l'écran principal restait bloqué).
                    entreprises_potentiel = rechercher_entreprises_potentiel_embauche(
                        codes_resolus_cv, departement_actif
                    )
                    # Repli national : un "hits":0 / une liste vide au niveau département
                    # est une réponse VALIDE de La Bonne Boîte (son modèle prédictif n'a
                    # simplement pas de données pour ce métier précis dans ce département),
                    # pas forcément une panne — on retente sans filtre département avant
                    # de conclure à une absence totale de données pour ce métier.
                    recherche_nationale_repli = False
                    if entreprises_potentiel is not None and not entreprises_potentiel:
                        entreprises_potentiel_nationales = rechercher_entreprises_potentiel_embauche(
                            codes_resolus_cv, None
                        )
                        if entreprises_potentiel_nationales:
                            entreprises_potentiel = entreprises_potentiel_nationales
                            recherche_nationale_repli = True

                    if entreprises_potentiel is None:
                        st.info(
                            "Aucune donnée disponible pour ces critères — l'appel API a échoué "
                            "(voir le diagnostic ci-dessous pour le détail)."
                        )
                    elif not entreprises_potentiel:
                        st.info(
                            "Aucune entreprise à fort potentiel identifiée pour ce(s) métier(s), ni "
                            "dans ce département ni à l'échelle nationale — La Bonne Boîte n'a pas "
                            "toujours de données prédictives pour tous les métiers (ce n'est pas "
                            "une erreur de l'app, juste une absence de données pour ce cas précis)."
                        )
                    else:
                        if recherche_nationale_repli:
                            st.caption(
                                "ℹ️ Aucun résultat dans le département sélectionné pour ce(s) "
                                "métier(s) — liste ci-dessous à l'échelle nationale à la place."
                            )
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

                with st.expander("🔧 Diagnostic technique La Bonne Boîte (temporaire)"):
                    st.caption(
                        "Teste directement l'appel API pour le(s) poste(s) et le département "
                        "actuellement sélectionnés, et affiche la vraie réponse brute des deux "
                        "endpoints (nombreEntreprise et recherche) — utile pour vérifier pourquoi "
                        "une liste reste vide ou pour confirmer que l'intégration répond bien."
                    )
                    if st.button("Lancer le diagnostic", key="btn_diagnostic_lbb_tendance"):
                        codes_diag = codes_resolus_cv if codes_resolus_cv else ["M1805"]
                        with st.spinner("Test de l'appel La Bonne Boîte en cours..."):
                            resultats_diag_lbb = diagnostiquer_la_bonne_boite(codes_diag, departement_actif)
                        st.json(resultats_diag_lbb)

                st.divider()
                st.info(
                    "📊 Repère général (indépendant de la recherche ci-dessus) : la durée moyenne "
                    "d'un recrutement de cadre en France est stable à 12 semaines depuis 2022 "
                    "(source : Apec, « Pratiques de recrutement des cadres » 2026). Nous n'avons pas "
                    "trouvé de repère aussi solidement sourcé pour les postes non-cadres — à prendre "
                    "avec prudence si tu cherches un point de comparaison sur ce type de poste."
                )

            with sous_tab_certifs:
                if "cv_suggestions_apercu" not in st.session_state:
                    st.info("Aucune suggestion disponible pour l'instant.")
                else:
                    df_comp, _, _, df_certifs, df_savoir_etre, nb_total_suggestions = st.session_state["cv_suggestions_apercu"]
                    st.caption(
                        "ℹ️ Résultat de la recherche sur des offres réelles publiées sur France "
                        "Travail pour le(s) poste(s) sélectionné(s)."
                    )
                    if df_certifs.empty:
                        st.info("Aucune certification identifiée dans les offres de cet échantillon.")
                    else:
                        st.dataframe(
                            df_certifs.drop(columns=["pourcentage"]).rename(
                                columns={"libelle": "Certification", "nombre_offres": "Occurrences"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    with st.expander("🔧 Vérifier un résultat suspect (temporaire)"):
                        st.caption(
                            "Si une certification semble déplacée pour ce métier (ex: « ADR » sur "
                            "un poste de management), tape son terme exact ci-dessous — affiche les "
                            "extraits de texte réels où il matche, pour distinguer un vrai signal "
                            "d'un faux positif (ex: « adr » à l'intérieur de « cadre »)."
                        )
                        terme_a_verifier = st.text_input(
                            "Terme à vérifier (ex: adr)", key="terme_diagnostic_certif"
                        )
                        if st.button("Vérifier", key="btn_diagnostic_terme_certif") and terme_a_verifier.strip():
                            with st.spinner("Recherche des occurrences en cours..."):
                                resultats_verif = diagnostiquer_terme_certification(
                                    terme_a_verifier.strip(), codes_resolus_cv, departement_actif,
                                    mots_cles_libres=titre_libre_cv,
                                )
                            st.json(resultats_verif)

                    st.divider()
                    st.markdown("##### 🛠️ Savoir-faire les plus demandés")
                    st.caption(
                        "ℹ️ Résultat de la recherche sur des offres réelles publiées sur France "
                        "Travail pour le(s) poste(s) sélectionné(s) — compétences pratiques/"
                        "techniques mentionnées (hors outils, langages et certifications, "
                        "affichés séparément)."
                    )
                    if df_comp.empty:
                        st.info("Aucun savoir-faire identifié dans les offres de cet échantillon.")
                    else:
                        st.dataframe(
                            df_comp.drop(columns=["pourcentage"]).rename(
                                columns={"libelle": "Savoir-faire", "nombre_offres": "Occurrences"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    st.divider()
                    st.markdown("##### 🤝 Savoir-être les plus demandés")
                    st.caption(
                        "ℹ️ Résultat de la recherche sur des offres réelles publiées sur France "
                        "Travail pour le(s) poste(s) sélectionné(s)."
                    )
                    if df_savoir_etre.empty:
                        st.info("Aucun savoir-être identifié dans les offres de cet échantillon.")
                    else:
                        st.dataframe(
                            df_savoir_etre.drop(columns=["pourcentage"]).rename(
                                columns={"libelle": "Savoir-être", "nombre_offres": "Occurrences"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    with st.expander("🔧 Diagnostic technique Savoir-être (temporaire)"):
                        st.caption(
                            "Récupère quelques offres brutes pour le poste actuel et affiche "
                            "directement le contenu du champ 'qualitesProfessionnelles' tel que "
                            "renvoyé par l'API — utile pour vérifier qu'il est bien rempli en pratique "
                            "quand la liste ci-dessus reste vide."
                        )
                        if st.button("Lancer le diagnostic", key="btn_diagnostic_savoir_etre"):
                            code_diag_se = codes_resolus_cv[0] if codes_resolus_cv else "M1805"
                            with st.spinner("Récupération d'un échantillon d'offres..."):
                                resultats_diag_se = diagnostiquer_savoir_etre(code_diag_se, departement_actif)
                            st.json(resultats_diag_se)

                st.divider()
                st.markdown("##### 📖 Référentiel officiel du métier (ROME)")
                st.caption(
                    "ℹ️ Compétences et savoir-être TELS QUE DÉFINIS par le répertoire officiel — "
                    "complémentaire des listes ci-dessus (qui reflètent la demande réelle des "
                    "recruteurs, là maintenant). Une fiche par poste sélectionné, pas fusionnée "
                    "en cas de multi-poste."
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
                            if fiche_metier["savoir_etre"]:
                                st.markdown("**Savoir-être :** " + ", ".join(fiche_metier["savoir_etre"]))
                            if fiche_metier["savoirs"]:
                                st.markdown("**Savoirs :** " + ", ".join(fiche_metier["savoirs"]))

                with st.expander("🔧 Diagnostic technique Fiches métiers ROME (temporaire)"):
                    st.caption(
                        "Teste directement l'appel API pour le premier poste sélectionné et affiche "
                        "la vraie réponse brute — utile pour vérifier pourquoi une fiche reste vide "
                        "ou pour confirmer que l'intégration répond bien."
                    )
                    if st.button("Lancer le diagnostic", key="btn_diagnostic_fiche_metier_tendance"):
                        code_diag_fm = codes_resolus_cv[0] if codes_resolus_cv else "M1805"
                        with st.spinner("Test de l'appel Fiches métiers en cours..."):
                            resultats_diag_fm = diagnostiquer_fiche_metier(code_diag_fm)
                        st.json(resultats_diag_fm)

            with sous_tab_villes:
                st.caption(
                    f"ℹ️ Classement {libelle_periode_offres} (même base que la tension et le top "
                    "recruteurs), et comparaison du dynamisme économique du département avec "
                    "quelques territoires contrastés."
                )

                # --- Classement des villes (remplace la carte) ---
                st.markdown("##### 🏆 Classement des villes")
                with st.spinner("Récupération des offres par ville..."):
                    df_villes, total_region, date_min_pub, date_max_pub, _, _ = offres_par_ville_elargi(
                        codes_resolus_cv, titre_libre_cv, departement_actif,
                        jours_max=jours_max_periode_offres,
                    )
                # Note (non affichée à l'écran, à la demande) : date_min_pub/date_max_pub
                # donnent la plage de publication réelle des offres renvoyées par l'API —
                # ex: "Offres publiées entre le {date_min_pub[:10]} et le {date_max_pub[:10]}
                # (format AAAA-MM-JJ)". L'API ne filtre pas par ancienneté par défaut : ces
                # offres sont simplement celles encore actives aujourd'hui.
                if df_villes.empty:
                    st.info("Aucune offre trouvée pour ces critères.")
                else:
                    # Regroupement des arrondissements/quartiers d'une même ville (ex:
                    # "Marseille 1er Arrondissement" et "Marseille 6e Arrondissement"
                    # comptaient jusqu'ici comme deux villes séparées).
                    df_classement = df_villes.copy()
                    df_classement["ville"] = df_classement["ville"].map(_nom_ville_simplifie)
                    df_classement = (
                        df_classement.groupby("ville", as_index=False)["nombre_offres"].sum()
                        .sort_values("nombre_offres", ascending=False)
                        .reset_index(drop=True)
                    )
                    df_classement.insert(0, "Classement", range(1, len(df_classement) + 1))
                    df_classement["Part des offres"] = (
                        (100 * df_classement["nombre_offres"] / total_region).round(1) if total_region else 0
                    )
                    st.dataframe(
                        df_classement.rename(columns={"ville": "Ville"})[
                            ["Classement", "Ville", "Part des offres"]
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Part des offres": st.column_config.NumberColumn(
                                "Part d'occurrence", format="%.1f%%"
                            )
                        },
                    )

                st.divider()
                # --- Dynamisme géographique : graphe comparatif gradué ---
                # Placé APRÈS le classement des villes : contrairement au reste de cet
                # onglet, cet indicateur est TERRITORIAL et GLOBAL — il ne dépend pas du
                # ou des poste(s) recherché(s) (l'API l'interroge avec un code générique
                # "MOYENNE", jamais un code ROME). Il vient donc en complément d'ambiance
                # économique du département, pas comme un résultat lié à ta recherche.
                st.markdown("##### 📊 Dynamisme géographique")
                st.caption(
                    "ℹ️ Contrairement aux sections précédentes, cet indicateur ne dépend PAS "
                    "du ou des poste(s) recherché(s) — c'est un signal général sur l'économie "
                    "du département dans son ensemble, pas sur ton métier précis."
                )
                # Comparaison avec Paris et Lyon (toujours inclus) + des départements tirés
                # au sort (stable tant que le département actif ne change pas, pour ne pas
                # re-tirer à chaque interaction) — ton département est TOUJOURS inclus en plus.
                cle_dep_aleatoires = "dynamisme_departements_aleatoires"
                departements_fixes = ["75", "69"]  # Paris, Lyon — toujours affichés en comparatif
                if st.session_state.get(f"{cle_dep_aleatoires}_pour") != departement_actif:
                    exclus = set(departements_fixes + [departement_actif])
                    autres_departements = [d for d in DEPARTEMENTS_VERS_NOM if d not in exclus]
                    # Échantillon élargi (3 -> 6) : augmente les chances de couvrir les 4
                    # paliers de valeur observés en pratique, plutôt que de laisser un bloc
                    # systématiquement vide faute d'avoir tiré le bon département.
                    st.session_state[cle_dep_aleatoires] = random.sample(
                        autres_departements, min(6, len(autres_departements))
                    )
                    st.session_state[f"{cle_dep_aleatoires}_pour"] = departement_actif
                departements_comparaison = list(dict.fromkeys(
                    [departement_actif] + departements_fixes + st.session_state[cle_dep_aleatoires]
                ))

                resultats_dynamisme = []
                for dep_comp in departements_comparaison:
                    val_dep, _, _, err_dep = dynamisme_territoire(dep_comp)
                    if not err_dep and val_dep is not None:
                        resultats_dynamisme.append({"departement": dep_comp, "valeur": val_dep})

                if len(resultats_dynamisme) < 2:
                    st.info("Comparaison indisponible pour le moment.")
                else:
                    st.caption(
                        "ℹ️ Indicateur composite officiel (source : France Travail & Acoss) mesurant "
                        "l'évolution COMPARÉE (pas le niveau absolu) des effectifs salariés, des "
                        "embauches et des offres diffusées, anticipée pour le trimestre à venir — un "
                        "petit département peut donc afficher une progression relative forte sur une "
                        "petite base, sans que ça signifie plus d'activité en valeur absolue qu'un "
                        "grand bassin d'emploi."
                    )
                    # Blocs pour les valeurs 1 à 4 (plage observée jusqu'ici en pratique) —
                    # tout palier resté VIDE après l'échantillonnage (aucun département tiré
                    # n'y correspond) est retiré du graphique plutôt qu'affiché comme bloc gris
                    # sans contenu ; une éventuelle valeur hors plage (défensif, l'échelle
                    # réelle n'étant pas documentée officiellement) est conservée si observée.
                    valeurs_par_dep = {v: [] for v in (1, 2, 3, 4)}
                    for r in resultats_dynamisme:
                        valeurs_par_dep.setdefault(round(r["valeur"]), []).append(r["departement"])
                    valeurs_par_dep = {v: deps for v, deps in valeurs_par_dep.items() if deps}
                    valeurs_graduees = sorted(valeurs_par_dep.keys())

                    palette_dyn = ["#2E86DE", "#10AC84", "#F9A826", "#EE5A6F", "#01A3A4"]
                    nb_blocs = len(valeurs_graduees)
                    couleurs_blocs = [palette_dyn[i % len(palette_dyn)] for i in range(nb_blocs)]
                    # Le département actif est mis en évidence par une COULEUR (violet) plutôt
                    # que par un texte type "(toi)", jugé peu professionnel pour cet usage.
                    # Chaque nom est suivi de son code département (ex: "Paris - 75").
                    textes_blocs = [
                        "<br>".join(
                            (
                                f'<span style="color:#5B21B6"><b>{DEPARTEMENTS_VERS_NOM.get(d, d)} - {d}</b></span>'
                                if d == departement_actif
                                else f"{DEPARTEMENTS_VERS_NOM.get(d, d)} - {d}"
                            )
                            for d in valeurs_par_dep[v]
                        )
                        for v in valeurs_graduees
                    ]
                    fig_dyn = go.Figure(
                        go.Bar(
                            x=[1] * nb_blocs,
                            y=[""] * nb_blocs,
                            base=list(range(nb_blocs)),
                            orientation="h",
                            marker=dict(color=couleurs_blocs, line=dict(width=1, color="#0e1117")),
                            text=textes_blocs,
                            textposition="inside",
                            insidetextanchor="middle",
                            textfont=dict(size=11, color="white"),
                            hoverinfo="skip",
                        )
                    )
                    fig_dyn.update_xaxes(
                        visible=True,
                        tickmode="array",
                        tickvals=[i + 0.5 for i in range(nb_blocs)],
                        ticktext=[str(v) for v in valeurs_graduees],
                        tickfont=dict(size=12, color="white"),
                        showgrid=False,
                        zeroline=False,
                    )
                    fig_dyn.update_yaxes(visible=False)
                    fig_dyn.update_layout(
                        height=130, margin=dict(t=20, l=10, r=10, b=30),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        showlegend=False,
                    )
                    st.plotly_chart(fig_dyn, use_container_width=True)

                    with st.expander("🔧 Diagnostic technique Dynamisme (temporaire)"):
                        st.caption(
                            "Teste directement l'appel API pour ton département et affiche le "
                            "statut HTTP et la réponse brute — utile pour confirmer que l'appel se "
                            "déroule bien plutôt que de se fier uniquement à la valeur affichée."
                        )
                        if st.button("Lancer le diagnostic", key="btn_diagnostic_dynamisme"):
                            with st.spinner("Test de l'appel Dynamisme en cours..."):
                                resultats_diag_dyn = diagnostiquer_dynamisme_territoire(departement_actif)
                            st.json(resultats_diag_dyn)

# ---------------------------------------------------------------------------
# Onglet "Compléments d'analyse"
# ---------------------------------------------------------------------------
with tab_avance:
    if "code_rome_choisi" not in st.session_state:
        st.info(
            "👉 Renseigne un poste dans l'onglet **🧾 Créer mon CV** — les Compléments d'analyse "
            "s'appuient sur l'analyse automatique de l'onglet Analyse principale."
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
                # Taille proportionnelle à l'AIRE du nombre d'offres brut, SANS compression
                # supplémentaire (une racine carrée avait été appliquée en plus du sizemode="area"
                # déjà en place, ce qui écrasait trop l'écart entre les valeurs — un 50 rendait
                # quasiment la même taille qu'un 20, un 10 la même taille qu'un 5). La lisibilité
                # du texte dans les petites sphères est assurée autrement : un plancher de taille
                # (sizemin) ET une police PAR SPHÈRE, plus petite pour les petites valeurs plutôt
                # que de gonfler artificiellement leur taille.
                tailles_base = df_contrats_tri["nombre_offres"]
                valeur_max = tailles_base.max()
                # Police entre 10 et 18 pt, sur la racine carrée du ratio à la valeur max (la
                # racine carrée reflète le rayon, dimension realmente perçue visuellement, pas
                # l'aire) — reste lisible même sur la plus petite sphère, sans être minuscule.
                polices_contrats = [
                    round(10 + 8 * ((v / valeur_max) ** 0.5), 1) for v in tailles_base
                ]
                # Écartement horizontal entre sphères (x2.4, au lieu de positions 0,1,2...) pour
                # garantir un espace visible entre elles même quand il y a plusieurs types de
                # contrat — sans ça, des sphères voisines se touchaient ou se chevauchaient
                # (constaté avec 5 types de contrat affichés simultanément).
                positions_x = [i * 2.4 for i in range(len(df_contrats_tri))]
                fig_contrats = go.Figure(
                    go.Scatter(
                        x=positions_x,
                        y=[0] * len(df_contrats_tri),
                        mode="markers+text",
                        marker=dict(
                            # sizemode="area" rend l'AIRE du cercle proportionnelle à
                            # nombre_offres — le diamètre cible maximal (150) fixe la taille de
                            # la plus grande sphère, sizemin garantit un plancher pour que même
                            # la plus petite valeur reste visible et manipulable.
                            size=tailles_base,
                            sizemode="area",
                            sizeref=2.0 * valeur_max / (150.0 ** 2),
                            sizemin=38,
                            color=couleurs_contrats,
                            line=dict(width=2, color="white"),
                        ),
                        text=[
                            # Intitulé en 2 mots (ex: "Profession commerciale") : saut de ligne
                            # après le premier mot plutôt que de laisser le texte déborder à
                            # l'horizontale hors de la sphère et chevaucher la voisine.
                            f"{row.type_contrat.replace(' ', '<br>', 1)}<br>{row.nombre_offres}"
                            for row in df_contrats_tri.itertuples()
                        ],
                        textposition="middle center",
                        textfont=dict(size=polices_contrats, color="white"),
                        hoverinfo="skip",
                    )
                )
                fig_contrats.update_xaxes(visible=False, range=[-1.2, positions_x[-1] + 1.2 if positions_x else 1])
                fig_contrats.update_yaxes(visible=False, range=[-1.3, 1.3])
                fig_contrats.update_layout(
                    height=320, margin=dict(t=10, l=10, r=10, b=10), showlegend=False,
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
                df_salaires_cdi = (
                    df_salaires[df_salaires["Type de contrat"] == "CDI"]
                    if "Type de contrat" in df_salaires.columns
                    else df_salaires.iloc[0:0]
                )
                if df_salaires_cdi.empty:
                    st.info("Aucune offre en CDI avec salaire indiqué pour ces critères.")
                else:
                    # Jauge graduée : un bloc par valeur DISTINCTE trouvée dans l'échantillon
                    # (arrondie au 5 000 € près pour regrouper des valeurs proches et limiter
                    # le nombre de graduations affichées — un arrondi au millier produisait
                    # trop de graduations serrées, illisibles les unes sous les autres),
                    # triées croissant — pas une simple barre continue du minimum absolu au
                    # maximum absolu, mais une graduation qui matérialise les paliers réels
                    # observés (ex: 30 000 € puis 50 000 € puis 60 000 € puis 80 000 €).
                    bornes = [_extraire_bornes_salaire(s) for s in df_salaires_cdi["Salaire indiqué"]]
                    toutes_valeurs = []
                    for borne_min, borne_max in bornes:
                        if borne_min is not None:
                            toutes_valeurs.append(borne_min)
                        if borne_max is not None:
                            toutes_valeurs.append(borne_max)

                    if not toutes_valeurs:
                        st.info("Salaires indiqués dans un format non reconnu, jauge non disponible.")
                    else:
                        # Pas d'arrondi calé dynamiquement sur l'étendue réelle des valeurs,
                        # plutôt qu'un arrondi fixe au 5 000 € — avec beaucoup d'offres, un pas
                        # fixe pouvait produire des dizaines de graduations illisibles et
                        # chevauchées (constaté avec 178 offres, plage 5 000 € à 600 000 €).
                        # Objectif : environ 8 à 10 blocs, quelle que soit l'étendue observée.
                        plage_valeurs = max(toutes_valeurs) - min(toutes_valeurs)
                        nb_blocs_cible = 9
                        if plage_valeurs > 0:
                            pas_arrondi = max(1000, round(plage_valeurs / nb_blocs_cible / 1000) * 1000)
                        else:
                            pas_arrondi = 1000
                        compteur_valeurs = Counter(round(v / pas_arrondi) * pas_arrondi for v in toutes_valeurs)
                        valeurs_graduees = sorted(compteur_valeurs.keys())
                        if len(valeurs_graduees) == 1:
                            st.metric("Salaire annuel indiqué", f"{valeurs_graduees[0]:,.0f} €".replace(",", " "))
                        else:
                            palette_jauge = ["#2E86DE", "#10AC84", "#F9A826", "#8854D0", "#EE5A6F", "#01A3A4"]
                            segments_largeur = [
                                valeurs_graduees[i + 1] - valeurs_graduees[i]
                                for i in range(len(valeurs_graduees) - 1)
                            ]
                            segments_base = valeurs_graduees[:-1]
                            couleurs_segments = [
                                palette_jauge[i % len(palette_jauge)] for i in range(len(segments_largeur))
                            ]
                            # Chaque bloc représente la tranche menant à sa graduation de DROITE
                            # (ex: le bloc entre 30 000 € et 50 000 € "mène" à 50 000 €) — au
                            # survol, on affiche combien d'offres ont un montant qui arrondit à
                            # cette borne précise.
                            textes_survol = [
                                f"{v:,.0f} € — {compteur_valeurs[v]} offre(s)".replace(",", " ")
                                for v in valeurs_graduees[1:]
                            ]
                            fig_jauge = go.Figure(
                                go.Bar(
                                    x=segments_largeur,
                                    y=[""] * len(segments_largeur),
                                    base=segments_base,
                                    orientation="h",
                                    marker=dict(color=couleurs_segments, line=dict(width=1, color="#0e1117")),
                                    hovertext=textes_survol,
                                    hoverinfo="text",
                                )
                            )
                            fig_jauge.update_xaxes(
                                visible=True,
                                tickmode="array",
                                tickvals=valeurs_graduees,
                                ticktext=[f"{v:,.0f} €".replace(",", " ") for v in valeurs_graduees],
                                tickfont=dict(size=12, color="white"),
                                tickangle=-30,
                                showgrid=False,
                                zeroline=False,
                            )
                            fig_jauge.update_yaxes(visible=False)
                            fig_jauge.update_layout(
                                height=130, margin=dict(t=25, l=10, r=10, b=40),
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                showlegend=False,
                            )
                            st.plotly_chart(fig_jauge, use_container_width=True)

                    # Repère de fiabilité déplacé ici en simple mention de source (au lieu
                    # d'un gros st.metric qui lui donnait plus de poids visuel que ce n'est
                    # qu'un indicateur de taille d'échantillon).
                    st.caption(
                        f"📎 Source : {nb_avec_salaire} offre(s) sur {nb_total_offres} indiquent un "
                        "salaire, tous types de contrat confondus — jauge ci-dessus calculée "
                        "uniquement sur les offres CDI parmi elles, montants annualisés (un salaire "
                        "mensuel est multiplié par 12 ; un salaire horaire est exclu, faute de "
                        "pouvoir le convertir en annuel de façon fiable)."
                    )

            st.divider()
            st.markdown("#### 🎓 Répartition par niveau d'expérience demandé")
            if df_experience.empty:
                st.info("Aucune donnée de niveau d'expérience disponible pour ces critères.")
            else:
                # Catégorie "Expérience exigée" retirée à la demande : trop vague pour être
                # exploitable (contrairement à "Débutant accepté" ou "2 An(s)", elle ne dit
                # rien de la durée réellement demandée).
                df_experience_tri = (
                    df_experience[df_experience["experience"] != "Expérience exigée"]
                    .sort_values("nombre_offres", ascending=False)
                )
                try:
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
                        # Infobulle réduite au strict nécessaire (libellé + nombre d'offres) —
                        # par défaut, un treemap Plotly affiche aussi le % du parent, le % de
                        # la racine et le chemin complet au survol, jugé trop chargé ici.
                        hovertemplate="%{label}<br>%{value} offre(s)<extra></extra>",
                    )
                    fig_experience.update_layout(
                        height=280, margin=dict(t=10, l=10, r=10, b=10), coloraxis_showscale=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig_experience, use_container_width=True)
                except Exception:
                    st.dataframe(
                        df_experience_tri.rename(columns={"experience": "Expérience", "nombre_offres": "Nombre d'offres"}),
                        use_container_width=True, hide_index=True,
                    )

# ---------------------------------------------------------------------------
# Onglet "Événements" — forums, salons, ateliers, job dating... via l'API
# "Mes événements emploi" de France Travail. Utilise le(s) code(s) ROME
# résolus et le département renseignés dans "Créer mon CV" (comme les autres
# onglets), pas de champ de recherche séparé.
# ---------------------------------------------------------------------------
with tab_evenements:
    st.caption(
        "Forums, salons, ateliers et job dating à venir (90 prochains jours), repérés via "
        "l'API « Mes événements emploi » de France Travail — filtrés sur le grand domaine du "
        "poste recherché et ton département."
    )

    postes_cv_evt = st.session_state.get("cv_postes_recherche", [])
    codes_par_poste_evt = st.session_state.get("cv_codes_par_poste", {})
    codes_resolus_evt = [c for c in codes_par_poste_evt.values() if c]
    departement_evt = st.session_state.get("cv_departement")

    if not postes_cv_evt:
        st.info(
            "👉 Renseigne un poste recherché dans l'onglet **🧾 Créer mon CV** pour voir les "
            "événements pertinents."
        )
    elif not departement_evt:
        st.info(
            "👉 Ton département de résidence n'est plus renseigné — retourne dans l'onglet "
            "**🧾 Créer mon CV** pour le sélectionner."
        )
    else:
        # Filtres facultatifs — la recherche se lance déjà avec les valeurs par
        # défaut ci-dessous (90 jours, toutes modalités, tous publics), les
        # cases permettent d'affiner sans devoir tout reconfigurer.
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            fenetre_jours = st.radio(
                "Période", [30, 90, 180], index=1,
                format_func=lambda j: f"{j} jours", horizontal=True, key="evt_fenetre",
            )
            debutant_uniquement = st.checkbox(
                "Ouvert aux débutants/étudiants uniquement", key="evt_debutant",
                help="Filtre sur le référentiel officiel : \"Ouvert aux jeunes\" + \"Débutant(e) accepté(e)\".",
            )
        with col_f2:
            modalite_choisie = st.radio(
                "Modalité", ["Toutes", "Présentiel", "Distanciel"], horizontal=True, key="evt_modalite",
            )
        modalite_code = {"Présentiel": "ENPHY", "Distanciel": "ADIST"}.get(modalite_choisie)
        public_cible_codes = [1, 2] if debutant_uniquement else None

        with st.spinner("Recherche d'événements en cours..."):
            evenements, total_grand_domaine, nb_avant_filtre_rome = rechercher_evenements_emploi(
                codes_resolus_evt, departement_evt, jours_max=fenetre_jours,
                modalite=modalite_code, public_cible=public_cible_codes,
            )

        if evenements is None:
            st.info(
                "Aucune donnée disponible — l'appel API a échoué (voir le diagnostic "
                "ci-dessous pour le détail)."
            )
        elif not evenements:
            st.info(
                f"Aucun événement trouvé pour ces critères dans les {fenetre_jours} prochains jours."
            )
        else:
            # Transparence sur le filtrage : le grand domaine ROME (une lettre, ex: "M" pour
            # "Support à l'entreprise") est large et couvre bien plus que le seul poste
            # recherché — un résultat final réduit après affinage sur le(s) code(s) ROME
            # précis n'est donc pas anormal, ce message permet de le vérifier soi-même
            # plutôt que de se demander si l'app "rate" des événements.
            if total_grand_domaine and len(evenements) < nb_avant_filtre_rome:
                st.caption(
                    f"ℹ️ {len(evenements)} événement(s) affiché(s), affinés sur le(s) poste(s) "
                    f"précis parmi {nb_avant_filtre_rome} récupérés sur cette page — le grand "
                    f"domaine du poste recherché en compte {total_grand_domaine} au total sur la "
                    "période, mais couvre bien d'autres métiers que celui recherché."
                )
            df_evenements = pd.DataFrame(
                [
                    {
                        "Titre": e.get("titre") or "N/C",
                        "Date": (e.get("dateEvenement") or "")[:10],
                        "Ville": e.get("ville") or "N/C",
                        "Type": e.get("type") or "N/C",
                        "Modalités": ", ".join(e.get("modalites") or []) or "N/C",
                        "Lien": e.get("urlDetailEvenement") or "",
                    }
                    for e in evenements
                ]
            )
            st.dataframe(
                df_evenements,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Lien": st.column_config.LinkColumn("Lien", display_text="Voir la fiche")
                },
            )

        with st.expander("🔧 Diagnostic technique Événements emploi (temporaire)"):
            st.caption(
                "Teste directement l'appel API pour le poste et le département actuellement "
                "sélectionnés, et affiche la vraie réponse brute — utile pour vérifier "
                "pourquoi une liste reste vide ou pour confirmer que l'intégration répond bien."
            )
            if st.button("Lancer le diagnostic", key="btn_diagnostic_evenements"):
                with st.spinner("Test de l'appel Événements en cours..."):
                    resultats_diag_evt = diagnostiquer_evenements(codes_resolus_evt, departement_evt)
                st.json(resultats_diag_evt)
