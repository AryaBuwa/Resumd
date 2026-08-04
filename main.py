"""
resumd — ATS-friendly Resume Scanner
=====================================
Privacy-first resume scanner. Everything runs in-memory on the app server.
No persistent storage, no retention, no external processing APIs or tracking.
Uploaded PDF is read into RAM, processed, and discarded when the session ends.

Source code is public — every privacy claim here is verifiable line by line.
"""

import re
import math
import streamlit as st
import fitz  # PyMuPDF

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

MAX_FILE_SIZE_MB    = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MIN_RESUME_WORDS    = 200
MIN_JD_WORDS        = 50

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
    "Experience":     ["experience","employment","work history","career","positions","roles","work experience"],
    "Education":      ["education","academic","degree","university","college","school","qualification","bachelor","master"],
    "Skills":         ["skills","technologies","tools","competencies","expertise","technical","proficiencies","tech stack"],
    "Summary":        ["summary","objective","profile","about","overview","introduction","professional summary"],
    "Projects":       ["projects","portfolio","work samples","case studies","personal projects","open source"],
    "Certifications": ["certifications","certificates","licenses","accreditations","credentials"],
    "Achievements":   ["achievements","awards","honors","recognition","accomplishments","highlights"],
}

# ATS benchmark scores per section (what a strong resume should score)
SECTION_BENCHMARKS = {
    "Experience":     85,
    "Education":      75,
    "Skills":         90,
    "Summary":        70,
    "Projects":       80,
    "Certifications": 65,
    "Achievements":   70,
}

# Weight of each section in final score
SECTION_WEIGHTS = {
    "Experience":     0.30,
    "Skills":         0.25,
    "Projects":       0.20,
    "Summary":        0.10,
    "Education":      0.08,
    "Certifications": 0.04,
    "Achievements":   0.03,
}


# ─────────────────────────────────────────────
# SCORING TIERS
# ─────────────────────────────────────────────

def get_score_tier(score: float) -> tuple:
    if score >= 80: return ("Excellent Match", "🟢")
    if score >= 65: return ("Strong Match",    "🟡")
    if score >= 50: return ("Fair Match",      "🟠")
    if score >= 35: return ("Weak Match",      "🔴")
    return                 ("Poor Match",      "⛔")


def score_color(score: float) -> str:
    if score >= 75: return "#00d4aa"
    if score >= 55: return "#f59e0b"
    return "#f44336"


# ─────────────────────────────────────────────
# TEXT PROCESSING
# ─────────────────────────────────────────────

def simple_stem(word: str) -> str:
    for suffix in ["ing","tion","tions","ation","ations","ed","er","ers",
                   "ly","ment","ments","ness","ity","ies","es","s"]:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def tokenize(text: str) -> set:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\+\#]", " ", text)
    cleaned = set()
    for token in text.split():
        token = token.strip(".,;:!?\"'()")
        if token and token not in STOP_WORDS and len(token) > 2:
            cleaned.add(simple_stem(token))
    return cleaned


def extract_section_text(full_text: str, section: str, keywords: list) -> str:
    """Extract approximate text belonging to a section."""
    tl = full_text.lower()
    lines = full_text.split('\n')
    section_lines = []
    in_section = False

    for i, line in enumerate(lines):
        ll = line.lower().strip()
        # detect section header
        if any(kw in ll for kw in keywords) and len(ll) < 50:
            in_section = True
            continue
        # detect next section header
        if in_section:
            is_new_section = False
            for other_section, other_kws in SECTION_KEYWORDS.items():
                if other_section != section and any(kw in ll for kw in other_kws) and len(ll) < 50:
                    is_new_section = True
                    break
            if is_new_section:
                break
            section_lines.append(line)

    return ' '.join(section_lines) if section_lines else ''


def extract_pdf_text(file_bytes: bytes) -> tuple:
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
            "ATS systems cannot parse image-only PDFs — please use a text-selectable PDF."
        )
    return text, warnings


# ─────────────────────────────────────────────
# SECTION SCORING ENGINE
# ─────────────────────────────────────────────

def score_section(section: str, section_text: str, resume_tokens: set,
                  jd_tokens: set, sections_found: dict) -> float:
    """
    Score each section on a 0-100 scale based on:
    - Whether the section exists (presence score)
    - Keyword density within the section
    - JD keyword overlap within the section (if JD provided)
    """
    # Section not found — base penalty
    if not sections_found.get(section, False):
        return 0.0

    # Section exists but no text extracted — partial credit
    if not section_text.strip():
        return 35.0

    section_tokens = tokenize(section_text)
    if not section_tokens:
        return 35.0

    # Base score for presence
    base = 40.0

    # Keyword density score (unique tokens vs word count)
    word_count = len(section_text.split())
    if word_count > 0:
        density = len(section_tokens) / word_count
        density_score = min(math.sqrt(density / 0.5) * 30, 30.0)
    else:
        density_score = 0.0

    # JD overlap score (if JD tokens available)
    if jd_tokens:
        section_jd_match = section_tokens & jd_tokens
        jd_overlap = len(section_jd_match) / len(jd_tokens) if jd_tokens else 0
        jd_score = min(math.sqrt(jd_overlap) * 30, 30.0)
    else:
        # health check mode — score by richness only
        jd_score = density_score

    total = base + density_score + jd_score
    return min(round(total, 1), 98.0)


def compute_section_scores(resume_text: str, resume_tokens: set,
                            jd_tokens: set, sections_found: dict) -> dict:
    """Compute individual score for each section."""
    scores = {}
    for section, keywords in SECTION_KEYWORDS.items():
        section_text = extract_section_text(resume_text, section, keywords)
        scores[section] = score_section(
            section, section_text, resume_tokens, jd_tokens, sections_found
        )
    return scores


def compute_weighted_final_score(section_scores: dict) -> float:
    """Weighted average of section scores → final display score."""
    total = sum(
        section_scores.get(s, 0) * w
        for s, w in SECTION_WEIGHTS.items()
    )
    # Normalize to 0-98
    return min(round(total, 1), 98.0)


# ─────────────────────────────────────────────
# ANALYSIS ENGINE
# ─────────────────────────────────────────────

def detect_sections(text: str) -> dict:
    tl = text.lower()
    return {s: any(kw in tl for kw in kws) for s, kws in SECTION_KEYWORDS.items()}


def structural_diagnostics(text: str) -> list:
    issues = []
    words = text.split()
    wc    = len(words)

    if wc < MIN_RESUME_WORDS:
        issues.append({"level": "error",
            "message": f"Resume is very short ({wc} words). Most ATS expect ≥{MIN_RESUME_WORDS} words."})
    elif wc > 1200:
        issues.append({"level": "warning",
            "message": f"Resume is long ({wc} words). Recruiters prefer 400–800 words (1–2 pages)."})

    if not re.search(r"\d+\s*%|\$\s*\d+|\d+\s*\+?\s*(years?|months?|clients?|projects?|teams?|employees?|users?|million|k\b)", text, re.I):
        issues.append({"level": "warning",
            "message": "No quantifiable achievements found (e.g. '40% faster', '$2M revenue', '10+ projects')."})

    if not re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text):
        issues.append({"level": "warning",
            "message": "No email address detected. Verify it's not embedded in an image."})

    if text.count("\t") > 20:
        issues.append({"level": "warning",
            "message": f"High tab count ({text.count(chr(9))}) — possible multi-column layout. Some ATS struggle with this."})

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
    r_tokens = tokenize(resume_text)
    j_tokens = tokenize(jd_text)

    if not j_tokens:
        return {"error": "Job description produced no tokens. Try pasting more content."}

    matched  = r_tokens & j_tokens
    gaps     = j_tokens - r_tokens
    union    = r_tokens | j_tokens

    coverage = len(matched) / len(j_tokens)
    jaccard  = len(matched) / len(union) if union else 0

    sections_found  = detect_sections(resume_text)
    section_scores  = compute_section_scores(resume_text, r_tokens, j_tokens, sections_found)
    weighted_score  = compute_weighted_final_score(section_scores)

    # Blend weighted section score with keyword matching score
    kw_raw   = 0.70 * coverage + 0.30 * jaccard
    kw_score = min(math.sqrt(kw_raw) * 98, 98.0)
    final    = round(0.60 * weighted_score + 0.40 * kw_score, 1)

    tier_label, tier_emoji = get_score_tier(final)
    diagnostics = structural_diagnostics(resume_text)
    tips        = generate_tips(resume_text, sections_found, gaps, section_scores)

    return {
        "mode":                "full",
        "score":               final,
        "tier_label":          tier_label,
        "tier_emoji":          tier_emoji,
        "matched_keywords":    sorted(matched),
        "gap_keywords":        sorted(gaps),
        "token_count_resume":  len(r_tokens),
        "token_count_jd":      len(j_tokens),
        "token_count_matched": len(matched),
        "coverage_pct":        round(coverage * 100, 1),
        "jaccard_pct":         round(jaccard  * 100, 1),
        "sections":            sections_found,
        "section_scores":      section_scores,
        "diagnostics":         diagnostics,
        "tips":                tips,
        "word_count":          len(resume_text.split()),
    }


def run_health_check(resume_text: str) -> dict:
    r_tokens       = tokenize(resume_text)
    sections_found = detect_sections(resume_text)
    section_scores = compute_section_scores(resume_text, r_tokens, set(), sections_found)
    weighted_score = compute_weighted_final_score(section_scores)

    wc        = len(resume_text.split())
    raw_ratio = len(r_tokens) / wc if wc else 0
    richness  = min(math.sqrt(raw_ratio / 0.65) * 98, 98.0)
    richness  = max(richness, 5.0)

    final = round(0.60 * weighted_score + 0.40 * richness, 1)

    diagnostics = structural_diagnostics(resume_text)
    tips        = generate_tips(resume_text, sections_found, set(), section_scores)

    return {
        "mode":           "health",
        "richness_score": final,
        "raw_richness":   round(raw_ratio * 100, 1),
        "unique_tokens":  len(r_tokens),
        "word_count":     wc,
        "sections":       sections_found,
        "section_scores": section_scores,
        "diagnostics":    diagnostics,
        "tips":           tips,
    }


def generate_tips(resume_text: str, sections: dict, gaps: set, section_scores: dict) -> list:
    tips = []

    # Section-specific tips based on scores
    for section, score in sorted(section_scores.items(), key=lambda x: x[1]):
        if score == 0:
            tips.append(f"Add a {section} section — ATS systems specifically look for this heading.")
        elif score < 50:
            tips.append(f"Strengthen your {section} section — it scores low on keyword density.")

    if not re.search(r"\d+\s*%|\$\s*\d+|\d+\s*\+?\s*(years?|months?|clients?|projects?)", resume_text, re.I):
        tips.append("Quantify achievements — numbers and percentages make a real difference.")

    if gaps and len(gaps) > 5:
        tips.append(f"Weave in missing keywords naturally — e.g.: {', '.join(list(gaps)[:5])}.")

    if len(resume_text.split()) < 300:
        tips.append("Expand your content. 400–600 words is the sweet spot for most ATS systems.")

    if not tips:
        tips.append("Resume looks solid! Keep tailoring it for each specific role — it pays off.")

    return tips[:5]  # cap at 5 tips


def generate_export(result: dict) -> str:
    mode  = result.get("mode", "full")
    lines = ["resumd — AUDIT REPORT", "=" * 42, ""]

    if mode == "full":
        lines += [
            f"Final Score    : {result['score']}%  {result['tier_emoji']} {result['tier_label']}",
            f"Coverage       : {result['coverage_pct']}%",
            f"Jaccard        : {result['jaccard_pct']}%",
            f"Matched Tokens : {result['token_count_matched']} of {result['token_count_jd']} JD keywords",
            "", "SECTION SCORES:",
        ]
        for s, sc in result["section_scores"].items():
            lines.append(f"  {s:<16} {sc}%")
        lines += [
            "", "KEYWORD MATCHES:",
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
            "SECTION SCORES:",
        ]
        for s, sc in result["section_scores"].items():
            lines.append(f"  {s:<16} {sc}%")
        lines.append("")

    lines += ["DIAGNOSTICS:"]
    for d in result["diagnostics"]:
        lines.append(f"  [{d['level'].upper()}] {d['message']}")

    lines += ["", "IMPROVEMENT SUGGESTIONS:"]
    for t in result["tips"]:
        lines.append(f"  → {t}")

    lines += [
        "", "─" * 42,
        "Generated by resumd.",
        "No resume data was stored or transmitted.",
        "Source: https://github.com/AryaBuwa/resumd",
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def purge_session():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()


# ─────────────────────────────────────────────
# CSS  (dark only — config.toml handles base)
# ─────────────────────────────────────────────

def inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }

.stApp, [data-testid="stAppViewContainer"] {
    background-color: #0f0f0f !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}
[data-testid="stHeader"] { background: transparent !important; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none !important; }

/* Inputs */
.stTextArea textarea {
    background-color: #141414 !important;
    color: #e8e8e8 !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
}
.stTextArea textarea:focus {
    border-color: #00d4aa !important;
    box-shadow: 0 0 0 2px #00d4aa22 !important;
}

/* File uploader */
[data-testid="stFileUploadDropzone"] {
    background-color: #141414 !important;
    border: 2px dashed #2a2a2a !important;
    border-radius: 8px !important;
}
[data-testid="stFileUploadDropzone"] small { display: none !important; }

/* Radio */
div[role="radiogroup"] label {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    background: #1a1a1a !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 6px !important;
    padding: 0.35rem 0.8rem !important;
    color: #e8e8e8 !important;
}
div[role="radiogroup"] label:hover { border-color: #00d4aa !important; }

/* Expander */
.streamlit-expanderHeader {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.82rem !important;
    background: #1a1a1a !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 6px !important;
    color: #888888 !important;
}
.streamlit-expanderContent {
    background: #1a1a1a !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 0 0 6px 6px !important;
}

/* Cards */
.ats-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    animation: fadeInUp 0.4s ease both;
}
.ats-card-accent { border-left: 3px solid #00d4aa; }

/* Score */
.score-number {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 4.5rem; font-weight: 600;
    color: #00d4aa; line-height: 1; text-align: center;
}
.score-label {
    font-size: 0.85rem; color: #888888; text-align: center;
    text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.3rem;
}
.score-tier {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1rem; font-weight: 500;
    color: #e8e8e8; text-align: center; margin-top: 0.4rem;
}
.score-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem; color: #888888;
    text-align: center; margin-top: 0.6rem;
}

/* Animated score bars */
.sbar-wrap {
    width: 100%; height: 8px; background: #2a2a2a;
    border-radius: 4px; margin: 0.4rem 0; overflow: hidden;
}
.sbar-fill {
    height: 100%; border-radius: 4px;
    animation: growBar 1.2s ease both;
    transform-origin: left;
}

/* Dashboard stat boxes */
.stat-box {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    border-radius: 8px; padding: 1rem; text-align: center;
}
.stat-val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.8rem; font-weight: 600; color: #00d4aa;
}
.stat-lbl {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem; color: #888888;
    text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.2rem;
}

/* Section score rows */
.sec-row {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.5rem 0; border-bottom: 1px solid #2a2a2a;
}
.sec-row:last-child { border-bottom: none; }
.sec-name {
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
    color: #888888; width: 110px; flex-shrink: 0; text-transform: uppercase;
}
.sec-bar-wrap { flex: 1; height: 6px; background: #2a2a2a; border-radius: 3px; overflow: hidden; }
.sec-bar-fill { height: 100%; border-radius: 3px; animation: growBar 1.2s ease both; transform-origin: left; }
.sec-pct {
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
    color: #e8e8e8; width: 38px; text-align: right; flex-shrink: 0;
}
.sec-status { font-size: 0.7rem; width: 60px; flex-shrink: 0; text-align: right; }

/* Keywords */
.keyword-grid { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
.kw-match {
    background: #0d2d1e; border: 1px solid #4caf50; color: #4caf50;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem;
    padding: 0.15rem 0.55rem; border-radius: 4px;
}
.kw-gap {
    background: #2d1010; border: 1px solid #f44336; color: #f44336;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.73rem;
    padding: 0.15rem 0.55rem; border-radius: 4px;
}

/* Diagnostics */
.diag-warning { background:#2d2200; border-left:3px solid #ff9800; padding:0.55rem 0.9rem; border-radius:0 6px 6px 0; margin-bottom:0.4rem; font-size:0.83rem; color:#e8e8e8; }
.diag-error   { background:#2d1010; border-left:3px solid #f44336; padding:0.55rem 0.9rem; border-radius:0 6px 6px 0; margin-bottom:0.4rem; font-size:0.83rem; color:#e8e8e8; }
.diag-info    { background:#0d1a2d; border-left:3px solid #2196f3; padding:0.55rem 0.9rem; border-radius:0 6px 6px 0; margin-bottom:0.4rem; font-size:0.83rem; color:#e8e8e8; }

/* Section badges */
.sbadge-found { display:inline-block; background:#0d2d1e; border:1px solid #4caf50; color:#4caf50; font-family:'IBM Plex Mono',monospace; font-size:0.68rem; padding:0.12rem 0.45rem; border-radius:4px; margin:0.12rem; text-transform:uppercase; letter-spacing:0.05em; }
.sbadge-miss  { display:inline-block; background:#0f0f0f; border:1px solid #2a2a2a; color:#555555; font-family:'IBM Plex Mono',monospace; font-size:0.68rem; padding:0.12rem 0.45rem; border-radius:4px; margin:0.12rem; text-transform:uppercase; letter-spacing:0.05em; text-decoration:line-through; }

/* Trust grid */
.trust-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:0.6rem; margin-top:0.75rem; }
.trust-item { background:#1e2d2a; border:1px solid #2a2a2a; border-radius:8px; padding:0.65rem 0.85rem; font-size:0.8rem; font-family:'IBM Plex Mono',monospace; color:#888888; display:flex; align-items:flex-start; gap:0.45rem; }
.trust-item .ti { color:#00d4aa; flex-shrink:0; }

/* Steps */
.steps-row { display:flex; gap:0.75rem; flex-wrap:wrap; margin-top:0.5rem; }
.step-item { flex:1; min-width:130px; background:#1a1a1a; border:1px solid #2a2a2a; border-radius:8px; padding:0.85rem; text-align:center; }
.step-num  { font-family:'IBM Plex Mono',monospace; font-size:1.4rem; font-weight:600; color:#00d4aa; }
.step-title { font-size:0.82rem; font-weight:500; color:#e8e8e8; margin-top:0.3rem; }
.step-desc  { font-size:0.73rem; color:#888888; margin-top:0.25rem; line-height:1.4; }

/* Tips */
.tip-item { display:flex; gap:0.5rem; align-items:flex-start; padding:0.45rem 0; border-bottom:1px solid #2a2a2a; font-size:0.83rem; color:#e8e8e8; }
.tip-item:last-child { border-bottom:none; }
.tip-icon { color:#00d4aa; flex-shrink:0; }

/* Hero */
.hero-title { font-family:'IBM Plex Mono',monospace; font-size:2rem; font-weight:600; color:#e8e8e8; line-height:1.2; }
.hero-accent { color:#00d4aa; }
.hero-sub { font-family:'IBM Plex Sans',sans-serif; font-size:0.95rem; color:#888888; margin-top:0.4rem; line-height:1.6; }
.mono-tag { font-family:'IBM Plex Mono',monospace; font-size:0.68rem; background:#1e2d2a; border:1px solid #2a2a2a; color:#00d4aa; padding:0.12rem 0.45rem; border-radius:3px; letter-spacing:0.05em; }
.section-label { font-family:'IBM Plex Mono',monospace; font-size:0.72rem; letter-spacing:0.1em; opacity:0.45; color:#e8e8e8; }
.ats-divider { border:none; border-top:1px solid #2a2a2a; margin:1.5rem 0; }

/* Animations */
@keyframes fadeInUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
@keyframes growBar  { from { transform:scaleX(0); } to { transform:scaleX(1); } }

::-webkit-scrollbar { width:5px; height:5px; }
::-webkit-scrollbar-track { background:#0f0f0f; }
::-webkit-scrollbar-thumb { background:#2a2a2a; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#00d4aa; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SVG LINE CHART
# ─────────────────────────────────────────────

def render_section_chart(section_scores: dict, sections_found: dict):
    """
    SVG line chart — X axis: sections, Y axis: ATS score 0-100.
    Shows resume score line vs ATS benchmark line.
    Dots at each section with score labels.
    """
    sections  = list(section_scores.keys())
    scores    = [section_scores[s] for s in sections]
    benchmarks = [SECTION_BENCHMARKS[s] for s in sections]
    n         = len(sections)

    W, H      = 680, 280
    pad_l, pad_r, pad_t, pad_b = 50, 30, 30, 60
    chart_w   = W - pad_l - pad_r
    chart_h   = H - pad_t - pad_b

    def x(i):   return pad_l + (i / (n - 1)) * chart_w
    def y(v):   return pad_t + (1 - v / 100) * chart_h

    # Build polyline points
    resume_pts    = " ".join(f"{x(i):.1f},{y(scores[i]):.1f}"    for i in range(n))
    benchmark_pts = " ".join(f"{x(i):.1f},{y(benchmarks[i]):.1f}" for i in range(n))

    # Build dots and labels for resume line
    dots = ""
    for i, (s, sc) in enumerate(zip(sections, scores)):
        cx    = x(i)
        cy    = y(sc)
        col   = score_color(sc)
        found = sections_found.get(s, False)
        # dot
        dots += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{col}" stroke="#0f0f0f" stroke-width="2"/>'
        # score label above dot
        label_y = cy - 12 if cy > pad_t + 20 else cy + 20
        dots += f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="11" fill="{col}">{sc}%</text>'

    # Benchmark dots (subtle)
    bench_dots = ""
    for i, bv in enumerate(benchmarks):
        cx = x(i)
        cy = y(bv)
        bench_dots += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="#888888" stroke="#0f0f0f" stroke-width="1.5"/>'

    # Y axis grid lines and labels
    grid = ""
    for val in [0, 25, 50, 75, 100]:
        gy = y(val)
        grid += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W - pad_r}" y2="{gy:.1f}" stroke="#2a2a2a" stroke-width="1"/>'
        grid += f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="10" fill="#555555">{val}</text>'

    # X axis labels
    xlabels = ""
    for i, s in enumerate(sections):
        cx = x(i)
        xlabels += f'<text x="{cx:.1f}" y="{H - 10}" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="10" fill="#888888">{s}</text>'

    svg = f"""
<div class="ats-card" style="padding:1.2rem;">
  <div class="section-label" style="margin-bottom:0.75rem;">SECTION PERFORMANCE vs ATS BENCHMARK</div>
  <svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;">
    <!-- Grid -->
    {grid}
    <!-- Benchmark line -->
    <polyline points="{benchmark_pts}" fill="none" stroke="#444444" stroke-width="1.5" stroke-dasharray="4,4"/>
    <!-- Resume line -->
    <polyline points="{resume_pts}" fill="none" stroke="#00d4aa" stroke-width="2.5"
              style="animation: none"/>
    <!-- Benchmark dots -->
    {bench_dots}
    <!-- Resume dots + labels -->
    {dots}
    <!-- X labels -->
    {xlabels}
    <!-- Legend -->
    <line x1="{pad_l}" y1="{H-28}" x2="{pad_l+20}" y2="{H-28}" stroke="#00d4aa" stroke-width="2.5"/>
    <text x="{pad_l+25}" y="{H-24}" font-family="IBM Plex Mono,monospace" font-size="10" fill="#888888">Your Resume</text>
    <line x1="{pad_l+120}" y1="{H-28}" x2="{pad_l+140}" y2="{H-28}" stroke="#444444" stroke-width="1.5" stroke-dasharray="4,4"/>
    <text x="{pad_l+145}" y="{H-24}" font-family="IBM Plex Mono,monospace" font-size="10" fill="#888888">ATS Benchmark</text>
  </svg>
</div>
"""
    st.markdown(svg, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────

def render_hero():
    st.markdown("""
<div class="hero-title">resum<span class="hero-accent">d</span></div>
<div class="hero-sub">
  Feed it your resume. Optionally, a job description. Get a straight-talking
  ATS compatibility report — processed entirely in-memory on the app server.
  No accounts. No persistent storage. No nonsense.
</div>
<br/>
<span class="mono-tag">v1.1.0</span>&nbsp;
<span class="mono-tag">ATS SCANNER</span>&nbsp;
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
      <div class="step-desc">Drop your PDF. Text extracted in-memory using PyMuPDF.</div>
    </div>
    <div class="step-item">
      <div class="step-num">02</div>
      <div class="step-title">Add JD (Optional)</div>
      <div class="step-desc">Paste the job description for a match score, or skip for a health check.</div>
    </div>
    <div class="step-item">
      <div class="step-num">03</div>
      <div class="step-title">Analyze</div>
      <div class="step-desc">Section-weighted scoring + keyword intersection — no AI black box.</div>
    </div>
    <div class="step-item">
      <div class="step-num">04</div>
      <div class="step-title">Review & Clear</div>
      <div class="step-desc">Read your report, export it, hit Purge — session discarded instantly.</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


def render_privacy_poc():
    st.markdown("""
<div class="ats-card ats-card-accent">
  <div class="section-label">DATA PRIVACY — PROOF OF CONCEPT</div>
  <div style="font-size:0.83rem; margin-top:0.6rem; line-height:1.6; opacity:0.8;">
    Your resume is processed in-memory on the server running this app.
    It is <b>never written to disk, retained in a database, sent to external APIs, or tracked.</b>
    Session data is discarded when the session expires or you hit Purge.
    Source code is public — verify every claim line by line.
  </div>
  <div class="trust-grid">
    <div class="trust-item"><span class="ti">✓</span><div><b>No persistent storage</b><br/>No database, no disk writes, no retention.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>No external processing APIs</b><br/>PDF parsed in-memory. Zero third-party transfer.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>No tracking or logging</b><br/>No analytics, no session recording by this app.</div></div>
    <div class="trust-item"><span class="ti">✓</span><div><b>Open source</b><br/>Every claim verifiable in the published code.</div></div>
  </div>
</div>
""", unsafe_allow_html=True)


def render_dashboard(result: dict):
    """Top stats dashboard — 4 key numbers at a glance."""
    mode = result.get("mode", "full")

    if mode == "full":
        main_score  = result["score"]
        matched     = result["token_count_matched"]
        total_jd    = result["token_count_jd"]
        coverage    = result["coverage_pct"]
        sections_found = sum(1 for v in result["sections"].values() if v)
        total_sections = len(result["sections"])

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{main_score}%</div>
  <div class="stat-lbl">Final Score</div>
</div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{matched}</div>
  <div class="stat-lbl">Keywords Matched</div>
</div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{coverage}%</div>
  <div class="stat-lbl">JD Coverage</div>
</div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{sections_found}/{total_sections}</div>
  <div class="stat-lbl">Sections Found</div>
</div>""", unsafe_allow_html=True)

    else:
        main_score  = result["richness_score"]
        unique_tok  = result["unique_tokens"]
        word_count  = result["word_count"]
        sections_found = sum(1 for v in result["sections"].values() if v)
        total_sections = len(result["sections"])

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{main_score}%</div>
  <div class="stat-lbl">Health Score</div>
</div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{unique_tok}</div>
  <div class="stat-lbl">Unique Tokens</div>
</div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{word_count}</div>
  <div class="stat-lbl">Total Words</div>
</div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""
<div class="stat-box">
  <div class="stat-val">{sections_found}/{total_sections}</div>
  <div class="stat-lbl">Sections Found</div>
</div>""", unsafe_allow_html=True)


def render_score_main(result: dict):
    mode = result.get("mode", "full")
    if mode == "full":
        score      = result["score"]
        tier_emoji = result["tier_emoji"]
        tier_label = result["tier_label"]
        meta       = f"{result['token_count_matched']} of {result['token_count_jd']} JD keywords matched &nbsp;·&nbsp; coverage {result['coverage_pct']}%"
        label      = "MATCH ANALYSIS SCORE"
    else:
        score      = result["richness_score"]
        tier_emoji = ""
        tier_label = "Resume Health Check"
        meta       = f"raw ratio {result['raw_richness']}% &nbsp;·&nbsp; {result['unique_tokens']} unique tokens"
        label      = "KEYWORD RICHNESS SCORE"

    st.markdown(f"""
<div class="ats-card" style="text-align:center; padding:2rem 1rem;">
  <div class="score-number">{score}%</div>
  <div class="score-label">{label}</div>
  <div class="sbar-wrap" style="margin:0.8rem auto; max-width:400px;">
    <div class="sbar-fill" style="width:{score}%; background:linear-gradient(90deg,#00a882,#00d4aa);"></div>
  </div>
  <div class="score-tier">{tier_emoji} {tier_label}</div>
  <div class="score-meta">{meta}</div>
</div>
""", unsafe_allow_html=True)


def render_section_bars(section_scores: dict, sections_found: dict):
    """Animated horizontal bars per section with status label."""
    rows = ""
    for section, score in section_scores.items():
        col   = score_color(score)
        found = sections_found.get(section, False)
        if not found:
            status = '<span style="color:#f44336;font-size:0.68rem;">MISSING</span>'
        elif score >= 75:
            status = '<span style="color:#00d4aa;font-size:0.68rem;">STRONG</span>'
        elif score >= 50:
            status = '<span style="color:#f59e0b;font-size:0.68rem;">FAIR</span>'
        else:
            status = '<span style="color:#f44336;font-size:0.68rem;">WEAK</span>'

        rows += f"""
<div class="sec-row">
  <div class="sec-name">{section}</div>
  <div class="sec-bar-wrap">
    <div class="sec-bar-fill" style="width:{score}%; background:{col};"></div>
  </div>
  <div class="sec-pct">{score}%</div>
  <div class="sec-status">{status}</div>
</div>"""

    st.markdown(f"""
<div class="ats-card">
  <div class="section-label" style="margin-bottom:0.75rem;">SECTION BREAKDOWN</div>
  {rows}
</div>""", unsafe_allow_html=True)


def render_explainability(mode: str, result: dict):
    if mode == "full":
        c = result.get("coverage_pct", "—")
        j = result.get("jaccard_pct",  "—")
        body = f"""
**How the score is calculated:**

Section scores (60% weight) — each resume section is scored individually on keyword density and JD overlap, then weighted by ATS importance (Skills 25%, Experience 30%, Projects 20%, etc.)

Keyword match score (40% weight) — Coverage ({c}%) and Jaccard similarity ({j}%) blended, square-root scaled.

```
final = 0.60 × section_weighted_score + 0.40 × keyword_score
```
Hard ceiling of 98% — a perfect score is a red flag.
"""
    else:
        body = f"""
**How the health score is calculated:**

Section scores (60% weight) — each section scored by keyword richness and density.

Vocabulary richness (40% weight):
```
raw_ratio = unique tokens ÷ total words
richness  = √(raw_ratio / 0.65) × 98
```
"""
    with st.expander("How was this score calculated?"):
        st.markdown(body)


def render_keywords(matched: list, gaps: list):
    mhtml = "".join(f'<span class="kw-match">{k}</span>' for k in matched[:60])
    ghtml = "".join(f'<span class="kw-gap">{k}</span>'   for k in gaps[:60])
    mn = f"<div style='font-size:0.7rem;opacity:0.4;margin-top:0.4rem;'>Top 60 of {len(matched)}</div>" if len(matched) > 60 else ""
    gn = f"<div style='font-size:0.7rem;opacity:0.4;margin-top:0.4rem;'>Top 60 of {len(gaps)}</div>"   if len(gaps)   > 60 else ""

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
    icons = {"warning": "⚠", "error": "✖", "info": "ℹ"}
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


def render_footer():
    st.markdown("""
<div style="border-top:1px solid #2a2a2a; padding:1.5rem 0 2.5rem; display:flex;
     justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-top:2rem;">
  <div style="font-family:'IBM Plex Mono',monospace; font-size:0.68rem; color:#555555;">
    resumd &nbsp;·&nbsp; v1.1.0 &nbsp;·&nbsp; zero data retained
  </div>
  <div style="font-family:'IBM Plex Mono',monospace; font-size:0.68rem; color:#555555;">
    built by &nbsp;<a href="https://github.com/AryaBuwa" target="_blank"
      style="color:#00d4aa; text-decoration:none; font-weight:500;
             border-bottom:1px solid #00d4aa;">Arya</a>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="resumd — ATS Resume Scanner",
        page_icon="📋",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    init_session()
    inject_css()

    render_hero()
    st.markdown("<br/>", unsafe_allow_html=True)
    render_how_it_works()
    st.markdown("<br/>", unsafe_allow_html=True)
    render_privacy_poc()
    st.markdown("<hr class='ats-divider'/>", unsafe_allow_html=True)

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
    st.markdown(
        '<div class="section-label" style="margin-bottom:0.3rem;">'
        'UPLOAD RESUME PDF &nbsp;·&nbsp; MAX 5 MB &nbsp;·&nbsp; PDF ONLY'
        '</div>',
        unsafe_allow_html=True
    )
    uploaded_file = st.file_uploader("resume_pdf", type=["pdf"], label_visibility="collapsed")

    jd_text = ""
    if mode == "full":
        st.markdown("<br/>", unsafe_allow_html=True)
        jd_text = st.text_area(
            "Paste Job Description",
            height=180,
            placeholder="Paste the full job description here. More detail → more accurate score.",
        )

    st.markdown("<br/>", unsafe_allow_html=True)

    col_run, col_purge = st.columns([3, 1])
    with col_run:
        run_clicked = st.button("▶  Run Analysis", use_container_width=True, type="primary")
    with col_purge:
        purge_clicked = st.button("✕  Purge", use_container_width=True)

    if purge_clicked:
        purge_session()

    if run_clicked:
        st.session_state.audit_result  = None
        st.session_state.error_message = None
        st.session_state.pdf_warnings  = []

        if uploaded_file is None:
            st.session_state.error_message = "No PDF uploaded. Please select a file to continue."
        elif uploaded_file.size > MAX_FILE_SIZE_BYTES:
            mb = uploaded_file.size / (1024 * 1024)
            st.session_state.error_message = f"File too large ({mb:.1f} MB). Limit is {MAX_FILE_SIZE_MB} MB."
        elif mode == "full" and len(jd_text.strip().split()) < MIN_JD_WORDS:
            wc = len(jd_text.strip().split())
            st.session_state.error_message = (
                f"Job description too short ({wc} words). "
                f"Paste at least {MIN_JD_WORDS} words, or switch to Resume Health Check."
            )
        else:
            file_bytes = uploaded_file.read()
            with st.spinner("Extracting and analyzing…"):
                resume_text, warnings = extract_pdf_text(file_bytes)

            st.session_state.pdf_warnings = warnings

            if not resume_text.strip():
                st.session_state.error_message = (
                    "No extractable text found. This PDF may be image-based. "
                    "Please use a digitally-created, text-selectable PDF."
                )
            else:
                st.session_state.resume_text = resume_text
                if mode == "full":
                    st.session_state.audit_result = run_full_audit(resume_text, jd_text)
                else:
                    st.session_state.audit_result = run_health_check(resume_text)

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

            # Dashboard
            render_dashboard(result)
            st.markdown("<br/>", unsafe_allow_html=True)

            # Main score
            render_score_main(result)

            # Explainability
            render_explainability(result.get("mode","full"), result)

            # SVG Line Chart
            render_section_chart(result["section_scores"], result["sections"])

            # Section breakdown bars
            render_section_bars(result["section_scores"], result["sections"])

            # Keywords (full mode only)
            mk = result.get("mode", "full")
            if mk == "full":
                render_keywords(result["matched_keywords"], result["gap_keywords"])

            # Diagnostics
            render_diagnostics(result["diagnostics"])

            # Tips
            render_tips(result["tips"])

            st.markdown("<br/>", unsafe_allow_html=True)
            st.download_button(
                label="↓  Download Full Report",
                data=generate_export(result),
                file_name="resumd_audit_report.txt",
                mime="text/plain",
            )

            st.markdown(
                '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;'
                'opacity:0.3;margin-top:0.4rem;text-align:center;">'
                'Session data is discarded when the session expires or you hit Purge.'
                '</div>',
                unsafe_allow_html=True
            )

    render_footer()


if __name__ == "__main__":
    main()