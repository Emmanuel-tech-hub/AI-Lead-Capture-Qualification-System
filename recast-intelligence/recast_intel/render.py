"""Turns a Briefing into the HTML email and a plain-text alternative."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .pipeline import Briefing
from .textutil import safe_url

TEMPLATES = Path(__file__).parent / "templates"
TOPIC_COLORS = ["#6D5BF7", "#3B82F6", "#A855F7", "#0EA5E9", "#7C3AED", "#2563EB"]
KIND_STYLE = {"official": ("#E3EEFF", "#1D4ED8"), "news": ("#F1EAFE", "#6D28D9"), "community": ("#EEF0F4", "#4B5563")}


def _ago(dt: datetime) -> str:
    mins = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return dt.strftime("%b %d")


def _env(cfg: Config) -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    names = [t.name for t in cfg.topics]
    env.globals["topic_color"] = lambda n: TOPIC_COLORS[names.index(n) % len(TOPIC_COLORS)] if n in names else "#64748B"
    env.globals["kind_bg"] = lambda k: KIND_STYLE.get(k, KIND_STYLE["community"])[0]
    env.globals["kind_fg"] = lambda k: KIND_STYLE.get(k, KIND_STYLE["community"])[1]
    env.filters["ago"] = _ago
    return env


def _scrub_links(b: Briefing) -> None:
    """Defense in depth: every link in the email must be http(s)."""
    for s in b.stories:
        s.url = safe_url(s.url) or "#"
        s.also = [x for x in s.also if safe_url(x["url"])]
    for w in b.watching:
        w["url"] = safe_url(w["url"]) or "#"
    for o in b.opportunities:
        o["links"] = [l for l in o["links"] if safe_url(l["url"])]


def render_html(cfg: Config, b: Briefing, banner: str = "") -> str:
    _scrub_links(b)
    local = b.generated_at.astimezone(cfg.delivery.tz)
    preheader = b.opening[:140] if b.opening else (b.stories[0].headline if b.stories else "No major updates today.")
    return _env(cfg).get_template("newsletter.html.j2").render(
        cfg=cfg, b=b, preheader=preheader, banner=banner,
        date_label=local.strftime("%A, %B %d, %Y").replace(" 0", " "),
        generated_label=local.strftime("%b %d, %I:%M %p %Z").replace(" 0", " "),
    )


def render_text(cfg: Config, b: Briefing) -> str:
    lines = [cfg.name.upper(), cfg.tagline, ""]
    if b.opening:
        lines += [b.opening, ""]
    if b.empty:
        lines += ["No major developments crossed your threshold since the last briefing.", ""]
    for i, s in enumerate(b.stories, 1):
        lines += [f"{i}. {s.headline}  [{s.topic_name} | {s.source_label}]", s.what_happened]
        if s.why_it_matters:
            lines.append(f"Why it matters: {s.why_it_matters}")
        lines += [f"Source: {s.url}", ""]
    if b.opportunities:
        lines += ["OPPORTUNITIES FOR RECAST"]
        for o in b.opportunities:
            lines += [f"- {o['idea']}: {o['rationale']}"] + [f"  {l['url']}" for l in o["links"]]
        lines.append("")
    if b.watching:
        lines += ["WORTH WATCHING"] + [f"- {w['title']} ({w['source_label']}) {w['url']}" for w in b.watching] + [""]
    if b.ai_written:
        lines.append("Summaries are AI-written from the linked sources. Check the source before acting.")
    return "\n".join(lines)
