# 🛡️ CC-AI Smart Platform

**AI-Assisted Common Criteria (CC) Evaluation Platform** — automates ASE-class pre-auditing using a local LLM (Ollama), built for security evaluation labs working under **CEM:2022 Revision 1** / **ISO/IEC 18045:2022**.

> Fully **airgapped-capable** — no data ever leaves your machine. The AI model runs locally via [Ollama](https://ollama.com).

---

## ✨ What does it do?

Common Criteria evaluation is traditionally a slow, paper-heavy process: an evaluator manually reads a Security Target (ST) document — often 100+ pages — and fills in a workbook covering 77 CEM work units across 7 ASE families. This typically takes **7–10 working days**.

CC-AI Smart Platform automates the first pass of this process:

1. **Upload** a Security Target PDF.
2. A **local LLM** (Qwen2.5, recommended `qwen2.5:7b` or larger) reads the document and produces a verdict (PASS / FAIL / INCONCLUSIVE / N/A) for every work unit, with cited evidence and a confidence score.
3. An **inline validation engine** scores the audit's reliability (schema integrity, traceability, confidence, hallucination risk, consistency) and flags which work units actually need human review.
4. A human **Evaluator** reviews only the flagged items, overrides where needed, and pushes the result through a structured multi-role workflow (**Evaluator → Lead Evaluator → CB Auditor → Developer**) that mirrors a real CC lab's process — including Technical Meetings, Developer response tracking, and EOR (Evaluation Observation Report) generation.
5. **Workbook** and **EOR ** PDF reports are generated directly from the audit, ready to route through your lab's existing SOP.

In testing across 5 real-world TOEs (532 work units total), `qwen2.5:7b` achieved a 73% average PASS rate with 100% evidence traceability — turning a multi-day manual task into a 2–4 hour AI pass plus focused human review.

**This tool does not replace evaluator judgment.** It produces a structured, evidence-cited first draft so a qualified CC evaluator can spend their time on the units that actually need expert review.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Prerequisites & Minimum Specs](#-prerequisites--minimum-specs)
- [Installation](#-installation)
- [Installing Ollama and Pulling a Model](#-installing-ollama-and-pulling-a-model)
- [Running the Platform](#-running-the-platform)
- [Step-by-Step Usage Tutorial](#-step-by-step-usage-tutorial)
- [Role Workflow Explained](#-role-workflow-explained)
- [Model Recommendations](#-model-recommendations)
- [Troubleshooting](#-troubleshooting)
- [Data & Privacy](#-data--privacy)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## 🚀 Features

- **AI Pre-Audit Engine** — 77 work units across ASE_CCL.1, ASE_ECD.1, ASE_INT.1, ASE_OBJ.2, ASE_SPD.1, ASE_REQ.2, ASE_TSS.1, fully aligned to CEM:2022 R1.
- **Deterministic shortcuts** — ASE_CCL.1 and ASE_ECD.1 sub-units are resolved without calling the LLM when no PP conformance or extended components are claimed, saving time and avoiding unnecessary model variance.
- **5 "Junior RCC Evaluator" prompting skills** — Grounding Anchor (forces page citations), Negative Space Awareness, Chain-of-Thought forcing, Semantic Similarity Guard, and Confidence Calibration — designed to reduce hallucination versus naive LLM prompting.
- **Inline Validation Engine** — automatic scoring (Schema 15 + Completeness 20 + Traceability 25 + Confidence 15 + Hallucination Risk 15 + Consistency 10 = 100) with a READY / REVIEW / REJECT verdict and per-family review-priority breakdown.
- **Multi-role Kanban workflow** — Evaluator, Lead Evaluator, CB Auditor, and Developer each get a tailored dashboard.
- **Collaborative EOR Workspace** — Lead Evaluator can comment, override, and attach evidence images inline.
- **Technical Meeting (TM1/TM2) management** — scheduling, minutes, and deadline tracking for CB Auditor coordination with developers.
- **Developer Dashboard** — structured, append-only Sponsor/Developer Action + Evaluator Action threads (matches the official CC EOR resolution format).
- **PDF report generation** — Workbook and EOR  generated directly from audit results, ready for your lab's sign-off process.
- **100% local / airgapped-capable** — no external API calls; all AI inference happens via your local Ollama instance.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Streamlit Web App (app.py)               │
│  ┌───────────────┐  ┌────────────────┐  ┌──────────────┐  │
│  │  PDF Extractor │→ │  AI Audit Loop  │→ │  Validation   │  │
│  │  (pdfplumber)  │  │  (77 work units)│  │  Engine       │  │
│  └───────────────┘  └────────┬────────┘  └──────────────┘  │
│                               │ HTTP                        │
│                               ▼                              │
│                    ┌─────────────────────┐                  │
│                    │   Ollama (local)     │                  │
│                    │   qwen2.5:7b / 14b    │                  │
│                    └─────────────────────┘                  │
│  ┌───────────────────────────────────────────────────────┐ │
│  │   Role-based Workflow: Evaluator → Lead → CB → Dev     │ │
│  │   (Kanban, EOR Workspace, TM Management, PDF export)   │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
        Data persisted as JSON in ./cc_ai_data/ (local disk)
```

This is currently a **monolithic Streamlit application** by design — it's meant to be easy to run on a single evaluator workstation or lab server with zero external dependencies. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a discussion of scaling this to a multi-user enterprise architecture (FastAPI + PostgreSQL + React).

---

## 💻 Prerequisites & Minimum Specs

### Software

| Component | Minimum Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.11 recommended |
| Ollama | Latest | https://ollama.com/download |
| OS | Windows 10/11, macOS 12+, or Linux | GPU acceleration works on all three via Ollama |

### Hardware — by model size

The platform's speed and AI audit quality depend heavily on which Ollama model you run. Below are realistic minimums based on internal testing.

| Model | Parameters | Min RAM (CPU-only) | Recommended GPU VRAM | Approx. audit time (77 WU) | Quality notes |
|---|---|---|---|---|---|
| `qwen2.5:7b` | 7B | 16 GB | 6–8 GB (e.g. RTX 3060) | 1.5–3 hours | **Recommended minimum.** Empirically: ~73% PASS rate, 100% evidence traceability, low hallucination risk. |
| `qwen2.5:14b` | 14B | 32 GB | 12–16 GB (e.g. RTX 4070 Ti / 3090) | 3–5 hours | Higher accuracy on harder families (ASE_OBJ.2, ASE_TSS.1). Use if hardware allows. |
| `qwen2.5:32b` | 32B | 64 GB | 24 GB+ (e.g. RTX 4090, A6000) | 6–10 hours | Best accuracy; only worth it for high-stakes EAL4+ evaluations with time to spare. |

> ⚠️ **Not recommended:** `deepseek-r1:8b` and other reasoning-tuned models were tested and showed significantly worse results for this use case (lower PASS rates, higher hallucination risk) — they are optimized for math/coding chain-of-thought, not long-document evidence extraction. Stick to the Qwen2.5 family for ASE auditing.

### Without a dedicated GPU

CPU-only inference works but is slow — expect 4–8x longer audit times than the GPU estimates above. A modern multi-core CPU (8+ cores) with 16–32 GB RAM can still complete a `qwen2.5:7b` audit overnight.

### Disk space

- Ollama + `qwen2.5:7b` model: ~5 GB
- Ollama + `qwen2.5:14b` model: ~9 GB
- Python environment + dependencies: ~1 GB
- Audit data (JSON, uploaded PDFs): grows per project, typically a few MB per evaluation

---

## 📦 Installation

### 1. Clone this repository

```bash
git clone https://github.com/<your-username>/cc-ai-smart-platform.git
cd cc-ai-smart-platform
```

### 2. Create a Python virtual environment (recommended)

```bash
python3 -m venv venv

# Activate it:
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows (PowerShell or cmd)
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## 🤖 Installing Ollama and Pulling a Model

### Step 1 — Install Ollama

Visit **https://ollama.com/download** and download the installer for your OS, or use the CLI:

**macOS / Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:** download and run the `.exe` installer from the Ollama website.

### Step 2 — Verify Ollama is running

```bash
ollama --version
```

Ollama runs as a background service automatically after install (listening on `http://localhost:11434` by default).

### Step 3 — Pull the recommended model

```bash
ollama pull qwen2.5:7b
```

This downloads roughly 4.7 GB. For better accuracy if your hardware supports it:

```bash
ollama pull qwen2.5:14b
```

### Step 4 — Confirm the model is available

```bash
ollama list
```

You should see `qwen2.5:7b` (or whichever model you pulled) in the output.

### Step 5 — Quick sanity test (optional)

```bash
ollama run qwen2.5:7b "Reply with exactly the word: OK"
```

If you get a response, Ollama and the model are working correctly.

---

## ▶️ Running the Platform

With your virtual environment activated and Ollama running in the background:

```bash
streamlit run app.py
```

This opens the platform in your browser at `http://localhost:8501`.

> 💡 **Airgapped deployment:** once the model is pulled, Ollama and this app run entirely offline. You can disconnect from the internet after the initial setup — no Security Target content or audit data ever leaves your machine.

---

## 📖 Step-by-Step Usage Tutorial

### 1. Log in

The platform ships with demo credentials for each role (see `app.py` — change these before any real deployment). Select your role: **Evaluator**, **Lead Evaluator**, **CB Auditor**, or **Developer**.

### 2. (Evaluator) Configure the audit

In the sidebar under **Audit Config**:
- **Model**: select your pulled Ollama model (e.g. `qwen2.5:7b`)
- **Max Pages**: limit how many ST pages to process (useful for very large documents)
- Skill toggles: leave Chain-of-Thought, Negative Space Awareness, Semantic Guard, and Confidence Calibration **enabled** — these meaningfully reduce hallucination.

### 3. Upload & Audit ST

Go to **Upload & Audit ST**, upload your Security Target PDF, fill in TOE name/version/EAL, and click **Start AI Audit**. Progress is shown live as each of the 77 work units is processed.

> 77 work units at `qwen2.5:7b` typically takes **1.5–3 hours** depending on your hardware and ST length. Keep the browser tab open during the audit — it runs synchronously in this version.

### 4. Review the Validation Score

Once the audit completes, an inline **Validation Score** panel appears showing a READY / REVIEW / REJECT verdict, a breakdown by scoring dimension, and a per-family review-priority table. Use this to decide where to focus your manual review.

### 5. Human Review & Override

In **Hasil Audit**, go through work units flagged for review (low confidence, INCONCLUSIVE, or high-priority family). Override the verdict where your expert judgment differs from the AI, attaching evidence images as needed.

### 6. Generate Workbook & EOR

Go to **Generate EOR** → choose the **Workbook** tab to download a -formatted PDF of all 77 work units, or the **EOR** tab to generate an formatted Evaluation Observation Report from your FAIL/INCONCLUSIVE findings.

### 7. Push to Lead Evaluator

Once satisfied, push the audit to the **Lead Evaluator** role for their review cycle.

### 8. (Lead Evaluator) Review & Approve

Switch to the Lead Evaluator role. In **EOR Workspace**, review the Evaluator's work, leave comments, override if needed, and either **Approve** (sends to CB Auditor) or **Request Revision** (sends back to Evaluator, max one cycle).

### 9. (CB Auditor) Technical Meeting & Push to Developer

As CB Auditor, schedule a **TM1** (lab-only clarification) or **TM2** (lab + CB + developer) meeting, record minutes, and push findings to the Developer once ready.

### 10. (Developer) Respond to Findings

As Developer (typically accessed externally), open **My Findings**, review the Issue Description for each finding, and submit a **Sponsor/Developer Action** with supporting evidence.

### 11. (Evaluator/Lead) Verify Fix

Back in the Evaluator or Lead role, review the Developer's response in **Manage Dev Findings**, and mark each finding as **FIXED** or **REISSUE**.

---

## 👥 Role Workflow Explained

```
Cycle 1: Evaluator
   → AI Pre-Audit (Ollama) → Human Override → Validation Score
   → Push to Lead Evaluator

Cycle 2: Lead Evaluator
   → EOR Workspace review
   → Accept (→ CB Auditor)  OR  Request Revision (→ Evaluator, max 1x)

Cycle 3: CB Auditor
   → TM1 (Lab only)  OR  TM2 (Lab + CB + Developer)
   → CB writes Issue Description (immutable once set)
   → Push findings to Developer

Cycle 4: Developer
   → Reviews findings (My Findings, unlocked after TM2)
   → Submits Sponsor/Developer Action + evidence (append-only)
   → Evaluator/Lead reviews → marks FIXED or REISSUE
```

This mirrors a real CC lab process and is designed to slot into existing SOPs (e.g. BSSN's `SOP.MT.04 Layanan Pengujian`) as a tooling layer — it does not replace formal sign-offs, BAST, or LSPro review steps.

---

## 🧠 Model Recommendations

Based on empirical testing across 5 real-world TOEs (532 total work units):

| Model | Avg. PASS Rate | Avg. Confidence | Evidence Traceability | High Hallucination Risk |
|---|---|---|---|---|
| `qwen2.5:7b` | ~73% | 0.83 | 100% | ~4.5% |
| `deepseek-r1:8b` | ~35% | 0.64 | 100% | ~22% (**not recommended**) |

**Recommendation:** default to `qwen2.5:7b` or larger Qwen2.5 variants. Avoid reasoning-tuned models (DeepSeek-R1 family) for this document-evidence-extraction task — they were designed and tuned for a different kind of reasoning.

---

## 🔧 Troubleshooting

**"Connection refused" / Ollama not reachable**
Make sure Ollama is running: `ollama serve` (if not already running as a background service), and that it's listening on `http://localhost:11434`.

**Audit results show many INCONCLUSIVE / red flags**
Check that:
1. You're using `qwen2.5:7b` or better (not a reasoning model).
2. Your ST PDF is text-based, not a scanned image (this tool does not do OCR).
3. Try increasing context by reducing "Max Pages" filtering if your ST is very long and content is being cut off.

**Audit is extremely slow**
Confirm you have a GPU available to Ollama (`ollama ps` while a model is loaded should show GPU usage). CPU-only inference is expected to be much slower — see the hardware table above.

**`reportlab` import error when generating Workbook/EOR PDFs**
Run `pip install reportlab` (it should already be in `requirements.txt`, but confirm your venv is activated).

**Streamlit shows a blank page or errors on startup**
Confirm your Python version is 3.10+ and that all dependencies installed successfully (`pip list` to check).

---

## 🔒 Data & Privacy

- All AI inference happens via your **local** Ollama instance — no Security Target content, audit results, or evaluation data is sent to any external API or cloud service.
- Audit data is persisted as JSON files under `./cc_ai_data/` on local disk.
- This makes the platform suitable for **airgapped environments** handling sensitive/confidential evaluation material, subject to your own organization's security review.
- **Before any production or sensitive use:** review and replace the demo credentials in `app.py`, and evaluate whether the current authentication mechanism meets your organization's security requirements (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for hardening recommendations).

---

## 📁 Project Structure

```
cc-ai-smart-platform/
├── app.py                  # Main Streamlit application (single-file monolith)
├── requirements.txt        # Python dependencies
├── README.md                # This file
├── LICENSE
├── .gitignore
├── .streamlit/
│   └── config.toml          # Streamlit theme/server config
├── docs/
│   └── ARCHITECTURE.md      # Notes on scaling beyond the monolith
├── assets/                  # (placeholder for screenshots / logos)
└── cc_ai_data/               # Created at runtime — local audit data (gitignored)
```

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome. Please open an issue describing the change before submitting a large pull request. Given the regulatory/compliance context of this tool, please:

- Clearly document any change to the scoring/validation formulas.
- Keep CEM:2022 R1 work unit references accurate when modifying the audit engine.
- Avoid introducing any external network calls to the AI audit path — local-only inference is a core design constraint.

---

## 📄 License

This project is released under the [MIT License](LICENSE) unless your organization requires otherwise — update this section and the `LICENSE` file to match your institution's policy before publishing.

---

## ⚠️ Disclaimer

This tool produces an **AI-generated first-pass draft** for Common Criteria evaluation work units. It is intended to **assist**, not replace, a qualified CC evaluator. All AI-generated verdicts must be reviewed and, where appropriate, overridden by a human evaluator with the relevant CC/CEM qualifications before being used in any formal certification deliverable. The maintainers make no warranty regarding the correctness of AI-generated verdicts and accept no liability for evaluation outcomes based on unreviewed AI output.
