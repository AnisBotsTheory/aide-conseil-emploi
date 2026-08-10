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
def get_secteurs_activite():
    """Référentiel des secteurs d'activité NAF (mêmes codes que le paramètre secteurActivite)."""
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/secteursActivites"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    return r.json()


def chercher_offres(code_rome, departement, secteur_naf=None, jours_max=None, range_str="0-19"):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"codeROME": code_rome, "departement": departement, "range": range_str}
    if secteur_naf:
        params["secteurActivite"] = secteur_naf
    if jours_max:
        date_min = datetime.now(timezone.utc) - timedelta(days=jours_max)
        params["minCreationDate"] = date_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            departement_offre = ville.split(" - ", 1)[0].strip() if " - " in ville else departement
            if nom_entreprise not in entreprises:
                entreprises[nom_entreprise] = {"nombre_offres": 0, "departements": set()}
            entreprises[nom_entreprise]["nombre_offres"] += 1
            entreprises[nom_entreprise]["departements"].add(departement_offre)

        date_creation = offre.get("dateCreation")
        if date_creation:
            dates_creation.append(date_creation)

    df = pd.DataFrame([{"ville": v, **infos} for v, infos in lieux.items()])
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    df_entreprises = pd.DataFrame(
        [
            {
                "entreprise": nom,
                "nombre_offres": infos["nombre_offres"],
                "departements": ", ".join(sorted(infos["departements"])),
            }
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
# API "Marché du travail" (stats-offres-demandes-emploi)
# Documentation confirmée : requêtes POST avec corps JSON.
# ---------------------------------------------------------------------------
# Le nom exact du scope de cette API n'est pas dans la doc publique (propre à
# la config de l'application). Plutôt que de deviner une seule fois et planter
# en 403, on teste plusieurs candidats au premier appel et on retient celui
# qui fonctionne réellement, en le mettant en cache pour le reste de la session.
_CANDIDATS_SCOPE_STATS_MARCHE = [
    "api_stats-offres-demandes-emploiv1 offresetdemandesemploi",  # confirmé via Swagger (section Scopes)
    "api_stats-offres-demandes-emploiv1",
    "stats-offres-demandes-emploi",
    "api_stats-offres-demandes-emploi",
]

BASE_STATS_MARCHE = "https://api.francetravail.io/partenaire/stats-offres-demandes-emploi"


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


# ---------------------------------------------------------------------------
# Fonctions "KPIs avancés" : évolution annuelle, type de contrat, salaire
# ---------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def evolution_offres_annuelle(code_rome, departement):
    """
    Volume d'offres par mois sur les 12 derniers mois, pour un ROME et un département.
    Une requête par mois (compte via Content-Range, pas de pagination des résultats).
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    maintenant = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    lignes = []
    for i in range(11, -1, -1):
        annee = maintenant.year
        mois = maintenant.month - i
        while mois <= 0:
            mois += 12
            annee -= 1
        debut_mois = datetime(annee, mois, 1, tzinfo=timezone.utc)
        if mois == 12:
            fin_mois = datetime(annee + 1, 1, 1, tzinfo=timezone.utc)
        else:
            fin_mois = datetime(annee, mois + 1, 1, tzinfo=timezone.utc)

        params = {
            "codeROME": code_rome,
            "departement": departement,
            "range": "0-0",
            "minCreationDate": debut_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxCreationDate": fin_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        r = requests.get(url, headers=headers, params=params)
        total = 0
        if r.status_code in (200, 206):
            content_range = r.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    total = int(content_range.split("/")[-1])
                except ValueError:
                    total = 0
        lignes.append({"mois": debut_mois.strftime("%Y-%m"), "nombre_offres": total})

    return pd.DataFrame(lignes)


@st.cache_data(ttl=1800)
def repartition_contrats_et_salaires(code_rome, departement, jours_max=None, max_pages=5):
    """
    Récupère les offres (ROME + département, filtre de fraîcheur optionnel) et
    calcule la répartition par type de contrat + extrait les mentions de salaire.
    """
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
            params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    compteur_contrats = Counter()
    lignes_salaires = []
    for offre in toutes_offres:
        type_contrat = offre.get("typeContratLibelle") or offre.get("typeContrat") or "Non précisé"
        compteur_contrats[type_contrat] += 1

        salaire = offre.get("salaire", {})
        libelle_salaire = salaire.get("libelle") if salaire else None
        if libelle_salaire:
            lignes_salaires.append(
                {
                    "Poste": offre.get("intitule", "N/C"),
                    "Entreprise": offre.get("entreprise", {}).get("nom", "N/C"),
                    "Salaire indiqué": libelle_salaire,
                }
            )

    df_contrats = pd.DataFrame(compteur_contrats.items(), columns=["type_contrat", "nombre_offres"])
    if not df_contrats.empty:
        df_contrats = df_contrats.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    df_salaires = pd.DataFrame(lignes_salaires)
    nb_total = len(toutes_offres)
    nb_avec_salaire = len(lignes_salaires)

    return df_contrats, df_salaires, nb_avec_salaire, nb_total


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

secteurs = get_secteurs_activite()
options_secteurs = {"Tous secteurs": None}
for s in secteurs:
    code = s.get("code")
    libelle = s.get("libelle")
    if code and libelle:
        options_secteurs[f"{libelle} ({code})"] = code

st.divider()

tab_profil, tab_avance, tab_offres, tab_cv = st.tabs(
    ["🎯 Tendance par profil", "🧩 KPIs avancés", "📋 Offres d'emploi", "🧾 Créer mon CV"]
)

# ---------------------------------------------------------------------------
# Onglet 1 : Tendance par profil
# ---------------------------------------------------------------------------
with tab_profil:
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
            st.markdown("#### Offres par poste de travail")
            st.dataframe(
                df_rome[["libelle", "nb_offres_echantillon"]].rename(
                    columns={"libelle": "Poste de travail", "nb_offres_echantillon": "Nombre d'offres"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            code_rome_choisi = st.selectbox(
                "Choisissez le poste le plus représentatif de votre recherche",
                options=df_rome["code_rome"],
                format_func=lambda c: df_rome.loc[df_rome.code_rome == c, "libelle"].values[0],
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

                st.markdown("#### 🏢 Top recruteurs")
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
                                "departements": "Département",
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

# ---------------------------------------------------------------------------
# Onglet "KPIs avancés"
# ---------------------------------------------------------------------------
with tab_avance:
    if "code_rome_choisi" not in st.session_state:
        st.info(
            "👉 Lance d'abord une analyse dans l'onglet **🎯 Tendance par profil** "
            "pour choisir ton métier — les KPIs avancés s'appuient dessus."
        )
    else:
        code_rome_actif = st.session_state["code_rome_choisi"]
        departement_actif = st.session_state["departement_profil_actif"]

        if st.button("🚀 Lancer l'analyse complète", type="primary", key="btn_analyse_complete"):
            with st.spinner("Analyse en cours (évolution, contrats, salaires)..."):
                df_evolution = evolution_offres_annuelle(code_rome_actif, departement_actif)
                df_contrats, df_salaires, nb_avec_salaire, nb_total_offres = repartition_contrats_et_salaires(
                    code_rome_actif, departement_actif
                )

            st.divider()
            st.markdown("#### 📈 Évolution du volume d'offres à l'année")
            if df_evolution.empty or df_evolution["nombre_offres"].sum() == 0:
                st.info("Aucune donnée d'évolution disponible pour ces critères.")
            else:
                st.bar_chart(df_evolution.set_index("mois")[["nombre_offres"]])
                st.caption("Nombre d'offres publiées par mois sur les 12 derniers mois.")

            st.divider()
            st.markdown("#### 📋 Répartition par type de contrat")
            if df_contrats.empty:
                st.info("Aucune donnée de type de contrat disponible pour ces critères.")
            else:
                st.bar_chart(df_contrats.set_index("type_contrat")[["nombre_offres"]])
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
                st.metric("Offres indiquant un salaire", f"{nb_avec_salaire} / {nb_total_offres} ({pct}%)")
                st.dataframe(df_salaires, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("#### 🎯 Difficulté de recrutement (BMO)")
            st.info(
                "⚠️ Pas encore branché — c'est un indicateur annuel et déclaratif (enquête "
                "employeurs), différent des données d'offres réelles utilisées ailleurs dans "
                "l'app. Dis-moi si tu veux qu'on l'ajoute."
            )

# ---------------------------------------------------------------------------
# Onglet 2 : Offres d'emploi (identique dans les deux parcours)
# ---------------------------------------------------------------------------
with tab_offres:
    if "df_rome_profil" not in st.session_state or st.session_state["df_rome_profil"].empty:
        st.info(
            "👉 Lance d'abord une recherche dans l'onglet **🎯 Tendance par profil** pour "
            "identifier les postes correspondant à ton métier — ils seront proposés ici."
        )
    else:
        df_rome_offres = st.session_state["df_rome_profil"]

        code_rome_offres = st.selectbox(
            "Choisissez le poste le plus représentatif de votre recherche",
            options=df_rome_offres["code_rome"],
            format_func=lambda c: df_rome_offres.loc[df_rome_offres.code_rome == c, "libelle"].values[0],
            index=(
                list(df_rome_offres["code_rome"]).index(st.session_state["code_rome_choisi"])
                if st.session_state.get("code_rome_choisi") in list(df_rome_offres["code_rome"])
                else 0
            ),
            key="code_rome_offres_select",
        )
        departement = st.text_input(
            "Département (ex: 13 = Bouches-du-Rhône)",
            value=st.session_state.get("departement_profil_actif", "13"),
            key="dep_offres",
        )
        secteur_choisi_offres = st.selectbox("Secteur d'activité", list(options_secteurs.keys()), key="secteur_offres")
        secteur_naf = options_secteurs[secteur_choisi_offres]
        fraicheur_choisie_offres = st.selectbox(
            "Publiées depuis",
            ["Toutes les offres actives", "7 derniers jours", "30 derniers jours", "90 derniers jours"],
            key="fraicheur_offres",
        )
        jours_max_offres = {
            "Toutes les offres actives": None,
            "7 derniers jours": 7,
            "30 derniers jours": 30,
            "90 derniers jours": 90,
        }[fraicheur_choisie_offres]

        if st.button("Chercher des offres"):
            with st.spinner("Recherche en cours..."):
                resultats, total = chercher_offres(code_rome_offres, departement, secteur_naf, jours_max_offres)
            if not resultats:
                st.warning("Aucune offre trouvée (ou erreur, voir message ci-dessus).")
            else:
                st.success(f"{len(resultats)} offres affichées sur {total} au total")
                for o in resultats:
                    entreprise = o.get("entreprise", {}).get("nom", "N/C")
                    lieu = o.get("lieuTravail", {}).get("libelle", "N/C")
                    date_pub = o.get("dateCreation", "")[:10]
                    st.markdown(f"**{o['intitule']}** — {entreprise} — {lieu} — publiée le {date_pub}")

# ---------------------------------------------------------------------------
# Onglet 3 : Créer mon CV (identique dans les deux parcours)
# ---------------------------------------------------------------------------
with tab_cv:
    afficher_generateur_cv()
