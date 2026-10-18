import argparse
import logging
import time
from pathlib import Path

from app.browser import BrowserUnavailable
from app.config import BOT_NAME, Settings
from app.mailbox import check_inbox
from app.options import add_source_options, apply_source_options, require_live_chrome


def main():
    parser = argparse.ArgumentParser(description="Poll unread Gmail RFQs every 30 seconds")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Build drafts without sending or marking mail read")
    parser.add_argument("--out", type=Path, default=Path("out/mail"))
    parser.add_argument("--interval", type=int, default=30, help="Seconds between inbox checks")
    add_source_options(parser)
    args = parser.parse_args()
    settings = apply_source_options(args, Settings.from_env())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        require_live_chrome(settings)
    except BrowserUnavailable as exc:
        parser.exit(1, str(exc) + "\n")
    logging.info("%s: Watching for RFQ emails (scraping mode: %s)", BOT_NAME, settings.describe())
    started = time.time()
    done = set()  # emails finished during this run; not downloaded again
    while True:
        try:
            sent = check_inbox(args.out, settings, dry_run=args.dry_run, since=started, done=done)
            if not args.once:
                logging.info("Inbox checked: %d %s. Next check in %d s (Ctrl+C to stop)",
                             sent, "reply sent" if sent == 1 else "replies sent", args.interval)
        except ValueError as exc:
            parser.exit(1, str(exc) + "\n")
        except Exception as exc:
            logging.error("Inbox check failed (%s: %s); retrying in %d s", type(exc).__name__,
                          str(exc)[:150], args.interval)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(args.interval)
