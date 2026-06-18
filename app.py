"""
CC-AI Smart Platform v2.0 FINAL
================================
SMART CC EVALUATION BASED AI PLATFORM — COMPLETE BUILD

CYCLE FLOW:
  Cycle 1 : Evaluator → AI Audit → Human Review → Push to Lead
  Cycle 2 : Lead Review → Accept/Revision → Push to CB
  Cycle 3 : CB → TM1 (Lab only) or TM2 (Lab+CB+Dev) → Push Findings to Dev
  Cycle 4 : Dev → Resolve Findings → Evaluator Action → FIXED/REISSUE

NEW in FINAL v2.0:
[JSON] Persistent JSON storage — EOR/findings survive server restart
[EOR]  EOR Observation format matches official CC template:
         NO | CC COMPONENT ELEMENTS | EVALUATION REFERENCE |
         ISSUE DESCRIPTION | RESOLUTION (append-only) | STATUS
[CB]   CB writes Issue Description per finding after TM2 — immutable
[DEV]  Dev Dashboard unlocked after CB push TM2 findings
[DEV]  Dev: Sponsor/Developer Action (append-only) + attach evidence
[DEV]  Dev push response → email sim + notif CB + Lead + Evaluator
[EVAL] Evaluator Action (append-only) after Dev response
[EVAL] Evaluator sets STATUS: FIXED (EOR Resolved) or REISSUE
[EOR]  EOR PDF export matches CC Observation table format
[EMAIL] Email simulation — displayed in UI as sent notification

CHANGELOG v1.0 → v2.0:
[A1] Evaluator: Human override inline — form diganti display langsung, tidak muncul form lagi setelah save
[A1] Evaluator: Attach multi-image evidence per work unit (untuk meyakinkan Lead)
[A2] Evaluator Kanban: 3 status jelas DRAFT/ON PROGRESS/DONE dengan warna berbeda
[A2] Evaluator Kanban: Tombol "Push to Lead" langsung dari Kanban card saat review selesai
[A3] Hasil Audit: Diperjelas flow — hasil audit terhubung langsung ke Generate EOR dan Kanban
[A5] Push ke Lead saja — tidak lagi ke CB dan Developer (belum waktunya Cycle 1)
[A5] Saat Push, Kanban otomatis update ke "ON REVIEW TO LEAD"
[B1] Lead EOR Workspace: Disederhanakan — CEM Ref dihapus, Justification inline dihapus
[B1] Lead: Comment + Attach Artefact + Override disatukan dalam 1 submit action
[B1] Lead aksi: " → Push to Evaluator" dan "Accept All → Push to CB"
[B1] Kanban update otomatis dari Lead action
[C] Manage Dev Findings: Kosong di Cycle 1, dibuka hanya setelah TM2 dari CB
[D] Timeline: Opsi assign evaluator dengan deadline, notif ke evaluator dashboard
[D] Timeline Developer: Kosong di Cycle 1, aktif setelah TM2
[E] Notifikasi: Format SPOK — Siapa | Aksi | Objek | Keterangan | Waktu
[CB] CB: Dua opsi TM (TM1=konfirmasi Lab, TM2=Lab+CB+Dev), bukan langsung approve
[CB] CB Kanban: 3 status ON_REVIEW_CB | TM_SCHEDULED | APPROVED
[Dev] Developer: My Findings dikunci sampai setelah TM2 dari CB

Features
── KANBAN BOARD  ──────────────────────────────────────
  5-column board: DRAFT → IN_AUDIT → UNDER_REVIEW → REVISION → APPROVED/CLOSED
  Each column shows EOR cards with:
    - TOE name, EAL, assignee, finding count (FAIL/INC)
    - Due date with overdue highlight
    - Progress bar (units reviewed / total)
    - Burndown indicator (days remaining vs findings open)
  One-click move between columns (no drag needed on mobile)
  Auto-notification on column change to relevant role
  Daily target tracker: target units/day vs actual completed

── DEV FINDING TRACKER (new role: developer) ──────────────────────────────────
  Developer sees ONLY their assigned findings (FAIL/INC units)
  Per-finding card shows:
    - Work unit ID + CEM reference + requirement text
    - AI evidence verbatim + Lead comment/justification
    - Response form: Developer reply + ST section reference + page number
    - Attachment reference: which ST section was updated/corrected
    - Status: OPEN → IN_PROGRESS → RESPONDED → VERIFIED → CLOSED
    - Due date per finding (set by Lead Evaluator)
    - Response history thread
  Lead can VERIFY or REJECT developer response inline
  Evaluator gets notification when dev responds → can re-audit that specific unit
  Burndown chart: open findings vs days elapsed per EOR

── PROJECT TIMELINE ───────────────────────────────────────────────────────────
  Gantt-style view: all active EORs with start/end/current day marker
  Per-role workload: how many open tasks per person
  SLA indicator: red if overdue, yellow if <3 days remaining

ROLES:
  evaluator      → Upload ST → AI Audit → EOR → Push to Kanban → Re-audit on dev response
  lead_evaluator → Kanban board → EOR Workspace → Assign findings to Dev → Verify responses
  developer      → My Findings → Respond → Attach ST sections → Track per finding
  cb_auditor     → Project Timeline → Approve final → Schedule TM → Record minutes

DEPENDENCIES:
  pip install streamlit pdfplumber requests reportlab plotly pandas
"""

import streamlit as st
import pdfplumber
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json, requests, re, io, base64, random, time, os, shutil, pathlib, html
import re
from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime, date, timedelta
from io import BytesIO

# ============================================================
# ASE WORK UNIT REGEX ENGINE
# ============================================================

WORK_UNIT_REGEX = re.compile(
    r"(ASE_[A-Z]+(?:\\.[0-9]+)+(?:-[0-9]+))"
)

COMPONENT_REGEX = re.compile(
    r"(ASE_[A-Z]+\\.[0-9]+\\.[0-9]+[A-Z])"
)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False


# ═══════════════════════════════════════════════════════════════════════════
# JSON PERSISTENT STORAGE
# ═══════════════════════════════════════════════════════════════════════════
DATA_DIR = pathlib.Path("./cc_ai_data")
EOR_DIR  = DATA_DIR / "eor"
UPL_DIR  = DATA_DIR / "uploads"

def ensure_dirs():
    for d in [DATA_DIR, EOR_DIR, UPL_DIR]: d.mkdir(parents=True, exist_ok=True)

ensure_dirs()

def _eor_path(eor_id: str) -> pathlib.Path:
    return EOR_DIR / f"{eor_id}.json"

def save_eor(eor: dict):
    """Persist EOR dict to JSON file."""
    try:
        _eor_path(eor["id"]).write_text(
            json.dumps(eor, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:
        pass  # degrade gracefully

def load_eor(eor_id: str) -> dict:
    p = _eor_path(eor_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

def delete_eor_permanently(eor_id: str):
    """Hapus EOR dari disk (JSON + uploads) dan memory."""
    # Hapus file JSON
    eor_path = _eor_path(eor_id)
    if eor_path.exists():
        eor_path.unlink()
    
    # Hapus folder uploads
    upload_folder = UPL_DIR / eor_id
    if upload_folder.exists():
        import shutil
        shutil.rmtree(upload_folder)
    
    # Hapus dari session state
    st.session_state.eor_backlog = [e for e in st.session_state.eor_backlog if e.get("id") != eor_id]
    st.session_state.workspace_comments.pop(eor_id, None)
    st.session_state.workspace_artefacts.pop(eor_id, None)
    if eor_id in st.session_state.dev_findings:
        del st.session_state.dev_findings[eor_id]
    
    return True

def load_all_eors() -> list:
    eors = []
    for p in sorted(EOR_DIR.glob("*.json")):
        try: eors.append(json.loads(p.read_text(encoding="utf-8")))
        except: pass
    return eors

def sync_eor_backlog():
    """Merge persisted EORs into session_state.eor_backlog (dedup by id)."""
    persisted = load_all_eors()
    existing_ids = {e["id"] for e in st.session_state.eor_backlog}
    for e in persisted:
        if e["id"] not in existing_ids:
            st.session_state.eor_backlog.append(e)
            existing_ids.add(e["id"])
    # Also update existing entries from disk (disk wins for resolution data)
    for i, eor in enumerate(st.session_state.eor_backlog):
        disk = load_eor(eor["id"])
        if disk:
            # Sync everything from disk so that memory completely matches disk perfectly
            for k, v in disk.items():
                eor[k] = v

def save_upload(eor_id: str, uid: str, filename: str, data: bytes) -> str:
    """Save uploaded file to disk. Returns relative path."""
    d = UPL_DIR / eor_id / uid
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]","_", filename)
    p = d / safe
    p.write_bytes(data)
    return str(p)

def list_uploads(eor_id: str, uid: str) -> list:
    d = UPL_DIR / eor_id / uid
    if not d.exists(): return []
    return [{"name": f.name, "path": str(f), "size": f.stat().st_size}
            for f in sorted(d.iterdir()) if f.is_file()]

def _attachment_image_bytes(att):
    """Return image bytes from persisted attachment metadata or legacy raw bytes."""
    try:
        if isinstance(att, bytes):
            return att
        if isinstance(att, bytearray):
            return bytes(att)
        if isinstance(att, dict):
            raw = att.get("bytes")
            if isinstance(raw, bytes):
                return raw
            if isinstance(raw, bytearray):
                return bytes(raw)
            if isinstance(raw, str) and raw.startswith("data:image/"):
                return base64.b64decode(raw.split(",", 1)[1])
            path = att.get("path")
            if path:
                p = pathlib.Path(path)
                if p.exists() and p.is_file():
                    return p.read_bytes()
    except Exception:
        return None
    return None

def _attachment_image_mime(att):
    if isinstance(att, dict):
        mime = att.get("type") or att.get("mime") or ""
        if mime.startswith("image/"):
            return mime
        name = att.get("name") or att.get("path") or ""
    else:
        name = ""
    ext = pathlib.Path(str(name)).suffix.lower().lstrip(".")
    return {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","gif":"image/gif","webp":"image/webp"}.get(ext, "image/png")

def persist_evaluator_images(eor_id: str, uid: str, images: list) -> list:
    """Persist evaluator evidence images and return JSON-safe attachment metadata."""
    persisted = []
    for idx, img in enumerate(images or [], 1):
        data = _attachment_image_bytes(img)
        if not data:
            continue
        if isinstance(img, dict):
            name = img.get("name") or f"evaluator_evidence_{idx}.png"
            mime = _attachment_image_mime(img)
        else:
            name = f"evaluator_evidence_{idx}.png"
            mime = "image/png"
        path = save_upload(eor_id, uid, name, data)
        persisted.append({
            "name": pathlib.Path(path).name,
            "type": mime,
            "size": len(data),
            "path": path,
            "source": "evaluator_ai_audit",
            "uploaded_by": st.session_state.get("user_name", "Evaluator"),
            "ts": datetime.now().isoformat(),
        })
    return persisted

def render_evidence_images(images, caption="Bukti Evaluator"):
    valid = [img for img in (images or []) if _attachment_image_bytes(img)]
    if not valid:
        return
    img_cols = st.columns(min(len(valid), 3))
    for idx, img in enumerate(valid):
        with img_cols[idx % len(img_cols)]:
            data = _attachment_image_bytes(img)
            mime = _attachment_image_mime(img)
            name = img.get("name", caption) if isinstance(img, dict) else caption
            try:
                _b64 = base64.b64encode(data).decode()
                st.markdown(
                    f'<div style="border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:.4rem;">'
                    f'<img src="data:{mime};base64,{_b64}" style="width:100%;height:auto;display:block;" />'
                    f'<div style="font-size:.67rem;color:#8b949e;padding:3px 6px;">{html.escape(name)}</div></div>',
                    unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Gagal tampilkan image: {e}")

def simulated_email(to: str, subject: str, body: str, sender="CC-AI Platform <noreply@lab.bssn.go.id>"):
    """Simulate email — store in session for display. In prod: replace with smtplib."""
    if "email_log" not in st.session_state:
        st.session_state.email_log = []
    st.session_state.email_log.append({
        "to": to, "subject": subject, "body": body,
        "sender": sender, "ts": datetime.now().isoformat()
    })

st.set_page_config(
    page_title="CC-AI Smart Platform v2.0",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded"
)
# ============================================================
# THEME
# ============================================================
def get_css(dark=True):
    if dark:
        bg,bg2,bg3="#0d1117","#161b22","#1c2128"
        text,muted,border="#e6edf3","#8b949e","#30363d"
        accent,green,yellow,red,purple,orange="#58a6ff","#3fb950","#d29922","#f85149","#d2a8ff","#ffa657"
        col_bg=["#161b22","#1c2128","#0d1f3a","#2a1f0d","#0d3321","#1a1a2e"]
        card_shadow="0 4px 20px rgba(0,0,0,.5)"
        ev_bg,input_bg="#0d1117","#0d1117"
        header_bg="linear-gradient(135deg,#0d1b2e,#1a2744)"
        metric_bg="linear-gradient(135deg,#1f2937,#111827)"
    else:
        bg,bg2,bg3="#f0f4f8","#e8edf2","#ffffff"
        text,muted,border="#0f172a","#64748b","#e2e8f0"
        accent,green,yellow,red,purple,orange="#1e40af","#16a34a","#d97706","#dc2626","#7c3aed","#ea580c"
        col_bg=["#e8edf2","#f0f4f8","#dbeafe","#fef9c3","#dcfce7","#ede9fe"]
        card_shadow="0 2px 12px rgba(0,0,0,.1)"
        ev_bg,input_bg="#f8fafc","#ffffff"
        header_bg="linear-gradient(135deg,#0f2027,#1e3a5f)"
        metric_bg="linear-gradient(135deg,#1e3a5f,#1e40af)"

    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Outfit:wght@300;400;600;700;800&display=swap');
:root{{
  --bg:{bg};--bg2:{bg2};--bg3:{bg3};--text:{text};--muted:{muted};--border:{border};
  --accent:{accent};--green:{green};--yellow:{yellow};--red:{red};--purple:{purple};--orange:{orange};
  --ev-bg:{ev_bg};--input:{input_bg};--header-bg:{header_bg};--metric-bg:{metric_bg};
  --shadow:{card_shadow};--font:'Outfit',sans-serif;--mono:'JetBrains Mono',monospace;
}}
html,body,.stApp{{font-family:var(--font)!important;background:var(--bg)!important;color:var(--text)!important;}}
.block-container{{padding:1.5rem 2rem 2rem!important;max-width:1600px!important;}}
[data-testid="stSidebar"]{{background:#161b22!important;border-right:1px solid rgba(255,255,255,.06)!important;}}
[data-testid="stSidebar"] *{{color:#e6edf3!important;}}
[data-testid="stSidebar"] .stRadio label{{color:#c9d1d9!important;font-size:.85rem!important;}}

/* Page header */
.pg-header{{background:var(--header-bg);border:1px solid rgba(255,255,255,.08);border-radius:18px;
  padding:1.5rem 2.2rem;margin-bottom:1.5rem;position:relative;overflow:hidden;}}
.pg-header::before{{content:'';position:absolute;top:-40%;right:-3%;width:280px;height:280px;
  background:radial-gradient(circle,rgba(88,166,255,.1) 0%,transparent 70%);pointer-events:none;}}
.pg-header h1{{color:#e6edf3!important;font-size:1.55rem!important;font-weight:800!important;margin:0 0 .2rem!important;}}
.pg-header p{{color:#8b949e!important;font-size:.82rem!important;margin:0!important;}}

/* Cards */
.cc-card{{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:1.25rem;
  margin-bottom:1rem;box-shadow:var(--shadow);transition:all .2s;}}
.cc-card:hover{{background:var(--bg3);transform:translateY(-2px);}}

/* Metrics */
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.8rem;margin-bottom:1.3rem;}}
.mc{{background:var(--metric-bg);border-radius:12px;padding:.95rem 1.1rem;text-align:center;
  border:1px solid rgba(255,255,255,.07);box-shadow:var(--shadow);transition:all .2s;}}
.mc:hover{{transform:translateY(-3px);}}
.mc-value{{font-size:1.8rem;font-weight:800;color:#e6edf3;line-height:1;margin-bottom:.2rem;}}
.mc-label{{font-size:.68rem;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;}}

/* ── KANBAN BOARD ──────────────────────────────────── */
.kanban-wrap{{display:grid;grid-template-columns:repeat(5,1fr);gap:.9rem;margin:1rem 0;}}
@media(max-width:1100px){{.kanban-wrap{{grid-template-columns:repeat(3,1fr);}}}}

.kb-col{{background:var(--bg2);border:1px solid var(--border);border-radius:14px;
  padding:.9rem;min-height:300px;}}
.kb-col-header{{font-size:.72rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;
  padding:.4rem .6rem;border-radius:8px;margin-bottom:.75rem;text-align:center;}}
.kb-draft{{background:rgba(110,118,129,.15);color:#8b949e;}}
.kb-audit{{background:rgba(88,166,255,.15);color:#58a6ff;}}
.kb-review{{background:rgba(210,153,34,.15);color:#d29922;}}
.kb-revision{{background:rgba(248,81,73,.15);color:#f85149;}}
.kb-approved{{background:rgba(63,185,80,.15);color:#3fb950;}}

.eor-card{{background:var(--bg3);border:1px solid var(--border);border-radius:10px;
  padding:.85rem;margin-bottom:.7rem;cursor:pointer;transition:all .2s;position:relative;}}
.eor-card:hover{{border-color:var(--accent);transform:translateY(-1px);box-shadow:0 4px 16px rgba(0,0,0,.3);}}
.eor-card.overdue{{border-left:3px solid var(--red)!important;}}
.eor-card.due-soon{{border-left:3px solid var(--yellow)!important;}}
.eor-card.on-track{{border-left:3px solid var(--green)!important;}}

.eor-card-title{{font-size:.82rem;font-weight:700;color:var(--text);margin-bottom:.25rem;}}
.eor-card-meta{{font-size:.68rem;color:var(--muted);font-family:var(--mono);}}
.eor-card-badges{{display:flex;flex-wrap:wrap;gap:3px;margin-top:.45rem;}}

/* Finding cards (Dev Tracker) */
.finding-card{{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:1rem;margin-bottom:.9rem;box-shadow:var(--shadow);}}
.finding-card.open{{border-left:4px solid var(--red);}}
.finding-card.in-progress{{border-left:4px solid var(--yellow);}}
.finding-card.responded{{border-left:4px solid var(--blue, #58a6ff);}}
.finding-card.verified{{border-left:4px solid var(--green);}}
.finding-card.closed{{border-left:4px solid #6e7681;}}

.finding-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.6rem;}}
.finding-uid{{font-family:var(--mono);font-size:.85rem;font-weight:700;color:var(--accent);}}
.finding-req{{font-size:.75rem;color:var(--muted);margin:.3rem 0;line-height:1.4;}}

/* Response thread */
.resp-thread{{border-left:2px solid var(--border);padding-left:.85rem;margin-top:.7rem;}}
.resp-bubble{{background:var(--bg3);border:1px solid var(--border);border-radius:8px;
  padding:.55rem .8rem;margin-bottom:.5rem;font-size:.78rem;}}
.resp-bubble.evaluator{{border-left:3px solid #58a6ff;}}
.resp-bubble.lead{{border-left:3px solid #3fb950;}}
.resp-bubble.developer{{border-left:3px solid #ffa657;}}
.resp-meta{{font-size:.67rem;color:var(--muted);font-family:var(--mono);margin-bottom:.25rem;}}

/* Badges */
.role-badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.67rem;font-weight:700;text-transform:uppercase;}}
.rb-eval{{background:#1a3a5c;color:#58a6ff;border:1px solid #58a6ff40;}}
.rb-lead{{background:#1a3a28;color:#3fb950;border:1px solid #3fb95040;}}
.rb-cb{{background:#3a1a2e;color:#d2a8ff;border:1px solid #d2a8ff40;}}
.rb-dev{{background:#2a1800;color:#ffa657;border:1px solid #ffa65740;}}

.sb{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.68rem;font-weight:600;text-transform:uppercase;}}
.sb-pass{{background:#0d3321;color:#3fb950;border:1px solid #3fb95040;}}
.sb-fail{{background:#3a0d0d;color:#f85149;border:1px solid #f8514940;}}
.sb-inc {{background:#3a2a0d;color:#d29922;border:1px solid #d2992240;}}
.sb-open{{background:#3a0d0d;color:#f85149;border:1px solid #f8514940;}}
.sb-prog{{background:#2a1800;color:#ffa657;border:1px solid #ffa65740;}}
.sb-resp{{background:#0d1f3a;color:#58a6ff;border:1px solid #58a6ff40;}}
.sb-veri{{background:#0d3321;color:#3fb950;border:1px solid #3fb95040;}}
.sb-clos{{background:#1a1a1a;color:#6e7681;border:1px solid #6e768140;}}

.skill-badge{{display:inline-block;background:rgba(210,168,255,.1);border:1px solid rgba(210,168,255,.3);
  border-radius:5px;padding:2px 7px;font-size:.67rem;color:#d2a8ff;font-family:var(--mono);margin:2px;}}
.artefact-pill{{display:inline-flex;align-items:center;gap:4px;background:rgba(88,166,255,.1);
  border:1px solid rgba(88,166,255,.3);border-radius:20px;padding:2px 9px;font-size:.7rem;color:#58a6ff;
  margin:2px;font-family:var(--mono);}}
.ndot{{display:inline-block;width:7px;height:7px;background:#f85149;border-radius:50%;
  margin-left:4px;vertical-align:middle;animation:pulse 2s infinite;}}
@keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.5;transform:scale(1.4)}}}}

/* Audit result boxes */
.v-pass{{border-left:4px solid #3fb950;background:rgba(63,185,80,.07);padding:10px 13px;margin:6px 0;border-radius:0 10px 10px 0;}}
.v-fail{{border-left:4px solid #f85149;background:rgba(248,81,73,.07);padding:10px 13px;margin:6px 0;border-radius:0 10px 10px 0;}}
.v-inc {{border-left:4px solid #d29922;background:rgba(210,153,34,.07);padding:10px 13px;margin:6px 0;border-radius:0 10px 10px 0;}}
.v-na  {{border-left:4px solid #6e7681;background:rgba(110,118,129,.07);padding:10px 13px;margin:6px 0;border-radius:0 10px 10px 0;}}
.ev-box{{background:var(--ev-bg);border:1px solid var(--border);border-left:3px solid var(--accent);
  padding:.55rem .8rem;border-radius:0 6px 6px 0;font-family:var(--mono);font-size:.77rem;
  color:var(--muted);white-space:pre-wrap;max-height:140px;overflow-y:auto;margin:.4rem 0;}}
.flag-review{{background:#2a1f0d;border:1px solid #d2992260;border-radius:6px;padding:4px 9px;font-size:.77rem;color:#d29922;}}
.human-override{{background:#1a2744;border-left:3px solid #58a6ff;padding:6px 10px;margin:4px 0;border-radius:0 6px 6px 0;color:#8b949e;font-size:.77rem;}}

/* Sidebar profile */
.sp{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:12px;
  padding:.85rem;text-align:center;margin-bottom:1rem;}}
.sp-avatar{{width:42px;height:42px;background:linear-gradient(135deg,#1e40af,#3b82f6);border-radius:50%;
  margin:0 auto .4rem;line-height:42px;font-size:1.25rem;}}
.sp-name{{font-weight:700;font-size:.85rem;color:#e6edf3;}}
.sp-email{{font-size:.67rem;color:#8b949e;font-family:var(--mono);margin-top:.1rem;}}

/* SLA bar */
.sla-bar{{height:5px;background:var(--bg3);border-radius:3px;overflow:hidden;margin:.2rem 0;}}
.sla-fill{{height:100%;border-radius:3px;transition:width .6s;}}

/* Buttons */
.stButton>button{{border-radius:9px!important;font-family:var(--font)!important;font-weight:600!important;transition:all .2s!important;}}
.stButton>button[kind="primary"]{{background:linear-gradient(135deg,#1e40af,#3b82f6)!important;border-color:#3b82f6!important;color:white!important;}}
.stTextInput>div>div>input,.stTextArea>div>div>textarea{{
  background:var(--input)!important;border-color:var(--border)!important;
  color:var(--text)!important;border-radius:9px!important;font-family:var(--font)!important;}}
::-webkit-scrollbar{{width:5px;height:5px;}}
::-webkit-scrollbar-thumb{{background:#30363d;border-radius:3px;}}
#MainMenu,footer,header{{visibility:hidden;}}
</style>"""

def apply_theme(): st.markdown(get_css(st.session_state.get("dark_mode",True)),unsafe_allow_html=True)

# ============================================================
# SESSION STATE
# ============================================================
def init_session():
    defaults={
        "logged_in":False,"role":None,"username":None,"user_name":None,
        "user_email":None,"user_avatar":"👤","two_factor_code":None,"dark_mode":True,
        "notifications":[],"eor_backlog":[],"tm_schedules":[],
        "few_shot_db":{},"audit_results":None,"audit_results_raw":[],
        "diagram_pages":{},"st_meta":{},"audit_done":False,
        "model":"qwen2.5:14b","max_pages":100,
        "project_id":"","toe_name":"","toe_version":"","toe_description":"","eal":"4",
        "evaluator_name":"","lead_evaluator_name":"",
        "scope_label":"Full ASE Suite (77 units)",
        "expected_ase_total":77,
        # v11 skills
        "skill_level":"junior_rcc","enable_cot":True,"enable_negative_space":True,
        "enable_sem_guard":True,"enable_confidence_calib":True,
        "workspace_comments":{},"workspace_artefacts":{},
        # v12 Kanban + Dev Tracker
        "kanban_projects":[],   # list of project dicts
        "dev_findings":{},      # {eor_id: {unit_id: finding_dict with dev responses}}
        "dev_assignments":{},   # {username: [eor_id+unit_id]}
        "project_timeline":[],  # for Gantt view
        "selected_project":None,
        # v2.0 additions
        "ev_evidence_images":{},    # {result_id: [image_bytes_list]}
        "tm1_done":False,           # CB TM1 completed
        "tm2_done":False,           # CB TM2 completed — unlocks Dev findings
        "cb_kanban":{},             # {eor_id: cb_status}
        "evaluator_timeline":{},    # {eor_id: {assignee, start, end, notified}}
        "dev_timeline":{},          # {eor_id: {uid: {deadline, notified}}}
        "cycle":1,                  # 1=Evaluator→Lead, 2=CB+Dev active
        "last_validation":{},      # inline validation result after audit
        "email_log":[],             # simulated email outbox
        "observations_cache":{},    # {eor_id: {uid: observation_dict}}
    }
    for k,v in defaults.items():
        if k not in st.session_state: st.session_state[k]=v

init_session()
apply_theme()

# ============================================================
# USERS — added developer role
# ============================================================
USERS={
    "evaluator":    {"password":"eval123","role":"evaluator",    "name":"Alfred Saut","email":"evaluator@cc-lab.go.id","avatar":"👨‍💻"},
    "leadevaluator":{"password":"lead123","role":"lead_evaluator","name":"John Doe",  "email":"lead@cc-lab.go.id",     "avatar":"👥"},
    "cbauditor":    {"password":"cb123",  "role":"cb_auditor",   "name":"Jane Smith", "email":"cb@cc-lab.go.id",       "avatar":"🏛️"},
    "developer":    {"password":"dev123", "role":"developer",    "name":"Budi Dev",   "email":"dev@vendor.co.id",      "avatar":"🛠️"},
}
ROLE_LABEL={"evaluator":"Evaluator","lead_evaluator":"Lead Evaluator","cb_auditor":"CB Auditor","developer":"Developer"}
ROLE_CLS  ={"evaluator":"rb-eval","lead_evaluator":"rb-lead","cb_auditor":"rb-cb","developer":"rb-dev"}

KANBAN_COLS=["DRAFT","IN_AUDIT","UNDER_REVIEW","REVISION","APPROVED"]
KANBAN_CSS ={"DRAFT":"kb-draft","IN_AUDIT":"kb-audit","UNDER_REVIEW":"kb-review","REVISION":"kb-revision","APPROVED":"kb-approved"}
KANBAN_ICONS={"DRAFT":"📝","IN_AUDIT":"🔍","UNDER_REVIEW":"👥","REVISION":"🔁","APPROVED":"✅"}
FINDING_STATUS=["OPEN","IN_PROGRESS","RESPONDED","VERIFIED","CLOSED"]
FINDING_CSS={"OPEN":"sb-open","IN_PROGRESS":"sb-prog","RESPONDED":"sb-resp","VERIFIED":"sb-veri","CLOSED":"sb-clos"}

# ============================================================
# HELPERS
# ============================================================
def pg_header(icon,title,sub):
    st.markdown(f'<div class="pg-header"><h1>{icon} {title}</h1><p>{sub}</p></div>',unsafe_allow_html=True)

def metric_html(v,l,c="#58a6ff"):
    return f'<div class="mc" style="--accent:{c};"><div class="mc-value">{v}</div><div class="mc-label">{l}</div></div>'

def add_notification(title,msg,target,sender=None,obj=None,keterangan=None,icon="🔔"):
    """SPOK format: Siapa | Predikat (title) | Objek | Keterangan"""
    sender = sender or st.session_state.get("user_name","System")
    spok = f"{sender} — {msg}"
    if obj: spok += f" · {obj}"
    if keterangan: spok += f" · {keterangan}"
    st.session_state.notifications.append({
        "id":f"n{int(time.time())}{random.randint(100,999)}",
        "title":title,"message":msg,"spok":spok,
        "sender":sender,"obj":obj or "","keterangan":keterangan or "",
        "icon":icon,"target_role":target,
        "created_at":datetime.now().isoformat(),"read":False})

def count_notifs(role):
    return len([n for n in st.session_state.notifications if n.get("target_role")==role and not n.get("read")])

def days_until(due_str):
    try:
        d=datetime.fromisoformat(due_str).date()
        return (d-date.today()).days
    except: return 99

def sla_color(days):
    if days<0: return "#f85149","overdue"
    if days<=3: return "#d29922","due-soon"
    return "#3fb950","on-track"

def logout():
    for k in ["logged_in","role","username","user_name","user_email","audit_results",
              "audit_results_raw","audit_done","pending_user","pending_email",
              "pending_role","pending_name","pending_avatar"]:
        if k in st.session_state: del st.session_state[k]
    st.rerun()

# ============================================================
# ── AI SKILL SYSTEM (from v11, unchanged) ──────────────────
# ============================================================
GROUNDING_ANCHORS={
    "ASE_INT":("GROUNDING SKILL — ASE_INT:\nEvery claim MUST cite [PDF PAGE N]. "
        "A section must have a HEADING + content — not just a mention in prose.\n"
        "ANCHOR: 'Section exists' = distinct heading + substantive content."),
    "ASE_CCL":("GROUNDING SKILL — ASE_CCL:\nCC edition must be exact text. "
        "'Latest CC standard' = NOT acceptable. Every claim must cite [PDF PAGE N]."),
    "ASE_ECD":("GROUNDING SKILL — ASE_ECD:\n_EXT format = X_YYY_EXT.N. "
        "Name mismatch between SFR section and ECD definition = FAIL regardless of content."),
    "ASE_OBJ":("GROUNDING SKILL — ASE_OBJ:\nTrace tables must be EXPLICIT tables, not prose. "
        "Cite actual table row: [PDF PAGE N] row O.xxx → T.xxx."),
    "ASE_SPD":("GROUNDING SKILL — ASE_SPD:\nEach T/OSP/A.xxx must be labelled item. "
        "Prose without IDs = FAIL. Cite: [PDF PAGE N] 'T.XXXXX: description'."),
    "ASE_REQ":("GROUNDING SKILL — ASE_REQ:\nSFR dependency: scan SFR LIST. "
        "If FAU_GEN.1 present, FPT_STM.1 MUST also be in SFR list. Cite both pages."),
    "ASE_TSS":("GROUNDING SKILL — ASE_TSS:\nTSS must describe IMPLEMENTATION MECHANISMS. "
        "'The TOE satisfies FIA_UAU.2' = paraphrase = NOT a PASS."),
}
NEGATIVE_SPACE={
    "ASE_INT":("NEG-SPACE ASE_INT FAIL indicators:\n❌ Version absent\n❌ TOE name inconsistent\n"
        "❌ Diagram no labelled boundary\n❌ TOE type vague ('security product')\n"
        "PASS: ✓ Explicit version ✓ Identical names ✓ Labelled boundary"),
    "ASE_CCL":("NEG-SPACE ASE_CCL FAIL:\n❌ CC v3.1 reference\n❌ 'Part 2 conformant' + _EXT SFRs\n"
        "❌ 'Part 2 extended' + no _EXT\n❌ PP claimed without name+version\n"
        "PASS: ✓ 'CC:2022 Rev.1' ✓ Part 2 AND Part 3 both stated"),
    "ASE_ECD":("NEG-SPACE ASE_ECD FAIL:\n❌ _EXT used but no ECD section\n"
        "❌ Name mismatch between usage and definition\n❌ 'should' instead of 'shall'\n"
        "PASS: ✓ ECD section heading present ✓ Exact name match"),
    "ASE_OBJ":("NEG-SPACE ASE_OBJ FAIL:\n❌ T.xxx in SPD but absent from rationale\n"
        "❌ Human tasks in TOE objectives\n❌ TOE functions in OE objectives\n"
        "PASS: ✓ Explicit table ✓ All SPD IDs covered"),
    "ASE_SPD":("NEG-SPACE ASE_SPD FAIL:\n❌ No T.xxx IDs (prose only)\n"
        "❌ OSP describes technical function\n❌ Assumption describes what TOE does\n"
        "PASS: ✓ T.xxx: [Adversary] [action] [Asset]"),
    "ASE_REQ":("NEG-SPACE ASE_REQ FAIL:\n❌ Empty [] placeholders remain\n"
        "❌ FAU_GEN.1 present but FPT_STM.1 absent\n❌ Rationale says 'meets objective' with no HOW\n"
        "PASS: ✓ All assignments completed ✓ Dependencies both present"),
    "ASE_TSS":("NEG-SPACE ASE_TSS FAIL:\n❌ TSS = SFR text paraphrase\n"
        "❌ SFR exists but no TSS paragraph\n❌ TSS claims beyond SFRs\n"
        "PASS: ✓ 'implements [SFR] using [algorithm/protocol]'"),
}
COT_INSTRUCTION="""
STRUCTURED DECOMPOSITION (MANDATORY):
STEP 1 — SCAN: Find [PDF PAGE N] where content appears. State: "Found at: [PDF PAGE N]" or "NOT FOUND."
STEP 2 — CHECKLIST: For each item: Evidence=[verbatim or NOT FOUND] Score=PASS/FAIL/UNCLEAR Reason=[one line]
STEP 3 — DERIVE: Any FAIL→FAIL. Any UNCLEAR→INCONCLUSIVE. All PASS→PASS.
STEP 4 — OUTPUT: Write JSON using Step 2-3 results. DO NOT skip steps."""

SEMANTIC_GUARD="""
SEMANTIC GUARD: Distinguish VERBATIM from PARAPHRASE.
❌ "conforms to CC standard" ≠ "CC:2022 Rev.1" explicitly stated
❌ "version info in header" ≠ exact version number verbatim
❌ "rationale section traces objectives" ≠ actual table with rows
❌ "appropriate security measures" = vague = NOT evidence
RULE: Accept only the actual words from [PDF PAGE N]."""

CONFIDENCE_CALIBRATION="""
CONFIDENCE CALIBRATION:
90-100: Verbatim + page cited + all checklist PASS + zero ambiguity
70-89:  Evidence found, minor ambiguity, page cited
50-69:  Evidence indirect/paraphrased, no page, some UNCLEAR
20-49:  Evidence NOT FOUND or contradicts requirement
0-19:   Cannot locate relevant section at all
LOWER by: passive voice(-10) no page(-20) >1 UNCLEAR(-15ea) guessing(-25) heading only(-30)
State: "Confidence:[N] because [reason]" in reasoning field."""

def build_skill_injection(uid,skill_level,cot,neg,sem,calib):
    fam=uid.split(".")[0]; parts=[]
    if skill_level in ("junior_rcc","strict"):
        a=GROUNDING_ANCHORS.get(fam,"")
        if a: parts.append(a)
    if neg:
        n=NEGATIVE_SPACE.get(fam,"")
        if n: parts.append(n)
    if cot: parts.append(COT_INSTRUCTION)
    if sem: parts.append(SEMANTIC_GUARD)
    if calib: parts.append(CONFIDENCE_CALIBRATION)
    if not parts: return ""
    sep="═"*55
    return f"\n{sep}\nJUNIOR RCC EVALUATOR SKILLS ACTIVE\n{sep}\n"+"\n\n".join(parts)+f"\n{sep}\n"

# ============================================================
# CC CATALOGUES + DATA MODEL (unchanged from v11)
# ============================================================
CC_PART2={
    "FAU_ARP.1","FAU_GEN.1","FAU_GEN.2","FAU_SAA.1","FAU_SAR.1","FAU_SAR.2","FAU_SAR.3",
    "FAU_SEL.1","FAU_STG.1","FAU_STG.2","FAU_STG.3","FAU_STG.4","FCO_NRO.1","FCO_NRR.1",
    "FCS_CKM.1","FCS_CKM.2","FCS_CKM.3","FCS_CKM.4","FCS_COP.1","FCS_RBG.1","FCS_RNG.1",
    "FDP_ACC.1","FDP_ACC.2","FDP_ACF.1","FDP_IFC.1","FDP_IFC.2","FDP_IFF.1","FDP_IFF.2",
    "FDP_IFF.3","FDP_IFF.4","FDP_IFF.5","FDP_IRC.1","FDP_ITC.1","FDP_ITC.2","FDP_ITT.1",
    "FDP_RIP.1","FDP_RIP.2","FDP_ROL.1","FDP_ROL.2","FDP_SDI.1","FDP_SDI.2","FDP_UCT.1",
    "FDP_UIT.1","FDP_UIT.2","FDP_UIT.3","FIA_AFL.1","FIA_ATD.1","FIA_SOS.1","FIA_SOS.2",
    "FIA_UAU.1","FIA_UAU.2","FIA_UAU.3","FIA_UAU.4","FIA_UAU.5","FIA_UAU.6","FIA_UAU.7",
    "FIA_UID.1","FIA_UID.2","FIA_USB.1","FMT_LIM.1","FMT_LIM.2","FMT_MOF.1","FMT_MSA.1",
    "FMT_MSA.2","FMT_MSA.3","FMT_MSA.4","FMT_MTD.1","FMT_MTD.2","FMT_REV.1","FMT_SAE.1",
    "FMT_SMF.1","FMT_SMR.1","FMT_SMR.2","FPR_ANO.1","FPR_PSE.1","FPR_UNO.1","FPR_UNO.2",
    "FPT_EMS.1","FPT_FLS.1","FPT_ITA.1","FPT_ITC.1","FPT_ITI.1","FPT_ITT.1","FPT_PHP.1",
    "FPT_PHP.2","FPT_PHP.3","FPT_RCV.1","FPT_RCV.2","FPT_RPL.1","FPT_SSP.1","FPT_STM.1",
    "FPT_STM.2","FPT_TDC.1","FPT_TEE.1","FPT_TRC.1","FPT_TST.1","FRU_FLT.1","FRU_FLT.2",
    "FRU_PRS.1","FRU_RSA.1","FRU_RSA.2","FTA_LSA.1","FTA_MCS.1","FTA_SSL.1","FTA_SSL.2",
    "FTA_SSL.3","FTA_SSL.4","FTA_TAB.1","FTA_TSE.1","FTP_ITC.1","FTP_PRO.1","FTP_TRP.1",
}
CC_PART3={
    "ADV_ARC.1","ADV_FSP.1","ADV_FSP.2","ADV_FSP.3","ADV_FSP.4","ADV_FSP.5","ADV_FSP.6",
    "ADV_IMP.1","ADV_IMP.2","ADV_INT.1","ADV_INT.2","ADV_INT.3","ADV_SPM.1","ADV_TDS.1",
    "ADV_TDS.2","ADV_TDS.3","ADV_TDS.4","ADV_TDS.5","ADV_TDS.6","AGD_OPE.1","AGD_PRE.1",
    "ALC_CMC.1","ALC_CMC.2","ALC_CMC.3","ALC_CMC.4","ALC_CMC.5","ALC_CMS.1","ALC_CMS.2",
    "ALC_CMS.3","ALC_CMS.4","ALC_CMS.5","ALC_DEL.1","ALC_DVS.1","ALC_DVS.2","ALC_FLR.1",
    "ALC_FLR.2","ALC_FLR.3","ALC_LCD.1","ALC_LCD.2","ALC_TAT.1","ALC_TAT.2","ALC_TAT.3",
    "ASE_CCL.1","ASE_ECD.1","ASE_INT.1","ASE_OBJ.1","ASE_OBJ.2","ASE_REQ.1","ASE_REQ.2",
    "ASE_SPD.1","ASE_TSS.1","ASE_TSS.2","ATE_COV.1","ATE_COV.2","ATE_COV.3","ATE_DPT.1",
    "ATE_DPT.2","ATE_DPT.3","ATE_FUN.1","ATE_FUN.2","ATE_IND.1","ATE_IND.2","ATE_IND.3",
    "AVA_VAN.1","AVA_VAN.2","AVA_VAN.3","AVA_VAN.4","AVA_VAN.5",
}
CC_P2_FAM={"FAU","FCO","FCS","FDP","FIA","FMT","FPR","FPT","FRU","FTA","FTP"}
CC_P3_FAM={"ADV","AGD","ALC","ATE","AVA","ASE","ACO"}
REVIEW_THRESHOLD=70   # Lowered: 85 was too strict for 7b models → 53+ red flags
# Dynamic threshold helper: small models get 70, large get 80
def get_review_threshold(model: str) -> int:
    m = (model or "").lower()
    if any(x in m for x in ("70b","72b","32b","34b","14b","13b")):
        return 80
    return 70   # 7b and smaller: 70 is appropriate
EXPECTED_ASE_WORK_UNITS = {
    "ASE_CCL": 21,
    "ASE_ECD": 13,
    "ASE_INT": 12,
    "ASE_OBJ": 6,
    "ASE_REQ": 18,
    "ASE_SPD": 4,
    "ASE_TSS": 3,
}

EXPECTED_TOTAL_ASE = 77

@dataclass
class Result:
    id:str;label:str;verdict:Literal["PASS","FAIL","INCONCLUSIVE"];confidence:int
    evidence:str;reasoning:str;is_na:bool=False;evidence_valid:bool=True
    validation_note:str="";needs_review:bool=False;human_verdict:str=""
    human_comment:str="";human_reviewer:str="";review_ts:str=""
    override_history:list=field(default_factory=list);extra:dict=field(default_factory=dict)
    def get_final_verdict(self): return self.human_verdict if self.human_verdict else self.verdict
    def is_overridden(self): return bool(self.human_verdict)

def _to_str(v):
    if isinstance(v,str): return v
    if isinstance(v,(dict,list)): return json.dumps(v,ensure_ascii=False)
    return str(v) if v is not None else ""

def check_cc_version(t):
    """Deterministic check for ASE_CCL.1:
    - CC edition claim (2022 R1 required)
    - PP conformance: if no PP referenced → N/A PASS
    - Package claim: EAL or CAP must be present
    """
    tl = t.lower()
    # ── CC Edition ───────────────────────────────────────────────────────
    old = any(re.search(p,tl) for p in [r"version\s*3\.1",r"v3\.1",r"ccmb-200[679]"])
    new = any(re.search(p,tl) for p in [r"2022",r"rev\.?1",r"15408:2022",r"cc:2022"])
    if old and not new:
        return {"verdict":"FAIL","conf":95,
                "reasoning":"FAIL — ST mengklaim CC v3.1, bukan CC:2022 Rev.1.","pp_claim":False}
    if not new and not old:
        return {"verdict":"INCONCLUSIVE","conf":50,
                "reasoning":"CC edition tidak jelas — tidak ada referensi versi yang diidentifikasi.","pp_claim":False}

    # ── PP Conformance ───────────────────────────────────────────────────
    # Patterns for PP claim: "conformant to PP", "PP conformant", "no PP claim", etc.
    pp_claimed = any(re.search(p,tl) for p in [
        r"protection profile", r"\bpp\b.*conform", r"conform.*\bpp\b",
        r"pp\s+conform", r"pp-conform", r"pp\s+reference",
        r"conformant.*protection", r"protection.*profile.*conform",
    ])
    pp_none = any(re.search(p,tl) for p in [
        r"no\s+pp\s+claim", r"not\s+conform.*pp", r"no.*protection.*profile",
        r"none.*protection.*profile", r"pp.*claim.*none",
        r"no\s+conformance.*claim\s+to.*pp",
        r"tidak.*protection.*profile", r"tanpa.*pp",
    ])

    # ── EAL / CAP Package ────────────────────────────────────────────────
    eal_match = re.search(r"eal\s*([1-7])\s*(?:\+|augmented)?", tl)
    cap_match = re.search(r"cap-?[bc]", tl)
    pkg = ""
    if eal_match: pkg = f"EAL{eal_match.group(1)}"
    elif cap_match: pkg = cap_match.group(0).upper()

    # ── Build verdict ────────────────────────────────────────────────────
    reasons = []
    verdict = "PASS"
    conf = 98

    # Edition check passed
    reasons.append("✅ CC:2022 Rev.1 teridentifikasi dalam ST.")

    # PP claim
    if pp_none:
        reasons.append("✅ PP Conformance Claim: Tidak ada klaim PP — N/A (PASS). "
                       "ST hanya mengklaim conformance ke CC Part 2/3.")
    elif pp_claimed:
        reasons.append("✅ PP Conformance Claim: PP ditemukan direferensikan dalam ST.")
    else:
        # No explicit statement either way — check if section exists
        has_ccl_section = any(re.search(p,tl) for p in [
            r"conformance claim", r"klaim kesesuaian", r"ase_ccl",
        ])
        if has_ccl_section:
            reasons.append("⚠️ PP Conformance: Section CCL ada namun tidak eksplisit menyatakan "
                           "ada/tidaknya PP claim. Perlu review manual.")
            conf = min(conf, 80)
        else:
            reasons.append("⚠️ PP Conformance: Bagian Conformance Claim tidak teridentifikasi. "
                           "Kemungkinan N/A jika tidak ada PP — perlu verifikasi manual.")
            conf = min(conf, 75)

    # Package
    if pkg:
        reasons.append(f"✅ Package Claim: {pkg} teridentifikasi.")
    else:
        reasons.append("⚠️ Package Claim (EAL/CAP): Tidak teridentifikasi secara eksplisit.")
        conf = min(conf, 82)

    return {
        "verdict": verdict,
        "conf": conf,
        "reasoning": "\n".join(reasons),
        "pp_claim": pp_claimed and not pp_none,
        "pp_none": pp_none,
        "package": pkg,
    }

def check_ecd1(st_text):
    """Deterministic check for ASE_ECD.1 — Extended Component Definition.

    Logic:
    1. Extract all SFR/SAR component tokens from ST text.
    2. Classify: standard (CC Part 2/3), extended (_EXT suffix or unknown family),
       unknown (not in CC catalogue), possible typo.
    3. N/A PASS path:
       - If NO extended components found AND NO unknown tokens → ST tidak mendefinisikan
         extended component → ASE_ECD.1 is N/A → auto PASS (sesuai CEM: jika tidak ada
         extended component definition maka ECD is not applicable).
    4. FAIL path: unknown tokens present (possible illegal/undefined component).
    5. PASS path: extended components present AND all properly defined.
    """
    tl = st_text.lower()

    # ── Detect explicit N/A statement ────────────────────────────────────
    na_explicit = any(re.search(p, tl) for p in [
        r"no\s+extended\s+component",
        r"extended\s+component.*not\s+applicable",
        r"extended\s+component.*n/?a\b",
        r"tidak.*extended.*component",
        r"no\s+new\s+component",
        r"all\s+sfr.*part\s*2",
        r"all\s+sar.*part\s*3",
        r"only.*standard.*component",
        r"no\s+extended.*definition",
    ])

    # ── Token extraction ─────────────────────────────────────────────────
    tokens = re.findall(r'\b([A-Z]{3,}_[A-Z]{2,}(?:_EXT)?(?:EX)?\.[0-9]+)\b', st_text)
    seen = {}
    for tok in tokens:
        if tok not in seen:
            seen[tok] = {"is_ext": "_EXT" in tok.upper() or tok.upper().endswith("EX")}

    standard, extended, unknown, typo = [], [], [], []
    for tok, info in seen.items():
        base = re.sub(r'(_EXT|EX)$', '', tok, flags=re.IGNORECASE).upper()
        if info["is_ext"]:
            extended.append(tok)
        elif base in CC_PART2 or base in CC_PART3:
            standard.append(tok)
        else:
            fam = base[:3]
            fam4 = base[:7]
            known = fam in CC_P2_FAM or fam in CC_P3_FAM
            sim = [c for c in (CC_PART2 | CC_PART3) if c.startswith(fam4)]
            if known and sim:
                typo.append({"token": tok, "similar": sim[:3]})
            else:
                unknown.append(tok)

    # ── N/A PASS: no extended, no unknown, or explicit N/A statement ─────
    if na_explicit:
        return {
            "verdict": "PASS", "conf": 98,
            "note": "N/A — ST secara eksplisit menyatakan tidak ada Extended Component Definition. "
                    "ASE_ECD.1 tidak applicable → PASS otomatis.",
            "standard": sorted(standard), "extended": [], "unknown": [], "typo": [],
            "na": True,
        }

    if not extended and not unknown:
        # No extended components found AND no unknown tokens
        # → ST hanya menggunakan komponen standar CC Part 2/3
        # → ECD is N/A → auto PASS
        return {
            "verdict": "PASS", "conf": 95,
            "note": (f"N/A (auto-detected) — Tidak ditemukan Extended Component dalam ST. "
                     f"Semua {len(standard)} komponen adalah standard CC Part 2/3. "
                     f"ASE_ECD.1 tidak applicable → PASS."),
            "standard": sorted(standard), "extended": [], "unknown": [], "typo": [],
            "na": True,
        }

    # ── FAIL: unknown components ──────────────────────────────────────────
    if unknown:
        return {
            "verdict": "FAIL", "conf": 90,
            "note": f"FAIL — Komponen tidak dikenal: {', '.join(unknown[:5])}. "
                    "Kemungkinan extended component tidak terdefinisi di ASE_ECD.",
            "standard": sorted(standard), "extended": sorted(extended),
            "unknown": unknown, "typo": typo, "na": False,
        }

    # ── INCONCLUSIVE: possible typos ─────────────────────────────────────
    if typo and not extended:
        return {
            "verdict": "INCONCLUSIVE", "conf": 70,
            "note": f"INCONCLUSIVE — Possible typo: {'; '.join(t['token'] for t in typo[:3])}. "
                    "Verifikasi apakah ini extended component yang tidak ber-suffix _EXT.",
            "standard": sorted(standard), "extended": [], "unknown": unknown,
            "typo": typo, "na": False,
        }

    # ── PASS: extended components properly defined ────────────────────────
    return {
        "verdict": "PASS", "conf": 92,
        "note": (f"PASS — {len(extended)} extended component ditemukan: {', '.join(extended[:5])}. "
                 f"{len(standard)} standard component. "
                 "Extended component definition harus diverifikasi human evaluator."),
        "standard": sorted(standard), "extended": sorted(extended),
        "unknown": unknown, "typo": typo, "na": False,
    }

def analyze_st_metadata(t):
    tl=t.lower()
    has_pp=bool(re.search(r'protection\s+profile',tl)) and not any(re.search(p,tl) for p in [r"no\s+protection\s+profile",r"does\s+not\s+conform"])
    has_pp_config=bool(re.search(r'pp[\s\-]?configuration',tl))
    ext_comps=list(set(re.findall(r'\b([A-Z]{3,}_[A-Z]{2,}_EXT\.\d+)\b',t)))
    has_ext=bool(ext_comps) or bool(re.search(r'extended\s+component',tl))
    spd_ids=re.findall(r'\b((?:T|OSP|A)\.[A-Z0-9_.\-]+)\b',t)
    return {"has_pp":has_pp,"has_pp_config":has_pp_config,"has_ext":has_ext,
            "ext_comps":ext_comps,"spd_ids":sorted(set(spd_ids)),"sfr_list":sorted(set(re.findall(r'\b(F[A-Z]{2}_[A-Z]{3,}\.\d+)\b',t)))}

def detect_toc(text):
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    if not lines: return False
    r=sum(1 for l in lines if re.search(r'[\.\s]{3,}\d{1,4}\s*$',l))/len(lines)
    return any(k in text.lower() for k in ["table of contents","daftar isi","contents"]) and r>=0.3

def detect_cem_table(text):
    cnt=sum(len(re.findall(p,text)) for p in [r'[A-Z]{3}_[A-Z]{2,}\.\d+[\.\d]*[CDE]\b',r'\b(ADV|AGD|ALC|ATE|AVA|ASE)_[A-Z]+\.\d'])
    return cnt>=2 or any(h in text for h in ["Developer action elements","Evaluator action elements"])

def _has_large_content_image(page):
    page_area = max(float(page.width) * float(page.height), 1.0)
    for img in getattr(page, "images", []) or []:
        width = float(img.get("x1", 0) - img.get("x0", 0))
        height = float(img.get("bottom", 0) - img.get("top", 0))
        area_ratio = (width * height) / page_area
        width_ratio = width / max(float(page.width), 1.0)
        height_ratio = height / max(float(page.height), 1.0)
        top = float(img.get("top", 0))
        bottom = float(img.get("bottom", 0))
        in_header_footer = bottom < page.height * 0.18 or top > page.height * 0.86
        if area_ratio >= 0.035 and width_ratio >= 0.25 and height_ratio >= 0.08 and not in_header_footer:
            return True
    return False

def is_diagram_page(page, text=None):
    text = text if text is not None else (page.extract_text() or "")
    has_caption = bool(re.search(r'(?im)^\s*(figure|fig\.|gambar|diagram|illustration)\s*\d+', text or ""))
    has_diagram_context = bool(re.search(r'(?i)\b(physical scope|logical scope|toe boundary|network topology|architecture diagram|boundary diagram)\b', text or ""))
    large_image = _has_large_content_image(page)
    vector_count = len(getattr(page, "curves", []) or []) + len(getattr(page, "rects", []) or []) + len(getattr(page, "lines", []) or [])
    return has_caption or (large_image and has_diagram_context) or (vector_count >= 30 and has_diagram_context)

def extract_page_image_bytes(page):
    try:
        img=page.to_image(resolution=120); buf=io.BytesIO(); img.save(buf,format="PNG"); return buf.getvalue()
    except Exception:
        return b""

def extract_st(pdf_file,max_pages):
    sections,extracted,dp,toc_nav,excluded,visual_pages=[],[],{},[],[],[]
    try:
        pdf_file.seek(0)
    except Exception:
        pass
    with pdfplumber.open(pdf_file) as pdf:
        total_pages=len(pdf.pages)
        total=min(total_pages,max_pages)
        for i in range(total):
            pg=pdf.pages[i]; pn=i+1; text=pg.extract_text() or ""
            if is_diagram_page(pg,text):
                visual_pages.append(pn)
                dp[pn]=extract_page_image_bytes(pg)
            if not text.strip():
                excluded.append(pn)
                continue
            if detect_toc(text):
                for line in text.splitlines():
                    m=re.search(r'(.+?)[\s\.]{2,}(\d{1,4})\s*$',line.strip())
                    if m and len(m.group(1).strip())>3: toc_nav.append(f"  {m.group(1).strip().rstrip('.')} -> p.{m.group(2)}")
                excluded.append(pn); continue
            if detect_cem_table(text): excluded.append(pn); continue
            extracted.append(pn)
            sections.append(f"[PDF PAGE {pn}]\n{text.strip()}")
    nav=("[TOC-NAVIGATION - use ONLY to find pages]\n"+"\n".join(toc_nav)+"\n\n") if toc_nav else ""
    note=f"[EXTRACTION]\nTotal PDF Pages:{total_pages} Processed:{extracted or 'none'} Excluded:{excluded or 'none'} Visual/Diagram Pages:{sorted(visual_pages) or 'none'}\n\n"
    return {"text":note+nav+"\n\n".join(sections),"pages":extracted,"total_pages":total_pages,"processed_pages":extracted,"excluded_pages":excluded,"diagram_pages":dp,"visual_pages":visual_pages}
def extract_work_units(text):

    matches = WORK_UNIT_REGEX.findall(text)

    unique_work_units = sorted(set(matches))

    return unique_work_units


def extract_components(text):

    matches = COMPONENT_REGEX.findall(text)

    unique_components = sorted(set(matches))

    return unique_components


# ============================================================
# ASE COVERAGE ENGINE
# ============================================================

EXPECTED_ASE_WORK_UNITS = {
    "ASE_CCL": 21,
    "ASE_ECD": 13,
    "ASE_INT": 12,
    "ASE_OBJ": 6,
    "ASE_REQ": 18,
    "ASE_SPD": 4,
    "ASE_TSS": 3,
}

EXPECTED_TOTAL_ASE = 77


def calculate_ase_coverage(work_units):

    detected = len(work_units)

    coverage = round(
        (detected / EXPECTED_TOTAL_ASE) * 100,
        2
    )

    return {
        "detected": detected,
        "expected": EXPECTED_TOTAL_ASE,
        "coverage": coverage
    }


def family_breakdown(work_units):

    result = {}

    for family, expected in EXPECTED_ASE_WORK_UNITS.items():

        detected = len([
            wu for wu in work_units
            if wu.startswith(family)
        ])

        result[family] = {
            "detected": detected,
            "expected": expected,
            "coverage": round(
                (detected / expected) * 100,
                2
            )
        }

    return result

# ── CRITERIA (56 work units, same as v11) ──────────────────
CRITERIA={
    "ASE_INT.1-1":{"fam":"ASE_INT","cc":"ASE_INT.1.1C","pp_dependent":False,"ext_dependent":False,
        "label":"ST Introduction — Mandatory Elements",
        "req":"ST introduction contains ST reference, TOE reference, TOE overview, TOE description.",
        "logic":"Check 1 — ST reference section with heading.\nCheck 2 — TOE reference section.\nCheck 3 — TOE overview section.\nCheck 4 — TOE description section.\nCheck 5 — TOE name consistent.",
        "checklist":["ST reference section present","TOE reference section present","TOE overview section present","TOE description section present","TOE name consistent across sections"]},
    "ASE_INT.1-2":{"fam":"ASE_INT","cc":"ASE_INT.1.2C","pp_dependent":False,"ext_dependent":False,
        "label":"ST Reference — Unique Identification","req":"ST reference uniquely identifies the ST.",
        "logic":"Check 1 — Title.\nCheck 2 — Version.\nCheck 3 — Date.\nCheck 4 — Unique combination.",
        "checklist":["ST title present","Version number stated","Date present","Combination unique"]},
    "ASE_INT.1-3":{"fam":"ASE_INT","cc":"ASE_INT.1.3C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Reference — Unique Identification","req":"TOE reference uniquely identifies the TOE.",
        "logic":"Check 1 — Product name.\nCheck 2 — Version/build.\nCheck 3 — Multi-component listed.\nCheck 4 — Consistent.",
        "checklist":["TOE product name stated","TOE version/build stated","All components listed if multi","Consistent with overview"]},
    "ASE_INT.1-4":{"fam":"ASE_INT","cc":"ASE_INT.1.3C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Reference — Not Misleading","req":"TOE reference is not misleading.",
        "logic":"Check 1 — Name not ambiguous.\nCheck 2 — No out-of-scope implied.\nCheck 3 — TOE vs non-TOE clear.",
        "checklist":["TOE name not ambiguous","No out-of-scope implied","TOE vs non-TOE clear"]},
    "ASE_INT.1-5":{"fam":"ASE_INT","cc":"ASE_INT.1.4C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Overview — Usage and Major Security Features","req":"TOE overview describes usage and major security features.",
        "logic":"Check 1 — Operational purpose.\nCheck 2 — Security features.\nCheck 3 — Understandable.\nCheck 4 — Consistent with SFRs.",
        "checklist":["Operational purpose described","Security features enumerated","Understandable to non-expert","Consistent with SFRs"]},
    "ASE_INT.1-6":{"fam":"ASE_INT","cc":"ASE_INT.1.5C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Overview — TOE Type","req":"TOE overview identifies the TOE type.",
        "logic":"Check 1 — TOE type explicitly identified.\nCheck 2 — Consistent with security functions.",
        "checklist":["TOE type identified","Uses CC product category","Not vague","Consistent with functions"]},
    "ASE_INT.1-7":{"fam":"ASE_INT","cc":"ASE_INT.1.5C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Type — Not Misleading","req":"TOE type is not misleading.",
        "logic":"Check 1 — Internal consistency.\nCheck 2 — No broader scope implied.",
        "checklist":["TOE type internally consistent","No broader scope implied"]},
    "ASE_INT.1-8":{"fam":"ASE_INT","cc":"ASE_INT.1.6C","pp_dependent":False,"ext_dependent":False,
        "label":"Non-TOE HW/SW/FW Dependencies","req":"TOE overview identifies non-TOE HW/SW/FW.",
        "logic":"Check 1 — Non-TOE HW.\nCheck 2 — SW/OS with version.\nCheck 3 — FW if applicable.\nCheck 4 — 'None' if no dependencies.",
        "checklist":["Non-TOE HW identified","Non-TOE SW/OS with version","FW if applicable","Zero dependency stated if none"]},
    "ASE_INT.1-9":{"fam":"ASE_INT","cc":"ASE_INT.1.7C","pp_dependent":True,"ext_dependent":False,
        "label":"Multi-Assurance TSF Organisation","req":"For multi-assurance ST, describes TSF organisation.",
        "logic":"N/A gate: no PP-Config -> PASS.",
        "checklist":["PP-Config checked","If N/A: single-assurance confirmed","If applicable: sub-TSF per PP-Module"]},
    "ASE_INT.1-10":{"fam":"ASE_INT","cc":"ASE_INT.1.8C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Description — Physical Scope","req":"TOE description describes physical scope.",
        "logic":"Check 1 — Diagram with labelled boundary.\nCheck 2 — HW/SW/FW with versions.\nCheck 3 — Network context.",
        "checklist":["Physical scope diagram with labelled boundary","HW/SW/FW listed with versions","Network context shown","Rational for TOE type"]},
    "ASE_INT.1-11":{"fam":"ASE_INT","cc":"ASE_INT.1.9C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Description — Logical Scope","req":"TOE description describes logical scope.",
        "logic":"Check 1 — Diagram.\nCheck 2 — In-scope functions.\nCheck 3 — Out-of-scope.\nCheck 4 — Map to SFRs.",
        "checklist":["Logical scope diagram present","In-scope functions enumerated","Out-of-scope identified","Functions map to SFR families","Diagram consistent with prose"]},
    "ASE_INT.1-12":{"fam":"ASE_INT","cc":"ASE_INT.1.9C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Reference/Overview/Description — Consistency","req":"TOE reference, overview, description consistent.",
        "logic":"Check 1 — Name identical.\nCheck 2 — Version identical.\nCheck 3 — Type vs scope.",
        "checklist":["TOE name identical across sections","TOE version identical","TOE type consistent with scope","Security features consistent"]},
    "ASE_CCL.1-1":{"fam":"ASE_CCL","cc":"ASE_CCL.1.1C","pp_dependent":False,"ext_dependent":False,
        "label":"Conformance Claim — CC Edition","req":"CC edition identified.",
        "logic":"DETERMINISTIC check.",
        "checklist":["CC edition identified","CC:2022 Rev.1 or SNI 2022","ST and TOE conformance stated"]},
    "ASE_CCL.1-2":{"fam":"ASE_CCL","cc":"ASE_CCL.1.2C","pp_dependent":False,"ext_dependent":True,
        "label":"Part 2 Conformant or Extended","req":"Part 2 claim stated.",
        "logic":"Check 1 — Explicit Part 2 claim.\nCheck 2 — _EXT matches claim.",
        "checklist":["Part 2 claim present","Claim matches SFR content"]},
    "ASE_CCL.1-3":{"fam":"ASE_CCL","cc":"ASE_CCL.1.3C","pp_dependent":False,"ext_dependent":True,
        "label":"Part 3 Conformant or Extended","req":"Part 3 claim stated.",
        "logic":"Check 1 — Explicit Part 3 claim.\nCheck 2 — Augmented SARs match.",
        "checklist":["Part 3 claim present","Claim matches SAR content"]},
    "ASE_CCL.1-4":{"fam":"ASE_CCL","cc":"ASE_CCL.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"Part 2 Claim Consistency","req":"Part 2 claim consistent with ECD.",
        "logic":"'Part 2 conformant' + _EXT = FAIL.",
        "checklist":["Part 2 claim consistent with SFR content"]},
    "ASE_CCL.1-5":{"fam":"ASE_CCL","cc":"ASE_CCL.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"Part 3 Claim Consistency","req":"Part 3 claim consistent with ECD.",
        "logic":"'Part 3 conformant' + extended SARs = FAIL.",
        "checklist":["Part 3 claim consistent with SAR content"]},
    "ASE_CCL.1-6":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":True,"ext_dependent":False,
        "label":"PP Claim Identification","req":"All PPs identified if claimed.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","All PPs listed if claimed"]},
    "ASE_CCL.1-7":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":True,"ext_dependent":False,
        "label":"Package Claim Rules","req":"No duplicate package claims.",
        "logic":"N/A if no PP.",
        "checklist":["No duplicate package claims","Augmented claims where applicable"]},
    "ASE_CCL.1-8":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":True,"ext_dependent":False,
        "label":"Allowed-With for Multiple PPs","req":"Allowed-with complete.",
        "logic":"N/A if single PP.",
        "checklist":["Applicability checked","All PP combinations permitted"]},
    "ASE_CCL.1-9":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":True,"ext_dependent":False,
        "label":"PP-Configuration Identification","req":"PP-Config identified.",
        "logic":"N/A if no PP-Config.",
        "checklist":["Applicability checked","PP-Config with name/version"]},
    "ASE_CCL.1-10":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":True,"ext_dependent":False,
        "label":"Exactly One PP-Configuration","req":"Exactly one PP-Config.",
        "logic":"N/A if no PP-Config.",
        "checklist":["Applicability checked","Exactly one PP-Configuration"]},
    "ASE_CCL.1-11":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":False,"ext_dependent":False,
        "label":"Functional Package Completeness","req":"Functional package definitions complete.",
        "logic":"N/A if no packages.",
        "checklist":["Applicability checked","Package definitions complete"]},
    "ASE_CCL.1-12":{"fam":"ASE_CCL","cc":"ASE_CCL.1.5C","pp_dependent":False,"ext_dependent":False,
        "label":"Assurance Package Completeness","req":"Assurance package complete.",
        "logic":"EAL identified; all SARs present.",
        "checklist":["EAL package identified","All standard SARs present"]},
    "ASE_CCL.1-13":{"fam":"ASE_CCL","cc":"ASE_CCL.1.6C","pp_dependent":False,"ext_dependent":False,
        "label":"All Packages Identified","req":"All packages listed in conformance claim.",
        "logic":"Every package used listed.",
        "checklist":["All packages used listed"]},
    "ASE_CCL.1-14":{"fam":"ASE_CCL","cc":"ASE_CCL.1.6C","pp_dependent":False,"ext_dependent":False,
        "label":"Package Status","req":"Each package conformant or augmented.",
        "logic":"Only valid terms.",
        "checklist":["Each package has conformant or augmented status","No invalid terms"]},
    "ASE_CCL.1-15":{"fam":"ASE_CCL","cc":"ASE_CCL.1.7C","pp_dependent":True,"ext_dependent":False,
        "label":"Only PP-Conformant Claims","req":"PP-Conformant terminology only.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","Only PP-Conformant used"]},
    "ASE_CCL.1-16":{"fam":"ASE_CCL","cc":"ASE_CCL.1.8C","pp_dependent":True,"ext_dependent":False,
        "label":"TOE Type vs PP Rationale","req":"TOE type consistent with PP.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","Rationale explains TOE type consistency"]},
    "ASE_CCL.1-17":{"fam":"ASE_CCL","cc":"ASE_CCL.1.9C","pp_dependent":True,"ext_dependent":False,
        "label":"SPD Consistency with PP","req":"SPD consistent with PP SPDs.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","SPD consistent","No assumptions contradicted"]},
    "ASE_CCL.1-18":{"fam":"ASE_CCL","cc":"ASE_CCL.1.10C","pp_dependent":True,"ext_dependent":False,
        "label":"Objectives Consistency with PP","req":"Objectives consistent with PPs.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","All PP objectives covered","None contradicted"]},
    "ASE_CCL.1-19":{"fam":"ASE_CCL","cc":"ASE_CCL.1.11C","pp_dependent":True,"ext_dependent":False,
        "label":"Requirements Consistency with PP","req":"ST consistent with PP requirements.",
        "logic":"All PP SFRs present; assignments in range.",
        "checklist":["Applicability checked","All PP SFRs present","Assignments in range","No weakening"]},
    "ASE_CCL.1-20":{"fam":"ASE_CCL","cc":"ASE_CCL.1.12C","pp_dependent":True,"ext_dependent":False,
        "label":"Exact/Strict/Demonstrable","req":"PP conformance is exact/strict/demonstrable.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","Conformance type valid"]},
    "ASE_CCL.1-21":{"fam":"ASE_CCL","cc":"ASE_CCL.1.13C","pp_dependent":True,"ext_dependent":False,
        "label":"Derived Evaluation Activities","req":"Required EAs identified.",
        "logic":"N/A if no PP.",
        "checklist":["Applicability checked","EAs identified","EA references specific"]},
    "ASE_ECD.1-1":{"fam":"ASE_ECD","cc":"ASE_ECD.1.1C","pp_dependent":False,"ext_dependent":False,
        "label":"Non-Extended Requirements in CC Part 2/3","req":"All non-extended requirements in CC Part 2 or 3.",
        "logic":"DETERMINISTIC database check.",
        "checklist":["SFRs/SARs inventoried","In CC Part 2","In CC Part 3","No unknown standard components"]},
    "ASE_ECD.1-2":{"fam":"ASE_ECD","cc":"ASE_ECD.1.2C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Components — Each _EXT Defined","req":"Definition for each _EXT.",
        "logic":"N/A if no _EXT. ECD section, names match.",
        "checklist":["N/A gate","ECD section present","Every _EXT defined","Names match exactly"]},
    "ASE_ECD.1-3":{"fam":"ASE_ECD","cc":"ASE_ECD.1.3C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Components — CC Taxonomy","req":"Each _EXT fits CC taxonomy.",
        "logic":"N/A if no _EXT.",
        "checklist":["N/A gate","Taxonomy placement explained","Non-redundancy justified","Dependencies stated"]},
    "ASE_ECD.1-4":{"fam":"ASE_ECD","cc":"ASE_ECD.1.3C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Components — Dependencies","req":"Dependencies identified.",
        "logic":"N/A if no _EXT.",
        "checklist":["N/A gate","Dependencies field present","Logical dependencies declared"]},
    "ASE_ECD.1-5":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Functional — CC Part 2 Model","req":"Extended functional uses CC Part 2 model.",
        "logic":"N/A if no extended functional.",
        "checklist":["N/A gate","Element numbering X.Y.Z","TSF shall language","CC operations correct","Management/Audit present"]},
    "ASE_ECD.1-6":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"New Functional Family — CC Model","req":"New functional family uses CC model.",
        "logic":"N/A if no new families.",
        "checklist":["N/A gate","Family Name","Family Behaviour","Component Levelling","Management/Audit"]},
    "ASE_ECD.1-7":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"New Functional Class — CC Model","req":"New functional class uses CC model.",
        "logic":"N/A if no new classes.",
        "checklist":["N/A gate","Class Name","Introduction","Family List","No code conflict"]},
    "ASE_ECD.1-8":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Assurance — CC Part 3 Model","req":"Extended assurance uses CC Part 3 model.",
        "logic":"N/A if no extended assurance.",
        "checklist":["N/A gate","Objectives","D elements","C elements","E elements"]},
    "ASE_ECD.1-9":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Assurance — Methodology","req":"Methodology per extended assurance component.",
        "logic":"N/A if no extended assurance.",
        "checklist":["N/A gate","Methodology per component","Methodology specific","Each E element covered"]},
    "ASE_ECD.1-10":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"New Assurance Family — CC Model","req":"New assurance family uses CC model.",
        "logic":"N/A if no new families.",
        "checklist":["N/A gate","Family Name","Objectives","Component Levelling"]},
    "ASE_ECD.1-11":{"fam":"ASE_ECD","cc":"ASE_ECD.1.4C","pp_dependent":False,"ext_dependent":True,
        "label":"New Assurance Class — CC Model","req":"New assurance class uses CC model.",
        "logic":"N/A if no new classes.",
        "checklist":["N/A gate","Class Name","Introduction","Family List","No code conflict"]},
    "ASE_ECD.1-12":{"fam":"ASE_ECD","cc":"ASE_ECD.1.5C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Components — Measurable and Objective","req":"Elements measurable and objective.",
        "logic":"N/A if no extended. No subjective language.",
        "checklist":["N/A gate","No subjective language","No vague qualifiers","Assignments completed"]},
    "ASE_ECD.1-13":{"fam":"ASE_ECD","cc":"ASE_ECD.1.5C","pp_dependent":False,"ext_dependent":True,
        "label":"Extended Components — Cannot Be Expressed Using Existing CC","req":"Cannot be expressed using existing CC.",
        "logic":"N/A if no extended. Refinement + Rename test.",
        "checklist":["N/A gate","Core function identified","CC Part 2/3 searched","Not a rename"]},
    "ASE_OBJ.2-1":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.1C","pp_dependent":False,"ext_dependent":False,
        "label":"Security Objectives Rationale — Tracing Matrix","req":"Rationale traces each objective to T/OSP/A.",
        "logic":"Explicit table. Every objective traced. Ground-Truth SPD IDs checked.",
        "checklist":["Explicit trace table present","Every objective traced","No floating objectives"]},
    "ASE_OBJ.2-2":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.1C","pp_dependent":False,"ext_dependent":False,
        "label":"SPD Coverage Completeness","req":"Rationale traces each T/OSP/A to at least one objective.",
        "logic":"All SPD IDs in rationale.",
        "checklist":["All Threats covered","All OSPs covered","All Assumptions covered"]},
    "ASE_OBJ.2-3":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.2C","pp_dependent":False,"ext_dependent":False,
        "label":"Countering Threats","req":"Objectives effective in countering threats.",
        "logic":"Specific rationale required.",
        "checklist":["Logical argument per threat","Mitigation specific","Rationale explains HOW"]},
    "ASE_OBJ.2-4":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.3C","pp_dependent":False,"ext_dependent":False,
        "label":"Fulfilling OSPs and Assumptions","req":"Objectives fulfill OSPs and assumptions.",
        "logic":"OSPs -> TOE obj. Assumptions -> OE obj.",
        "checklist":["OSPs fulfilled by TOE objective","Assumptions fulfilled by OE objective"]},
    "ASE_OBJ.2-5":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.4C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Objectives are for the TOE","req":"TOE objectives not stated as OE.",
        "logic":"No human tasks in TOE objectives.",
        "checklist":["TOE objectives describe technical functions only","No personnel tasks in TOE objectives"]},
    "ASE_OBJ.2-6":{"fam":"ASE_OBJ","cc":"ASE_OBJ.2.4C","pp_dependent":False,"ext_dependent":False,
        "label":"OE Objectives are for the Environment","req":"OE objectives not stated as TOE.",
        "logic":"No TOE technical functions in OE objectives.",
        "checklist":["OE objectives describe environment only","No TOE functions in OE objectives"]},
    "ASE_SPD.1-1":{"fam":"ASE_SPD","cc":"ASE_SPD.1.1C","pp_dependent":False,"ext_dependent":False,
        "label":"SPD — Threats Identification","req":"All threats identified.",
        "logic":"T.xxx ID + asset + adversary per threat.",
        "checklist":["Threat IDs present (T.xxx)","Assets identified","Adversaries identified","Threats relevant to TOE"]},
    "ASE_SPD.1-2":{"fam":"ASE_SPD","cc":"ASE_SPD.1.2C","pp_dependent":False,"ext_dependent":False,
        "label":"SPD — OSPs Identification","req":"All OSPs identified.",
        "logic":"OSP.xxx IDs. Policy statements.",
        "checklist":["OSP IDs present","OSPs describe policies","If no OSPs: None stated"]},
    "ASE_SPD.1-3":{"fam":"ASE_SPD","cc":"ASE_SPD.1.3C","pp_dependent":False,"ext_dependent":False,
        "label":"SPD — Assumptions Identification","req":"All assumptions identified.",
        "logic":"A.xxx IDs. Environmental conditions.",
        "checklist":["Assumption IDs present (A.xxx)","Assumptions relate to environment","No TOE functions in assumptions"]},
    "ASE_SPD.1-4":{"fam":"ASE_SPD","cc":"ASE_SPD.1.4C","pp_dependent":False,"ext_dependent":False,
        "label":"SPD — Internal Consistency","req":"SPD internally consistent.",
        "logic":"No contradictions. Consistent terminology.",
        "checklist":["No contradictions between T/OSP/A","Consistent terminology"]},
    "ASE_REQ.2-1":{"fam":"ASE_REQ","cc":"ASE_REQ.2.1C","pp_dependent":False,"ext_dependent":False,
        "label":"Subjects/Objects/Attributes Defined","req":"All subjects/objects/attributes defined.",
        "logic":"Every subject/object in SFRs defined.",
        "checklist":["All subjects defined","All objects defined","Security attributes defined"]},
    
    "ASE_REQ.2-2":{"fam":"ASE_REQ","cc":"ASE_REQ.2.2C","pp_dependent":False,"ext_dependent":False,
        "label":"SAR Description",
        "req":"Statement of security requirements describes the SARs.",
        "logic":"SAR section exists. SARs identified. Assurance package consistent.",
        "checklist":["SAR section present","SARs identified","Assurance package consistent","SAR descriptions present"]},
   
    "ASE_REQ.2-3":{"fam":"ASE_REQ","cc":"ASE_REQ.2.3C","pp_dependent":False,"ext_dependent":False,
        "label":"All Operations Identified","req":"All CC operations completed.",
        "logic":"No [] placeholders. Refinements explicit. Iterations distinguished.",
        "checklist":["All assignments completed","All selections completed","Refinements indicated","Iterations distinguished"]},

    "ASE_REQ.2-4":{"fam":"ASE_REQ","cc":"ASE_REQ.2.4C","pp_dependent":True,"ext_dependent":False,
        "label":"SAR Consistency with PP",
        "req":"SARs consistent with PP or PP-Configuration.",
        "logic":"N/A if no PP claim.",
        "checklist":["Applicability checked","SARs consistent with PP","No conflicting SARs"]},

    "ASE_REQ.2-5":{"fam":"ASE_REQ","cc":"ASE_REQ.2.5C","pp_dependent":True,"ext_dependent":False,
        "label":"Global SAR Set",
        "req":"Global SAR set defined for entire TOE.",
        "logic":"N/A if not multi-assurance.",
        "checklist":["Applicability checked","Global SAR set identified","SARs apply to TOE"]},

    "ASE_REQ.2-6":{"fam":"ASE_REQ","cc":"ASE_REQ.2.6C","pp_dependent":True,"ext_dependent":False,
        "label":"Sub-TSF SAR Definition",
        "req":"SARs defined for each sub-TSF.",
        "logic":"N/A if not multi-assurance.",
        "checklist":["Sub-TSF SARs identified","SARs identical or augmented","No undefined SARs"]},

    "ASE_REQ.2-7":{"fam":"ASE_REQ","cc":"ASE_REQ.2.7C","pp_dependent":True,"ext_dependent":False,
        "label":"Augmented SAR Rationale",
        "req":"Rationale provided for augmented SARs.",
        "logic":"Check augmented rationale section.",
        "checklist":["Augmented SARs identified","Rationale exists","Rationale technically justified"]},

    "ASE_REQ.2-8":{"fam":"ASE_REQ","cc":"ASE_REQ.2.8C","pp_dependent":False,"ext_dependent":False,
        "label":"Dependencies Satisfied","req":"All SFR dependencies satisfied.",
        "logic":"FAU_GEN.1->FPT_STM.1. FCS_COP.1->FCS_CKM.1+4. FIA_UAU->FIA_UID.1.",
        "checklist":["FAU_GEN.1->FPT_STM.1 satisfied","FCS_COP.1->FCS_CKM satisfied","FIA_UAU->FIA_UID.1 satisfied","All other dependencies satisfied"]},
    
    "ASE_REQ.2-9":{"fam":"ASE_REQ","cc":"ASE_REQ.2.9C","pp_dependent":False,"ext_dependent":False,
        "label":"Definitions of Terms",
        "req":"Subjects, objects, attributes, operations and entities defined.",
        "logic":"All technical entities defined.",
        "checklist":["Subjects defined","Objects defined","Operations defined","Entities defined"]},

    "ASE_REQ.2-10":{"fam":"ASE_REQ","cc":"ASE_REQ.2.10C","pp_dependent":False,"ext_dependent":False,
        "label":"Security Requirement Operations",
        "req":"All operations on security requirements identified.",
        "logic":"Assignments, selections, refinements identified.",
        "checklist":["Assignments identified","Selections identified","Refinements identified","Iterations identified"]},

    "ASE_REQ.2-11":{"fam":"ASE_REQ","cc":"ASE_REQ.2.11C","pp_dependent":False,"ext_dependent":False,
        "label":"Assignment Correctness",
        "req":"Assignment operations performed correctly.",
        "logic":"Assignments technically valid.",
        "checklist":["Assignments completed","Assignments valid","No placeholders"]},

    "ASE_REQ.2-12":{"fam":"ASE_REQ","cc":"ASE_REQ.2.12C","pp_dependent":False,"ext_dependent":False,
        "label":"SFR-to-Objective Rationale Completeness","req":"Each SFR traced to at least one TOE objective.",
        "logic":"Rationale table present. Every SFR mapped.",
        "checklist":["Rationale table present","Every SFR mapped to objective","No SFR unreferenced"]},

    "ASE_REQ.2-13":{"fam":"ASE_REQ","cc":"ASE_REQ.2.13C","pp_dependent":False,"ext_dependent":False,
        "label":"Selection Correctness",
        "req":"Selection operations performed correctly.",
        "logic":"Selections valid.",
        "checklist":["Selections completed","Selections valid","No invalid options"]},

    "ASE_REQ.2-14":{"fam":"ASE_REQ","cc":"ASE_REQ.2.14C","pp_dependent":False,"ext_dependent":False,
        "label":"Refinement Correctness",
        "req":"Refinement operations performed correctly.",
        "logic":"Refinements preserve meaning.",
        "checklist":["Refinements identified","No weakening introduced","Refinements valid"]},

    "ASE_REQ.2-15":{"fam":"ASE_REQ","cc":"ASE_REQ.2.15C","pp_dependent":False,"ext_dependent":False,
        "label":"Dependencies Satisfied or Justified",
        "req":"Dependencies satisfied or justified.",
        "logic":"Dependency analysis required.",
        "checklist":["Dependencies identified","Dependencies satisfied","Unsatisfied dependencies justified"]},
    
    "ASE_REQ.2-16":{"fam":"ASE_REQ","cc":"ASE_REQ.2.16C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Objectives Coverage by SFRs","req":"Each TOE objective traced to SFR.",
        "logic":"Every O.xxx has at least one SFR.",
        "checklist":["Every TOE objective covered by SFR","No TOE objective uncovered"]},

    "ASE_REQ.2-17":{"fam":"ASE_REQ","cc":"ASE_REQ.2.17C","pp_dependent":False,"ext_dependent":False,
        "label":"SAR Selection Rationale",
        "req":"Rationale explains why SARs chosen.",
        "logic":"Rationale explains assurance selection.",
        "checklist":["SAR rationale exists","Rationale technically justified","Consistent with EAL"]},

    "ASE_REQ.2-18":{"fam":"ASE_REQ","cc":"ASE_REQ.2.18C","pp_dependent":False,"ext_dependent":False,
        "label":"SFR Rationale Sufficiency","req":"SFR rationale demonstrates HOW each SFR meets objective.",
        "logic":"Specific rationale. No circular reasoning.",
        "checklist":["Rationale specific","Rationale explains HOW","No circular reasoning"]},

    "ASE_TSS.1-1":{"fam":"ASE_TSS","cc":"ASE_TSS.1.1C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Summary Specification — SFR Implementation","req":"TSS describes how each SFR is implemented.",
        "logic":"TSS section present. Each SFR has mechanism. Technical not paraphrase.",
        "checklist":["TSS section present","Each SFR has TSF mechanism","Descriptions technical not paraphrase","No SFR without TSS"]},
    
    "ASE_TSS.1-2":{"fam":"ASE_TSS","cc":"ASE_TSS.1.2C","pp_dependent":False,"ext_dependent":False,
        "label":"TOE Summary Specification — Non-Misleading","req":"TSS is non-misleading.",
        "logic":"TSS does not exceed SFRs. Consistent with scope.",
        "checklist":["TSS does not exceed SFRs","TSS consistent with scope","No contradictions"]},
}

SYSTEM_PROMPT_BASE="""You are a Junior RCC Evaluator (CEM:2022 Rev.1).
Audit ONE work unit. EVIDENCE VERBATIM from [PDF PAGE N]. NOT FOUND → INCONCLUSIVE.
CHECKLIST: PASS/FAIL/UNCLEAR per item. UNCLEAR→INCONCLUSIVE. FAIL→FAIL. All PASS→PASS.
OUTPUT single JSON only:
{"verdict":"PASS|FAIL|INCONCLUSIVE","confidence":0-100,"evidence":"[PDF PAGE X] verbatim","reasoning":"Step 1..Step 2..Step 3..","checklist":{"item":"PASS|FAIL|UNCLEAR"},"confidence_reason":"why"}"""

def build_unit_prompt(uid,st_text,few_shots=None,spd_gt=None,skill_level="junior_rcc",cot=True,neg=True,sem=True,calib=True):
    u=CRITERIA[uid]; chk="\n".join("- "+c for c in u.get("checklist",[]))
    shots=""
    if few_shots:
        shots="\nCONFIRMED EXAMPLES:\n"
        for s in few_shots[-2:]: shots+=f"[{uid}] Evidence:'{_to_str(s.get('evidence',''))[:60]}' → {s.get('verdict','')}\n"
    gt=""
    if spd_gt and any(x in uid for x in ("ASE_OBJ","ASE_SPD","ASE_REQ")):
        gt=f"\n[GROUND-TRUTH SPD IDs: {', '.join(spd_gt[:25])}]\n"
    skills=build_skill_injection(uid,skill_level,cot,neg,sem,calib)
    return (f"ST CONTENT:\n{'='*50}\n{st_text[:28000]}\n{'='*50}\n\n"
            f"{shots}{gt}{skills}"
            f"WORK UNIT: {uid}\nCC REF: {u.get('cc','')}\nREQ: {u.get('req','')}\n\n"
            f"LOGIC:\n{u.get('logic','')}\n\nCHECKLIST:\n{chk}\n\nOutput JSON for {uid} only.")

def _ollama_timeout_for_model(model):
    m = (model or "").lower()
    if "70b" in m or "72b" in m:
        return 2400
    if "mistral-small" in m or "32b" in m or "34b" in m:
        return 1800
    if "14b" in m or "13b" in m:
        return 900
    return 600

def _extract_json_object(raw):
    raw = _to_str(raw).strip()
    raw = re.sub(r"```(?:json)?\s*|```", "", raw, flags=re.IGNORECASE).strip()
    if not raw:
        return ""
    try:
        json.loads(raw)
        return raw
    except Exception:
        pass

    starts = [m.start() for m in re.finditer(r"\{", raw)]
    for start in starts:
        depth = 0
        in_str = False
        esc = False
        for pos in range(start, len(raw)):
            ch = raw[pos]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start:pos + 1]
                        if '"verdict"' in candidate:
                            return candidate
                        break
    return ""

def _parse_ollama_response(raw):
    json_text = _extract_json_object(raw)
    if not json_text:
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 20,
            "evidence": "LLM returned no parseable JSON",
            "reasoning": _to_str(raw)[:500],
            "checklist": {}
        }
    try:
        parsed = json.loads(json_text)
        return parsed if isinstance(parsed, dict) else {
            "verdict": "INCONCLUSIVE",
            "confidence": 20,
            "evidence": "LLM JSON was not an object",
            "reasoning": _to_str(parsed)[:500],
            "checklist": {}
        }
    except json.JSONDecodeError as e:
        return {
            "verdict": "INCONCLUSIVE",
            "confidence": 20,
            "evidence": "LLM JSON parse error",
            "reasoning": f"{e}: {json_text[:500]}",
            "checklist": {}
        }

def call_ollama(model,prompt):
    timeout = _ollama_timeout_for_model(model)
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT_BASE,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_ctx": 16384,
            "num_predict": 1400
        }
    }
    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=timeout)
        if resp.status_code == 404:
            raise RuntimeError(f"Model not found: ollama pull {model}")
        if resp.status_code == 400 and "format" in resp.text.lower():
            payload.pop("format", None)
            resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=timeout)
        if resp.status_code in (400, 413, 500) and len(prompt) > 7000:
            smaller = dict(payload)
            smaller["prompt"] = prompt[:14000]
            smaller["options"] = dict(payload["options"], num_ctx=8192, num_predict=1000)
            resp = requests.post("http://localhost:11434/api/generate", json=smaller, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout as e:
        if len(prompt) > 7000:
            try:
                retry_payload = dict(payload)
                retry_payload["prompt"] = prompt[:14000]
                retry_payload["options"] = dict(payload["options"], num_ctx=8192, num_predict=900)
                retry_payload.pop("format", None)
                resp = requests.post("http://localhost:11434/api/generate", json=retry_payload, timeout=max(timeout, 900))
                resp.raise_for_status()
                data = resp.json()
            except Exception as retry_error:
                raise RuntimeError(f"Ollama timeout after {timeout}s for model {model}; compact retry failed: {retry_error}") from e
        else:
            raise RuntimeError(f"Ollama timeout after {timeout}s for model {model}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError("Cannot connect to Ollama at http://localhost:11434. Start Ollama and load the selected model.") from e
    except requests.exceptions.RequestException as e:
        body = getattr(e.response, "text", "") if getattr(e, "response", None) is not None else ""
        raise RuntimeError(f"Ollama request failed: {e}. {body[:300]}") from e
    except ValueError as e:
        raise RuntimeError(f"Ollama returned non-JSON HTTP response: {resp.text[:300]}") from e

    if data.get("error"):
        raise RuntimeError(f"Ollama error: {data.get('error')}")

    done_reason = data.get("done_reason", "")
    parsed = _parse_ollama_response(data.get("response", ""))
    # Only penalise "length" (context window exceeded) — not other reasons
    # "stop" = normal, "" = normal, "length" = truncated output
    if done_reason == "length":
        cur_conf = parsed.get("confidence", 50)
        parsed["confidence"] = max(int(cur_conf) - 15, 30)
        parsed["reasoning"] = (f"[Ollama done_reason=length — output truncated]\n"
                               + _to_str(parsed.get("reasoning", "")))[:700]
    return parsed
def validate_evidence(evidence, st_text):
    """Validate AI evidence against ST text.
    
    Strategy (lenient — AI paraphrases, not verbatim copy):
    1. Trivial/empty evidence → pass (no penalty)
    2. Verbatim match → pass (best case)
    3. Key noun phrases (>=12 chars, all-alpha words) → pass if >=1 hit in 2+ probes
    4. Citation present [PDF PAGE N] with any content → pass (trust citation)
    5. Short evidence (<40 chars) → pass (model gave short answer, don't penalise)
    6. Only fail if evidence is long AND completely unmatched AND no citation
    """
    if not evidence or evidence.strip().upper() in ("N/A", "", "NOT FOUND", "—"):
        return True, ""
    
    # Strip page citations for content check
    has_citation = bool(re.search(r'\[PDF PAGE \d+', evidence))
    clean = re.sub(r'\[PDF PAGE \d+[^\]]*\]', '', evidence).strip()
    
    # Very short evidence — don't penalise
    if len(clean) < 40:
        return True, ""
    
    # If citation present + reasonable content → trust it
    if has_citation and len(clean) >= 20:
        return True, "Evidence has page citation"
    
    # Verbatim match
    if clean.lower() in st_text.lower():
        return True, "Evidence verified verbatim"
    
    # Key noun phrase extraction — words >=6 chars (nouns/technical terms)
    words = re.findall(r'\b[A-Za-z]{6,}\b', clean)
    # Use longer unique phrases (12+ chars) as probes
    phrases = list(dict.fromkeys(
        w for w in words
        if len(w) >= 6 and w.lower() not in {
            'should', 'shall', 'provide', 'include', 'contain', 'described',
            'define', 'defines', 'defined', 'according', 'following', 'document',
            'section', 'security', 'target', 'evaluation', 'criteria', 'common'
        }
    ))
    
    if not phrases:
        return True, ""
    
    # Need at least 2 unique probes to make a judgment
    if len(phrases) < 2:
        return True, ""
    
    # Check hits — lenient: 30% hit rate is enough (was 50%)
    hits = sum(1 for p in phrases[:10] if p.lower() in st_text.lower())
    hit_rate = hits / min(len(phrases), 10)
    
    if hit_rate >= 0.3:
        return True, f"Evidence key terms found ({hits}/{min(len(phrases),10)})"
    
    # Only mark as hallucination risk if very low hit rate AND no citation AND long evidence
    if hit_rate < 0.1 and not has_citation and len(clean) > 100:
        return False, f"Evidence not verified — possible hallucination risk ({hits}/{min(len(phrases),10)} terms found)"
    
    return True, "Evidence partially verified"

# ═══════════════════════════════════════════════════════════════════════════
# INLINE VALIDATION ENGINE (ported from validation.py)
# Formula: Schema(15) + Completeness(20) + Traceability(25) +
#          Confidence(15) + Hallucination Risk(15) + Consistency(10) = 100
# Verdict: READY>=85, REVIEW>=70, REJECT<70
# ═══════════════════════════════════════════════════════════════════════════
_VAL_WEIGHTS = {"schema":15,"completeness":20,"traceability":25,
                "confidence":15,"hallucination":15,"consistency":10}
_RISK_VAL    = {"LOW":1.0,"MEDIUM":0.5,"HIGH":0.0}
_CONS_OK     = {"CONSISTENT","HUMAN_OVERRIDDEN"}

def _val_traceable(r) -> bool:
    """Check if a Result object has traceable evidence (non-empty evidence field)."""
    ev = getattr(r,"evidence","") or ""
    return bool(ev.strip()) and len(ev.strip()) > 20

def _val_halluc_risk(r) -> str:
    """Infer hallucination risk from confidence score."""
    conf = getattr(r,"confidence",0) or 0
    if conf >= 85: return "LOW"
    if conf >= 60: return "MEDIUM"
    return "HIGH"

def _val_consistency(r) -> str:
    """Check consistency status."""
    if r.is_overridden(): return "HUMAN_OVERRIDDEN"
    return "CONSISTENT"

def run_inline_validation(results: list, model: str, toe_name: str,
                          scope_ids: list) -> dict:
    """Run validation formula on audit results. Returns validation dict."""
    total = len(results)
    if total == 0:
        return {"score":0.0,"verdict":"INVALID","error":"No results"}

    # Counts
    n_pass  = sum(1 for r in results if r.get_final_verdict()=="PASS" and not r.is_na)
    n_fail  = sum(1 for r in results if r.get_final_verdict()=="FAIL")
    n_inc   = sum(1 for r in results if r.get_final_verdict()=="INCONCLUSIVE")
    n_na    = sum(1 for r in results if r.is_na)

    # Traceability
    n_trace = sum(1 for r in results if _val_traceable(r))

    # Confidence (normalized 0-1)
    confs   = [max(0,min(100,getattr(r,"confidence",0) or 0))/100.0 for r in results]
    avg_cf  = sum(confs)/len(confs) if confs else 0.0

    # Hallucination risk
    risks   = [_RISK_VAL.get(_val_halluc_risk(r), 0.5) for r in results]
    avg_rk  = sum(risks)/len(risks) if risks else 0.0
    n_high  = sum(1 for r in results if _val_halluc_risk(r)=="HIGH")
    n_med   = sum(1 for r in results if _val_halluc_risk(r)=="MEDIUM")
    n_low   = sum(1 for r in results if _val_halluc_risk(r)=="LOW")

    # Consistency
    n_cons  = sum(1 for r in results if _val_consistency(r) in _CONS_OK)
    avg_cs  = n_cons/total

    # Expected work units
    expected = max(len(scope_ids), 76)

    # Score per dimension
    s_schema = _VAL_WEIGHTS["schema"]   # always 15 if we get results
    s_compl  = min(total/expected, 1.0) * _VAL_WEIGHTS["completeness"]
    s_trace  = (n_trace/total if total else 0) * _VAL_WEIGHTS["traceability"]
    s_conf   = avg_cf * _VAL_WEIGHTS["confidence"]
    s_halluc = avg_rk * _VAL_WEIGHTS["hallucination"]
    s_cons   = avg_cs * _VAL_WEIGHTS["consistency"]
    total_score = round(s_schema+s_compl+s_trace+s_conf+s_halluc+s_cons, 2)

    if total_score >= 85:   verdict = "READY"
    elif total_score >= 70: verdict = "REVIEW"
    else:                   verdict = "REJECT"

    # Per-family breakdown
    families = {}
    for r in results:
        fam = r.id.rsplit(".",1)[0] if "." in r.id else r.id.rsplit("-",1)[0]
        if fam not in families:
            families[fam] = {"pass":0,"fail":0,"inc":0,"na":0,
                              "conf_sum":0,"n":0,"high_h":0}
        fv = r.get_final_verdict()
        families[fam]["n"] += 1
        families[fam]["conf_sum"] += max(0,min(100,getattr(r,"confidence",0) or 0))
        if r.is_na:         families[fam]["na"] += 1
        elif fv=="PASS":    families[fam]["pass"] += 1
        elif fv=="FAIL":    families[fam]["fail"] += 1
        else:               families[fam]["inc"] += 1
        if _val_halluc_risk(r)=="HIGH": families[fam]["high_h"] += 1

    # Human review priority per family
    review_priority = []
    for fam, fs in sorted(families.items()):
        avg_fam_conf = fs["conf_sum"]/fs["n"] if fs["n"] else 0
        inc_rate = fs["inc"]/fs["n"] if fs["n"] else 0
        if inc_rate >= 0.5 or avg_fam_conf < 70:
            priority = "HIGH"
        elif inc_rate >= 0.25 or avg_fam_conf < 80:
            priority = "MEDIUM"
        else:
            priority = "LOW"
        review_priority.append({
            "family":fam, "pass":fs["pass"],"fail":fs["fail"],
            "inc":fs["inc"],"na":fs["na"],
            "avg_conf":round(avg_fam_conf,1),
            "high_h":fs["high_h"],"priority":priority
        })

    return {
        "model":       model,
        "toe_name":    toe_name,
        "total_units": total,
        "n_pass":      n_pass,
        "n_fail":      n_fail,
        "n_inc":       n_inc,
        "n_na":        n_na,
        "n_trace":     n_trace,
        "trace_pct":   round(n_trace/total*100,1) if total else 0,
        "avg_conf":    round(avg_cf*100,1),
        "n_high_h":    n_high,
        "n_med_h":     n_med,
        "n_low_h":     n_low,
        "n_cons":      n_cons,
        "score":       total_score,
        "score_schema":   round(s_schema,2),
        "score_compl":    round(s_compl,2),
        "score_trace":    round(s_trace,2),
        "score_conf":     round(s_conf,2),
        "score_halluc":   round(s_halluc,2),
        "score_cons":     round(s_cons,2),
        "verdict":        verdict,
        "family_breakdown": review_priority,
    }


def render_validation_result(val: dict):
    """Render validation result card in Streamlit after audit completes."""
    import streamlit as st
    verdict = val.get("verdict","?")
    score   = val.get("score",0)
    model   = val.get("model","?")

    # Color scheme per verdict
    vcolor  = {"READY":"#3fb950","REVIEW":"#d29922","REJECT":"#f85149"}.get(verdict,"#8b949e")
    vbg     = {"READY":"rgba(63,185,80,.08)","REVIEW":"rgba(210,153,34,.08)",
               "REJECT":"rgba(248,81,73,.08)"}.get(verdict,"rgba(110,118,129,.08)")
    vborder = {"READY":"rgba(63,185,80,.3)","REVIEW":"rgba(210,153,34,.3)",
               "REJECT":"rgba(248,81,73,.3)"}.get(verdict,"rgba(110,118,129,.3)")

    # Verdict icon
    vicon   = {"READY":"✅","REVIEW":"🔍","REJECT":"❌"}.get(verdict,"❓")

    st.markdown(f"""
<div style="background:{vbg};border:1px solid {vborder};border-left:5px solid {vcolor};
  border-radius:0 14px 14px 0;padding:1.1rem 1.3rem;margin:1rem 0;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;">
    <div>
      <span style="font-size:1.1rem;font-weight:900;color:{vcolor};">{vicon} {verdict}</span>
      <span style="font-size:.75rem;color:#8b949e;margin-left:.75rem;">
        Validation Score: <b style="color:{vcolor};">{score:.1f}/100</b>
      </span>
    </div>
    <div style="font-size:.72rem;color:#8b949e;font-family:var(--mono);">
      Model: {html.escape(model)}
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # Score breakdown bar
    dims = [
        ("Schema",        val.get("score_schema",0),  15,  "#58a6ff"),
        ("Completeness",  val.get("score_compl",0),   20,  "#79c0ff"),
        ("Traceability",  val.get("score_trace",0),   25,  "#3fb950"),
        ("Confidence",    val.get("score_conf",0),    15,  "#d29922"),
        ("Halluc. Risk",  val.get("score_halluc",0),  15,  "#ffa657"),
        ("Consistency",   val.get("score_cons",0),    10,  "#bc8cff"),
    ]
    # Build horizontal stacked bar with HTML
    bar_segs = ""
    for label, pts, maxpts, clr in dims:
        pct = pts/100*100  # percentage of 100 total
        bar_segs += (
            f'<div style="width:{pct:.1f}%;background:{clr};height:100%;'
            f'display:inline-block;vertical-align:top;" '
            f'title="{label}: {pts:.1f}/{maxpts}"></div>'
        )
    bar_labels = " ".join(
        f'<span style="font-size:.65rem;color:#8b949e;">'
        f'<span style="color:{clr};">■</span> {label} {pts:.1f}/{maxpts}'
        f'</span>'
        for label, pts, maxpts, clr in dims
    )
    st.markdown(f"""
<div style="margin:.5rem 0;">
  <div style="width:100%;height:18px;background:rgba(110,118,129,.2);border-radius:9px;
    overflow:hidden;">{bar_segs}</div>
  <div style="margin-top:.4rem;display:flex;flex-wrap:wrap;gap:.5rem;">{bar_labels}</div>
</div>""", unsafe_allow_html=True)

    # Key metrics
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("✅ PASS",  val.get("n_pass",0))
    c2.metric("❌ FAIL",  val.get("n_fail",0))
    c3.metric("⚠️ INC",   val.get("n_inc",0))
    c4.metric("📊 Trace", f"{val.get('trace_pct',0):.0f}%")
    c5.metric("🔴 HIGH_H", val.get("n_high_h",0))

    # Family breakdown table
    fam_data = val.get("family_breakdown",[])
    if fam_data:
        with st.expander("📋 Per-Family CEM Breakdown & Review Priority", expanded=True):
            pri_color = {"HIGH":"#f85149","MEDIUM":"#d29922","LOW":"#3fb950"}
            header = (
                '<div style="display:grid;grid-template-columns:130px 50px 50px 50px 70px 80px 90px;'
                'gap:.3rem;font-size:.68rem;font-weight:700;color:#8b949e;'
                'border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:.3rem;margin-bottom:.3rem;">'
                '<div>Family</div><div>PASS</div><div>FAIL</div><div>INC</div>'
                '<div>AvgConf%</div><div>HIGH_H</div><div>Review Pri.</div></div>'
            )
            rows_html = ""
            for f in fam_data:
                pc = pri_color.get(f["priority"],"#8b949e")
                fam_id = html.escape(f["family"])
                rows_html += (
                    f'<div style="display:grid;grid-template-columns:130px 50px 50px 50px 70px 80px 90px;'
                    f'gap:.3rem;font-size:.72rem;padding:.2rem 0;'
                    f'border-bottom:1px solid rgba(255,255,255,.05);">'
                    f'<div style="font-family:var(--mono);color:var(--accent);">{fam_id}</div>'
                    f'<div style="color:#3fb950;">{f["pass"]}</div>'
                    f'<div style="color:{("#f85149" if f["fail"]>0 else "#3fb950")};">{f["fail"]}</div>'
                    f'<div style="color:{("#d29922" if f["inc"]>0 else "#3fb950")};">{f["inc"]}</div>'
                    f'<div>{f["avg_conf"]:.0f}%</div>'
                    f'<div style="color:{("#f85149" if f["high_h"]>0 else "#3fb950")};">{f["high_h"]}</div>'
                    f'<div><span style="background:{pc}20;color:{pc};font-size:.66rem;font-weight:700;'
                    f'padding:1px 7px;border-radius:10px;">{f["priority"]}</span></div>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="background:var(--bg2);border:1px solid var(--border);'
                f'border-radius:10px;padding:.75rem 1rem;">{header}{rows_html}</div>',
                unsafe_allow_html=True
            )

            # Legend
            st.markdown("""<div style="font-size:.68rem;color:#6e7681;margin-top:.5rem;">
              🔴 HIGH: INC ≥50% atau AvgConf &lt;70% — review semua INC unit
              &nbsp;|&nbsp; 🟡 MEDIUM: INC ≥25% atau AvgConf &lt;80% — review INC &lt;0.75
              &nbsp;|&nbsp; 🟢 LOW: AI reliable — spot-check saja
            </div>""", unsafe_allow_html=True)

    # Recommendation box
    reco = {
        "READY": ("✅ Workbook siap dikirim ke Lead Evaluator.",
                  "Lakukan human review hanya pada work unit dengan confidence < 85% atau FAIL.",
                  "#3fb950"),
        "REVIEW": ("🔍 Workbook perlu review sebelum dikirim ke Lead.",
                   "Review semua family dengan priority HIGH/MEDIUM. Utamakan INCONCLUSIVE dan FAIL.",
                   "#d29922"),
        "REJECT": ("❌ Workbook tidak layak dikirim ke Lead dalam kondisi ini.",
                   "Terlalu banyak INCONCLUSIVE atau confidence rendah. Pertimbangkan ganti model atau review ulang ST upload.",
                   "#f85149"),
    }.get(verdict, ("","","#8b949e"))

    st.markdown(f"""
<div style="background:rgba(0,0,0,.15);border-left:4px solid {reco[2]};
  border-radius:0 10px 10px 0;padding:.75rem 1rem;margin:.75rem 0;">
  <div style="font-weight:700;color:{reco[2]};font-size:.82rem;">{reco[0]}</div>
  <div style="color:#8b949e;font-size:.78rem;margin-top:.25rem;">{reco[1]}</div>
</div>""", unsafe_allow_html=True)


def run_audit(model,st_text,meta,scope_ids,few_shot_db,progress_cb=None,
              skill_level="junior_rcc",cot=True,neg=True,sem=True,calib=True):
    results=[]
    has_ext=meta.get("has_ext",False); has_pp=meta.get("has_pp",False); spd_gt=meta.get("spd_ids",[])
    for i,uid in enumerate(scope_ids):
        if progress_cb: progress_cb(i,len(scope_ids),uid)
        u=CRITERIA.get(uid,{}); label=u.get("label",uid)
        if u.get("ext_dependent",False) and not has_ext:
            results.append(Result(uid,label,"PASS",100,"N/A","N/A — no _EXT.",is_na=True,validation_note="ext_dependent -> N/A")); continue
        if u.get("pp_dependent",False) and not has_pp:
            results.append(Result(uid,label,"PASS",100,"N/A","N/A — no PP.",is_na=True,validation_note="pp_dependent -> N/A")); continue
        # ── DETERMINISTIC SHORTCUTS for CCL and ECD family ──────────────
        # CCL.1-2: PP conformance claim — if no PP referenced → N/A PASS
        if uid in ("ASE_CCL.1-2","ASE_CCL.1-3","ASE_CCL.1-4"):
            vc2 = check_cc_version(st_text)
            if uid == "ASE_CCL.1-2":
                if vc2.get("pp_none"):
                    results.append(Result(uid,label,"PASS",97,
                        "Deterministic PP claim",
                        "[DETERMINISTIC — N/A] Tidak ada PP conformance claim dalam ST. "
                        "ASE_CCL.1-2 tidak applicable → PASS.")); continue
                elif vc2.get("pp_claim"):
                    results.append(Result(uid,label,"PASS",90,
                        "Deterministic PP claim",
                        "[DETERMINISTIC] PP conformance claim ditemukan. "
                        "Verifikasi identitas PP oleh evaluator.")); continue
            elif uid == "ASE_CCL.1-3":
                pkg = vc2.get("package","")
                if pkg:
                    results.append(Result(uid,label,"PASS",95,
                        "Deterministic package claim",
                        f"[DETERMINISTIC] Package claim teridentifikasi: {pkg}. "
                        "EAL/CAP package sesuai CC.")); continue
            elif uid == "ASE_CCL.1-4":
                # EAL augmentation — check if augmentation mentioned
                has_aug = bool(re.search(r"augmented|\+|avmsec|alc_tda|ase_tsfi",
                                         st_text.lower()))
                if not has_aug:
                    results.append(Result(uid,label,"PASS",90,
                        "Deterministic augmentation",
                        "[DETERMINISTIC] Tidak ada augmentation eksplisit ditemukan. "
                        "Package sesuai baseline EAL/CAP tanpa augmentation.")); continue
        # ── ECD sub-units ──────────────────────────────────────────────────
        if uid in ("ASE_ECD.1-2","ASE_ECD.1-3"):
            r2b = check_ecd1(st_text)
            if r2b.get("na"):
                results.append(Result(uid,label,"PASS",95,
                    "CC Part 2/3 catalogue",
                    f"[DETERMINISTIC — N/A] Tidak ada Extended Component → "
                    f"ASE_ECD.1 tidak applicable. {r2b['note']}")); continue
        if uid=="ASE_CCL.1-1":
            vc=check_cc_version(st_text)
            det_note = (
                f"[DETERMINISTIC] CC Edition + PP Conformance + Package\n"
                f"PP Claim: {'Ada (direferensikan)' if vc.get('pp_claim') else ('Tidak ada / N/A' if vc.get('pp_none') else 'Tidak diidentifikasi eksplisit')}\n"
                f"Package: {vc.get('package','Tidak teridentifikasi')}\n"
                f"{vc['reasoning']}"
            )
            results.append(Result(uid,label,vc["verdict"],vc["conf"],"Deterministic CC edition",det_note)); continue
        if uid=="ASE_ECD.1-1":
            r2=check_ecd1(st_text)
            na_tag = "[N/A — AUTO PASS] " if r2.get("na") else "[DETERMINISTIC] "
            ecd_note = (
                f"{na_tag}CC Component Catalogue Check\n"
                f"{r2['note']}\n"
                f"Standard: {len(r2['standard'])} | Extended: {len(r2['extended'])} | Unknown: {len(r2['unknown'])} | Typo: {len(r2['typo'])}"
            )
            results.append(Result(uid,label,r2["verdict"],r2["conf"],"CC Part 2/3 catalogue",
                ecd_note,
                extra={"standard":r2["standard"],"extended":r2["extended"],
                       "unknown":r2["unknown"],"typo":r2["typo"],"na":r2.get("na",False)})); continue
        shots=few_shot_db.get(uid,[])
        prompt=build_unit_prompt(uid,st_text[:12500],shots,spd_gt,skill_level,cot,neg,sem,calib)
        try: raw=call_ollama(model,prompt)
        except Exception as e:
            results.append(Result(uid,label,"INCONCLUSIVE",0,"Ollama request failed",str(e),needs_review=True)); continue
        vr=_to_str(raw.get("verdict","INCONCLUSIVE")).upper()
        if "PASS" in vr and "FAIL" not in vr: verdict="PASS"
        elif "FAIL" in vr: verdict="FAIL"
        else: verdict="INCONCLUSIVE"
        conf=max(0,min(100,int(raw.get("confidence",50))))
        ev=_to_str(raw.get("evidence",""))
        rsn=_to_str(raw.get("reasoning",""))
        cr=_to_str(raw.get("confidence_reason",""))
        chk_raw=raw.get("checklist",{})
        if not isinstance(chk_raw,dict): chk_raw={}
        n_unclear = sum(1 for v in chk_raw.values() if "UNCLEAR" in str(v).upper())
        if n_unclear >= 2 and verdict=="PASS":
            # Only downgrade if 2+ checklist items are UNCLEAR (not just 1)
            verdict="INCONCLUSIVE"; conf=max(conf-15,40); rsn=f"[AUTO-DOWNGRADE: {n_unclear} UNCLEAR checklist items]\n"+rsn
        ev_valid,ev_note=validate_evidence(ev,st_text)
        if not ev_valid:
            # Soft downgrade: note the risk but don't force INCONCLUSIVE
            # Only force INCONCLUSIVE if model was already uncertain (conf<60)
            if conf < 60:
                verdict="INCONCLUSIVE"
            conf=max(conf-15,30)   # was -30, now -15 (less aggressive)
            rsn="[EVIDENCE RISK]\n"+ev_note+"\n"+rsn
        r_obj=Result(uid,label,verdict,conf,ev[:600],(rsn+("\n[Conf:"+cr+"]" if cr else ""))[:700],
                     evidence_valid=ev_valid,validation_note=ev_note,needs_review=conf<get_review_threshold(model))
        if verdict=="PASS" and conf>=get_review_threshold(model):
            few_shot_db.setdefault(uid,[]).append({"verdict":verdict,"evidence":ev[:100],"reasoning":rsn[:100]})
        results.append(r_obj)
    return results

# ── PDF Export ──
def generate_workbook_pdf(results, meta, ev_name, lead_name, eal, toe, version, pid, skill_level="—"):
    """Generate Workbook ASE PDF — format FR.MT.04.WB (landscape A4).
    Columns: No | Evaluation Action | Evaluation Component | CC Component Requirement |
             CEM Reference | Evaluator Justification | Overall Verdict | EOR No.
    """
    if not REPORTLAB_OK: return None
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, HRFlowable, PageBreak, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = BytesIO()
    PAGE = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=PAGE,
        rightMargin=8*mm, leftMargin=8*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()

    # ── Colours ──────────────────────────────────────────────────────────
    NAVY   = colors.HexColor("#1F4E79")
    MID    = colors.HexColor("#2E75B6")
    LIGHT  = colors.HexColor("#D6E4F0")
    PASS_C = colors.HexColor("#375623")
    FAIL_C = colors.HexColor("#C00000")
    INC_C  = colors.HexColor("#7F6000")
    NA_C   = colors.HexColor("#595959")
    GREY   = colors.HexColor("#595959")
    ALT    = colors.HexColor("#EBF3FB")
    WHITE  = colors.white
    PASS_B = colors.HexColor("#E2EFDA")
    FAIL_B = colors.HexColor("#FCE4D6")
    INC_B  = colors.HexColor("#FFF2CC")
    NA_B   = colors.HexColor("#F2F2F2")

    # ── Paragraph styles ─────────────────────────────────────────────────
    hdr_st  = ParagraphStyle("hdr", parent=styles["Normal"],
                fontSize=8, textColor=WHITE, fontName="Helvetica-Bold",
                alignment=1, leading=10)
    just_st = ParagraphStyle("just", parent=styles["Normal"],
                fontSize=8, textColor=colors.HexColor("#1F2937"),
                fontName="Helvetica", leading=10, spaceAfter=2)
    just_it = ParagraphStyle("just_it", parent=styles["Normal"],
                fontSize=8, textColor=colors.HexColor("#2E75B6"),
                fontName="Helvetica-Oblique", leading=10)
    verdict_st = ParagraphStyle("verd", parent=styles["Normal"],
                fontSize=9, fontName="Helvetica-Bold", alignment=1, leading=11)
    cem_st  = ParagraphStyle("cem", parent=styles["Normal"],
                fontSize=7.5, textColor=MID, fontName="Helvetica-Bold",
                alignment=1, leading=10)
    tiny    = ParagraphStyle("tiny", parent=styles["Normal"],
                fontSize=7, textColor=GREY, fontName="Helvetica", leading=9)
    sec_st  = ParagraphStyle("sec", parent=styles["Normal"],
                fontSize=9, textColor=WHITE, fontName="Helvetica-Bold",
                leading=11)

    W = PAGE[0] - 16*mm  # usable width ~251mm (landscape A4)

    # Column widths (mm) — must sum to ~251
    # No(8) | Action(18) | Component(22) | CC Req(58) | CEM(14) | Justification(87) | Verdict(16) | EOR(10) = 233 mm (fits)
    CW = [c*mm for c in [8, 18, 22, 58, 14, 87, 16, 10]]

    def verdict_color(v):
        if v == "PASS":         return PASS_C, PASS_B
        if v == "FAIL":         return FAIL_C, FAIL_B
        if v == "INCONCLUSIVE": return INC_C,  INC_B
        if v == "N/A":          return NA_C,   NA_B
        return colors.black, WHITE

    # ── Helper: build one data row ────────────────────────────────────────
    def make_row(r_obj, idx):
        uid   = r_obj.id
        fv    = r_obj.get_final_verdict()
        ev    = r_obj.evidence or ""
        rsn   = r_obj.reasoning or ""
        conf  = getattr(r_obj, "confidence", 0) or 0
        ov    = r_obj.is_overridden()
        ov_v  = r_obj.human_verdict if ov else ""
        ov_c  = r_obj.human_comment if ov else ""

        cc_req = CRITERIA.get(uid, {}).get("req", "See CC Part 2/3")
        cem_ref = uid  # CEM work unit ID

        # Justification: evidence + reasoning + override note
        just_lines = []
        if ev.strip():
            just_lines.append(f"[Evidence] {ev[:200]}")
        if rsn.strip():
            just_lines.append(f"[Reasoning] {rsn[:180]}")
        if ov and ov_c:
            just_lines.append(f"[Override → {ov_v}] {ov_c[:120]}")
        if r_obj.is_na:
            just_lines = [f"[N/A] Work unit tidak applicable untuk TOE ini."]
        just_text = "\n".join(just_lines) or "—"


        vc, vbg = verdict_color(fv if not ov else ov_v)
        fill    = ALT if idx % 2 == 0 else WHITE
        eor_no  = "—"  # filled when EOR exists

        # Truncate for cell fit
        def tp(txt, maxc=320):
            return (txt[:maxc]+"…") if len(txt)>maxc else txt

        # CC component text (short)
        cc_short = CRITERIA.get(uid, {}).get("cc","") or uid

        return [
            Paragraph(str(idx), verdict_st),
            Paragraph(f"{uid.split('.')[0]}.1.1E", just_st),
            Paragraph(f"<b>{uid}</b>", ParagraphStyle("uid",parent=just_st,
                textColor=MID.clone() if hasattr(MID,'clone') else MID,
                fontName="Helvetica-Bold")),
            Paragraph(tp(cc_short, 300), just_st),
            Paragraph(f"<b>{uid}</b>", cem_st),
            Paragraph(tp(just_text, 500), just_st),
            Paragraph(f"<b>{fv if not ov else ov_v}</b>",
                ParagraphStyle("vv",parent=verdict_st,
                    textColor=vc)),
            Paragraph(eor_no, tiny),
        ], fill, vbg

    # ── Build flowables ───────────────────────────────────────────────────
    story = []

    # Cover / Identification block
    id_data = [
        [Paragraph("<b>Judul Evaluasi</b>", just_st),
         Paragraph(f"{toe} — Workbook Kelas ASE", just_st),
         Paragraph("<b>Nomor Workbook</b>", just_st),
         Paragraph(f"WB-ASE-{pid or '—'}", just_st)],
        [Paragraph("<b>TOE</b>", just_st),
         Paragraph(f"{toe} v{version}", just_st),
         Paragraph("<b>EAL Target</b>", just_st),
         Paragraph(f"<b>{eal}</b>", ParagraphStyle("eal",parent=just_st,
             textColor=PASS_C,fontName="Helvetica-Bold"))],
        [Paragraph("<b>Evaluator</b>", just_st),
         Paragraph(ev_name or "—", just_st),
         Paragraph("<b>Lead Evaluator</b>", just_st),
         Paragraph(lead_name or "—", just_st)],
        [Paragraph("<b>Tanggal Audit</b>", just_st),
         Paragraph(datetime.now().strftime("%d %B %Y"), just_st),
         Paragraph("<b>Standar</b>", just_st),
         Paragraph("CC:2022 R1 | CEM:2022 R1 | SNI ISO/IEC 15408:2022", just_st)],
    ]
    id_t = Table(id_data, colWidths=[30*mm, 70*mm, 30*mm, 70*mm])
    id_t.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("BACKGROUND",(0,0),(0,-1),LIGHT),
        ("BACKGROUND",(2,0),(2,-1),LIGHT),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("PADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story.append(Paragraph(f"<b>WORKBOOK EVALUASI KEAMANAN — KELAS ASE</b>  |  "
                           f"CC:2022 R1  |  FR.MT.04.WB",
                ParagraphStyle("title",parent=styles["Normal"],
                    fontSize=11,textColor=NAVY,fontName="Helvetica-Bold",
                    spaceBefore=0,spaceAfter=4)))
    story.append(id_t)
    story.append(Spacer(1, 4*mm))

    # ── TABLE HEADER ROW ──────────────────────────────────────────────────
    hdr_row = [
        Paragraph("No.", hdr_st),
        Paragraph("Evaluation\nAction", hdr_st),

        Paragraph("Evaluation\nComponent", hdr_st),

        Paragraph("CC Component Requirement", hdr_st),
        Paragraph("CEM\nRef.", hdr_st),

        Paragraph("Evaluator Justification", hdr_st),
        Paragraph("Overall\nVerdict", hdr_st),
        Paragraph("EOR\nNo.", hdr_st),
    ]



    # ── BUILD DATA BY FAMILY ───────────────────────────────────────────────
    families = {}
    for r_obj in results:
        uid = r_obj.id
        # Derive family from UID (e.g. ASE_CCL.1-1 → ASE_CCL.1)
        parts = uid.rsplit("-",1)
        fam = parts[0] if len(parts)==2 else uid
        if fam not in families: families[fam] = []
        families[fam].append(r_obj)

    FAMILY_LABELS = {
        "ASE_CCL.1": "ASE_CCL.1 — Conformance Claim",
        "ASE_ECD.1": "ASE_ECD.1 — Extended Components Definition",
        "ASE_INT.1": "ASE_INT.1 — ST Introduction",
        "ASE_OBJ.2": "ASE_OBJ.2 — Security Objectives",
        "ASE_SPD.1": "ASE_SPD.1 — Security Problem Definition",
        "ASE_REQ.2": "ASE_REQ.2 — Security Requirements",
        "ASE_TSS.1": "ASE_TSS.1 — TOE Summary Specification",
    }

    all_rows = [hdr_row]
    row_styles = [
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),NAVY),
        ("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("PADDING",(0,0),(-1,-1),4),
        ("ALIGN",(0,1),(0,-1),"CENTER"),    # No.
        ("ALIGN",(4,1),(4,-1),"CENTER"),    # CEM ref
        ("ALIGN",(6,1),(6,-1),"CENTER"),    # Verdict
        ("ALIGN",(7,1),(7,-1),"CENTER"),    # EOR No.
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("LEADING",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,ALT]),
    ]

    global_row_idx = 1  # row 0 is header

    for fam_key in ["ASE_CCL.1","ASE_ECD.1","ASE_INT.1","ASE_OBJ.2",
                    "ASE_SPD.1","ASE_REQ.2","ASE_TSS.1"]:
        fam_results = families.get(fam_key, [])
        if not fam_results: continue

        # Section header row (full-width span)
        sec_row = [Paragraph(f"<b>{FAMILY_LABELS.get(fam_key,fam_key)}</b>"
                             f"  —  {len(fam_results)} Work Units",
                             sec_st),
                   "","","","","","",""]
        all_rows.append(sec_row)
        row_styles.append(("BACKGROUND",(0,global_row_idx),(-1,global_row_idx),
                           colors.HexColor("#2F5496")))
        row_styles.append(("SPAN",(0,global_row_idx),(-1,global_row_idx)))
        row_styles.append(("TOPPADDING",(0,global_row_idx),(-1,global_row_idx),7))
        row_styles.append(("BOTTOMPADDING",(0,global_row_idx),(-1,global_row_idx),7))
        global_row_idx += 1

        # Work unit rows
        for i, r_obj in enumerate(fam_results):
            row_data, fill, vbg = make_row(r_obj, i)
            all_rows.append(row_data)
            # Verdict cell background
            fv = r_obj.get_final_verdict()
            if r_obj.is_overridden(): fv = r_obj.human_verdict
            vc, vbg2 = verdict_color(fv)
            row_styles.append(("BACKGROUND",(6,global_row_idx),(6,global_row_idx), vbg2))
            row_styles.append(("TEXTCOLOR",(6,global_row_idx),(6,global_row_idx), vc))
            if i % 2 == 0:
                row_styles.append(("BACKGROUND",(0,global_row_idx),(5,global_row_idx), ALT))
                row_styles.append(("BACKGROUND",(7,global_row_idx),(7,global_row_idx), ALT))
            global_row_idx += 1

    wb_table = Table(all_rows, colWidths=CW, repeatRows=1)
    wb_table.setStyle(TableStyle(row_styles))
    story.append(wb_table)
    story.append(Spacer(1, 5*mm))

    # ── SUMMARY ───────────────────────────────────────────────────────────
    n_p  = sum(1 for r in results if r.get_final_verdict()=="PASS" or
               (r.is_overridden() and r.human_verdict=="PASS"))
    n_f  = sum(1 for r in results if (r.get_final_verdict()=="FAIL" and not r.is_overridden()) or
               (r.is_overridden() and r.human_verdict=="FAIL"))
    n_i  = sum(1 for r in results if (r.get_final_verdict()=="INCONCLUSIVE" and not r.is_overridden()) or
               (r.is_overridden() and r.human_verdict=="INCONCLUSIVE"))
    n_na = sum(1 for r in results if r.is_na)

    sum_data = [
        [Paragraph("<b>RINGKASAN HASIL EVALUASI</b>", hdr_st), "", "", ""],
        [Paragraph("Total Work Units", just_st),
         Paragraph(f"<b>{len(results)}</b>", verdict_st),
         Paragraph("PASS", ParagraphStyle("ps",parent=verdict_st,textColor=PASS_C)),
         Paragraph(f"<b>{n_p}</b>", ParagraphStyle("ps",parent=verdict_st,textColor=PASS_C))],
        [Paragraph("Evaluator", just_st),
         Paragraph(ev_name or "—", just_st),
         Paragraph("FAIL", ParagraphStyle("fs",parent=verdict_st,textColor=FAIL_C)),
         Paragraph(f"<b>{n_f}</b>", ParagraphStyle("fs",parent=verdict_st,textColor=FAIL_C))],
        [Paragraph("Lead Evaluator", just_st),
         Paragraph(lead_name or "—", just_st),
         Paragraph("INCONCLUSIVE", ParagraphStyle("is",parent=verdict_st,textColor=INC_C)),
         Paragraph(f"<b>{n_i}</b>", ParagraphStyle("is",parent=verdict_st,textColor=INC_C))],
        [Paragraph("Tanggal", just_st),
         Paragraph(datetime.now().strftime("%d %B %Y"), just_st),
         Paragraph("N/A", ParagraphStyle("ns",parent=verdict_st,textColor=NA_C)),
         Paragraph(f"<b>{n_na}</b>", ParagraphStyle("ns",parent=verdict_st,textColor=NA_C))],
    ]
    sum_t = Table(sum_data, colWidths=[40*mm,80*mm,40*mm,40*mm])
    sum_t.setStyle(TableStyle([
        ("SPAN",(0,0),(-1,0)),
        ("BACKGROUND",(0,0),(-1,0),NAVY),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("PADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,1),(1,-1),LIGHT),
    ]))
    story.append(sum_t)

    doc.build(story)
    buf.seek(0)
    return buf


def generate_eor_pdf(eor: dict, ev_name: str, lead_name: str) -> BytesIO:
    """Generate EOR PDF matching FR.MT.04.11 format exactly:
    Cover | Section 1 EOR Identification | Signature Block | Section 2 Observation Table
    """
    if not REPORTLAB_OK: return None
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, HRFlowable, PageBreak, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    W = 210*mm - 30*mm  # A4 usable width

    # ── Colours ─────────────────────────────────────────────────────────
    NAVY   = colors.HexColor("#1F4E79")
    MID    = colors.HexColor("#2E75B6")
    LIGHT  = colors.HexColor("#D6E4F0")
    COVER  = colors.HexColor("#1A2B4A")
    RED    = colors.HexColor("#C00000")
    PASS_C = colors.HexColor("#375623")
    PASS_B = colors.HexColor("#E2EFDA")
    FAIL_C = colors.HexColor("#C00000")
    FAIL_B = colors.HexColor("#FCE4D6")
    INC_C  = colors.HexColor("#7F6000")
    INC_B  = colors.HexColor("#FFF2CC")
    GREY   = colors.HexColor("#595959")
    ALT    = colors.HexColor("#F7FBFF")
    WHITE  = colors.white
    ORANGE = colors.HexColor("#ED7D31")

    # ── Paragraph styles ────────────────────────────────────────────────
    norm  = ParagraphStyle("n",  parent=styles["Normal"], fontSize=9,  fontName="Helvetica",  leading=12, spaceAfter=2)
    normi = ParagraphStyle("ni", parent=styles["Normal"], fontSize=9,  fontName="Helvetica-Oblique", leading=12, textColor=GREY)
    bold9 = ParagraphStyle("b9", parent=styles["Normal"], fontSize=9,  fontName="Helvetica-Bold", leading=12)
    bold10= ParagraphStyle("b10",parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", leading=13)
    hdrW  = ParagraphStyle("hW", parent=styles["Normal"], fontSize=9,  fontName="Helvetica-Bold",
                textColor=WHITE, alignment=1, leading=11)
    tiny  = ParagraphStyle("ty", parent=styles["Normal"], fontSize=7.5,fontName="Helvetica",   leading=10, textColor=GREY)
    tinyi = ParagraphStyle("ti", parent=styles["Normal"], fontSize=7.5,fontName="Helvetica-Oblique", leading=10, textColor=GREY)
    cover_big   = ParagraphStyle("cb",parent=styles["Normal"],fontSize=22,fontName="Helvetica-BoldOblique",textColor=WHITE,alignment=1,leading=28)
    cover_sub   = ParagraphStyle("cs",parent=styles["Normal"],fontSize=14,fontName="Helvetica-Bold",textColor=colors.HexColor("#BDD7EE"),alignment=1,leading=18)
    cover_label = ParagraphStyle("cl",parent=styles["Normal"],fontSize=9, fontName="Helvetica",textColor=colors.HexColor("#BDD7EE"),alignment=2,leading=12)
    fr_code     = ParagraphStyle("fr",parent=styles["Normal"],fontSize=8, fontName="Helvetica",textColor=GREY,alignment=2)

    eid   = eor.get("id","—")
    toe   = eor.get("toe_name","—")
    ver   = eor.get("toe_version","")
    eal_  = eor.get("eal","—")
    proj  = eor.get("id","—")
    obs_  = eor.get("observations", [])
    now_  = datetime.now().strftime("%d-%b-%Y")

    story = []

    # ════════════════════════════════════════════════════════════════════
    # PAGE 1: COVER
    # ════════════════════════════════════════════════════════════════════
    story.append(Paragraph("FR.MT.04.11", fr_code))
    story.append(Spacer(1, 3*mm))

    # Cover box — navy background
    cov_data = [[
        Paragraph("LABORATORIUM PENGUJIAN<br/>BADAN SIBER DAN SANDI NEGARA",
                  ParagraphStyle("ch",parent=styles["Normal"],fontSize=13,
                      fontName="Helvetica-Bold",textColor=WHITE,alignment=1,leading=17)),
    ],[
        Paragraph("RUANG LINGKUP: KEAMANAN PERANGKAT TEKNOLOGI INFORMASI",
                  ParagraphStyle("crl",parent=styles["Normal"],fontSize=9,
                      fontName="Helvetica",textColor=colors.HexColor("#BDD7EE"),
                      alignment=1,leading=12)),
    ],[
        Paragraph("<i>Evaluation Observation Report</i>",
                  ParagraphStyle("ceor",parent=styles["Normal"],fontSize=20,
                      fontName="Helvetica-BoldOblique",textColor=WHITE,
                      alignment=1,leading=25)),
    ],[
        Paragraph(f"<b>Kelas  ASE</b>",
                  ParagraphStyle("ck",parent=styles["Normal"],fontSize=14,
                      fontName="Helvetica-Bold",textColor=colors.HexColor("#BDD7EE"),
                      alignment=1,leading=18)),
    ],[
        Paragraph(f"<b>{toe}</b>  v{ver}",
                  ParagraphStyle("ct",parent=styles["Normal"],fontSize=12,
                      fontName="Helvetica-Bold",textColor=WHITE,
                      alignment=2,leading=16)),
    ]]
    cov_t = Table(cov_data, colWidths=[W])
    cov_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),COVER),
        ("PADDING",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(-1,0),16),
        ("BOTTOMPADDING",(0,-1),(-1,-1),16),
        ("LINEBELOW",(0,1),(-1,1),0.5,MID),
        ("LINEBELOW",(0,3),(-1,3),0.5,MID),
    ]))
    story.append(cov_t)
    story.append(Spacer(1,5*mm))
    # Bottom labels (right-aligned like original)
    bot_data = [[
        Paragraph("<b>LABORATORIUM PENGUJIAN<br/>BADAN SIBER DAN SANDI NEGARA</b>",
            ParagraphStyle("bl",parent=styles["Normal"],fontSize=9,fontName="Helvetica-Bold",
                textColor=NAVY,alignment=2,leading=12)),
    ],[
        Paragraph("<b>RUANG LINGKUP<br/>KEAMANAN PERANGKAT TEKNOLOGI INFORMASI</b>",
            ParagraphStyle("br",parent=styles["Normal"],fontSize=9,fontName="Helvetica-Bold",
                textColor=NAVY,alignment=2,leading=12)),
    ]]
    bot_t = Table(bot_data, colWidths=[W])
    bot_t.setStyle(TableStyle([("PADDING",(0,0),(-1,-1),4)]))
    story.append(bot_t)
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════════════
    # PAGE 2: SECTION 1 — EOR IDENTIFICATION
    # ════════════════════════════════════════════════════════════════════
    story.append(Paragraph("FR.MT.04.11", fr_code))
    story.append(Spacer(1,4*mm))

    # Section header
    sec1_hdr = Table([[Paragraph("1    EOR Identification", bold10)]],
                     colWidths=[W])
    sec1_hdr.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),NAVY),
        ("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("PADDING",(0,0),(-1,-1),8),
    ]))
    story.append(sec1_hdr)
    story.append(Spacer(1,3*mm))

    LW = 50*mm; VW = W - LW
    def id_row(label, value, val_para=None, span3=False):
        cell_v = val_para if val_para else Paragraph(value, norm)
        return [
            Paragraph(f"<b>{label}</b>", ParagraphStyle("lb",parent=styles["Normal"],
                fontSize=9,fontName="Helvetica-Bold",textColor=WHITE,leading=12)),
            cell_v,
        ]

    # Work Package radio buttons
    def wp_cell():
        wp_items = [("APE",False),("ASE",True),("ADV",False),
                    ("AGD",False),("ALC",False),("ATE",False),("AVA",False)]
        lines = []
        row_txt = ""
        for i,(lbl,chk) in enumerate(wp_items):
            mark = "⦿" if chk else "○"
            row_txt += f"{mark} {lbl}   "
            if (i+1) % 3 == 0:
                lines.append(Paragraph(row_txt, norm)); row_txt = ""
        if row_txt: lines.append(Paragraph(row_txt, norm))
        return lines

    # EOR ID with red project prefix
    eor_id_para = Paragraph(
        f'<font color="#C00000">{proj}</font>/KPTI/{datetime.now().year}/FR.MT.04.11', norm)

    id_data = [
        [Paragraph("<b>Project ID</b>", hdrW),
         Paragraph(proj, norm)],
        [Paragraph("<b>EOR ID</b>", hdrW),
         eor_id_para],
        [Paragraph("<b>EOR Version</b>", hdrW),
         Paragraph("v1.0", norm)],
        [Paragraph("<b>Work Package</b>", hdrW),
         Paragraph("○ APE   <b>⦿ ASE</b>   ○ ADV<br/>○ AGD   ○ ALC   ○ ATE<br/>○ AVA", norm)],
        [Paragraph("<b>Deliverable(s) Reference</b>", hdrW),
         Paragraph(eor.get("cycle_note","Security Target, Guidance Documents"), norm)],
        [Paragraph("<b>CC Component(s)</b>", hdrW),
         Paragraph("ASE_CCL.1, ASE_ECD.1, ASE_INT.1, ASE_OBJ.2, ASE_REQ.2, ASE_SPD.1, ASE_TSS.1", norm)],
    ]
    # Date row — split into 2 halves
    date_row = [
        [Paragraph("<b>EOR Released Date</b>", hdrW),
         Paragraph(f"<i>{now_}</i>", normi),
         Paragraph("<b>EOR Resolved Date</b>", hdrW),
         Paragraph("dd-MMM-yyyy", normi)],
    ]

    id_t = Table(id_data, colWidths=[LW, VW])
    id_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),MID),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("PADDING",(0,0),(-1,-1),7),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(id_t)

    # Date row (4 columns)
    dt_t = Table(date_row[0:1], colWidths=[LW, VW/2-LW/2+LW/4, LW/2+LW/4, VW/2])
    dt_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,0),MID),
        ("BACKGROUND",(2,0),(2,0),MID),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("PADDING",(0,0),(-1,-1),7),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(dt_t)
    story.append(Spacer(1,8*mm))

    # ── Signature block ─────────────────────────────────────────────────
    col3 = W/3
    sig_data = [[
        Paragraph("Tanggal:", norm),
        Paragraph("Tanggal", norm),
        Paragraph("Tanggal:", norm),
    ],[
        Paragraph("Diterima oleh:", ParagraphStyle("db",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12)),
        Paragraph("Disahkan oleh:", ParagraphStyle("db",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12)),
        Paragraph("Disusun oleh:", ParagraphStyle("db",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12)),
    ],[
        Paragraph("", norm),
        Paragraph("", norm),
        Paragraph("", norm),
    ],[
        Paragraph("", norm),
        Paragraph("", norm),
        Paragraph("", norm),
    ],[
        Paragraph("", norm),
        Paragraph("", norm),
        Paragraph("", norm),
    ],[
        Paragraph("(Nama Terang)", ParagraphStyle("nt",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12,textColor=GREY)),
        Paragraph("(Nama Terang)", ParagraphStyle("nt",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12,textColor=GREY)),
        Paragraph("(Nama Terang)", ParagraphStyle("nt",parent=styles["Normal"],
            fontSize=9,fontName="Helvetica",alignment=1,leading=12,textColor=GREY)),
    ],[
        Paragraph("<i>Sponsor/Developer</i>", normi),
        Paragraph("<b>Manajer Teknis</b>", bold9),
        Paragraph("<b>Lead Evaluator</b>", bold9),
    ]]
    sig_t = Table(sig_data, colWidths=[col3,col3,col3], rowHeights=[None,None,12*mm,8*mm,8*mm,None,None])
    sig_t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("LINEABOVE",(0,5),(-1,5),0.8,colors.black),
        ("VALIGN",(0,0),(-1,-1),"BOTTOM"),
        ("ALIGN",(0,1),(-1,-1),"CENTER"),
        ("PADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,2),(-1,4),0),
        ("BOTTOMPADDING",(0,2),(-1,4),0),
    ]))
    story.append(sig_t)
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════════════
    # PAGE 3+: SECTION 2 — OBSERVATION TABLE
    # FR.MT.04.11 col widths: NO | CC COMPONENT | EVAL REF | ISSUE DESC | RESOLUTION | STATUS
    # ════════════════════════════════════════════════════════════════════
    # Column widths for A4 portrait (180mm usable)
    OBS_CW = [8*mm, 28*mm, 24*mm, 35*mm, 60*mm, 25*mm]  # sum=180mm

    def build_obs_page_header():
        return [
            Paragraph("FR.MT.04.11", fr_code),
            Spacer(1,2*mm),
            Paragraph("CONFIDENTIAL", ParagraphStyle("conf",parent=styles["Normal"],
                fontSize=8,fontName="Helvetica-Bold",textColor=RED,alignment=2)),
            Spacer(1,3*mm),
        ]

    # Obs table header
    obs_hdr = [
        Paragraph("NO.", hdrW),
        Paragraph("CC COMPONENT\nELEMENTS", hdrW),

        Paragraph("EVALUATION\nREFERENCE", hdrW),

        Paragraph("ISSUE DESCRIPTION", hdrW),
        Paragraph("RESOLUTION\n(to be updated by the sponsor/developer and evaluator.\nNote: What is written cannot be deleted.)", hdrW),


        Paragraph("STATUS", hdrW),
    ]

    def resolution_cell():
        return [
            Paragraph("<b>Sponsor/Developer Action</b>",
                ParagraphStyle("sa",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica-Bold",textColor=MID,leading=10)),
            Paragraph("[DDMMYYYY] Sponsor/developer action which can either be a "
                      "description of the changes made to the input document or a "
                      "justification as to why the issue is not an issue for the TOE.",
                tinyi),
            HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#AAAAAA"),
                spaceAfter=4,spaceBefore=4),
            Paragraph("<b>Evaluator Action</b>",
                ParagraphStyle("ea",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica-Bold",textColor=MID,leading=10)),
            Paragraph("[DDMMYYYY] Evaluator finding(s) from the review of the "
                      "changes made by the sponsor/developer.",
                tinyi),
        ]

    def status_cell():
        return [
            Paragraph("☐  <b>FIXED</b>",
                ParagraphStyle("fc",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica-Bold",textColor=PASS_C,leading=12)),
            Paragraph("(EOR Resolved)", tiny),
            Spacer(1,4),
            Paragraph("☐  <b>REISSUE</b>",
                ParagraphStyle("rc",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica-Bold",textColor=FAIL_C,leading=12)),
            Paragraph("(EOR Not Resolve)", tiny),
        ]

    # Build observation rows from EOR data
    obs_data = [obs_hdr]
    obs_styles = [
        ("BACKGROUND",(0,0),(-1,0),MID),
        ("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#AAAAAA")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("PADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("ALIGN",(0,0),(0,-1),"CENTER"),
        ("ALIGN",(5,0),(5,-1),"LEFT"),
    ]

    # Get actual observations from EOR (FAIL/INC findings only)
    observations = [o for o in obs_ if o.get("status","") not in ("","OPEN") or
                    o.get("issue_description","").strip()]
    # If no observations, show 3 template rows
    if not observations:
        observations = [
            {"no":1,"cc_component":"—","eval_reference":"—",
             "issue_description":"[Template] Isi temuan FAIL/INCONCLUSIVE di sini."},
            {"no":2,"cc_component":"—","eval_reference":"—","issue_description":""},
            {"no":3,"cc_component":"—","eval_reference":"—","issue_description":""},
        ]

    for i, obs in enumerate(observations, 1):
        fill = ALT if i % 2 == 1 else WHITE
        comp = obs.get("cc_component","—")
        ref  = obs.get("eval_reference","—")
        issue= obs.get("issue_description","")

        # Build resolution cells with actual thread if available
        res_cells = []
        thread = obs.get("resolution_thread",[])
        if thread:
            for entry in thread:
                et = entry.get("type","")
                edate = entry.get("date","")
                etext = entry.get("text","")
                if et == "dev_action":
                    res_cells.append(Paragraph(f"<b>Sponsor/Developer Action</b>",
                        ParagraphStyle("sa2",parent=styles["Normal"],fontSize=8,
                            fontName="Helvetica-Bold",textColor=MID,leading=10)))
                    res_cells.append(Paragraph(f"[{edate}] {etext[:300]}", tinyi))
                elif et == "evaluator_action":
                    res_cells.append(HRFlowable(width="100%",thickness=0.5,
                        color=colors.HexColor("#AAAAAA"),spaceAfter=3,spaceBefore=3))
                    res_cells.append(Paragraph(f"<b>Evaluator Action</b>",
                        ParagraphStyle("ea2",parent=styles["Normal"],fontSize=8,
                            fontName="Helvetica-Bold",textColor=MID,leading=10)))
                    res_cells.append(Paragraph(f"[{edate}] {etext[:300]}", tinyi))
        else:
            res_cells = resolution_cell()

        # Status based on obs status
        obs_status = obs.get("status","OPEN")
        if obs_status == "FIXED":
            st_cells = [
                Paragraph("☑  <b>FIXED</b>",
                    ParagraphStyle("fc2",parent=styles["Normal"],fontSize=8,
                        fontName="Helvetica-Bold",textColor=PASS_C,leading=12)),
                Paragraph("(EOR Resolved)", tiny),
                Spacer(1,4),
                Paragraph("☐  REISSUE",
                    ParagraphStyle("rc2",parent=styles["Normal"],fontSize=8,
                        fontName="Helvetica",textColor=GREY,leading=12)),
                Paragraph("(EOR Not Resolve)", tiny),
            ]
        elif obs_status == "REISSUE":
            st_cells = [
                Paragraph("☐  FIXED",
                    ParagraphStyle("fc3",parent=styles["Normal"],fontSize=8,
                        fontName="Helvetica",textColor=GREY,leading=12)),
                Paragraph("(EOR Resolved)", tiny),
                Spacer(1,4),
                Paragraph("☑  <b>REISSUE</b>",
                    ParagraphStyle("rc3",parent=styles["Normal"],fontSize=8,
                        fontName="Helvetica-Bold",textColor=FAIL_C,leading=12)),
                Paragraph("(EOR Not Resolve)", tiny),
            ]
        else:
            st_cells = status_cell()

        obs_data.append([
            Paragraph(str(i), ParagraphStyle("no",parent=styles["Normal"],
                fontSize=9,fontName="Helvetica-Bold",alignment=1,leading=11,
                textColor=NAVY)),
            Paragraph(f"<b>{comp}</b>",
                ParagraphStyle("cc2",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica-Bold",textColor=NAVY,leading=10)),
            Paragraph(ref,
                ParagraphStyle("er2",parent=styles["Normal"],fontSize=8,
                    fontName="Helvetica",textColor=MID,leading=10)),
            Paragraph(issue or "—", tinyi),
            res_cells,
            st_cells,
        ])

        # Alternate shading
        obs_styles.append(("BACKGROUND",(0,i),(3,i), fill))
        obs_styles.append(("BACKGROUND",(4,i),(4,i), fill))

    story.extend(build_obs_page_header())

    # Section 2 header
    sec2_hdr = Table([[Paragraph("2    Observation", bold10)]],
                     colWidths=[W])
    sec2_hdr.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),NAVY),
        ("TEXTCOLOR",(0,0),(-1,-1),WHITE),
        ("PADDING",(0,0),(-1,-1),8),
    ]))
    story.append(sec2_hdr)
    story.append(Spacer(1,3*mm))

    obs_t = Table(obs_data, colWidths=OBS_CW, repeatRows=1)
    obs_t.setStyle(TableStyle(obs_styles))
    story.append(obs_t)

    doc.build(story)
    buf.seek(0)
    return buf


def make_donut(n_p,n_f,n_i,n_na,dark=True):
    fc="#e6edf3" if dark else "#0f172a"
    fig=go.Figure(go.Pie(labels=["PASS","FAIL","INC","N/A"],values=[n_p,n_f,n_i,n_na],hole=0.65,
        marker=dict(colors=["#3fb950","#f85149","#d29922","#6e7681"],line=dict(width=0)),
        textinfo="none",hovertemplate="<b>%{label}</b><br>%{value} (%{percent})<extra></extra>"))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=5,b=5,l=5,r=5),height=200,showlegend=True,
        legend=dict(font=dict(family="Outfit",size=10,color=fc),bgcolor="rgba(0,0,0,0)"),
        annotations=[dict(text=f"<b>{n_p+n_f+n_i+n_na}</b>",x=0.5,y=0.5,showarrow=False,
            font=dict(size=17,color=fc,family="Outfit"))])
    return fig

# ============================================================
# ══ KANBAN BOARD ════════
# ============================================================

def get_eor_due_status(eor):
    due=eor.get("due_date","")
    if not due: return "#6e7681","on-track"
    d=days_until(due)
    if d<0: return "#f85149","overdue"
    if d<=3: return "#d29922","due-soon"
    return "#3fb950","on-track"

def eor_progress(eor):
    ws_comments=st.session_state.workspace_comments.get(eor.get("id",""),{})
    total=len(eor.get("findings",[])); reviewed=sum(1 for f in eor.get("findings",[]) if ws_comments.get(f["id"]))
    return reviewed,total

def render_evaluator_kanban():
    """v2.0 Evaluator Kanban: 4 status jelas DRAFT/ON_PROGRESS/REVISION/DONE + badge re-submit."""
    pg_header("📋","Kanban Board Evaluator","DRAFT → ON PROGRESS → REVISION → DONE | Push to Lead saat selesai")
    results = st.session_state.audit_results_raw
    audit_done = st.session_state.audit_done
    has_eor = bool(st.session_state.audit_results)
    eors = st.session_state.eor_backlog

    # Map EORs to evaluator kanban status
    def get_ev_kanban_status(eor):
        s = eor.get("status","DRAFT")
        if s in ("DRAFT","IN_AUDIT"): return "DRAFT"
        if s in ("SUBMITTED","UNDER_REVIEW"): return "ON_PROGRESS"
        if s in ("APPROVED","CLOSED","REVIEW_TO_CB"): return "DONE"
        if s == "REVISION": return "REVISION"
        return "DRAFT"

    col_defs = [
        ("DRAFT","📝 DRAFT","Belum diaudit / sedang audit","#6e7681"),
        ("ON_PROGRESS","🔍 ON PROGRESS","Dikirim ke Lead, menunggu review","#58a6ff"),
        ("REVISION","🔁 REVISION","Dikembalikan Lead - Perlu re-submit","#f85149"),
        ("DONE","✅ DONE","Disetujui Lead, lanjut ke CB","#3fb950"),
    ]

    # Current work in progress (audit not yet pushed)
    wip_card = None
    if audit_done and has_eor and not any(e.get("submitted_by")==st.session_state.username and
        e.get("status") in ("SUBMITTED","UNDER_REVIEW") for e in eors):
        res = st.session_state.audit_results
        n_f = res.get("fail",0); n_i = res.get("inc",0)
        wip_card = {"id":"WIP","toe_name":res.get("toe_name","—"),"eal":res.get("eal","—"),
            "status":"DRAFT","submitted_by":st.session_state.username,
            "findings_count":n_f+n_i,"is_wip":True}

    cols = st.columns(4)
    for ci,(status,label,desc,color) in enumerate(col_defs):
        with cols[ci]:
            st.markdown(f"""
<div style="background:rgba(0,0,0,.15);border:1px solid {color}40;border-radius:12px;
  padding:.6rem .85rem;margin-bottom:.85rem;">
  <div style="color:{color};font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.6px;">{label}</div>
  <div style="color:#6e7681;font-size:.67rem;margin-top:2px;">{desc}</div>
</div>""", unsafe_allow_html=True)
            
            col_eors = [
                e for e in eors
                if get_ev_kanban_status(e) == status
                and (
                    e.get("submitted_by") == st.session_state.username
                    or e.get("assigned_role") == "evaluator"
                    or e.get("status") == "REVISION"
                )
            ]

            if status=="DRAFT" and wip_card:
                col_eors = [wip_card] + col_eors

            if not col_eors:
                st.markdown(f'<div style="color:#6e7681;font-size:.75rem;text-align:center;padding:1rem 0;">— kosong —</div>', unsafe_allow_html=True)

            for eor in col_eors:
                is_wip = eor.get("is_wip",False)
                n_findings = eor.get("findings_count",len(eor.get("findings",[])))
                eor_status = eor.get("status","DRAFT")
                
                # === AMBIL RESUBMIT COUNT ===
                resubmit_count = eor.get("resubmit_count", 0)
                is_resubmit = resubmit_count > 0
                
                border_c = {
                    "DRAFT":"#6e7681",
                    "SUBMITTED":"#58a6ff",
                    "APPROVED":"#3fb950",
                    "REVISION":"#f85149"
                }.get(eor_status,color)

                # === BADGE UNTUK ON_PROGRESS (SUBMITTED) ===
                resubmit_badge = ""
                resubmit_note_html = ""
                
                if is_resubmit:
                    if status == "ON_PROGRESS":
                        # Ini adalah EOR yang sudah di-re-submit, menunggu review Lead
                        resubmit_badge = f'<span style="background:#d29922;color:#0d1117;font-size:.6rem;font-weight:700;padding:2px 8px;border-radius:12px;margin-left:.3rem;">🔄 RE-SUBMIT #{resubmit_count}</span>'
                    elif status == "REVISION":
                        # Ini adalah EOR yang dikembalikan lagi setelah re-submit
                        resubmit_badge = f'<span style="background:#f85149;color:#fff;font-size:.6rem;font-weight:700;padding:2px 8px;border-radius:12px;margin-left:.3rem;">🔄 Re-submit #{resubmit_count}</span>'
                        resubmit_note = eor.get("resubmit_note", "")
                        if resubmit_note:
                            resubmit_note_html = f'<div style="font-size:.7rem;color:#ffa657;margin:.2rem 0;">📝 {html.escape(resubmit_note[:80])}</div>'

                st.markdown(f"""
<div class="eor-card" style="border-left:3px solid {border_c};">
    <div class="eor-card-title">{html.escape(eor.get("toe_name","—"))} {resubmit_badge}</div>
    <div class="eor-card-meta">{html.escape(eor.get("id","WIP"))} | {html.escape(eor.get("eal","—"))}</div>
    <div class="eor-card-badges" style="margin-top:.4rem;">
        <span class="sb sb-fail">❌ {n_findings} findings</span>
        {"<span class='sb sb-prog'>📝 DRAFT</span>" if is_wip else f"<span class='sb sb-resp'>{html.escape(eor_status)}</span>"}
        {f'<span class="sb sb-resp" style="background:#d29922;color:#0d1117;">🔄 #{resubmit_count}</span>' if is_resubmit and status == "ON_PROGRESS" else ''}
    </div>
    {resubmit_note_html}
</div>""", unsafe_allow_html=True)

                # Push to Lead button — only on DRAFT WIP card when audit done
                if is_wip and audit_done and has_eor:
                    if st.button("🚀 Push to Lead Evaluator",
                        key=f"push_kanban_wip_{ci}",
                        type="primary",
                        use_container_width=True,
                        help="Layer 1 review selesai — kirim ke Lead Evaluator"):
                        st.session_state.pending_push_from_kanban = True
                        st.session_state["next_page"] = "push"
                        st.rerun()

                # Revision card — Lead Comments review button
                if eor_status == "REVISION" and not is_wip:
                    # Show re-submit info if any
                    if eor.get("resubmit_count",0)>0:
                        st.markdown(f'<div style="text-align:center;margin-bottom:.3rem;"><span class="sb sb-resp" style="background:#f85149;color:#fff;">🔄 Re-submit #{eor.get("resubmit_count",0)}</span></div>', unsafe_allow_html=True)
                    
                    ack_key = f"revision_acks_{eor.get('id','')}"
                    acks_done = st.session_state.get(ack_key, {})
                    ws_c = st.session_state.workspace_comments.get(eor.get("id",""), {})
                    findings_with_lead = sum(
                        1 for f in eor.get("findings",[])
                        if ws_c.get(f.get("id","")) or f.get("lead_comment") or f.get("lead_verdict")
                    )
                    acked_n = sum(1 for k,v in acks_done.items()
                                 if v and not k.endswith("_override"))
                    if findings_with_lead > 0:
                        ack_label = (f"✅ {acked_n}/{findings_with_lead} acked"
                                    if acked_n >= findings_with_lead
                                    else f"📝 {acked_n}/{findings_with_lead} belum")
                        st.markdown(f'<div style="font-size:.72rem;color:#d29922;text-align:center;margin:.25rem 0;">{ack_label}</div>', unsafe_allow_html=True)

                    if st.button(
                        "📋 Baca & Respond Komentar Lead",
                        key=f"review_lead_{eor.get('id','')}",
                        type="primary",
                        use_container_width=True,
                        help="Buka Revision Review — baca komentar Lead, acknowledge, re-submit"
                    ):
                        st.session_state["active_revision_eor"] = eor.get("id","")
                        st.session_state["revision_mode"] = True
                        st.session_state["nav_target"] = "revision_review"
                        st.rerun()

    st.markdown("### 📊 Progress Evaluator")
    c1,c2,c3,c4 = st.columns(4)
    my_eors = [e for e in eors if e.get("submitted_by")==st.session_state.username]
    c1.metric("📋 Total EOR Saya", len(my_eors)+(1 if wip_card else 0))
    c2.metric("⏳ Menunggu Lead", sum(1 for e in my_eors if e.get("status") in ("SUBMITTED","UNDER_REVIEW")))
    c3.metric("🔁 Perlu Revisi", sum(1 for e in my_eors if e.get("status")=="REVISION"))
    
    # === METRIK RE-SUBMIT ===
    resubmit_total = sum(1 for e in my_eors if e.get("resubmit_count",0)>0)
    c4.metric("🔄 Re-submit", resubmit_total, delta=f"dari {len(my_eors)} EOR" if resubmit_total>0 and len(my_eors)>0 else None)

def render_kanban_board():
    pg_header("📋","Kanban Board","Project tracking internal — tanpa Jira | Semua roles")
    
    # DEFINE THESE FIRST (fix bug)
    col_headers = {
        "DRAFT": "📝 DRAFT",
        "IN_AUDIT": "🔍 IN AUDIT", 
        "UNDER_REVIEW": "👥 UNDER REVIEW",
        "REVISION": "🔁 REVISION",
        "APPROVED": "✅ APPROVED"
    }
    col_colors = {
        "DRAFT": "#6e7681",
        "IN_AUDIT": "#58a6ff", 
        "UNDER_REVIEW": "#d29922",
        "REVISION": "#f85149",
        "APPROVED": "#3fb950"
    }
    
    dark=st.session_state.dark_mode
    cols=st.columns(5)
    
    for ci,(colname,label) in enumerate(col_headers.items()):
        with cols[ci]:
            # Map status ke kolom yang sesuai
            if colname == "UNDER_REVIEW":
                status_filter = ["UNDER_REVIEW", "SUBMITTED"]
            elif colname == "REVISION":
                status_filter = ["REVISION"]
            elif colname == "APPROVED":
                status_filter = ["APPROVED", "CLOSED"]
            elif colname == "DRAFT":
                status_filter = ["DRAFT", "IN_AUDIT"]
            else:
                status_filter = [colname]
            
            col_eors = [e for e in st.session_state.eor_backlog if e.get("status","") in status_filter]
            
            c = col_colors[colname]
            st.markdown(f'<div style="background:rgba(0,0,0,.2);border:1px solid {c}40;border-radius:10px;padding:.5rem .7rem;margin-bottom:.75rem;"><span style="color:{c};font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.6px;">{label}</span> <span style="background:{c}30;color:{c};border-radius:10px;padding:1px 8px;font-size:.7rem;font-weight:700;">{len(col_eors)}</span></div>',unsafe_allow_html=True)

            for eor in col_eors:
                due=eor.get("due_date","")
                d_val=days_until(due) if due else 99
                dc,ds=get_eor_due_status(eor)
                rev,tot=eor_progress(eor)
                pct=int(rev/tot*100) if tot>0 else 0
                n_fail=sum(1 for f in eor.get("findings",[]) if f.get("verdict")=="FAIL")
                n_inc=sum(1 for f in eor.get("findings",[]) if f.get("verdict")=="INCONCLUSIVE")
                
                # === NEW: Check if this is a re-submit ===
                resubmit_count = eor.get("resubmit_count", 0)
                is_resubmit = resubmit_count > 0
                
                # Different badge based on column
                if is_resubmit:
                    if colname == "UNDER_REVIEW":
                        # Re-submit waiting for Lead review
                        resubmit_badge = f'<span style="background:#d29922;color:#0d1117;font-size:.6rem;font-weight:700;padding:2px 8px;border-radius:12px;margin-left:.3rem;">🔄 RE-SUBMIT #{resubmit_count}</span>'
                    elif colname == "REVISION":
                        # Needs revision after re-submit
                        resubmit_badge = f'<span style="background:#f85149;color:#fff;font-size:.6rem;font-weight:700;padding:2px 8px;border-radius:12px;margin-left:.3rem;">🔄 Re-submit #{resubmit_count}</span>'
                    else:
                        resubmit_badge = f'<span class="sb sb-resp" style="font-size:.6rem;">🔄 #{resubmit_count}</span>'
                else:
                    resubmit_badge = ""

                due_label=""
                if due:
                    if d_val<0: due_label=f"<span style='color:#f85149;font-size:.67rem;'>⚠ OVERDUE {abs(d_val)}d</span>"
                    elif d_val<=3: due_label=f"<span style='color:#d29922;font-size:.67rem;'>⏰ {d_val}d left</span>"
                    else: due_label=f"<span style='color:#3fb950;font-size:.67rem;'>📅 {d_val}d</span>"

                # Add special styling for re-submit cards
                card_border_style = ""
                if is_resubmit and colname == "UNDER_REVIEW":
                    card_border_style = "border: 2px solid #d29922;"
                elif is_resubmit and colname == "REVISION":
                    card_border_style = "border: 2px solid #f85149;"

                st.markdown(f"""
<div class="eor-card {ds}" style="border-color:{dc}40; {card_border_style}">
  <div class="eor-card-title">{eor.get('toe_name','—')} {resubmit_badge}</div>
  <div class="eor-card-meta">{eor.get('id','')} | {eor.get('eal','—')}</div>
  <div class="eor-card-meta">👤 {eor.get('submitted_by','—')}</div>
  <div style="margin:.35rem 0;">{due_label}</div>
  <div class="eor-card-badges">
    <span class="sb sb-fail">❌{n_fail}</span>
    <span class="sb sb-inc">⚠{n_inc}</span>
  </div>
  <div style="margin-top:.45rem;">
    <div style="display:flex;justify-content:space-between;font-size:.67rem;color:#8b949e;margin-bottom:2px;">
      <span>Review</span><span>{rev}/{tot}</span>
    </div>
    <div class="sla-bar"><div class="sla-fill" style="width:{pct}%;background:{'#3fb950' if pct>70 else '#d29922' if pct>30 else '#f85149'};"></div></div>
  </div>
</div>""",unsafe_allow_html=True)

                # Move card button
                role=st.session_state.role
                if role in ("lead_evaluator","evaluator"):
                    ci2=list(col_headers.keys()).index(colname) if colname in col_headers else 0
                    opts=[c for c in col_headers.keys() if c!=colname]
                    with st.expander(f"Move card",expanded=False):
                        target=st.selectbox("Move to",opts,key=f"mv_{eor['id']}_{colname}")
                        if st.button("→ Move",key=f"movebtn_{eor['id']}_{colname}",use_container_width=True):
                            old=eor["status"]; eor["status"]=target
                            eor.setdefault("history",[]).append({
                                "from":old,"to":target,"by":st.session_state.user_name,
                                "ts":datetime.now().isoformat()})
                            notif_target="evaluator" if target in ("REVISION","APPROVED") else "lead_evaluator"
                            add_notification(f"📋 EOR Moved",f"{eor['id']} moved {old}→{target}",notif_target)
                            if target=="REVISION":
                                add_notification(f"🔁 Revision Required",f"EOR {eor['id']} dikembalikan ke Evaluator","evaluator")
                            st.success(f"Moved to {target}!"); st.rerun()
                        st.divider()

                    # === TOMBOL DELETE YANG SUDAH DIMODIFIKASI ===
                    if st.button(f"🗑️ Delete {eor['id']} PERMANEN", key=f"del_{eor['id']}", use_container_width=True, help="Hapus EOR ini dari memory DAN disk"):
                        # Konfirmasi double click untuk keamanan
                        confirm_key = f"confirm_del_{eor['id']}"
                        if st.session_state.get(confirm_key, False):
                            # Hapus file JSON
                            eor_path = _eor_path(eor.get("id"))
                            if eor_path.exists():
                                eor_path.unlink()
                                st.info(f"📁 File JSON dihapus")
                            
                            # Hapus folder uploads
                            upload_folder = UPL_DIR / eor.get("id")
                            if upload_folder.exists():
                                import shutil
                                shutil.rmtree(upload_folder)
                                st.info(f"📁 Folder uploads dihapus")

                        # 3. Hapus dari session state (memory)
                            st.session_state.eor_backlog = [e for e in st.session_state.eor_backlog if e.get("id") != eor.get("id")]
                            st.session_state.workspace_comments.pop(eor.get("id"), None)
                            st.session_state.workspace_artefacts.pop(eor.get("id"), None)
                            if eor.get("id") in st.session_state.dev_findings:
                                del st.session_state.dev_findings[eor.get("id")]
                        
                            st.session_state[confirm_key] = False
                            st.success(f"✅ {eor['id']} dihapus PERMANEN!")
                            st.rerun()
                        else:
                            st.session_state[confirm_key] = True
                            st.warning(f"⚠️ Klik sekali lagi untuk konfirmasi hapus PERMANEN {eor['id']}")
    st.divider()
    # Daily target summary
    st.markdown("### 📊 Daily Progress Overview")
    c1,c2,c3=st.columns(3)
    with c1:
        total_open=sum(1 for e in st.session_state.eor_backlog if e.get("status") not in ("APPROVED","CLOSED"))
        st.metric("🔓 Active EORs",total_open)
    with c2:
        total_findings=sum(len(e.get("findings",[])) for e in st.session_state.eor_backlog)
        dev_findings=st.session_state.dev_findings
        responded=sum(1 for eid,units in dev_findings.items() for uid,f in units.items() if f.get("status") in ("RESPONDED","VERIFIED","CLOSED"))
        st.metric("💬 Dev Responded",responded,delta=f"/{total_findings} total")
    with c3:
        overdue_eors=sum(1 for e in st.session_state.eor_backlog if e.get("due_date","") and days_until(e["due_date"])<0)
        st.metric("⚠️ Overdue EORs",overdue_eors,delta="need attention" if overdue_eors>0 else "all on track")
        

# ============================================================
# ══ DEV FINDING TRACKER (v12 NEW) ══════════════════════════
# ============================================================

def render_dev_finding_tracker(dev_username):
    """v2.0 FINAL: Dev My Findings — CC EOR Observation format. Append-only thread."""
    pg_header("🛠️","My Findings — EOR Resolution",
        "CC Observation Format | Sponsor/Developer Action | Append-Only")

    if not st.session_state.tm2_done:
        st.markdown("""
<div style="background:rgba(0,0,0,.5);border:1px solid rgba(255,255,255,.08);
  border-radius:16px;padding:3rem 2rem;text-align:center;margin:2rem 0;">
  <div style="font-size:2.5rem;margin-bottom:.75rem;">🔒</div>
  <div style="font-size:1.1rem;font-weight:800;color:#e6edf3;margin-bottom:.5rem;">My Findings Terkunci</div>
  <div style="color:#8b949e;font-size:.85rem;line-height:1.8;max-width:440px;margin:0 auto;">
    Dibuka oleh <b>CB Auditor</b> setelah <b>TM2</b> selesai dan findings di-push.<br>
    Anda akan mendapat <b>notifikasi + email</b> begitu akses dibuka.
  </div>
</div>""", unsafe_allow_html=True)
        return

    dev_findings = st.session_state.dev_findings
    my_findings = []
    for eor_id, units in dev_findings.items():
        eor_obj = next((e for e in st.session_state.eor_backlog if e.get("id")==eor_id), {})
        for uid, f in units.items():
            assigned = f.get("assigned_to","")
            if (assigned in (dev_username,"","developer")) and f.get("source","")=="TM2":
                my_findings.append({"eor_id":eor_id,"uid":uid,"finding":f,"eor":eor_obj})

    if not my_findings:
        st.info("Belum ada findings dari TM2. Tunggu CB Auditor push findings."); return

    n_open  = sum(1 for mf in my_findings if mf["finding"].get("status","OPEN")=="OPEN")
    n_prog  = sum(1 for mf in my_findings if mf["finding"].get("status","")=="IN_PROGRESS")
    n_resp  = sum(1 for mf in my_findings if mf["finding"].get("status","")=="RESPONDED")
    n_fix   = sum(1 for mf in my_findings if mf["finding"].get("status","")=="FIXED")
    n_rei   = sum(1 for mf in my_findings if mf["finding"].get("status","")=="REISSUE")

    st.markdown(f"""<div class="metric-grid">
  {metric_html(len(my_findings),"Total","#58a6ff")}
  {metric_html(n_open,"Open","#f85149")}
  {metric_html(n_prog,"In Progress","#d29922")}
  {metric_html(n_resp,"Responded","#58a6ff")}
  {metric_html(n_fix,"Fixed","#3fb950")}
  {metric_html(n_rei,"Reissue","#f85149")}
</div>""", unsafe_allow_html=True)

    flt = st.multiselect("Filter",["OPEN","IN_PROGRESS","RESPONDED","FIXED","REISSUE"],
        default=["OPEN","IN_PROGRESS","REISSUE"])
    st.divider()

    for mf in my_findings:
        uid=mf["uid"]; finding=mf["finding"]; eor_id=mf["eor_id"]; eor_obj=mf["eor"]
        fstatus=finding.get("status","OPEN")
        if fstatus not in flt: continue

        pri=finding.get("priority","MAJOR")
        pri_c={"MAJOR":"#f85149","MINOR":"#d29922","INFO":"#58a6ff"}.get(pri,"#8b949e")
        dl=finding.get("dev_deadline","")
        d_val=days_until(dl) if dl else 99
        dc,_=sla_color(d_val)
        sc={"OPEN":"sb-open","IN_PROGRESS":"sb-prog","RESPONDED":"sb-resp",
            "FIXED":"sb-veri","REISSUE":"sb-fail"}.get(fstatus,"sb-open")

        # EOR Observation Card
        st.markdown(f"""
<div style="background:var(--bg2);border:1px solid var(--border);
  border-left:4px solid {pri_c};border-radius:0 14px 14px 0;padding:1rem 1.1rem;margin-bottom:.5rem;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem;">
    <div>
      <span style="font-family:var(--mono);font-size:.88rem;font-weight:700;color:var(--accent);">
        {finding.get("no","")}.&nbsp;{html.escape(uid)}</span>
      <span class="sb {sc}" style="margin-left:.4rem;">{html.escape(fstatus)}</span>
      <span style="background:{pri_c}20;color:{pri_c};font-size:.68rem;font-weight:700;
        padding:2px 7px;border-radius:10px;margin-left:.3rem;">{html.escape(pri)}</span>
    </div>
    <div style="font-size:.75rem;color:{dc};">Deadline: {html.escape(dl)} ({d_val}d)</div>
  </div>
  <div style="margin:.55rem 0;padding:.45rem .7rem;background:var(--bg3);border-radius:7px;">
    <div style="font-size:.68rem;font-weight:700;color:#8b949e;text-transform:uppercase;margin-bottom:.2rem;">CC Component Elements | Eval Reference</div>
    <span style="font-family:var(--mono);font-size:.82rem;color:var(--accent);">{html.escape(finding.get("cc_component",""))}</span>
    <span style="font-size:.78rem;color:#8b949e;margin-left:.6rem;">{html.escape(finding.get("eval_reference",""))}</span>
  </div>
  <div style="margin:.4rem 0;padding:.55rem .75rem;background:rgba(248,81,73,.06);
    border:1px solid rgba(248,81,73,.2);border-radius:7px;">
    <div style="font-size:.68rem;font-weight:700;color:#f85149;text-transform:uppercase;margin-bottom:.25rem;">Issue Description (CB Auditor — immutable)</div>
    <div style="font-size:.82rem;color:var(--text);line-height:1.5;">{html.escape(finding.get("issue_description","—"))}</div>
  </div>
</div>""", unsafe_allow_html=True)

        # Resolution thread
        thread=finding.get("resolution_thread",[])
        if thread:
            for entry in thread:
                etype=entry.get("type","")
                if etype=="dev_action":
                    bg="rgba(255,166,87,.07)"; bc="#ffa657"; lbl="🛠️ Sponsor/Developer Action"
                elif etype=="evaluator_action":
                    bg="rgba(88,166,255,.07)"; bc="#58a6ff"; lbl="👨‍💻 Evaluator Action"
                else:
                    bg="rgba(110,118,129,.07)"; bc="#6e7681"; lbl="📝"
                sv=entry.get("status","")
                sb_html=f'<span class="sb {"sb-veri" if sv=="FIXED" else "sb-fail"}" style="margin-left:.4rem;">{html.escape(sv)}</span>' if sv else ""
                att_html="".join(f'<span class="artefact-pill">📎 {html.escape(a.get("name",""))}</span>' for a in entry.get("attachments",[]))
                st.markdown(f"""
<div style="background:{bg};border-left:3px solid {bc};border-radius:0 8px 8px 0;
  padding:.65rem .85rem;margin:.3rem 0 .3rem 1rem;">
  <div style="font-size:.7rem;color:#8b949e;font-family:var(--mono);margin-bottom:.25rem;">
    {html.escape(entry.get("date",""))} — {lbl}{sb_html}</div>
  <div style="font-size:.82rem;color:var(--text);line-height:1.5;">{html.escape(entry.get("text",""))}</div>
  <div style="margin-top:.3rem;">{att_html}</div>
</div>""", unsafe_allow_html=True)

        # Dev action form
        if fstatus not in ("FIXED","VERIFIED"):
            with st.expander(f"✍️ Tulis Sponsor/Developer Action — {uid}",
                expanded=(fstatus in ("OPEN","REISSUE"))):
                st.markdown("""<div style="background:rgba(255,166,87,.06);border:1px solid rgba(255,166,87,.2);
                  border-radius:8px;padding:.6rem .9rem;margin-bottom:.7rem;font-size:.8rem;color:#ffa657;">
                  ⚠️ <b>Append-only</b> — teks yang ditulis tidak bisa dihapus/diubah.</div>""",
                  unsafe_allow_html=True)
                dev_text=st.text_area("Sponsor/Developer Action",height=110,
                    key=f"dt_{eor_id}_{uid}",
                    placeholder=f"[{datetime.now().strftime('%d%m%Y')}] Deskripsi perubahan yang dibuat "
                                "atau justifikasi mengapa ini bukan issue untuk TOE...")
                up_files=st.file_uploader("📎 Upload Bukti (ST revisi, screenshot, PDF)",
                    type=["png","jpg","jpeg","pdf"],accept_multiple_files=True,
                    key=f"df_{eor_id}_{uid}")
                new_st=st.selectbox("Update Status",["IN_PROGRESS","RESPONDED"],
                    index=0,key=f"ds_{eor_id}_{uid}")
                if st.button(f"🚀 Submit Response — {uid}",key=f"dsub_{eor_id}_{uid}",
                    type="primary",use_container_width=True):
                    if not dev_text.strip():
                        st.warning("Isi Sponsor/Developer Action terlebih dahulu.")
                    else:
                        saved=[]; 
                        for uf in (up_files or []):
                            p=save_upload(eor_id,uid,uf.name,uf.getvalue())
                            saved.append({"name":uf.name,"path":p,"size":uf.size})
                        entry={"type":"dev_action","date":datetime.now().strftime("%d%m%Y"),
                            "datetime":datetime.now().isoformat(),"text":dev_text.strip(),
                            "author":dev_username,"attachments":saved,"status":None}
                        finding["resolution_thread"].append(entry)
                        finding["status"]=new_st
                        for obs in eor_obj.get("observations",[]):
                            if obs.get("id")==uid:
                                obs["resolution_thread"]=finding["resolution_thread"]
                                obs["status"]=new_st
                        save_eor(eor_obj)
                        # Email to CB (primary), Lead + Evaluator (CC)
                        _att_names = ", ".join(a["name"] for a in saved) if saved else "none"
                        for _to, _role in [
                            ("cb@cc-lab.go.id","CB Auditor"),
                            ("evaluator@cc-lab.go.id","Evaluator"),
                            ("lead@cc-lab.go.id","Lead Evaluator"),
                        ]:
                            simulated_email(to=_to,
                                subject=f"[CC-AI] Dev Response — {uid} | EOR {eor_id}",
                                body=(
                                    f"Yth. {_role},\n\n"
                                    f"Developer merespond finding:\n"
                                    f"EOR: {eor_id} | Finding: {uid} [{finding.get('priority','')}]\n"
                                    f"Status: {new_st}\n\n"
                                    f"Sponsor/Developer Action:\n{dev_text.strip()}\n\n"
                                    f"Attachments: {_att_names}\n\n"
                                    f"Review di platform: CC-AI → Manage Dev Findings\n"
                                ))
                        # Notifications: CB primary, Lead + Evaluator CC
                        add_notification(
                            f"💬 Dev Response: {uid}",
                            f"merespond finding {uid} (Sponsor/Developer Action)",
                            target="cb_auditor",
                            sender=dev_username,
                            obj=f"EOR {eor_id} — {uid} [{finding.get('priority','')}]",
                            keterangan=f"{dev_text[:55]} | {len(saved)} file(s)",
                            icon="💬")
                        add_notification(
                            f"💬 [CC] Dev Response: {uid}",
                            f"merespond finding {uid} — review di Manage Dev Findings",
                            target="evaluator",
                            sender=dev_username,
                            obj=f"EOR {eor_id} — {uid}",
                            keterangan=dev_text[:60],icon="💬")
                        add_notification(
                            f"💬 [CC] Dev Response: {uid}",
                            f"merespond finding {uid}",
                            target="lead_evaluator",
                            sender=dev_username,
                            obj=f"EOR {eor_id} — {uid}",
                            keterangan=dev_text[:60],icon="💬")
        st.divider()

def render_lead_dev_management():
    """Lead + Evaluator: View Dev responses, Verify/Reject per finding.
    Reads from resolution_thread (written by Dev Dashboard).
    Shows APPROVED EORs (Dev findings created post-TM2).
    Images from Dev attachments displayed inline.
    """
    pg_header("🔧","Dev Response Inbox",
        "Response Developer (TM2) — Review Evaluator Action per Finding")

    dev_findings = st.session_state.dev_findings
    # Include all EORs that have dev findings OR are in relevant status
    eors_map = {e["id"]:e for e in st.session_state.eor_backlog
                if dev_findings.get(e.get("id",""))
                or e.get("status") in ("APPROVED","CLOSED","SUBMITTED","UNDER_REVIEW","REVISION")}
    if not eors_map:
        st.info("📭 Belum ada EOR. Dev Findings muncul setelah CB push TM2."); return

    sel_id = st.selectbox("Pilih EOR", list(eors_map.keys()),
        format_func=lambda x: f"{x} — {eors_map[x].get('toe_name','')} ({eors_map[x].get('status','')})")
    eor = eors_map[sel_id]
    df_eor = dev_findings.get(sel_id, {})

    # Metrics
    n_tot  = len(df_eor)
    n_open = sum(1 for f in df_eor.values() if f.get("status","OPEN")=="OPEN")
    n_resp = sum(1 for f in df_eor.values() if f.get("status")=="RESPONDED")
    n_fix  = sum(1 for f in df_eor.values() if f.get("status") in ("FIXED","VERIFIED"))
    n_rei  = sum(1 for f in df_eor.values() if f.get("status")=="REISSUE")

    st.markdown(f"""<div class="metric-grid">
      {metric_html(n_tot,"📋 Total","#58a6ff")}
      {metric_html(n_open,"⏳ Open","#6e7681")}
      {metric_html(n_resp,"💬 Dev Responded","#d29922")}
      {metric_html(n_fix,"✅ Fixed","#3fb950")}
      {metric_html(n_rei,"🔁 Reissue","#f85149")}
    </div>""", unsafe_allow_html=True)

    if not df_eor:
        st.info("📭 Belum ada findings TM2. CB Auditor perlu push findings ke Developer."); return

    flt = st.multiselect("Filter Status",
        ["OPEN","IN_PROGRESS","RESPONDED","VERIFIED","FIXED","REISSUE"],
        default=["RESPONDED","REISSUE","IN_PROGRESS"])
    st.divider()

    for uid, f_data in df_eor.items():
        fstatus = f_data.get("status","OPEN")
        if fstatus not in flt: continue

        # resolution_thread is the correct key (written by Dev Dashboard)
        thread       = f_data.get("resolution_thread", [])
        dev_resps    = [e for e in thread if e.get("type")=="dev_action"]
        ev_actions   = [e for e in thread if e.get("type")=="evaluator_action"]
        has_dev_resp = bool(dev_resps)

        pri   = f_data.get("priority","MAJOR")
        pri_c = {"MAJOR":"#f85149","MINOR":"#d29922","INFO":"#58a6ff"}.get(pri,"#8b949e")
        sc    = {"OPEN":"sb-open","IN_PROGRESS":"sb-prog","RESPONDED":"sb-resp",
                 "VERIFIED":"sb-veri","FIXED":"sb-veri","REISSUE":"sb-fail"}.get(fstatus,"sb-open")
        dl    = f_data.get("dev_deadline","")
        d_val = days_until(dl) if dl else 99
        dc,_  = sla_color(d_val)

        # Finding header
        _h_uid   = html.escape(uid)
        _h_title = html.escape(f_data.get("title",uid)[:80])
        _h_issue = html.escape(f_data.get("issue_description","—")[:110])
        st.markdown(
            f'<div style="background:var(--bg2);border:1px solid var(--border);'
            f'border-left:4px solid {pri_c};border-radius:0 14px 14px 0;'
            f'padding:1rem 1.1rem;margin-bottom:.5rem;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem;">'
            f'<div><b style="font-family:var(--mono);color:var(--accent);">{_h_uid}</b>'
            f'<span class="sb {sc}" style="margin-left:.4rem;">{html.escape(fstatus)}</span>'
            f'<span style="background:{pri_c}20;color:{pri_c};font-size:.68rem;font-weight:700;'
            f'padding:2px 7px;border-radius:10px;margin-left:.3rem;">{html.escape(pri)}</span></div>'
            f'<div style="font-size:.75rem;color:{dc};">Deadline: {html.escape(dl)} ({d_val}d)</div></div>'
            f'<div style="font-size:.75rem;color:#8b949e;margin-top:.3rem;">{_h_title}</div>'
            f'<div style="font-size:.72rem;color:var(--muted);margin-top:.2rem;">'
            f'Issue (CB): {_h_issue}</div></div>',
            unsafe_allow_html=True)

        # Show full resolution thread with images
        for entry in thread:
            etype  = entry.get("type","")
            edate  = entry.get("date","")
            etext  = html.escape(entry.get("text",""))
            e_atts = entry.get("attachments",[])
            ev_stat= entry.get("status","")

            if etype=="dev_action":    bg="rgba(255,166,87,.07)"; bc="#ffa657"; lbl=f"🛠️ Sponsor/Developer Action — {edate}"
            elif etype=="evaluator_action": bg="rgba(88,166,255,.07)"; bc="#58a6ff"; lbl=f"👨‍💻 Evaluator Action — {edate}"
            else:                     bg="rgba(110,118,129,.07)"; bc="#6e7681"; lbl=f"📝 {edate}"
            sv_html = (f'<span class="sb {"sb-veri" if ev_stat=="FIXED" else "sb-fail"}">{html.escape(ev_stat)}</span>'
                       if ev_stat else "")

            st.markdown(
                f'<div style="background:{bg};border-left:3px solid {bc};'
                f'border-radius:0 8px 8px 0;padding:.7rem .9rem;margin:.3rem 0 .3rem 1rem;">'
                f'<div style="font-size:.7rem;color:#8b949e;font-family:var(--mono);">'
                f'{html.escape(lbl)} {sv_html}</div>'
                f'<div style="font-size:.82rem;color:var(--text);line-height:1.5;">{etext}</div></div>',
                unsafe_allow_html=True)

            # Attachments: images inline, files as pills
            img_atts   = [a for a in e_atts if a.get("type","").startswith("image/") or
                          a.get("name","").lower().endswith((".png",".jpg",".jpeg",".gif",".webp"))]
            other_atts = [a for a in e_atts if a not in img_atts]
            if img_atts:
                n_ic = min(len(img_atts),3)
                i_cols = st.columns(n_ic)
                for ci2, art in enumerate(img_atts):
                    ab = art.get("bytes"); an = art.get("name","img")
                    with i_cols[ci2 % n_ic]:
                        if ab:
                            _ext = an.lower().rsplit(".",1)[-1] if "." in an else "png"
                            _mime = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png",
                                     "gif":"image/gif","webp":"image/webp"}.get(_ext,"image/png")
                            _b64 = base64.b64encode(ab).decode()
                            st.markdown(
                                f'<div style="border:1px solid var(--border);border-radius:8px;'
                                f'overflow:hidden;margin-bottom:.4rem;">'
                                f'<img src="data:{_mime};base64,{_b64}" '
                                f'style="width:100%;height:auto;display:block;" title="{html.escape(an)}" />'
                                f'<div style="font-size:.67rem;color:#8b949e;padding:3px 6px;'
                                f'font-family:var(--mono);">{html.escape(an)} ({int(art.get("size",0)/1024)}KB)</div>'
                                f'</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<span class="artefact-pill">🖼️ {html.escape(an)}</span>', unsafe_allow_html=True)
            if other_atts:
                pills = " ".join(f'<span class="artefact-pill">📄 {html.escape(a.get("name",""))}</span>' for a in other_atts)
                st.markdown(f'<div style="margin:.2rem 0 .2rem 1rem;">{pills}</div>', unsafe_allow_html=True)

        if not thread and fstatus=="OPEN":
            st.markdown('<div style="color:#6e7681;font-size:.78rem;padding:.4rem .6rem 0;">⏳ Menunggu Developer respond...</div>', unsafe_allow_html=True)

        # Evaluator Action — VERIFY or REJECT
        already_ev = bool(ev_actions)
        if has_dev_resp and not already_ev and fstatus not in ("FIXED","VERIFIED","CLOSED"):
            with st.expander(f"👨‍💻 Evaluator Action — {uid}", expanded=True):
                st.markdown('''<div style="background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.2);
                  border-radius:8px;padding:.6rem .9rem;margin-bottom:.7rem;font-size:.8rem;color:#58a6ff;">
                  ℹ️ <b>Append-only</b> — tidak bisa diubah setelah submit.</div>''', unsafe_allow_html=True)
                ev_txt = st.text_area("Evaluator Action", height=90,
                    key=f"ev_act_{sel_id}_{uid}",
                    placeholder=f"[{datetime.now().strftime('%d%m%Y')}] Hasil review perubahan developer...")
                c_fx, c_ri = st.columns(2)
                with c_fx:
                    if st.button(f"✅ FIXED",key=f"fixed_{sel_id}_{uid}",type="primary",use_container_width=True):
                        if not ev_txt.strip(): st.warning("Isi Evaluator Action.")
                        else:
                            _e = {"type":"evaluator_action","date":datetime.now().strftime("%d%m%Y"),
                                  "datetime":datetime.now().isoformat(),"text":ev_txt.strip(),
                                  "author":st.session_state.get("user_name","Evaluator"),"status":"FIXED","attachments":[]}
                            f_data["resolution_thread"].append(_e)
                            f_data["status"]="FIXED"
                            for obs in eor.get("observations",[]):
                                if obs.get("id")==uid:
                                    obs["resolution_thread"]=f_data["resolution_thread"]; obs["status"]="FIXED"
                            save_eor(eor)
                            simulated_email(to="dev@vendor.co.id",
                                subject=f"[CC-AI] FIXED — {uid} | EOR {sel_id}",
                                body=f"Finding {uid} FIXED.\nEvaluator Action:\n{ev_txt.strip()}")
                            for _tgt in ["developer","cb_auditor","lead_evaluator"]:
                                add_notification(f"✅ FIXED: {uid}","menyatakan finding FIXED",
                                    target=_tgt,sender=st.session_state.get("user_name","Evaluator"),
                                    obj=f"EOR {sel_id}",keterangan=ev_txt[:60],icon="✅")
                            st.success(f"✅ {uid} FIXED!"); st.rerun()
                with c_ri:
                    if st.button(f"🔁 REISSUE",key=f"rei_{sel_id}_{uid}",use_container_width=True):
                        if not ev_txt.strip(): st.warning("Isi Evaluator Action.")
                        else:
                            _e2 = {"type":"evaluator_action","date":datetime.now().strftime("%d%m%Y"),
                                   "datetime":datetime.now().isoformat(),"text":ev_txt.strip(),
                                   "author":st.session_state.get("user_name","Evaluator"),"status":"REISSUE","attachments":[]}
                            f_data["resolution_thread"].append(_e2)
                            f_data["status"]="REISSUE"
                            for obs in eor.get("observations",[]):
                                if obs.get("id")==uid:
                                    obs["resolution_thread"]=f_data["resolution_thread"]; obs["status"]="REISSUE"
                            save_eor(eor)
                            simulated_email(to="dev@vendor.co.id",
                                subject=f"[CC-AI] REISSUE — {uid} | EOR {sel_id}",
                                body=f"Finding {uid} REISSUE — harap perbaiki.\nEvaluator Action:\n{ev_txt.strip()}")
                            for _tgt in ["developer","cb_auditor","lead_evaluator"]:
                                add_notification(f"🔁 REISSUE: {uid}","menyatakan REISSUE — dev perbaiki lagi",
                                    target=_tgt,sender=st.session_state.get("user_name","Evaluator"),
                                    obj=f"EOR {sel_id}",keterangan=ev_txt[:60],icon="🔁")
                            st.warning(f"🔁 {uid} REISSUE!"); st.rerun()
        elif already_ev:
            last_ev = ev_actions[-1]
            _ev_st = last_ev.get("status","")
            _ev_sc = "sb-veri" if _ev_st=="FIXED" else "sb-fail"
            st.markdown(
                f'<div style="background:rgba(88,166,255,.06);border-left:3px solid #58a6ff;'
                f'border-radius:0 8px 8px 0;padding:.6rem .85rem;margin:.3rem 0;">'
                f'<div style="font-size:.7rem;color:#8b949e;">👨‍💻 Evaluator Action sudah diberikan:</div>'
                f'<span class="sb {_ev_sc}">{html.escape(_ev_st)}</span></div>',
                unsafe_allow_html=True)
        st.divider()

def render_collaborative_workspace(eor):
    """v2.0: EOR Workspace disederhanakan.
    - Menampilkan ringkasan re-submit jika ada
    - Komentar Lead lama disembunyikan (hanya tampilkan yang terbaru)
    """
    eor_id = eor.get("id","")
    ws_comments = st.session_state.workspace_comments.setdefault(eor_id,{})
    ws_artefacts = st.session_state.workspace_artefacts.setdefault(eor_id,{})
    
    # Load persisted lead_comment and artefacts from findings into session workspace
    for finding in eor.get("findings",[]):
        uid = finding.get("id","")
        if uid not in ws_comments:
            ws_comments[uid] = []
            # Convert persisted lead_comment back to thread format
            lead_comment = finding.get("lead_comment","")
            lead_verdict = finding.get("lead_verdict","")
            if lead_comment or lead_verdict:
                entry = {
                    "role":"lead_evaluator",
                    "text":lead_comment,
                    "ts":finding.get("override_ts", datetime.now().isoformat()),
                    "artefacts":[],
                    "status":lead_verdict
                }
                ws_comments[uid].append(entry)
        if uid not in ws_artefacts and finding.get("lead_artefacts"):
            ws_artefacts[uid] = finding.get("lead_artefacts",[])
    
    cycle_note = eor.get("cycle_note","")
    
    # === TAMPILKAN BADGE RE-SUBMIT DI HEADER ===
    resubmit_count = eor.get("resubmit_count", 0)
    resubmit_note = eor.get("resubmit_note", "")
    
    if resubmit_count > 0:
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
            <h3 style="margin:0;">📋 EOR Workspace — `{eor_id}`</h3>
            <span style="background:#d29922;color:#0d1117;font-size:.7rem;font-weight:700;padding:4px 12px;border-radius:20px;">
                🔄 RE-SUBMIT #{resubmit_count}
            </span>
        </div>
        """, unsafe_allow_html=True)
        
        # === RINGKASAN RE-SUBMIT UNTUK LEAD ===
        st.markdown(f"""
<div style="background:rgba(88,166,255,.1);border:1px solid rgba(88,166,255,.3);
  border-radius:12px;padding:1rem;margin-bottom:1rem;">
  <div style="font-weight:800;color:#58a6ff;margin-bottom:.5rem;">📝 RINGKASAN RE-SUBMIT #{resubmit_count}</div>
  <div style="font-size:.85rem;color:var(--text);margin-bottom:.5rem;">
    <b>Catatan Evaluator:</b> {html.escape(resubmit_note)}
  </div>
  <div style="font-size:.78rem;color:#8b949e;">
    <b>⚠️ Perubahan yang dilakukan oleh Evaluator:</b>
  </div>
  <ul style="font-size:.78rem;color:#8b949e;margin-top:.3rem;">
    <li>Semua komentar Lead telah di-acknowledge</li>
    <li>Workbook telah direvisi sesuai catatan Lead</li>
    <li>Silakan review ulang findings di bawah</li>
  </ul>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(f"### 📋 EOR Workspace — `{eor_id}`")
    
    c1,c2,c3 = st.columns(3)
    c1.markdown(f"**TOE:** {eor.get('toe_name','')}")
    c2.markdown(f"**EAL:** {eor.get('eal','')}")
    c3.markdown(f"**Submitted by:** {eor.get('submitted_by','')}")
    if cycle_note:
        st.info(f"📝 Catatan Evaluator (Push pertama): {cycle_note}")

    # ── Lead Decision Bar ─────────────────────────────────────────────────
    st.markdown("""<div style="background:rgba(63,185,80,.06);border:1px solid rgba(63,185,80,.2);
      border-radius:12px;padding:1rem 1.2rem;margin:1rem 0;">
      <b style="color:#3fb950;">Lead Evaluator Decision</b>
      <span style="color:#8b949e;font-size:.8rem;margin-left:.5rem;">
        Setelah review semua findings di bawah, pilih aksi:</span>
    </div>""", unsafe_allow_html=True)

    lead_note = st.text_area("Komentar keseluruhan EOR (opsional)",
        value=eor.get("lead_note",""),height=65,key=f"ln_{eor_id}",
        placeholder="Catatan umum untuk evaluator terkait workbook ini...")

    col_rev, col_acc = st.columns(2)
    with col_rev:
        if st.button("🔁 Need Revision — Push to Evaluator",
            key=f"rev_{eor_id}",use_container_width=True,
            help="Kembalikan ke Evaluator untuk diperbaiki"):
            eor["status"]="REVISION"
            eor["workflow_state"] = "BACK_TO_EVALUATOR"
            eor["assigned_role"] = "evaluator"
            eor["active"] = True
            eor["needs_reaudit"] = True

            eor["lead_note"]=lead_note
            eor["revision_at"]=datetime.now().isoformat()
            eor["revised_by"]=st.session_state.user_name
            save_eor(eor)
            add_notification(
                "🔁 Workbook Perlu Revisi",
                f"meminta revisi Workbook {eor_id}",
                target="evaluator",
                sender=st.session_state.get("user_name","Lead Evaluator"),
                obj=f"EOR {eor_id} — {eor.get('toe_name','')}",
                keterangan=lead_note[:80] if lead_note else "Lihat workspace untuk detail",
                icon="🔁"
            )
            st.warning("✅ EOR dikembalikan ke Evaluator. Kanban: ON PROGRESS → **REVISION**")
            st.rerun()

    with col_acc:
        if st.button("✅ Accept All — Push to CB Auditor",
            key=f"acc_{eor_id}",type="primary",use_container_width=True,
            help="Setujui semua verdict dan kirim ke CB Auditor"):
            eor["status"]="APPROVED"
            eor["lead_note"]=lead_note
            eor["approved_by"]=st.session_state.user_name
            eor["approved_at"]=datetime.now().isoformat()
            save_eor(eor)
            add_notification(
                "✅ Workbook Disetujui Lead — Masuk ke CB",
                f"menyetujui Workbook {eor_id} dan meneruskan ke CB Auditor",
                target="cb_auditor",
                sender=st.session_state.get("user_name","Lead Evaluator"),
                obj=f"EOR {eor_id} — {eor.get('toe_name','')} {eor.get('eal','')}",
                keterangan=f"Findings: {len(eor.get('findings',[]))} | Approved: {datetime.now().strftime('%d %b %Y')}",
                icon="✅"
            )
            add_notification(
                "✅ Workbook Anda Disetujui Lead",
                f"menyetujui Workbook EOR {eor_id}",
                target="evaluator",
                sender=st.session_state.get("user_name","Lead Evaluator"),
                obj=f"EOR {eor_id}",
                keterangan="Lanjut ke CB Auditor untuk review final",
                icon="✅"
            )
            st.success("✅ EOR disetujui! Kanban: **ON REVIEW TO CB**. CB Auditor mendapat notifikasi.")
            st.rerun()

    st.divider()
    rev, tot = eor_progress(eor)
    pct = int(rev/tot*100) if tot>0 else 0
    st.markdown(f"**Review progress:** {rev}/{tot} finding dikomentari ({pct}%)")
    st.progress(pct/100)
    st.divider()

    # ── Per-finding review ────────────────────────────────────────────────
    findings = eor.get("findings",[])
    if not findings:
        st.info("Tidak ada findings (semua PASS)."); return

    for finding in findings:
        uid = finding.get("id","")
        thread = ws_comments.setdefault(uid,[])
        artefacts = ws_artefacts.setdefault(uid,[])
        verdict = finding.get("lead_verdict") or finding.get("verdict","")
        dev_f = st.session_state.dev_findings.get(eor_id,{}).get(uid,{})
        dev_status = dev_f.get("status","") if dev_f else ""

        vcolor = {"FAIL":"#f85149","INCONCLUSIVE":"#d29922","PASS":"#3fb950"}.get(verdict,"#8b949e")
        vcsscls = "sb-fail" if verdict=="FAIL" else "sb-inc" if verdict=="INCONCLUSIVE" else "sb-pass"
        lead_v = finding.get("lead_verdict","")
        has_images = finding.get("has_images",False)

        # Finding header card - simplified structure
        _uid_html = html.escape(uid)
        _title_html = html.escape(finding.get('title','')[:80])
        _evidence_html = html.escape(finding.get('evidence','-')[:280])
        _verdict_html = html.escape(verdict)
        _lead_badge = f"<span class='sb sb-veri' style='font-size:.7rem;'>{html.escape(lead_v)}</span>" if lead_v else ""
        _photo_badge = "<span style='font-size:.7rem;color:#3fb950;margin-left:.5rem;'>🖼️ Ada foto bukti</span>" if has_images else ""
        
        st.markdown(f"""<div style="background:var(--bg2);border:1px solid var(--border);border-left:4px solid {vcolor};border-radius:0 12px 12px 0;padding:.9rem 1rem;margin-bottom:.5rem;">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;">
<div style="flex:1;">
<b style="font-family:var(--mono);color:var(--accent);">{_uid_html}</b> {_photo_badge}
<br><span style="font-size:.75rem;color:#8b949e;">{_title_html}</span>
<div style="margin-top:.5rem;padding:.5rem .7rem;background:rgba(255,255,255,.02);border-left:2px solid var(--accent);border-radius:0 4px 4px 0;font-family:var(--mono);font-size:.76rem;color:var(--muted);white-space:pre-wrap;max-height:120px;overflow-y:auto;">{_evidence_html}</div>
</div>
<div style="white-space:nowrap;">
<span class="sb {vcsscls}">{_verdict_html}</span> {_lead_badge}
</div>
</div>
</div>""", unsafe_allow_html=True)

        # Evaluator's comments and override from AI evaluation
        ev_override = finding.get("evaluator_override")
        ev_comment = finding.get("evaluator_comment")
        ev_images = finding.get("evaluator_images",[])
        
        if ev_override or ev_comment or ev_images:
            override_badge = f"<span class='sb sb-veri' style='font-size:.7rem;margin-right:.3rem;'>Evaluator Override: {html.escape(ev_override)}</span>" if ev_override else ""
            st.markdown(f"""
<div style="background:rgba(88,166,255,.07);border-left:3px solid #58a6ff;border-radius:0 8px 8px 0;padding:.7rem .9rem;margin:.3rem 0 .3rem 0;">
  <div style="font-size:.7rem;color:#8b949e;font-weight:600;margin-bottom:.3rem;">👨‍💻 Evaluator Review (dari Audit)</div>
  {override_badge}
  {f'<div style="font-size:.82rem;color:var(--text);margin-top:.3rem;line-height:1.5;">{html.escape(ev_comment)}</div>' if ev_comment else ''}
</div>""", unsafe_allow_html=True)
            
            # Display evaluator evidence images
            if ev_images:
                render_evidence_images(ev_images, caption="Bukti Evaluator")

        # === MODIFIKASI: Hanya tampilkan komentar Lead dari siklus terakhir ===
        # Untuk re-submit, kita hanya tampilkan komentar yang belum di-acknowledge
        # atau komentar dari siklus review terakhir
        
        # Filter komentar berdasarkan timestamp atau status
        if thread:
            st.markdown('<div class="resp-thread">', unsafe_allow_html=True)
            
            # Untuk re-submit, kita bisa menandai komentar lama vs baru
            is_resubmit_case = eor.get("resubmit_count", 0) > 0
            
            for c in thread:
                rc = c.get("role","")
                ri = {"evaluator":"👨‍💻 Evaluator","lead_evaluator":"👥 Lead","system":"⚙️ System"}.get(rc,rc)
                arts_html = ""
                for a in c.get("artefacts",[]):
                    arts_html += f'<span class="artefact-pill">📎 {html.escape(a.get("name","file"))}</span>'
                
                # Tandai komentar yang sudah di-acknowledge
                is_acked = eor.get("revision_acks", {}).get(uid, False)
                ack_badge = '<span class="sb sb-veri" style="font-size:.6rem;margin-left:.5rem;">✓ Acknowledged</span>' if is_acked else ''
                
                st.markdown(
                    f'<div class="resp-bubble {html.escape(rc)}"><div class="resp-meta">{html.escape(ri)} — {html.escape(c.get("ts","")[:16])}</div><div>{html.escape(c.get("text",""))}</div>{arts_html}{ack_badge}</div>',
                    unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Artefact pills
        if artefacts:
            pills = " ".join(f'<span class="artefact-pill">📎 {html.escape(a.get("name",""))} ({int(a.get("size",0)/1024)} KB)</span>' for a in artefacts)
            st.markdown(f'<div style="margin:.25rem 0 .6rem;">{pills}</div>', unsafe_allow_html=True)

        # ── UNIFIED ACTION FORM (v2.0 — 1 click) ─────────────────────────
        with st.expander(f"✏️ Review — {uid}", expanded=False):
            st.markdown("**Isi semua yang relevan, lalu klik Simpan 1x:**")

            row1_c1, row1_c2 = st.columns([2,1])
            with row1_c1:
                new_comment = st.text_area("Komentar Lead",height=70,key=f"lc_{eor_id}_{uid}",
                    placeholder="Komentar, catatan evaluasi, atau instruksi perbaikan...")
            with row1_c2:
                new_verdict = st.selectbox("Override Verdict",
                    ["(keep)",f"PASS — Accept",f"FAIL — Confirm",f"INCONCLUSIVE — Confirm"],
                    key=f"ov_{eor_id}_{uid}")
                artefact_file = st.file_uploader("📎 Attach Proof",
                    type=["png","jpg","jpeg","pdf"],
                    key=f"art_{eor_id}_{uid}",
                    label_visibility="visible")

            if st.button(f"💾 Simpan Review — {uid}",key=f"save_{eor_id}_{uid}",type="primary",use_container_width=True):
                saved_something = False
                entry = {"role":st.session_state.role,"text":"","ts":datetime.now().isoformat(),"artefacts":[]}

                if new_comment.strip():
                    entry["text"] = new_comment.strip()
                    finding["lead_comment"] = new_comment.strip()
                    saved_something = True

                if new_verdict != "(keep)":
                    clean_v = new_verdict.split(" — ")[0]
                    finding["lead_verdict"] = clean_v
                    finding["override_ts"] = datetime.now().isoformat()
                    finding["override_by"] = st.session_state.user_name
                    entry["text"] += f" [OVERRIDE: {verdict}→{clean_v}]"
                    saved_something = True

                if artefact_file is not None:
                    art_entry = {"name":artefact_file.name,"type":artefact_file.type,
                        "size":artefact_file.size,"bytes":artefact_file.getvalue(),
                        "uploaded_by":st.session_state.user_name,"ts":datetime.now().isoformat()}
                    artefacts.append(art_entry)
                    finding.setdefault("lead_artefacts",[]).append(art_entry)
                    entry["artefacts"].append({"name":artefact_file.name,"size":artefact_file.size})
                    saved_something = True

                if saved_something and entry["text"].strip():
                    thread.append(entry)

                if saved_something:
                    save_eor(eor)
                    add_notification(
                        f"💬 Lead mereview {uid}",
                        f"menambahkan review pada finding {uid}",
                        target="evaluator",
                        sender=st.session_state.get("user_name","Lead"),
                        obj=f"EOR {eor_id} → {uid}",
                        keterangan=new_comment[:50] if new_comment.strip() else "Lihat workspace",
                        icon="💬"
                    )
                    st.success(f"✅ Review {uid} disimpan!"); st.rerun()
                else:
                    st.warning("Tidak ada yang disimpan — isi komentar, override, atau attach file.")
        st.markdown("---")
        
# ============================================================
# PROJECT TIMELINE (Gantt)
# ============================================================
def render_cb_kanban():
    """v2.0 CB Kanban: 3 kolom — ON_REVIEW_CB | TM_SCHEDULED | APPROVED
    TM1 harus selesai dulu sebelum bisa pilih TM2
    """
    pg_header("📋","CB Auditor Kanban","ON REVIEW BY CB → TM1 → TM2 → APPROVED")
    approved_eors = [e for e in st.session_state.eor_backlog if e.get("status")=="APPROVED"]
    if not approved_eors:
        st.info("📭 Belum ada EOR yang disetujui Lead. Menunggu Lead Evaluator.")
        return

    cb_kanban = st.session_state.cb_kanban

    col_defs = [
        ("ON_REVIEW_CB","🔍 ON REVIEW BY CB","Workbook diterima dari Lead, CB mereview","#d29922"),
        ("TM_SCHEDULED","📅 TM SCHEDULED","TM1 atau TM2 dijadwalkan","#d2a8ff"),
        ("CB_APPROVED","✅ APPROVED BY CB","CB Auditor menyetujui — Dev Finding dibuka","#3fb950"),
    ]

    cols = st.columns(3)
    for ci,(status,label,desc,color) in enumerate(col_defs):
        with cols[ci]:
            st.markdown(f"""
<div style="background:rgba(0,0,0,.15);border:1px solid {color}40;border-radius:12px;
  padding:.6rem .85rem;margin-bottom:.85rem;">
  <div style="color:{color};font-size:.75rem;font-weight:800;text-transform:uppercase;">{label}</div>
  <div style="color:#6e7681;font-size:.67rem;margin-top:2px;">{desc}</div>
</div>""", unsafe_allow_html=True)

            for eor in approved_eors:
                eid = eor.get("id","")
                cur = cb_kanban.get(eid,"ON_REVIEW_CB")
                
                # Track TM completion status
                tm1_completed = eor.get("tm1_completed", False)
                tm2_completed = eor.get("tm2_completed", False)
                
                if cur != status: 
                    continue

                n_findings = len(eor.get("findings",[]))
                
                # Show TM status badge
                tm_badge = ""
                if tm1_completed:
                    tm_badge = '<span class="sb sb-veri">✅ TM1 Selesai</span>'
                elif tm2_completed:
                    tm_badge = '<span class="sb sb-veri">✅ TM2 Selesai</span>'
                
                st.markdown(f"""
<div class="eor-card" style="border-left:3px solid {color};">
  <div class="eor-card-title">{html.escape(eor.get("toe_name","—"))}</div>
  <div class="eor-card-meta">{html.escape(eid)} | {html.escape(eor.get("eal","—"))}</div>
  <div class="eor-card-meta">👥 Lead: {html.escape(eor.get("approved_by","—"))}</div>
  <div class="eor-card-badges" style="margin-top:.4rem;">
    <span class="sb sb-fail">❌ {n_findings} findings</span>
    {tm_badge}
  </div>
</div>""", unsafe_allow_html=True)

                if status == "ON_REVIEW_CB":
                    btn1, btn2 = st.columns(2)
                    with btn1:
                        # Tombol TM1 - selalu aktif
                        if st.button(f"🔬 TM1 — Konfirmasi Lab",key=f"tm1_{eid}",use_container_width=True):
                            cb_kanban[eid] = "TM_SCHEDULED"
                            eor["cb_tm_type"] = "TM1"
                            eor["tm1_completed"] = False
                            eor["tm2_completed"] = False
                            add_notification("📅 TM1 Dijadwalkan",
                                "menjadwalkan Technical Meeting 1 (konfirmasi Lab)",
                                target="lead_evaluator",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",keterangan="TM1: CB + Lab",icon="📅")
                            add_notification("📅 TM1 Dijadwalkan",
                                "menjadwalkan Technical Meeting 1 dengan CB Auditor",
                                target="evaluator",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",keterangan="Harap konfirmasi jadwal",icon="📅")
                            st.success("✅ TM1 dijadwalkan!")
                            st.rerun()
                    
                    with btn2:
                        # Tombol TM2 - HANYA AKTIF JIKA TM1 SUDAH SELESAI
                        if not tm1_completed:
                            st.button(f"🚀 TM2 — Locked (Selesaikan TM1 dulu)", 
                                key=f"tm2_disabled_{eid}",
                                use_container_width=True,
                                disabled=True,
                                help="TM2 hanya bisa dipilih setelah TM1 selesai")
                        else:
                            if st.button(f"🚀 TM2 — Lab+CB+Dev",key=f"tm2_{eid}",use_container_width=True):
                                cb_kanban[eid] = "TM_SCHEDULED"
                                eor["cb_tm_type"] = "TM2"
                                st.session_state.tm2_done = False
                                add_notification("📅 TM2 Dijadwalkan",
                                    "menjadwalkan Technical Meeting 2 (Lab + CB + Developer)",
                                    target="lead_evaluator",
                                    sender=st.session_state.get("user_name","CB Auditor"),
                                    obj=f"EOR {eid}",keterangan="TM2: CB + Lab + Developer",icon="📅")
                                add_notification("📅 TM2 Dijadwalkan",
                                    "menjadwalkan Technical Meeting 2 bersama CB dan Developer",
                                    target="evaluator",
                                    sender=st.session_state.get("user_name","CB Auditor"),
                                    obj=f"EOR {eid}",keterangan="Harap konfirmasi jadwal TM2",icon="📅")
                                st.success("✅ TM2 dijadwalkan!")
                                st.rerun()

                elif status == "TM_SCHEDULED":
                    tm_type = eor.get("cb_tm_type","TM1")
                    
                    st.caption(f"Tipe: {tm_type}")
                    
                    if tm_type == "TM1" and not tm1_completed:
                        if st.button(f"✅ Selesaikan TM1 — {eid}",key=f"complete_tm1_{eid}",type="primary",use_container_width=True):
                            eor["tm1_completed"] = True
                            add_notification("✅ TM1 Selesai",
                                "Technical Meeting 1 telah selesai",
                                target="lead_evaluator",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",
                                keterangan="TM1 selesai, sekarang bisa lanjut ke TM2",
                                icon="✅")
                            st.success(f"✅ TM1 untuk {eid} telah selesai! Sekarang bisa pilih TM2.")
                            # Kembalikan ke ON_REVIEW_CB agar bisa pilih TM2
                            cb_kanban[eid] = "ON_REVIEW_CB"
                            st.rerun()
                    
                    elif tm_type == "TM2" and not tm2_completed:
                        if st.button(f"✅ Selesaikan TM2 & Approve — {eid}",key=f"complete_tm2_{eid}",type="primary",use_container_width=True):
                            cb_kanban[eid] = "CB_APPROVED"
                            eor["tm2_completed"] = True
                            eor["cb_approved_at"] = datetime.now().isoformat()
                            eor["cb_approved_by"] = st.session_state.user_name
                            # Unlock dev findings after TM2
                            st.session_state.tm2_done = True
                            st.session_state.cycle = 2
                            add_notification("🔓 My Findings Dibuka",
                                "membuka akses Developer Findings setelah TM2",
                                target="developer",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",
                                keterangan="Akses My Findings sekarang tersedia — harap respond sesuai deadline",
                                icon="🔓")
                            add_notification("✅ CB Approve",
                                "menyetujui workbook EOR",
                                target="lead_evaluator",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",
                                keterangan=f"Setelah {tm_type}",icon="✅")
                            add_notification("✅ CB Approve",
                                "menyetujui workbook EOR Anda",
                                target="evaluator",
                                sender=st.session_state.get("user_name","CB Auditor"),
                                obj=f"EOR {eid}",icon="✅")
                            st.success(f"✅ EOR {eid} disetujui CB!")
                            st.rerun()
                    
                    elif tm_type == "TM1" and tm1_completed:
                        st.info("✅ TM1 sudah selesai. Silakan pilih TM2 di kolom ON_REVIEW_CB")
                        if st.button(f"↩ Kembali ke ON_REVIEW_CB",key=f"back_{eid}",use_container_width=True):
                            cb_kanban[eid] = "ON_REVIEW_CB"
                            st.rerun()

                elif status == "CB_APPROVED":
                    st.caption("✅ EOR sudah disetujui")
                    if st.button(f"↩ Kembali ke ON_REVIEW_CB",key=f"back2_{eid}",use_container_width=True):
                        cb_kanban[eid] = "ON_REVIEW_CB"
                        st.rerun()


def render_cb_tm_management():
    """v2.0 FINAL CB TM Management:
    - TM1: schedule + minutes, peserta CB+Lab only
    - TM2: schedule + minutes + CB writes Issue Description per finding
           CB push findings to Dev → email sim → Dev Dashboard unlocked
    """
    pg_header("📅","TM Management","TM1: CB+Lab | TM2: CB+Lab+Dev → Push Findings ke Developer")

    approved_eors = [e for e in st.session_state.eor_backlog if e.get("status")=="APPROVED"]
    if not approved_eors:
        st.info("Belum ada EOR yang disetujui Lead. Tunggu Lead Evaluator approve dulu."); return

    cb_kanban = st.session_state.cb_kanban

    # Select EOR
    eor_opts = {f"{e['id']} — {e.get('toe_name','')} ({e.get('eal','')})":e for e in approved_eors}
    sel_label = st.selectbox("Pilih EOR", list(eor_opts.keys()))
    eor = eor_opts[sel_label]
    eid = eor.get("id","")
    tm_type = eor.get("cb_tm_type","TM1")

    tab_schedule, tab_minutes, tab_push = st.tabs([
        "📅 Schedule TM",
        "📝 TM Minutes",
        f"🚀 Push Findings ke Developer {'(TM2 only)' if tm_type=='TM1' else ''}"
    ])

    # ── TAB 1: Schedule ───────────────────────────────────────────────────
    with tab_schedule:
        st.markdown(f"**Tipe TM yang dipilih di Kanban:** `{tm_type}`")
        if tm_type == "TM1":
            st.info("TM1 — Peserta: **CB Auditor + Lab (Evaluator + Lead)**. Developer tidak ikut TM1.")
        else:
            st.success("TM2 — Peserta: **CB Auditor + Lab + Developer**. Output: findings final dikirim ke Dev.")

        c1,c2,c3 = st.columns(3)
        with c1: tm_date = st.date_input("Tanggal",key=f"tmd_{eid}")
        with c2: tm_time = st.time_input("Waktu",key=f"tmt_{eid}")
        with c3: platform = st.selectbox("Platform",["Google Meet","Microsoft Teams","Zoom"],key=f"tmp_{eid}")

        st.markdown("**Peserta:**")
        at_lead = st.text_input("Lead Evaluator",value="lead@cc-lab.go.id",key=f"atl_{eid}")
        at_eval = st.text_input("Evaluator",value="evaluator@cc-lab.go.id",key=f"ate_{eid}")
        at_dev  = ""
        if tm_type == "TM2":
            at_dev = st.text_input("Developer",value="dev@vendor.co.id",key=f"atd_{eid}")

        tm_agenda = st.text_area("Agenda",height=80,key=f"tma_{eid}",
            placeholder="1. Review findings\n2. Konfirmasi evidence\n3. Tentukan deadline")

        if st.button("📧 Kirim Undangan TM",key=f"inv_{eid}",type="primary"):
            link = "https://meet.google.com/abc-xyz" if platform=="Google Meet"                    else f"https://teams.microsoft.com/l/meetup-join/{random.randint(1000000,9999999)}"
            tm_rec = {"id":f"TM-{eid}-{tm_type}","eor_id":eid,"type":tm_type,
                "date":str(tm_date),"time":tm_time.strftime("%H:%M"),"link":link,
                "platform":platform,"agenda":tm_agenda,
                "attendees":[at_lead,at_eval]+([at_dev] if at_dev else []),"status":"scheduled"}
            st.session_state.tm_schedules.append(tm_rec)
            attendees = [at_lead, at_eval] + ([at_dev] if at_dev else [])
            for email in attendees:
                simulated_email(
                    to=email,
                    subject=f"[CC-AI] Undangan {tm_type} — EOR {eid}",
                    body=(f"Yth. Tim Evaluasi,\n\n"
                          f"Anda diundang dalam {tm_type} untuk EOR {eid}.\n\n"
                          f"Tanggal: {tm_date} {tm_time.strftime('%H:%M')}\n"
                          f"Platform: {platform}\nLink: {link}\n\n"
                          f"Agenda:\n{tm_agenda}\n\nSalam,\nCB Auditor")
                )
            for t in ["lead_evaluator","evaluator"]:
                add_notification(f"📅 Undangan {tm_type}",
                    f"mengundang Anda ke {tm_type} untuk EOR {eid}",
                    target=t,
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"{str(tm_date)} {tm_time.strftime('%H:%M')} | {platform}",
                    keterangan=f"Link: {link}",icon="📅")
            if at_dev:
                add_notification("📅 Undangan TM2",
                    "mengundang Anda ke Technical Meeting 2",
                    target="developer",
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"{str(tm_date)} {tm_time.strftime('%H:%M')} | {platform}",
                    keterangan="Findings EOR akan dibahas dalam TM ini",icon="📅")
            st.success(f"✅ Undangan {tm_type} terkirim! Link: {link}")
            # Show email simulation
            with st.expander("📧 Preview Email Terkirim"):
                for em in st.session_state.get("email_log",[])[-len(attendees):]:
                    st.markdown(f"**To:** `{em['to']}`")
                    st.code(em["body"])

    # ── TAB 2: Minutes ────────────────────────────────────────────────────
    with tab_minutes:
        existing_tms = [t for t in st.session_state.tm_schedules
                        if t.get("eor_id")==eid and t.get("type")==tm_type]
        if not existing_tms:
            st.info(f"Jadwalkan {tm_type} dulu di tab Schedule."); return

        tm = existing_tms[-1]
        st.markdown(f"**{tm_type}** | {tm.get('date','')} {tm.get('time','')} | {tm.get('platform','')}")
        st.markdown(f"Link: `{tm.get('link','')}`")

        minutes = st.text_area("Notulen TM",height=120,key=f"mins_{eid}",
            value=tm.get("minutes",""),
            placeholder="Ringkasan diskusi dan keputusan...")
        decisions = st.text_area("Keputusan / Action Items",height=80,key=f"dec_{eid}",
            value=tm.get("decisions",""),
            placeholder="- Evaluator: revisi workbook ASE_INT\n- Dev: update ST §3.2 dalam 14 hari")

        c1,c2 = st.columns(2)
        with c1: lab_dl = st.date_input("Deadline Lab",key=f"lad_{eid}",
            value=date.today()+timedelta(days=14))
        with c2:
            dev_dl = st.date_input("Deadline Developer",key=f"devdl_{eid}",
                value=date.today()+timedelta(days=21)) if tm_type=="TM2" else None

        if st.button("💾 Simpan Minutes",key=f"savemins_{eid}",type="primary"):
            tm["minutes"]=minutes; tm["decisions"]=decisions
            tm["lab_deadline"]=str(lab_dl); tm["status"]="completed"
            if dev_dl: tm["dev_deadline"]=str(dev_dl)
            add_notification(f"📝 {tm_type} Minutes",
                f"mengirim minutes {tm_type}",target="evaluator",
                sender=st.session_state.get("user_name","CB Auditor"),
                obj=f"EOR {eid}",keterangan=f"Deadline Lab: {lab_dl}",icon="📝")
            add_notification(f"📝 {tm_type} Minutes",
                f"mengirim minutes {tm_type}",target="lead_evaluator",
                sender=st.session_state.get("user_name","CB Auditor"),
                obj=f"EOR {eid}",keterangan=decisions[:60],icon="📝")
            if tm_type=="TM2":
                add_notification("📝 TM2 Minutes + Deadline",
                    f"mengirim minutes TM2 dengan deadline perbaikan",target="developer",
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"EOR {eid}",
                    keterangan=f"Deadline: {dev_dl} | My Findings akan segera dibuka",icon="📝")
            st.success("✅ Minutes disimpan!")

    # ── TAB 3: Push Findings ke Developer (TM2 only) ──────────────────────
    with tab_push:
        if tm_type == "TM1":
            st.warning("TM1 tidak mengirim findings ke Developer. Pilih TM2 di Kanban jika ingin push ke Dev.")
            return

        st.markdown("### 📋 Tulis Issue Description per Finding (CB writes — immutable setelah push)")
        st.info("**Penting:** Issue Description yang ditulis CB di sini tidak bisa diubah setelah di-push. "
                "Ini adalah narasi final hasil TM2 yang dikirim ke Developer.")

        observations = eor.get("observations", [])
        if not observations:
            st.warning("Tidak ada observations. Push EOR dari Evaluator dulu."); return

        # CB writes Issue Description per observation
        cb_issues = {}
        for obs in observations:
            uid = obs.get("id","")
            existing_issue = obs.get("issue_description","")
            already_pushed = obs.get("pushed_to_dev", False)

            # Color by AI verdict
            vcolor = {"FAIL":"#f85149","INCONCLUSIVE":"#d29922","PASS":"#3fb950"}.get(
                obs.get("verdict_ai",""),"#8b949e")

            with st.expander(
                f"{'✅' if already_pushed else '📝'} {uid} — "
                f"{obs.get('verdict_ai','')} | {obs.get('cc_component',uid)[:60]}",
                expanded=not already_pushed):

                c1,c2 = st.columns([2,1])
                with c1:
                    st.markdown(f"**CC Component:** `{obs.get('cc_component','')}`")
                    st.markdown(f"**Eval Reference:** `{obs.get('eval_reference','')}`")
                with c2:
                    deadline_key = f"obs_dl_{eid}_{uid}"
                    obs_dl = st.date_input("Deadline Dev",key=deadline_key,
                        value=date.today()+timedelta(days=21))
                    priority = st.selectbox("Prioritas",["MAJOR","MINOR","INFO"],
                        key=f"pri_{eid}_{uid}")

                if already_pushed:
                    st.markdown(f"""
<div style="background:rgba(63,185,80,.08);border:1px solid rgba(63,185,80,.2);
  border-radius:8px;padding:.75rem;margin:.5rem 0;">
  <div style="font-size:.72rem;color:#3fb950;font-weight:700;">✅ SUDAH DI-PUSH KE DEV — IMMUTABLE</div>
  <div style="font-size:.82rem;color:#e6edf3;margin-top:.3rem;">{obs.get("issue_description","")}</div>
</div>""", unsafe_allow_html=True)
                else:
                    issue_text = st.text_area(
                        "Issue Description (narasi CB — hasil TM2)",
                        value=existing_issue,
                        height=100,
                        key=f"issue_{eid}_{uid}",
                        placeholder=f"[{datetime.now().strftime('%d%m%Y')}] Berdasarkan review TM2, "
                                    f"ditemukan bahwa {uid} tidak memenuhi requirement karena... "
                                    f"Developer diminta untuk..."
                    )
                    cb_issues[uid] = {
                        "text": issue_text,
                        "deadline": str(obs_dl),
                        "priority": priority
                    }

        st.divider()

        # Summary of what will be pushed
        to_push = [obs for obs in observations
                   if not obs.get("pushed_to_dev",False)
                   and cb_issues.get(obs.get("id",""),{}).get("text","").strip()]
        already_pushed_count = sum(1 for obs in observations if obs.get("pushed_to_dev",False))

        c1,c2 = st.columns(2)
        c1.metric("📤 Siap di-push", len(to_push))
        c2.metric("✅ Sudah di-push", already_pushed_count)

        dev_email_target = st.text_input("Email Developer",value="dev@vendor.co.id",key=f"devemail_{eid}")

        if to_push:
            if st.button(f"🚀 Push {len(to_push)} Findings ke Developer",
                key=f"push_dev_{eid}",type="primary",use_container_width=True):

                # Write issue descriptions — immutable after this
                for obs in observations:
                    uid = obs.get("id","")
                    if uid in cb_issues and cb_issues[uid]["text"].strip():
                        obs["issue_description"] = cb_issues[uid]["text"].strip()
                        obs["issue_written_by"] = st.session_state.get("user_name","CB Auditor")
                        obs["issue_written_at"] = datetime.now().isoformat()
                        obs["pushed_to_dev"] = True
                        obs["dev_deadline"] = cb_issues[uid]["deadline"]
                        obs["priority"] = cb_issues[uid]["priority"]
                        obs["status"] = "OPEN"
                        obs["resolution_thread"] = []

                        # Initialize dev_findings in session
                        df_eor = st.session_state.dev_findings.setdefault(eid, {})
                        df_eor[uid] = {
                            "uid": uid,
                            "no": obs.get("no",1),
                            "cc_component": obs.get("cc_component",uid),
                            "eval_reference": obs.get("eval_reference",""),
                            "issue_description": obs["issue_description"],
                            "priority": obs["priority"],
                            "dev_deadline": obs["dev_deadline"],
                            "status": "OPEN",
                            "resolution_thread": [],
                            "assigned_to": "developer",
                            "pushed_by": st.session_state.get("user_name","CB Auditor"),
                            "pushed_at": datetime.now().isoformat(),
                            "source": "TM2"
                        }

                # Save to disk
                eor["status_dev"] = "FINDINGS_PUSHED"
                save_eor(eor)

                # Unlock dev dashboard
                st.session_state.tm2_done = True
                st.session_state.cycle = 2

                # Email simulation to Dev
                finding_lines = ""
                for obs in observations:
                    if obs.get("pushed_to_dev") and obs.get("issue_description","").strip():
                        finding_lines += (
                            f"\n{'─'*50}\n"
                            f"No. {obs.get('no','')} | {obs.get('cc_component','')}\n"
                            f"Eval Ref: {obs.get('eval_reference','')}\n"
                            f"Prioritas: {obs.get('priority','')} | Deadline: {obs.get('dev_deadline','')}\n"
                            f"Issue Description:\n{obs.get('issue_description','')}\n"
                        )

                simulated_email(
                    to=dev_email_target,
                    subject=f"[CC-AI TM2] Action Required — Findings EOR {eid} untuk {eor.get('toe_name','')}",
                    body=(
                        f"Yth. Developer/Sponsor,\n\n"
                        f"Berikut adalah findings hasil Technical Meeting 2 (TM2) yang perlu "
                        f"Anda tindaklanjuti:\n"
                        f"\nEOR ID   : {eid}"
                        f"\nTOE      : {eor.get('toe_name','')} {eor.get('toe_version','')}"
                        f"\nEAL      : {eor.get('eal','')}"
                        f"\n\n=== OBSERVATIONS ===\n"
                        f"{finding_lines}"
                        f"\n\nSilakan login ke CC-AI Platform untuk mengisi Resolution "
                        f"(Sponsor/Developer Action) dan attach bukti perbaikan."
                        f"\n\nAkses platform: https://cc-ai.lab.bssn.go.id:8501"
                        f"\n\nSalam,\nCB Auditor — {st.session_state.get('user_name','')}"
                    )
                )

                # Notifications
                add_notification("🚀 Findings TM2 Dikirim ke Dev",
                    f"mem-push {len(to_push)} findings TM2 ke Developer",
                    target="developer",
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"EOR {eid} — {eor.get('toe_name','')}",
                    keterangan="My Findings sekarang aktif — login dan respond sesuai deadline",
                    icon="🔓")
                add_notification("📤 Findings TM2 Di-push ke Dev",
                    f"mem-push {len(to_push)} findings ke Developer",
                    target="lead_evaluator",
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"EOR {eid}",keterangan="Developer akan meresolve findings",icon="📤")
                add_notification("📤 Findings TM2 Di-push ke Dev",
                    "findings sudah dikirim ke Developer — tunggu response Dev untuk re-audit",
                    target="evaluator",
                    sender=st.session_state.get("user_name","CB Auditor"),
                    obj=f"EOR {eid}",
                    keterangan="Setelah Dev respond, Evaluator mengisi Evaluator Action",
                    icon="📤")

                st.success(f"✅ {len(to_push)} findings berhasil di-push ke Developer!")
                st.info(f"📧 Email terkirim ke: {dev_email_target}")

                # Show email preview
                with st.expander("📧 Preview Email ke Developer"):
                    em = st.session_state.get("email_log",[])
                    if em:
                        st.markdown(f"**To:** `{em[-1]['to']}`")
                        st.markdown(f"**Subject:** {em[-1]['subject']}")
                        st.code(em[-1]["body"])
                st.rerun()
        else:
            if already_pushed_count == len(observations):
                st.success("✅ Semua findings sudah di-push ke Developer.")
            else:
                st.warning("Isi Issue Description untuk findings yang akan di-push.")


def page_cb_dev_responses():
    """CB Auditor: Monitor Dev responses — read-only view with images."""
    pg_header("💬","Dev Response Monitoring","Monitor Dev responses per finding | CB View")
    dev_findings = st.session_state.dev_findings
    if not dev_findings:
        st.info("📭 Belum ada Dev responses. Findings aktif setelah CB push TM2."); return

    all_f = [(eid,uid,f) for eid,units in dev_findings.items() for uid,f in units.items()]
    n_open = sum(1 for _,_,f in all_f if f.get("status","OPEN")=="OPEN")
    n_resp = sum(1 for _,_,f in all_f if f.get("status")=="RESPONDED")
    n_fix  = sum(1 for _,_,f in all_f if f.get("status") in ("FIXED","VERIFIED"))
    n_rei  = sum(1 for _,_,f in all_f if f.get("status")=="REISSUE")

    st.markdown(f"""<div class="metric-grid">
      {metric_html(len(all_f),"📋 Total","#58a6ff")}
      {metric_html(n_open,"⏳ Open","#6e7681")}
      {metric_html(n_resp,"💬 Dev Responded","#d29922")}
      {metric_html(n_fix,"✅ Fixed","#3fb950")}
      {metric_html(n_rei,"🔁 Reissue","#f85149")}
    </div>""", unsafe_allow_html=True)

    eor_ids = list(dev_findings.keys())
    sel_eor = st.selectbox("Filter EOR", ["Semua"] + eor_ids)
    st.divider()

    for eid, units in dev_findings.items():
        if sel_eor != "Semua" and eid != sel_eor: continue
        eor_obj = next((e for e in st.session_state.eor_backlog if e.get("id")==eid), {})
        st.markdown(f"#### 📋 EOR {eid} — {eor_obj.get('toe_name','')} {eor_obj.get('eal','')}")
        for uid, f_data in units.items():
            thread  = f_data.get("resolution_thread",[])
            fstatus = f_data.get("status","OPEN")
            if not thread and fstatus=="OPEN": continue
            pri   = f_data.get("priority","MAJOR")
            pri_c = {"MAJOR":"#f85149","MINOR":"#d29922","INFO":"#58a6ff"}.get(pri,"#8b949e")
            sc    = {"OPEN":"sb-open","IN_PROGRESS":"sb-prog","RESPONDED":"sb-resp",
                     "FIXED":"sb-veri","VERIFIED":"sb-veri","REISSUE":"sb-fail"}.get(fstatus,"sb-open")
            with st.expander(f"`{uid}` [{pri}] — {html.escape(f_data.get('title',uid)[:60])} | {fstatus}",
                             expanded=(fstatus=="RESPONDED")):
                st.markdown(f'<div style="font-size:.78rem;color:#8b949e;margin-bottom:.5rem;">'
                    f'Issue: {html.escape(f_data.get("issue_description","—")[:100])}</div>',
                    unsafe_allow_html=True)
                for entry in thread:
                    etype  = entry.get("type","")
                    edate  = entry.get("date","")
                    etext  = html.escape(entry.get("text",""))
                    ev_s   = entry.get("status","")
                    e_atts = entry.get("attachments",[])
                    if etype=="dev_action":         bg="rgba(255,166,87,.07)"; bc="#ffa657"; lbl=f"🛠️ Dev Action — {edate}"
                    elif etype=="evaluator_action": bg="rgba(88,166,255,.07)"; bc="#58a6ff"; lbl=f"👨‍💻 Evaluator Action — {edate}"
                    else:                           bg="rgba(110,118,129,.07)"; bc="#6e7681"; lbl=edate
                    sv_h = (f'<span class="sb {"sb-veri" if ev_s=="FIXED" else "sb-fail"}">{html.escape(ev_s)}</span>'
                            if ev_s else "")
                    st.markdown(
                        f'<div style="background:{bg};border-left:3px solid {bc};'
                        f'border-radius:0 8px 8px 0;padding:.65rem .85rem;margin:.25rem 0 .25rem 1rem;">'
                        f'<div style="font-size:.7rem;color:#8b949e;">{html.escape(lbl)} {sv_h}</div>'
                        f'<div style="font-size:.82rem;color:var(--text);">{etext}</div></div>',
                        unsafe_allow_html=True)
                    img_atts = [a for a in e_atts
                        if a.get("type","").startswith("image/") or
                        a.get("name","").lower().endswith((".png",".jpg",".jpeg",".gif",".webp"))]
                    other_atts = [a for a in e_atts if a not in img_atts]
                    if img_atts:
                        n_ic = min(len(img_atts),3)
                        i_cols = st.columns(n_ic)
                        for ci3, art in enumerate(img_atts):
                            ab=art.get("bytes"); an=art.get("name","img")
                            with i_cols[ci3%n_ic]:
                                if ab:
                                    _ext=an.lower().rsplit(".",1)[-1] if "." in an else "png"
                                    _mime={"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png",
                                           "gif":"image/gif","webp":"image/webp"}.get(_ext,"image/png")
                                    _b64=base64.b64encode(ab).decode()
                                    st.markdown(
                                        f'<img src="data:{_mime};base64,{_b64}" '
                                        f'style="width:100%;border-radius:6px;border:1px solid var(--border);" '
                                        f'title="{html.escape(an)}" />', unsafe_allow_html=True)
                                    st.caption(an)
                    if other_atts:
                        pills=" ".join(f'<span class="artefact-pill">📄 {html.escape(a.get("name",""))}</span>' for a in other_atts)
                        st.markdown(f'<div style="margin:.2rem 0;">{pills}</div>', unsafe_allow_html=True)
        st.divider()

def render_project_timeline():
    """v2.0 Timeline: 
    - Opsi assign evaluator dengan deadline + notifikasi ke evaluator dashboard
    - Dev timeline: kosong Cycle 1, aktif setelah TM2 (Cycle 2)"""
    pg_header("📅","Project Timeline","Gantt | Assign Evaluator | Dev Timeline (Cycle 2)")
    if not st.session_state.eor_backlog:
        st.info("Belum ada proyek."); return
    today = date.today()

    tab_gantt, tab_ev_assign, tab_dev_tl = st.tabs([
        "📊 Gantt Chart",
        "👨‍💻 Assign Evaluator",
        f"🛠️ Dev Timeline {'(Cycle 2 — setelah TM2)' if not st.session_state.tm2_done else ''}"
    ])

    with tab_gantt:
        rows = []
        for e in st.session_state.eor_backlog:
            start_str = e.get("submitted_at","")[:10] if e.get("submitted_at") else str(today)
            due_str = e.get("due_date") or str(today+timedelta(days=14))
            rows.append({
                "Task":f"{e.get('id','')} — {e.get('toe_name','')[:20]}",
                "Start":start_str,"Finish":due_str,
                "Status":e.get("status","DRAFT"),
                "Findings":len(e.get("findings",[])),"EAL":e.get("eal","—")
            })
        if rows:
            df = pd.DataFrame(rows)
            status_colors = {"DRAFT":"#6e7681","IN_AUDIT":"#58a6ff","SUBMITTED":"#58a6ff",
                "UNDER_REVIEW":"#d29922","REVISION":"#f85149","APPROVED":"#3fb950"}
            try:
                fig = px.timeline(df,x_start="Start",x_end="Finish",y="Task",color="Status",
                    color_discrete_map=status_colors,hover_data={"Findings":True,"EAL":True,"Status":True})
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                    height=max(200,len(rows)*45+80),
                    font=dict(family="Outfit",size=11,color="#e6edf3"),
                    xaxis=dict(gridcolor="#30363d"),yaxis=dict(gridcolor="#30363d"),
                    legend=dict(bgcolor="rgba(0,0,0,0)",font=dict(color="#8b949e")))
                fig.add_vline(x=str(today),line_dash="dash",line_color="#f85149",
                    annotation_text="Today",annotation_font_color="#f85149",annotation_font_size=11)
                st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
            except:
                st.dataframe(df,use_container_width=True,hide_index=True)

    with tab_ev_assign:
        st.markdown("### 👨‍💻 Assign Evaluator ke EOR + Set Deadline")
        ev_timeline = st.session_state.evaluator_timeline
        for e in st.session_state.eor_backlog:
            eid = e.get("id","")
            existing = ev_timeline.get(eid,{})
            with st.expander(f"📋 {eid} — {e.get('toe_name','')} ({e.get('status','')})",
                expanded=(not existing)):
                ev_users = [u for u,info in USERS.items() if info["role"]=="evaluator"]
                ev_names = {u:USERS[u]["name"] for u in ev_users}
                c1,c2,c3 = st.columns(3)
                with c1:
                    cur_ev = existing.get("assignee","")
                    ev_opts = ["(pilih)"]+ev_users
                    cur_idx = ev_opts.index(cur_ev) if cur_ev in ev_opts else 0
                    sel_ev = st.selectbox("Evaluator",ev_opts,index=cur_idx,
                        format_func=lambda x:"(pilih)" if x=="(pilih)" else f"{ev_names.get(x,x)} ({x})",
                        key=f"evass_{eid}")
                with c2:
                    start_d = st.date_input("Start Date",key=f"evs_{eid}",
                        value=datetime.fromisoformat(existing["start"]).date() if existing.get("start") else today)
                with c3:
                    end_d = st.date_input("Deadline",key=f"eve_{eid}",
                        value=datetime.fromisoformat(existing["end"]).date() if existing.get("end") else today+timedelta(days=14))

                note = st.text_input("Catatan untuk Evaluator",key=f"evnote_{eid}",
                    value=existing.get("note",""),placeholder="e.g. Fokus pada ASE_INT dan ASE_CCL dulu")

                if st.button(f"💾 Assign & Notifikasi",key=f"evassign_{eid}",type="primary"):
                    if sel_ev != "(pilih)":
                        ev_timeline[eid] = {
                            "assignee":sel_ev,"start":str(start_d),
                            "end":str(end_d),"note":note,
                            "assigned_by":st.session_state.get("user_name","Lead"),
                            "assigned_at":datetime.now().isoformat()
                        }
                        add_notification(
                            f"📅 Assignment Baru: {eid}",
                            f"menugaskan Anda untuk mengerjakan EOR {eid}",
                            target="evaluator",
                            sender=st.session_state.get("user_name","Lead Evaluator"),
                            obj=f"EOR {eid} — {e.get('toe_name','')}",
                            keterangan=f"Deadline: {end_d} | {note}" if note else f"Deadline: {end_d}",
                            icon="📅"
                        )
                        st.success(f"✅ Assigned ke {ev_names.get(sel_ev,sel_ev)}! Notifikasi terkirim."); st.rerun()
                    else:
                        st.warning("Pilih evaluator terlebih dahulu.")

    with tab_dev_tl:
        if not st.session_state.tm2_done:
            st.markdown("""
<div style="background:rgba(0,0,0,.4);border-radius:16px;padding:3rem;text-align:center;">
  <div style="font-size:2rem;margin-bottom:.75rem;">🔒</div>
  <div style="font-size:1rem;color:#e6edf3;font-weight:700;margin-bottom:.5rem;">Dev Timeline Terkunci</div>
  <div style="color:#8b949e;font-size:.85rem;">Developer Timeline hanya aktif setelah CB Auditor menyelesaikan<br>
  <b>Technical Meeting 2 (TM2)</b> dan meng-approve workbook.<br>
  Cycle 1 masih berlangsung.</div>
</div>""", unsafe_allow_html=True)
        else:
            st.success("🔓 Dev Timeline aktif — Cycle 2 berjalan (setelah TM2)")
            dev_timeline = st.session_state.dev_timeline
            dev_users = [u for u,info in USERS.items() if info["role"]=="developer"]
            dev_names = {u:USERS[u]["name"] for u in dev_users}

            for e in st.session_state.eor_backlog:
                eid = e.get("id","")
                dev_founds = st.session_state.dev_findings.get(eid,{})
                if not dev_founds: continue

                with st.expander(f"🛠️ Dev Timeline — {eid} ({len(dev_founds)} findings)"):
                    for uid, fdata in dev_founds.items():
                        tl_key = f"{eid}_{uid}"
                        existing_tl = dev_timeline.get(tl_key,{})
                        c1,c2,c3 = st.columns(3)
                        with c1:
                            st.markdown(f"**`{uid}`** — {fdata.get('title',uid)[:45]}")
                            st.markdown(f'<span class="sb {FINDING_CSS.get(fdata.get("status","OPEN"),"sb-open")}">{fdata.get("status","OPEN")}</span>', unsafe_allow_html=True)
                        with c2:
                            dev_d = st.date_input("Deadline Dev",key=f"devtl_{tl_key}",
                                value=datetime.fromisoformat(existing_tl["deadline"]).date()
                                    if existing_tl.get("deadline") else today+timedelta(days=14))
                        with c3:
                            priority = st.selectbox("Prioritas",["MAJOR","MINOR","INFO"],
                                key=f"devpri_{tl_key}",
                                index=["MAJOR","MINOR","INFO"].index(existing_tl.get("priority","MAJOR")))

                        if st.button(f"💾 Set Dev Timeline {uid}",key=f"setdevtl_{tl_key}"):
                            dev_timeline[tl_key] = {"deadline":str(dev_d),"priority":priority,
                                "set_by":st.session_state.get("user_name","Lead"),
                                "set_at":datetime.now().isoformat()}
                            add_notification(
                                f"📅 Deadline Finding {uid}",
                                f"menetapkan deadline perbaikan finding {uid}",
                                target="developer",
                                sender=st.session_state.get("user_name","Lead Evaluator"),
                                obj=f"{uid} [{priority}] — EOR {eid}",
                                keterangan=f"Deadline: {dev_d}",icon="📅")
                            st.success(f"✅ Dev timeline {uid} ditetapkan!"); st.rerun()
                        st.divider()

# ============================================================
# AUTH
# ============================================================
def login_page():
    pg_header("🔒","CC-AI Smart Platform v2.0","Cycle 1: Evaluator → Lead | Cycle 2: CB → Dev | Junior RCC AI Skills")
    _,col,_=st.columns([1,1.1,1])
    with col:
        dm=st.toggle("🌙 Dark Mode",value=st.session_state.dark_mode,key="ldm")
        if dm!=st.session_state.dark_mode: st.session_state.dark_mode=dm; st.rerun()
        pending=st.session_state.get("pending_user")
        if not pending:
            with st.form("lf"):
                st.markdown("### 🔐 Login")
                un=st.text_input("👤 Username"); pw=st.text_input("🔑 Password",type="password")
                if st.form_submit_button("Masuk →",type="primary",use_container_width=True):
                    if un in USERS and USERS[un]["password"]==pw:
                        code=str(random.randint(1000,9999))
                        st.session_state.two_factor_code=code
                        for k,v in [("pending_user",un),("pending_email",USERS[un]["email"]),("pending_role",USERS[un]["role"]),("pending_name",USERS[un]["name"]),("pending_avatar",USERS[un]["avatar"])]:
                            st.session_state[k]=v
                        st.success(f"✅ 2FA → {USERS[un]['email']} (demo: **{code}**)"); st.rerun()
                    else: st.error("❌ Credentials salah!")
        else:
            st.info(f"📧 Kode 2FA → **{st.session_state.pending_email}**")
            current_2fa = st.session_state.get("two_factor_code", "")
            if current_2fa:
                st.markdown(
                    f"""
                    <div style='display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;'>
                        <div style='padding:0.6rem 0.85rem;background:rgba(56,139,253,.12);border-radius:0.45rem;color:#c3d0e8;font-weight:700;'>Kode 2FA: {current_2fa}</div>
                        <button onclick="navigator.clipboard.writeText('{current_2fa}')" style='padding:0.5rem 0.9rem;border:none;border-radius:0.45rem;background:#238636;color:#fff;cursor:pointer;'>Copy 2FA</button>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with st.form("2f"):
                ci=st.text_input("🔢 Kode 2FA", value=current_2fa, max_chars=4)
                v2,r2=st.columns(2)
                with v2: vb=st.form_submit_button("Verifikasi ✓",type="primary",use_container_width=True)
                with r2: rb=st.form_submit_button("Kirim Ulang",use_container_width=True)
            if vb:
                if ci==st.session_state.two_factor_code:
                    un=st.session_state.pending_user
                    st.session_state.logged_in=True; st.session_state.role=st.session_state.pending_role
                    st.session_state.username=un; st.session_state.user_name=st.session_state.pending_name
                    st.session_state.user_email=st.session_state.pending_email; st.session_state.user_avatar=st.session_state.pending_avatar
                    st.session_state.evaluator_name=st.session_state.pending_name
                    for k in ["pending_user","pending_email","pending_role","pending_name","pending_avatar"]:
                        if k in st.session_state: del st.session_state[k]
                    st.success("✅ Login!"); time.sleep(0.3); st.rerun()
                else: st.error("❌ Kode salah!")
            if rb:
                nc=str(random.randint(1000,9999)); st.session_state.two_factor_code=nc; st.success(f"✅ Kode: **{nc}**")
        with st.expander("ℹ️ Demo credentials"):
            st.markdown("| Role | Username | Password |\n|------|----------|----------|\n| Evaluator | `evaluator` | `eval123` |\n| Lead Evaluator | `leadevaluator` | `lead123` |\n| CB Auditor | `cbauditor` | `cb123` |\n| Developer | `developer` | `dev123` |")

# ============================================================
# SIDEBAR
# ============================================================
def render_sidebar():
    role = st.session_state.role
    name = st.session_state.get("user_name", "")
    email = st.session_state.get("user_email", "")
    avatar = st.session_state.get("user_avatar", "👤")
    notif_n = count_notifs(role)
    ndot = '<span class="ndot"></span>' if notif_n > 0 else ""
    rc = ROLE_CLS.get(role, "rb-eval")
    rl = ROLE_LABEL.get(role, "")
    scope_ids = []  # <=== INI PENTING: default empty list

    st.sidebar.markdown(
        f'<div class="sp"><div class="sp-avatar">{avatar}</div><div class="sp-name">{name}</div><div class="sp-email">{email}</div><br><span class="role-badge {rc}">{rl}</span></div>',
        unsafe_allow_html=True,
    )

    if role == "evaluator":
        st.sidebar.markdown("##### 📝 EVALUATOR")
        ev_tl = st.session_state.evaluator_timeline
        my_assignments = [eid for eid, tl in ev_tl.items() if tl.get("assignee") == st.session_state.username]
        assign_dot = '<span class="ndot"></span>' if my_assignments else ""
        has_revision = any(
            e.get("status") == "REVISION" and
            e.get("submitted_by") == st.session_state.username
            for e in st.session_state.eor_backlog
        )
        menu = {
            "🏠 Dashboard": "dashboard",
            f"📋 Kanban Board{assign_dot}": "kanban",
            "📄 Upload & Audit ST": "upload_audit",
            "📊 Hasil Audit": "audit_results",
            "📋 Generate EOR": "eor",
            "🚀 Push ke Lead Evaluator": "push",
            ("🔁 🔴 Revision Review" if has_revision else "🔁 Revision Review"): "revision_review",
            f"🔔 Notifikasi{ndot}": "notifications",
        }
        st.sidebar.markdown("##### 📁 Project")
        st.sidebar.markdown("Isi data TOE / proyek sebelum menjalankan AI audit.")
        st.session_state.project_id = st.sidebar.text_input(
            "Project ID", value=st.session_state.project_id, placeholder="Contoh: ECMT-2025-001"
        )
        st.session_state.toe_name = st.sidebar.text_input(
            "TOE Name", value=st.session_state.toe_name, placeholder="Contoh: Desktop Application SIFER Security Target"
        )
        st.session_state.toe_version = st.sidebar.text_input(
            "TOE Version", value=st.session_state.toe_version, placeholder="Contoh: v1.0.0"
        )
        st.session_state.toe_description = st.sidebar.text_area(
            "TOE Keterangan", value=st.session_state.toe_description,
            placeholder="Catatan singkat tentang TOE ini", height=100,
        )
        st.session_state.model = st.sidebar.selectbox(
            "🤖 Model", ["qwen2.5:14b", "qwen2.5:7b", "qwen:7b", "mistral-nemo"],
            index=["qwen2.5:14b", "qwen2.5:7b", "qwen:7b", "mistral-nemo"].index(st.session_state.model)
                if st.session_state.model in ["qwen2.5:14b", "qwen2.5:7b", "qwen:7b", "mistral-nemo"] else 0,
        )
        st.session_state.max_pages = st.sidebar.slider("📄 Max Pages", 30, 200, st.session_state.max_pages)
        st.session_state.eal = st.sidebar.selectbox(
            "EAL", ["1", "2", "3", "4", "5", "6", "7"],
            index=int(st.session_state.eal) - 1 if st.session_state.eal.isdigit() else 3,
        )
        st.sidebar.markdown("##### 🎯 Scope")
        int_ids = [k for k in CRITERIA if k.startswith("ASE_INT")]
        ccl_ids = [k for k in CRITERIA if k.startswith("ASE_CCL")]
        ecd_ids = [k for k in CRITERIA if k.startswith("ASE_ECD")]
        obj_ids = [k for k in CRITERIA if k.startswith("ASE_OBJ")]
        spd_ids_ = [k for k in CRITERIA if k.startswith("ASE_SPD")]
        req_ids = [k for k in CRITERIA if k.startswith("ASE_REQ")]
        tss_ids = [k for k in CRITERIA if k.startswith("ASE_TSS")]
        all_ids = int_ids + ccl_ids + ecd_ids + obj_ids + spd_ids_ + req_ids + tss_ids
        smap = {
            "Full ASE Suite (77 units)": all_ids,
            "ASE_INT (12)": int_ids,
            "ASE_CCL (21)": ccl_ids,
            "ASE_ECD (13)": ecd_ids,
            "ASE_OBJ (6)": obj_ids,
            "ASE_SPD (4)": spd_ids_,
            "ASE_REQ (18)": req_ids,
            "ASE_TSS (2)": tss_ids,
        }
        st.session_state.scope_label = st.sidebar.selectbox(
            "Scope", list(smap.keys()),
            index=list(smap.keys()).index(st.session_state.scope_label) if st.session_state.scope_label in smap else 0,
        )
        scope_ids = smap[st.session_state.scope_label]
        st.sidebar.caption(f"{len(scope_ids)} work units")
        
    elif role == "lead_evaluator":
        st.sidebar.markdown("##### 👥 LEAD EVALUATOR")
        lead_dev_resp = sum(
            1 for _eid, _units in st.session_state.dev_findings.items()
            for _uid, _f in _units.items() if _f.get("status") == "RESPONDED"
        )
        _ldot = '<span class="ndot"></span>' if lead_dev_resp > 0 else ""
        menu = {
            "🏠 Dashboard": "dashboard",
            "📋 Kanban Board": "kanban",
            "📋 EOR Workspace": "eor_workspace",
            f"🔧 Dev Responses{_ldot}": "dev_manage",
            "📅 Timeline": "timeline",
            f"🔔 Notifikasi{ndot}": "notifications",
        }
        # scope_ids tetap [] (dari default)
        
    elif role == "developer":
        st.sidebar.markdown("##### 🛠️ DEVELOPER")
        menu = {
            "🏠 Dashboard": "dashboard",
            "🔍 My Findings": "my_findings",
            f"🔔 Notifikasi{ndot}": "notifications",
        }
        # scope_ids tetap [] (dari default)
        
    else:  # cb_auditor
        st.sidebar.markdown("##### 🏛️ CB AUDITOR")
        menu = {
            "🏠 Dashboard": "dashboard",
            "📋 Kanban Board CB": "kanban",
            "📅 TM Management": "tm_management",
            "💬 Dev Responses": "dev_responses_cb",
            "📊 Project Timeline": "timeline",
            f"🔔 Notifikasi{ndot}": "notifications",
        }
        # CB Auditor tidak perlu AI Skills, Project, atau Scope
        scope_ids = []  # CB Auditor tidak perlu scope_ids

    st.sidebar.divider()
    
    # Dev/Testing Reset Panel - SEMENTARA DINONAKTIFKAN (KOMENTARI DULU)
    # with st.sidebar.expander("⚙️ Dev Tools (Reset)"):
    #     st.markdown("<small>⚠️ Prototype mode — untuk testing/development</small>", unsafe_allow_html=True)
    #     col1, col2 = st.columns(2)
    #     with col1:
    #         if st.button("🔄 Reset All EOR", use_container_width=True, help="Hapus semua EOR data (PERMANEN)"):
    #             if st.session_state.get("confirm_reset_all"):
    #                 for p in EOR_DIR.glob("*.json"):
    #                     p.unlink()
    #                 for d in UPL_DIR.iterdir():
    #                     if d.is_dir():
    #                         import shutil
    #                         shutil.rmtree(d)
    #                 st.session_state.eor_backlog = []
    #                 st.session_state.workspace_comments = {}
    #                 st.session_state.workspace_artefacts = {}
    #                 st.session_state.dev_findings = {}
    #                 st.success("✅ Semua EOR dihapus PERMANEN dari disk dan memory!")
    #                 st.session_state.pop("confirm_reset_all", None)
    #                 st.rerun()
    #             else:
    #                 st.session_state["confirm_reset_all"] = True
    #                 st.warning("⚠️ Klik lagi untuk konfirmasi HAPUS SEMUA EOR PERMANEN")
    #     with col2:
    #         if st.button("🗑️ Clear Audit", use_container_width=True, help="Hapus hasil audit"):
    #             st.session_state.audit_results = {}
    #             st.session_state.audit_results_raw = []
    #             st.session_state.audit_done = False
    #             st.success("✅ Audit data dihapus")
    #             st.rerun()

    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        logout()

    selected = st.sidebar.radio("Navigation", list(menu.keys()), key="sb_menu_radio")
    _nav = st.session_state.pop("nav_target", None)
    if _nav and _nav in list(menu.values()):
        return _nav, scope_ids
    return menu.get(selected, "dashboard"), scope_ids
# ============================================================
# RESULT CARD
# ============================================================
def render_result_card(r,idx,diagram_pages,ev_name):
    """v2.0: Override inline — form langsung terganti display, tidak muncul lagi setelah save.
    Multi-image evidence attachment per work unit."""
    fv = r.get_final_verdict()
    css = {"PASS":"v-pass","FAIL":"v-fail","INCONCLUSIVE":"v-inc"}.get(fv,"v-inc")
    if r.is_na: css="v-na"
    icon_map = {"PASS":"✅ PASS","FAIL":"❌ FAIL","INCONCLUSIVE":"⚠️ INC","N/A":"📌 N/A"}
    icon = icon_map.get(fv,"⚠️ INC")
    ec = "#3fb950" if r.evidence_valid else "#f85149"
    cc_ref = CRITERIA.get(r.id,{}).get("cc","-")
    wk = re.sub(r"[^A-Za-z0-9_]+","_",f"{r.id}_{idx}")

    # Evidence images strip
    ev_imgs = st.session_state.ev_evidence_images.get(r.id,[])
    img_html = ""
    if ev_imgs:
        thumbs = ""
        for i, img in enumerate(ev_imgs):
            data = _attachment_image_bytes(img)
            if not data:
                continue
            mime = _attachment_image_mime(img)
            thumbs += f'<img class="ev-img-thumb" src="data:{mime};base64,{base64.b64encode(data).decode()}" title="Evidence {i+1}"/>'
        img_html = f'<div class="ev-images">{thumbs}</div>'

    # Override display (applied state — no form)
    if r.is_overridden():
        st.markdown(f"""
<div class="override-applied">
  <div class="ov-label">✏️ Human Override Applied</div>
  <div class="ov-verdict">{html.escape(r.human_verdict)}</div>
  <div class="ov-comment">{html.escape(r.human_comment)}</div>
  <div class="ov-by">By {html.escape(r.human_reviewer)} · {r.review_ts[:16]}</div>
</div>""", unsafe_allow_html=True)
        return  # stop here — form not shown again

    # Normal card
    rv_html = '<div class="flag-review">⚑ Human Review Required (conf &lt;85%)</div>' if r.needs_review else ""
    st.markdown(f"""
<div class="{css}">
  <span style="font-size:.72em;color:#8b949e;">{html.escape(cc_ref)}</span>
  <b style="margin-left:.5rem;">{html.escape(r.id)}</b> — {html.escape(r.label[:90])}<br>
  <b>{icon}</b> <span style="font-size:.8em;color:#8b949e;">conf:{int(r.confidence)}%</span>
  {rv_html}
  <div class="ev-box">{html.escape(r.evidence[:380])}</div>
  {img_html}
  <div style="font-size:.76em;margin-top:4px;color:#8b949e;">{html.escape(r.reasoning[:300])}</div>
  <div style="font-size:.7em;color:{ec};">{html.escape(r.validation_note or "")}</div>
</div>""", unsafe_allow_html=True)

    # Attach evidence images
    with st.expander(f"📎 Attach Evidence Images — {r.id}", expanded=False):
        uploaded_imgs = st.file_uploader(
            "Upload gambar bukti (screenshot ST, diagram, dll)",
            type=["png","jpg","jpeg"],
            accept_multiple_files=True,
            key=f"ev_img_{wk}"
        )
        if uploaded_imgs:
            if st.button(f"💾 Simpan Gambar ({len(uploaded_imgs)})", key=f"save_img_{wk}"):
                existing = st.session_state.ev_evidence_images.get(r.id,[])
                for uf in uploaded_imgs:
                    data = uf.getvalue()
                    existing.append({
                        "name": uf.name,
                        "type": uf.type or "image/png",
                        "size": len(data),
                        "bytes": data,
                    })
                st.session_state.ev_evidence_images[r.id] = existing
                st.success(f"{len(uploaded_imgs)} gambar ditambahkan!"); st.rerun()

    # Human override — only show form if NOT yet overridden
    if r.needs_review or fv in ("FAIL","INCONCLUSIVE"):
        with st.expander(f"✏️ Override Verdict — {r.id}", expanded=r.needs_review):
            c1,c2 = st.columns([1,2])
            with c1:
                ov_sel = st.selectbox("Override",["PASS","FAIL","INCONCLUSIVE"],key=f"ov_{wk}")
            with c2:
                ov_cmt = st.text_input("Justification / Comment",key=f"ovc_{wk}",
                    placeholder="Alasan override — cite halaman ST")
            if st.button(f"✅ Apply Override",key=f"sov_{wk}",type="primary"):
                r.human_verdict = ov_sel
                r.human_comment = ov_cmt
                r.human_reviewer = ev_name or st.session_state.get("user_name","Evaluator")
                r.review_ts = datetime.now().isoformat()
                r.needs_review = False
                r.override_history.append({"old":fv,"new":ov_sel,"comment":ov_cmt,
                    "reviewer":r.human_reviewer,"ts":r.review_ts})
                add_notification(f"Override {r.id}",
                    f"mengoverride verdict {r.id}: {fv} → {ov_sel}",
                    "lead_evaluator",
                    sender=r.human_reviewer,
                    obj=f"Work unit {r.id}",
                    keterangan=ov_cmt[:60],
                    icon="✏️")
                st.success(f"✅ Override saved: {fv} → {ov_sel}"); st.rerun()
# ============================================================
# PAGES
# ============================================================
def page_dashboard():
    role=st.session_state.role
    dark=st.session_state.dark_mode
    role_titles={"evaluator":("📝","Evaluator Dashboard","Upload ST → AI Audit → EOR → Kanban"),
                 "lead_evaluator":("👥","Lead Evaluator Dashboard","EOR Workspace | Dev Management | Timeline"),
                 "developer":("🛠️","Developer Dashboard","My Assigned Findings | Respond | Track"),
                 "cb_auditor":("🏛️","CB Auditor Dashboard","Kanban | Timeline | Technical Meeting")}
    icon,title,sub=role_titles.get(role,("🏠","Dashboard",""))
    pg_header(icon,title,sub)

    results=st.session_state.audit_results_raw
    n_p=sum(1 for r in results if r.get_final_verdict()=="PASS" and not r.is_na) if results else 0
    n_f=sum(1 for r in results if r.get_final_verdict()=="FAIL") if results else 0
    n_i=sum(1 for r in results if r.get_final_verdict()=="INCONCLUSIVE") if results else 0
    n_na=sum(1 for r in results if r.is_na) if results else 0
    total_eor=len(st.session_state.eor_backlog)
    pend=len([e for e in st.session_state.eor_backlog if e.get("status") in ("SUBMITTED","IN_AUDIT","UNDER_REVIEW")])
    appr=len([e for e in st.session_state.eor_backlog if e.get("status")=="APPROVED"])

    st.markdown(f"""
<div class="metric-grid">
  {metric_html(n_p,"✅ PASS","#3fb950")}
  {metric_html(n_f,"❌ FAIL","#f85149")}
  {metric_html(n_i,"⚠️ INC","#d29922")}
  {metric_html(n_na,"📌 N/A","#6e7681")}
  {metric_html(total_eor,"📋 Total EOR","#58a6ff")}
  {metric_html(pend,"⏳ Active","#d29922")}
  {metric_html(appr,"✅ Approved","#3fb950")}
  {metric_html(count_notifs(role),"🔔 Notif","#d2a8ff")}
</div>""",unsafe_allow_html=True)

    c1,c2=st.columns([1.4,1])
    with c1:
        st.markdown("### 📊 Audit Distribution")
        if results: st.plotly_chart(make_donut(n_p,n_f,n_i,n_na,dark),use_container_width=True,config={"displayModeBar":False})
        else: st.info("Belum ada hasil audit.")
    with c2:
        st.markdown("### 🔔 Notifikasi Terbaru")
        my=[n for n in st.session_state.notifications if n.get("target_role")==role]
        if my:
            for n in reversed(my[-4:]):
                n["read"]=True
                icon = n.get("icon","🔔")
                spok_line = n.get("spok","") or n.get("message","")
                ts = n.get("created_at","")[:16].replace("T"," ")
                st.markdown(f"""
<div class="notif-card">
  <div class="notif-icon">{icon}</div>
  <div class="notif-body">
    <div class="notif-subject">{html.escape(n.get("title",""))}</div>
    <div class="notif-spok" style="font-size:.75rem;color:#8b949e;">{html.escape(spok_line[:120])}</div>
    <div class="notif-ts">🕐 {ts}</div>
  </div>
</div>""", unsafe_allow_html=True)
        else: st.info("Tidak ada notifikasi.")

        # ============================================================
        # SHOW REVISION ALERT FOR EVALUATOR
        # ============================================================
        if role == "evaluator":
            rev_eors = [e for e in st.session_state.eor_backlog
                        if e.get("status")=="REVISION"
                        and e.get("submitted_by")==st.session_state.username]
            if rev_eors:
                for rev_e in rev_eors:
                    lead_note = rev_e.get("lead_note","")
                    revised_by = rev_e.get("revised_by","Lead Evaluator")
                    resubmit_count = rev_e.get("resubmit_count", 0)
                    resubmit_info = f"🔄 Re-submit #{resubmit_count}" if resubmit_count > 0 else ""
                    
                    st.markdown(f"""
<div style="background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.3);
  border-radius:12px;padding:.9rem 1.1rem;margin:.5rem 0;cursor:pointer;">
  <div style="font-size:.78rem;font-weight:800;color:#f85149;margin-bottom:.3rem;">
    🔁 EOR Anda Dikembalikan untuk Revisi {resubmit_info}</div>
  <div style="font-size:.82rem;color:var(--text);margin-bottom:.4rem;">
    <b>{html.escape(rev_e.get("id",""))}</b> — {html.escape(rev_e.get("toe_name",""))} {html.escape(rev_e.get("eal",""))}</div>
  <div style="font-size:.78rem;color:#8b949e;margin-bottom:.6rem;">
    Lead: <i>"{html.escape(lead_note[:80])}{("..." if len(lead_note)>80 else "")}"</i></div>
</div>""", unsafe_allow_html=True)
                    if st.button(
                        "📋 Buka Revision Review →",
                        key=f"dash_rev_{rev_e.get('id','')}",
                        type="primary"
                    ):
                        st.session_state["active_revision_eor"] = rev_e.get("id","")
                        st.session_state["revision_mode"] = True
                        st.session_state["nav_target"] = "revision_review"
                        st.rerun()

        # ============================================================
        # SHOW RE-SUBMIT ALERTS FOR LEAD EVALUATOR (TAMBAHKAN INI)
        # ============================================================
        if role == "lead_evaluator":
            resubmit_eors = [
                e for e in st.session_state.eor_backlog 
                if e.get("resubmit_count", 0) > 0 
                and e.get("status") in ("SUBMITTED", "UNDER_REVIEW")
            ]
            if resubmit_eors:
                st.markdown("### 🔄 Perhatian: EOR Hasil Re-submit")
                for rev_e in resubmit_eors:
                    st.markdown(f"""
<div style="background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);
  border-radius:12px;padding:.9rem 1.1rem;margin:.5rem 0;">
  <div style="font-size:.78rem;font-weight:800;color:#d29922;margin-bottom:.3rem;">
    🔄 EOR Hasil Re-submit #{rev_e.get('resubmit_count',0)}</div>
  <div style="font-size:.82rem;color:var(--text);margin-bottom:.4rem;">
    <b>{html.escape(rev_e.get('id',''))}</b> — {html.escape(rev_e.get('toe_name',''))}</div>
  <div style="font-size:.78rem;color:#8b949e;margin-bottom:.6rem;">
    Catatan Evaluator: <i>"{html.escape(rev_e.get('resubmit_note', '')[:100])}"</i></div>
</div>""", unsafe_allow_html=True)

        # ============================================================
        # SHOW EVALUATOR ASSIGNMENTS FROM TIMELINE
        # ============================================================
        if role == "evaluator":
            ev_tl = st.session_state.evaluator_timeline
            my_ass = [(eid,tl) for eid,tl in ev_tl.items() if tl.get("assignee")==st.session_state.username]
            if my_ass:
                st.markdown("### 📅 Penugasan Saya")
                for eid,tl in my_ass:
                    end_d = tl.get("end","")
                    d_val = days_until(end_d) if end_d else 99
                    dc,_ = sla_color(d_val)
                    st.markdown(f"""
<div class="tl-assign-row">
  <div>📋 <b>{html.escape(eid)}</b></div>
  <div style="color:{dc};font-size:.8rem;">📅 Deadline: {end_d} ({d_val}d)</div>
  <div style="font-size:.75rem;color:#8b949e;">{html.escape(tl.get("note",""))}</div>
</div>""", unsafe_allow_html=True)

def page_upload_audit(scope_ids):
    pg_header("📄","Upload & Audit ST","Real Ollama Audit | Junior RCC Skills | "+st.session_state.scope_label)
    active=[s for s,k in [("🎯 CoT","enable_cot"),("🔍 NegSpace","enable_negative_space"),("🛡️ SemGuard","enable_sem_guard"),("📊 ConfCalib","enable_confidence_calib")] if st.session_state.get(k,True)]
    if active: st.markdown("**Active Skills:** "+" ".join(f'<span class="skill-badge">{s}</span>' for s in active),unsafe_allow_html=True)
    c1,c2=st.columns([1,1])
    with c1:
        pdf_file=st.file_uploader("Upload ST PDF",type=["pdf"],key="pdf_up")
        if pdf_file:
            st.success(f"✅ **{pdf_file.name}** | TOE: `{st.session_state.toe_name or '(isi sidebar)'}` | Model: `{st.session_state.model}`")
            if not st.session_state.toe_name: st.warning("⚠️ Isi TOE Name di sidebar.")
            elif st.button("▶ RUN AI AUDIT",type="primary",use_container_width=True):
                st.session_state.few_shot_db={}; st.session_state.audit_done=False
                with st.spinner("🔍 Extracting..."):
                    ext=extract_st(pdf_file,st.session_state.max_pages)
                    st_text=ext["text"]; dp=ext["diagram_pages"]
                    meta=analyze_st_metadata(st_text)
                    meta.update({
                        "project_id":st.session_state.project_id,
                        "toe_name":st.session_state.toe_name,
                        "toe_version":st.session_state.toe_version,
                        "toe_description":st.session_state.toe_description,
                        "eal":st.session_state.eal,
                        "total_pages":ext.get("total_pages",len(ext.get("pages",[]))),
                        "diagram_pages":ext.get("visual_pages",list(dp.keys()))
                    })
                    st.session_state.diagram_pages=dp; st.session_state.st_meta=meta
                c1b,c2b,c3b,c4b=st.columns(4)
                c1b.metric("Pages",ext.get("total_pages",len(ext["pages"]))); c2b.metric("Diagrams",len(ext.get("visual_pages",list(dp.keys()))))
                c3b.metric("Has PP","Yes" if meta["has_pp"] else "No"); c4b.metric("Has _EXT","Yes" if meta["has_ext"] else "No")
                if meta["spd_ids"]: st.info("SPD: "+", ".join(meta["spd_ids"][:15]))
                prog=st.progress(0,"Starting...")
                def cb(i,total,uid): prog.progress((i+1)/total,f"[{i+1}/{total}] {uid}")
                results=run_audit(st.session_state.model,st_text,meta,scope_ids,
                    st.session_state.few_shot_db,cb,
                    skill_level=st.session_state.skill_level,cot=st.session_state.enable_cot,
                    neg=st.session_state.enable_negative_space,sem=st.session_state.enable_sem_guard,
                    calib=st.session_state.enable_confidence_calib)
                st.session_state.audit_results_raw=results; st.session_state.audit_done=True
                # ── INLINE VALIDATION (validation.py formula) ────────────────────
                _val = run_inline_validation(
                    results=results,
                    model=st.session_state.model,
                    toe_name=st.session_state.toe_name,
                    scope_ids=scope_ids
                )
                st.session_state["last_validation"] = _val
                # ─────────────────────────────────────────────────────────────────
                prog.progress(1.0,"✅ Selesai!")
                n_p=sum(1 for r in results if r.get_final_verdict()=="PASS" and not r.is_na)
                n_f=sum(1 for r in results if r.get_final_verdict()=="FAIL")
                n_i=sum(1 for r in results if r.get_final_verdict()=="INCONCLUSIVE")
                n_na=sum(1 for r in results if r.is_na)
                st.session_state.audit_results={"toe_name":st.session_state.toe_name,"toe_version":st.session_state.toe_version,"eal":f"EAL{st.session_state.eal}","timestamp":datetime.now().isoformat(),"total_units":len(results),"pass":n_p,"fail":n_f,"inc":n_i,"na":n_na,"findings":[{"id":r.id,"title":r.label,"verdict":r.get_final_verdict(),"confidence":r.confidence,"evidence":r.evidence[:120]} for r in results if r.get_final_verdict() in ("FAIL","INCONCLUSIVE")]}
                st.rerun()
        else: st.info("📁 Upload ST PDF.")
    with c2:
        if st.session_state.audit_done and st.session_state.audit_results:
            res=st.session_state.audit_results
            st.subheader("📊 Ringkasan Audit")
            st.plotly_chart(make_donut(res.get("pass",0),res.get("fail",0),res.get("inc",0),res.get("na",0),st.session_state.toe_name),use_container_width=True,config={"displayModeBar":False})
            st.metric("Total Work Units",res.get("total_units",0))
            n_rev=sum(1 for r in st.session_state.audit_results_raw if r.needs_review and not r.is_overridden())
            if n_rev>0: st.warning(f"⚑ {n_rev} perlu human review")
            # ── VALIDATION RESULT PANEL ──────────────────────────────────
            val = st.session_state.get("last_validation",{})
            if val:
                st.divider()
                st.subheader("🔬 Validation Score")
                render_validation_result(val)
            # ─────────────────────────────────────────────────────────────
            st.divider()
            st.markdown("**Top Findings:**")
            for f in res.get("findings",[])[:5]:
                st.markdown(f"{'❌' if f['verdict']=='FAIL' else '⚠️'} `{f['id']}` — {f['title'][:55]}")

def render_evaluator_action_panel(eor_id: str, uid: str):
    """Evaluator fills Evaluator Action after Dev responds.
    Append-only. Sets STATUS: FIXED or REISSUE."""
    dev_findings = st.session_state.dev_findings
    finding = dev_findings.get(eor_id,{}).get(uid,{})
    if not finding: return
    fstatus = finding.get("status","OPEN")
    if fstatus not in ("RESPONDED","IN_PROGRESS"): return

    thread = finding.get("resolution_thread",[])
    dev_responses = [e for e in thread if e.get("type")=="dev_action"]
    if not dev_responses: return

    eor_obj = next((e for e in st.session_state.eor_backlog if e.get("id")==eor_id), {})

    with st.expander(f"👨‍💻 Evaluator Action — {uid} (Dev sudah respond)", expanded=True):
        st.markdown("""<div style="background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.2);
          border-radius:8px;padding:.6rem .9rem;margin-bottom:.7rem;font-size:.8rem;color:#58a6ff;">
          ℹ️ <b>Append-only</b> — Evaluator Action ditambahkan ke thread, tidak bisa diubah.</div>""",
          unsafe_allow_html=True)

        # Show last dev action
        last_dev = dev_responses[-1]
        st.markdown(f"""
<div style="background:rgba(255,166,87,.06);border-left:3px solid #ffa657;
  border-radius:0 8px 8px 0;padding:.65rem .85rem;margin-bottom:.75rem;">
  <div style="font-size:.7rem;color:#8b949e;font-family:var(--mono);">
    {last_dev.get('date','')} — 🛠️ Sponsor/Developer Action</div>
  <div style="font-size:.82rem;color:var(--text);">{html.escape(last_dev.get('text',''))}</div>
  {''.join(f'<span class="artefact-pill">📎 {html.escape(a.get("name",""))}</span>' for a in last_dev.get("attachments",[]))}
</div>""", unsafe_allow_html=True)

        ev_text = st.text_area("Evaluator Action",height=100,key=f"ev_act_{eor_id}_{uid}",
            placeholder=f"[{datetime.now().strftime('%d%m%Y')}] Hasil review atas perubahan "
                        "yang dibuat oleh sponsor/developer...")

        c1,c2 = st.columns(2)
        with c1:
            if st.button(f"✅ FIXED — EOR Resolved",key=f"fixed_{eor_id}_{uid}",
                type="primary",use_container_width=True):
                if not ev_text.strip():
                    st.warning("Isi Evaluator Action terlebih dahulu.")
                else:
                    entry = {"type":"evaluator_action",
                        "date":datetime.now().strftime("%d%m%Y"),
                        "datetime":datetime.now().isoformat(),
                        "text":ev_text.strip(),
                        "author":st.session_state.get("user_name","Evaluator"),
                        "status":"FIXED","attachments":[]}
                    finding["resolution_thread"].append(entry)
                    finding["status"] = "FIXED"
                    for obs in eor_obj.get("observations",[]):
                        if obs.get("id")==uid:
                            obs["resolution_thread"] = finding["resolution_thread"]
                            obs["status"] = "FIXED"
                    save_eor(eor_obj)
                    simulated_email(to="dev@vendor.co.id",
                        subject=f"[CC-AI] FIXED — {uid} | EOR {eor_id}",
                        body=f"Finding {uid} telah dinyatakan FIXED (EOR Resolved).\n\n"
                             f"Evaluator Action:\n{ev_text.strip()}")
                    add_notification(f"✅ FIXED: {uid}","menyatakan finding FIXED (EOR Resolved)",
                        target="developer",sender=st.session_state.get("user_name","Evaluator"),
                        obj=f"EOR {eor_id} — {uid}",keterangan=ev_text[:60],icon="✅")
                    add_notification(f"✅ FIXED: {uid}","menyatakan finding FIXED",
                        target="lead_evaluator",sender=st.session_state.get("user_name","Evaluator"),
                        obj=f"EOR {eor_id} — {uid}",icon="✅")
                    st.success(f"✅ {uid} FIXED — EOR Resolved!"); st.rerun()

        with c2:
            if st.button(f"🔁 REISSUE — EOR Not Resolve",key=f"reissue_{eor_id}_{uid}",
                use_container_width=True):
                if not ev_text.strip():
                    st.warning("Isi Evaluator Action terlebih dahulu.")
                else:
                    entry = {"type":"evaluator_action",
                        "date":datetime.now().strftime("%d%m%Y"),
                        "datetime":datetime.now().isoformat(),
                        "text":ev_text.strip(),
                        "author":st.session_state.get("user_name","Evaluator"),
                        "status":"REISSUE","attachments":[]}
                    finding["resolution_thread"].append(entry)
                    finding["status"] = "REISSUE"
                    for obs in eor_obj.get("observations",[]):
                        if obs.get("id")==uid:
                            obs["resolution_thread"] = finding["resolution_thread"]
                            obs["status"] = "REISSUE"
                    save_eor(eor_obj)
                    simulated_email(to="dev@vendor.co.id",
                        subject=f"[CC-AI] REISSUE — {uid} | EOR {eor_id}",
                        body=f"Finding {uid} REISSUE (EOR Not Resolve). Harap perbaiki lagi.\n\n"
                             f"Evaluator Action:\n{ev_text.strip()}")
                    add_notification(f"🔁 REISSUE: {uid}","menyatakan finding REISSUE — harap perbaiki",
                        target="developer",sender=st.session_state.get("user_name","Evaluator"),
                        obj=f"EOR {eor_id} — {uid}",keterangan=ev_text[:60],icon="🔁")
                    st.warning(f"🔁 {uid} REISSUE — Dev harus respond lagi."); st.rerun()


def page_audit_results():
    pg_header("📊","Hasil Audit Detail","Per-family | Human Override | Evidence Images | Flow: Audit → EOR → Push to Lead")
    if not st.session_state.audit_done or not st.session_state.audit_results_raw:
        st.info("Belum ada audit. Pergi ke Upload & Audit ST."); return

    # Flow banner v2.0
    st.markdown("""
<div style="background:rgba(88,166,255,.07);border:1px solid rgba(88,166,255,.15);
  border-radius:10px;padding:.75rem 1.1rem;margin-bottom:1rem;font-size:.82rem;color:#8b949e;">
  <b style="color:#58a6ff;">Flow:</b>
  Upload ST → AI Audit (LLM) → <b>Hasil Audit (halaman ini)</b> → Human Override + Attach Evidence →
  Generate EOR → <b>Push ke Lead Evaluator</b>
</div>""", unsafe_allow_html=True)

    results=st.session_state.audit_results_raw; dp=st.session_state.diagram_pages; ev=st.session_state.evaluator_name
    n_p=sum(1 for r in results if r.get_final_verdict()=="PASS" and not r.is_na)
    n_f=sum(1 for r in results if r.get_final_verdict()=="FAIL")
    n_i=sum(1 for r in results if r.get_final_verdict()=="INCONCLUSIVE")
    n_na=sum(1 for r in results if r.is_na)
    n_r=sum(1 for r in results if r.needs_review and not r.is_overridden())
    n_ov=sum(1 for r in results if r.is_overridden())
    st.markdown(f'<div class="metric-grid">{metric_html(n_p,"✅ PASS","#3fb950")}{metric_html(n_f,"❌ FAIL","#f85149")}{metric_html(n_i,"⚠️ INC","#d29922")}{metric_html(n_na,"📌 N/A","#6e7681")}{metric_html(n_r,"⚑ Review","#58a6ff")}{metric_html(n_ov,"✏️ Override","#d2a8ff")}</div>',unsafe_allow_html=True)
    tab_all,tab_fail,tab_ev_action,tab_exp=st.tabs([
        "📋 All","❌ FAIL / ⚠️ INC",
        "👨‍💻 Evaluator Action (Dev Responded)","📄 Export"])
    with tab_all:
        for fam in ["ASE_INT","ASE_CCL","ASE_ECD","ASE_OBJ","ASE_SPD","ASE_REQ","ASE_TSS"]:
            fr=[r for r in results if r.id.startswith(fam)]
            if not fr: continue
            fp=sum(1 for r in fr if r.get_final_verdict()=="PASS"); ff=sum(1 for r in fr if r.get_final_verdict()=="FAIL"); fi=sum(1 for r in fr if r.get_final_verdict()=="INCONCLUSIVE")
            with st.expander(f"**{fam}** — {fp}✅ {ff}❌ {fi}⚠️ / {len(fr)}",expanded=(fam=="ASE_INT")):
                for idx,r in enumerate(fr): render_result_card(r,idx,dp,ev)
    with tab_fail:
        fl=[r for r in results if r.get_final_verdict()=="FAIL"]; il=[r for r in results if r.get_final_verdict()=="INCONCLUSIVE"]
        if not fl and not il: st.success("🎉 Tidak ada FAIL/INCONCLUSIVE!")
        for idx,r in enumerate(fl+il): render_result_card(r,1000+idx,dp,ev)
    with tab_ev_action:
        st.markdown("### 👨‍💻 Evaluator Action — Review Dev Responses")
        st.info("Setelah Developer submit Sponsor/Developer Action, Evaluator mengisi "
                "Evaluator Action dan menetapkan STATUS: FIXED atau REISSUE.")
        dev_findings = st.session_state.dev_findings
        responded_items = []
        for eor_id, units in dev_findings.items():
            for uid, f in units.items():
                if f.get("status") in ("RESPONDED","IN_PROGRESS"):
                    has_dev_resp = any(e.get("type")=="dev_action"
                                       for e in f.get("resolution_thread",[]))
                    if has_dev_resp:
                        responded_items.append((eor_id, uid, f))
        if not responded_items:
            st.info("📭 Belum ada Dev response yang perlu di-review. "
                    "Tunggu Developer submit Sponsor/Developer Action.")
        else:
            st.markdown(f"**{len(responded_items)} finding** menunggu Evaluator Action:")
            for eor_id, uid, f in responded_items:
                pri = f.get("priority","MAJOR")
                pri_c = {"MAJOR":"#f85149","MINOR":"#d29922","INFO":"#58a6ff"}.get(pri,"#8b949e")
                st.markdown(f"""
<div style="background:var(--bg2);border:1px solid var(--border);
  border-left:3px solid {pri_c};border-radius:0 10px 10px 0;
  padding:.75rem 1rem;margin-bottom:.4rem;">
  <b style="font-family:var(--mono);color:var(--accent);">{html.escape(uid)}</b>
  <span class="sb sb-resp" style="margin-left:.4rem;">Dev RESPONDED</span>
  <span style="background:{pri_c}20;color:{pri_c};font-size:.68rem;font-weight:700;
    padding:2px 7px;border-radius:10px;margin-left:.3rem;">{html.escape(pri)}</span>
  <div style="font-size:.75rem;color:#8b949e;margin-top:.25rem;">
    EOR: {html.escape(eor_id)}</div>
</div>""", unsafe_allow_html=True)
                render_evaluator_action_panel(eor_id, uid)
                st.divider()

    with tab_exp:
        c1,c2=st.columns(2)
        with c1:
            if st.button("Generate Workbook PDF"):
                if REPORTLAB_OK:
                    buf=generate_workbook_pdf(results,st.session_state.st_meta,st.session_state.evaluator_name,st.session_state.user_name,st.session_state.eal,st.session_state.toe_name,st.session_state.toe_version,st.session_state.project_id,st.session_state.skill_level)
                    if buf: st.download_button("⬇️ Workbook PDF",data=buf,file_name=f"Workbook_{datetime.now().strftime('%Y%m%d')}.pdf",mime="application/pdf")
        with c2:
            fl2=[r for r in results if r.get_final_verdict()=="FAIL"]; il2=[r for r in results if r.get_final_verdict()=="INCONCLUSIVE"]
            if st.button("Generate EOR PDF"):
                if REPORTLAB_OK:
                    buf=generate_eor_pdf(fl2,il2,st.session_state.st_meta,st.session_state.evaluator_name,st.session_state.user_name,st.session_state.project_id)
                    if buf: st.download_button("⬇️ EOR PDF",data=buf,file_name=f"EOR_{datetime.now().strftime('%Y%m%d')}.pdf",mime="application/pdf")
        exp_data=[{"id":r.id,"verdict":r.verdict,"final":r.get_final_verdict(),"confidence":r.confidence,"evidence":r.evidence,"reasoning":r.reasoning,"is_na":r.is_na,"override":r.human_verdict} for r in results]
        st.download_button("⬇️ JSON Backlog",data=json.dumps(exp_data,indent=2,ensure_ascii=False),file_name=f"Backlog_{datetime.now().strftime('%Y%m%d_%H%M')}.json",mime="application/json")

def page_generate_eor():
    """Generate Workbook ASE dan EOR dalam format resmi:
    - Workbook: FR.MT.04.WB (landscape, 77 WU, justifikasi per WU)
    - EOR: FR.MT.04.11 (cover + EOR Identification + Observation Table)
    """
    pg_header("📋","Generate Workbook & EOR",
        "Format Resmi FR.MT.04.WB + FR.MT.04.11 | Download langsung")

    if not st.session_state.audit_done or not st.session_state.audit_results_raw:
        st.info("⚠️ Belum ada hasil audit. Jalankan Upload & Audit ST terlebih dahulu.")
        return

    res     = st.session_state.audit_results
    results = st.session_state.audit_results_raw
    ev_name = st.session_state.evaluator_name or st.session_state.user_name or "—"
    lead_name = st.session_state.lead_evaluator_name or "—"
    toe     = res.get("toe_name","—")
    ver     = res.get("toe_version","")
    eal     = res.get("eal","EAL4+")
    pid     = st.session_state.project_id or ""

    # Summary metrics
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("✅ PASS",  res.get("pass",0))
    c2.metric("❌ FAIL",  res.get("fail",0))
    c3.metric("⚠️ INC",   res.get("inc",0))
    c4.metric("📌 N/A",   res.get("na",0))

    # Find matching EOR from backlog
    eor_obj = next((e for e in st.session_state.eor_backlog
                    if e.get("toe_name")==toe and
                    e.get("submitted_by")==st.session_state.username), None)

    st.divider()
    tab_wb, tab_eor = st.tabs(["📄 Workbook ASE (FR.MT.04.WB)", "🔴 EOR (FR.MT.04.11)"])

    # ── TAB 1: WORKBOOK ──────────────────────────────────────────────────
    with tab_wb:
        st.markdown("""
<div style="background:rgba(88,166,255,.07);border:1px solid rgba(88,166,255,.2);
  border-radius:10px;padding:.9rem 1.1rem;margin-bottom:1rem;">
  <b style="color:#58a6ff;">📄 Workbook ASE — FR.MT.04.WB</b><br>
  <span style="font-size:.83rem;color:#8b949e;">
  Format landscape A4 · 8 kolom · Semua 77 work unit ASE ·
  Justifikasi per WU dari hasil AI Audit · Colour-coded verdict
  </span>
</div>""", unsafe_allow_html=True)

        # Preview table of results
        preview_rows = []
        for r_obj in results[:10]:
            fv = r_obj.get_final_verdict()
            if r_obj.is_overridden(): fv = r_obj.human_verdict
            conf = getattr(r_obj,"confidence",0) or 0
            preview_rows.append({
                "Work Unit": r_obj.id,
                "Verdict": fv,
                "Confidence": f"{int(conf)}%",
                "N/A": "✓" if r_obj.is_na else "",
                "Override": "✓" if r_obj.is_overridden() else "",
            })
        if preview_rows:
            st.markdown(f"**Preview 10 work unit pertama** (dari {len(results)} total):")
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True,
                         hide_index=True, height=280)

        if REPORTLAB_OK:
            if st.button("📥 Generate & Download Workbook ASE PDF",
                         key="dl_wb", type="primary", use_container_width=True):
                with st.spinner("Generating Workbook ASE PDF..."):
                    buf_wb = generate_workbook_pdf(
                        results=results,
                        meta=st.session_state.st_meta,
                        ev_name=ev_name,
                        lead_name=lead_name,
                        eal=eal, toe=toe, version=ver, pid=pid,
                        skill_level=st.session_state.skill_level
                    )
                if buf_wb:
                    fname_wb = f"Workbook_ASE_{toe.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                    st.download_button(
                        "⬇️ Download Workbook PDF",
                        data=buf_wb,
                        file_name=fname_wb,
                        mime="application/pdf",
                        use_container_width=True
                    )
                    st.success(f"✅ Workbook siap: {fname_wb}")
                    st.info("📌 Format: FR.MT.04.WB | Landscape A4 | 77 Work Unit ASE")
                else:
                    st.error("Gagal generate PDF.")
        else:
            st.error("reportlab tidak terinstall. Run: `pip install reportlab`")

    # ── TAB 2: EOR ───────────────────────────────────────────────────────
    with tab_eor:
        st.markdown("""
<div style="background:rgba(248,81,73,.07);border:1px solid rgba(248,81,73,.2);
  border-radius:10px;padding:.9rem 1.1rem;margin-bottom:1rem;">
  <b style="color:#f85149;">🔴 EOR — FR.MT.04.11</b><br>
  <span style="font-size:.83rem;color:#8b949e;">
  Format portrait A4 · Cover BSSN · EOR Identification · Signature Block ·
  Observation Table (CC Component | Eval Ref | Issue Description | Resolution | Status)
  </span>
</div>""", unsafe_allow_html=True)

        # EOR source selection
        eor_source = st.radio(
            "Sumber data EOR:",
            ["Dari hasil AI Audit (FAIL/INCONCLUSIVE)",
             "Dari EOR yang sudah di-push ke Lead (dengan Issue Description CB)"],
            key="eor_source_sel"
        )

        # Build observations list
        if eor_source.startswith("Dari hasil AI Audit") or not eor_obj:
            # Build from audit results
            fail_inc = [r for r in results
                        if r.get_final_verdict() in ("FAIL","INCONCLUSIVE") and not r.is_na]
            eor_for_pdf = {
                "id": f"EOR-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "toe_name": toe, "toe_version": ver, "eal": eal,
                "cycle_note": f"AI Audit — {len(fail_inc)} temuan FAIL/INC",
                "observations": [
                    {
                        "no": i+1,
                        "cc_component": r.id,
                        "eval_reference": f"CEM:2022 R1 {r.id}",
                        "issue_description": (
                            f"AI Verdict: {r.get_final_verdict()} (conf:{int(r.confidence or 0)}%) — "
                            f"{r.evidence[:150] if r.evidence else 'Lihat workbook untuk detail evidence.'}"
                        ),
                        "resolution_thread": [],
                        "status": "OPEN",
                    }
                    for i, r in enumerate(fail_inc)
                ],
            }
            n_obs = len(fail_inc)
            if n_obs == 0:
                st.success("🎉 Tidak ada temuan FAIL/INC — EOR kosong (clean audit).")
                eor_for_pdf["observations"] = []
            else:
                st.markdown(f"**{n_obs} temuan** akan dimasukkan ke EOR:")
                prev_data = [{"No":i+1,"Work Unit":r.id,
                              "Verdict":r.get_final_verdict(),
                              "Confidence":f"{int(r.confidence or 0)}%"}
                             for i,r in enumerate(fail_inc)]
                st.dataframe(pd.DataFrame(prev_data), use_container_width=True,
                             hide_index=True, height=200)
        else:
            eor_for_pdf = eor_obj
            n_obs = len([o for o in eor_obj.get("observations",[])
                         if o.get("issue_description","").strip()])
            if n_obs > 0:
                st.info(f"📋 EOR dari backlog: {eor_obj.get('id','?')} — {n_obs} observations")
            else:
                st.warning("EOR backlog belum memiliki Issue Description dari CB Auditor. "
                           "Gunakan template kosong.")

        # Additional info fields
        with st.expander("⚙️ Isi Detail EOR (opsional)", expanded=False):
            eor_for_pdf["project_id"] = st.text_input(
                "Project ID", value=pid or "KPTI/2026", key="eor_projid")
            eor_for_pdf["toe_name"] = st.text_input(
                "Nama TOE", value=toe, key="eor_toe")
            eor_for_pdf["toe_version"] = st.text_input(
                "Versi TOE", value=ver, key="eor_ver")
            lead_name_input = st.text_input(
                "Lead Evaluator", value=lead_name, key="eor_lead")

        if REPORTLAB_OK:
            if st.button("📥 Generate & Download EOR PDF",
                         key="dl_eor", type="primary", use_container_width=True):
                with st.spinner("Generating EOR FR.MT.04.11 PDF..."):
                    buf_eor = generate_eor_pdf(
                        eor=eor_for_pdf,
                        ev_name=ev_name,
                        lead_name=lead_name
                    )
                if buf_eor:
                    fname_eor = (f"EOR_{eor_for_pdf.get('id','ASE')}_"
                                 f"{toe.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf")
                    st.download_button(
                        "⬇️ Download EOR PDF (FR.MT.04.11)",
                        data=buf_eor,
                        file_name=fname_eor,
                        mime="application/pdf",
                        use_container_width=True
                    )
                    st.success(f"✅ EOR siap: {fname_eor}")
                    st.info("📌 Format: FR.MT.04.11 | Portrait A4 | Cover + Identification + Observation Table")
                else:
                    st.error("Gagal generate EOR PDF.")
        else:
            st.error("reportlab tidak terinstall. Run: `pip install reportlab`")


def page_revision_review():
    """Evaluator Revision Review Page - dengan re-submit counter dan note"""
    
    # IMPORTANT: Set flag bahwa kita sedang di halaman ini
    st.session_state["current_page"] = "revision_review"
    st.session_state["in_revision_review"] = True
    
    pg_header("🔁","Revision Review","Baca komentar Lead → Acknowledge → Re-Submit ke Lead")
    
    # Cari EOR revision
    my_revision_eors = [
        e for e in st.session_state.eor_backlog
        if e.get("status") == "REVISION"
        and e.get("submitted_by") == st.session_state.username
    ]

    if not my_revision_eors:
        st.info("Tidak ada EOR revision saat ini.")
        if st.button("← Kembali ke Kanban"):
            st.session_state.pop("in_revision_review", None)
            st.session_state.pop("current_page", None)
            st.session_state.pop("revision_mode", None)
            st.session_state.pop("active_revision_eor", None)
            st.session_state["nav_target"] = "kanban"
            st.rerun()
        return

    # Pilih EOR
    active_id = st.session_state.get("active_revision_eor", "")
    if active_id and any(e.get("id") == active_id for e in my_revision_eors):
        eor = next(e for e in my_revision_eors if e.get("id") == active_id)
    else:
        eor = my_revision_eors[0]
    
    st.session_state["active_revision_eor"] = eor.get("id", "")
    eor_id = eor.get("id", "")
    ws_comments = st.session_state.workspace_comments.get(eor_id, {})

    # Tampilkan info re-submit sebelumnya jika ada
    prev_resubmit_count = eor.get("resubmit_count", 0)
    if prev_resubmit_count > 0:
        st.info(f"📌 Ini adalah re-submit ke-{prev_resubmit_count + 1}. Previous note: {eor.get('resubmit_note', '-')[:100]}")

    st.markdown(f"**EOR:** `{eor_id}` | **TOE:** {eor.get('toe_name','')}")

    # Initialize storage
    if "revision_acks" not in eor:
        eor["revision_acks"] = {}
    if "revision_responses" not in eor:
        eor["revision_responses"] = {}
    
    acks = eor["revision_acks"]
    responses = eor["revision_responses"]

    findings = eor.get("findings", [])
    
    # Progress
    total_feedback = sum(1 for f in findings if ws_comments.get(f.get("id", "")))
    total_acked = sum(1 for f in findings if acks.get(f.get("id", ""), False))
    
    if total_feedback > 0:
        st.progress(total_acked / total_feedback)
        st.caption(f"Progress: {total_acked}/{total_feedback}")
    st.divider()

    # Loop findings
    for finding in findings:
        uid = finding.get("id", "")
        thread = ws_comments.get(uid, [])
        lead_comment = finding.get("lead_comment", "")
        is_acked = acks.get(uid, False)

        st.markdown(f"**{uid}** - {finding.get('title', '')[:60]}")
        if lead_comment:
            st.info(f"💬 Lead: {lead_comment}")
        for c in thread:
            if c.get("role") == "lead_evaluator":
                st.markdown(f"📝 {c.get('text', '')[:150]}")

        if is_acked:
            st.success(f"✅ Acknowledged")
            if st.button(f"↩ Undo", key=f"undo_{eor_id}_{uid}"):
                acks[uid] = False
                eor["revision_acks"] = dict(acks)
                save_eor(eor)
                st.session_state["current_page"] = "revision_review"
                st.rerun()
        else:
            with st.form(key=f"form_{eor_id}_{uid}"):
                resp_text = st.text_area("Tanggapan", value=responses.get(uid, ""), height=80)
                submitted = st.form_submit_button("✅ Acknowledge", type="primary")
                if submitted:
                    responses[uid] = resp_text if resp_text.strip() else "[Acknowledged]"
                    acks[uid] = True
                    eor["revision_acks"] = dict(acks)
                    eor["revision_responses"] = dict(responses)
                    save_eor(eor)
                    st.session_state["current_page"] = "revision_review"
                    st.rerun()
        st.divider()

    # ============================================================
    # RE-SUBMIT BUTTON - DENGAN COUNTER
    # ============================================================
    
    # Hitung ulang dengan lebih jelas
    findings_with_lead_comment = []
    for f in findings:
        uid = f.get("id", "")
        has_lead_comment = bool(ws_comments.get(uid)) or bool(f.get("lead_comment")) or bool(f.get("lead_verdict"))
        if has_lead_comment:
            findings_with_lead_comment.append(uid)
    
    total_with_feedback = len(findings_with_lead_comment)
    total_acked = sum(1 for uid in findings_with_lead_comment if acks.get(uid, False))
    
    st.markdown("---")
    
    if total_with_feedback == 0:
        st.info("📝 Tidak ada finding dengan komentar Lead. Anda bisa langsung re-submit.")
        all_acked = True
    else:
        all_acked = total_acked >= total_with_feedback
        st.info(f"📊 Progress: {total_acked}/{total_with_feedback} finding dengan komentar Lead sudah di-acknowledge")
    
    # Tampilkan tombol jika semua sudah di-acknowledge ATAU tidak ada komentar Lead
    if all_acked:
        st.markdown('<div style="background:rgba(63,185,80,.08);border:1px solid rgba(63,185,80,.2);border-radius:10px;padding:.85rem 1.1rem;margin:.5rem 0;font-size:.85rem;color:#3fb950;">✅ Semua komentar Lead sudah di-acknowledge. Siap untuk Re-Submit ke Lead Evaluator.</div>', unsafe_allow_html=True)
        
        col_a, col_b = st.columns([3, 1])
        with col_a:
            resubmit_note = st.text_input(
                "📝 Catatan Re-Submit (wajib diisi - akan tampil di Kanban Lead)",
                placeholder="e.g. Semua komentar Lead sudah dipertimbangkan. Perubahan sudah dilakukan di ST section 3.2.",
                key=f"resubmit_note_{eor_id}"
            )
        with col_b:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 Re-Submit ke Lead", key=f"resubmit_{eor_id}", type="primary", use_container_width=True):
                if not resubmit_note.strip():
                    st.warning("⚠️ Mohon isi catatan re-submit sebagai informasi untuk Lead Evaluator.")
                else:
                    # Update EOR status - INCREMENT RESUBMIT COUNTER
                    current_count = eor.get("resubmit_count", 0)
                    eor["status"] = "SUBMITTED"
                    eor["resubmitted_at"] = datetime.now().isoformat()
                    eor["resubmit_note"] = resubmit_note.strip()
                    eor["resubmit_count"] = current_count + 1  # INCREMENT DI SINI
                    eor.pop("needs_reaudit", None)
                    eor.pop("revision_at", None)
                    save_eor(eor)
                    
                    # Clean up session state
                    st.session_state.pop("in_revision_review", None)
                    st.session_state.pop("current_page", None)
                    st.session_state.pop("revision_mode", None)
                    st.session_state.pop("active_revision_eor", None)
                    
                    add_notification(
                        "🔄 EOR Re-Submitted (Revision)",
                        f"mengirim ulang Workbook EOR setelah revision",
                        target="lead_evaluator",
                        sender=st.session_state.get("user_name","Evaluator"),
                        obj=f"EOR {eor_id} — {eor.get('toe_name','')} (Re-submit #{eor['resubmit_count']})",
                        keterangan=resubmit_note.strip()[:100],
                        icon="🔄"
                    )
                    st.success(f"✅ EOR {eor_id} berhasil di-re-submit ke Lead Evaluator! (Re-submit #{eor['resubmit_count']})")
                    st.info("Kanban Lead akan menampilkan badge RE-SUBMIT dengan border kuning.")
                    st.session_state["nav_target"] = "kanban"
                    st.rerun()
    else:
        remaining = total_with_feedback - total_acked
        st.warning(f"⚠️ {remaining} finding dengan komentar Lead belum di-acknowledge. Baca dan acknowledge semua komentar Lead sebelum Re-Submit.")

def page_push_to_lead():
    """v2.0: Push ke Lead SAJA — bukan CB atau Developer.
    Kanban otomatis update ke ON REVIEW TO LEAD (status=SUBMITTED)."""
    pg_header("🚀","Push ke Lead Evaluator","Cycle 1 — Workbook Layer 1 dikirim ke Lead untuk final review")
    
    # VALIDASI: Pastikan data TOE sudah diisi
    if not st.session_state.toe_name:
        st.error("❌ Isi TOE Name di sidebar terlebih dahulu sebelum push ke Lead!")
        return
    if not st.session_state.project_id:
        st.warning("⚠️ Project ID belum diisi. Silakan isi di sidebar.")
    
    if not st.session_state.audit_results:
        st.warning("Belum ada hasil audit. Jalankan audit terlebih dahulu."); return
    res=st.session_state.audit_results; results=st.session_state.audit_results_raw
    fl=[r for r in results if r.get_final_verdict()=="FAIL"]
    il=[r for r in results if r.get_final_verdict()=="INCONCLUSIVE"]
    all_findings = fl+il

    # Summary
    c1,c2,c3,c4=st.columns(4)
    c1.metric("✅ PASS",res["pass"]); c2.metric("❌ FAIL",res["fail"])
    c3.metric("⚠️ INC",res["inc"]); c4.metric("📌 N/A",res.get("na",0))

    st.markdown("""
<div style="background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.2);
  border-radius:10px;padding:1rem;margin:1rem 0;">
  <b style="color:#58a6ff;">ℹ️ Alur Push Cycle 1</b><br>
  <span style="font-size:.85rem;color:#8b949e;">
  Evaluator → <b>Lead Evaluator</b> (review & override workbook)<br>
  Kanban: DRAFT → <b>ON REVIEW TO LEAD</b><br>
  Lead akan: Accept All → Push to CB <b>atau</b> Need Revision → kembali ke Evaluator<br>
  CB dan Developer belum dilibatkan di Cycle 1.
  </span>
</div>""", unsafe_allow_html=True)

    if not all_findings:
        st.success("🎉 Tidak ada temuan FAIL/INC — workbook clean!")
        st.info("Anda tetap bisa push workbook ke Lead untuk konfirmasi.")

    st.markdown(f"**{len(all_findings)} finding** akan disertakan dalam workbook EOR.")

    col_a, col_b = st.columns(2)
    with col_a:
        due_date=st.date_input("📅 Target Due Date",value=date.today()+timedelta(days=14))
    with col_b:
        cycle_note = st.text_input("📝 Catatan untuk Lead",
            placeholder="e.g. Cycle 1 review ASE_INT selesai — 2 temuan perlu konfirmasi")

    if st.button("🚀 Push ke Lead Evaluator",type="primary",use_container_width=True):
        active=[s for s,k in [("CoT","enable_cot"),("NegSpace","enable_negative_space"),
            ("SemGuard","enable_sem_guard"),("ConfCalib","enable_confidence_calib")]
            if st.session_state.get(k,True)]
        eor_id = f"EOR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        findings_payload = []
        for r in all_findings:
            evaluator_images = persist_evaluator_images(
                eor_id,
                r.id,
                st.session_state.ev_evidence_images.get(r.id, [])
            )
            findings_payload.append({
                "id":r.id,
                "title":r.label,
                "verdict":r.get_final_verdict(),
                "confidence":r.confidence,
                "evidence":r.evidence[:150],
                "has_images":bool(evaluator_images),
                "evaluator_override": r.human_verdict if r.is_overridden() else None,
                "evaluator_comment": r.human_comment if r.human_comment else None,
                "evaluator_images": evaluator_images
            })
        eor_entry={
            "id":eor_id,
            "toe_name":res["toe_name"],"toe_version":res["toe_version"],"eal":res["eal"],
            "submitted_by":st.session_state.username,
            "submitted_at":datetime.now().isoformat(),
            "due_date":str(due_date),"status":"SUBMITTED",
            "cycle_note":cycle_note,
            "cycle":1,
            "findings":findings_payload,
            "ai_engine":"CC-AI Smart Platform v2.0","skill_level":st.session_state.skill_level,
            "active_skills":str(active),
            "pass_count":res["pass"],"fail_count":res["fail"],
            "inc_count":res["inc"],"na_count":res.get("na",0),
            # === BARU: Initial values untuk re-submit tracking ===
            "resubmit_count": 0,
            "resubmit_note": "",
        }
        # Add observations list (CC EOR format)
        eor_entry["observations"] = [
            {
                "id": f["id"],
                "no": i+1,
                "cc_component": f["id"],
                "eval_reference": CRITERIA.get(f["id"],{}).get("cc","—"),
                "issue_description": "",
                "resolution_thread": [],
                "status": "OPEN",
                "verdict_ai": f["verdict"],
                "confidence": f["confidence"],
            }
            for i,f in enumerate(eor_entry["findings"])
        ]
        st.session_state.eor_backlog.append(eor_entry)
        save_eor(eor_entry)
        
        add_notification(
            "📋 Workbook EOR Diterima (Cycle 1)",
            f"mengirimkan Workbook EOR Cycle 1 untuk {res['toe_name']}",
            target="lead_evaluator",
            sender=st.session_state.get("user_name","Evaluator"),
            obj=f"EOR {eor_id} — {len(all_findings)} findings ({res['fail']} FAIL, {res['inc']} INC)",
            keterangan=cycle_note or f"Due: {due_date}",
            icon="📋"
        )
        st.success(f"✅ Workbook {eor_id} berhasil dikirim ke Lead Evaluator!")
        st.info("📋 Kanban Board: DRAFT → **ON REVIEW TO LEAD**. Menunggu review Lead.")
        st.rerun()

def page_eor_workspace():
    pg_header("📋","EOR Workspace","Review inline — comment, override, artefact, dev status")
    if not st.session_state.eor_backlog: 
        st.info("📭 Belum ada EOR.")
        return
    
    # === MODIFIKASI: Tampilkan badge re-submit di dropdown ===
    eor_options = []
    for e in st.session_state.eor_backlog:
        eor_id = e.get('id', '')
        toe_name = e.get('toe_name', '')
        status = e.get('status', '')
        resubmit_count = e.get('resubmit_count', 0)
        
        # Tambahkan indikator re-submit
        if resubmit_count > 0:
            label = f"🔄 {eor_id} — {toe_name} ({status}) [RE-SUBMIT #{resubmit_count}]"
        else:
            label = f"{eor_id} — {toe_name} ({status})"
        
        eor_options.append({"label": label, "eor": e})
    
    selected_label = st.selectbox(
        "Pilih EOR", 
        options=[opt["label"] for opt in eor_options],
        key="eor_workspace_select"
    )
    
    # Cari EOR yang dipilih
    eor = None
    for opt in eor_options:
        if opt["label"] == selected_label:
            eor = opt["eor"]
            break
    
    if eor is None:
        st.error("EOR tidak ditemukan")
        return
    
    render_collaborative_workspace(eor)

def page_schedule_tm():
    pg_header("📅","Schedule Technical Meeting","")
    c1,c2=st.columns(2)
    with c1: md=st.date_input("Date"); mt=st.time_input("Time")
    with c2: pl=st.radio("Platform",["Google Meet","Microsoft Teams"],horizontal=True)
    e1=st.text_input("Evaluator Email",value="evaluator@cc-lab.go.id")
    e2=st.text_input("Developer Email",value="developer@example.com")
    if st.button("📧 Schedule",type="primary"):
        link="https://meet.google.com/abc-xyz" if pl=="Google Meet" else f"https://teams.microsoft.com/meeting_{random.randint(100000,999999)}"
        st.session_state.tm_schedules.append({"id":f"TM-{datetime.now().strftime('%Y%m%d%H%M%S')}","date":str(md),"time":mt.strftime("%H:%M"),"link":link,"status":"scheduled"})
        add_notification("📅 TM Scheduled",f"TM dijadwalkan {md} {mt}","evaluator")
        add_notification("📅 TM Scheduled",f"TM dijadwalkan {md} {mt}","developer")
        st.success(f"✅ TM Scheduled! 🔗 {link}")

def page_record_tm():
    pg_header("📝","Record TM Minutes","Notulen dan action items")
    sched=[t for t in st.session_state.tm_schedules if t.get("status")=="scheduled"]
    if not sched: st.info("Belum ada TM."); return
    sel=st.selectbox("Pilih TM",sched,format_func=lambda x:f"{x['id']} {x['date']}")
    mins=st.text_area("Notulen",height=150); acts=st.text_area("Action Items",height=100)
    if st.button("📧 Save & Send",type="primary"):
        sel["status"]="completed"; sel["minutes"]=mins; sel["actions"]=acts
        add_notification("📝 TM Minutes",f"Minutes TM {sel['id']} tersedia","evaluator")
        add_notification("📝 TM Minutes",f"Minutes TM {sel['id']} tersedia","developer")
        st.success("✅ Minutes recorded & sent!")

def page_notifications(role):
    """v2.0: Notifikasi format SPOK — Siapa | Predikat | Objek | Keterangan | Waktu"""
    pg_header("🔔","Notifikasi","Format SPOK: Siapa · Aksi · Objek · Keterangan · Waktu")
    my=[n for n in st.session_state.notifications if n.get("target_role")==role]
    if not my:
        st.info("📭 Tidak ada notifikasi."); return

    unread = [n for n in my if not n.get("read")]
    if unread:
        st.markdown(f'<span class="sb sb-fail">{len(unread)} belum dibaca</span>', unsafe_allow_html=True)

    col_filter1, col_filter2 = st.columns([1,4])
    with col_filter1:
        if st.button("✅ Tandai Semua Dibaca"):
            for n in my: n["read"]=True
            st.rerun()

    st.divider()
    for n in reversed(my):
        icon = n.get("icon","🔔")
        is_unread = not n.get("read",False)
        n["read"] = True

        sender   = n.get("sender","System")
        title    = n.get("title","Notifikasi")
        msg      = n.get("message","")
        obj      = n.get("obj","")
        ket      = n.get("keterangan","")
        ts       = n.get("created_at","")[:16].replace("T"," ")
        spok     = n.get("spok","")

        # Build SPOK line
        spok_parts = []
        if sender and sender != "System": spok_parts.append(f"<b>{sender}</b>")
        spok_parts.append(msg)
        if obj: spok_parts.append(f"· <i>{obj}</i>")
        if ket: spok_parts.append(f"· {ket}")
        spok_html = " ".join(spok_parts)

        unread_dot = '<div class="notif-unread"></div>' if is_unread else '<div style="width:6px;"></div>'

        st.markdown(f"""
<div class="notif-card">
  {unread_dot}
  <div class="notif-icon">{icon}</div>
  <div class="notif-body">
    <div class="notif-subject">{title}</div>
    <div class="notif-spok">{spok_html}</div>
    <div class="notif-ts">🕐 {ts}</div>
  </div>
</div>""", unsafe_allow_html=True)

def page_dev_dashboard():
    pg_header("🛠️","Developer Dashboard","Assigned findings & response tracking")
    dev_findings=st.session_state.dev_findings
    my_findings=[(eid,uid,f) for eid,units in dev_findings.items() for uid,f in units.items()
                 if f.get("assigned_to","")==st.session_state.username or not f.get("assigned_to","")]
    n_open=sum(1 for _,_,f in my_findings if f.get("status","OPEN")=="OPEN")
    n_resp=sum(1 for _,_,f in my_findings if f.get("status","")=="RESPONDED")
    n_veri=sum(1 for _,_,f in my_findings if f.get("status","")=="VERIFIED")
    st.markdown(f'<div class="metric-grid">{metric_html(n_open,"🔴 Open","#f85149")}{metric_html(n_resp,"🔵 Responded","#58a6ff")}{metric_html(n_veri,"🟢 Verified","#3fb950")}{metric_html(count_notifs("developer"),"🔔 Notif","#d2a8ff")}</div>',unsafe_allow_html=True)
    my_notifs=[n for n in st.session_state.notifications if n.get("target_role")=="developer"]
    if my_notifs:
        st.markdown("### 🔔 Notifikasi")
        for n in reversed(my_notifs[-4:]): n["read"]=True; st.info(f"**{n['title']}**: {n['message']}")

# ============================================================
# MAIN
# ============================================================
def main():
    # Sync persistent EORs from disk on every load
    sync_eor_backlog()
    
    # === MIGRASI DATA UNTUK EOR LAMA (tanpa resubmit_count) ===
    for eor in st.session_state.eor_backlog:
        if "resubmit_count" not in eor:
            eor["resubmit_count"] = 0
        if "resubmit_note" not in eor:
            eor["resubmit_note"] = ""
    
    if not st.session_state.logged_in:
        login_page()
        return

    # SAFE PAGE REDIRECT HANDLER (use nav_target to avoid widget key conflict)
    if "next_page" in st.session_state:
        st.session_state["nav_target"] = st.session_state.pop("next_page")

    # NAVIGATION - Use current_page from session state
    # Set default page if not set
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "dashboard"
    
    # Auto-redirect for revision review
    if st.session_state.role == "evaluator":
        # Check if we're in revision review mode
        if st.session_state.get("in_revision_review", False):
            st.session_state["current_page"] = "revision_review"
        elif st.session_state.get("revision_mode", False):
            has_revision = any(
                e.get("status") == "REVISION" and
                e.get("submitted_by") == st.session_state.username
                for e in st.session_state.eor_backlog
            )
            if has_revision:
                st.session_state["current_page"] = "revision_review"
                st.session_state["in_revision_review"] = True
            else:
                st.session_state.pop("revision_mode", None)
    
    # SIDEBAR - get page and scope_ids
    page, scope_ids = render_sidebar()
    
    # Get role AFTER sidebar (or from session state)
    role = st.session_state.role
    
    # Override page from session state if needed (for evaluator only)
    if role == "evaluator":
        if st.session_state.get("current_page") == "revision_review":
            page = "revision_review"

    # ROLE ROUTING
    if role == "evaluator":
        pages = {
            "dashboard": page_dashboard,
            "kanban": render_evaluator_kanban,
            "upload_audit": lambda: page_upload_audit(scope_ids),
            "audit_results": page_audit_results,
            "eor": page_generate_eor,
            "push": page_push_to_lead,
            "revision_review": page_revision_review,
            "notifications": lambda: page_notifications(role)
        }
    elif role == "lead_evaluator":
        pages = {
            "dashboard": page_dashboard,
            "kanban": render_kanban_board,
            "eor_workspace": page_eor_workspace,
            "dev_manage": render_lead_dev_management,
            "timeline": render_project_timeline,
            "notifications": lambda: page_notifications(role)
        }
    elif role == "developer":
        pages = {
            "dashboard": page_dev_dashboard,
            "my_findings": lambda: render_dev_finding_tracker(st.session_state.username),
            "notifications": lambda: page_notifications(role)
        }
    else:  # cb_auditor
        pages = {
            "dashboard": page_dashboard,
            "kanban": render_cb_kanban,
            "tm_management": render_cb_tm_management,
            "dev_responses_cb": page_cb_dev_responses,
            "timeline": render_project_timeline,
            "notifications": lambda: page_notifications(role)
        }
    
    # Execute the page
    if pages:
        pages.get(page, list(pages.values())[0])()
    else:
        st.error("No pages configured for this role")


if __name__ == "__main__":
    main()

