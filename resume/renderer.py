"""
resume/renderer.py
Deterministic Python-based LaTeX resume generator.
Uses master_resume.tex as formatting baseline and populates it with tailored, verified data.
All user and dynamic text is escaped with latex_escape.
"""
from typing import Dict, Any, List
from resume.latex_escape import escape, escape_url
from agent.safety import assert_not_blacklisted


class LaTeXResumeRenderer:
    """
    Renders structured resume data into an ATS-friendly, compile-ready LaTeX document.
    """

    @classmethod
    def render(cls, profile: Dict[str, Any], tailored_plan: Dict[str, Any]) -> str:
        """
        Renders complete LaTeX document from candidate profile and tailored plan.
        """
        identity = profile.get("identity", {})
        education = (profile.get("education", []) or [{}])[0]
        links = profile.get("links", {})
        skills = tailored_plan.get("skills", {})
        projects = tailored_plan.get("selected_projects", [])
        certifications = tailored_plan.get("certifications", [])

        # 1. Header Information
        name = escape(identity.get("name", "Swopnab Bikram Karki"))
        phone = escape(identity.get("phone", "+1 986-600-8163"))
        email = identity.get("email", "swopnabbikram@gmail.com")
        linkedin = links.get("linkedin", "https://linkedin.com/in/swopnabbkarki")
        github = links.get("github", "https://github.com/Swopnab")

        # Clean display links
        linkedin_disp = escape(linkedin.replace("https://", "").replace("http://", ""))
        github_disp = escape(github.replace("https://", "").replace("http://", ""))

        # 2. Education Information
        institution = escape(education.get("institution", "University of Texas at Arlington"))
        degree = escape(education.get("degree", "B.S. in Computer Science"))
        location = escape(education.get("location", "Arlington, TX"))
        graduation = escape(education.get("graduation", "Fall 2027"))

        # 3. Technical Skills
        def fmt_skill_line(category_label: str, skill_list: List[str]) -> str:
            if not skill_list:
                return ""
            escaped_skills = ", ".join(escape(s) for s in skill_list)
            return f"\\textbf{{{escape(category_label)}:}} {escaped_skills} \\\\"

        skills_lines = []
        if skills.get("languages"):
            skills_lines.append(fmt_skill_line("Languages", skills["languages"]))
        if skills.get("web_and_backend"):
            skills_lines.append(fmt_skill_line("Web & Backend", skills["web_and_backend"]))
        if skills.get("ai_ml"):
            skills_lines.append(fmt_skill_line("AI / Machine Learning", skills["ai_ml"]))
        if skills.get("cloud_databases"):
            skills_lines.append(fmt_skill_line("Cloud & Databases", skills["cloud_databases"]))
        if skills.get("security"):
            skills_lines.append(fmt_skill_line("Security", skills["security"]))
        if skills.get("tools"):
            # Strip trailing \\ on last line
            line = fmt_skill_line("Tools", skills["tools"])
            if line.endswith(" \\\\"):
                line = line[:-3]
            skills_lines.append(line)

        skills_block = "\n".join(skills_lines)

        # 4. Projects Blocks
        project_blocks = []
        for p in projects:
            p_id = p.get("id", "")
            assert_not_blacklisted(p_id)
            assert_not_blacklisted(p.get("display_name", ""))

            p_name = escape(p.get("display_name", ""))
            p_subtitle = escape(p.get("subtitle", ""))
            p_years = escape(p.get("years", "2025--2026")).replace("-", "--") if "--" not in p.get("years", "") else escape(p.get("years", ""))
            tech_stack = ", ".join(escape(t) for t in p.get("tech_stack", []))

            bullets_latex = []
            for b in p.get("bullets", []):
                bullets_latex.append(f"  \\item {escape(b)}")
            bullets_block = "\n".join(bullets_latex)

            p_latex = f"""% Project: {escape(p_id)}
\\noindent
\\textbf{{{p_name}}} \\hfill {p_years} \\\\
\\textit{{{p_subtitle}}} \\hfill \\textit{{{tech_stack}}}
\\begin{{itemize}}
{bullets_block}
\\end{{itemize}}"""
            project_blocks.append(p_latex)

        projects_section = "\n\n\\vspace{3pt}\n\n".join(project_blocks)

        # 5. Certifications Blocks
        cert_items = []
        for c in certifications:
            cert_items.append(f"  \\item {escape(c)}")
        certs_block = "\n".join(cert_items)

        # Assemble Full Document
        latex_code = f"""\\documentclass[10pt, letterpaper]{{article}}

\\usepackage[
  top=0.45in,
  bottom=0.45in,
  left=0.55in,
  right=0.55in
]{{geometry}}

\\usepackage{{enumitem}}
\\usepackage{{titlesec}}
\\usepackage{{hyperref}}
\\usepackage{{xcolor}}
\\usepackage{{parskip}}
\\usepackage{{microtype}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{lmodern}}

\\hypersetup{{
  colorlinks=true,
  urlcolor=black,
  linkcolor=black,
  pdfborder={{0 0 0}}
}}

% Section formatting
\\titleformat{{\\section}}
  {{\\normalfont\\normalsize\\bfseries\\scshape}}
  {{}}
  {{0em}}
  {{}}
  [\\titlerule]

\\titlespacing*{{\\section}}{{0pt}}{{6pt}}{{3pt}}

% List formatting
\\setlist[itemize]{{
  leftmargin=*,
  noitemsep,
  topsep=1pt,
  parsep=0pt,
  partopsep=0pt,
  label=\\textbullet,
}}

\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{0pt}}

\\pagestyle{{empty}}

\\begin{{document}}

% ============================================================
% HEADER
% ============================================================
\\begin{{center}}
  {{\\LARGE \\textbf{{{name}}}}} \\\\[3pt]
  \\small
  {phone} $|$
  \\href{{mailto:{escape_url(email)}}}{{{escape(email)}}} $|$
  \\href{{{escape_url(linkedin)}}}{{{linkedin_disp}}} $|$
  \\href{{{escape_url(github)}}}{{{github_disp}}}
\\end{{center}}

\\vspace{{-2pt}}

% ============================================================
% EDUCATION
% ============================================================
\\section{{Education}}

\\noindent
\\textbf{{{institution}}} \\hfill {location} \\\\
\\textit{{{degree}}} \\hfill \\textit{{Expected Graduation: {graduation}}}

\\vspace{{2pt}}

% ============================================================
% TECHNICAL SKILLS
% ============================================================
\\section{{Technical Skills}}

\\noindent
{skills_block}

\\vspace{{2pt}}

% ============================================================
% PROJECTS
% ============================================================
\\section{{Projects}}

{projects_section}

\\vspace{{2pt}}

% ============================================================
% CERTIFICATIONS
% ============================================================
\\section{{Certifications}}

\\begin{{itemize}}[leftmargin=*, label={{}}]
{certs_block}
\\end{{itemize}}

\\end{{document}}
"""
        return latex_code
