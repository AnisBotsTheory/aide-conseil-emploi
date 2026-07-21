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

# --- API Offres d'emploi ---
def chercher_offres(mots_cles, departement):
    token = get_token("api_offresdemploiv2 o2dsoffre")
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": mots_cles, "departement": departement, "range": "0-19"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres {r.status_code} : {r.text}")
        return []
    return r.json().get("resultats", [])

# --- API Marché du travail : demandeurs d'emploi inscrits (DE_1) ---
def stat_demandeurs(code_departement, code_rome):
    scope = "api_stats-offres-demandes-emploiv1 offresetdemandesemploi"
    token = get_token(scope)
    url = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi/v1/indicateur/stat-demandeurs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
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

# Libellés lisibles pour les catégories de demandeurs d'emploi
LIBELLES_CATEGORIES = {
    "A": "Catégorie A (sans activité)",
    "B": "Catégorie B (activité réduite courte)",
    "C": "Catégorie C (activité réduite longue)",
    "D": "Catégorie D (stage, maladie...)",
    "E": "Catégorie E (contrat aidé...)",
    "F": "Catégorie F",
    "G": "Catégorie G",
}

st.set_page_config(page_title="Aide Conseil Emploi", layout="centered")
st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

tab1, tab2 = st.tabs(["📋 Offres d'emploi", "📊 Tendances du marché"])

with tab1:
    mots = st.text_input("Mots-clés", value="data")
    departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône)", value="13")

    if st.button("Chercher des offres"):
        with st.spinner("Recherche en cours..."):
            resultats = chercher_offres(mots, departement)
        if not resultats:
            st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
        else:
            st.success(f"{len(resultats)} offres trouvées")
            for o in resultats:
                entreprise = o.get("entreprise", {}).get("nom", "N/C")
                lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu}")

with tab2:
    st.write("Consultez le nombre de demandeurs d'emploi inscrits pour un métier (code ROME) et un département.")
    code_rome = st.text_input(
        "Code ROME du métier (ex: M1805 = Études et développement informatique)",
        value="M1805"
    )
    departement2 = st.text_input("Département (ex: 13)", value="13", key="dep2")

    if st.button("Voir les tendances"):
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

                st.markdown("---")
                st.markdown("**Détail par catégorie**")

                lignes = []
                for v in valeurs:
                    code_nom = v.get("codeNomenclature")
                    if code_nom in ["A", "B", "C", "D", "E", "F", "G"]:
                        lignes.append({
                            "Catégorie": LIBELLES_CATEGORIES.get(code_nom, code_nom),
                            "Nombre": v.get("valeurPrincipaleNombre", 0),
                            "% du total": f"{v.get('valeurSecondairePourcentage', 0)}%"
                        })

                if lignes:
                    df = pd.DataFrame(lignes).sort_values("Nombre", ascending=False)
                    st.dataframe(df, hide_index=True, use_container_width=True)
                    st.bar_chart(df.set_index("Catégorie")["Nombre"])
