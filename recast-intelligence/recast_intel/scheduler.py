"""One "tick" runs every 15 minutes (Windows Task Scheduler). It decides what is due:
collect + triage, breaking alerts, and the daily briefing. Delivery time and timezone come from config.yaml,
so changing them never requires re-registering the scheduled task."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import mailer
from .config import Config
from .pipeline import Briefing, build_briefing, collect, triage
from .render import render_html, render_text
from .store import Store, now_utc

log = logging.getLogger(__name__)


def collect_due(cfg: Config, store: Store, now: datetime, max_age_minutes: int | None = None) -> bool:
    last = store.get_state("last_collect_at")
    if not last:
        return True
    age = now - datetime.fromisoformat(last)
    return age >= timedelta(minutes=max_age_minutes or cfg.delivery.monitor_every_minutes)


def daily_due(cfg: Config, store: Store, now: datetime) -> bool:
    local = now.astimezone(cfg.delivery.tz)
    h, m = cfg.delivery.daily_hm
    return (local.hour, local.minute) >= (h, m) and store.sends_on("daily", local.date().isoformat()) == 0


def deliver(cfg: Config, store: Store, b: Briefing, kind: str, send_fn=mailer.send) -> None:
    send_fn(cfg.secrets, b.subject, render_html(cfg, b), render_text(cfg, b))
    if b.item_ids:
        store.mark_sent(b.item_ids, "daily" if kind == "daily" else "breaking")
    local_date = now_utc().astimezone(cfg.delivery.tz).date().isoformat()
    store.record_send(kind, local_date, b.subject, b.item_ids)


def tick(cfg: Config, store: Store, now: datetime | None = None, send_fn=mailer.send) -> list[str]:
    now = now or now_utc()
    today = now.astimezone(cfg.delivery.tz).date().isoformat()
    actions: list[str] = []
    is_daily = daily_due(cfg, store, now)

    # Refresh sources if due, and always within 30 minutes before a daily briefing goes out.
    if collect_due(cfg, store, now) or (is_daily and collect_due(cfg, store, now, max_age_minutes=30)):
        r = collect(cfg, store)
        n = triage(cfg, store)
        actions.append(f"collected new={r.new} dup={r.duplicates} failed={len(r.failed)} triaged={n}")

    d = cfg.delivery
    if d.breaking_alerts and cfg.ai_active and store.sends_on("breaking", today) < d.max_breaking_per_day:
        b = build_briefing(cfg, store, mode="breaking", hours=12)
        if not b.empty:
            b.subject = f"Breaking: {b.subject}"
            deliver(cfg, store, b, "breaking", send_fn)
            actions.append(f"sent breaking alert ({len(b.stories)} stories)")

    if is_daily:
        b = build_briefing(cfg, store, mode="daily")
        if not b.empty:
            deliver(cfg, store, b, "daily", send_fn)
            actions.append(f"sent daily briefing ({len(b.stories)} stories)")
        elif d.empty_day == "short_note":
            deliver(cfg, store, b, "daily", send_fn)
            actions.append("sent no-major-updates note")
        else:
            store.record_send("daily", today, "(skipped: nothing important)", [])
            actions.append("daily skipped: nothing important")

    log.info("tick actions=%s", actions or ["nothing due"])
    return actions
