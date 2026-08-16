"""
cv_builder.py
--------------
Formulaire de création de CV pour l'application "Aide Conseil Emploi".
Mise en page à deux colonnes (bandeau latéral coloré + colonne principale),
avec 3 thèmes de couleur au choix. Pas de photo (décision produit actuelle).

Intégration dans app.py :
    from cv_builder import afficher_generateur_cv
    ...
    with tab_cv:
        afficher_generateur_cv()
"""

import streamlit as st
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from io import BytesIO


# ---------------------------------------------------------------------------
# Thèmes de couleur
# ---------------------------------------------------------------------------
THEMES = {
    "🔵 Bleu classique": {
        "accent": "1F4E79",       # titres, nom, filets
        "bandeau_fond": "EAF1F8",  # fond du bandeau latéral
        "bandeau_texte": "1F4E79",
    },
    "🍷 Bordeaux élégant": {
        "accent": "7B2C3B",
        "bandeau_fond": "F6ECEE",
        "bandeau_texte": "7B2C3B",
    },
    "🟢 Vert forêt": {
        "accent": "2F5233",
        "bandeau_fond": "EAF2EA",
        "bandeau_texte": "2F5233",
    },
}


# ---------------------------------------------------------------------------
# Drapeaux (facultatif, best-effort — langues reconnues seulement)
# ---------------------------------------------------------------------------
DRAPEAUX_LANGUES = {
    "français": "🇫🇷", "anglais": "🇬🇧", "espagnol": "🇪🇸", "allemand": "🇩🇪",
    "italien": "🇮🇹", "portugais": "🇵🇹", "arabe": "🇸🇦", "chinois": "🇨🇳",
    "mandarin": "🇨🇳", "japonais": "🇯🇵", "russe": "🇷🇺", "néerlandais": "🇳🇱",
    "coréen": "🇰🇷", "turc": "🇹🇷", "polonais": "🇵🇱", "grec": "🇬🇷",
    "hébreu": "🇮🇱", "hindi": "🇮🇳", "suédois": "🇸🇪", "norvégien": "🇳🇴",
    "danois": "🇩🇰", "finnois": "🇫🇮", "roumain": "🇷🇴", "ukrainien": "🇺🇦",
}


def _drapeau_pour_langue(texte_ligne):
    """Retourne un drapeau si le nom de la langue est reconnu, sinon chaîne vide."""
    debut = texte_ligne.strip().lower()
    for nom, drapeau in DRAPEAUX_LANGUES.items():
        if debut.startswith(nom):
            return drapeau + " "
    return ""


# ---------------------------------------------------------------------------
# Échelle automatique (police / espacement) pour tenir sur une page
# ---------------------------------------------------------------------------
def _estimer_volume_contenu(data):
    volume = len(data.get("profil", ""))
    for exp in data.get("experiences", []):
        volume += len(exp.get("description", "")) + 60
    for form in data.get("formations", []):
        volume += 40
    volume += len(data.get("langues", ""))
    volume += len(data.get("competences", ""))
    volume += len(data.get("outils", ""))
    volume += len(data.get("langages_informatiques", ""))
    volume += len(data.get("interets", ""))
    return volume


def _calculer_echelle(volume):
    """Plus le contenu est volumineux, plus on réduit polices/espacements."""
    if volume < 1400:
        return 1.0
    elif volume < 2200:
        return 0.92
    elif volume < 3000:
        return 0.85
    elif volume < 3800:
        return 0.78
    elif volume < 4600:
        return 0.71
    elif volume < 5500:
        return 0.65
    elif volume < 6500:
        return 0.60
    else:
        return 0.55


def _calculer_marge_verticale(echelle):
    """Réduit aussi les marges haut/bas de page pour les contenus très volumineux."""
    if echelle >= 0.85:
        return 1.2
    elif echelle >= 0.65:
        return 0.9
    else:
        return 0.6


def _pt(base, echelle):
    return Pt(round(base * echelle * 2) / 2)


# ---------------------------------------------------------------------------
# Initialisation de l'état
# ---------------------------------------------------------------------------
def _init_cv_state():
    if "cv_experiences" not in st.session_state:
        st.session_state.cv_experiences = []
    if "cv_formations" not in st.session_state:
        st.session_state.cv_formations = []


# ---------------------------------------------------------------------------
# Sections dynamiques (expériences / formations)
# ---------------------------------------------------------------------------
def _section_experiences():
    st.markdown("#### 💼 Expériences professionnelles")

    a_supprimer = None
    for i, exp in enumerate(st.session_state.cv_experiences):
        with st.container(border=True):
            c1, c2 = st.columns(2)
            exp["poste"] = c1.text_input("Poste", value=exp.get("poste", ""), key=f"exp_poste_{i}")
            exp["entreprise"] = c2.text_input("Entreprise", value=exp.get("entreprise", ""), key=f"exp_entreprise_{i}")

            c3, c4, c5 = st.columns(3)
            exp["ville"] = c3.text_input("Ville", value=exp.get("ville", ""), key=f"exp_ville_{i}")
            exp["date_debut"] = c4.text_input("Début (ex: Jan. 2022)", value=exp.get("date_debut", ""), key=f"exp_debut_{i}")
            exp["date_fin"] = c5.text_input("Fin (ex: Déc. 2023 ou En cours)", value=exp.get("date_fin", ""), key=f"exp_fin_{i}")

            exp["description"] = st.text_area(
                "Missions / réalisations (une ligne = une puce)",
                value=exp.get("description", ""),
                key=f"exp_description_{i}",
                height=100,
            )

            if st.button("🗑️ Supprimer cette expérience", key=f"exp_supprimer_{i}"):
                a_supprimer = i

    if a_supprimer is not None:
        st.session_state.cv_experiences.pop(a_supprimer)
        st.rerun()

    if st.button("➕ Ajouter une expérience"):
        st.session_state.cv_experiences.append({})
        st.rerun()


def _section_formations():
    st.markdown("#### 🎓 Formation")

    a_supprimer = None
    for i, form in enumerate(st.session_state.cv_formations):
        with st.container(border=True):
            c1, c2 = st.columns(2)
            form["diplome"] = c1.text_input("Diplôme", value=form.get("diplome", ""), key=f"form_diplome_{i}")
            form["etablissement"] = c2.text_input("Établissement", value=form.get("etablissement", ""), key=f"form_etab_{i}")

            c3, c4 = st.columns(2)
            form["ville"] = c3.text_input("Ville", value=form.get("ville", ""), key=f"form_ville_{i}")
            form["annee"] = c4.text_input("Année (ex: sept 2017 / oct 2018)", value=form.get("annee", ""), key=f"form_annee_{i}")

            if st.button("🗑️ Supprimer cette formation", key=f"form_supprimer_{i}"):
                a_supprimer = i

    if a_supprimer is not None:
        st.session_state.cv_formations.pop(a_supprimer)
        st.rerun()

    if st.button("➕ Ajouter une formation"):
        st.session_state.cv_formations.append({})
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers python-docx bas niveau (ombrage de cellule, bordures de tableau)
# ---------------------------------------------------------------------------
def _ombrer_cellule(cell, couleur_hex):
    """Applique une couleur de fond à une cellule de tableau (non exposé par l'API haut niveau)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), couleur_hex)
    tc_pr.append(shd)


def _supprimer_bordures_tableau(table):
    """Retire toutes les bordures d'un tableau (utilisé comme grille de mise en page invisible)."""
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for cote in ("top", "left", "bottom", "right", "insideH", "insideV"):
        elem = OxmlElement(f"w:{cote}")
        elem.set(qn("w:val"), "nil")
        borders.append(elem)
    tbl_pr.append(borders)


def _definir_marges_cellule(cell, gauche=0.15, droite=0.15, haut=0.05, bas=0.05):
    """Définit des marges internes (en cm) pour une cellule."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for cote, valeur in (("left", gauche), ("right", droite), ("top", haut), ("bottom", bas)):
        elem = OxmlElement(f"w:{cote}")
        elem.set(qn("w:w"), str(int(valeur * 567)))  # cm -> twips (1cm ≈ 567 twips)
        elem.set(qn("w:type"), "dxa")
        tc_mar.append(elem)
    tc_pr.append(tc_mar)


def _titre_section(cell_ou_doc, texte, couleur_hex, taille=12, echelle=1.0, espace_avant=12):
    """Ajoute un titre de section stylé (majuscules, gras, coloré)."""
    p = cell_ou_doc.add_paragraph()
    p.paragraph_format.space_before = _pt(espace_avant, echelle)
    p.paragraph_format.space_after = _pt(4, echelle)
    run = p.add_run(texte.upper())
    run.bold = True
    run.font.size = _pt(taille, echelle)
    run.font.color.rgb = RGBColor.from_string(couleur_hex)
    return p


_CARACTERES_PUCE_PARASITES = " -•➤▸●○*>·‣"


def _nettoyer_ligne(texte):
    """Retire les puces/symboles que l'utilisateur a pu coller depuis un autre CV
    (➤, ▸, -, •...) pour éviter un double affichage avec notre propre puce."""
    return texte.strip(_CARACTERES_PUCE_PARASITES).strip()


def _puce(cell_ou_doc, texte, couleur_puce=None, taille=10, echelle=1.0):
    p = cell_ou_doc.add_paragraph()
    p.paragraph_format.space_after = _pt(2, echelle)
    run = p.add_run(f"• {texte}")
    run.font.size = _pt(taille, echelle)
    if couleur_puce:
        run.font.color.rgb = RGBColor.from_string(couleur_puce)
    return p


# ---------------------------------------------------------------------------
# Génération du document Word (mise en page 2 colonnes)
# ---------------------------------------------------------------------------
def generer_cv_docx(data, theme_nom="🔵 Bleu classique", photo_bytes=None, afficher_drapeaux=True):
    theme = THEMES.get(theme_nom, THEMES["🔵 Bleu classique"])
    accent = theme["accent"]
    bandeau_fond = theme["bandeau_fond"]
    bandeau_texte = theme["bandeau_texte"]
    echelle = _calculer_echelle(_estimer_volume_contenu(data))
    marge_verticale = _calculer_marge_verticale(echelle)

    doc = Document()
    # Interligne compact par défaut (évite l'espacement 1.08/1.15 par défaut de Word,
    # qui gonfle inutilement la hauteur de chaque ligne de texte).
    style_normal = doc.styles["Normal"]
    style_normal.paragraph_format.line_spacing = 1.0
    style_normal.paragraph_format.space_after = Pt(0)

    for section in doc.sections:
        section.top_margin = Cm(marge_verticale)
        section.bottom_margin = Cm(marge_verticale)
        section.left_margin = Cm(1.2)
        section.right_margin = Cm(1.2)
        largeur_utile = section.page_width - section.left_margin - section.right_margin

    largeur_bandeau = Inches(2.3)
    largeur_principale = largeur_utile - largeur_bandeau

    # --- Tableau de mise en page 1 ligne x 2 colonnes, bordures invisibles ---
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    _supprimer_bordures_tableau(table)
    table.columns[0].width = largeur_bandeau
    table.columns[1].width = largeur_principale

    cell_bandeau = table.cell(0, 0)
    cell_principale = table.cell(0, 1)
    cell_bandeau.width = largeur_bandeau
    cell_principale.width = largeur_principale
    _ombrer_cellule(cell_bandeau, bandeau_fond)
    marge_cellule_haut = 0.15 if echelle < 0.85 else 0.3
    _definir_marges_cellule(cell_bandeau, gauche=0.35, droite=0.25, haut=marge_cellule_haut, bas=0.15)
    _definir_marges_cellule(cell_principale, gauche=0.35, droite=0.1, haut=marge_cellule_haut, bas=0.15)
    cell_bandeau.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    cell_principale.vertical_alignment = WD_ALIGN_VERTICAL.TOP

    # Suppression réelle (pas juste vidage du texte) du paragraphe auto-créé dans
    # chaque cellule — sinon il reste une ligne vide qui pousse tout le contenu
    # vers le bas, y compris le nom en haut de la colonne principale.
    for cellule in (cell_bandeau, cell_principale):
        p_vide = cellule.paragraphs[0]
        p_vide._element.getparent().remove(p_vide._element)

    # =======================================================================
    # BANDEAU LATÉRAL
    # =======================================================================
    # --- Photo (facultative) ---
    if photo_bytes:
        p_photo = cell_bandeau.add_paragraph()
        p_photo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_photo.paragraph_format.space_after = _pt(10, echelle)
        run_photo = p_photo.add_run()
        run_photo.add_picture(BytesIO(photo_bytes), width=Inches(1.6))

    # --- Contact ---
    _titre_section(cell_bandeau, "Contact", bandeau_texte, echelle=echelle, espace_avant=0)
    for label, valeur in [
        ("E-mail", data.get("email")),
        ("Téléphone", data.get("telephone")),
        ("Ville", data.get("ville")),
    ]:
        if valeur:
            p = cell_bandeau.add_paragraph()
            p.paragraph_format.space_after = _pt(2, echelle)
            run_label = p.add_run(f"{label}\n")
            run_label.bold = True
            run_label.font.size = _pt(9, echelle)
            run_label.font.color.rgb = RGBColor.from_string(bandeau_texte)
            run_val = p.add_run(valeur)
            run_val.font.size = _pt(10, echelle)

    # --- Langues ---
    if data.get("langues"):
        _titre_section(cell_bandeau, "Langues", bandeau_texte, echelle=echelle)
        for ligne in data["langues"].split("\n"):
            ligne = _nettoyer_ligne(ligne)
            if ligne:
                prefixe = _drapeau_pour_langue(ligne) if afficher_drapeaux else ""
                _puce(cell_bandeau, f"{prefixe}{ligne}", echelle=echelle)

    # --- Compétences ---
    if data.get("competences"):
        _titre_section(cell_bandeau, "Compétences", bandeau_texte, echelle=echelle)
        for ligne in data["competences"].split("\n"):
            ligne = _nettoyer_ligne(ligne)
            if ligne:
                _puce(cell_bandeau, ligne, echelle=echelle)

    # --- Outils informatiques ---
    if data.get("outils"):
        _titre_section(cell_bandeau, "Outils informatiques", bandeau_texte, echelle=echelle)
        for ligne in data["outils"].split("\n"):
            ligne = _nettoyer_ligne(ligne)
            if ligne:
                _puce(cell_bandeau, ligne, echelle=echelle)

    # --- Langages informatiques (facultatif, invisible si vide — profils non-tech) ---
    if data.get("langages_informatiques"):
        _titre_section(cell_bandeau, "Langages informatiques", bandeau_texte, echelle=echelle)
        for ligne in data["langages_informatiques"].split("\n"):
            ligne = _nettoyer_ligne(ligne)
            if ligne:
                _puce(cell_bandeau, ligne, echelle=echelle)

    # --- Centres d'intérêt ---
    if data.get("interets"):
        _titre_section(cell_bandeau, "Centres d'intérêt", bandeau_texte, echelle=echelle)
        interets_list = [i.strip() for i in data["interets"].replace("\n", ",").split(",") if i.strip()]
        p = cell_bandeau.add_paragraph()
        run = p.add_run(" · ".join(interets_list))
        run.font.size = _pt(10, echelle)

    # =======================================================================
    # COLONNE PRINCIPALE
    # =======================================================================
    # --- En-tête : nom + titre recherché ---
    p_nom = cell_principale.add_paragraph()
    p_nom.paragraph_format.space_after = Pt(0)
    run_nom = p_nom.add_run(f"{data.get('prenom', '')} {data.get('nom', '')}".strip().upper())
    run_nom.bold = True
    run_nom.font.size = _pt(20, echelle)
    run_nom.font.color.rgb = RGBColor.from_string(accent)

    if data.get("titre_recherche"):
        p_titre = cell_principale.add_paragraph()
        p_titre.paragraph_format.space_after = _pt(8, echelle)
        run_titre = p_titre.add_run(data["titre_recherche"])
        run_titre.italic = True
        run_titre.font.size = _pt(13, echelle)
        run_titre.font.color.rgb = RGBColor.from_string(accent)

    # Filet horizontal sous l'en-tête
    p_filet = cell_principale.add_paragraph()
    p_filet.paragraph_format.space_after = _pt(8, echelle)
    pPr = p_filet._p.get_or_add_pPr()
    bord = OxmlElement("w:pBdr")
    bas = OxmlElement("w:bottom")
    bas.set(qn("w:val"), "single")
    bas.set(qn("w:sz"), "12")
    bas.set(qn("w:space"), "1")
    bas.set(qn("w:color"), accent)
    bord.append(bas)
    pPr.append(bord)

    # --- Profil ---
    if data.get("profil"):
        _titre_section(cell_principale, "Profil", accent, taille=13, echelle=echelle)
        p = cell_principale.add_paragraph()
        run = p.add_run(data["profil"])
        run.font.size = _pt(10.5, echelle)

    # --- Expériences ---
    experiences = [e for e in data.get("experiences", []) if e.get("poste") or e.get("entreprise")]
    if experiences:
        _titre_section(cell_principale, "Expériences professionnelles", accent, taille=13, echelle=echelle)
        for exp in experiences:
            p = cell_principale.add_paragraph()
            p.paragraph_format.space_before = _pt(6, echelle)
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(f"{exp.get('poste', '')} — {exp.get('entreprise', '')}")
            run.bold = True
            run.font.size = _pt(11, echelle)

            dates_ville = " · ".join(
                x for x in [
                    f"{exp.get('date_debut', '')} - {exp.get('date_fin', '')}".strip(" -"),
                    exp.get("ville", ""),
                ] if x
            )
            if dates_ville:
                p_meta = cell_principale.add_paragraph()
                p_meta.paragraph_format.space_after = _pt(3, echelle)
                run_meta = p_meta.add_run(dates_ville)
                run_meta.italic = True
                run_meta.font.size = _pt(9.5, echelle)
                run_meta.font.color.rgb = RGBColor.from_string(accent)

            description = exp.get("description", "").strip()
            if description:
                for ligne in description.split("\n"):
                    ligne = _nettoyer_ligne(ligne)
                    if ligne:
                        _puce(cell_principale, ligne, taille=10, echelle=echelle)

    # --- Formation ---
    formations = [f for f in data.get("formations", []) if f.get("diplome") or f.get("etablissement")]
    if formations:
        _titre_section(cell_principale, "Formation", accent, taille=13, echelle=echelle)
        for form in formations:
            p = cell_principale.add_paragraph()
            p.paragraph_format.space_before = _pt(4, echelle)
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(f"{form.get('diplome', '')} — {form.get('etablissement', '')}")
            run.bold = True
            run.font.size = _pt(10.5, echelle)

            meta = " · ".join(x for x in [form.get("ville", ""), form.get("annee", "")] if x)
            if meta:
                p_meta = cell_principale.add_paragraph()
                p_meta.paragraph_format.space_after = _pt(2, echelle)
                run_meta = p_meta.add_run(meta)
                run_meta.italic = True
                run_meta.font.size = _pt(9.5, echelle)
                run_meta.font.color.rgb = RGBColor.from_string(accent)

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer, echelle



# ---------------------------------------------------------------------------
# Suggestions de compétences / outils / langages (basées sur les offres réelles)
# ---------------------------------------------------------------------------
def _ajouter_suggestion(cle_session, valeur):
    """Ajoute une ligne à un textarea (par clé de session_state) si elle n'y est pas déjà."""
    actuel = st.session_state.get(cle_session, "")
    lignes = [l.strip() for l in actuel.split("\n") if l.strip()]
    if valeur not in lignes:
        lignes.append(valeur)
        st.session_state[cle_session] = "\n".join(lignes)


def _ajouter_suggestion(cle_session, valeur):
    """Ajoute une valeur à une liste d'options (session_state) si elle n'y est pas déjà."""
    if cle_session not in st.session_state:
        st.session_state[cle_session] = []
    if valeur not in st.session_state[cle_session]:
        st.session_state[cle_session].append(valeur)


# Listes de base toujours proposées, même sans recherche de profil préalable
# (pour que le champ ne soit jamais "vide" par défaut).
_DEFAUTS_COMPETENCES = [
    "Gestion de projet", "Communication", "Travail d'équipe", "Résolution de problèmes",
    "Organisation", "Leadership", "Analyse", "Négociation", "Gestion du temps", "Esprit critique",
]
_DEFAUTS_OUTILS = ["Excel", "Word", "PowerPoint", "Outlook", "Teams"]
_DEFAUTS_LANGAGES = []  # vide par défaut : pertinent seulement pour les profils tech


def _champ_liste_avec_ajout(titre, cle_base, valeurs_par_defaut, aide=None):
    """
    Affiche une liste à choix multiples (options par défaut + suggestions éventuelles)
    avec possibilité d'ajouter ses propres éléments à la liste. Retourne le résultat
    au format 'une valeur par ligne' (compatible avec generer_cv_docx).
    """
    cle_options = f"{cle_base}_options"
    if cle_options not in st.session_state:
        st.session_state[cle_options] = list(valeurs_par_defaut)

    cle_select = f"{cle_base}_select"
    selection = st.multiselect(titre, options=st.session_state[cle_options], key=cle_select, help=aide)

    col_ajout, col_bouton = st.columns([4, 1])
    nouvel_element = col_ajout.text_input(
        f"Ajouter un élément à « {titre} »",
        key=f"{cle_base}_nouveau",
        label_visibility="collapsed",
        placeholder="Ajouter un élément non listé...",
    )
    if col_bouton.button("➕ Ajouter", key=f"{cle_base}_bouton_ajout"):
        valeur = nouvel_element.strip()
        if valeur:
            _ajouter_suggestion(cle_options, valeur)
            if valeur not in st.session_state[cle_select]:
                st.session_state[cle_select] = st.session_state[cle_select] + [valeur]
            st.rerun()

    return "\n".join(selection)


def _section_suggestions_competences(fonction_analyse_competences):
    """
    Récupère (sur clic) les compétences/outils/langages les plus demandés pour le
    poste sélectionné dans "Tendance par profil", et enrichit les listes d'options
    correspondantes. Affiche aussi un aperçu des % les plus demandés à titre indicatif.
    """
    if not fonction_analyse_competences:
        return
    if "code_rome_choisi" not in st.session_state:
        st.info(
            "👉 Lance d'abord une recherche dans l'onglet **🎯 Tendance par profil** pour "
            "enrichir ces listes avec les compétences réellement demandées sur ce métier "
            "(sinon, une liste générique de base reste disponible ci-dessous)."
        )
        return

    if st.button("🔍 Enrichir les listes avec les offres de ce poste", key="btn_suggestions_competences"):
        with st.spinner("Analyse des offres en cours..."):
            df_comp, df_outils, df_langages, nb_total = fonction_analyse_competences(
                st.session_state["code_rome_choisi"],
                st.session_state.get("departement_profil_actif"),
                mots_cles=st.session_state.get("mots_cles_profil_actif"),
                secteur_activite=st.session_state.get("secteur_profil_actif"),
            )
        for cle_options, df in [
            ("cv_competences_options", df_comp),
            ("cv_outils_options", df_outils),
            ("cv_langages_options", df_langages),
        ]:
            if cle_options not in st.session_state:
                st.session_state[cle_options] = []
            for lib in df["libelle"]:
                if lib not in st.session_state[cle_options]:
                    st.session_state[cle_options].append(lib)
        st.session_state["cv_suggestions_apercu"] = (df_comp, df_outils, df_langages, nb_total)
        st.rerun()

    if "cv_suggestions_apercu" in st.session_state:
        df_comp, df_outils, df_langages, nb_total = st.session_state["cv_suggestions_apercu"]
        if nb_total < 10:
            st.caption(f"⚠️ Échantillon réduit ({nb_total} offre(s)) — indicatif seulement.")
        else:
            st.caption(f"Listes enrichies à partir de {nb_total} offre(s) trouvée(s) pour ce poste.")
        for titre_apercu, df in [
            ("Compétences les + demandées", df_comp),
            ("Outils les + demandés", df_outils),
            ("Langages les + demandés", df_langages),
        ]:
            if not df.empty:
                apercu = ", ".join(f"{r.libelle} ({r.pourcentage}%)" for _, r in df.head(6).iterrows())
                st.caption(f"💡 **{titre_apercu}** : {apercu}")


# ---------------------------------------------------------------------------
# Interface Streamlit
# ---------------------------------------------------------------------------
def afficher_generateur_cv(fonction_analyse_competences=None):
    _init_cv_state()

    st.header("🧾 Créez votre CV")
    st.write("Créez votre CV professionnel, prêt à l'emploi, au format Word — en une seule page.")
    st.markdown(
        "**Comment ça marche ici :** renseignez vos informations ci-dessous (coordonnées, "
        "expériences, formations, compétences...), choisissez un thème de couleur, puis générez "
        "votre CV en un clic."
    )
    st.markdown(
        "**Le parcours complet de l'application :**\n"
        "1. 🧾 **Créer mon CV** *(vous êtes ici)* — construisez votre CV et définissez le poste "
        "que vous visez.\n"
        "2. 🎯 **Tendance par profil** — analysez le marché pour ce poste : offres disponibles, "
        "secteurs qui recrutent, tension du marché.\n"
        "3. 📋 **Offres d'emploi** — consultez les annonces réelles, avec un score de "
        "correspondance calculé à partir de votre profil.\n"
        "4. 🧩 **KPIs avancés** — pour aller plus loin : évolution du marché, salaires, types "
        "de contrat."
    )
    st.caption(
        "ℹ️ Renseignez vos compétences, outils et mots-clés sectoriels ci-dessous : ils "
        "permettent de calculer le score de correspondance affiché pour chaque offre dans "
        "l'onglet **📋 Offres d'emploi**."
    )

    theme_choisi = st.radio(
        "🎨 Thème de couleur",
        list(THEMES.keys()),
        horizontal=True,
        key="cv_theme",
    )

    photo_uploadee = st.file_uploader(
        "📷 Photo (facultatif, format carré recommandé)", type=["png", "jpg", "jpeg"], key="cv_photo"
    )
    if photo_uploadee:
        col_apercu, _ = st.columns([1, 4])
        col_apercu.image(photo_uploadee, width=100)

    afficher_drapeaux = st.checkbox("🏳️ Afficher un drapeau à côté des langues reconnues", value=True, key="cv_drapeaux")

    st.markdown("#### 👤 Informations générales")
    c1, c2 = st.columns(2)
    prenom = c1.text_input("Prénom", key="cv_prenom")
    nom = c2.text_input("Nom", key="cv_nom")

    titre_recherche = st.text_input(
        "Titre du poste recherché (ex: PMO Finance)",
        key="cv_titre",
        help="C'est ce titre qui apparaîtra sur ton CV, sous ton nom — peut être personnalisé librement.",
    )
    st.caption(
        "💡 Pour analyser les tendances du marché sur ce métier, direction l'onglet "
        "**🎯 Tendance par profil** — son sélecteur de poste s'appuie directement sur la "
        "nomenclature officielle France Travail."
    )

    mots_cles_secteur = st.text_input(
        "🎯 Mots-clés sectoriels / métier (pour le % de correspondance des offres)",
        key="cv_mots_cles_secteur",
        placeholder="ex: finance, reporting, contrôle de gestion",
        help=(
            "N'apparaît jamais sur ton CV — utilisé uniquement pour calculer le % de "
            "correspondance affiché sous chaque offre dans l'onglet 'Offres d'emploi'. "
            "Sépare plusieurs mots-clés par une virgule."
        ),
    )
    st.caption(
        "💡 Facultatif pour générer le CV, mais nécessaire (avec les compétences ci-dessous) "
        "pour activer le score de correspondance sur les offres."
    )

    c3, c4, c5 = st.columns(3)
    email = c3.text_input("Email", key="cv_email")
    telephone = c4.text_input("Téléphone", key="cv_telephone")
    ville = c5.text_input("Ville", key="cv_ville")

    profil = st.text_area(
        "Profil / accroche (2-3 phrases qui résument votre parcours et votre projet)",
        key="cv_profil",
        height=100,
    )

    st.divider()
    _section_experiences()

    st.divider()
    _section_formations()

    st.divider()
    st.markdown("#### 🌍 Langues")
    langues = st.text_area(
        "Une langue par ligne (ex: Anglais - Courant)",
        key="cv_langues",
        height=80,
    )

    st.divider()
    st.markdown("#### 💡 Compétences, outils & langages")
    _section_suggestions_competences(fonction_analyse_competences)

    st.markdown("###### 🧠 Compétences")
    competences = _champ_liste_avec_ajout(
        "Sélectionne ou ajoute tes compétences", "cv_competences", _DEFAUTS_COMPETENCES
    )

    st.markdown("###### 🛠️ Outils informatiques")
    outils = _champ_liste_avec_ajout(
        "Sélectionne ou ajoute tes outils", "cv_outils", _DEFAUTS_OUTILS
    )

    st.markdown("###### 💻 Langages informatiques")
    st.caption("Facultatif — pertinent surtout pour les profils tech/data.")
    langages_informatiques = _champ_liste_avec_ajout(
        "Sélectionne ou ajoute tes langages", "cv_langages", _DEFAUTS_LANGAGES
    )

    st.markdown("#### 🎯 Centres d'intérêt")
    interets = st.text_area(
        "Séparés par une virgule ou une ligne (ex: Kayak, Dessin, Voyages)",
        key="cv_interets",
        height=60,
    )

    st.divider()

    if st.button("📄 Générer mon CV", type="primary"):
        if not nom or not prenom:
            st.error("Merci de renseigner au minimum votre nom et prénom.")
        else:
            data = {
                "nom": nom,
                "prenom": prenom,
                "titre_recherche": titre_recherche,
                "email": email,
                "telephone": telephone,
                "ville": ville,
                "profil": profil,
                "experiences": st.session_state.cv_experiences,
                "formations": st.session_state.cv_formations,
                "langues": langues,
                "competences": competences,
                "langages_informatiques": langages_informatiques,
                "outils": outils,
                "interets": interets,
            }
            photo_bytes = photo_uploadee.getvalue() if photo_uploadee else None
            buffer, echelle = generer_cv_docx(
                data, theme_nom=theme_choisi, photo_bytes=photo_bytes, afficher_drapeaux=afficher_drapeaux
            )
            st.success("Votre CV est prêt !")
            if echelle < 0.85:
                st.warning(
                    "⚠️ Contenu assez volumineux : la police et les espacements ont été "
                    "automatiquement réduits pour essayer de tenir sur une page. Si le rendu "
                    "final dépasse quand même une page, pense à raccourcir certaines descriptions "
                    "d'expérience."
                )
            st.download_button(
                label="⬇️ Télécharger mon CV (.docx)",
                data=buffer,
                file_name=f"CV_{prenom}_{nom}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
