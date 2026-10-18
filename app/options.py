"""Command-line options shared by build.py and mailbot.py."""
from app.browser import LIVE_START_HELP, BrowserUnavailable, cdp_ready
from app.config import MODES


def add_source_options(parser):
    parser.add_argument("--mode", choices=MODES,
                        help="live: scrape in the visible Chrome on port 9333 for the audience; "
                             "background: same scraping in a hidden Chrome (default, or RFQ_MODE)")
    parser.add_argument("--demo-delay", type=float, help="Seconds to show each product page in live mode")
    parser.add_argument("--offline", action="store_true", help="Use only the supplied catalog; no network")
    parser.add_argument("--no-browser", action="store_true", help="Use HTTPS, PDFs, and catalog without Chrome")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--quality", choices=("rules", "ai"))


def apply_source_options(args, settings):
    if args.mode:
        settings.mode = args.mode
    if args.demo_delay is not None:
        settings.demo_delay = args.demo_delay
    if args.offline:
        settings.offline = True
    if args.no_browser:
        settings.browser = False
    if args.no_pdf:
        settings.pdfs = False
    if args.quality:
        settings.quality = args.quality
    return settings


def require_live_chrome(settings):
    """Fail at startup, not per email, when live mode has no visible Chrome."""
    if settings.mode == "live" and settings.browser and not settings.offline and not cdp_ready(settings.cdp_url, 2):
        raise BrowserUnavailable(f"No Chrome on {settings.cdp_url}.\n" + LIVE_START_HELP)
