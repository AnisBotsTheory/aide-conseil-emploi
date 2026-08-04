"""
cv_builder.py
--------------
Formulaire de création de CV pour l'application "Aide Conseil Emploi".

Intégration dans app.py :
    from cv_builder import afficher_generateur_cv
    ...
    with tab_cv:
        afficher_generateur_cv()
"""

import streamlit as st
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from io import BytesIO


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
            form["annee"] = c4.text_input("Année", value=form.get("annee", ""), key=f"form_annee_{i}")

            if st.button("🗑️ Supprimer cette formation", key=f"form_supprimer_{i}"):
                a_supprimer = i

    if a_supprimer is not None:
        st.session_state.cv_formations.pop(a_supprimer)
        st.rerun()

    if st.button("➕ Ajouter une formation"):
        st.session_state.cv_formations.append({})
        st.rerun()


# ---------------------------------------------------------------------------
# Génération du document Word
# ---------------------------------------------------------------------------
def _ajouter_titre_section(doc, texte):
    p = doc.add_paragraph()
    run = p.add_run(texte.upper())
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = None  # garde la couleur par défaut, modifiable si besoin
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    # ligne de séparation simple sous le titre
    p_border = doc.add_paragraph()
    p_border.paragraph_format.space_after = Pt(2)
    return p


def generer_cv_docx(data):
    doc = Document()

    # Marges resserrées pour un CV compact
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # --- En-tête ---
    p_nom = doc.add_paragraph()
    p_nom.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_nom = p_nom.add_run(f"{data['prenom']} {data['nom']}".strip().upper())
    run_nom.bold = True
    run_nom.font.size = Pt(20)

    if data.get("titre_recherche"):
        p_titre = doc.add_paragraph()
        p_titre.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_titre = p_titre.add_run(data["titre_recherche"])
        run_titre.italic = True
        run_titre.font.size = Pt(13)

    contact_parts = [c for c in [data.get("email"), data.get("telephone"), data.get("ville")] if c]
    if contact_parts:
        p_contact = doc.add_paragraph()
        p_contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_contact = p_contact.add_run(" | ".join(contact_parts))
        run_contact.font.size = Pt(10)

    # --- Profil ---
    if data.get("profil"):
        _ajouter_titre_section(doc, "Profil")
        doc.add_paragraph(data["profil"])

    # --- Expériences ---
    experiences = [e for e in data.get("experiences", []) if e.get("poste") or e.get("entreprise")]
    if experiences:
        _ajouter_titre_section(doc, "Expériences professionnelles")
        for exp in experiences:
            p = doc.add_paragraph()
            ligne1 = p.add_run(f"{exp.get('poste', '')} — {exp.get('entreprise', '')}")
            ligne1.bold = True

            dates_ville = " · ".join(
                x for x in [
                    f"{exp.get('date_debut', '')} - {exp.get('date_fin', '')}".strip(" -"),
                    exp.get("ville", ""),
                ] if x
            )
            if dates_ville:
                p_meta = doc.add_paragraph()
                run_meta = p_meta.add_run(dates_ville)
                run_meta.italic = True
                run_meta.font.size = Pt(10)
                p_meta.paragraph_format.space_after = Pt(2)

            description = exp.get("description", "").strip()
            if description:
                for ligne in description.split("\n"):
                    ligne = ligne.strip(" -•")
                    if ligne:
                        doc.add_paragraph(ligne, style="List Bullet")

    # --- Formation ---
    formations = [f for f in data.get("formations", []) if f.get("diplome") or f.get("etablissement")]
    if formations:
        _ajouter_titre_section(doc, "Formation")
        for form in formations:
            p = doc.add_paragraph()
            ligne1 = p.add_run(f"{form.get('diplome', '')} — {form.get('etablissement', '')}")
            ligne1.bold = True

            meta = " · ".join(x for x in [form.get("ville", ""), form.get("annee", "")] if x)
            if meta:
                p_meta = doc.add_paragraph()
                run_meta = p_meta.add_run(meta)
                run_meta.italic = True
                run_meta.font.size = Pt(10)

    # --- Langues ---
    if data.get("langues"):
        _ajouter_titre_section(doc, "Langues")
        for ligne in data["langues"].split("\n"):
            ligne = ligne.strip()
            if ligne:
                doc.add_paragraph(ligne, style="List Bullet")

    # --- Outils informatiques ---
    if data.get("outils"):
        _ajouter_titre_section(doc, "Outils informatiques")
        for ligne in data["outils"].split("\n"):
            ligne = ligne.strip()
            if ligne:
                doc.add_paragraph(ligne, style="List Bullet")

    # --- Centres d'intérêt ---
    if data.get("interets"):
        _ajouter_titre_section(doc, "Centres d'intérêt")
        interets_list = [i.strip() for i in data["interets"].replace("\n", ",").split(",") if i.strip()]
        doc.add_paragraph(" · ".join(interets_list))

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Interface Streamlit
# ---------------------------------------------------------------------------
def afficher_generateur_cv():
    _init_cv_state()

    st.header("🧾 Créez votre CV")
    st.write("Remplissez les sections ci-dessous, puis générez votre CV au format Word (.docx).")

    st.markdown("#### 👤 Informations générales")
    c1, c2 = st.columns(2)
    prenom = c1.text_input("Prénom", key="cv_prenom")
    nom = c2.text_input("Nom", key="cv_nom")

    titre_recherche = st.text_input("Titre du poste recherché (ex: Chef de projet PMO)", key="cv_titre")

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

    st.markdown("#### 🛠️ Outils informatiques")
    outils = st.text_area(
        "Un outil/une compétence par ligne (ex: Excel - Avancé, Power BI, Python)",
        key="cv_outils",
        height=80,
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
                "outils": outils,
                "interets": interets,
            }
            buffer = generer_cv_docx(data)
            st.success("Votre CV est prêt !")
            st.download_button(
                label="⬇️ Télécharger mon CV (.docx)",
                data=buffer,
                file_name=f"CV_{prenom}_{nom}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
