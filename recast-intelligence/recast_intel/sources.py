"""Fetches articles from RSS/Atom feeds, Google News search and the Hacker News Algolia API."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from .config import Source
from .textutil import canonical_url, clean_text, safe_url, stable_id, strip_publisher_suffix

log = logging.getLogger(__name__)

USER_AGENT = "RecastIntelligence/1.0 (personal newsletter; +https://www.recast.app)"
MAX_BYTES = 5_000_000
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&numericFilters=points%3E{p}&hitsPerPage=30"


@dataclass
class Article:
    id: str
    source_id: str
    source_name: str
    kind: str
    publisher: str
    title: str
    url: str
    canonical: str
    published_at: datetime
    summary: str
    topics: list[str] = field(default_factory=list)


class FetchError(RuntimeError):
    pass


def http_get(url: str, client: httpx.Client, attempts: int = 3) -> bytes:
    """GET with retries and exponential backoff. Retries timeouts, 429 and 5xx; not other 4xx."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            r = client.get(url)
            if r.status_code == 429 or r.status_code >= 500:
                raise FetchError(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} (not retried)")
            if len(r.content) > MAX_BYTES:
                raise FetchError("response too large")
            return r.content
        except FetchError as e:
            last = e
            if "not retried" in str(e):
                break
        except httpx.HTTPError as e:
            last = e
        if attempt < attempts - 1:
            time.sleep(2 ** attempt * 2)
    raise FetchError(f"{url}: {last}")


def _entry_time(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def parse_feed(content: bytes, source: Source) -> list[Article]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise FetchError(f"not a valid feed ({feed.get('bozo_exception', 'parse error')})")
    out = []
    for e in feed.entries:
        link = safe_url(e.get("link"))
        if not link:
            continue
        publisher = ""
        if source.type == "google_news":
            publisher = clean_text((e.get("source") or {}).get("title", ""), 120)
        title = clean_text(strip_publisher_suffix(e.get("title", ""), publisher), 300)
        if not title:
            continue
        body = e.get("summary") or ""
        if e.get("content"):
            body = e["content"][0].get("value") or body
        out.append(Article(
            id=stable_id(source.id, e.get("id") or link),
            source_id=source.id,
            source_name=source.name,
            kind=source.kind,
            publisher=publisher or source.name,
            title=title,
            url=link,
            canonical=canonical_url(link),
            published_at=_entry_time(e),
            # Google News summaries only repeat the headline, so they carry no extra facts.
            summary="" if source.type == "google_news" else clean_text(body, 2500),
            topics=list(source.topics),
        ))
    return out


def parse_hn(payload: dict, source: Source) -> list[Article]:
    out = []
    for hit in payload.get("hits", []):
        discussion = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        link = safe_url(hit.get("url")) or discussion
        title = clean_text(hit.get("title"), 300)
        if not title:
            continue
        ts = hit.get("created_at_i")
        out.append(Article(
            id=stable_id(source.id, str(hit.get("objectID"))),
            source_id=source.id,
            source_name=source.name,
            kind=source.kind,
            publisher="Hacker News",
            title=title,
            url=link,
            canonical=canonical_url(link),
            published_at=datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc),
            summary=f"Hacker News discussion with {hit.get('points', 0)} points and "
                    f"{hit.get('num_comments', 0)} comments. Discussion: {discussion}",
            topics=list(source.topics),
        ))
    return out


def fetch_source(source: Source, client: httpx.Client) -> tuple[list[Article], str]:
    """Returns (articles, url_used). Tries fallback URLs for RSS sources."""
    if source.type == "rss":
        errors = []
        for url in [source.url, *source.fallback_urls]:
            try:
                return parse_feed(http_get(url, client), source), url
            except FetchError as e:
                errors.append(str(e))
        raise FetchError("; ".join(errors))
    if source.type == "google_news":
        url = GOOGLE_NEWS.format(q=quote_plus(source.query))
        return parse_feed(http_get(url, client), source), url
    if source.type == "hn_algolia":
        url = HN_SEARCH.format(q=quote_plus(source.query), p=int(source.min_points))
        return parse_hn(json.loads(http_get(url, client)), source), url
    raise FetchError(f"unknown source type {source.type}")


def make_client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
