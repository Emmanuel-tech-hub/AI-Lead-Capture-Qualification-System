from datetime import datetime, timedelta, timezone

from recast_intel.config import Source
from recast_intel.relevance import prefilter
from recast_intel.sources import Article, parse_feed, parse_hn
from recast_intel.textutil import canonical_url, clean_text, safe_url, similarity

from conftest import FIXTURES


def art(title, url="https://example.com/a", kind="news", summary="", source="s1", publisher="Pub", hours_ago=1):
    return Article(id=f"{source}-{title}-{url}", source_id=source, source_name=source, kind=kind, publisher=publisher,
                   title=title, url=url, canonical=canonical_url(url),
                   published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago), summary=summary,
                   topics=["ai_video"])


def test_canonical_url_strips_tracking_and_www():
    assert canonical_url("https://www.Example.com/post/?utm_source=x&b=2&a=1#top") == "https://example.com/post?a=1&b=2"


def test_clean_text_removes_scripts_and_bidi():
    assert clean_text("<p>Hello</p><script>evil()</script>‮world") == "Hello world"


def test_safe_url_blocks_non_http():
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url("https://ok.com") == "https://ok.com"


def test_similarity_detects_same_story():
    assert similarity("OpenAI launches Sora 3 video model", "OpenAI launches new Sora 3 video model today") > 0.7


def test_parse_atom_fixture_cleans_and_drops_bad_links():
    src = Source(id="t", name="Test", kind="official", type="rss", topics=["ai_tools"], url="https://x")
    items = parse_feed((FIXTURES / "sample_atom.xml").read_bytes(), src)
    assert len(items) == 1  # javascript: link dropped
    assert items[0].summary == "New agent hooks."
    assert items[0].canonical == "https://example.com/releases/v9.9.9"


def test_parse_google_news_strips_publisher():
    src = Source(id="g", name="GN", kind="news", type="google_news", topics=["ai_video"], query="x")
    [a] = parse_feed((FIXTURES / "sample_gnews.xml").read_bytes(), src)
    assert a.title == "Higgsfield launches new motion model"
    assert a.publisher == "TechExample"
    assert a.summary == ""  # headline-only summaries are not treated as facts


def test_parse_hn():
    src = Source(id="h", name="HN", kind="community", type="hn_algolia", topics=["ai_video"], query="x")
    [a] = parse_hn({"hits": [{"objectID": "1", "title": "Show HN: AI video tool", "url": "https://tool.dev",
                              "points": 120, "num_comments": 40, "created_at_i": 1790000000}]}, src)
    assert a.url == "https://tool.dev" and "120 points" in a.summary


def test_prefilter_exclusions_and_community_rules(cfg):
    assert prefilter(art("Huge giveaway for Kling users"), cfg) == (0.0, False)
    assert prefilter(art("Gardening tips", kind="community"), cfg)[1] is False
    assert prefilter(art("Kling ships image-to-video update", kind="community"), cfg)[1] is True
    assert prefilter(art("Untitled post", kind="official"), cfg)[1] is True


def test_dedupe_same_url_and_near_duplicate_title(store):
    assert store.add_article(art("Runway releases Gen-5 video model", url="https://a.com/x?utm_source=1"), 5, True) == "new"
    assert store.add_article(art("Different headline", url="https://www.a.com/x/", source="s2"), 5, True) == "duplicate"
    assert store.add_article(art("Runway releases Gen-5 video model today", url="https://b.com/y", source="s3"), 5, True) == "duplicate"
    assert store.add_article(art("Runway releases Gen-5 video model", url="https://a.com/x?utm_source=1"), 5, True) == "seen"
    assert len(store.untriaged()) == 1


def test_official_source_becomes_primary_story(store):
    store.add_article(art("Kling 3 launches with lip sync", url="https://news.com/k"), 5, True)
    store.add_article(art("Kling 3 launches with lip sync", url="https://kling.ai/blog/k3", kind="official", source="off"), 5, True)
    [primary] = store.untriaged()
    assert primary["kind"] == "official"
    assert [r["publisher"] for r in store.also_covered_by(primary["id"])] == ["Pub"]
