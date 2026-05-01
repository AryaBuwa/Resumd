# resumd

> An ATS-friendly resume scanner that respects your privacy.

**[Live App →](https://resumd.streamlit.app)**

---

## What is this?

Most ATS scanners ask you to create an account, store your resume, and quietly send your data to third-party services. Resumd doesn't.

You upload your resume. It gets scanned in-memory on the app server. You get a score. The session expires and it's gone.

No persistent storage. No retention. No account. No black box.

---

## Features

- **Full Audit** — Upload your resume + paste a job description. Get a keyword match score, verified matches, knowledge gaps, and improvement suggestions.
- **Resume Health Check** — No JD needed. Get a structural analysis, section detection, formatting diagnostics, and keyword richness score.
- **Honest Scoring** — Blended coverage + Jaccard similarity formula with square-root scaling. Strong resumes score fairly, not brutally.
- **Section Detection** — Checks for Experience, Education, Skills, Summary, Projects, Certifications, Achievements.
- **Formatting Diagnostics** — Flags ATS parsing risks like image-based PDFs, missing contact info, decorative characters, multi-column layouts.
- **Export Report** — Download a plain `.txt` audit report generated entirely from session memory.
- **Dark / Light Mode** — Because your eyes matter.
- **Purge Session** — One click discards everything immediately.

---

## Privacy Model

This is not a marketing claim. It is verifiable in the source code.

| Claim | Accurate wording |
|---|---|
| Processing | Runs in-memory on the app server — not browser-side, not client-side |
| Storage | No persistent storage or retention of any kind |
| External services | No external processing APIs or tracking services |
| Session data | Discarded when the session expires or is purged |
| Logging | No analytics, no session recording, no fingerprinting by this app |

> **Note:** Streamlit's own infrastructure may maintain standard server logs outside the control of this app. This app itself performs no logging, tracking, or data retention.

The only external call is loading the IBM Plex font from Google Fonts — a stylesheet, not your data.

---

## How the Score Works

### Full Audit Score

Two signals, blended honestly:

- **Coverage** — what % of the job description's unique keywords appear in your resume *(70% weight)*
- **Jaccard Similarity** — shared keywords ÷ total unique keywords across both documents *(30% weight)*

```
blended       = (0.70 × coverage) + (0.30 × jaccard)
display_score = √blended × 98
```

The square-root stretch means covering 50% of a JD lands you ~70%, not 50% — because that's genuinely good alignment. Hard ceiling of 98%.

### Resume Health Score

```
raw_ratio     = unique meaningful tokens ÷ total words
display_score = √(raw_ratio / 0.65) × 98
```

A well-written resume with ~47% raw vocabulary diversity displays as ~73%. Honest, not punishing.

---

## Tech Stack

| Layer | Tool |
|---|---|
| UI Framework | [Streamlit](https://streamlit.io) |
| PDF Extraction | [PyMuPDF](https://pymupdf.readthedocs.io) (fitz) |
| NLP | Hardcoded stop words + custom suffix stemmer |
| Storage | `st.session_state` only — no persistence |
| Styling | Custom CSS injected via `st.markdown` |
| Deployment | [Streamlit Community Cloud](https://streamlit.io/cloud) |

No external NLP libraries. No NLTK. No network calls for processing.

---

## Run Locally

```bash
# Clone the repo
git clone https://github.com/[your-handle]/resumd
cd resumd

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

When running locally, your PDF never leaves your machine at all.

---

## File Structure

```
resumd/
├── app.py
├── requirements.txt
└── README.md
```

---

## Limitations

- **Image-based / scanned PDFs** will not work — ATS systems can't read them either, so this is by design.
- **Score is keyword-based** — it measures vocabulary overlap, not quality of experience or writing.
- **Stemming is heuristic** — a lightweight custom stemmer is used. Edge cases exist.
- **Hosted version** processes your PDF on Streamlit's servers in volatile memory. For zero network exposure, run locally.
- **Session timing** — session data is discarded on expiry or purge. Streamlit's session lifecycle controls exact timing, not this app.

---

## Contributing

PRs welcome. If you find a bug, open an issue. If you want to improve the scoring logic or add a feature, fork it and go.

Please don't add external APIs, databases, or anything that compromises the stateless privacy model. That's the whole point.

---

## Usage & Disclaimer

**Educational Use Only**
This project is provided for educational and personal portfolio demonstration. You may fork this repository for learning purposes; however, redistribution or commercial use without explicit permission is prohibited.

**Warranty Disclaimer**
The software is provided "as is" without warranty of any kind. The author assumes no responsibility for data loss or damages resulting from use of this application. Use at your own discretion.

---

## Acknowledgements

Built with the assistance of AI tools.
Scoring logic, privacy architecture, and design decisions are my own.

---

<div align="center">
  <sub>Built by <a href="https://github.com/[your-handle]">Arya</a> · No persistent storage · Ever.</sub>
</div>