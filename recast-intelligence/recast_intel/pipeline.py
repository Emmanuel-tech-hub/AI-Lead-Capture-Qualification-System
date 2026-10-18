"""The end-to-end steps: collect -> triage -> build briefing. Rendering and sending live elsewhere."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ai import AIError, Claude
from .config import Config
from .relevance import heuristic_importance, keyword_score, prefilter
from .sources import Article, FetchError, fetch_source, make_client
from .store import Store, now_utc

log = logging.getLogger(__name__)

SOURCE_LABEL = {"official": "Official announcement", "news": "Reported by {publisher}",
                "community": "Community discussion ({publisher})"}


# ---------------------------------------------------------------- collect
@dataclass
class CollectReport:
    new: int = 0
    duplicates: int = 0
    seen: int = 0
    too_old: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    ok: dict[str, int] = field(default_factory=dict)


def collect(cfg: Config, store: Store, client=None) -> CollectReport:
    report = CollectReport()
    cutoff = now_utc() - timedelta(hours=cfg.delivery.lookback_hours)
    own_client = client is None
    client = client or make_client()
    try:
        for src in (s for s in cfg.sources if s.enabled):
            try:
                articles, _ = fetch_source(src, client)
            except (FetchError, Exception) as e:  # one broken source must never stop the run
                report.failed[src.id] = str(e)[:300]
                store.record_source_run(src.id, ok=False, error=str(e))
                log.warning("source_failed source=%s error=%s", src.id, e)
                continue
            new_here = 0
            for a in articles:
                if a.published_at < cutoff:
                    report.too_old += 1
                    continue
                score, passed = prefilter(a, cfg)
                result = store.add_article(a, score, passed)
                if result == "new":
                    new_here += 1
                    report.new += 1
                elif result == "duplicate":
                    report.duplicates += 1
                else:
                    report.seen += 1
            report.ok[src.id] = new_here
            store.record_source_run(src.id, ok=True, new_items=new_here)
            log.info("source_ok source=%s fetched=%d new=%d", src.id, len(articles), new_here)
    finally:
        if own_client:
            client.close()
    store.set_state("last_collect_at", now_utc().isoformat())
    return report


# ---------------------------------------------------------------- triage
def _excerpt(row, limit: int) -> str:
    text = row["summary"] or ""
    return text[:limit]


def triage(cfg: Config, store: Store, claude: Claude | None = None) -> int:
    rows = store.untriaged()
    if not rows:
        return 0
    if cfg.ai_active:
        claude = claude or Claude(cfg)
        payload = [{"ref": f"a{i}", "title": r["title"], "source": r["publisher"], "kind": r["kind"],
                    "published": r["published_at"], "excerpt": _excerpt(r, 400)} for i, r in enumerate(rows)]
        try:
            results = claude.triage(payload)
        except AIError as e:
            log.error("triage_failed error=%s (falling back to keyword ranking)", e)
            results = {}
        for i, r in enumerate(rows):
            t = results.get(f"a{i}")
            if t:
                store.save_triage(r["id"], t.importance, t.topic, t.breaking, t.reason)
        missing = [r for i, r in enumerate(rows) if f"a{i}" not in results]
    else:
        missing = list(rows)
    for r in missing:  # keyword fallback (AI off, failed, or skipped an item)
        a = Article(r["id"], r["source_id"], r["source_name"], r["kind"], r["publisher"], r["title"], r["url"],
                    r["canonical"], datetime.fromisoformat(r["published_at"]), r["summary"] or "",
                    json.loads(r["topics"] or "[]"))
        score, topic = keyword_score(a, cfg)
        store.save_triage(r["id"], heuristic_importance(r["kind"], score), topic or "other", False,
                          "Keyword ranking (AI unavailable)")
    return len(rows)


# ---------------------------------------------------------------- briefing
@dataclass
class Story:
    item_id: str
    headline: str
    what_happened: str
    why_it_matters: str
    url: str
    source_label: str
    kind: str
    topic_name: str
    published: datetime
    score: int
    also: list[dict] = field(default_factory=list)


@dataclass
class Briefing:
    mode: str
    subject: str
    opening: str
    stories: list[Story]
    opportunities: list[dict]
    watching: list[dict]
    ai_written: bool
    failing_sources: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=now_utc)

    @property
    def item_ids(self) -> list[str]:
        return [s.item_id for s in self.stories] + [w["item_id"] for w in self.watching]

    @property
    def empty(self) -> bool:
        return not self.stories


def source_label(row) -> str:
    return SOURCE_LABEL.get(row["kind"], "{publisher}").format(publisher=row["publisher"] or row["source_name"])


def build_briefing(cfg: Config, store: Store, mode: str = "daily", hours: int | None = None,
                   claude: Claude | None = None, include_sent: bool = False) -> Briefing:
    d = cfg.delivery
    since = now_utc() - timedelta(hours=hours or d.lookback_hours)
    if mode == "breaking":
        rows = store.breaking_candidates(d.breaking_min_score, since)[:3]
    else:
        rows = store.candidates(d.daily_min_score, since, exclude_sent_daily=not include_sent)
        rows = rows[: d.max_stories + d.max_watching + 4]
    failing = [f"{r['source_id']}" for r in store.failing_sources()]
    if not rows:
        return Briefing(mode, f"{cfg.name}: no major updates", "", [], [], [], cfg.ai_active, failing)

    by_ref = {f"a{i}": r for i, r in enumerate(rows)}

    def topic_name(row) -> str:
        t = cfg.topic(row["topic"] or "")
        return t.name if t else "Other"

    def story_from(ref: str, headline: str, what: str, why: str) -> Story:
        r = by_ref[ref]
        also = [{"publisher": x["publisher"], "url": x["url"]} for x in store.also_covered_by(r["id"])][:3]
        return Story(r["id"], headline, what, why, r["url"], source_label(r), r["kind"], topic_name(r),
                     datetime.fromisoformat(r["published_at"]), r["score"], also)

    if cfg.ai_active:
        claude = claude or Claude(cfg)
        payload = [{"ref": ref, "title": r["title"], "source_label": source_label(r), "published": r["published_at"],
                    "importance": r["score"], "excerpt": _excerpt(r, 1500)} for ref, r in by_ref.items()]
        try:
            out = claude.briefing(payload, mode, d.max_stories, d.max_watching)
            stories = [story_from(s.ref, s.headline, s.what_happened, s.why_it_matters) for s in out.stories]
            watching = [{"item_id": by_ref[w.ref]["id"], "title": by_ref[w.ref]["title"], "note": w.note,
                         "url": by_ref[w.ref]["url"], "source_label": source_label(by_ref[w.ref])}
                        for w in out.worth_watching]
            opps = [{"idea": o.idea, "rationale": o.rationale,
                     "links": [{"title": by_ref[r]["title"], "url": by_ref[r]["url"]} for r in o.refs]}
                    for o in out.opportunities]
            return Briefing(mode, out.subject, out.opening, stories, opps, watching, True, failing)
        except AIError as e:
            log.error("briefing_ai_failed error=%s (sending keyword version)", e)

    # Keyword fallback: real headlines and excerpts, no AI analysis.
    top, rest = rows[: d.max_stories if mode == "daily" else 3], rows[d.max_stories:][: d.max_watching]
    ref_of = {r["id"]: ref for ref, r in by_ref.items()}
    stories = [story_from(ref_of[r["id"]], r["title"], _excerpt(r, 400) or "Details are in the source article.",
                          "") for r in top]
    watching = [{"item_id": r["id"], "title": r["title"], "note": "", "url": r["url"],
                 "source_label": source_label(r)} for r in rest] if mode == "daily" else []
    subject = f"{cfg.name}: {top[0]['title'][:70]}"
    opening = "AI summaries are unavailable for this edition, so stories are ranked by keywords and source."
    return Briefing(mode, subject, opening, stories, [], watching, False, failing)
