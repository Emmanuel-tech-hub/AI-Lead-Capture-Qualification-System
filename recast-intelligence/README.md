# Recast Intelligence

Your personal briefing on AI, creative technology, and what's next. A small Python app that watches the
sources you care about, filters out noise, has Claude explain what matters for Recast, and emails you a
polished briefing. No n8n, no frontend, no server: it runs on your Windows PC through Task Scheduler.

```
config.yaml ──► collect ──► store + dedupe ──► triage ──► briefing ──► HTML email
(your interests)  RSS/APIs    SQLite           Claude     Claude      SMTP (Gmail etc.)
                  retries     URL + title      scores     writes,
                              matching         1-10       links come from the database
```

## What you get
- **Daily Briefing** at your chosen time: opening, ranked top stories with *what happened* and *why it matters to Recast*, **Opportunities for Recast**, **Worth Watching**, and source links.
- **Breaking Updates** (optional): an immediate email for genuinely major news (score 9+ by default, at most 2 a day).
- **No empty newsletters:** quiet days are skipped, or you get a one-line note (`empty_day` in config).
- **Every story is labeled** *Official announcement*, *Reported by <outlet>*, or *Community discussion*.

## How accuracy is protected
- Claude only sees article text that was actually fetched, wrapped as untrusted data, with instructions never to follow anything inside it.
- **Claude never writes links or source labels.** It refers to articles by ID. URLs, outlets and labels come from the database, so a made-up link is impossible. Any ID Claude returns that wasn't provided is discarded.
- Headline-only items (Google News) are flagged so Claude doesn't invent details.
- Only `http(s)` links reach the email, and all text is HTML-escaped.

---

## Setup on Windows (about 15 minutes)

**1. Install Python 3.11+** from python.org (tick "Add python.exe to PATH").

**2. Get the code and install it.** In PowerShell, inside the `recast-intelligence` folder:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```
This creates a private Python environment (`.venv`), installs the libraries, and creates your `.env` file.

**3. Fill in `.env`** (Notepad is fine). This is the minimum you need:

| Setting | Why it's needed | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude scores stories and writes the briefing. Without it you still get emails, ranked by keywords with article excerpts | console.anthropic.com → API Keys (needs billing set up) |
| `RECAST_EMAIL_TO` / `RECAST_EMAIL_FROM` | Where the briefing goes and who it's from | Your email address for both |
| `RECAST_SMTP_*` | Sends the email | Gmail: host `smtp.gmail.com`, port `587`, user = your Gmail address, password = a **16-character App Password** (Google Account → Security → 2-Step Verification → App passwords). Your normal password will not work |

`.env` is git-ignored, so your keys never get committed.

**4. Check everything:**
```powershell
.\.venv\Scripts\python.exe -m recast_intel doctor
```
This tests every source and shows which ones answer. If a source fails, set `enabled: false` on it in `config.yaml`, or fix its URL.

**5. Preview, then send a test:**
```powershell
.\.venv\Scripts\python.exe -m recast_intel preview --open     # builds output\preview.html and opens it
.\.venv\Scripts\python.exe -m recast_intel send-test          # emails it to you, marked [TEST]
```
The first run looks back `lookback_hours` (36 h by default), so there's real content right away.

**6. Turn on automatic delivery:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
```
This registers a task that runs every 15 minutes while you're logged in. Each run checks `config.yaml` and does only what's due: refresh sources (every `monitor_every_minutes`), breaking alerts, and the daily briefing. If your PC was off at 7:30, the briefing goes out as soon as it's back on that day.

---

## Customizing (all in `config.yaml`, no code changes)

| To change... | Edit |
|---|---|
| Delivery time and timezone | `delivery.daily_time`, `delivery.timezone` |
| How often sources are checked | `delivery.monitor_every_minutes` |
| How picky it is | `daily_min_score` (default 6), `breaking_min_score` (default 9), `max_stories` |
| Breaking alerts on or off | `delivery.breaking_alerts` |
| Quiet-day behavior | `delivery.empty_day`: `skip` or `short_note` |
| Your interests | `topics`: add a topic with `id`, `name`, `keywords`, `weight` |
| Things to ignore | `exclusions` |
| What Claude knows about Recast | `about_me` |
| Models | `ai.triage_model`, `ai.briefing_model` (default `claude-opus-5-5`; a cheaper model such as `claude-haiku-4-5` for triage cuts cost) |

**Adding a source.** Three types are supported:
```yaml
- id: my_feed            # any RSS or Atom feed (check it with `doctor`)
  name: Some Blog
  kind: official         # official | news | community
  type: rss
  url: https://example.com/feed.xml
  topics: [ai_video]

- id: news_capcut        # Google News search for any company, person or keyword
  name: News - CapCut
  kind: news
  type: google_news
  query: '"CapCut" when:2d'
  topics: [competitors]

- id: hn_runway          # Hacker News stories above a points threshold
  name: Hacker News - Runway
  kind: community
  type: hn_algolia
  query: Runway
  min_points: 50
  topics: [ai_video]
```

## Commands
| Command | What it does |
|---|---|
| `doctor` | Checks config, keys and every source |
| `collect` | Fetches sources, stores new articles, scores them |
| `preview [--open] [--no-ai] [--hours 48]` | Builds `output/preview.html` without sending or marking anything as sent |
| `send-test` | Emails the preview to you |
| `daily` | Builds and sends today's briefing now |
| `tick` | What the scheduler runs |

Logs are in `logs/recast.log` (rotated automatically), and scheduler output is in `logs/scheduler.log`. Failing sources are listed in the footer of the next briefing.

## Sources: what's verified

| Source | Status |
|---|---|
| Claude Code releases (GitHub Atom) | **Fetched live** on 2026-10-18 |
| OpenAI News RSS | Listed by feed directories and the OpenAI forum; confirm with `doctor` |
| Google DeepMind blog RSS | Listed by feed directories (served gzip-compressed; handled automatically) |
| Google AI blog RSS | Two URL variants exist; the app tries both and `doctor` reports which one works |
| Google News search RSS | Widely used but **undocumented by Google**; could change without notice |
| Hacker News search API (hn.algolia.com) | Public API |
| **Anthropic news** | **No official RSS feed exists.** Covered by Claude Code releases and Google News; unofficial community feeds are not used by default |
| **Higgsfield, Kling, Runway** | No official feeds found. Covered through Google News search |

## Project layout
```
recast_intel/
  config.py     load and validate config.yaml + .env
  sources.py    RSS / Google News / Hacker News fetchers with retries
  textutil.py   HTML cleaning, canonical URLs, title fingerprints
  store.py      SQLite: articles, dedupe, sends, source health
  relevance.py  keyword pre-filter and the no-AI ranking
  ai.py         Claude triage and briefing (structured output, refusal fallback)
  pipeline.py   collect -> triage -> build briefing
  render.py     HTML + plain-text email
  mailer.py     SMTP with retries
  scheduler.py  the 15-minute "tick"
templates/newsletter.html.j2   the email design
scripts/        Windows setup, Task Scheduler install, design sample
tests/          pytest suite (python -m pytest)
```

## Costs
Claude is billed per use. Triage runs only on new, pre-filtered articles (in batches of 40, at low effort), and the briefing is one call a day plus any breaking alerts. Check current prices at anthropic.com/pricing. If you want to spend less, switch `triage_model` to a cheaper model.
