"""Renders output/design-sample.html with PLACEHOLDER content, to preview the email design without any
network access or API keys. Nothing in it is real news; the banner at the top says so.
Run:  python scripts/design_sample.py"""
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recast_intel.config import load_config  # noqa: E402
from recast_intel.pipeline import Briefing, Story  # noqa: E402
from recast_intel.render import render_html  # noqa: E402
from recast_intel.store import now_utc  # noqa: E402

cfg = load_config()
t = now_utc()
ex = "https://example.com/"
stories = [
    Story("s1", "Example: A video provider opens a motion-control API",
          "Placeholder text. In a real edition this explains what was announced, using only facts from the source.",
          "Placeholder. Here Claude explains the impact on Recast, e.g. a new creative recipe you could offer.",
          ex + "1", "Official announcement", "official", "AI Video & Creative Tech", t - timedelta(hours=3), 9,
          [{"publisher": "Example News", "url": ex + "1b"}]),
    Story("s2", "Example: A competitor launches templates for short-form remixes",
          "Placeholder text describing a competitor launch, written as reporting because it comes from a news outlet.",
          "Placeholder. Why this matters for Recast's positioning and pricing.",
          ex + "2", "Reported by Example Tech Daily", "news", "Competitors & Opportunities", t - timedelta(hours=7), 8),
    Story("s3", "Example: A developer tool ships agent hooks",
          "Placeholder text about a developer-tool release that could speed up building Recast.",
          "Placeholder. How it could shorten your build cycle.",
          ex + "3", "Official announcement", "official", "AI Tools & Product Updates", t - timedelta(hours=11), 7),
]
b = Briefing(
    mode="daily", subject="Recast Intelligence: design sample", ai_written=True,
    opening="Placeholder opening. A real edition starts with the single most important development and why it matters to you.",
    stories=stories,
    opportunities=[{"idea": "Example: a 'Motion Match' recipe",
                    "rationale": "Placeholder rationale linking an opportunity to the stories above.",
                    "links": [{"title": "s1", "url": ex + "1"}]}],
    watching=[{"item_id": "w1", "title": "Example: Rumored pricing change at a video provider", "note": "Placeholder note.",
               "url": ex + "4", "source_label": "Reported by Example Wire"},
              {"item_id": "w2", "title": "Example: Community thread on character consistency", "note": "",
               "url": ex + "5", "source_label": "Community discussion (Hacker News)"}],
)
out = ROOT / "output"
out.mkdir(exist_ok=True)
path = out / "design-sample.html"
path.write_text(render_html(cfg, b, banner="DESIGN SAMPLE: placeholder text, not real news"), encoding="utf-8")
print(path)
