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
import re
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
    - motsCles (si renseigné) pour "Tous les postes" (recherche large, indexée sur le
      même métier que la recherche de profil)
    secteur_activite : un code NAF unique (str) est transmis directement en paramètre
    d'API, quel que soit code_rome. Une LISTE de codes (multi-secteur) n'est en
    revanche jamais transmise à l'API (qui n'accepte qu'une seule valeur) — le
    filtrage se fait après coup côté Python via filtrer_offres_par_secteurs().
    """
    params = {} if code_rome == "TOUS" else {"codeROME": code_rome}
    if code_rome == "TOUS" and mots_cles:
        params["motsCles"] = mots_cles
    if secteur_activite and isinstance(secteur_activite, str):
        params["secteurActivite"] = secteur_activite
    return params


def filtrer_offres_par_secteurs(offres, codes_secteurs):
    """
    Filtre une liste d'offres brutes sur une liste de codes NAF (multi-secteur,
    filtrage post-fusion — l'API France Travail n'accepte qu'un seul code
    secteurActivite par requête). Si codes_secteurs est None, vide, ou un simple
    code unique (str, déjà appliqué côté API), renvoie les offres inchangées.
    """
    if not codes_secteurs or isinstance(codes_secteurs, str):
        return offres
    codes_secteurs = set(codes_secteurs)
    return [o for o in offres if o.get("secteurActivite") in codes_secteurs]


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

# France Travail n'a PAS de champ API dédié "certifications" (confirmé : le schéma
# d'offre expose "formations" — niveau/domaine d'études requis, pas des certifications
# nommées — et "competences", une liste libre où des certifications apparaissent parfois
# mélangées aux autres compétences). Cette liste sert donc à les repérer par mot-clé dans
# ce même champ libre, comme pour les outils/langages — couverture partielle par nature,
# à enrichir si des cas manquants remontent en usage réel.
_REF_CERTIFICATIONS = {
    # Gestion de projet / méthodes
    "pmp", "prince2", "prince 2", "capm", "itil", "cobit", "six sigma", "lean six sigma",
    "lean management", "scrum master", "psm", "csm", "safe agilist", "safe", "product owner certifié",
    "pspo",
    # Cybersécurité / IT
    "cissp", "cism", "cisa", "ceh", "oscp", "comptia", "security+", "network+",
    "ccna", "ccnp", "ccie", "mcsa", "mcse", "rhce", "lpic",
    # Cloud
    "aws certified", "aws solutions architect", "azure certified", "microsoft certified",
    "google cloud certified", "gcp certified", "terraform associate", "kubernetes certified", "ckad", "cka",
    # Data / IA
    "tensorflow developer certificate", "databricks certified", "sas certified",
    # Qualité / normes
    "iso 27001", "iso 9001", "iso 14001", "iso 45001", "haccp", "qualiopi",
    # Langues
    "toeic", "toefl", "ielts", "bulats", "linguaskill", "delf", "dalf", "goethe zertifikat", "dele",
    # Finance / comptabilité / droit
    "amf", "dscg", "dec", "cfa", "cfa level", "frm",
    # Marketing / vente
    "google ads", "google analytics certified", "hubspot certified", "meta blueprint",
    # Sécurité / logistique / terrain
    "caces", "habilitation électrique", "habilitation electrique", "sst", "hacces",
    "bafa", "bafd", "permis b", "permis c", "permis ce", "permis poids lourd", "fimo", "fco", "adr",
    "ifop", "ifsi", "diplôme d'état", "diplome d'etat",
    # RH / immobilier
    "carte professionnelle", "carte t", "certification voltaire", "tosa",
}


def _classifier_competence(libelle):
    """Classe un libellé de compétence en 'langage', 'outil', 'certification' ou
    'competence' (générique). Certification vérifiée en premier : certains sigles
    (ex: "AWS Certified...") contiennent aussi un nom d'outil ("aws")."""
    l = f" {libelle.lower().strip()} "
    for certif in _REF_CERTIFICATIONS:
        if certif in l:
            return "certification"
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
    extrait leur champ 'competences' pour bâtir 4 listes de suggestions
    (compétences génériques / outils informatiques / langages informatiques /
    certifications), chacune avec un % d'offres qui la mentionne.

    NB certifications : France Travail n'a pas de champ API dédié aux certifications
    (le schéma expose "formations" pour le niveau/domaine d'études requis, pas des
    certifications nommées) — repérées ici par mot-clé à la fois dans le champ
    structuré "competences" ET dans le texte complet de la fiche de poste (intitulé +
    description), une certification étant souvent mentionnée en phrase libre plutôt
    que comme un tag structuré. Couverture partielle par construction.
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
        if departement:
            params["departement"] = departement
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
    compteurs = {"competence": Counter(), "outil": Counter(), "langage": Counter(), "certification": Counter()}

    for offre in toutes_offres:
        competences_offre = offre.get("competences", [])
        libelles_vus = set()  # évite un double comptage si dupliqué dans la même offre
        for comp in competences_offre:
            libelle = (comp.get("libelle") or "").strip()
            if not libelle or libelle in libelles_vus:
                continue
            libelles_vus.add(libelle)
            categorie = _classifier_competence(libelle)
            compteurs[categorie][libelle] += 1

        # Certifications aussi repérées dans le texte complet de la fiche de poste
        # (intitulé + description rédigée par le recruteur), pas seulement dans le
        # champ structuré "competences" — une certification est souvent mentionnée
        # en phrase libre ("Certification PMP appréciée", "CACES R489 requis")
        # plutôt que comme un tag structuré.
        texte_fiche_poste = f"{offre.get('intitule', '')} {offre.get('description', '')}".lower()
        if texte_fiche_poste.strip():
            for terme_certif in _REF_CERTIFICATIONS:
                if terme_certif in texte_fiche_poste:
                    libelle_certif = terme_certif.upper() if (" " not in terme_certif and len(terme_certif) <= 6) else terme_certif.title()
                    compteurs["certification"][libelle_certif] += 1

    def _construire_df(compteur):
        if nb_total_offres == 0:
            return pd.DataFrame(columns=["libelle", "nombre_offres", "pourcentage"])
        lignes = [
            {"libelle": lib, "nombre_offres": n, "pourcentage": round(100 * n / nb_total_offres)}
            for lib, n in compteur.most_common(15)
        ]
        # Colonnes explicites : pd.DataFrame([]) sans "columns=" ne crée AUCUNE colonne
        # quand lignes est vide (ex: des offres ont été trouvées mais aucune ne mentionne
        # de compétence dans cette catégorie précise) — provoquait un KeyError("libelle")
        # plus loin sur df["libelle"] au lieu d'un DataFrame vide exploitable normalement.
        return pd.DataFrame(lignes, columns=["libelle", "nombre_offres", "pourcentage"])

    return (
        _construire_df(compteurs["competence"]),
        _construire_df(compteurs["outil"]),
        _construire_df(compteurs["langage"]),
        _construire_df(compteurs["certification"]),
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


_RE_GENRE_ROME = re.compile(r"^(\S+)\s*/\s*\S+\b(.*)$")


def _normaliser_texte(texte):
    """
    Minuscules et retrait des accents, pour des comparaisons robustes. Retire
    aussi la variante de genre en tête d'un libellé ROME type "Chef / Cheffe de
    projet informatique" -> "chef de projet informatique" : sans ça, une saisie
    comme "chef de projet informatique" ne correspondait JAMAIS au vrai préfixe
    du libellé officiel (le "/ Cheffe" s'interposait), ce qui cassait toute
    correspondance directe et faisait retomber la recherche sur du bruit flou.
    """
    texte = texte.lower().strip()
    remplacements = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    texte = texte.translate(remplacements)
    correspondance_genre = _RE_GENRE_ROME.match(texte)
    if correspondance_genre:
        texte = (correspondance_genre.group(1) + correspondance_genre.group(2)).strip()
    return texte


ROMEO_SCOPE = "api_romeov2"  # confirmé via un serveur MCP tiers documentant ce scope exact

# Chemins d'endpoint candidats : aucune documentation publique officielle trouvée en
# clair pour ROMEO 2 (contrairement au scope, confirmé) — on suit la convention
# observée sur le reste de francetravail.io (api.francetravail.io/partenaire/
# <produit>/v<version>/<ressource>) et on teste plusieurs variantes plausibles.
_CANDIDATS_ENDPOINT_ROMEO = [
    "https://api.francetravail.io/partenaire/romeo/v2/predictionMetiers",
    "https://api.francetravail.io/partenaire/romeo/v1/predictionMetiers",
    "https://api.francetravail.io/partenaire/romeo/v2/predictionMetier",
    "https://api.francetravail.io/partenaire/rome-romeo/v2/predictionMetiers",
]
# Idem pour le nom du champ portant l'intitulé dans le corps de la requête POST.
_CANDIDATS_CHAMP_INTITULE_ROMEO = ["intitulesPostes", "libellesAppellation", "intitules"]


def predire_rome_romeo(intitule, seuil_score=0.3, nb_resultats=5):
    """
    Utilise ROMEO 2 (modèle d'IA de France Travail) pour rapprocher un intitulé de
    poste en texte libre des appellations ROME les plus probables, avec un score
    de confiance — robuste sur des cas que notre recherche floue maison ne peut
    pas résoudre par nature (ex: "Responsable de projet" -> "Chef de projet",
    vrais synonymes métier sans aucune ressemblance textuelle).

    ATTENTION — expérimental : le scope OAuth ('api_romeov2') est confirmé via une
    source tierce documentée, mais ni le chemin exact de l'endpoint ni le format du
    corps de requête n'ont pu être vérifiés via une documentation officielle
    publique au moment de l'écriture. Cette fonction teste plusieurs combinaisons
    plausibles (et mémorise en session celle qui fonctionne), et se dégrade
    silencieusement (renvoie None) si aucune ne répond correctement — jamais
    d'erreur remontée à l'utilisateur, mais peut très bien ne renvoyer rien tant
    que la vraie combinaison n'a pas été confirmée en conditions réelles.

    Retourne une liste de {"code_rome":..., "libelle":..., "score":...} triée par
    score décroissant, ou None si rien n'a fonctionné (dans ce cas, le reste de
    l'app continue de fonctionner exactement comme avant — intégration purement
    additive, jamais un point de blocage).
    """
    try:
        token = get_token(ROMEO_SCOPE)
    except Exception:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    cle_endpoint = "romeo_endpoint_valide"
    cle_champ = "romeo_champ_intitule_valide"
    cle_indisponible = "romeo_indisponible"

    # Coupe-circuit : si aucune combinaison endpoint/champ n'a fonctionné une
    # première fois dans cette session, on ne retente plus à chaque frappe (ça
    # ferait jusqu'à 12 requêtes réseau par suggestion pour rien) — seul un
    # rechargement complet de l'app retente une découverte fraîche.
    if st.session_state.get(cle_indisponible):
        return None

    endpoint_connu = st.session_state.get(cle_endpoint)
    champ_connu = st.session_state.get(cle_champ)
    endpoints_a_essayer = (
        [endpoint_connu] + [e for e in _CANDIDATS_ENDPOINT_ROMEO if e != endpoint_connu]
        if endpoint_connu else _CANDIDATS_ENDPOINT_ROMEO
    )
    champs_a_essayer = (
        [champ_connu] + [c for c in _CANDIDATS_CHAMP_INTITULE_ROMEO if c != champ_connu]
        if champ_connu else _CANDIDATS_CHAMP_INTITULE_ROMEO
    )

    for endpoint in endpoints_a_essayer:
        for champ in champs_a_essayer:
            try:
                r = requests.post(endpoint, headers=headers, json={champ: [intitule]}, timeout=8)
            except requests.RequestException:
                continue
            if r.status_code not in (200, 206):
                continue
            try:
                data = r.json()
            except ValueError:
                continue
            # Formats de réponse possibles selon la vraie structure (liste plate,
            # ou liste de listes une par intitulé soumis) — on prend ce qui existe.
            predictions_brutes = data[0] if data and isinstance(data, list) and isinstance(data[0], list) else data
            if not isinstance(predictions_brutes, list) or not predictions_brutes:
                continue

            resultats = []
            for pred in predictions_brutes:
                if not isinstance(pred, dict):
                    continue
                score = pred.get("score") or pred.get("scorePrediction")
                code_rome = pred.get("codeRome") or pred.get("codeMetier")
                libelle = pred.get("libelleRome") or pred.get("libelleAppellation") or pred.get("libelle")
                if code_rome is None:
                    continue
                resultats.append({"code_rome": code_rome, "libelle": libelle, "score": score})

            if resultats:
                st.session_state[cle_endpoint] = endpoint
                st.session_state[cle_champ] = champ
                resultats = [r for r in resultats if r["score"] is None or r["score"] >= seuil_score]
                resultats.sort(key=lambda r: r["score"] or 0, reverse=True)
                return resultats[:nb_resultats]

    st.session_state[cle_indisponible] = True
    return None


@st.cache_data(ttl=1800)
def suggerer_postes(saisie, max_resultats=8):
    """
    Suggère des postes du référentiel ROME à partir d'un intitulé libre/moderne.
    Ordre de priorité, du plus fiable au plus approximatif :
      1. Dictionnaire de correspondances connues (ex: "Data Analyst" -> "Analyste
         de données").
      2. Correspondance EXACTE (normalisée) avec un libellé officiel.
      3. Le libellé COMMENCE par la saisie (ex: "chef de projet" tapé ->
         "Chef de projet informatique") — presque toujours une vraie
         spécialisation du même métier, la priorité recherchée en pratique.
      4. La saisie apparaît ailleurs dans le libellé, précédée d'un autre mot
         (ex: "chef de projet" tapé -> "Assistant chef de projet") — une
         correspondance réelle mais qui change souvent le métier (rôle
         d'appui, subalterne...), donc délibérément moins prioritaire qu'un
         préfixe direct.
      5. Recherche floue en dernier recours seulement (fautes de frappe,
         variantes non couvertes ci-dessus), plafonnée pour ne jamais dépasser
         une correspondance directe.
    Retourne une liste de libellés d'appellations officielles.
    """
    saisie_normalisee = _normaliser_texte(saisie)
    if len(saisie_normalisee) < 2:
        return []

    appellations = get_referentiel_appellations()
    labels = sorted({a.get("libelle", "").strip() for a in appellations if a.get("libelle")})
    if not labels:
        return []

    candidats = {}  # libelle -> meilleur score
    labels_normalises = {label: _normaliser_texte(label) for label in labels}

    # 0) ROMEO 2 (IA), en complément — capte les vrais synonymes métier qu'aucune
    # comparaison textuelle (exacte, préfixe, ou floue) ne peut deviner par nature
    # (ex: "Responsable de projet" -> "Chef de projet"). Purement additif : si
    # l'appel échoue (endpoint expérimental, cf. predire_rome_romeo), on continue
    # avec les étapes suivantes exactement comme avant, sans rien perdre.
    predictions_romeo = predire_rome_romeo(saisie)
    if predictions_romeo:
        labels_par_code_rome = {}
        for a in appellations:
            code = _extraire_code_rome(a)
            if code and code not in labels_par_code_rome:
                labels_par_code_rome[code] = a.get("libelle", "").strip()
        for pred in predictions_romeo:
            label_predit = labels_par_code_rome.get(pred["code_rome"])
            if label_predit:
                score_romeo = round((pred["score"] or 0.5) * 100)
                candidats[label_predit] = max(candidats.get(label_predit, 0), score_romeo)

    # 1) Dictionnaire : si un terme connu est contenu dans la saisie, on cherche
    # les appellations officielles correspondant aux mots-clés français associés.
    for terme_moderne, mots_cles_fr in DICTIONNAIRE_INTITULES_MODERNES.items():
        if terme_moderne in saisie_normalisee:
            for mot_cle in mots_cles_fr:
                mot_cle_normalise = _normaliser_texte(mot_cle)
                for label, label_norm in labels_normalises.items():
                    if mot_cle_normalise in label_norm:
                        candidats[label] = max(candidats.get(label, 0), 100)

    # 2/3/4) Correspondance directe (exacte, préfixe, ou incluse ailleurs) —
    # avant toute recherche floue, sur la base de la présence littérale de la
    # saisie dans le libellé normalisé.
    for label, label_norm in labels_normalises.items():
        if label_norm == saisie_normalisee:
            candidats[label] = max(candidats.get(label, 0), 100)
        elif label_norm.startswith(saisie_normalisee):
            candidats[label] = max(candidats.get(label, 0), 95)
        elif f" {saisie_normalisee} " in f" {label_norm} " or label_norm.endswith(f" {saisie_normalisee}"):
            candidats[label] = max(candidats.get(label, 0), 70)

    # 5) Recherche floue, en tout dernier recours (fautes de frappe/variantes non
    # couvertes ci-dessus) — fuzz.WRatio écarté : testé et confirmé trop permissif
    # avec des textes courts (donnait 85,5 à "chef de projet" vs "accessoiriste de
    # décor", des libellés sans aucun rapport). fuzz.token_sort_ratio reste strict
    # sur les paires non liées (score ~30-40 sur le même exemple) tout en
    # rattrapant correctement une vraie faute de frappe (~90-96). Score plafonné à
    # 90 pour ne jamais dépasser une correspondance directe.
    norm_vers_label = {}
    for label, norm in labels_normalises.items():
        norm_vers_label.setdefault(norm, label)
    resultats_flous = process.extract(
        saisie_normalisee, list(norm_vers_label.keys()), scorer=fuzz.token_sort_ratio, limit=max_resultats * 2
    )
    for label_normalise, score, _ in resultats_flous:
        if score >= 70:
            label = norm_vers_label[label_normalise]
            candidats[label] = max(candidats.get(label, 0), min(score, 90))

    # Pénalité (affinage) par mot supplémentaire par rapport à la saisie — utile
    # surtout pour départager plusieurs correspondances de catégorie 4 entre elles.
    mots_saisie = len(saisie_normalisee.split())
    candidats_ajustes = {}
    for label, score in candidats.items():
        mots_label = len(labels_normalises[label].split())
        mots_en_trop = max(0, mots_label - mots_saisie)
        candidats_ajustes[label] = score - (mots_en_trop * 3)

    resultats_tries = sorted(candidats_ajustes.items(), key=lambda x: x[1], reverse=True)
    return [label for label, _ in resultats_tries[:max_resultats]]


def chercher_offres(code_rome, departement, secteur_naf=None, jours_max=None, mots_cles=None, range_str="0-149"):
    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"range": range_str}
    if departement:
        params["departement"] = departement
    params.update(_params_filtre_poste(code_rome, mots_cles))
    if secteur_naf and isinstance(secteur_naf, str):
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
    resultats = data.get("resultats", [])
    if isinstance(secteur_naf, list) and secteur_naf:
        resultats = filtrer_offres_par_secteurs(resultats, secteur_naf)
        # Le total renvoyé par l'API ne reflète pas ce filtrage post-fetch multi-secteur :
        # on retombe sur le nombre réellement filtré, plus honnête que le total brut.
        total = len(resultats)
    return resultats, total


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
        if secteur_activite and isinstance(secteur_activite, str):
            params["secteurActivite"] = secteur_activite
        r = requests.get(url, headers=headers, params=params)
        if r.status_code not in (200, 206):
            break
        resultats = r.json().get("resultats", [])
        toutes_offres.extend(resultats)
        if len(resultats) < taille_page:
            break

    toutes_offres = filtrer_offres_par_secteurs(toutes_offres, secteur_activite)

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
        params = {"range": f"{debut}-{fin}"}
        if departement:
            params["departement"] = departement
        params.update(_params_filtre_poste(code_rome, mots_cles))
        if secteur_activite and isinstance(secteur_activite, str):
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
    return filtrer_offres_par_secteurs(toutes_offres, secteur_activite)


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

# ---------------------------------------------------------------------------
# Ville de repli (la plus grande ville du département — généralement la
# préfecture, sauf quelques exceptions notables comme 76 -> Le Havre plutôt que
# Rouen) avec ses coordonnées GPS approximatives. Utilisée pour positionner sur
# la carte les offres dont le lieu de travail n'est renseigné qu'au niveau
# département (pas de latitude/longitude précise côté France Travail).
# ---------------------------------------------------------------------------
DEPARTEMENTS_CHEF_LIEU = {
    "01": ("Bourg-en-Bresse", 46.2058, 5.2255), "02": ("Laon", 49.5642, 3.6247),
    "03": ("Moulins", 46.5606, 3.3325), "04": ("Digne-les-Bains", 44.0925, 6.2361),
    "05": ("Gap", 44.5594, 6.0790), "06": ("Nice", 43.7102, 7.2620),
    "07": ("Privas", 44.7355, 4.5985), "08": ("Charleville-Mézières", 49.7714, 4.7199),
    "09": ("Foix", 42.9646, 1.6050), "10": ("Troyes", 48.2973, 4.0744),
    "11": ("Carcassonne", 43.2130, 2.3491), "12": ("Rodez", 44.3505, 2.5738),
    "13": ("Marseille", 43.2965, 5.3698), "14": ("Caen", 49.1829, -0.3707),
    "15": ("Aurillac", 44.9282, 2.4444), "16": ("Angoulême", 45.6484, 0.1562),
    "17": ("La Rochelle", 46.1603, -1.1511), "18": ("Bourges", 47.0810, 2.3987),
    "19": ("Brive-la-Gaillarde", 45.1590, 1.5335), "2A": ("Ajaccio", 41.9192, 8.7386),
    "2B": ("Bastia", 42.7028, 9.4508), "21": ("Dijon", 47.3220, 5.0415),
    "22": ("Saint-Brieuc", 48.5141, -2.7654), "23": ("Guéret", 46.1700, 1.8700),
    "24": ("Périgueux", 45.1848, 0.7217), "25": ("Besançon", 47.2380, 6.0243),
    "26": ("Valence", 44.9334, 4.8924), "27": ("Évreux", 49.0270, 1.1509),
    "28": ("Chartres", 48.4439, 1.4894), "29": ("Brest", 48.3904, -4.4861),
    "30": ("Nîmes", 43.8367, 4.3601), "31": ("Toulouse", 43.6047, 1.4442),
    "32": ("Auch", 43.6465, 0.5854), "33": ("Bordeaux", 44.8378, -0.5792),
    "34": ("Montpellier", 43.6108, 3.8767), "35": ("Rennes", 48.1173, -1.6778),
    "36": ("Châteauroux", 46.8106, 1.6910), "37": ("Tours", 47.3941, 0.6848),
    "38": ("Grenoble", 45.1885, 5.7245), "39": ("Lons-le-Saunier", 46.6742, 5.5527),
    "40": ("Mont-de-Marsan", 43.8897, -0.4980), "41": ("Blois", 47.5861, 1.3359),
    "42": ("Saint-Étienne", 45.4397, 4.3872), "43": ("Le Puy-en-Velay", 45.0432, 3.8859),
    "44": ("Nantes", 47.2184, -1.5536), "45": ("Orléans", 47.9029, 1.9093),
    "46": ("Cahors", 44.4478, 1.4409), "47": ("Agen", 44.2049, 0.6205),
    "48": ("Mende", 44.5183, 3.5006), "49": ("Angers", 47.4784, -0.5632),
    "50": ("Cherbourg-en-Cotentin", 49.6337, -1.6222), "51": ("Reims", 49.2583, 4.0317),
    "52": ("Chaumont", 48.1113, 5.1391), "53": ("Laval", 48.0698, -0.7700),
    "54": ("Nancy", 48.6921, 6.1844), "55": ("Bar-le-Duc", 48.7714, 5.1608),
    "56": ("Lorient", 47.7482, -3.3660), "57": ("Metz", 49.1193, 6.1757),
    "58": ("Nevers", 46.9896, 3.1590), "59": ("Lille", 50.6292, 3.0573),
    "60": ("Beauvais", 49.4295, 2.0807), "61": ("Alençon", 48.4322, 0.0900),
    "62": ("Calais", 50.9513, 1.8587), "63": ("Clermont-Ferrand", 45.7772, 3.0870),
    "64": ("Pau", 43.2951, -0.3708), "65": ("Tarbes", 43.2328, 0.0784),
    "66": ("Perpignan", 42.6886, 2.8948), "67": ("Strasbourg", 48.5734, 7.7521),
    "68": ("Mulhouse", 47.7508, 7.3359), "69": ("Lyon", 45.7640, 4.8357),
    "70": ("Vesoul", 47.6236, 6.1548), "71": ("Chalon-sur-Saône", 46.7800, 4.8524),
    "72": ("Le Mans", 48.0061, 0.1996), "73": ("Chambéry", 45.5646, 5.9178),
    "74": ("Annecy", 45.8992, 6.1294), "75": ("Paris", 48.8566, 2.3522),
    "76": ("Le Havre", 49.4944, 0.1079), "77": ("Melun", 48.5388, 2.6600),
    "78": ("Versailles", 48.8049, 2.1204), "79": ("Niort", 46.3239, -0.4587),
    "80": ("Amiens", 49.8942, 2.2957), "81": ("Albi", 43.9298, 2.1480),
    "82": ("Montauban", 44.0181, 1.3533), "83": ("Toulon", 43.1242, 5.9280),
    "84": ("Avignon", 43.9493, 4.8055), "85": ("La Roche-sur-Yon", 46.6705, -1.4269),
    "86": ("Poitiers", 46.5802, 0.3404), "87": ("Limoges", 45.8336, 1.2611),
    "88": ("Épinal", 48.1735, 6.4519), "89": ("Auxerre", 47.7982, 3.5731),
    "90": ("Belfort", 47.6379, 6.8629), "91": ("Évry-Courcouronnes", 48.6288, 2.4419),
    "92": ("Boulogne-Billancourt", 48.8397, 2.2400), "93": ("Saint-Denis", 48.9362, 2.3574),
    "94": ("Créteil", 48.7904, 2.4556), "95": ("Argenteuil", 48.9479, 2.2467),
    "971": ("Les Abymes", 16.2699, -61.5058), "972": ("Fort-de-France", 14.6161, -61.0588),
    "973": ("Cayenne", 4.9224, -52.3135), "974": ("Saint-Denis", -20.8789, 55.4481),
    "976": ("Mamoudzou", -12.7806, 45.2278),
}


def departements_vers_param(departements):
    """
    Convertit une sélection de départements en valeur du paramètre 'departement'
    pour l'API France Travail, qui accepte plusieurs codes séparés par une
    virgule (cf. data.gouv.fr : "L'API Offres d'emploi offre la possibilité de
    filtrer sur plusieurs métiers, communes, départements"). None ou une liste
    vide -> pas de paramètre du tout (recherche "Toute la France").
    """
    if not departements:
        return None
    if isinstance(departements, str):
        return departements
    return ",".join(departements)


def departement_est_multiple(departement_param):
    """True si departement_param couvre plus d'un département : soit une
    recherche nationale (None, aucun filtre), soit plusieurs codes explicites
    séparés par une virgule. Utilisé pour désactiver la tension du marché, qui
    ne se calcule proprement que pour UN seul département (statistique Dares
    trimestrielle, un appel par territoire)."""
    return departement_param is None or "," in str(departement_param)


_RE_CODE_DEPARTEMENT_PREFIXE = re.compile(r"^(2[AB]|\d{2,3})\s*-")


def _deviner_departement_offre(ville_libelle, departement_recherche):
    """
    Déduit un code département pour positionner sur la carte une offre sans
    coordonnées précises : d'abord depuis le préfixe du libellé de lieu
    lui-même (ex: "13 - Bouches-du-Rhône" -> "13", fiable quel que soit le
    nombre de départements recherchés), sinon depuis le département de
    recherche SI c'est un code unique (pas une liste multi-département ni une
    recherche nationale, où on ne peut pas savoir lequel des départements
    sélectionnés concerne cette offre précise — dans ce cas, retourne None :
    l'offre restera non localisée plutôt que mal placée).
    """
    m = _RE_CODE_DEPARTEMENT_PREFIXE.match(ville_libelle or "")
    if m:
        return m.group(1)
    if departement_recherche and isinstance(departement_recherche, str) and "," not in departement_recherche:
        return departement_recherche
    return None



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
def volumes_departement_offres_multi(codes_rome, departement, secteur_activite=None, jours_max=None):
    """Somme des volumes d'offres pour une liste de codes ROME."""
    return sum(
        volumes_departement_offres(code, departement, secteur_activite=secteur_activite, jours_max=jours_max)
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


def rechercher_offres_toutes_sources(mots_cles, departement, jours_max):
    """
    Recherche d'offres en mode large — codeROME="TOUS" + recherche libre sur
    motsCles côté France Travail, complétée par Adzuna, fusionnée et dédupliquée.
    mots_cles vide (ou None) = toutes les offres actives, sans filtre mot-clé.
    Pas de filtre secteur (retiré de l'app) ni de résolution en code ROME précis :
    la recherche est volontairement large, la précision se fait via les mots-clés
    tapés par l'utilisateur plutôt que via un code métier étroit.
    """
    resultats, total = chercher_offres("TOUS", departement, None, jours_max, mots_cles=mots_cles or "")

    for o in resultats:
        o.setdefault("source", "France Travail")

    if mots_cles and adzuna_configure():
        lieu = departement_vers_lieu_adzuna(departement) if departement and "," not in departement else None
        offres_adzuna = rechercher_offres_adzuna(mots_cles, ou=lieu)
        if offres_adzuna:
            resultats = fusionner_offres(resultats, offres_adzuna)
            # Le total France Travail seul ne reflète pas les offres Adzuna ajoutées.
            total = max(total, len(resultats))

    return resultats, total


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
            .agg(
                nombre_offres=("nombre_offres", "sum"),
                # "first" seul peut retomber sur une ligne à latitude/longitude manquantes
                # si le même nom de ville apparaît d'abord dans les résultats d'un poste
                # dont l'offre n'avait pas de coordonnées — on prend la première valeur
                # RÉELLEMENT disponible parmi tous les postes fusionnés.
                latitude=("latitude", lambda s: next((v for v in s if pd.notna(v)), None)),
                longitude=("longitude", lambda s: next((v for v in s if pd.notna(v)), None)),
                # False (précis) l'emporte sur True (repli chef-lieu) si l'un des postes
                # fusionnés avait bien des coordonnées précises pour ce même libellé de lieu.
                approximatif=("approximatif", "min"),
            )
            .sort_values("nombre_offres", ascending=False)
            .reset_index(drop=True)
        )
    else:
        df_villes = pd.DataFrame(columns=["ville", "nombre_offres", "latitude", "longitude", "approximatif"])

    if dfs_entreprises:
        df_ent_concat = pd.concat(dfs_entreprises, ignore_index=True)
        # Regroupement insensible à la casse/espaces : "Signe+" et "SIGNE +" doivent
        # fusionner en une seule ligne plutôt que d'apparaître comme deux entreprises.
        df_ent_concat["_cle"] = df_ent_concat["entreprise"].str.strip().str.lower()
        df_entreprises = (
            df_ent_concat.groupby("_cle", as_index=False)
            .agg(
                entreprise=("entreprise", "first"),
                nombre_offres=("nombre_offres", "sum"),
                villes=("villes", lambda s: ", ".join(sorted({v.strip() for grp in s for v in grp.split(",")}))),
            )
            .drop(columns="_cle")
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


LABEL_ENTREPRISE_ANONYME = "Entreprise non communiquée"


def _nom_entreprise_normalise(offre):
    """Nom d'entreprise d'une offre, ou LABEL_ENTREPRISE_ANONYME si l'offre est diffusée
    sans nom d'entreprise visible (recrutement anonyme) — regroupe ces offres sous une
    même étiquette au lieu de les exclure du tableau des recruteurs."""
    return offre.get("entreprise", {}).get("nom") or LABEL_ENTREPRISE_ANONYME


# ---------------------------------------------------------------------------
# Fiche entreprise — API "Recherche d'entreprises" (data.gouv.fr / DINUM), publique
# et gratuite, SANS clé ni compte à créer (contrairement à ROMEO/RNCP/Data Emploi,
# qui restent à intégrer une fois les accès confirmés). Synthèse des données SIRENE
# (INSEE) et du Registre National des Entreprises — utile pour préparer une
# candidature spontanée (candidat) ou un argumentaire de prospection (agence).
# ---------------------------------------------------------------------------
RECHERCHE_ENTREPRISES_URL = "https://recherche-entreprises.api.gouv.fr/search"

# Codes INSEE "tranche d'effectif salarié" -> libellé lisible.
TRANCHE_EFFECTIF_LABELS = {
    "NN": "Effectif non renseigné", "00": "0 salarié", "01": "1 à 2 salariés",
    "02": "3 à 5 salariés", "03": "6 à 9 salariés", "11": "10 à 19 salariés",
    "12": "20 à 49 salariés", "21": "50 à 99 salariés", "22": "100 à 199 salariés",
    "31": "200 à 249 salariés", "32": "250 à 499 salariés", "41": "500 à 999 salariés",
    "42": "1 000 à 1 999 salariés", "51": "2 000 à 4 999 salariés",
    "52": "5 000 à 9 999 salariés", "53": "10 000 salariés et plus",
}


@st.cache_data(ttl=86400)
def rechercher_entreprise_siren(nom_entreprise):
    """
    Cherche une entreprise par nom sur l'API "Recherche d'entreprises" (DINUM,
    gratuite, sans clé) et renvoie une fiche synthétique, ou None si rien trouvé.

    Récupère plusieurs candidats (pas juste le premier) et préfère celui qui a un
    effectif renseigné : pour un grand groupe, le tout premier résultat est souvent
    la holding de tête (ex: "Capgemini SE"), qui n'emploie souvent personne en
    propre et n'a qu'un seul établissement déclaré — l'entité opérationnelle réelle
    (qui a un vrai effectif) est presque toujours plus informative pour un candidat
    ou un recruteur.

    La recherche par nom reste approximative — le résultat doit être présenté
    comme une correspondance probable à vérifier, pas une certitude, surtout pour
    des noms d'entreprise courts ou très courants.
    """
    if not nom_entreprise or nom_entreprise == LABEL_ENTREPRISE_ANONYME:
        return None
    try:
        r = requests.get(
            RECHERCHE_ENTREPRISES_URL, params={"q": nom_entreprise, "per_page": 5}, timeout=8
        )
        r.raise_for_status()
    except requests.RequestException:
        return None

    resultats = r.json().get("results", [])
    if not resultats:
        return None

    res = next((c for c in resultats if c.get("tranche_effectif_salarie")), resultats[0])
    siege = res.get("siege", {}) or {}
    tranche = res.get("tranche_effectif_salarie")

    return {
        "nom": res.get("nom_complet") or res.get("nom_raison_sociale"),
        "siren": res.get("siren"),
        "siret_siege": siege.get("siret"),
        "naf": res.get("activite_principale"),
        "secteur_libelle": naf_vers_libelle(res.get("activite_principale")),
        "categorie_entreprise": res.get("categorie_entreprise"),  # TPE/PME/ETI/GE
        "tranche_effectif_libelle": TRANCHE_EFFECTIF_LABELS.get(tranche, "Non renseigné"),
        "adresse": siege.get("adresse"),
        "date_creation": res.get("date_creation"),
        "forme_juridique": res.get("nature_juridique"),
        "est_qualiopi": (res.get("complements") or {}).get("est_qualiopi"),
        # Proxy de présence géographique : nombre d'établissements ouverts sur le
        # territoire. Ne dit pas OÙ (ça demanderait un appel supplémentaire par
        # établissement), juste une idée de l'étendue — présenté comme tel.
        "nombre_etablissements_ouverts": res.get("nombre_etablissements_ouverts"),
        "url_annuaire": f"https://annuaire-entreprises.data.gouv.fr/entreprise/{res.get('siren')}" if res.get("siren") else None,
    }


@st.cache_data(ttl=3600)
def _referentiel_naf_vers_libelle():
    """Dict code NAF -> libellé, construit une seule fois à partir du référentiel
    secteurs d'activité France Travail (mêmes codes que le paramètre secteurActivite
    de l'API Offres d'emploi — à vérifier si jamais les codes SIRENE s'avèrent dans
    un format légèrement différent en pratique)."""
    return {s.get("code"): s.get("libelle") for s in get_secteurs_activite() if s.get("code")}


def naf_vers_libelle(code_naf):
    """Libellé humain d'un code NAF (ex: '84.11Z' -> 'Administration publique
    générale'), ou None si le code est absent du référentiel — mieux vaut ne rien
    afficher qu'un mauvais libellé deviné."""
    if not code_naf:
        return None
    return _referentiel_naf_vers_libelle().get(code_naf)


def rechercher_offres_entreprise(nom_entreprise, max_pages=1):
    """
    Recherche LARGE (nationale, tous postes confondus, motsCles=nom d'entreprise)
    pour maximiser les chances de trouver une offre exploitable — donc une
    description d'entreprise — même si celle-ci ne recrute pas actuellement sur
    le poste précis ciblé par l'utilisateur. Remplace une recherche restreinte au
    seul poste résolu, qui ratait des entreprises pourtant en train de recruter,
    juste pas sur ce poste-là.
    """
    if not nom_entreprise or nom_entreprise == LABEL_ENTREPRISE_ANONYME:
        return []
    return rechercher_offres_completes("TOUS", None, max_pages=max_pages, mots_cles=nom_entreprise)


WIKIPEDIA_HEADERS = {"User-Agent": "AideConseilEmploi/1.0 (outil d'aide à la recherche d'emploi)"}


@st.cache_data(ttl=86400)
def rechercher_wikipedia_entreprise(nom_entreprise):
    """
    Cherche un article Wikipédia (français) correspondant à l'entreprise et en
    renvoie un résumé synthétique — souvent plus riche et plus lisible que le code
    NAF de la fiche SIRENE pour comprendre le VRAI domaine d'expertise d'une
    entreprise (positionnement, histoire, activités). Ne couvre par nature que les
    entreprises suffisamment connues pour avoir un article — inutile pour la
    plupart des PME/TPE, où rien ne sera trouvé.

    Deux appels : 1) recherche du titre d'article le plus pertinent (l'entreprise
    n'a pas toujours un article au nom exact tapé), 2) résumé de cet article via
    l'API REST officielle de Wikipédia (gratuite, sans clé). Renvoie None si aucun
    article trouvé, si la page est une homonymie, ou en cas d'erreur réseau.
    """
    if not nom_entreprise:
        return None
    try:
        r_recherche = requests.get(
            "https://fr.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": nom_entreprise,
                "format": "json", "srlimit": 1,
            },
            headers=WIKIPEDIA_HEADERS, timeout=8,
        )
        r_recherche.raise_for_status()
        resultats_recherche = r_recherche.json().get("query", {}).get("search", [])
        if not resultats_recherche:
            return None
        titre = resultats_recherche[0]["title"]

        r_resume = requests.get(
            f"https://fr.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(titre)}",
            headers=WIKIPEDIA_HEADERS, timeout=8,
        )
        r_resume.raise_for_status()
        resume = r_resume.json()
    except requests.RequestException:
        return None

    if resume.get("type") == "disambiguation":  # page d'homonymie, pas exploitable telle quelle
        return None

    extrait = resume.get("extract")
    if not extrait:
        return None

    return {
        "titre": resume.get("title", titre),
        "extrait": extrait,
        "url": (resume.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
        # Identifiant Wikidata lié à cet article (ex: "Q193326" pour Capgemini) —
        # permet d'aller chercher des champs structurés (secteurs, effectif,
        # filiales) que le simple extrait Wikipédia ne contient pas.
        "wikidata_id": resume.get("wikibase_item"),
    }


@st.cache_data(ttl=86400)
def rechercher_wikidata_entreprise(wikidata_id):
    """
    Complète rechercher_wikipedia_entreprise() avec des champs structurés depuis
    Wikidata (la base de données liée à Wikipédia, gratuite et sans clé) :
    secteurs d'intervention (propriété "industry"/P452, PLUSIEURS valeurs
    possibles — plus riche qu'un unique code NAF), effectif (propriété
    "employees"/P1128, un vrai nombre avec sa date de mesure — plus précis que
    la tranche SIRENE), et filiales (propriété "subsidiary"/P355).

    Pays de présence VOLONTAIREMENT absent : Wikidata ne structure fiablement
    que le pays du SIÈGE (P17), pas l'empreinte internationale réelle d'une
    entreprise — l'inclure donnerait une fausse impression de couverture
    complète plutôt que de ne rien dire du tout.

    Deux appels : 1) les "claims" (déclarations) de l'entité, qui pour les
    secteurs/filiales ne sont que des identifiants Wikidata (QID) à résoudre ;
    2) un second appel groupé pour récupérer le libellé français de chaque QID
    trouvé. Renvoie None si rien d'exploitable (fréquent : beaucoup d'entités
    Wikidata d'entreprises ont un article mais peu de champs structurés remplis).
    """
    if not wikidata_id:
        return None
    try:
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities", "ids": wikidata_id, "format": "json",
                "props": "claims",
            },
            headers=WIKIPEDIA_HEADERS, timeout=8,
        )
        r.raise_for_status()
        claims = r.json().get("entities", {}).get(wikidata_id, {}).get("claims", {})
    except requests.RequestException:
        return None

    def _qids_pour_propriete(code_prop, limite=8):
        qids = []
        for claim in claims.get(code_prop, [])[:limite]:
            valeur = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(valeur, dict) and valeur.get("id"):
                qids.append(valeur["id"])
        return qids

    qids_industrie = _qids_pour_propriete("P452")
    qids_filiales = _qids_pour_propriete("P355", limite=10)

    # Effectif (P1128) : valeur numérique directe, rien à résoudre.
    effectif = None
    if claims.get("P1128"):
        valeur_effectif = claims["P1128"][0].get("mainsnak", {}).get("datavalue", {}).get("value")
        montant = valeur_effectif.get("amount") if isinstance(valeur_effectif, dict) else None
        if montant:
            try:
                effectif = int(float(montant))
            except (TypeError, ValueError):
                effectif = None

    tous_qids = qids_industrie + qids_filiales
    libelles = {}
    if tous_qids:
        try:
            r_labels = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities", "ids": "|".join(tous_qids), "format": "json",
                    "props": "labels", "languages": "fr",
                },
                headers=WIKIPEDIA_HEADERS, timeout=8,
            )
            r_labels.raise_for_status()
            for qid, ent in r_labels.json().get("entities", {}).items():
                label = ent.get("labels", {}).get("fr", {}).get("value")
                if label:
                    libelles[qid] = label
        except requests.RequestException:
            pass

    secteurs = [libelles[q] for q in qids_industrie if q in libelles]
    filiales = [libelles[q] for q in qids_filiales if q in libelles]

    if not secteurs and not effectif and not filiales:
        return None

    return {"secteurs": secteurs, "effectif": effectif, "filiales": filiales}


def infos_entretien_entreprise(nom_entreprise, offres_disponibles):
    """
    Repère, parmi une liste d'offres déjà récupérées, une offre de cette
    entreprise et en extrait le nécessaire pour préparer un entretien : le
    domaine d'activité TEL QUE DÉCRIT par France Travail (secteurActiviteLibelle,
    un libellé humain — plus parlant qu'un code NAF brut) et la description
    d'entreprise rédigée par l'employeur lui-même (entreprise.description),
    jamais affichée jusqu'ici dans l'app alors qu'elle est déjà présente dans
    les données qu'on récupère. Renvoie un dict (potentiellement partiel si
    l'information manque) ou None si aucune offre de cette entreprise trouvée.
    """
    for offre in offres_disponibles:
        if _nom_entreprise_normalise(offre).strip().lower() != nom_entreprise.strip().lower():
            continue
        description = (offre.get("entreprise", {}) or {}).get("description")
        secteur_libelle = offre.get("secteurActiviteLibelle")
        if description or secteur_libelle:
            return {"description": description, "secteur_libelle": secteur_libelle}
    return None


def _agreger_offres_par_ville_et_entreprise(toutes_offres, departement):
    """
    Agrège une liste d'offres déjà récupérées par ville et par entreprise —
    logique extraite de offres_par_ville() pour être réutilisable sur une liste
    d'offres obtenue autrement (ex: fusion code ROME + mots-clés dans
    rechercher_offres_completes_elargi()), sans refaire un appel API dédié.
    Retourne (df_villes, df_entreprises, nb_offres_approximatives, dates_creation).
    """
    lieux = {}
    entreprises = {}  # cle_normalisee -> {"nom_affiche":..., "nombre_offres":..., "villes": set()}
    dates_creation = []
    for offre in toutes_offres:
        lieu_travail = offre.get("lieuTravail", {})
        ville = lieu_travail.get("libelle", "Non renseigné")
        lat_brute = lieu_travail.get("latitude")
        lon_brute = lieu_travail.get("longitude")
        if ville not in lieux:
            if lat_brute is not None and lon_brute is not None:
                lieux[ville] = {
                    "nombre_offres": 0, "latitude": lat_brute, "longitude": lon_brute, "approximatif": False,
                }
            elif (chef_lieu := DEPARTEMENTS_CHEF_LIEU.get(
                str(_deviner_departement_offre(ville, departement) or "").strip().upper()
            )):
                _, lat_repli, lon_repli = chef_lieu
                lieux[ville] = {
                    "nombre_offres": 0, "latitude": lat_repli, "longitude": lon_repli, "approximatif": True,
                }
            else:
                lieux[ville] = {"nombre_offres": 0, "latitude": None, "longitude": None, "approximatif": True}
        elif lieux[ville]["approximatif"] and lat_brute is not None:
            lieux[ville]["latitude"] = lat_brute
            lieux[ville]["longitude"] = lon_brute
            lieux[ville]["approximatif"] = False
        lieux[ville]["nombre_offres"] += 1

        nom_entreprise = _nom_entreprise_normalise(offre)
        cle_entreprise = nom_entreprise.strip().lower()
        nom_ville = ville.split(" - ", 1)[-1].strip() if " - " in ville else ville
        if cle_entreprise not in entreprises:
            entreprises[cle_entreprise] = {"nom_affiche": nom_entreprise.strip(), "nombre_offres": 0, "villes": set()}
        entreprises[cle_entreprise]["nombre_offres"] += 1
        entreprises[cle_entreprise]["villes"].add(nom_ville)

        date_creation = offre.get("dateCreation")
        if date_creation:
            dates_creation.append(date_creation)

    df = pd.DataFrame([{"ville": v, **infos} for v, infos in lieux.items()])
    if not df.empty:
        df = df.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    df_entreprises = pd.DataFrame(
        [
            {
                "entreprise": infos["nom_affiche"],
                "nombre_offres": infos["nombre_offres"],
                "villes": ", ".join(sorted(infos["villes"])),
            }
            for nom, infos in entreprises.items()
        ]
    )
    if not df_entreprises.empty:
        df_entreprises = df_entreprises.sort_values("nombre_offres", ascending=False).reset_index(drop=True)

    nb_offres_approximatives = int(df.loc[df["approximatif"], "nombre_offres"].sum()) if not df.empty else 0

    return df, df_entreprises, nb_offres_approximatives, dates_creation


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
        params = {"range": f"{debut}-{fin}"}
        if departement:
            params["departement"] = departement
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

    toutes_offres = filtrer_offres_par_secteurs(toutes_offres, secteur_activite)

    df, df_entreprises, nb_offres_approximatives, dates_creation = _agreger_offres_par_ville_et_entreprise(
        toutes_offres, departement
    )
    date_min_pub = min(dates_creation) if dates_creation else None
    date_max_pub = max(dates_creation) if dates_creation else None
    return df, len(toutes_offres), date_min_pub, date_max_pub, df_entreprises, nb_offres_approximatives


def rechercher_offres_completes_elargi(codes_rome, mots_cles_libres, departement, max_pages=3, jours_max=None):
    """
    Récupère les offres en combinant DEUX stratégies, fusionnées et dédupliquées :
    la correspondance exacte par code(s) ROME résolu(s), ET une recherche libre
    par mots-clés sur l'intitulé tel que tapé par l'utilisateur (motsCles, mode
    "TOUS").

    Nécessaire car une offre peut être classée par France Travail sous un code
    ROME légèrement différent de celui résolu par notre suggestion — une
    recherche par code(s) seul(s) peut donc sous-compter fortement par rapport à
    ce qu'un candidat trouve en tapant le même intitulé directement sur
    francetravail.fr (constaté en pratique : 12 offres via codes ROME contre 53
    en recherche libre pour "Chef de projet informatique" dans le 13, un même
    mois). La recherche libre comble cet écart sans perdre la précision des
    codes ROME résolus (les deux résultats sont fusionnés, pas remplacés).
    """
    codes_valides = [c for c in codes_rome if c] if codes_rome else []
    offres_par_code = []
    for code in codes_valides:
        offres_par_code.extend(
            rechercher_offres_completes(code, departement, max_pages=max_pages, jours_max=jours_max)
        )
    offres_mots_cles = []
    if mots_cles_libres and mots_cles_libres.strip():
        offres_mots_cles = rechercher_offres_completes(
            "TOUS", departement, max_pages=max_pages, mots_cles=mots_cles_libres.strip(), jours_max=jours_max
        )
    return fusionner_offres(offres_par_code, offres_mots_cles)


def offres_par_ville_elargi(codes_rome, mots_cles_libres, departement, jours_max=None, max_pages=3):
    """Version "élargie" (code(s) ROME + mots-clés fusionnés) de offres_par_ville(),
    pour un ou plusieurs postes indifféremment — remplace offres_par_ville/_multi
    dans "Tendance par profil" pour ne plus sous-compter par rapport à une
    recherche libre équivalente sur France Travail. Même forme de retour que
    offres_par_ville()."""
    toutes_offres = rechercher_offres_completes_elargi(
        codes_rome, mots_cles_libres, departement, max_pages=max_pages, jours_max=jours_max
    )
    df, df_entreprises, nb_offres_approximatives, dates_creation = _agreger_offres_par_ville_et_entreprise(
        toutes_offres, departement
    )
    date_min_pub = min(dates_creation) if dates_creation else None
    date_max_pub = max(dates_creation) if dates_creation else None
    return df, len(toutes_offres), date_min_pub, date_max_pub, df_entreprises, nb_offres_approximatives




@st.cache_data(ttl=1800)
def volumes_departement_offres(code_rome, departement, mots_cles=None, secteur_activite=None, jours_max=None):
    """
    Total offres pour un code ROME (ou tous, via mots-clés) sur un département.

    Si secteur_activite est une LISTE (multi-secteur), l'API ne permet pas de filtrer
    côté serveur (un seul secteurActivite par requête) : impossible d'utiliser le
    simple total Content-Range dans ce cas, il refléterait TOUS les secteurs. On
    récupère alors les offres (paginé) et on compte après filtrage post-fetch, comme
    le fait déjà offres_par_ville() — plus coûteux mais seul moyen d'avoir un total
    cohérent avec le reste de l'app en multi-secteur.
    """
    if isinstance(secteur_activite, list) and secteur_activite:
        offres = rechercher_offres_completes(
            code_rome, departement, max_pages=5, mots_cles=mots_cles,
            secteur_activite=secteur_activite, jours_max=jours_max,
        )
        return len(offres)

    token = get_token(SCOPE_OFFRES)
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"range": "0-0"}
    if departement:
        params["departement"] = departement
    params.update(_params_filtre_poste(code_rome, mots_cles, secteur_activite))
    if jours_max:
        date_min = datetime.now(timezone.utc) - timedelta(days=jours_max)
        params["minCreationDate"] = date_min.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    NB multi-secteur : ce compteur s'appuie uniquement sur Content-Range (pas de
    liste d'offres brutes à filtrer après coup), donc contrairement aux autres
    fonctions de ce module, une LISTE de codes secteur n'est pas filtrable ici —
    _params_filtre_poste l'ignore silencieusement (retombe sur "tous secteurs"
    pour ce graphique précis) plutôt que de fausser le compte.
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
            "range": "0-0",
            "minCreationDate": debut_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxCreationDate": fin_mois.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if departement:
            params["departement"] = departement
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
def _agreger_contrats_et_salaires(toutes_offres):
    """
    Agrège une liste d'offres déjà récupérées en répartition par type de
    contrat, par niveau d'expérience, et par salaire — logique réutilisable sur
    une liste d'offres obtenue autrement (ex: fusion code ROME + mots-clés dans
    repartition_contrats_et_salaires_elargi()).
    """
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
                    "Entreprise": _nom_entreprise_normalise(offre),
                    "Type de contrat": type_contrat,
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
        params = {"range": f"{debut}-{fin}"}
        if departement:
            params["departement"] = departement
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

    toutes_offres = filtrer_offres_par_secteurs(toutes_offres, secteur_activite)
    return _agreger_contrats_et_salaires(toutes_offres)


def repartition_contrats_et_salaires_elargi(codes_rome, mots_cles_libres, departement, jours_max=None, max_pages=3):
    """
    Version "élargie" (code(s) ROME + mots-clés fusionnés, cf.
    rechercher_offres_completes_elargi) de repartition_contrats_et_salaires() —
    remplace la version mono/multi-poste dans KPIs avancés pour rester cohérente
    avec les totaux de "Tendance par profil", qui utilisent déjà cette même
    fusion depuis la correction du sous-comptage par code ROME exact seul.
    """
    toutes_offres = rechercher_offres_completes_elargi(
        codes_rome, mots_cles_libres, departement, max_pages=max_pages, jours_max=jours_max
    )
    return _agreger_contrats_et_salaires(toutes_offres)


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


def conseils_tension(tension):
    """
    Conseils actionnables selon le palier de tension (même paliers que
    interpreter_tension). Chaque conseil pointe vers quelque chose de concret
    dans l'app plutôt qu'un principe général. Retourne une liste vide si
    tension est None.
    """
    if tension is None:
        return []
    if tension >= 1.5:
        return [
            "Le marché est en tension pour les recruteurs : les process sont souvent plus "
            "rapides. Mène 2 à 3 candidatures en parallèle plutôt qu'une seule à la fois.",
            "Position de force pour négocier salaire, télétravail, date de démarrage — ne te "
            "sous-vends pas sur la première offre.",
            "Regarde en priorité les offres sans salaire affiché : sur un marché tendu pour "
            "l'employeur, c'est souvent négociable à la hausse.",
        ]
    if tension >= 1.0:
        return [
            "Cible reste précise, pas besoin d'élargir — mais vérifie la fraîcheur des offres "
            "(« Publiées depuis ») pour prioriser les plus récentes, les plus anciennes ont "
            "souvent déjà un candidat en cours de process.",
            "Repère les entreprises qui publient plusieurs offres dans le tableau « Top "
            "recruteurs » : signe d'un recrutement actif, bon candidat pour une candidature "
            "spontanée sur un poste proche non publié.",
        ]
    if tension >= 0.5:
        return [
            "Vérifie que ton % de correspondance (onglet Offres d'emploi) dépasse 60-70% avant "
            "de candidater, sinon ajuste tes mots-clés sectoriels dans « Créer mon CV ».",
            "Élargis d'un cran plutôt que de dix : ajoute 1 à 2 intitulés proches via les "
            "suggestions du sélecteur de poste plutôt que de basculer directement sur « Tous "
            "les postes ».",
        ]
    return [
        "Priorité candidature spontanée : cible directement les entreprises du tableau « Top "
        "recruteurs », même sans offre publiée en ce moment.",
        "Élargis la zone géographique : essaie un département limitrophe et compare sa "
        "tension.",
        "Élargis l'intitulé de poste : ajoute 2 à 3 intitulés proches via les suggestions du "
        "sélecteur de poste.",
    ]


def estimer_duree_recherche(tension):
    """
    Estimation INDICATIVE (maison, non officielle) d'une durée de recherche
    d'emploi côté candidat, à partir de l'indice de tension local. Il n'existe
    pas d'étude publiée (Dares, Apec, cabinets de conseil) reliant précisément
    un indice de tension à une durée de recherche candidat — ce n'est donc pas
    une statistique officielle, juste une mise à l'échelle des 4 mêmes paliers
    que interpreter_tension(), calée sur le seul repère chiffré et sourcé
    trouvé : la durée moyenne de RECRUTEMENT (côté entreprise, pas candidat)
    observée par l'Apec pour les cadres, environ 9 à 11 semaines
    (source : Apec, "Pratiques de recrutement des cadres",
    https://corporate.apec.fr/home/espace-medias/pratiques-de-recrutements-des-cadres-en-2022.html).
    Cette durée d'entreprise sert d'ancrage pour le palier "équilibré", les
    autres paliers sont des fourchettes plus rapides/plus longues par
    extrapolation, pas des données mesurées.

    Retourne (fourchette_texte, note_source) ou (None, None) si tension est None.
    """
    if tension is None:
        return None, None

    note_source = (
        "Estimation indicative, non officielle — aucune étude publiée ne relie précisément "
        "un indice de tension à une durée de recherche candidat. Calée sur le seul repère "
        "chiffré et sourcé disponible : la durée moyenne de RECRUTEMENT (côté entreprise) "
        "observée par l'Apec pour les cadres, environ 9 à 11 semaines (Apec, « Pratiques de "
        "recrutement des cadres »)."
    )

    if tension >= 1.5:
        return "environ 4 à 6 semaines", note_source
    if tension >= 1.0:
        return "environ 6 à 9 semaines", note_source
    if tension >= 0.5:
        return "environ 9 à 14 semaines", note_source
    return "environ 14 à 26 semaines (3 à 6 mois)", note_source




__all__ = [
    "CLIENT_ID",
    "CLIENT_SECRET",
    "SCOPE_OFFRES",
    "get_token",
    "_params_filtre_poste",
    "filtrer_offres_par_secteurs",
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
    "ROMEO_SCOPE",
    "predire_rome_romeo",
    "suggerer_postes",
    "chercher_offres",
    "resoudre_codes_rome",
    "secteurs_pour_poste",
    "rechercher_offres_completes",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "ADZUNA_BASE_URL",
    "DEPARTEMENTS_VERS_NOM",
    "DEPARTEMENTS_CHEF_LIEU",
    "departements_vers_param",
    "departement_est_multiple",
    "_deviner_departement_offre",
    "adzuna_configure",
    "departement_vers_lieu_adzuna",
    "rechercher_offres_adzuna",
    "_adapter_offre_adzuna",
    "_deduire_type_contrat",
    "fusionner_offres",
    "volumes_departement_offres_multi",
    "rechercher_offres_completes_multi",
    "chercher_offres_multi",
    "rechercher_offres_toutes_sources",
    "offres_par_ville_multi",
    "evolution_offres_annuelle_multi",
    "repartition_contrats_et_salaires_multi",
    "LABEL_ENTREPRISE_ANONYME",
    "_nom_entreprise_normalise",
    "RECHERCHE_ENTREPRISES_URL",
    "TRANCHE_EFFECTIF_LABELS",
    "rechercher_entreprise_siren",
    "_referentiel_naf_vers_libelle",
    "naf_vers_libelle",
    "rechercher_offres_entreprise",
    "WIKIPEDIA_HEADERS",
    "rechercher_wikipedia_entreprise",
    "rechercher_wikidata_entreprise",
    "infos_entretien_entreprise",
    "offres_par_ville",
    "_agreger_offres_par_ville_et_entreprise",
    "rechercher_offres_completes_elargi",
    "offres_par_ville_elargi",
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
    "_agreger_contrats_et_salaires",
    "repartition_contrats_et_salaires",
    "repartition_contrats_et_salaires_elargi",
    "calculer_tension",
    "interpreter_tension",
    "conseils_tension",
    "estimer_duree_recherche",
]
