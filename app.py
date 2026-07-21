import streamlit as st
import requests
import os
import pandas as pd

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

# --- Authentification ---
def get_token(scope):
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": scope
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(url, data=payload, headers=headers)
    r.raise_for_status()
    return r.json()["access_token"]

SCOPE_STATS = "api_stats-offres-demandes-emploiv1 offresetdemandesemploi"

# --- API Offres d'emploi (liste d'offres) ---
def chercher_offres(mots_cles, departement, secteur_naf=None):
    token = get_token("api_offresdemploiv2 o2dsoffre")
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": mots_cles, "departement": departement, "range": "0-19"}
    if secteur_naf:
        params["secteurActivite"] = secteur_naf
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres {r.status_code} : {r.text}")
        return []
    return r.json().get("resultats", [])

# --- API Marché du travail : demandeurs d'emploi inscrits (DE_1) ---
def stat_demandeurs(code_departement, code_rome):
    token = get_token(SCOPE_STATS)
    url = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi/v1/indicateur/stat-demandeurs"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": code_departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "codeTypeNomenclature": "CATCAND",
        "dernierePeriode": True,
        "sansCaracteristiques": True
    }
    r = requests.post(url, headers=headers, json=body)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Marché du travail {r.status_code} : {r.text}")
        return None
    return r.json()

# --- API Marché du travail : tension du recrutement (PERSP_2) ---
def stat_tension_recrutement(code_departement, code_rome):
    token = get_token(SCOPE_STATS)
    url = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi/v1/indicateur/stat-perspective-employeur"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": code_departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "ANNEE",
        "codeTypeNomenclature": "TYPE_TENSION",
        "dernierePeriode": True
    }
    r = requests.post(url, headers=headers, json=body)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Tension recrutement {r.status_code} : {r.text}")
        return None
    return r.json()

# --- API Marché du travail : offres enregistrées (OFF_1) ---
def stat_offres_enregistrees(code_departement, code_rome):
    token = get_token(SCOPE_STATS)
    url = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi/v1/indicateur/stat-offres"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": code_departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "codeTypeNomenclature": "ORIGINEOFF",
        "dernierePeriode": True,
        "sansCaracteristiques": True
    }
    r = requests.post(url, headers=headers, json=body)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres enregistrées {r.status_code} : {r.text}")
        return None
    return r.json()

st.set_page_config(page_title="Aide Conseil Emploi", layout="centered")
st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

tab1, tab2, tab3 = st.tabs(["📋 Offres d'emploi", "🔥 Tension du recrutement", "👥 Demandeurs d'emploi"])

with tab1:
    mots = st.text_input("Mots-clés", value="data")
    departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône)", value="13")
    secteur_naf = st.text_input(
        "Secteur d'activité NAF, 2 chiffres, optionnel (ex: 62 = Programmation informatique, "
        "56 = Restauration, 41 = Construction de bâtiments)",
        value=""
    )

    if st.button("Chercher des offres"):
        with st.spinner("Recherche en cours..."):
            resultats = chercher_offres(mots, departement, secteur_naf.strip() or None)
        if not resultats:
            st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
        else:
            st.success(f"{len(resultats)} offres trouvées")
            for o in resultats:
                entreprise = o.get("entreprise", {}).get("nom", "N/C")
                lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu}")

with tab2:
    st.write(
        "L'indicateur de **tension** mesure la difficulté des entreprises à recruter sur un métier : "
        "plus la tension est élevée, plus ce métier est recherché et difficile à pourvoir pour les employeurs."
    )
    code_rome_t = st.text_input(
        "Code ROME du métier (ex: M1805 = Études et développement informatique)",
        value="M1805", key="rome_tension"
    )
    departement_t = st.text_input("Département (ex: 13)", value="13", key="dep_tension")

    if st.button("Voir la tension du recrutement"):
        with st.spinner("Récupération des statistiques..."):
            data_tension = stat_tension_recrutement(departement_t, code_rome_t)
            data_offres = stat_offres_enregistrees(departement_t, code_rome_t)

        if data_tension:
            valeurs = data_tension.get("listeValeursParPeriode", [])
            if not valeurs:
                st.warning("Aucune donnée de tension disponible pour ce métier/département.")
            else:
                libelle_metier = valeurs[0].get("libActivite", code_rome_t)
                libelle_territoire = valeurs[0].get("libTerritoire", departement_t)
                libelle_periode = valeurs[0].get("libPeriode", "")
                st.subheader(f"📍 {libelle_metier}")
                st.caption(f"{libelle_territoire} — {libelle_periode}")

                for v in valeurs:
                    lib_nomenclature = v.get("libNomenclature", "")
                    nombre = v.get("valeurPrincipaleNombre")
                    taux = v.get("valeurPrincipaleTaux")
                    st.metric(lib_nomenclature, nombre if nombre is not None else taux)

        if data_offres:
            valeurs_o = data_offres.get("listeValeursParPeriode", [])
            total_offres = next((v for v in valeurs_o if v.get("codeNomenclature") == "ENSEMBLE"), None)
            if total_offres:
                st.markdown("---")
                st.metric(
                    "Offres enregistrées sur la période",
                    f"{total_offres['valeurPrincipaleNombre']:,}".replace(",", " ")
                )
            elif valeurs_o:
                st.markdown("---")
                st.markdown("**Détail des offres par origine**")
                lignes_o = [{
                    "Origine": v.get("libNomenclature", ""),
                    "Nombre d'offres": v.get("valeurPrincipaleNombre", 0)
                } for v in valeurs_o]
                st.dataframe(pd.DataFrame(lignes_o), hide_index=True, use_container_width=True)

with tab3:
    st.write("Consultez le nombre de demandeurs d'emploi inscrits pour un métier (code ROME) et un département.")
    code_rome = st.text_input(
        "Code ROME du métier (ex: M1805 = Études et développement informatique)",
        value="M1805", key="rome_de"
    )
    departement2 = st.text_input("Département (ex: 13)", value="13", key="dep_de")

    if st.button("Voir les demandeurs d'emploi"):
        with st.spinner("Récupération des statistiques..."):
            data = stat_demandeurs(departement2, code_rome)

        if data:
            valeurs = data.get("listeValeursParPeriode", [])
            if not valeurs:
                st.warning("Aucune donnée disponible pour ce métier/département.")
            else:
                libelle_metier = valeurs[0].get("libActivite", code_rome)
                libelle_territoire = valeurs[0].get("libTerritoire", departement2)
                libelle_periode = valeurs[0].get("libPeriode", "")

                st.subheader(f"📍 {libelle_metier}")
                st.caption(f"{libelle_territoire} — {libelle_periode}")

                total = next((v for v in valeurs if v.get("codeNomenclature") == "ABCDEFG"), None)
                actifs = next((v for v in valeurs if v.get("codeNomenclature") == "ABC"), None)

                col1, col2 = st.columns(2)
                if total:
                    col1.metric("Total demandeurs d'emploi", f"{total['valeurPrincipaleNombre']:,}".replace(",", " "))
                if actifs:
                    col2.metric(
                        "En recherche active (A+B+C)",
                        f"{actifs['valeurPrincipaleNombre']:,}".replace(",", " "),
                        f"{actifs['valeurSecondairePourcentage']}% du total"
                    )
