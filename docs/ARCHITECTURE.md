# Architecture Notes — Scaling Beyond the Monolith

This document is for anyone considering scaling CC-AI Smart Platform beyond a single-evaluator workstation deployment. The current `app.py` is intentionally a monolithic Streamlit application — easy to install, zero infrastructure dependencies, fully airgapped-capable. That design is a deliberate trade-off, and it has real limits worth understanding before you rely on it for multi-evaluator, production-scale lab operations.

## Current limitations

| Limitation | Why it matters |
|---|---|
| AI audit runs synchronously in the browser session | A 76-work-unit audit (1.5–5+ hours depending on model) blocks the UI for that entire time; closing the browser loses progress. |
| No concurrency control on JSON data files | Two users editing the same EOR simultaneously can race and corrupt data — there is no locking or transaction mechanism. |
| Authentication is a hardcoded demo dictionary | Not suitable for any deployment where real credentials/security matter — replace before exposing beyond a trusted local network. |
| Single Python process | One unhandled error can take down the whole app for every concurrent user. |
| No automated tests, no CI/CD | Every code change should be manually verified before deployment. |

## Recommended target architecture (if scaling is needed)

```
React/Next.js Frontend
        │
        ▼
   FastAPI Backend  ──────►  PostgreSQL (audit data, EOR, users)
        │
        ▼
  Celery + Redis (background AI audit jobs)
        │
        ▼
   Ollama (unchanged — still local inference)
```

### Phase 0 — Foundation (no user-facing change)
Refactor `app.py` into separate modules (`audit_engine.py`, `eor_service.py`, `auth.py`, `notifications.py`). Stand up PostgreSQL and migrate existing JSON data into it. The Streamlit UI keeps working exactly as before during this phase.

### Phase 1 — Background job queue
This is the highest-value phase. Move the AI audit loop into a Celery task backed by Redis, so:
- The browser no longer needs to stay open during a multi-hour audit.
- Multiple audits can run concurrently without blocking each other.
- Progress can be polled or pushed via WebSocket instead of blocking the Streamlit script.

### Phase 2 — Frontend decoupling
Replace the Streamlit UI with a React/Next.js frontend talking to the FastAPI backend over REST/WebSocket. This unlocks proper multi-user sessions, role-based routing, and a more maintainable component-based UI.

### Phase 3 — Auth & hardening
Integrate real authentication (LDAP/SSO if your organization has it, or at minimum `FastAPI-Users` with TOTP 2FA). Move file storage to a proper object store (MinIO) instead of local disk. Add Nginx + TLS in front of everything.

### Phase 4 — Observability
Add Prometheus/Grafana for metrics, structured logging, and automated backups. Set up CI/CD so changes go through lint → test → build → deploy rather than manual file copying.

## What stays the same throughout

- **Local-only AI inference via Ollama** — this is a hard constraint, not just a current convenience. Do not introduce calls to external LLM APIs as part of any scaling effort without a full security/compliance review.
- **The CEM:2022 R1 work unit logic and the 5 prompting skills** — this business logic should be lifted into a backend module largely as-is; it doesn't need a rewrite, just a new home outside the Streamlit script.
- **The CC EOR / Workbook formats** — `FR.MT.04.WB` and `FR.MT.04.11` report generation logic can be reused directly in a FastAPI endpoint.

## A note on incremental migration

None of the above needs to happen as a "big bang" rewrite. The monolith can keep running for active evaluations while infrastructure work happens in parallel. Phase 0 and Phase 1 alone — modularizing the code and moving the audit loop to a background job — solve the two most painful operational problems (long-running blocking audits and code maintainability) without requiring a frontend rewrite.
