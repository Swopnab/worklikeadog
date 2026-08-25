"""
resume/ats_checker.py
ATS (Applicant Tracking System) compliance verification and keyword density checker.

Heuristics:
1. Standard section headers presence (Education, Technical Skills, Projects, Certifications)
2. Complete contact info (Name, Phone, Email, LinkedIn, GitHub)
3. No tables, multi-column blocks, or embedded graphics in LaTeX source
4. Standard single-column layout
5. Plain text extractability
6. Relevant technical keyword match ratio
"""
import re
from typing import Dict, Any, List, Optional


class ATSChecker:
    """
    Evaluates LaTeX source and generated text for ATS parseability and keyword alignment.
    """

    REQUIRED_SECTIONS = ["Education", "Technical Skills", "Projects"]
    OPTIONAL_SECTIONS = ["Certifications"]

    @classmethod
    def check_latex_source(cls, latex_source: str, target_keywords: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Runs comprehensive ATS heuristics on LaTeX code.
        """
        issues = []
        warnings = []
        score = 100

        # 1. Check for standard sections
        found_sections = []
        for sec in cls.REQUIRED_SECTIONS:
            # Match \section{Section Name} or \section*{Section Name}
            if re.search(r"\\section\*?\{" + re.escape(sec) + r"\}", latex_source, re.IGNORECASE):
                found_sections.append(sec)
            else:
                issues.append(f"Missing standard ATS section: '{sec}'")
                score -= 15

        for sec in cls.OPTIONAL_SECTIONS:
            if re.search(r"\\section\*?\{" + re.escape(sec) + r"\}", latex_source, re.IGNORECASE):
                found_sections.append(sec)

        # 2. Check for ATS-unfriendly LaTeX elements (tables, tabularx, multicol, figures, graphics)
        unfriendly_patterns = [
            (r"\\begin\{tabular\}", "Standard tabular tables can cause column-merge issues in older ATS parsers."),
            (r"\\begin\{tabularx\}", "Tabularx tables can disrupt linear text extraction in ATS systems."),
            (r"\\begin\{figure\}", "Figures / floating elements are not parseable by ATS."),
            (r"\\includegraphics", "Images / graphics / headshots should never be in an ATS resume."),
            (r"\\begin\{multicols\}", "Multi-column text flows disrupt reading order in many parsers."),
            (r"\\begin\{minipage\}", "Nested minipages can cause line wrapping and parsing fragmentation."),
        ]

        for pat, desc in unfriendly_patterns:
            if re.search(pat, latex_source):
                warnings.append(desc)
                score -= 10

        # 3. Check for standard contact information
        contact_checks = [
            (r"\+?1?\s*\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", "Phone number detected", "Missing phone number"),
            (r"[\w.-]+@[\w.-]+\.\w+", "Email address detected", "Missing email address"),
            (r"linkedin\.com/in/[\w.-]+", "LinkedIn profile detected", "Missing LinkedIn link"),
            (r"github\.com/[\w.-]+", "GitHub profile detected", "Missing GitHub link"),
        ]

        for pat, success_msg, fail_msg in contact_checks:
            if not re.search(pat, latex_source, re.IGNORECASE):
                warnings.append(fail_msg)
                score -= 5

        # 4. Keyword density analysis if target keywords provided
        matched_keywords = []
        missing_keywords = []
        if target_keywords:
            latex_clean = re.sub(r"\\[a-zA-Z]+(\[[^\]]*\])?(\{([^}]*)\})?", r" \3 ", latex_source)
            latex_clean = re.sub(r"[{}\\_&%$#~^]", " ", latex_clean).lower()

            for kw in target_keywords:
                kw_norm = kw.strip().lower()
                if not kw_norm:
                    continue
                if re.search(r"\b" + re.escape(kw_norm) + r"\b", latex_clean):
                    matched_keywords.append(kw)
                else:
                    missing_keywords.append(kw)

        # Clamp score
        final_score = max(0, min(100, score))

        return {
            "ats_score": final_score,
            "is_ats_compliant": len(issues) == 0 and final_score >= 80,
            "found_sections": found_sections,
            "issues": issues,
            "warnings": warnings,
            "matched_keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "formatting_checks": {
                "single_column": not bool(re.search(r"\\begin\{multicols\}", latex_source)),
                "no_images": not bool(re.search(r"\\includegraphics", latex_source)),
                "no_complex_tables": not bool(re.search(r"\\begin\{tabular", latex_source)),
                "standard_fonts": bool(re.search(r"\\usepackage.*(fontenc|lmodern|geometry)", latex_source)),
            }
        }
