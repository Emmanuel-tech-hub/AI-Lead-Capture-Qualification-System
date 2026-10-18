"""Cleaning untrusted article text, canonical URLs and title fingerprints for deduplication."""
from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "si", "cmpid", "ocid"}
STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "its", "it",
             "at", "by", "from", "as", "this", "that", "new", "now", "how", "why", "what", "you", "your"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "iframe", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in {"p", "li", "div", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def clean_text(raw: str | None, limit: int = 2000) -> str:
    """HTML -> plain text, with control and bidi characters removed. Output is still untrusted data."""
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = _CONTROL.sub("", html.unescape(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def safe_url(url: str | None) -> str:
    """Only http(s) links reach the email."""
    if not url:
        return ""
    url = url.strip()
    return url if urlsplit(url).scheme in {"http", "https"} else ""


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def strip_publisher_suffix(title: str, publisher: str = "") -> str:
    """Google News titles end with ' - Publisher'."""
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].strip()
    return title


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9.\-]*", title.lower())
    return {w.strip(".-") for w in words if w not in STOPWORDS and len(w) > 1}


def title_fingerprint(title: str) -> str:
    return hashlib.sha1(" ".join(sorted(title_tokens(title))).encode()).hexdigest()[:16]


def similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]
