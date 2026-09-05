# Repo notes for Claude

This repository was originally an n8n lead-capture workflow writeup
(see `README.md` at the repo root). That original project has no code in
this repo — just documentation.

## Active project: Freight Invoice Auditor

Branch: `claude/freight-invoice-auditor-u4z5jf`
Location: `freight-invoice-auditor/`

**What it is:** V1 of a "money-finding engine" for logistics companies —
upload a carrier contract, a carrier invoice, and shipment records; it
matches every billed invoice line against the contracted rate, flags
discrepancies (rate charged above contract, fuel surcharge above cap,
phantom/over-capped accessorial fees) with cited evidence, totals the
potential overcharge, and exports a dispute report (PDF/CSV).

**Status:** Complete and working. FastAPI backend + vanilla JS/HTML
frontend, sample data, and a passing pytest suite. Verified end-to-end via
browser automation (upload → audit → export all confirmed working).

**To run it:**
```bash
cd freight-invoice-auditor/backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000 and upload the sample files in
`sample_data/` (or your own — see `freight-invoice-auditor/README.md` for
the expected document format).

**Full details:** see `freight-invoice-auditor/README.md` — architecture,
document format spec, API reference, project layout, and what V2 would add
(OCR/LLM extraction for arbitrary PDF layouts, auth/database,
QuickBooks/Xero/NetSuite/SAP integrations).

No PR has been opened for this branch yet (not requested). To pick this
work back up: `git checkout claude/freight-invoice-auditor-u4z5jf`.
