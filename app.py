import streamlit as st
import requests
import os
import pandas as pd
from collections import Counter

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SCOPE_OFFRES = "api_offresdemploiv2 o2dsoffre"

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

@st.cache_data(ttl=3600)
def get_niveaux_formation():
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/niveauxFormations"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    return r.json()

def chercher_offres(mots_cles, departement, secteur_naf=None, niveau_formation=None, range_str="0-19"):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": mots_cles, "departement": departement, "range": range_str}
    if secteur_naf:
        params["secteurActivite"] = secteur_naf
    if niveau_formation:
        params["niveauFormation"] = niveau_formation
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres {r.status_code} : {r.text}")
        return [], 0
    data = r.json()
    total = 0
    content_range = r.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            total = 0
    return data.get("resultats", []), total

def analyser_tendances(mots_cles, departement, secteur_naf=None, niveau_formation=None, max_offres=150):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    debut = 0
    taille_page = 50
    while debut < max_offres:
        fin = min(debut + taille_page - 1, max_offres - 1)
        params = {"departement": departement, "range": f"{debut}-{fin}"}
        if mots_cles:
            params["motsCles"] = mots_cles
        if secteur_naf:
            params["secteurActivite"] = secteur_naf
        if niveau_formation:
            params["niveauFormation"] = niveau_formation
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            if debut == 0:
                st.error(f"Erreur API Offres {r.status_code} : {r.text}")
                return [], Counter(), Counter()
            break
        data = r.json()
        resultats = data.get("resultats", [])
        if not resultats:
            break
        toutes_offres.extend(resultats)
        debut += taille_page
        if len(resultats) < taille_page:
            break

    compteur_metiers = Counter()
    compteur_secteurs = Counter()
    for o in toutes_offres:
        metier = o.get("romeLibelle") or o.get("appellationlibelle")
        secteur = o.get("secteurActiviteLibelle")
        if metier:
            compteur_metiers[metier] += 1
        if secteur:
            compteur_secteurs[secteur] += 1

    return toutes_offres, compteur_metiers, compteur_secteurs

st.set_page_config(page_title="Aide Conseil Emploi", layout="centered")
st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

niveaux = get_niveaux_formation()
options_niveaux = {"Tous niveaux": None}
for n in niveaux:
    code = n.get("code")
    libelle = n.get("libelle")
    if code and libelle:
        options_niveaux[libelle] = code

tab1, tab2 = st.tabs(["📋 Offres d'emploi", "📊 Tendances de recrutement"])

with tab1:
    mots = st.text_input("Mots-clés", value="data")
    departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône)", value="13")
    secteur_naf = st.text_input(
        "Secteur d'activité NAF, 2 chiffres, optionnel (ex: 62 = Programmation informatique, "
        "56 = Restauration, 41 = Construction de bâtiments)",
        value=""
    )
    niveau_choisi = st.selectbox("Niveau de formation", list(options_niveaux.keys()), key="niveau_offres")
    code_niveau = options_niveaux[niveau_choisi]

    if st.button("Chercher des offres"):
        with st.spinner("Recherche en cours..."):
            resultats, total = chercher_offres(mots, departement, secteur_naf.strip() or None, code_niveau)
        if not resultats:
            st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
        else:
            st.success(f"{len(resultats)} offres affichées sur {total} au total")
            for o in resultats:
                entreprise = o.get("entreprise", {}).get("nom", "N/C")
                lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu}")

with tab2:
    st.write(
        "Découvrez quels **métiers** et quels **secteurs** recrutent le plus actuellement, "
        "en analysant les offres réellement publiées sur le territoire choisi."
    )
    mots_t = st.text_input("Mots-clés (optionnel, laissez vide pour tout voir)", value="", key="mots_tendance")
    departement_t = st.text_input("Département (ex: 13)", value="13", key="dep_tendance")
    secteur_t = st.text_input("Secteur NAF, optionnel (2 chiffres)", value="", key="secteur_tendance")
    niveau_choisi_t = st.selectbox(
        "Niveau de formation", list(options_niveaux.keys()), key="niveau_tendance"
    )
    code_niveau_t = options_niveaux[niveau_choisi_t]

    if st.button("Analyser les tendances de recrutement"):
        with st.spinner("Analyse des offres en cours (peut prendre quelques secondes)..."):
            offres, compteur_metiers, compteur_secteurs = analyser_tendances(
                mots_t.strip(), departement_t, secteur_t.strip() or None, code_niveau_t
            )

        if not offres:
            st.warning("Aucune offre trouvée pour ces critères.")
        else:
            st.success(f"{len(offres)} offres analysées")

            st.markdown("### 🧑‍💼 Métiers les plus recherchés")
            if compteur_metiers:
                df_metiers = pd.DataFrame(
                    compteur_metiers.most_common(10), columns=["Métier", "Nombre d'offres"]
                )
                st.dataframe(df_metiers, hide_index=True, use_container_width=True)
                st.bar_chart(df_metiers.set_index("Métier")["Nombre d'offres"])
            else:
                st.info("Pas assez de données sur les métiers pour ces critères.")

            st.markdown("### 🏭 Secteurs qui recrutent le plus")
            if compteur_secteurs:
                df_secteurs = pd.DataFrame(
                    compteur_secteurs.most_common(10), columns=["Secteur d'activité", "Nombre d'offres"]
                )
                st.dataframe(df_secteurs, hide_index=True, use_container_width=True)
                st.bar_chart(df_secteurs.set_index("Secteur d'activité")["Nombre d'offres"])
            else:
                st.info(
                    "Le secteur d'activité n'est renseigné que sur une partie des offres "
                    "(environ 20% selon la documentation), les résultats peuvent être partiels."
                )
