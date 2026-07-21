import streamlit as st
import requests
import os

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

def get_token():
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "api_offresdemploiv2 o2dsoffre"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(url, data=payload, headers=headers)
    r.raise_for_status()
    return r.json()["access_token"]

def chercher_offres(mots_cles, departement):
    token = get_token()
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    params = {"motsCles": mots_cles, "departement": departement, "range": "0-19"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API {r.status_code} : {r.text}")
        return []
    return r.json().get("resultats", [])

st.set_page_config(page_title="Aide Conseil Emploi")
st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

mots = st.text_input("Mots-clés", value="data")
departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône, couvre Marseille et Aix)", value="13")

if st.button("Chercher"):
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
