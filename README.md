# resumd

> A stateless, privacy-first ATS resume scanner. No data stored. No APIs called. No nonsense.

**[Live App →](https://resumd.streamlit.app)**

---

## What is this?

Most ATS scanners ask you to create an account, store your resume, and quietly send your data to third-party services. Resumd doesn't.

You upload your resume. It gets scanned in memory. You get a score. It's gone.

No database. No logging. No account. No black box.

---

## Features

- **Full Audit** — Upload your resume + paste a job description. Get a keyword match score, verified matches, knowledge gaps, and improvement suggestions.
- **Resume Health Check** — No JD needed. Get a structural analysis, section detection, formatting diagnostics, and keyword richness score.
- **Honest Scoring** — Blended coverage + Jaccard similarity formula with square-root scaling. Strong resumes score fairly, not brutally.
- **Section Detection** — Checks for Experience, Education, Skills, Summary, Projects, Certifications, Achievements.
- **Formatting Diagnostics** — Flags ATS parsing risks like image-based PDFs, missing contact info, decorative characters, multi-column layouts.
- **Export Report** — Download a plain `.txt` audit report generated entirely from session memory.
- **Dark / Light Mode** — Because your eyes matter.
- **Purge Session** — One click wipes everything. No traces.

---

## Privacy Model

This is not a marketing claim. It is verifiable in the source code.

| Claim | Where to verify |
|---|---|
| No database writes | Search the codebase for any DB import — you won't find one |
| No third-party API calls | `Ctrl+F` for `requests`, `httpx`, `urllib` — zero results |
| No file logging | No `open()`, no `write()`, no temp files |
| PDF parsed in memory | `fitz.open(stream=file_bytes)` — RAM only, never disk |
| Session state only | All data lives in `st.session_state`, cleared on purge or tab close |

The only external call is loading the IBM Plex font from Google Fonts — a stylesheet, not your data.

---

## How the Score Works

### Full Audit Score

Two signals, blended honestly:

- **Coverage** — what % of the job description's unique keywords appear in your resume *(70% weight)*
- **Jaccard Similarity** — shared keywords ÷ total unique keywords across both documents *(30% weight)*

```
blended      = (0.70 × coverage) + (0.30 × jaccard)
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
| PDF Extraction | [PyMuPDF (fitz)](https://pymupdf.readthedocs.io) |
| NLP | Hardcoded stop words + custom suffix stemmer |
| Storage | `st.session_state` only — zero persistence |
| Styling | Custom CSS injected via `st.markdown` |
| Deployment | [Streamlit Community Cloud](https://streamlit.io/cloud) |

No external NLP libraries. No NLTK. No spaCy. No network calls for processing.

---

## Run Locally

```bash
# Clone the repo
git clone https://github.com/AryaBuwa/resumd
cd resumd

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

When running locally, your PDF never leaves your machine at all. Not even to Streamlit's servers.

---

## File Structure

```
resumd/
├── app.py            # entire application — one file, fully commented
├── requirements.txt  # streamlit, pymupdf — nothing else
└── README.md
```

---

## Limitations

- **Image-based / scanned PDFs** will not work — ATS systems can't read them either, so this is by design.
- **Score is keyword-based** — it measures vocabulary overlap, not quality of experience or writing.
- **Stemming is heuristic** — a lightweight custom stemmer is used instead of NLTK to keep the app fully offline-capable. Edge cases exist.
- **Hosted version** processes your PDF on Streamlit's servers in volatile memory. If you want zero network exposure, run it locally.

---

## Contributing

PRs welcome. If you find a bug, open an issue. If you want to improve the scoring logic or add a feature, fork it and go.

Please don't add external API calls, databases, or anything that compromises the stateless privacy model. That's the whole point.

---

## Acknowledgements

Built with the assistance of AI tools.
Scoring logic, privacy architecture, and design decisions are my own.

--- 

## License

MIT — use it, fork it, learn from it.

---

<div align="center">
  <sub>Built by <a href="https://github.com/AryaBuwa ">Arya</a> · No data retained · Ever.</sub>
</div>