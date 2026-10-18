"""Command line: python -m recast_intel <command>

  doctor      Check config, credentials and every source (run this first)
  collect     Fetch sources, store new articles, score them
  preview     Build the newsletter into output/preview.html without sending or marking anything
  send-test   Email the preview to yourself (marks nothing as sent)
  daily       Build and send today's briefing now
  tick        What the scheduler runs every 15 minutes: does whatever is due
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

from . import mailer
from .config import ConfigError, load_config
from .logsetup import setup_logging
from .pipeline import build_briefing, collect, triage
from .render import render_html, render_text
from .scheduler import deliver, tick
from .sources import FetchError, fetch_source, make_client
from .store import Store

log = logging.getLogger("recast_intel")


def cmd_doctor(cfg, store, args) -> int:
    print(f"Config OK: {len(cfg.topics)} topics, {len(cfg.sources)} sources, timezone {cfg.delivery.timezone}, "
          f"daily at {cfg.delivery.daily_time}")
    s = cfg.secrets
    print(f"Claude API key: {'set' if s.anthropic_api_key else 'MISSING (newsletter will use keyword ranking only)'}")
    print(f"Email: {'ready' if s.smtp_ready else 'NOT CONFIGURED (preview works, sending does not)'}")
    print("\nSources:")
    ok = 0
    with make_client() as client:
        for src in cfg.sources:
            if not src.enabled:
                print(f"  [off]  {src.id}")
                continue
            try:
                arts, url = fetch_source(src, client)
                ok += 1
                latest = max((a.published_at for a in arts), default=None)
                print(f"  [ OK ] {src.id:24} {len(arts):3} items, latest {latest:%Y-%m-%d}" if latest
                      else f"  [ OK ] {src.id:24}   0 items (feed works but is empty)")
                if url != src.url and src.type == "rss":
                    print(f"         answered from fallback URL: {url}  (consider making it the main url)")
            except FetchError as e:
                print(f"  [FAIL] {src.id:24} {str(e)[:110]}")
    print(f"\n{ok}/{sum(1 for x in cfg.sources if x.enabled)} sources reachable.")
    return 0


def cmd_collect(cfg, store, args) -> int:
    r = collect(cfg, store)
    n = triage(cfg, store)
    print(f"New: {r.new}  duplicates: {r.duplicates}  already seen: {r.seen}  too old: {r.too_old}  scored: {n}")
    for sid, err in r.failed.items():
        print(f"  source failed: {sid}: {err[:120]}")
    return 0


def _build(cfg, store, args):
    if args.no_ai:
        cfg.ai.enabled = False
    if not args.no_collect:
        cmd_collect(cfg, store, args)
    return build_briefing(cfg, store, mode=args.mode, hours=args.hours, include_sent=True)


def cmd_preview(cfg, store, args) -> int:
    b = _build(cfg, store, args)
    out = cfg.root / "output"
    out.mkdir(exist_ok=True)
    path = out / "preview.html"
    path.write_text(render_html(cfg, b), encoding="utf-8")
    (out / "preview.txt").write_text(render_text(cfg, b), encoding="utf-8")
    print(f"Subject: {b.subject}\nStories: {len(b.stories)}  watching: {len(b.watching)}  "
          f"opportunities: {len(b.opportunities)}  AI-written: {b.ai_written}\nPreview: {path}")
    if args.open:
        webbrowser.open(path.as_uri())
    return 0


def cmd_send_test(cfg, store, args) -> int:
    b = _build(cfg, store, args)
    mailer.send(cfg.secrets, f"[TEST] {b.subject}", render_html(cfg, b), render_text(cfg, b))
    print(f"Test email sent to {cfg.secrets.email_to}")
    return 0


def cmd_daily(cfg, store, args) -> int:
    collect(cfg, store)
    triage(cfg, store)
    b = build_briefing(cfg, store, mode="daily")
    if b.empty and cfg.delivery.empty_day == "skip":
        print("Nothing important since the last briefing; nothing sent (empty_day: skip).")
        return 0
    deliver(cfg, store, b, "daily")
    print(f"Sent: {b.subject}")
    return 0


def cmd_tick(cfg, store, args) -> int:
    for a in tick(cfg, store):
        print(a)
    return 0


COMMANDS = {"doctor": cmd_doctor, "collect": cmd_collect, "preview": cmd_preview, "send-test": cmd_send_test,
            "daily": cmd_daily, "tick": cmd_tick}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="recast_intel", description="Recast Intelligence newsletter")
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("--mode", choices=["daily", "breaking"], default="daily", help="preview/send-test only")
    p.add_argument("--hours", type=int, default=None, help="look back this many hours (preview/send-test)")
    p.add_argument("--no-ai", action="store_true", help="skip Claude; keyword ranking only")
    p.add_argument("--no-collect", action="store_true", help="use stored articles; don't fetch")
    p.add_argument("--open", action="store_true", help="open the preview in your browser")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    try:
        cfg = load_config()
    except (ConfigError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 2
    setup_logging(cfg.root, verbose=args.verbose)
    store = Store(cfg.db_path)
    try:
        return COMMANDS[args.command](cfg, store, args)
    except mailer.MailError as e:
        log.error("mail_error %s", e)
        print(f"Email error: {e}", file=sys.stderr)
        return 1
    except Exception:
        log.exception("unhandled_error command=%s", args.command)
        print("Unexpected error; details in logs/recast.log", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
