import streamlit as st
import requests
import os

CLIENT_ID = os.environ["PAR_aideconseillechercheu_467a5502cfd022b25b0a7af6b5de4b7921d3758c89c193fb9dc172f59d64c759"]
CLIENT_SECRET = os.environ["eb787e22c71d75d0e4e9d343dfd2f48269802403b84bca13753448a9c8518b1a"]

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

def chercher_offres(mots_cles, commune="13055"):
    token = get_token()
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"motsCles": mots_cles, "commune": commune, "range": "0-19"}
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json().get("resultats", [])

st.set_page_config(page_title="Aide Conseil Emploi")
st.title("🎯 Aide Conseil Emploi")
st.write("Orientation des chercheurs d'emploi selon les tendances du marché.")

mots = st.text_input("Mots-clés", value="data")

if st.button("Chercher"):
    with st.spinner("Recherche en cours..."):
        resultats = chercher_offres(mots)
    if not resultats:
        st.warning("Aucune offre trouvée.")
    else:
        st.success(f"{len(resultats)} offres trouvées")
        for o in resultats:
            entreprise = o.get("entreprise", {}).get("nom", "N/C")
            lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
            st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu}")
