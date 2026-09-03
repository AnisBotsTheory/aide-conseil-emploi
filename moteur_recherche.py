"""
moteur_recherche.py
--------------------
Module central de calcul, partagé entre l'Espace Candidat et l'Espace
Recruteur. Aucune interface ici — uniquement des fonctions réutilisables
(appels API France Travail, appels API Adzuna, résolution ROME, scoring de
correspondance...). Objectif : éviter toute duplication du moteur de calcul
entre les deux espaces (cf. synthèse technique, section "Architecture retenue").
"""

import streamlit as st
import requests
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import Counter
from rapidfuzz import process, fuzz

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


def _params_filtre_poste(code_rome, mots_cles=None, secteur_activite=None):
    """
    Retourne le(s) paramètre(s) de filtre à utiliser pour l'API Offres d'emploi :
    - codeROME pour un poste précis
    - motsCles + secteurActivite (si renseignés) pour "Tous les postes" (recherche large,
      indexée sur le même métier et le même secteur que la recherche de profil).
    """
    if code_rome == "TOUS":
        params = {}
        if mots_cles:
            params["motsCles"] = mots_cles
        if secteur_activite:
            params["secteurActivite"] = secteur_activite
        return params
    return {"codeROME": code_rome}


# ---------------------------------------------------------------------------
# Suggestions de compétences / outils / langages (basées sur les offres réelles)
# ---------------------------------------------------------------------------
# Listes de référence pour classer chaque libellé de compétence renvoyé par
# l'API. Non exhaustives par nature — à enrichir si des cas manquants
# remontent en usage réel.
_REF_LANGAGES_INFORMATIQUES = {
    "python", "java", "javascript", "typescript", "sql", "php", "c++", "c#",
    "ruby", "golang", "go", "rust", "swift", "kotlin", "scala", "html", "css",
    "bash", "shell", "matlab", "vba", "perl", "dart", "r ", "plsql", "pl/sql",
}

_REF_OUTILS_INFORMATIQUES = {
    "excel", "sap", "salesforce", "jira", "power bi", "jedox", "dynamics 365",
    "dynamics", "tableau", "google sheets", "word", "powerpoint", "sharepoint",
    "teams", "slack", "git", "docker", "aws", "azure", "gcp", "kubernetes",
    "linux", "windows", "photoshop", "illustrator", "autocad", "sketch", "figma",
    "wordpress", "hubspot", "workday", "successfactors", "oracle", "peoplesoft",
    "netsuite", "quickbooks", "sage", "cegid", "confluence", "notion", "trello",
    "asana", "servicenow", "zendesk", "power automate", "power apps", "qlik",
    "looker", "google analytics", "efront", "sap fico", "sap mm", "sap sd",
    "outlook", "access", "visio", "adobe", "canva", "wix", "shopify",
}


def _classifier_competence(libelle):
    """Classe un libellé de compétence en 'langage', 'outil' ou 'competence' (générique)."""
    l = f" {libelle.lower().strip()} "
    for lang in _REF_LANGAGES_INFORMATIQUES:
        if f" {lang.strip()} " in l:
            return "langage"
    for outil in _REF_OUTILS_INFORMATIQUES:
        if outil in l:
            return "outil"
    return "competence"


def _normaliser(texte):
    return texte.strip().lower()


def calculer_correspondance_offre(offre, competences_utilisateur, outils_utilisateur, langages_utilisateur, mots_cles_secteur):
    """
    Calcule un score de correspondance entre une offre et le profil déclaré par
    l'utilisateur (Créer mon CV), dimension par dimension. Une dimension est
    ignorée (pas de pénalité) si l'offre ou l'utilisateur n'a rien à comparer
    sur cette dimension. Retourne (score_global_pct ou None, détail par dimension).
    """
    comp_user = {_normaliser(c) for c in competences_utilisateur}
    outils_user = {_normaliser(o) for o in outils_utilisateur}
    langages_user = {_normaliser(l) for l in langages_utilisateur}

    # Rien à comparer côté utilisateur : pas de score plutôt qu'un faux 0%.
    if not comp_user and not outils_user and not langages_user and not (mots_cles_secteur and mots_cles_secteur.strip()):
        return None, {}

    competences_offre = offre.get("competences", []) or []
    comp_offre_generique, outils_offre, langages_offre = set(), set(), set()
    for c in competences_offre:
        libelle = (c.get("libelle") or "").strip()
        if not libelle:
            continue
        categorie = _classifier_competence(libelle)
        if categorie == "competence":
            comp_offre_generique.add(_normaliser(libelle))
        elif categorie == "outil":
            outils_offre.add(_normaliser(libelle))
        else:
            langages_offre.add(_normaliser(libelle))

    detail = {}

    if comp_offre_generique:
        detail["Compétences"] = (len(comp_offre_generique & comp_user), len(comp_offre_generique))
    if outils_offre:
        detail["Outils"] = (len(outils_offre & outils_user), len(outils_offre))
    if langages_offre:
        detail["Langages"] = (len(langages_offre & langages_user), len(langages_offre))

    if mots_cles_secteur and mots_cles_secteur.strip():
        mots = [m.strip().lower() for m in mots_cles_secteur.split(",") if m.strip()]
        texte_offre = f"{offre.get('intitule', '')} {offre.get('description', '')}".lower()
        trouves = sum(1 for m in mots if m in texte_offre)
        if mots:
            detail["Mots-clés"] = (trouves, len(mots))

    if not detail:
        return None, detail

    score_global = round(100 * sum(n / d for n, d in detail.values()) / len(detail))
    return score_global, detail


def calculer_correspondance_recruteur(
    offre, poste_souhaite, competences_utilisateur, outils_utilisateur, langages_utilisateur, secteur_souhaite_code
):
    """
    Score de correspondance pondéré, spécifique à l'Espace Recruteur, sur 3 critères :
    - Intitulé du poste souhaité par le candidat vs intitulé réel de l'offre (recherche
      floue rapidfuzz) — poids 50%
    - Compétences/outils/langages déclarés vs compétences demandées par l'offre (réutilise
      calculer_correspondance_offre) — poids 30%
    - Secteur d'activité souhaité vs secteur de l'entreprise qui recrute (comparaison de
      code NAF, exacte) — poids 20%
    Une dimension sans donnée à comparer (ni côté candidat, ni côté offre) est retirée du
    calcul et le poids des dimensions restantes est réajusté proportionnellement — pas de
    pénalité pour une donnée manquante.
    """
    POIDS = {"poste": 0.5, "competences": 0.3, "secteur": 0.2}
    contributions = {}

    if poste_souhaite and poste_souhaite.strip() and offre.get("intitule"):
        contributions["poste"] = fuzz.WRatio(poste_souhaite, offre["intitule"]) / 100

    score_competences, _ = calculer_correspondance_offre(
        offre, competences_utilisateur, outils_utilisateur, langages_utilisateur, ""
    )
    if score_competences is not None:
        contributions["competences"] = score_competences / 100

    secteur_offre_code = offre.get("secteurActivite")
    if secteur_souhaite_code and secteur_offre_code:
        contributions["secteur"] = 1.0 if secteur_souhaite_code == secteur_offre_code else 0.0

    if not contributions:
        return None, {}

    poids_total = sum(POIDS[cle] for cle in contributions)
    score_global = round(100 * sum(contributions[cle] * POIDS[cle] for cle in contributions) / poids_total)

    detail = {}
    if "poste" in contributions:
        detail["Poste"] = f"{round(contributions['poste'] * 100)}%"
    if "competences" in contributions:
        detail["Compétences"] = f"{round(contributions['competences'] * 100)}%"
    if "secteur" in contributions:
        detail["Secteur"] = "✓ identique" if contributions["secteur"] == 1.0 else "✗ différent"

    return score_global, detail


@st.cache_data(ttl=1800)
def analyser_competences(code_rome, departement, mots_cles=None, secteur_activite=None, jours_max=None, max_pages=5):
    """
    Récupère les offres (même logique de filtrage que le reste de l'app) et
    extrait leur champ 'competences' pour bâtir 3 listes de suggestions
    (compétences génériques / outils informatiques / langages informatiques),
    chacune avec un % d'offres qui la mentionnent.
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"departement": departement, "range": f"{debut}-{fin}"}
        params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
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

    nb_total_offres = len(toutes_offres)
    compteurs = {"competence": Counter(), "outil": Counter(), "langage": Counter()}

    for offre in toutes_offres:
        competences_offre = offre.get("competences", [])
        if not competences_offre:
            continue
        libelles_vus = set()  # évite un double comptage si dupliqué dans la même offre
        for comp in competences_offre:
            libelle = (comp.get("libelle") or "").strip()
            if not libelle or libelle in libelles_vus:
                continue
            libelles_vus.add(libelle)
            categorie = _classifier_competence(libelle)
            compteurs[categorie][libelle] += 1

    def _construire_df(compteur):
        if nb_total_offres == 0:
            return pd.DataFrame(columns=["libelle", "nombre_offres", "pourcentage"])
        lignes = [
            {"libelle": lib, "nombre_offres": n, "pourcentage": round(100 * n / nb_total_offres)}
            for lib, n in compteur.most_common(15)
        ]
        return pd.DataFrame(lignes)

    return (
        _construire_df(compteurs["competence"]),
        _construire_df(compteurs["outil"]),
        _construire_df(compteurs["langage"]),
        nb_total_offres,
    )


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


@st.cache_data(ttl=86400)
def get_referentiel_appellations():
    """
    Référentiel officiel complet des appellations de métiers (~14 300 entrées),
    pour proposer un vrai sélecteur de poste dès le départ plutôt que de dépendre
    d'une recherche préalable dans les offres. Nom de ressource pas garanti à 100%
    (jamais testé en conditions réelles) — on essaie plusieurs candidats.
    """
    token = get_token(SCOPE_OFFRES)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for ressource in ("appellations", "romes"):
        url = f"https://api.francetravail.io/partenaire/offresdemploi/v2/referentiel/{ressource}"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return data
    return []


def _extraire_code_rome(item_appellation):
    """
    Essaie de trouver un code ROME directement dans une entrée du référentiel
    appellations (plusieurs noms de champ possibles selon la structure réelle,
    jamais vérifiée). Retourne None si non trouvé — un fallback par recherche
    prend le relai dans ce cas.
    """
    for cle in ("codeRome", "romeCode", "code_rome"):
        if item_appellation.get(cle):
            return item_appellation[cle]
    metier = item_appellation.get("metier")
    if isinstance(metier, dict):
        for cle in ("code", "codeRome"):
            if metier.get(cle):
                return metier[cle]
    return None


# ---------------------------------------------------------------------------
# Suggestion de postes à partir d'un intitulé libre / moderne (dictionnaire +
# recherche floue), pour pallier les intitulés absents de la nomenclature ROME
# telle quelle (ex: "Data Analyst", "Product Owner"...).
# ---------------------------------------------------------------------------
DICTIONNAIRE_INTITULES_MODERNES = {
    "data analyst": ["analyste de données", "chargé d'études statistiques"],
    "data scientist": ["data scientist", "statisticien"],
    "data engineer": ["ingénieur data", "data engineer"],
    "product owner": ["chef de produit", "responsable produit"],
    "product manager": ["chef de produit", "responsable produit"],
    "scrum master": ["chef de projet", "coordinateur de projet"],
    "ux designer": ["ergonome", "designer d'interface"],
    "ui designer": ["designer graphique", "webdesigner"],
    "ux/ui designer": ["ergonome", "designer d'interface", "designer graphique"],
    "devops": ["administrateur systèmes et réseaux", "ingénieur systèmes"],
    "sre": ["administrateur systèmes et réseaux", "ingénieur systèmes"],
    "business analyst": ["analyste fonctionnel", "consultant en organisation"],
    "growth hacker": ["chargé de marketing digital"],
    "growth manager": ["chargé de marketing digital"],
    "customer success manager": ["chargé de relation clientèle", "gestionnaire de la relation client"],
    "community manager": ["chargé de communication", "animateur de communauté web"],
    "social media manager": ["chargé de communication digitale"],
    "full stack developer": ["développeur informatique", "développeur web"],
    "front end developer": ["développeur web"],
    "back end developer": ["développeur informatique"],
    "software engineer": ["développeur informatique", "ingénieur logiciel"],
    "qa engineer": ["testeur logiciel", "chargé de tests"],
    "project manager": ["chef de projet"],
    "pmo": ["chargé de reporting", "assistant chef de projet", "coordinateur de projet"],
    "hr business partner": ["chargé de ressources humaines", "responsable ressources humaines"],
    "talent acquisition": ["chargé de recrutement"],
    "recruiter": ["chargé de recrutement"],
    "office manager": ["assistant de direction", "responsable administratif"],
    "sales manager": ["responsable commercial", "chef des ventes"],
    "account manager": ["chargé de clientèle", "responsable de comptes"],
    "supply chain manager": ["responsable logistique", "responsable supply chain"],
    "revenue manager": ["contrôleur de gestion", "analyste financier"],
    "financial controller": ["contrôleur de gestion"],
    "legal counsel": ["juriste"],
    "brand manager": ["chef de produit marketing", "responsable marketing"],
}


def _normaliser_texte(texte):
    """Minuscules et retrait des accents, pour des comparaisons robustes."""
    texte = texte.lower().strip()
    remplacements = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    return texte.translate(remplacements)


@st.cache_data(ttl=1800)
def suggerer_postes(saisie, max_resultats=8):
    """
    Suggère des postes du référentiel ROME à partir d'un intitulé libre/moderne,
    en combinant un petit dictionnaire de correspondances connues (ex: "Data
    Analyst" -> "Analyste de données") et une recherche floue directe sur la
    saisie brute (rattrape les variantes/fautes de frappe absentes du
    dictionnaire). Retourne une liste de libellés d'appellations officielles.
    """
    saisie_normalisee = _normaliser_texte(saisie)
    if len(saisie_normalisee) < 2:
        return []

    appellations = get_referentiel_appellations()
    labels = sorted({a.get("libelle", "").strip() for a in appellations if a.get("libelle")})
    if not labels:
        return []

    candidats = {}  # libelle -> meilleur score

    # 1) Dictionnaire : si un terme connu est contenu dans la saisie, on cherche
    # les appellations officielles correspondant aux mots-clés français associés.
    for terme_moderne, mots_cles_fr in DICTIONNAIRE_INTITULES_MODERNES.items():
        if terme_moderne in saisie_normalisee:
            for mot_cle in mots_cles_fr:
                mot_cle_normalise = _normaliser_texte(mot_cle)
                for label in labels:
                    if mot_cle_normalise in _normaliser_texte(label):
                        candidats[label] = max(candidats.get(label, 0), 100)  # priorité maximale

    # 2) Recherche floue directe sur la saisie brute, en complément.
    resultats_flous = process.extract(saisie, labels, scorer=fuzz.WRatio, limit=max_resultats * 2)
    for label, score, _ in resultats_flous:
        if score >= 55:  # seuil pour écarter le bruit non pertinent
            candidats[label] = max(candidats.get(label, 0), score)

    resultats_tries = sorted(candidats.items(), key=lambda x: x[1], reverse=True)
    return [label for label, _ in resultats_tries[:max_resultats]]


def chercher_offres(code_rome, departement, secteur_naf=None, jours_max=None, mots_cles=None, range_str="0-149"):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"departement": departement, "range": range_str}
    params.update(_params_filtre_poste(code_rome, mots_cles))
    if secteur_naf:
        params["secteurActivite"] = secteur_naf
    if jours_max:
        date_min = datetime.now(timezone.utc) - timedelta(days=jours_max)
        params["minCreationDate"] = date_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 204:
        # 204 No Content = réponse valide de l'API pour "aucune offre trouvée" sur ce
        # critère précis (fréquent en recherche multi-poste : tous les codes ROME
        # sélectionnés n'ont pas forcément d'offre active en ce moment) — pas une erreur.
        return [], 0
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
@st.cache_data(ttl=1800)
def resoudre_codes_rome(mots_cles=None, departement=None, secteur_activite=None, max_pages=8):
    """
    Parcourt toutes les offres correspondant au mot-clé (ou au secteur seul si
    mots_cles est vide) pour identifier TOUS les postes (codes ROME) rencontrés.
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"range": f"{debut}-{fin}"}
        if mots_cles:
            params["motsCles"] = mots_cles
        if departement:
            params["departement"] = departement
        if secteur_activite:
            params["secteurActivite"] = secteur_activite
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    compteur = Counter()
    libelles = {}
    for offre in toutes_offres:
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
def secteurs_pour_poste(code_rome, departement=None, max_pages=2):
    """
    Liste les secteurs d'activité (NAF) des entreprises qui recrutent réellement
    pour ce poste (code ROME), avec le nombre d'offres par secteur. Sert à filtrer
    le sélecteur "Secteur d'activité" sur des options pertinentes plutôt que la
    liste NAF générique complète.
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"codeROME": code_rome, "range": f"{debut}-{fin}"}
        if departement:
            params["departement"] = departement
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    compteur = Counter()
    libelles = {}
    for offre in toutes_offres:
        code = offre.get("secteurActivite")
        libelle = offre.get("secteurActiviteLibelle")
        if code and libelle:
            compteur[code] += 1
            libelles[code] = libelle

    df = pd.DataFrame([{"code": c, "libelle": libelles[c], "nombre_offres": n} for c, n in compteur.items()])
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=1800)
def rechercher_offres_completes(code_rome, departement, max_pages=1, mots_cles=None, secteur_activite=None, jours_max=None):
    """
    Récupère les offres complètes (tous les champs bruts : intitulé, entreprise,
    compétences, secteur d'activité...) pour un département — filtrées soit par
    code ROME (poste précis), soit par mots-clés libres (ex: nom de société) en
    passant code_rome="TOUS", avec un filtre secteur d'activité et un filtre
    d'ancienneté (jours_max) optionnels dans les deux cas — jusqu'à 150 x
    max_pages offres. Utilisée pour le matching détaillé côté Espace Recruteur
    (contrairement à offres_par_ville, qui n'agrège que par ville).
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"departement": departement, "range": f"{debut}-{fin}"}
        params.update(_params_filtre_poste(code_rome, mots_cles))
        if secteur_activite:
            params["secteurActivite"] = secteur_activite
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
    return toutes_offres


# ---------------------------------------------------------------------------
# API Adzuna — complément à France Travail sur la couverture des offres.
#
# Principe : chaque offre Adzuna est reformatée pour ADOPTER LA MÊME FORME que
# les offres brutes France Travail ci-dessus (mêmes clés : intitule, entreprise,
# lieuTravail, competences, salaire, typeContratLibelle...). calculer_correspondance_offre,
# calculer_correspondance_recruteur et repartition_contrats_et_salaires lisent
# toujours ces clés-là (jamais un schéma "interne" séparé) : une offre Adzuna
# ainsi formatée traverse tout le reste du moteur sans aucune modification de
# ces fonctions.
# ---------------------------------------------------------------------------
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY")
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs/fr/search"

# Table de correspondance code département France Travail -> nom, pour
# construire le paramètre "where" (texte libre) d'Adzuna : Adzuna ne connaît
# pas les codes département, seulement des noms de lieu à géocoder.
DEPARTEMENTS_VERS_NOM = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze",
    "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne",
    "25": "Doubs", "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir",
    "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne",
    "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan",
    "57": "Moselle", "58": "Nièvre", "59": "Nord", "60": "Oise",
    "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}


def adzuna_configure():
    """True si les identifiants Adzuna sont présents. Même logique de repli que
    DATABASE_URL : si absent, les fonctions Adzuna se désactivent silencieusement
    plutôt que de faire planter l'app."""
    return bool(ADZUNA_APP_ID and ADZUNA_APP_KEY)


def departement_vers_lieu_adzuna(code_departement):
    """
    Convertit un code département France Travail (ex: '13', '2A', '971') en un
    nom de lieu utilisable comme paramètre 'where' Adzuna. Renvoie None si le
    code est inconnu — dans ce cas, appeler rechercher_offres_adzuna sans 'ou'
    revient à chercher sur toute la France plutôt que d'échouer.
    """
    if not code_departement:
        return None
    return DEPARTEMENTS_VERS_NOM.get(str(code_departement).strip().upper())


@st.cache_data(ttl=1800)
def rechercher_offres_adzuna(mots_cles, ou=None, max_pages=2):
    """
    Interroge Adzuna (marché français) par mots-clés libres + lieu en texte libre
    (ex: "Marseille", "Bouches-du-Rhône" — pas un code département : Adzuna ne
    connaît pas cette notion, contrairement à l'API France Travail).

    Renvoie une liste d'offres au même format brut que rechercher_offres_completes(),
    directement concaténable avec ses résultats via fusionner_offres().
    Ne lève jamais d'exception : identifiants absents, erreur réseau ou quota
    dépassé renvoient simplement une liste vide.
    """
    if not adzuna_configure():
        return []

    toutes_offres = []
    taille_page = 50  # max par page côté Adzuna
    for page in range(1, max_pages + 1):
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": taille_page,
            "what": mots_cles,
            "content-type": "application/json",
        }
        if ou:
            params["where"] = ou

        try:
            r = requests.get(f"{ADZUNA_BASE_URL}/{page}", params=params, timeout=10)
            r.raise_for_status()
        except requests.RequestException:
            break  # panne ou quota dépassé : on garde ce qui a déjà été récupéré

        resultats = r.json().get("results", [])
        if not resultats:
            break
        toutes_offres.extend(_adapter_offre_adzuna(o) for o in resultats)
        if len(resultats) < taille_page:
            break

    return toutes_offres


def _adapter_offre_adzuna(offre_brute):
    """
    Reformate une offre Adzuna pour qu'elle porte les mêmes clés qu'une offre
    France Travail brute. Champs absents côté Adzuna laissés vides/None plutôt
    qu'inventés, pour que les fonctions de scoring existantes réajustent leurs
    poids exactement comme elles le font déjà pour une offre France Travail
    incomplète.
    """
    salaire_min = offre_brute.get("salary_min")
    salaire_max = offre_brute.get("salary_max")
    libelle_salaire = None
    if salaire_min or salaire_max:
        estime = " (estimé)" if offre_brute.get("salary_is_predicted") else ""
        if salaire_min and salaire_max and salaire_min != salaire_max:
            libelle_salaire = f"{int(salaire_min):,}\u2009€ - {int(salaire_max):,}\u2009€ par an{estime}".replace(",", " ")
        else:
            valeur = salaire_min or salaire_max
            libelle_salaire = f"{int(valeur):,}\u2009€ par an{estime}".replace(",", " ")

    categorie = offre_brute.get("category") or {}

    return {
        # --- clés identiques au format France Travail, lues telles quelles en aval ---
        "intitule": (offre_brute.get("title") or "").strip(),
        "description": offre_brute.get("description", ""),
        "entreprise": {"nom": (offre_brute.get("company") or {}).get("display_name")},
        "lieuTravail": {
            "libelle": (offre_brute.get("location") or {}).get("display_name", ""),
            "latitude": offre_brute.get("latitude"),
            "longitude": offre_brute.get("longitude"),
        },
        "competences": [],  # Adzuna ne structure pas les compétences par offre
        # secteurActivite volontairement vide : la "category" Adzuna n'est pas un code NAF.
        # La renseigner ferait échouer systématiquement la comparaison de code exact dans
        # calculer_correspondance_recruteur au lieu de faire ignorer la dimension.
        "secteurActivite": None,
        "secteurActiviteLibelle": categorie.get("label", ""),
        "typeContratLibelle": _deduire_type_contrat(offre_brute),
        "experienceLibelle": "Non précisé",  # Adzuna ne fournit pas ce champ
        "salaire": {"libelle": libelle_salaire} if libelle_salaire else {},
        "romeCode": None,  # pas de code ROME côté Adzuna
        "dateCreation": offre_brute.get("created"),
        # --- clés supplémentaires, ignorées par le moteur existant, utiles pour l'affichage ---
        "source": "Adzuna",
        "url": offre_brute.get("redirect_url", ""),
    }


def _deduire_type_contrat(offre_brute):
    """Adzuna ne renvoie pas un libellé de contrat unique comme France Travail :
    on le déduit des flags disponibles (approximation, notamment pas de distinction
    Intérim/CDD, à affiner si besoin en pratique)."""
    if offre_brute.get("contract_type") == "permanent":
        return "CDI"
    if offre_brute.get("contract_type") == "contract":
        return "CDD"
    return "Non précisé"


def fusionner_offres(*listes_offres):
    """
    Concatène plusieurs listes d'offres (France Travail + Adzuna, dans n'importe
    quel ordre) et déduplique sur intitulé + entreprise + ville — une même offre
    publiée sur les deux plateformes partage généralement ces trois champs.
    """
    vues = set()
    resultat = []
    for offres in listes_offres:
        for o in offres:
            cle = (
                (o.get("intitule") or "").strip().lower(),
                ((o.get("entreprise") or {}).get("nom") or "").strip().lower(),
                ((o.get("lieuTravail") or {}).get("libelle") or "").strip().lower(),
            )
            if cle in vues:
                continue
            vues.add(cle)
            resultat.append(o)
    return resultat


# ---------------------------------------------------------------------------
# Variantes "_multi" — sélection MULTIPLE de postes (plusieurs codes ROME dans
# une même recherche, ex: "Consultant" + "Consultant ERP" + "Consultant IT").
# Chacune réutilise la fonction mono-poste existante (inchangée) une fois par
# code, puis regroupe les résultats (sommes / concaténations) — pas de logique
# d'appel API dupliquée. La tension du marché reste volontairement un
# indicateur mono-poste (comme pour "Tous les postes") : pas de variante "_multi".
# ---------------------------------------------------------------------------
def volumes_departement_offres_multi(codes_rome, departement, secteur_activite=None):
    """Somme des volumes d'offres pour une liste de codes ROME."""
    return sum(
        volumes_departement_offres(code, departement, secteur_activite=secteur_activite)
        for code in codes_rome if code
    )


def rechercher_offres_completes_multi(codes_rome, departement, max_pages=1, secteur_activite=None, jours_max=None):
    """Fusionne (et déduplique) les offres complètes de plusieurs codes ROME."""
    listes = [
        rechercher_offres_completes(
            code, departement, max_pages=max_pages, secteur_activite=secteur_activite, jours_max=jours_max
        )
        for code in codes_rome if code
    ]
    return fusionner_offres(*listes)


def chercher_offres_multi(codes_rome, departement, secteur_naf=None, jours_max=None, range_str="0-149"):
    """
    Fusionne (et déduplique) les résultats de chercher_offres() pour plusieurs codes
    ROME. Le total renvoyé est le nombre d'offres réellement affichées après fusion —
    pas la somme des totaux bruts par code, qui compterait plusieurs fois une même
    offre présente sous plusieurs intitulés (ex: une offre "Consultant ERP" remontant
    à la fois pour le code ROME "Consultant" et "Consultant ERP").
    """
    tous_resultats = []
    for code in codes_rome:
        if not code:
            continue
        resultats, _ = chercher_offres(code, departement, secteur_naf, jours_max, range_str=range_str)
        tous_resultats.extend(resultats)
    offres_dedupliquees = fusionner_offres(tous_resultats)
    return offres_dedupliquees, len(offres_dedupliquees)


def offres_par_ville_multi(codes_rome, departement, jours_max=None, secteur_activite=None):
    """
    Fusionne les résultats de offres_par_ville() pour plusieurs codes ROME :
    sommes des volumes par ville et par entreprise, bornes de date étendues.
    """
    dfs_villes, dfs_entreprises = [], []
    total_cumule, nb_anonymes_cumule = 0, 0
    dates_min, dates_max = [], []

    for code in codes_rome:
        if not code:
            continue
        dfv, total, dmin, dmax, dfe, nb_anon = offres_par_ville(
            code, departement, jours_max=jours_max, secteur_activite=secteur_activite
        )
        if not dfv.empty:
            dfs_villes.append(dfv)
        if not dfe.empty:
            dfs_entreprises.append(dfe)
        total_cumule += total
        nb_anonymes_cumule += nb_anon
        if dmin:
            dates_min.append(dmin)
        if dmax:
            dates_max.append(dmax)

    if dfs_villes:
        df_villes = (
            pd.concat(dfs_villes, ignore_index=True)
            .groupby("ville", as_index=False)
            .agg({"nombre_offres": "sum", "latitude": "first", "longitude": "first"})
            .sort_values("nombre_offres", ascending=False)
            .reset_index(drop=True)
        )
    else:
        df_villes = pd.DataFrame(columns=["ville", "nombre_offres", "latitude", "longitude"])

    if dfs_entreprises:
        df_entreprises = pd.concat(dfs_entreprises, ignore_index=True)
        df_entreprises = (
            df_entreprises.groupby("entreprise", as_index=False)
            .agg(
                nombre_offres=("nombre_offres", "sum"),
                villes=("villes", lambda s: ", ".join(sorted({v.strip() for grp in s for v in grp.split(",")}))),
            )
            .sort_values("nombre_offres", ascending=False)
            .reset_index(drop=True)
        )
    else:
        df_entreprises = pd.DataFrame(columns=["entreprise", "nombre_offres", "villes"])

    date_min_global = min(dates_min) if dates_min else None
    date_max_global = max(dates_max) if dates_max else None
    return df_villes, total_cumule, date_min_global, date_max_global, df_entreprises, nb_anonymes_cumule


def evolution_offres_annuelle_multi(codes_rome, departement, secteur_activite=None):
    """Somme, mois par mois, l'évolution d'offres de plusieurs codes ROME."""
    dfs = [
        evolution_offres_annuelle(code, departement, secteur_activite=secteur_activite)
        for code in codes_rome if code
    ]
    dfs = [d for d in dfs if not d.empty]
    if not dfs:
        return pd.DataFrame(columns=["mois", "nombre_offres"])
    return (
        pd.concat(dfs, ignore_index=True)
        .groupby("mois", as_index=False)["nombre_offres"]
        .sum()
        .sort_values("mois")
        .reset_index(drop=True)
    )


def repartition_contrats_et_salaires_multi(codes_rome, departement, jours_max=None, secteur_activite=None):
    """Fusionne la répartition contrats/salaires/expérience de plusieurs codes ROME."""
    resultats = [
        repartition_contrats_et_salaires(code, departement, jours_max=jours_max, secteur_activite=secteur_activite)
        for code in codes_rome if code
    ]
    if not resultats:
        return (
            pd.DataFrame(columns=["type_contrat", "nombre_offres"]),
            pd.DataFrame(),
            0,
            0,
            pd.DataFrame(columns=["experience", "nombre_offres"]),
        )

    dfs_contrats = [r[0] for r in resultats if not r[0].empty]
    dfs_salaires = [r[1] for r in resultats if not r[1].empty]
    nb_avec_salaire = sum(r[2] for r in resultats)
    nb_total = sum(r[3] for r in resultats)
    dfs_experience = [r[4] for r in resultats if not r[4].empty]

    df_contrats = (
        pd.concat(dfs_contrats, ignore_index=True)
        .groupby("type_contrat", as_index=False)["nombre_offres"]
        .sum()
        .sort_values("nombre_offres", ascending=False)
        .reset_index(drop=True)
        if dfs_contrats
        else pd.DataFrame(columns=["type_contrat", "nombre_offres"])
    )
    df_salaires = pd.concat(dfs_salaires, ignore_index=True) if dfs_salaires else pd.DataFrame()
    df_experience = (
        pd.concat(dfs_experience, ignore_index=True)
        .groupby("experience", as_index=False)["nombre_offres"]
        .sum()
        .sort_values("nombre_offres", ascending=False)
        .reset_index(drop=True)
        if dfs_experience
        else pd.DataFrame(columns=["experience", "nombre_offres"])
    )
    return df_contrats, df_salaires, nb_avec_salaire, nb_total, df_experience


@st.cache_data(ttl=1800)
def offres_par_ville(code_rome, departement, jours_max=None, max_pages=5, mots_cles=None, secteur_activite=None):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"departement": departement, "range": f"{debut}-{fin}"}
        params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
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
            nom_ville = ville.split(" - ", 1)[-1].strip() if " - " in ville else ville
            if nom_entreprise not in entreprises:
                entreprises[nom_entreprise] = {"nombre_offres": 0, "villes": set()}
            entreprises[nom_entreprise]["nombre_offres"] += 1
            entreprises[nom_entreprise]["villes"].add(nom_ville)

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
                "villes": ", ".join(sorted(infos["villes"])),
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
def volumes_departement_offres(code_rome, departement, mots_cles=None, secteur_activite=None):
    """Total offres pour un code ROME (ou tous, via mots-clés) sur un département."""
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"departement": departement, "range": "0-0"}
    params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
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


def demandeurs_emploi_departement_multi(codes_rome, departement):
    """
    Somme des demandeurs d'emploi (cat. A+B+C) pour une liste de codes ROME —
    permet de calculer une tension du marché agrégée pour une sélection multi-
    poste : somme des offres / somme des demandeurs sur l'ensemble des postes
    sélectionnés. Une erreur sur un seul code n'empêche pas de sommer les
    autres ; l'erreur n'est remontée que si TOUS les codes échouent.
    """
    codes_valides = [c for c in codes_rome if c]
    total = 0
    periode = None
    erreurs = []
    for code in codes_valides:
        t, p, e = demandeurs_emploi_departement(code, departement)
        if e:
            erreurs.append(f"{code}: {e}")
            continue
        total += t or 0
        periode = periode or p
    erreur_globale = "; ".join(erreurs) if erreurs and len(erreurs) == len(codes_valides) else None
    return total, periode, erreur_globale


# ---------------------------------------------------------------------------
# Fonctions "KPIs avancés" : évolution annuelle, type de contrat, salaire
# ---------------------------------------------------------------------------
_MOIS_FR = {
    1: "jan", 2: "fév", 3: "mars", 4: "avr", 5: "mai", 6: "juin",
    7: "juil", 8: "août", 9: "sept", 10: "oct", 11: "nov", 12: "déc",
}


def _formater_mois_fr(mois_str):
    """'2026-03' -> 'mars 2026'"""
    annee, mois = mois_str.split("-")
    return f"{_MOIS_FR[int(mois)]} {annee}"


@st.cache_data(ttl=1800)
def evolution_offres_annuelle(code_rome, departement, mots_cles=None, secteur_activite=None):
    """
    Volume d'offres par mois sur les 12 derniers mois, pour un ROME (ou tous, via
    mots-clés) et un département. Une requête par mois (compte via Content-Range).
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
            "departement": departement,
            "range": "0-0",
            "minCreationDate": debut_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxCreationDate": fin_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
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
def repartition_contrats_et_salaires(code_rome, departement, jours_max=None, max_pages=5, mots_cles=None, secteur_activite=None):
    """
    Récupère les offres (ROME ou tous via mots-clés, + département, filtre de
    fraîcheur optionnel) et calcule la répartition par type de contrat + salaires.
    """
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    toutes_offres = []
    taille_page = 150
    for page in range(max_pages):
        debut = page * taille_page
        fin = debut + taille_page - 1
        params = {"departement": departement, "range": f"{debut}-{fin}"}
        params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
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
    compteur_experience = Counter()
    lignes_salaires = []
    for offre in toutes_offres:
        type_contrat_brut = offre.get("typeContratLibelle") or offre.get("typeContrat") or "Non précisé"
        # On ignore la nuance de durée après le tiret (ex: "Intérim - 6 Mois" -> "Intérim")
        type_contrat = type_contrat_brut.split(" - ")[0].strip()
        compteur_contrats[type_contrat] += 1

        experience_libelle = offre.get("experienceLibelle") or "Non précisé"
        compteur_experience[experience_libelle] += 1

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

    df_experience = pd.DataFrame(compteur_experience.items(), columns=["experience", "nombre_offres"])
    if not df_experience.empty:
        df_experience = df_experience.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    df_salaires = pd.DataFrame(lignes_salaires)
    nb_total = len(toutes_offres)
    nb_avec_salaire = len(lignes_salaires)

    return df_contrats, df_salaires, nb_avec_salaire, nb_total, df_experience


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




__all__ = [
    "CLIENT_ID",
    "CLIENT_SECRET",
    "SCOPE_OFFRES",
    "get_token",
    "_params_filtre_poste",
    "_REF_LANGAGES_INFORMATIQUES",
    "_REF_OUTILS_INFORMATIQUES",
    "_classifier_competence",
    "_normaliser",
    "calculer_correspondance_offre",
    "calculer_correspondance_recruteur",
    "analyser_competences",
    "get_secteurs_activite",
    "get_referentiel_appellations",
    "_extraire_code_rome",
    "DICTIONNAIRE_INTITULES_MODERNES",
    "_normaliser_texte",
    "suggerer_postes",
    "chercher_offres",
    "resoudre_codes_rome",
    "secteurs_pour_poste",
    "rechercher_offres_completes",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "ADZUNA_BASE_URL",
    "DEPARTEMENTS_VERS_NOM",
    "adzuna_configure",
    "departement_vers_lieu_adzuna",
    "rechercher_offres_adzuna",
    "_adapter_offre_adzuna",
    "_deduire_type_contrat",
    "fusionner_offres",
    "volumes_departement_offres_multi",
    "rechercher_offres_completes_multi",
    "chercher_offres_multi",
    "offres_par_ville_multi",
    "evolution_offres_annuelle_multi",
    "repartition_contrats_et_salaires_multi",
    "offres_par_ville",
    "volumes_departement_offres",
    "_CANDIDATS_SCOPE_STATS_MARCHE",
    "BASE_STATS_MARCHE",
    "_appeler_indicateur",
    "_appel_avec_decouverte_scope",
    "demandeurs_emploi_departement",
    "demandeurs_emploi_departement_multi",
    "_MOIS_FR",
    "_formater_mois_fr",
    "evolution_offres_annuelle",
    "repartition_contrats_et_salaires",
    "calculer_tension",
    "interpreter_tension",
]
