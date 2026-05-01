"""
Stateless ATS Auditor
=====================
Privacy-first resume scanner. Everything runs in-memory.
No data is stored, logged, or sent to any server or third-party API.
All processing is local Python — PyMuPDF parses the PDF on the server
running this app, in volatile RAM, and is discarded immediately after.

Source code is public — every privacy claim here is verifiable line by line.
"""

import re
import math
import streamlit as st
import fitz  # PyMuPDF

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

MAX_FILE_SIZE_MB   = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MIN_RESUME_WORDS   = 200
MIN_JD_WORDS       = 50

# Hardcoded stop words — zero external dependencies, zero network calls.
STOP_WORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","was","are","were","be","been","being","have","has",
    "had","do","does","did","will","would","could","should","may","might",
    "shall","can","need","dare","ought","used","it","its","this","that",
    "these","those","i","me","my","we","our","you","your","he","his","she",
    "her","they","their","what","which","who","whom","how","when","where",
    "why","all","each","every","both","few","more","most","other","some",
    "such","no","not","only","same","so","than","too","very","just","as",
    "up","out","if","about","into","through","during","before","after",
    "above","below","between","own","then","once","here","there","also",
    "any","etc","per","via","well","new","good","work","use","get","make",
    "like","time","year","way","day","man","woman","great","right","look",
    "come","over","think","go","see","know","take","give","find","tell",
    "ask","seem","feel","try","leave","call","strong","high","back","place",
    "large","big","long","little","old","next","early","young","important",
    "public","private","real","best","free","sure","able","using","used",
    "within","without","across","along","around","been","want","need",
}

SECTION_KEYWORDS = {
    "experience":     ["experience","employment","work history","career","positions","roles","work experience"],
    "education":      ["education","academic","degree","university","college","school","qualification","bachelor","master"],
    "skills":         ["skills","technologies","tools","competencies","expertise","technical","proficiencies","tech stack"],
    "summary":        ["summary","objective","profile","about","overview","introduction","professional summary"],
    "projects":       ["projects","portfolio","work samples","case studies","personal projects","open source"],
    "certifications": ["certifications","certificates","licenses","accreditations","credentials"],
    "achievements":   ["achievements","awards","honors","recognition","accomplishments","highlights"],
}


# ─────────────────────────────────────────────
# SCORING TIERS
# ─────────────────────────────────────────────

def get_score_tier(score: float) -> tuple:
    if score >= 80:  return ("Excellent Match",  "🟢")
    if score >= 65:  return ("Strong Match",      "🟡")
    if score >= 50:  return ("Fair Match",        "🟠")
    if score >= 35:  return ("Weak Match",        "🔴")
    return               ("Poor Match",           "⛔")


# ─────────────────────────────────────────────
# TEXT PROCESSING
# ─────────────────────────────────────────────

def simple_stem(word: str) -> str:
    """
    Lightweight suffix stripping — no libraries, no network.
    Handles the most common English inflections well enough
    for keyword intersection matching.
    """
    for suffix in ["ing","tion","tions","ation","ations","ed","er","ers",
                   "ly","ment","ments","ness","ity","ies","es","s"]:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def tokenize(text: str) -> set:
    """
    Lowercase → strip non-alphanumeric (keep +, #) → split →
    remove stop words → stem → return unique token set.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\+\#]", " ", text)
    cleaned = set()
    for token in text.split():
        token = token.strip(".,;:!?\"'()")
        if token and token not in STOP_WORDS and len(token) > 2:
            cleaned.add(simple_stem(token))
    return cleaned


def extract_pdf_text(file_bytes: bytes) -> tuple:
    """
    Parse PDF entirely in-memory using PyMuPDF (fitz).
    file_bytes never leave this function — no disk write, no network call.
    Returns (text: str, warnings: list[str]).
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        return "", [f"Could not open PDF: {e}"]

    if doc.page_count == 0:
        return "", ["PDF has no pages."]

    parts = [page.get_text("text") for page in doc if page.get_text("text").strip()]
    doc.close()
    text = "\n".join(parts)

    warnings = []
    if not text.strip():
        warnings.append(
            "No extractable text found. This PDF may be image-based or scanned. "
            "ATS systems (and this tool) cannot parse image-only PDFs — "
            "please use a digitally-created, text-selectable PDF."
        )
    return text, warnings


# ─────────────────────────────────────────────
# ANALYSIS ENGINE
# ─────────────────────────────────────────────

def detect_sections(text: str) -> dict:
    tl = text.lower()
    return {s: any(kw in tl for kw in kws) for s, kws in SECTION_KEYWORDS.items()}


def structural_diagnostics(text: str) -> list:
    """
    Structural checks — returns list of {level, message} dicts.
    Levels: "error" | "warning" | "info"
    """
    issues = []
    words  = text.split()
    wc     = len(words)

    if wc < MIN_RESUME_WORDS:
        issues.append({"level": "error",
            "message": f"Resume is very short ({wc} words). Most ATS expect ≥{MIN_RESUME_WORDS} words."})
    elif wc > 1200:
        issues.append({"level": "warning",
            "message": f"Resume is long ({wc} words). Recruiters and ATS prefer 400–800 words (1–2 pages)."})

    if not re.search(r"\d+\s*%|\$\s*\d+|\d+\s*\+?\s*(years?|months?|clients?|projects?|teams?|employees?|users?|million|k\b)", text, re.I):
        issues.append({"level": "warning",
            "message": "No quantifiable achievements found (e.g. '40% faster', '$2M revenue', '10+ projects'). Numbers help."})

    if not re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text):
        issues.append({"level": "warning",
            "message": "No email address detected in extractable text. Verify it's not embedded in an image."})

    if text.count("\t") > 20:
        issues.append({"level": "warning",
            "message": f"High tab count ({text.count(chr(9))}) detected — possible multi-column layout. Some ATS struggle with this."})

    if len(re.findall(r"[|■●◆▸►•‣⦿◉]", text)) > 15:
        issues.append({"level": "warning",
            "message": "Many decorative characters detected. Heavy design elements can corrupt ATS parsing."})

    if not re.search(r"(\+?\d[\d\s\-().]{7,}\d)", text):
        issues.append({"level": "info",
            "message": "No phone number detected. Verify it's not embedded in a header image."})

    if not issues:
        issues.append({"level": "info",
            "message": "No major formatting issues detected. Structure looks ATS-friendly. ✓"})

    return issues


def run_full_audit(resume_text: str, jd_text: str) -> dict:
    """
    Full audit — resume vs job description.

    SCORING FORMULA (simple, honest, explainable):
    ─────────────────────────────────────────────
    We measure two things:

    1. Coverage  = matched tokens / JD tokens
       "How much of the JD vocabulary appears in your resume?"

    2. Jaccard   = matched tokens / union of all tokens
       "How focused is the overlap relative to both documents combined?"

    Blend: score_raw = 0.70 × coverage + 0.30 × jaccard

    Then we apply a square-root stretch so the display score feels
    proportional to effort. A resume with 50% raw coverage displays
    as ~70%, not 50% — because covering half the JD keywords is
    genuinely good performance for a real resume.

    Final: display_score = √score_raw × 98   (capped at 98)
    """
    r_tokens = tokenize(resume_text)
    j_tokens = tokenize(jd_text)

    if not j_tokens:
        return {"error": "Job description produced no tokens after processing. Try pasting more content."}

    matched  = r_tokens & j_tokens
    gaps     = j_tokens - r_tokens
    union    = r_tokens | j_tokens

    coverage = len(matched) / len(j_tokens)
    jaccard  = len(matched) / len(union) if union else 0
    raw      = 0.70 * coverage + 0.30 * jaccard
    score    = min(math.sqrt(raw) * 98, 98.0)

    tier_label, tier_emoji = get_score_tier(score)
    sections    = detect_sections(resume_text)
    diagnostics = structural_diagnostics(resume_text)
    tips        = generate_tips(resume_text, sections, gaps)

    return {
        "mode":               "full",
        "score":              round(score, 1),
        "tier_label":         tier_label,
        "tier_emoji":         tier_emoji,
        "matched_keywords":   sorted(matched),
        "gap_keywords":       sorted(gaps),
        "token_count_resume": len(r_tokens),
        "token_count_jd":     len(j_tokens),
        "token_count_matched":len(matched),
        "coverage_pct":       round(coverage * 100, 1),
        "jaccard_pct":        round(jaccard  * 100, 1),
        "sections":           sections,
        "diagnostics":        diagnostics,
        "tips":               tips,
        "word_count":         len(resume_text.split()),
    }


def run_health_check(resume_text: str) -> dict:
    """
    Resume-only health check.

    RICHNESS SCORE:
    ───────────────
    raw_ratio = unique meaningful tokens / total words

    A well-written resume typically has raw_ratio ≈ 0.45–0.60.
    We scale that to a fair display range:

    display_score = √(raw_ratio / 0.65) × 98

    So raw_ratio 0.47 (like yours) → display ~73%, not 47%.
    That's honest — 47% vocabulary diversity is genuinely solid writing.
    """
    r_tokens = tokenize(resume_text)
    sections    = detect_sections(resume_text)
    diagnostics = structural_diagnostics(resume_text)
    wc          = len(resume_text.split())

    raw_ratio   = len(r_tokens) / wc if wc else 0
    score       = min(math.sqrt(raw_ratio / 0.65) * 98, 98.0)
    score       = max(score, 5.0)

    tips = generate_tips(resume_text, sections, set())

    return {
        "mode":          "health",
        "richness_score": round(score, 1),
        "raw_richness":   round(raw_ratio * 100, 1),
        "unique_tokens":  len(r_tokens),
        "word_count":     wc,
        "sections":       sections,
        "diagnostics":    diagnostics,
        "tips":           tips,
    }


def generate_tips(resume_text: str, sections: dict, gaps: set) -> list:
    tips = []
    if not sections.get("summary"):
        tips.append("Add a professional summary — ATS systems use it to classify your profile quickly.")
    if not sections.get("skills"):
        tips.append("Add a dedicated Skills section. Many ATS parsers specifically look for this heading.")
    if not sections.get("projects"):
        tips.append("Consider adding a Projects section to demonstrate hands-on work.")
    if not re.search(r"\d+\s*%|\$\s*\d+|\d+\s*\+?\s*(years?|months?|clients?|projects?)", resume_text, re.I):
        tips.append("Quantify achievements — numbers, percentages, and dollar amounts make a real difference.")
    if gaps and len(gaps) > 5:
        tips.append(f"Try weaving in missing keywords naturally — e.g.: {', '.join(list(gaps)[:5])}.")
    if len(resume_text.split()) < 300:
        tips.append("Expand your content. 400–600 words is the sweet spot for most ATS systems.")
    if not tips:
        tips.append("Resume looks solid! Keep tailoring it for each specific role — it pays off.")
    return tips


def generate_export(result: dict) -> str:
    """
    Build plain-text report from session data.
    Generated entirely in-memory — no file is read or written.
    """
    mode  = result.get("mode", "full")
    lines = [
        "STATELESS ATS AUDITOR — AUDIT REPORT",
        "=" * 42, "",
    ]
    if mode == "full":
        lines += [
            f"Match Score    : {result['score']}%  {result['tier_emoji']} {result['tier_label']}",
            f"Coverage       : {result['coverage_pct']}%  (JD keywords found in resume)",
            f"Jaccard        : {result['jaccard_pct']}%  (overlap vs combined vocabulary)",
            f"Matched Tokens : {result['token_count_matched']} of {result['token_count_jd']} JD keywords",
            f"Resume Tokens  : {result['token_count_resume']} unique", "",
            "KEYWORD MATCHES:",
            ", ".join(result["matched_keywords"]) or "None", "",
            "KNOWLEDGE GAPS:",
            ", ".join(result["gap_keywords"]) or "None", "",
        ]
    else:
        lines += [
            f"Richness Score : {result['richness_score']}%",
            f"Raw Ratio      : {result['raw_richness']}%",
            f"Unique Tokens  : {result['unique_tokens']}",
            f"Word Count     : {result['word_count']}", "",
        ]

    lines += ["DETECTED SECTIONS:"]
    for s, found in result["sections"].items():
        lines.append(f"  {'✓' if found else '✗'} {s.upper()}")

    lines += ["", "DIAGNOSTICS:"]
    for d in result["diagnostics"]:
        lines.append(f"  [{d['level'].upper()}] {d['message']}")

    lines += ["", "IMPROVEMENT SUGGESTIONS:"]
    for t in result["tips"]:
        lines.append(f"  → {t}")

    lines += [
        "", "─" * 42,
        "Generated by Stateless ATS Auditor.",
        "No resume data was stored or transmitted to any server or API.",
        "Source: https://github.com/AryaBuwa/stateless-ats-auditor",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────

def init_session():
    defaults = {
        "audit_result":  None,
        "resume_text":   None,
        "pdf_warnings":  [],
        "error_message": None,
        "dark_mode":     True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def purge_session():
    """
    Clears all session data.
    dark_mode is a UI preference, not data — it survives the purge
    so the user doesn't lose their theme on every clear.
    """
    pref = st.session_state.get("dark_mode", True)
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state["dark_mode"] = pref
    st.rerun()


# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────

def inject_css(dark: bool):
    # ── theme tokens ──
    if dark:
        bg           = "#0f0f0f"
        bg_card      = "#1a1a1a"
        bg_input     = "#141414"
        text         = "#e8e8e8"
        text2        = "#888888"
        accent       = "#00d4aa"
        accent_dim   = "#00a882"
        border       = "#2a2a2a"
        badge_bg     = "#1e2d2a"
        warn_bg      = "#2d2200";  warn_bd  = "#ff9800"
        err_bg       = "#2d1010";  err_bd   = "#f44336"
        info_bg      = "#0d1a2d";  info_bd  = "#2196f3"
        ok_bg        = "#0d2d1e";  ok_bd    = "#4caf50"
        upload_bg    = "#1a1a1a"
        upload_text  = "#888888"
    else:
        bg           = "#f5f5f0"
        bg_card      = "#ffffff"
        bg_input     = "#fafafa"
        text         = "#1a1a1a"
        text2        = "#555555"
        accent       = "#00a882"
        accent_dim   = "#007a60"
        border       = "#e0e0e0"
        badge_bg     = "#e8f5f1"
        warn_bg      = "#fff8e1";  warn_bd  = "#e67e00"
        err_bg       = "#ffebee";  err_bd   = "#c62828"
        info_bg      = "#e3f2fd";  info_bd  = "#1565c0"
        ok_bg        = "#e8f5e9";  ok_bd    = "#2e7d32"
        upload_bg    = "#ffffff"
        upload_text  = "#333333"

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

*, *::before, *::after {{ box-sizing: border-box; }}

/* ── App base ── */
.stApp {{
    background-color: {bg} !important;
    color: {text} !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}}
[data-testid="stAppViewContainer"] {{
    background-color: {bg} !important;
}}
[data-testid="stHeader"] {{ background: transparent !important; }}
#MainMenu, footer, header {{ visibility: hidden; }}
.stDeployButton {{ display: none !important; }}

/* ── Global text colour — catches Streamlit's own labels ── */
label, p, span, div {{
    color: {text} !important;
}}

/* ── Headings ── */
h1,h2,h3,h4 {{
    font-family: 'IBM Plex Mono', monospace !important;
    color: {text} !important;
}}

/* ── Inputs ── */
.stTextArea textarea, .stTextInput input {{
    background-color: {bg_input} !important;
    color: {text} !important;
    border: 1px solid {border} !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
}}
.stTextArea textarea:focus {{
    border-color: {accent} !important;
    box-shadow: 0 0 0 2px {accent}33 !important;
    outline: none !important;
}}
.stTextArea label, .stTextInput label {{
    color: {text2} !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
}}

/* ── File uploader ── */
[data-testid="stFileUploadDropzone"],
[data-testid="stFileUploader"] section,
section[data-testid="stFileUploadDropzone"] {{
    background-color: {bg_input} !important;
    background: {bg_input} !important;
    border: 2px dashed {border} !important;
    border-radius: 8px !important;
}}
[data-testid="stFileUploadDropzone"]:hover,
section[data-testid="stFileUploadDropzone"]:hover {{
    border-color: {accent} !important;
}}
/* All text inside the uploader */
[data-testid="stFileUploadDropzone"] *,
[data-testid="stFileUploaderDropzoneInstructions"] * {{
    color: {text2} !important;
}}
/* Hide the "Limit 200MB per file" text */
[data-testid="stFileUploadDropzone"] small,
[data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploadDropzone"] span small {{
    display: none !important;
}}
/* Browse files button inside uploader */
[data-testid="stFileUploadDropzone"] button,
[data-testid="stFileUploaderDropzoneInstructions"] button {{
    background-color: {bg_card} !important;
    color: {accent} !important;
    border: 1px solid {accent} !important;
    width: auto !important;
}}

/* ══════════════════════════════════════════
   BUTTONS — nuclear override for Streamlit.
   Targets every selector variant including
   data-testid attributes Streamlit uses
   internally to force background colours.
   ══════════════════════════════════════════ */

/* Kill Streamlit's own button background first */
[data-testid="baseButton-secondary"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-secondary"]:focus,
[data-testid="baseButton-primary"]:focus,
button[kind="secondary"],
button[kind="primary"] {{
    background-color: transparent !important;
    background: transparent !important;
    color: {accent} !important;
    border: 1.5px solid {accent} !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.03em !important;
    transition: background 0.2s, color 0.2s, box-shadow 0.2s, transform 0.15s !important;
    width: 100% !important;
    box-shadow: none !important;
}}

/* Hover */
[data-testid="baseButton-secondary"]:hover,
[data-testid="baseButton-primary"]:hover {{
    background-color: {accent} !important;
    background: {accent} !important;
    color: {bg} !important;
    border-color: {accent} !important;
    box-shadow: 0 4px 12px {accent}40 !important;
    transform: translateY(-1px) !important;
}}
[data-testid="baseButton-secondary"]:active,
[data-testid="baseButton-primary"]:active {{
    transform: translateY(0) !important;
    box-shadow: none !important;
}}

/* CTA wrapper — Run Analysis filled */
.cta-btn [data-testid="baseButton-secondary"],
.cta-btn [data-testid="baseButton-primary"],
.cta-btn button {{
    background-color: {accent} !important;
    background: {accent} !important;
    color: {bg} !important;
    border-color: {accent} !important;
    font-size: 0.95rem !important;
}}
.cta-btn [data-testid="baseButton-secondary"]:hover,
.cta-btn [data-testid="baseButton-primary"]:hover {{
    background-color: {accent_dim} !important;
    background: {accent_dim} !important;
    color: {bg} !important;
}}
.cta-btn button:hover,
.cta-btn .stButton > button:hover {{
    background-color: {accent_dim} !important;
    background: {accent_dim} !important;
    color: {bg} !important;
    border-color: {accent_dim} !important;
}}

/* Danger — Purge Session */
.danger-btn [data-testid="baseButton-secondary"],
.danger-btn [data-testid="baseButton-primary"],
.danger-btn button {{
    background-color: transparent !important;
    background: transparent !important;
    color: {err_bd} !important;
    border-color: {err_bd} !important;
    border-width: 1.5px !important;
}}
.danger-btn [data-testid="baseButton-secondary"]:hover,
.danger-btn [data-testid="baseButton-primary"]:hover,
.danger-btn button:hover {{
    background-color: {err_bd} !important;
    background: {err_bd} !important;
    color: #ffffff !important;
    border-color: {err_bd} !important;
}}

/* Download button */
.stDownloadButton [data-testid="baseButton-secondary"],
.stDownloadButton button {{
    background-color: transparent !important;
    background: transparent !important;
    color: {text2} !important;
    border: 1px solid {border} !important;
    font-size: 0.8rem !important;
}}
.stDownloadButton [data-testid="baseButton-secondary"]:hover,
.stDownloadButton button:hover {{
    border-color: {accent} !important;
    color: {accent} !important;
    background-color: transparent !important;
}}

/* File uploader browse button — the black button inside the dropzone */
[data-testid="stFileUploadDropzone"] [data-testid="baseButton-secondary"],
[data-testid="stFileUploadDropzone"] button,
[data-testid="stFileUploaderDropzoneInstructions"] button {{
    background-color: {bg_card} !important;
    background: {bg_card} !important;
    color: {accent} !important;
    border: 1px solid {accent} !important;
    border-radius: 4px !important;
    font-size: 0.78rem !important;
    width: auto !important;
    padding: 0.3rem 0.8rem !important;
}}
[data-testid="stFileUploadDropzone"] button:hover {{
    background-color: {accent} !important;
    color: {bg} !important;
}}

/* ── Radio buttons — fully themed ── */
.stRadio > div {{ gap: 0.4rem !important; flex-wrap: wrap; }}
.stRadio label {{ color: {text} !important; }}
.stRadio label p {{ color: {text} !important; }}
div[role="radiogroup"] label {{
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    color: {text} !important;
    background: {bg_card} !important;
    border: 1px solid {border} !important;
    border-radius: 6px !important;
    padding: 0.35rem 0.8rem !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
}}
div[role="radiogroup"] label:hover {{
    border-color: {accent} !important;
}}
/* Hide the actual radio circle — use border highlight instead */
div[role="radiogroup"] [data-testid="stMarkdownContainer"] p {{
    color: {text} !important;
    margin: 0 !important;
}}

/* ── Checkbox (dark mode toggle) ── */
.stCheckbox label {{ color: {text2} !important; font-size: 0.8rem !important; }}
.stCheckbox label p {{ color: {text2} !important; }}

/* ── Expander ── */
.streamlit-expanderHeader {{
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.82rem !important;
    color: {text2} !important;
    background: {bg_card} !important;
    border: 1px solid {border} !important;
    border-radius: 6px !important;
}}
.streamlit-expanderContent {{
    background: {bg_card} !important;
    border: 1px solid {border} !important;
    border-top: none !important;
    border-radius: 0 0 6px 6px !important;
    color: {text} !important;
}}
.streamlit-expanderContent p, .streamlit-expanderContent li,
.streamlit-expanderContent code {{
    color: {text} !important;
}}

/* ── Cards ── */
.ats-card {{
    background: {bg_card};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    animation: fadeInUp 0.4s ease both;
}}
.ats-card-accent {{ border-left: 3px solid {accent}; }}

/* ── Score ── */
.score-number {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 4.5rem;
    font-weight: 600;
    color: {accent};
    line-height: 1;
    text-align: center;
}}
.score-label {{
    font-size: 0.85rem;
    color: {text2};
    text-align: center;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 0.3rem;
}}
.score-tier {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1rem;
    font-weight: 500;
    color: {text};
    text-align: center;
    margin-top: 0.4rem;
}}
.score-meta {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: {text2};
    text-align: center;
    margin-top: 0.6rem;
}}
.score-bar-wrap {{
    width: 100%;
    height: 5px;
    background: {border};
    border-radius: 3px;
    margin: 0.8rem 0;
    overflow: hidden;
}}
.score-bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, {accent_dim}, {accent});
    border-radius: 3px;
    animation: growBar 1.2s ease both;
    transform-origin: left;
}}

/* ── Keywords ── */
.keyword-grid {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }}
.kw-match {{
    background: {ok_bg}; border: 1px solid {ok_bd}; color: {ok_bd};
    font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem;
    padding: 0.15rem 0.55rem; border-radius: 4px;
}}
.kw-gap {{
    background: {err_bg}; border: 1px solid {err_bd}; color: {err_bd};
    font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem;
    padding: 0.15rem 0.55rem; border-radius: 4px;
}}

/* ── Diagnostics ── */
.diag-warning {{
    background:{warn_bg}; border-left:3px solid {warn_bd};
    padding:0.55rem 0.9rem; border-radius:0 6px 6px 0;
    margin-bottom:0.4rem; font-size:0.83rem; color:{text};
}}
.diag-error {{
    background:{err_bg}; border-left:3px solid {err_bd};
    padding:0.55rem 0.9rem; border-radius:0 6px 6px 0;
    margin-bottom:0.4rem; font-size:0.83rem; color:{text};
}}
.diag-info {{
    background:{info_bg}; border-left:3px solid {info_bd};
    padding:0.55rem 0.9rem; border-radius:0 6px 6px 0;
    margin-bottom:0.4rem; font-size:0.83rem; color:{text};
}}

/* ── Section badges ── */
.sbadge-found {{
    display:inline-block; background:{ok_bg}; border:1px solid {ok_bd};
    color:{ok_bd}; font-family:'IBM Plex Mono',monospace; font-size:0.68rem;
    padding:0.12rem 0.45rem; border-radius:4px; margin:0.12rem;
    text-transform:uppercase; letter-spacing:0.05em;
}}
.sbadge-miss {{
    display:inline-block; background:{bg}; border:1px solid {border};
    color:{text2}; font-family:'IBM Plex Mono',monospace; font-size:0.68rem;
    padding:0.12rem 0.45rem; border-radius:4px; margin:0.12rem;
    text-transform:uppercase; letter-spacing:0.05em; text-decoration:line-through;
}}

/* ── Trust grid ── */
.trust-grid {{
    display:grid; grid-template-columns:repeat(2,1fr); gap:0.6rem; margin-top:0.75rem;
}}
.trust-item {{
    background:{badge_bg}; border:1px solid {border}; border-radius:8px;
    padding:0.65rem 0.85rem; font-size:0.8rem; font-family:'IBM Plex Mono',monospace;
    color:{text2}; display:flex; align-items:flex-start; gap:0.45rem;
}}
.trust-item .ti {{color:{accent}; flex-shrink:0;}}

/* ── Steps ── */
.steps-row {{ display:flex; gap:0.75rem; flex-wrap:wrap; margin-top:0.5rem; }}
.step-item {{
    flex:1; min-width:130px; background:{bg_card}; border:1px solid {border};
    border-radius:8px; padding:0.85rem; text-align:center;
}}
.step-num {{ font-family:'IBM Plex Mono',monospace; font-size:1.4rem; font-weight:600; color:{accent}; }}
.step-title {{ font-size:0.82rem; font-weight:500; color:{text}; margin-top:0.3rem; }}
.step-desc {{ font-size:0.73rem; color:{text2}; margin-top:0.25rem; line-height:1.4; }}

/* ── Tips ── */
.tip-item {{
    display:flex; gap:0.5rem; align-items:flex-start;
    padding:0.45rem 0; border-bottom:1px solid {border};
    font-size:0.83rem; color:{text};
}}
.tip-item:last-child {{ border-bottom:none; }}
.tip-icon {{ color:{accent}; flex-shrink:0; }}

/* ── Hero ── */
.hero-title {{
    font-family:'IBM Plex Mono',monospace; font-size:2rem;
    font-weight:600; color:{text}; line-height:1.2;
}}
.hero-accent {{ color:{accent}; }}
.hero-sub {{
    font-family:'IBM Plex Sans',sans-serif; font-size:0.95rem;
    color:{text2}; margin-top:0.4rem; line-height:1.6;
}}
.mono-tag {{
    font-family:'IBM Plex Mono',monospace; font-size:0.68rem;
    background:{badge_bg}; border:1px solid {border}; color:{accent};
    padding:0.12rem 0.45rem; border-radius:3px; letter-spacing:0.05em;
}}
.section-label {{
    font-family:'IBM Plex Mono',monospace; font-size:0.72rem;
    letter-spacing:0.1em; opacity:0.45; color:{text};
}}
.ats-divider {{
    border:none; border-top:1px solid {border}; margin:1.5rem 0;
}}
.pulse {{
    animation:pulse 1.5s ease infinite;
    color:{accent}; font-family:'IBM Plex Mono',monospace; font-size:0.88rem;
}}

/* ── Animations ── */
@keyframes fadeInUp {{
    from {{ opacity:0; transform:translateY(10px); }}
    to   {{ opacity:1; transform:translateY(0); }}
}}
@keyframes fadeIn {{
    from {{ opacity:0; }} to {{ opacity:1; }}
}}
@keyframes growBar {{
    from {{ transform:scaleX(0); }} to {{ transform:scaleX(1); }}
}}
@keyframes pulse {{
    0%,100% {{ opacity:1; }} 50% {{ opacity:0.4; }}
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width:5px; height:5px; }}
::-webkit-scrollbar-track {{ background:{bg}; }}
::-webkit-scrollbar-thumb {{ background:{border}; border-radius:3px; }}
::-webkit-scrollbar-thumb:hover {{ background:{accent}; }}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────

def render_hero():
    st.markdown("""
<div class="hero-title">Stateless <span class="hero-accent">ATS</span> Auditor</div>
<div class="hero-sub">
  Feed it your resume. Optionally, a job description. Get a straight-talking
  compatibility report — processed entirely in-memory, gone the moment you close the tab.
  No accounts. No databases. No nonsense.
</div>
<br/>
<span class="mono-tag">v1.0.0</span>&nbsp;
<span class="mono-tag">STATELESS</span>&nbsp;
<span class="mono-tag">OPEN SOURCE</span>
""", unsafe_allow_html=True)


def render_how_it_works():
    st.markdown("""
<div class="ats-card">
  <div class="section-label">HOW IT WORKS</div>
  <div class="steps-row">
    <div class="step-item">
      <div class="step-num">01</div>
      <div class="step-title">Upload Resume</div>
      <div class="step-desc">Drop your PDF. Text is extracted using PyMuPDF, locally in RAM.</div>
    </div>
    <div class="step-item">
      <div class="step-num">02</div>
      <div class="step-title">Add JD (Optional)</div>
      <div class="step-desc">Paste the job description for a match score, or skip for a health check.</div>
    </div>
    <div class="step-item">
      <div class="step-num">03</div>
      <div class="step-title">Analyze</div>
      <div class="step-desc">Token intersection logic scores your resume — no AI black box.</div>
    </div>
    <div class="step-item">
      <div class="step-num">04</div>
      <div class="step-title">Review & Clear</div>
      <div class="step-desc">Read your report, export it, hit Purge — data is gone. No traces.</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


def render_privacy_poc():
    st.markdown("""
<div class="ats-card ats-card-accent">
  <div class="section-label">DATA PRIVACY — PROOF OF CONCEPT</div>
  <div style="font-size:0.83rem; margin-top:0.6rem; line-height:1.6; opacity:0.8;">
    Your resume is processed on the server running this app, in volatile RAM.
    It is <b>never written to disk, stored in a database, sent to any third-party API, or logged.</b>
    The source code is public — verify every claim line by line.
  </div>
  <div class="trust-grid">
    <div class="trust-item"><span class="ti">✓</span><div><b>No database writes</b><br/>Session state only — cleared on purge or tab close.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>No external API calls</b><br/>PyMuPDF parses locally. Zero third-party transfer.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>No file logging</b><br/>Bytes are processed then discarded from RAM.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>Open source</b><br/>Every claim is verifiable in the published code.</div></div>
  </div>
</div>
""", unsafe_allow_html=True)


def render_score_full(result: dict):
    score = result["score"]
    st.markdown(f"""
<div class="ats-card" style="text-align:center; padding:2rem 1rem;">
  <div class="score-number">{score}%</div>
  <div class="score-label">Match Analysis Score</div>
  <div class="score-bar-wrap"><div class="score-bar-fill" style="width:{score}%"></div></div>
  <div class="score-tier">{result['tier_emoji']} {result['tier_label']}</div>
  <div class="score-meta">
    {result['token_count_matched']} of {result['token_count_jd']} JD keywords matched &nbsp;·&nbsp;
    coverage {result['coverage_pct']}% &nbsp;·&nbsp; jaccard {result['jaccard_pct']}%
  </div>
</div>
""", unsafe_allow_html=True)


def render_score_health(result: dict):
    score = result["richness_score"]
    st.markdown(f"""
<div class="ats-card" style="text-align:center; padding:2rem 1rem;">
  <div class="score-number">{score}%</div>
  <div class="score-label">Keyword Richness Score</div>
  <div class="score-bar-wrap"><div class="score-bar-fill" style="width:{score}%"></div></div>
  <div class="score-tier">Resume Health Check</div>
  <div class="score-meta">
    {result['unique_tokens']} unique tokens &nbsp;·&nbsp;
    {result['word_count']} total words &nbsp;·&nbsp;
    raw ratio {result['raw_richness']}%
  </div>
</div>
""", unsafe_allow_html=True)


def render_explainability(mode: str, result: dict):
    if mode == "full":
        c = result.get("coverage_pct","—")
        j = result.get("jaccard_pct","—")
        body = f"""
**Two signals, one honest score.**

- **Coverage ({c}%)** — what % of the JD's unique keywords appear in your resume *(70% weight)*
- **Jaccard ({j}%)** — shared keywords ÷ all unique keywords across both docs *(30% weight)*

```
blended  = 0.70 × coverage  +  0.30 × jaccard
display  = √blended × 98
```

The square-root stretch means covering 50% of a JD lands you ~70%, not 50% — because that's genuinely good alignment. Hard ceiling of 98% — a perfect score is a red flag, not a goal.
"""
    else:
        r = result.get("raw_richness","—")
        body = f"""
**Vocabulary diversity, scaled fairly.**

Raw ratio (unique tokens ÷ total words): **{r}%**

A well-written resume typically has a raw ratio of 45–60%. We scale it:

```
display = √(raw_ratio / 0.65) × 98
```

So raw 47% → display ~73%. That's honest — high vocabulary diversity *is* good writing.
"""
    with st.expander("How was this score calculated?"):
        st.markdown(body)


def render_sections(sections: dict):
    badges = "".join(
        f'<span class="sbadge-found">✓ {s.upper()}</span>' if found
        else f'<span class="sbadge-miss">{s.upper()}</span>'
        for s, found in sections.items()
    )
    st.markdown(f"""
<div class="ats-card">
  <div class="section-label">DETECTED SECTIONS</div>
  <div style="margin-top:0.6rem;">{badges}</div>
</div>
""", unsafe_allow_html=True)


def render_keywords(matched: list, gaps: list):
    mhtml = "".join(f'<span class="kw-match">{k}</span>' for k in matched[:60])
    ghtml = "".join(f'<span class="kw-gap">{k}</span>'   for k in gaps[:60])
    mn = f"<div style='font-size:0.7rem;opacity:0.4;margin-top:0.4rem;'>Top 60 of {len(matched)}</div>" if len(matched)>60 else ""
    gn = f"<div style='font-size:0.7rem;opacity:0.4;margin-top:0.4rem;'>Top 60 of {len(gaps)}</div>"   if len(gaps)>60   else ""

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
<div class="ats-card">
  <div class="section-label">✓ KEYWORD MATCHES ({len(matched)})</div>
  <div class="keyword-grid" style="margin-top:0.5rem;">{mhtml}</div>{mn}
</div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
<div class="ats-card">
  <div class="section-label">✗ KNOWLEDGE GAPS ({len(gaps)})</div>
  <div class="keyword-grid" style="margin-top:0.5rem;">{ghtml}</div>{gn}
</div>""", unsafe_allow_html=True)


def render_diagnostics(diagnostics: list):
    icons = {"warning":"⚠","error":"✖","info":"ℹ"}
    items = "".join(
        f'<div class="diag-{d["level"]}">{icons.get(d["level"],"·")} {d["message"]}</div>'
        for d in diagnostics
    )
    st.markdown(f"""
<div class="ats-card">
  <div class="section-label">FORMATTING &amp; COMPATIBILITY DIAGNOSTICS</div>
  <div style="margin-top:0.65rem;">{items}</div>
</div>""", unsafe_allow_html=True)


def render_tips(tips: list):
    items = "".join(
        f'<div class="tip-item"><span class="tip-icon">→</span><span>{t}</span></div>'
        for t in tips
    )
    st.markdown(f"""
<div class="ats-card ats-card-accent">
  <div class="section-label">IMPROVEMENT SUGGESTIONS</div>
  <div style="margin-top:0.65rem;">{items}</div>
</div>""", unsafe_allow_html=True)


def render_footer(dark: bool):
    border_c = "#2a2a2a" if dark else "#e0e0e0"
    text_c   = "#555555" if dark else "#444444"
    link_c   = "#00d4aa" if dark else "#00a882"
    st.markdown(f"""
<div style="border-top:1px solid {border_c}; padding:1.5rem 0 2.5rem; display:flex;
     justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-top:2rem;">
  <div style="font-family:'IBM Plex Mono',monospace; font-size:0.68rem; color:{text_c};">
    stateless-ats-auditor &nbsp;·&nbsp; v1.0.0 &nbsp;·&nbsp; zero data retained
  </div>
  <div style="font-family:'IBM Plex Mono',monospace; font-size:0.68rem; color:{text_c};">
    built by &nbsp;<a href="https://github.com/AryaBuwa" target="_blank"
      style="color:{link_c}; text-decoration:none; font-weight:500;
             border-bottom:1px solid {link_c};">Arya</a>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Stateless ATS Auditor",
        page_icon="📋",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    init_session()

    # ── Dark/light toggle (top right) ──
    col_hero, col_toggle = st.columns([5, 1])
    with col_toggle:
        dark = st.checkbox("🌙", value=st.session_state.dark_mode,
                           key="dark_mode_toggle", help="Toggle dark / light mode")
        st.session_state.dark_mode = dark

    inject_css(dark)

    # JS fallback: force button styles that CSS alone can't reach due to
    # Streamlit's internal specificity. Runs after DOM is ready.
    accent_js  = "#00d4aa" if dark else "#00a882"
    bg_js      = "#0f0f0f" if dark else "#f5f5f0"
    err_js     = "#f44336" if dark else "#c62828"
    card_js    = "#1a1a1a" if dark else "#ffffff"
    st.markdown(f"""
<script>
(function applyButtonFix() {{
    function fix() {{
        // All stButton buttons
        document.querySelectorAll('[data-testid="baseButton-secondary"], [data-testid="baseButton-primary"]').forEach(function(btn) {{
            if (btn.closest('.cta-btn')) {{
                btn.style.setProperty('background-color', '{accent_js}', 'important');
                btn.style.setProperty('color', '{bg_js}', 'important');
                btn.style.setProperty('border-color', '{accent_js}', 'important');
            }} else if (btn.closest('.danger-btn')) {{
                btn.style.setProperty('background-color', 'transparent', 'important');
                btn.style.setProperty('color', '{err_js}', 'important');
                btn.style.setProperty('border-color', '{err_js}', 'important');
            }} else if (!btn.closest('[data-testid="stFileUploadDropzone"]') && !btn.closest('.stDownloadButton')) {{
                btn.style.setProperty('background-color', 'transparent', 'important');
                btn.style.setProperty('color', '{accent_js}', 'important');
                btn.style.setProperty('border-color', '{accent_js}', 'important');
            }}
        }});
        // File uploader browse button
        document.querySelectorAll('[data-testid="stFileUploadDropzone"] button').forEach(function(btn) {{
            btn.style.setProperty('background-color', '{card_js}', 'important');
            btn.style.setProperty('color', '{accent_js}', 'important');
            btn.style.setProperty('border', '1px solid {accent_js}', 'important');
        }});
    }}
    // Run immediately and on any DOM mutation
    fix();
    new MutationObserver(fix).observe(document.body, {{childList: true, subtree: true}});
}})();
</script>
""", unsafe_allow_html=True)

    with col_hero:
        render_hero()

    st.markdown("<br/>", unsafe_allow_html=True)
    render_how_it_works()
    st.markdown("<br/>", unsafe_allow_html=True)
    render_privacy_poc()
    st.markdown("<hr class='ats-divider'/>", unsafe_allow_html=True)

    # ── Inputs ──
    st.markdown('<div class="section-label">DOCUMENT INPUT STREAM</div>', unsafe_allow_html=True)
    st.markdown("<br/>", unsafe_allow_html=True)

    scan_mode = st.radio(
        "mode",
        ["Full Audit (Resume + Job Description)", "Resume Health Check (Resume Only)"],
        horizontal=True,
        label_visibility="collapsed",
    )
    mode = "full" if "Full" in scan_mode else "health"

    st.markdown("<br/>", unsafe_allow_html=True)

    # Custom label above uploader (Streamlit's built-in "200MB" text is hidden via CSS ::after)
    st.markdown(
        '<div class="section-label" style="margin-bottom:0.3rem;">'
        'UPLOAD RESUME PDF &nbsp;·&nbsp; MAX 5 MB &nbsp;·&nbsp; PDF ONLY'
        '</div>',
        unsafe_allow_html=True
    )
    uploaded_file = st.file_uploader(
        "resume_pdf",
        type=["pdf"],
        help="Max 5 MB. Resumes are typically 100 KB – 2 MB.",
        label_visibility="collapsed",
    )

    jd_text = ""
    if mode == "full":
        st.markdown("<br/>", unsafe_allow_html=True)
        jd_text = st.text_area(
            "Paste Job Description",
            height=180,
            placeholder="Paste the full job description here. More detail → more accurate score.",
            help=f"Minimum {MIN_JD_WORDS} words recommended.",
        )

    st.markdown("<br/>", unsafe_allow_html=True)

    col_run, col_purge = st.columns([3, 1])
    with col_run:
        st.markdown('<div class="cta-btn">', unsafe_allow_html=True)
        run_clicked = st.button("▶  Run Analysis", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_purge:
        st.markdown('<div class="danger-btn">', unsafe_allow_html=True)
        purge_clicked = st.button("✕  Purge Session", use_container_width=True,
                                  help="Clears all session data immediately.")
        st.markdown("</div>", unsafe_allow_html=True)

    if purge_clicked:
        purge_session()

    # ── Analysis ──
    if run_clicked:
        st.session_state.audit_result  = None
        st.session_state.error_message = None
        st.session_state.pdf_warnings  = []

        if uploaded_file is None:
            st.session_state.error_message = "No PDF uploaded. Please select a file to continue."

        elif uploaded_file.size > MAX_FILE_SIZE_BYTES:
            mb = uploaded_file.size / (1024 * 1024)
            st.session_state.error_message = (
                f"File too large ({mb:.1f} MB). Limit is {MAX_FILE_SIZE_MB} MB. "
                "Try re-saving or compressing the PDF."
            )

        elif mode == "full" and len(jd_text.strip().split()) < MIN_JD_WORDS:
            wc = len(jd_text.strip().split())
            st.session_state.error_message = (
                f"Job description too short ({wc} words). "
                f"Please paste at least {MIN_JD_WORDS} words, "
                "or switch to Resume Health Check mode."
            )

        else:
            file_bytes = uploaded_file.read()   # in-memory only, never written to disk
            with st.spinner("Extracting and analyzing…"):
                resume_text, warnings = extract_pdf_text(file_bytes)

            st.session_state.pdf_warnings = warnings

            if not resume_text.strip():
                st.session_state.error_message = (
                    "No extractable text found. This PDF may be image-based or scanned. "
                    "Please use a digitally-created, text-selectable PDF."
                )
            else:
                st.session_state.resume_text = resume_text
                if mode == "full":
                    st.session_state.audit_result = run_full_audit(resume_text, jd_text)
                else:
                    st.session_state.audit_result = run_health_check(resume_text)

    # ── Errors ──
    if st.session_state.error_message:
        st.markdown(
            f'<div class="diag-error" style="margin-top:1rem;border-radius:6px;padding:0.8rem 1rem;">'
            f'✖ &nbsp;{st.session_state.error_message}</div>',
            unsafe_allow_html=True
        )

    for w in st.session_state.pdf_warnings:
        st.markdown(
            f'<div class="diag-warning" style="margin-top:0.5rem;border-radius:6px;">'
            f'⚠ &nbsp;{w}</div>',
            unsafe_allow_html=True
        )

    # ── Results ──
    result = st.session_state.audit_result
    if result:
        if "error" in result:
            st.markdown(
                f'<div class="diag-error" style="margin-top:1rem;border-radius:6px;padding:0.8rem 1rem;">'
                f'✖ &nbsp;{result["error"]}</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown("<hr class='ats-divider'/>", unsafe_allow_html=True)
            st.markdown('<div class="section-label">AUDIT REPORT &amp; METRICS</div>',
                        unsafe_allow_html=True)
            st.markdown("<br/>", unsafe_allow_html=True)

            mk = result.get("mode", "full")
            if mk == "full":
                render_score_full(result)
            else:
                render_score_health(result)

            render_explainability(mk, result)
            render_sections(result["sections"])

            if mk == "full":
                render_keywords(result["matched_keywords"], result["gap_keywords"])

            render_diagnostics(result["diagnostics"])
            render_tips(result["tips"])

            st.markdown("<br/>", unsafe_allow_html=True)
            st.download_button(
                label="↓  Download Plain Text Report",
                data=generate_export(result),
                file_name="ats_audit_report.txt",
                mime="text/plain",
                help="Generated from session memory. Nothing is sent anywhere.",
            )

            st.markdown(
                '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;'
                'opacity:0.3;margin-top:0.4rem;text-align:center;">'
                'All data lives in this browser session. Close the tab or hit Purge to erase everything.'
                '</div>',
                unsafe_allow_html=True
            )

    render_footer(dark)


if __name__ == "__main__":
    main()