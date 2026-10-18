"""Cheap keyword pre-filter (before any AI cost) and a keyword-only ranking used when AI is off."""
from __future__ import annotations

import re

from .config import Config
from .sources import Article

KIND_BASE = {"official": 3.0, "news": 1.5, "community": 1.0}


def _hits(keyword: str, text: str) -> int:
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])", text))


def is_excluded(text: str, cfg: Config) -> bool:
    low = text.lower()
    return any(_hits(x, low) for x in cfg.exclusions)


def keyword_score(a: Article, cfg: Config) -> tuple[float, str | None]:
    """Returns (score, best topic id). Title matches count triple."""
    title, body = a.title.lower(), a.summary.lower()
    best_topic, best = None, 0.0
    total = 0.0
    for topic in cfg.topics:
        s = sum(3 * _hits(k, title) + min(_hits(k, body), 3) for k in topic.keywords) * topic.weight
        total += s
        if s > best:
            best_topic, best = topic.id, s
    return total, best_topic


def prefilter(a: Article, cfg: Config) -> tuple[float, bool]:
    """Official and topic-specific news sources pass on any keyword hit or by being on-topic by construction;
    community items need a keyword hit. Exclusions always drop."""
    if is_excluded(f"{a.title} {a.summary}", cfg):
        return 0.0, False
    score, _ = keyword_score(a, cfg)
    if a.kind == "community":
        return score, score > 0
    return score, True


def heuristic_importance(kind: str, kw_score: float) -> int:
    """1-10 importance without AI: source authority plus keyword strength."""
    return max(1, min(10, round(KIND_BASE.get(kind, 1.0) + min(kw_score, 12) / 2 + 2)))
