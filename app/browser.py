"""Chrome over CDP for ferguson.com product pages, in live (visible) or background (hidden) mode.

Both modes drive a normally started Chrome through the DevTools protocol, the method the RFQ
brief prescribes. Live mode attaches to the Chrome window the presenter opened on port 9333 and
shows every page to the audience. Background mode starts its own Chrome with the window placed
off-screen, so the same scraping happens without anything on screen.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

LIVE_START_HELP = (
    "Live mode needs the visible Chrome running with remote debugging. Start it with:\n"
    '  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" `\n'
    "    --remote-debugging-port=9333 `\n"
    '    --user-data-dir="$env:TEMP\\chrome-rfq" `\n'
    "    https://www.ferguson.com/\n"
    "or run with --mode background."
)
SPEC_TABLE = ".product-specification-table"
SPEC_ROW = ".c-product-details__specs__specsAttributes"
HIGHLIGHT_CSS = SPEC_TABLE + " { outline: 4px solid #f59e0b; outline-offset: 6px; }"


class BrowserUnavailable(RuntimeError):
    """No Chrome could be reached for the ferguson.com step."""


class Blocked(RuntimeError):
    """ferguson.com refused the request (bot protection)."""


class NotOnSite(RuntimeError):
    """ferguson.com answered, but has no product page for the ID."""


def find_chrome(configured=""):
    candidates = [configured, os.getenv("CHROME_PATH", "")]
    for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")):
        if base:
            candidates.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
    candidates += [shutil.which(name) or "" for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium")]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def cdp_ready(url, timeout=1.0):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout):
            return True
    except OSError:
        return False


class Browser:
    def __init__(self, settings):
        self.settings = settings
        self.mode = settings.mode
        self.playwright = self.browser = self.page = self.process = None
        self.last_load = 0.0

    def start(self):
        """Connect to Chrome. Raises BrowserUnavailable with a clear reason."""
        if self.mode == "live":
            url = self.settings.cdp_url
            if not cdp_ready(url, 2):
                raise BrowserUnavailable(f"No Chrome on {url}.\n" + LIVE_START_HELP)
        else:
            url = f"http://127.0.0.1:{self.settings.background_port}"
            if not cdp_ready(url):
                self._launch_hidden(url)
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(url, timeout=10000)
            context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            self.page = context.new_page()
            if self.mode == "live":
                self.page.bring_to_front()
        except Exception as exc:
            self.close()
            raise BrowserUnavailable(f"Cannot attach to Chrome on {url}: {exc}") from exc
        log.info("[%s] Chrome connected on %s", self.mode, url)

    def _launch_hidden(self, url):
        chrome = find_chrome(self.settings.chrome_path)
        if not chrome:
            raise BrowserUnavailable("Chrome is not installed here (set CHROME_PATH to use background mode)")
        profile = Path(tempfile.gettempdir()) / "chrome-rfq-background"
        self.process = subprocess.Popen(
            [chrome, f"--remote-debugging-port={self.settings.background_port}",
             "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
             "--window-position=-32000,-32000", "--window-size=1280,900",
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cdp_ready(url, 0.5):
                return
            time.sleep(0.3)
        self.close()
        raise BrowserUnavailable("Background Chrome did not start within 20 seconds")

    def product_page(self, url, product_id):
        """Load a product page and return (html, final_url)."""
        page = self.page
        # Polite pacing between page loads: rapid sequences get rate-limited (Access Denied).
        wait = self.last_load + self.settings.page_pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_load = time.monotonic()
        log.info("[%s] ferguson.com: opening %s", self.mode, product_id)
        page.goto(url, wait_until="domcontentloaded", timeout=self.settings.page_timeout * 1000)
        deadline = time.monotonic() + self.settings.page_timeout
        title = ""
        while time.monotonic() < deadline:
            title = page.title() or ""
            if title and not title.startswith("Loading") and "just a moment" not in title.lower():
                break
            page.wait_for_timeout(500)
        if "access denied" in title.lower():
            raise Blocked("ferguson.com returned Access Denied")
        if title.startswith("404") or "oops" in title.lower():
            raise NotOnSite("ferguson.com has no product page for this ID")
        # The specification block renders after the product data; reading earlier loses fields.
        for selector, wait in (('script[type="application/ld+json"]', 5000), (SPEC_ROW, 8000)):
            try:
                page.wait_for_selector(selector, state="attached", timeout=wait)
            except Exception:
                pass
        if self.mode == "live":
            self._show(page)
        return page.content(), page.url

    def _show(self, page):
        """Let the audience see the specification block that is being read."""
        try:
            page.add_style_tag(content=HIGHLIGHT_CSS)
            page.locator(SPEC_TABLE).first.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(int(self.settings.demo_delay * 1000))

    def close(self):
        for action in (lambda: self.page and self.page.close(),
                       # Disconnect only; the presenter's Chrome stays open.
                       lambda: self.playwright and self.playwright.stop()):
            try:
                action()
            except Exception:
                pass
        self.page = self.browser = self.playwright = None
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
