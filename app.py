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


# ---------------------------------------------------------------------------
# Fonctions "Tendance par profil" (analyse personnalisée par métier ROME)
# ---------------------------------------------------------------------------
def resoudre_codes_rome(mots_cles, departement=None, echantillon=100):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": mots_cles, "range": f"0-{echantillon - 1}"}
    if departement:
        params["departement"] = departement

    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres {r.status_code} : {r.text}")
        return pd.DataFrame(columns=["code_rome", "libelle", "nb_offres_echantillon"])

    resultats = r.json().get("resultats", [])
    compteur = Counter()
    libelles = {}
    for offre in resultats:
        rome = offre.get("romeCode")
        if rome:
            compteur[rome] += 1
            libelles[rome] = offre.get("romeLibelle", rome)

    df = pd.DataFrame(
        [{"code_rome": r_, "libelle": libelles[r_], "nb_offres_echantillon": c} for r_, c in compteur.items()]
    )
    if not df.empty:
        df = df.sort_values("nb_offres_echantillon", ascending=False).reset_index(drop=True)
    return df


def offres_par_ville(code_rome, departement, max_pages=5):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"codeROME": code_rome, "departement": departement, "range": f"{debut}-{fin}"}
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    villes = Counter()
    for offre in toutes_offres:
        lieu = offre.get("lieuTravail", {}).get("libelle", "Non renseigné")
        villes[lieu] += 1

    df = pd.DataFrame(villes.items(), columns=["ville", "nombre_offres"])
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)
    return df, len(toutes_offres)


def volumes_nationaux_offres(code_rome):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"codeROME": code_rome, "range": "0-0"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        st.error(f"Erreur API Offres {r.status_code} : {r.text}")
        return 0
    content_range = r.headers.get("Content-Range", "")
    total = 0
    if "/" in content_range:
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            total = 0
    return total


def volumes_nationaux_demandeurs(code_rome):
    """
    TODO : à brancher sur l'API Marché du travail v1 une fois le endpoint exact
    confirmé dans ton Swagger (francetravail.io). En attendant, saisie manuelle
    proposée dans l'interface.
    """
    return None


def calculer_tension(nb_offres, nb_demandeurs):
    if not nb_demandeurs or nb_demandeurs == 0:
        return None
    return round(nb_offres / nb_demandeurs, 2)


def interpreter_tension(tension):
    if tension is None:
        return "Donnée insuffisante pour calculer la tension."
    if tension >= 1.5:
        return "Marché très favorable au candidat (peu de concurrence, beaucoup d'offres)."
    if tension >= 1.0:
        return "Marché favorable au candidat."
    if tension >= 0.5:
        return "Marché équilibré à concurrentiel."
    return "Marché très concurrentiel (peu d'offres pour beaucoup de candidats)."


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
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

st.markdown("### 👋 Pour commencer, dites-nous où vous en êtes")
profil = st.radio(
    "Que souhaitez-vous faire ?",
    ["🔍 Je suis en recherche active sur un métier précis", "📈 Je veux analyser les tendances du marché (reconversion)"],
    index=0,
)
recherche_active = profil.startswith("🔍")

st.divider()

if recherche_active:
    tab_profil, tab_offres = st.tabs(["🎯 Tendance par profil", "📋 Offres d'emploi"])
else:
    tab_profil, tab_offres = st.tabs(["📊 Tendance du marché", "📋 Offres d'emploi"])

# ---------------------------------------------------------------------------
# Onglet 1 (contenu conditionnel selon le profil)
# ---------------------------------------------------------------------------
with tab_profil:
    if recherche_active:
        st.write(
            "Indiquez le métier que vous ciblez : nous calculons pour vous où sont les offres "
            "près de chez vous, le volume national, et le niveau de tension du marché sur ce métier."
        )

        col1, col2 = st.columns(2)
        with col1:
            mots_cles_profil = st.text_input("Métier recherché", value="consultant", key="mots_profil")
        with col2:
            departement_profil = st.text_input("Département (région d'intérêt)", value="13", key="dep_profil")

        if st.button("Lancer l'analyse de mon profil"):
            with st.spinner("Résolution du métier vers un/des code(s) ROME..."):
                df_rome = resoudre_codes_rome(mots_cles_profil, departement=departement_profil)

            if df_rome.empty:
                st.error("Aucun code ROME trouvé pour ce métier. Essayez un autre mot-clé.")
            else:
                st.markdown("#### Codes ROME identifiés")
                st.dataframe(df_rome, use_container_width=True, hide_index=True)

                code_rome_choisi = st.selectbox(
                    "Choisissez le code ROME le plus représentatif de votre recherche",
                    options=df_rome["code_rome"],
                    format_func=lambda c: f"{c} — {df_rome.loc[df_rome.code_rome == c, 'libelle'].values[0]}",
                )

                st.markdown(f"#### 📍 Offres par ville — département {departement_profil}")
                with st.spinner("Récupération des offres par ville..."):
                    df_villes, total_region = offres_par_ville(code_rome_choisi, departement_profil)
                st.metric("Total offres dans la région", total_region)
                if not df_villes.empty:
                    st.bar_chart(df_villes.set_index("ville"))
                    st.dataframe(df_villes, use_container_width=True, hide_index=True)

                st.markdown("#### 🇫🇷 Vision nationale")
                with st.spinner("Récupération des volumes nationaux..."):
                    total_national_offres = volumes_nationaux_offres(code_rome_choisi)
                    total_national_demandeurs = volumes_nationaux_demandeurs(code_rome_choisi)

                c1, c2 = st.columns(2)
                c1.metric("Offres au niveau national", total_national_offres)
                if total_national_demandeurs is None:
                    total_national_demandeurs = st.number_input(
                        "Demandeurs d'emploi (saisie manuelle en attendant l'API Marché du travail)",
                        min_value=0, value=0,
                    )
                c2.metric("Demandeurs d'emploi (national)", total_national_demandeurs)

                st.markdown("#### ⚖️ Tension du marché")
                tension = calculer_tension(total_national_offres, total_national_demandeurs)
                if tension is not None:
                    st.metric("Indice de tension (offres / demandeurs)", tension)
                    st.info(interpreter_tension(tension))
                else:
                    st.info("Renseignez un nombre de demandeurs pour calculer la tension.")

                st.markdown("#### 💡 Autres KPIs à envisager")
                st.markdown(
                    """
- **Évolution du volume d'offres** sur 30/60/90 jours
- **Répartition par type de contrat** (CDI / CDD / intérim / freelance)
- **Répartition par niveau d'expérience demandé**
- **Fourchette de salaire proposée**, si disponible
- **Durée de vie moyenne des offres** (proxy de tension indirecte)
- **Top entreprises qui recrutent** via l'API La Bonne Boite
- **Dynamisme du territoire** via l'API Informations sur un territoire
- **Comparaison multi-département** pour arbitrer une mobilité géographique
                    """
                )
    else:
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

# ---------------------------------------------------------------------------
# Onglet 2 : Offres d'emploi (identique dans les deux parcours)
# ---------------------------------------------------------------------------
with tab_offres:
    mots = st.text_input("Mots-clés", value="data", key="mots_offres")
    departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône)", value="13", key="dep_offres")
    secteur_naf = st.text_input(
        "Secteur d'activité NAF, 2 chiffres, optionnel (ex: 62 = Programmation informatique, "
        "56 = Restauration, 41 = Construction de bâtiments)",
        value="", key="secteur_offres"
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
