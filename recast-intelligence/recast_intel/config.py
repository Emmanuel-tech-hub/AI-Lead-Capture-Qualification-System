"""Loads config.yaml and secrets from the environment (.env)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_TYPES = {"rss", "google_news", "hn_algolia"}
SOURCE_KINDS = {"official", "news", "community"}


class ConfigError(ValueError):
    pass


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines. Real environment variables always win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Topic:
    id: str
    name: str
    keywords: list[str]
    weight: float = 1.0


@dataclass
class Source:
    id: str
    name: str
    kind: str
    type: str
    topics: list[str]
    url: str = ""
    query: str = ""
    fallback_urls: list[str] = field(default_factory=list)
    min_points: int = 0
    enabled: bool = True
    verification: str = ""


@dataclass
class Delivery:
    timezone: str = "America/New_York"
    daily_time: str = "07:30"
    monitor_every_minutes: int = 120
    daily_min_score: int = 6
    max_stories: int = 6
    max_watching: int = 4
    breaking_alerts: bool = True
    breaking_min_score: int = 9
    max_breaking_per_day: int = 2
    empty_day: str = "skip"
    lookback_hours: int = 36

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def daily_hm(self) -> tuple[int, int]:
        h, m = self.daily_time.split(":")
        return int(h), int(m)


@dataclass
class AISettings:
    enabled: bool = True
    triage_model: str = "claude-opus-5-5"
    briefing_model: str = "claude-opus-5-5"
    triage_effort: str = "low"
    briefing_effort: str = "medium"


@dataclass
class Secrets:
    anthropic_api_key: str
    email_to: str
    email_from: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str

    @property
    def smtp_ready(self) -> bool:
        return all([self.email_to, self.email_from, self.smtp_host, self.smtp_user, self.smtp_password])


@dataclass
class Config:
    name: str
    tagline: str
    delivery: Delivery
    ai: AISettings
    about_me: str
    topics: list[Topic]
    exclusions: list[str]
    sources: list[Source]
    secrets: Secrets
    root: Path = PROJECT_ROOT

    @property
    def db_path(self) -> Path:
        return self.root / "recast_intel.db"

    @property
    def topic_ids(self) -> list[str]:
        return [t.id for t in self.topics]

    def topic(self, topic_id: str) -> Topic | None:
        return next((t for t in self.topics if t.id == topic_id), None)

    @property
    def ai_active(self) -> bool:
        return self.ai.enabled and bool(self.secrets.anthropic_api_key)


def _secrets_from_env() -> Secrets:
    return Secrets(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        email_to=os.environ.get("RECAST_EMAIL_TO", ""),
        email_from=os.environ.get("RECAST_EMAIL_FROM", ""),
        smtp_host=os.environ.get("RECAST_SMTP_HOST", ""),
        smtp_port=int(os.environ.get("RECAST_SMTP_PORT", "587") or 587),
        smtp_user=os.environ.get("RECAST_SMTP_USER", ""),
        smtp_password=os.environ.get("RECAST_SMTP_PASSWORD", ""),
    )


def load_config(path: Path | None = None, root: Path | None = None) -> Config:
    root = root or PROJECT_ROOT
    path = path or root / "config.yaml"
    load_dotenv(root / ".env")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    nl = raw.get("newsletter", {})
    delivery = Delivery(**(raw.get("delivery") or {}))
    ai = AISettings(**(raw.get("ai") or {}))
    topics = [Topic(**t) for t in raw.get("topics", [])]
    sources = [Source(**s) for s in raw.get("sources", [])]

    cfg = Config(
        name=nl.get("name", "Recast Intelligence"),
        tagline=nl.get("tagline", ""),
        delivery=delivery,
        ai=ai,
        about_me=(raw.get("about_me") or "").strip(),
        topics=topics,
        exclusions=[str(x) for x in raw.get("exclusions", [])],
        sources=sources,
        secrets=_secrets_from_env(),
        root=root,
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    errors = []
    try:
        cfg.delivery.tz
    except Exception:
        errors.append(f"delivery.timezone '{cfg.delivery.timezone}' is not a valid IANA timezone")
    if not re.fullmatch(r"\d{1,2}:\d{2}", cfg.delivery.daily_time):
        errors.append("delivery.daily_time must look like 07:30")
    if cfg.delivery.empty_day not in {"skip", "short_note"}:
        errors.append("delivery.empty_day must be 'skip' or 'short_note'")
    for name in ("daily_min_score", "breaking_min_score"):
        if not 1 <= getattr(cfg.delivery, name) <= 10:
            errors.append(f"delivery.{name} must be between 1 and 10")
    if not cfg.topics:
        errors.append("at least one topic is required")
    seen = set()
    for s in cfg.sources:
        if s.id in seen:
            errors.append(f"duplicate source id '{s.id}'")
        seen.add(s.id)
        if s.type not in SOURCE_TYPES:
            errors.append(f"source '{s.id}': type must be one of {sorted(SOURCE_TYPES)}")
        if s.kind not in SOURCE_KINDS:
            errors.append(f"source '{s.id}': kind must be one of {sorted(SOURCE_KINDS)}")
        if s.type == "rss" and not s.url.startswith("https://"):
            errors.append(f"source '{s.id}': rss sources need an https url")
        if s.type in {"google_news", "hn_algolia"} and not s.query:
            errors.append(f"source '{s.id}': {s.type} sources need a query")
        for t in s.topics:
            if t not in cfg.topic_ids:
                errors.append(f"source '{s.id}': unknown topic '{t}'")
    if errors:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(errors))
