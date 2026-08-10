import streamlit as st
import requests
import os
import pandas as pd
import folium
from datetime import datetime, timedelta, timezone
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from collections import Counter

from cv_builder import afficher_generateur_cv

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


@st.cache_data(ttl=3600)
def get_secteurs_activite():
    """Référentiel des secteurs d'activité NAF (mêmes codes que le paramètre secteurActivite)."""
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/secteursActivites"
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
def resoudre_codes_rome(mots_cles, departement=None, secteur_activite=None, echantillon=100):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": mots_cles, "range": f"0-{echantillon - 1}"}
    if departement:
        params["departement"] = departement
    if secteur_activite:
        params["secteurActivite"] = secteur_activite

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


@st.cache_data(ttl=1800)
def offres_par_ville(code_rome, departement, jours_max=None, max_pages=5):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"codeROME": code_rome, "departement": departement, "range": f"{debut}-{fin}"}
        if jours_max:
            date_min = datetime.now(timezone.utc) - timedelta(days=jours_max)
            params["minCreationDate"] = date_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    lieux = {}
    entreprises = {}
    dates_creation = []
    for offre in toutes_offres:
        lieu_travail = offre.get("lieuTravail", {})
        ville = lieu_travail.get("libelle", "Non renseigné")
        if ville not in lieux:
            lieux[ville] = {
                "nombre_offres": 0,
                "latitude": lieu_travail.get("latitude"),
                "longitude": lieu_travail.get("longitude"),
            }
        lieux[ville]["nombre_offres"] += 1

        nom_entreprise = offre.get("entreprise", {}).get("nom")
        if nom_entreprise:
            if nom_entreprise not in entreprises:
                entreprises[nom_entreprise] = {"nombre_offres": 0, "villes": set()}
            entreprises[nom_entreprise]["nombre_offres"] += 1
            entreprises[nom_entreprise]["villes"].add(ville)

        date_creation = offre.get("dateCreation")
        if date_creation:
            dates_creation.append(date_creation)

    df = pd.DataFrame([{"ville": v, **infos} for v, infos in lieux.items()])
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    df_entreprises = pd.DataFrame(
        [
            {"entreprise": nom, "nombre_offres": infos["nombre_offres"], "villes": ", ".join(sorted(infos["villes"]))}
            for nom, infos in entreprises.items()
        ]
    )
    if not df_entreprises.empty:
        df_entreprises = df_entreprises.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    nb_offres_anonymes = sum(1 for o in toutes_offres if not o.get("entreprise", {}).get("nom"))

    date_min_pub = min(dates_creation) if dates_creation else None
    date_max_pub = max(dates_creation) if dates_creation else None
    return df, len(toutes_offres), date_min_pub, date_max_pub, df_entreprises, nb_offres_anonymes



@st.cache_data(ttl=1800)
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


@st.cache_data(ttl=1800)
def volumes_departement_offres(code_rome, departement):
    """Total offres pour un code ROME sur un département (via Content-Range, pas de pagination)."""
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"codeROME": code_rome, "departement": departement, "range": "0-0"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        return 0
    content_range = r.headers.get("Content-Range", "")
    total = 0
    if "/" in content_range:
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            total = 0
    return total


# ---------------------------------------------------------------------------
# API "Marché du travail" (stats-offres-demandes-emploi) et
# "Informations sur un territoire" (stats-informations-territoire)
# Documentation confirmée : requêtes POST avec corps JSON.
# ---------------------------------------------------------------------------
# Le nom exact du scope de ces API n'est pas dans la doc publique (propre à la
# config de l'application). Plutôt que de deviner une seule fois et planter en
# 403, on teste plusieurs candidats au premier appel et on retient celui qui
# fonctionne réellement, en le mettant en cache pour le reste de la session.
_CANDIDATS_SCOPE_STATS_MARCHE = [
    "api_stats-offres-demandes-emploiv1 offresetdemandesemploi",  # confirmé via Swagger (section Scopes)
    "api_stats-offres-demandes-emploiv1",
    "stats-offres-demandes-emploi",
    "api_stats-offres-demandes-emploi",
]
_CANDIDATS_SCOPE_STATS_TERRITOIRE = [
    "api_stats-informations-territoirev1 informationsterritoire",  # par analogie, à confirmer si échec
    "api_stats-informations-territoirev1",
    "api_stats-informations-territoirev1 stats-informations-territoire",
    "stats-informations-territoire",
    "api_stats-informations-territoire",
]

BASE_STATS_MARCHE = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi"
BASE_STATS_TERRITOIRE = "https://api.francetravail.io/partenaire/stats-informations-territoire"


def _appeler_indicateur(base_url, ressource, token, payload):
    url = f"{base_url}{ressource}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code not in (200, 206):
        return None, f"Erreur API {r.status_code} : {r.text}"
    return r.json(), None


def _appel_avec_decouverte_scope(candidats, cle_session, base_url, ressource, payload):
    """
    Essaie le scope déjà validé pour cette famille d'API (mémorisé en session),
    sinon teste chaque candidat jusqu'à trouver celui qui fonctionne réellement.
    """
    scope_connu = st.session_state.get(cle_session)
    ordre_essai = [scope_connu] + [c for c in candidats if c != scope_connu] if scope_connu else candidats

    derniere_erreur = "Aucun scope testé."
    for scope in ordre_essai:
        try:
            token = get_token(scope)
        except Exception as e:
            derniere_erreur = f"Échec d'obtention du token pour le scope '{scope}' : {e}"
            continue
        data, erreur = _appeler_indicateur(base_url, ressource, token, payload)
        if erreur is None:
            st.session_state[cle_session] = scope
            return data, None
        derniere_erreur = f"[scope '{scope}'] {erreur}"

    return None, (
        f"Aucun scope testé n'a fonctionné pour cette API. Dernière erreur : {derniere_erreur} "
        "— vérifie le nom exact du scope via le bouton 'Authorize' du Swagger France Travail."
    )


@st.cache_data(ttl=1800)
def demandeurs_emploi_departement(code_rome, departement):
    """Indicateur DE_1 : nombre de demandeurs d'emploi (cat. A+B+C) pour un ROME et un département."""
    payload = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "codeTypeNomenclature": "CATCAND",
        "listeCodeNomenclature": ["A", "B", "C"],
        "dernierePeriode": True,
        "sansCaracteristiques": True,
    }
    data, erreur = _appel_avec_decouverte_scope(
        _CANDIDATS_SCOPE_STATS_MARCHE, "scope_stats_marche", BASE_STATS_MARCHE,
        "/v1/indicateur/stat-demandeurs", payload,
    )
    if erreur:
        return None, None, erreur
    valeurs = data.get("listeValeursParPeriode", [])
    total = sum(v.get("valeurPrincipaleNombre") or 0 for v in valeurs)
    periode = valeurs[0].get("libPeriode") if valeurs else None
    return total, periode, None


def dynamisme_territoire(code_rome, departement):
    """Indicateur DYN_1 : dynamique globale de l'emploi sur le territoire, via l'API Informations sur un territoire."""
    payload = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "dernierePeriode": True,
        "sansCaracteristiques": True,
    }
    data, erreur = _appel_avec_decouverte_scope(
        _CANDIDATS_SCOPE_STATS_TERRITOIRE, "scope_stats_territoire", BASE_STATS_TERRITOIRE,
        "/v1/indicateur/stat-dynamique-emploi", payload,
    )
    if erreur:
        return None, erreur
    return data.get("listeValeursParPeriode", []), None


def embauches_recentes(code_rome, departement):
    """Indicateur EMB_1 : embauches récentes sur le métier et le département."""
    payload = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "codeTypeNomenclature": "CATCAND",
        "listeCodeNomenclature": ["A", "B", "C"],
        "dernierePeriode": True,
        "sansCaracteristiques": True,
    }
    data, erreur = _appel_avec_decouverte_scope(
        _CANDIDATS_SCOPE_STATS_MARCHE, "scope_stats_marche", BASE_STATS_MARCHE,
        "/v1/indicateur/stat-embauches", payload,
    )
    if erreur:
        return None, None, erreur
    valeurs = data.get("listeValeursParPeriode", [])
    total = sum(v.get("valeurPrincipaleNombre") or 0 for v in valeurs)
    periode = valeurs[0].get("libPeriode") if valeurs else None
    return total, periode, None


def etablissements_secteur(code_rome, departement):
    """Indicateur ETAB_1 : établissements par secteur sur le département."""
    payload = {
        "codeTypeTerritoire": "DEP",
        "codeTerritoire": departement,
        "codeTypeActivite": "ROME",
        "codeActivite": code_rome,
        "codeTypePeriode": "TRIMESTRE",
        "dernierePeriode": True,
        "sansCaracteristiques": True,
    }
    data, erreur = _appel_avec_decouverte_scope(
        _CANDIDATS_SCOPE_STATS_TERRITOIRE, "scope_stats_territoire", BASE_STATS_TERRITOIRE,
        "/v1/indicateur/stat-etablissements", payload,
    )
    if erreur:
        return None, erreur
    return data.get("listeValeursParPeriode", []), None


def _dataframe_indicateur(valeurs):
    """Transforme une liste de valeurs d'indicateur (schéma commun) en DataFrame lisible."""
    lignes = []
    for v in valeurs:
        lignes.append({
            "Territoire": v.get("libTerritoire", ""),
            "Activité": v.get("libActivite", ""),
            "Période": v.get("libPeriode", ""),
            "Indicateur": v.get("valeurPrincipaleNom", ""),
            "Valeur (nombre)": v.get("valeurPrincipaleNombre"),
            "Valeur (taux)": v.get("valeurPrincipaleTaux"),
            "Valeur (montant)": v.get("valeurPrincipaleMontant"),
        })
    return pd.DataFrame(lignes)


# ---------------------------------------------------------------------------
# Fonctions "Top entreprises qui recrutent" (API La Bonne Boite v2)
# ---------------------------------------------------------------------------
# ATTENTION : scope à vérifier. Le nom exact du scope dépend de la déclaration
# de ton application sur francetravail.io (visible dans les identifiants de ton
# app, section "scope"). "api_labonneboitev2" est une supposition à confirmer.
SCOPE_LBB = "api_labonneboitev2"


def geocoder_ville(nom_ville):
    """
    Géocode un nom de ville en (latitude, longitude) via l'API Adresse
    (api-adresse.data.gouv.fr), gratuite et sans clé, opérée par l'État français.
    """
    url = "https://api-adresse.data.gouv.fr/search/"
    params = {"q": nom_ville, "type": "municipality", "limit": 1}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None, None
    features = r.json().get("features", [])
    if not features:
        return None, None
    lon, lat = features[0]["geometry"]["coordinates"]
    return lat, lon


def top_entreprises_recrutement(code_rome, ville, rayon_km=30, max_resultats=10):
    """
    Interroge l'API La Bonne Boite v2 pour lister les entreprises à fort potentiel
    d'embauche autour d'une ville, pour un métier (code ROME) donné.

    Pattern d'URL confirmé par la doc officielle France Travail (exemple donné en v1) :
    GET /partenaire/labonneboite/v1/company/?distance=30&latitude=..&rome_codes=M1607
    Adapté ici en v2 conformément à ton abonnement. A vérifier si l'appel échoue.
    """
    lat, lon = geocoder_ville(ville)
    if lat is None:
        return pd.DataFrame(), "Ville introuvable, vérifiez l'orthographe."

    token = get_token(SCOPE_LBB)
    url = "https://api.francetravail.io/partenaire/labonneboite/v2/company/"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "rome_codes": code_rome,
        "latitude": lat,
        "longitude": lon,
        "distance": rayon_km,
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code not in (200, 206):
        return pd.DataFrame(), f"Erreur API La Bonne Boite {r.status_code} : {r.text}"

    data = r.json()
    entreprises = data.get("companies", data if isinstance(data, list) else [])
    lignes = []
    for e in entreprises[:max_resultats]:
        lignes.append({
            "Entreprise": e.get("name") or e.get("raison_sociale", "N/C"),
            "Ville": e.get("city", "N/C"),
            "Secteur": e.get("naf_text") or e.get("naf", "N/C"),
            "Distance (km)": e.get("distance", "N/C"),
        })
    return pd.DataFrame(lignes), None


# ---------------------------------------------------------------------------
# Comparaison multi-département (réutilise l'API Offres d'emploi déjà fonctionnelle)
# ---------------------------------------------------------------------------
def comparer_departements(code_rome, departements):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    resultats = []
    for dep in departements:
        dep = dep.strip()
        if not dep:
            continue
        params = {"codeROME": code_rome, "departement": dep, "range": "0-0"}
        r = requests.get(url, headers=headers, params=params)
        total = 0
        if r.status_code in (200, 206):
            content_range = r.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    total = int(content_range.split("/")[-1])
                except ValueError:
                    total = 0
        resultats.append({"departement": dep, "nombre_offres": total})

    df = pd.DataFrame(resultats)
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)
    return df


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

secteurs = get_secteurs_activite()
options_secteurs = {"Tous secteurs": None}
for s in secteurs:
    code = s.get("code")
    libelle = s.get("libelle")
    if code and libelle:
        options_secteurs[f"{libelle} ({code})"] = code

st.markdown("### 👋 Pour commencer, dites-nous où vous en êtes")
profil = st.radio(
    "Que souhaitez-vous faire ?",
    ["🔍 Je suis en recherche active sur un métier précis", "📈 Je veux analyser les tendances du marché (reconversion)"],
    index=0,
)
recherche_active = profil.startswith("🔍")

st.divider()

if recherche_active:
    tab_profil, tab_avance, tab_offres, tab_cv = st.tabs(
        ["🎯 Tendance par profil", "🧩 KPIs avancés", "📋 Offres d'emploi", "🧾 Créer mon CV"]
    )
else:
    tab_profil, tab_offres, tab_cv = st.tabs(["📊 Tendance du marché", "📋 Offres d'emploi", "🧾 Créer mon CV"])

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

        secteur_choisi_profil = st.selectbox(
            "Secteur d'activité (optionnel — affine la recherche, ex: 'consultant' + secteur "
            "'Programmation informatique' pour éviter les résultats hors-sujet)",
            list(options_secteurs.keys()),
            key="secteur_profil",
        )
        code_secteur_profil = options_secteurs[secteur_choisi_profil]

        if st.button("Lancer l'analyse de mon profil"):
            with st.spinner("Résolution du métier vers un/des code(s) ROME..."):
                df_rome = resoudre_codes_rome(
                    mots_cles_profil, departement=departement_profil, secteur_activite=code_secteur_profil
                )
            # Stocké en session_state pour survivre aux reruns déclenchés par le
            # selectbox ci-dessous, et pour être accessible depuis l'onglet "KPIs avancés".
            st.session_state["df_rome_profil"] = df_rome
            st.session_state["departement_profil_actif"] = departement_profil

        if "df_rome_profil" in st.session_state:
            df_rome = st.session_state["df_rome_profil"]
            departement_actif = st.session_state["departement_profil_actif"]

            if df_rome.empty:
                st.error("Aucun code ROME trouvé pour ce métier. Essayez un autre mot-clé.")
            else:
                st.markdown("#### Codes ROME identifiés")
                st.dataframe(df_rome, use_container_width=True, hide_index=True)

                code_rome_choisi = st.selectbox(
                    "Choisissez le code ROME le plus représentatif de votre recherche",
                    options=df_rome["code_rome"],
                    format_func=lambda c: f"{c} — {df_rome.loc[df_rome.code_rome == c, 'libelle'].values[0]}",
                    key="code_rome_choisi_select",
                )
                # Persisté pour l'onglet "KPIs avancés"
                st.session_state["code_rome_choisi"] = code_rome_choisi

                st.markdown(f"#### 📍 Offres par ville — département {departement_actif}")
                fraicheur_choisie = st.selectbox(
                    "Publiées depuis",
                    ["Toutes les offres actives", "7 derniers jours", "30 derniers jours", "90 derniers jours"],
                    key="fraicheur_offres_ville",
                )
                jours_max = {
                    "Toutes les offres actives": None,
                    "7 derniers jours": 7,
                    "30 derniers jours": 30,
                    "90 derniers jours": 90,
                }[fraicheur_choisie]

                with st.spinner("Récupération des offres par ville..."):
                    df_villes, total_region, date_min_pub, date_max_pub, df_entreprises, nb_offres_anonymes = (
                        offres_par_ville(code_rome_choisi, departement_actif, jours_max=jours_max)
                    )
                st.metric("Total offres dans la région", total_region)
                if date_min_pub and date_max_pub:
                    st.caption(
                        f"📅 Offres publiées entre le {date_min_pub[:10]} et le {date_max_pub[:10]} "
                        "(format AAAA-MM-JJ) — l'API ne filtre pas par ancienneté par défaut, "
                        "ces offres sont simplement celles encore actives aujourd'hui."
                    )
                # Persisté pour préremplir l'onglet "KPIs avancés" avec la ville la plus pertinente
                if not df_villes.empty:
                    st.session_state["ville_top_profil"] = (
                        df_villes.iloc[0]["ville"].split(" - ", 1)[-1]
                    )
                if not df_villes.empty:
                    df_carte = df_villes.dropna(subset=["latitude", "longitude"]).copy()
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
                            tiles="CartoDB dark_matter",
                        )
                        cluster = MarkerCluster(
                            # Regroupe agressivement au dézoom, éclate vite au zoom (comportement demandé)
                            options={"maxClusterRadius": 60, "disableClusteringAtZoom": 15}
                        ).add_to(carte)

                        for _, row in df_carte.iterrows():
                            # Un marqueur par offre (pas par ville) pour que le chiffre affiché sur
                            # un cluster corresponde bien au nombre total d'offres regroupées.
                            for _ in range(int(row["nombre_offres"])):
                                folium.CircleMarker(
                                    location=[row["latitude"], row["longitude"]],
                                    radius=8,
                                    tooltip=f"{row['ville']} : {int(row['nombre_offres'])} offre(s)",
                                    color="#0066cc",
                                    fill=True,
                                    fill_color="#0066cc",
                                    fill_opacity=0.8,
                                    weight=1,
                                ).add_to(cluster)

                        # returned_objects=[] : la carte ne renvoie plus rien au serveur, donc
                        # zoomer/déplacer ne déclenche plus de rerun Streamlit — la carte reste
                        # 100% interactive côté navigateur, sans saccade ni réinitialisation.
                        st_folium(
                            carte,
                            use_container_width=True,
                            height=500,
                            key="carte_offres_ville",
                            returned_objects=[],
                        )
                    else:
                        st.info("Coordonnées GPS non disponibles pour ces offres, carte non affichée.")

                    st.markdown("#### 🏢 Entreprises ayant publié une offre sur la période")
                    if df_entreprises.empty:
                        st.info(
                            "Aucun nom d'entreprise exploitable — soit aucune offre, soit toutes "
                            "les offres sont diffusées de façon anonyme."
                        )
                    else:
                        st.dataframe(
                            df_entreprises.rename(
                                columns={
                                    "entreprise": "Entreprise",
                                    "nombre_offres": "Nombre d'offres",
                                    "villes": "Ville(s)",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                        if nb_offres_anonymes:
                            st.caption(
                                f"ℹ️ {nb_offres_anonymes} offre(s) supplémentaire(s) diffusée(s) sans "
                                "nom d'entreprise visible (recrutement anonyme), non comptabilisée(s) ci-dessus."
                            )

                st.markdown("#### 🇫🇷 Contexte national")
                with st.spinner("Récupération du volume national d'offres..."):
                    total_national_offres = volumes_nationaux_offres(code_rome_choisi)
                st.metric("Offres au niveau national (indicatif)", total_national_offres)

                st.markdown(f"#### ⚖️ Tension du marché — département {departement_actif}")
                with st.spinner("Récupération des demandeurs d'emploi..."):
                    total_dep_offres = volumes_departement_offres(code_rome_choisi, departement_actif)
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
                    c1.metric(f"Offres — département {departement_actif}", total_dep_offres)
                    c2.metric(
                        f"Demandeurs d'emploi{' — ' + periode_demandeurs if periode_demandeurs else ''}",
                        total_dep_demandeurs,
                    )

                tension = calculer_tension(total_dep_offres, total_dep_demandeurs)
                if tension is not None:
                    st.metric("Indice de tension (offres / demandeurs)", tension)
                    st.info(interpreter_tension(tension))
                else:
                    st.info("Donnée de demandeurs insuffisante pour calculer la tension.")

                st.divider()
                st.info(
                    "💡 Pour le top entreprises, la comparaison multi-département, le "
                    "dynamisme du territoire, les embauches et les établissements, direction "
                    "l'onglet **🧩 KPIs avancés**."
                )
    else:
        st.write(
            "Découvrez quels **métiers** et quels **secteurs** recrutent le plus actuellement, "
            "en analysant les offres réellement publiées sur le territoire choisi."
        )
        mots_t = st.text_input("Mots-clés (optionnel, laissez vide pour tout voir)", value="", key="mots_tendance")
        departement_t = st.text_input("Département (ex: 13)", value="13", key="dep_tendance")
        secteur_choisi_t = st.selectbox("Secteur d'activité", list(options_secteurs.keys()), key="secteur_tendance")
        secteur_t = options_secteurs[secteur_choisi_t]
        niveau_choisi_t = st.selectbox(
            "Niveau de formation", list(options_niveaux.keys()), key="niveau_tendance"
        )
        code_niveau_t = options_niveaux[niveau_choisi_t]

        if st.button("Analyser les tendances de recrutement"):
            with st.spinner("Analyse des offres en cours (peut prendre quelques secondes)..."):
                offres, compteur_metiers, compteur_secteurs = analyser_tendances(
                    mots_t.strip(), departement_t, secteur_t, code_niveau_t
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
# Onglet "KPIs avancés" (uniquement en parcours recherche active)
# ---------------------------------------------------------------------------
if recherche_active:
    with tab_avance:
        if "code_rome_choisi" not in st.session_state:
            st.info(
                "👉 Lance d'abord une analyse dans l'onglet **🎯 Tendance par profil** "
                "pour choisir ton métier (code ROME) — les KPIs avancés s'appuient dessus."
            )
        else:
            code_rome_actif = st.session_state["code_rome_choisi"]
            departement_actif = st.session_state["departement_profil_actif"]
            st.write(f"Analyse approfondie pour le code ROME **{code_rome_actif}**, département **{departement_actif}**.")

            col_ville, col_rayon = st.columns([2, 1])
            with col_ville:
                ville_lbb = st.text_input(
                    "Ville de référence (pour le top entreprises)",
                    value=st.session_state.get("ville_top_profil", "Aix-en-Provence"),
                    key="ville_lbb",
                )
            with col_rayon:
                rayon_lbb = st.slider("Rayon (km)", 5, 100, 30, key="rayon_lbb")

            departements_compare = st.text_input(
                "Départements à comparer, séparés par une virgule (ex: 13,84,06)",
                value=f"{departement_actif},84,06",
                key="dep_compare",
            )

            if st.button("🚀 Lancer l'analyse complète", type="primary", key="btn_analyse_complete"):
                with st.spinner("Analyse en cours (entreprises, comparaison, dynamisme, embauches, établissements)..."):
                    df_entreprises, erreur_lbb = top_entreprises_recrutement(code_rome_actif, ville_lbb, rayon_lbb)
                    df_compare = comparer_departements(code_rome_actif, departements_compare.split(","))
                    valeurs_dyn, erreur_dyn = dynamisme_territoire(code_rome_actif, departement_actif)
                    total_embauches, periode_embauches, erreur_embauches = embauches_recentes(
                        code_rome_actif, departement_actif
                    )
                    valeurs_etab, erreur_etab = etablissements_secteur(code_rome_actif, departement_actif)

                st.divider()
                st.markdown("#### 🏢 Top entreprises qui recrutent (La Bonne Boite)")
                if erreur_lbb:
                    st.error(erreur_lbb)
                elif df_entreprises.empty:
                    st.info("Aucune entreprise trouvée pour ces critères.")
                else:
                    st.dataframe(df_entreprises, use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("#### 🗺️ Comparaison multi-département")
                if df_compare.empty:
                    st.info("Aucune donnée à afficher.")
                else:
                    st.bar_chart(df_compare.set_index("departement"))
                    st.dataframe(df_compare, use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("#### 🌆 Dynamisme du territoire")
                if erreur_dyn:
                    st.error(erreur_dyn)
                elif not valeurs_dyn:
                    st.info("Aucune donnée de dynamisme disponible pour ces critères.")
                else:
                    st.dataframe(_dataframe_indicateur(valeurs_dyn), use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("#### 📈 Embauches récentes")
                if erreur_embauches:
                    st.error(erreur_embauches)
                else:
                    st.metric(
                        f"Embauches{' — ' + periode_embauches if periode_embauches else ''}",
                        total_embauches,
                    )

                st.divider()
                st.markdown("#### 🏭 Établissements qui recrutent")
                if erreur_etab:
                    st.error(erreur_etab)
                elif not valeurs_etab:
                    st.info("Aucune donnée d'établissements disponible pour ces critères.")
                else:
                    st.dataframe(_dataframe_indicateur(valeurs_etab), use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("#### 💡 Autres KPIs à envisager")
                st.markdown(
                    """
- **Évolution du volume d'offres** sur 30/60/90 jours
- **Répartition par type de contrat** (CDI / CDD / intérim / freelance)
- **Répartition par niveau d'expérience demandé**
- **Fourchette de salaire proposée**, si disponible
- **Difficulté de recrutement (BMO)** via l'indicateur "Perspectives Recrutement" — pas encore branché, dis-moi si tu veux qu'on l'ajoute
                    """
                )

# ---------------------------------------------------------------------------
# Onglet 2 : Offres d'emploi (identique dans les deux parcours)
# ---------------------------------------------------------------------------
with tab_offres:
    mots = st.text_input("Mots-clés", value="data", key="mots_offres")
    departement = st.text_input("Département (ex: 13 = Bouches-du-Rhône)", value="13", key="dep_offres")
    secteur_choisi_offres = st.selectbox("Secteur d'activité", list(options_secteurs.keys()), key="secteur_offres")
    secteur_naf = options_secteurs[secteur_choisi_offres]
    niveau_choisi = st.selectbox("Niveau de formation", list(options_niveaux.keys()), key="niveau_offres")
    code_niveau = options_niveaux[niveau_choisi]

    if st.button("Chercher des offres"):
        with st.spinner("Recherche en cours..."):
            resultats, total = chercher_offres(mots, departement, secteur_naf, code_niveau)
        if not resultats:
            st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
        else:
            st.success(f"{len(resultats)} offres affichées sur {total} au total")
            for o in resultats:
                entreprise = o.get("entreprise", {}).get("nom", "N/C")
                lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu}")

# ---------------------------------------------------------------------------
# Onglet 3 : Créer mon CV (identique dans les deux parcours)
# ---------------------------------------------------------------------------
with tab_cv:
    afficher_generateur_cv()
