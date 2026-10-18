import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

MODES = ("live", "background")
BOT_NAME = "FERG_GOAT_QUOTE"


@dataclass
class Settings:
    offline: bool = False
    browser: bool = True
    pdfs: bool = True
    quality: str = "rules"
    timeout: float = 12
    cdp_url: str = "http://127.0.0.1:9333"
    # live: visible Chrome on cdp_url for the audience; background: hidden Chrome started by the app.
    mode: str = "background"
    demo_delay: float = 2.0
    page_timeout: float = 30
    page_pause: float = 2.0
    background_port: int = 9334
    chrome_path: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            offline=os.getenv("RFQ_OFFLINE", "false").lower() == "true",
            browser=os.getenv("RFQ_BROWSER", "true").lower() == "true",
            pdfs=os.getenv("RFQ_PDFS", "true").lower() == "true",
            quality=os.getenv("RFQ_QUALITY", "rules"),
            timeout=float(os.getenv("RFQ_TIMEOUT", "12")),
            cdp_url=os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9333"),
            mode=os.getenv("RFQ_MODE", "background").lower(),
            demo_delay=float(os.getenv("RFQ_DEMO_DELAY", "2")),
            page_timeout=float(os.getenv("RFQ_PAGE_TIMEOUT", "30")),
            page_pause=float(os.getenv("RFQ_PAGE_PAUSE", "2")),
            background_port=int(os.getenv("RFQ_BACKGROUND_PORT", "9334")),
            chrome_path=os.getenv("CHROME_PATH", ""),
        )

    def describe(self):
        if self.offline:
            return "offline (catalog only, no network)"
        service = "product service, then " if os.getenv("RFQ_PRODUCT_API", "true").lower() == "true" else ""
        if not self.browser:
            return f"no browser ({service}ferguson.com over HTTPS, then PDF, then catalog)"
        return f"{self.mode} ({service}ferguson.com via Chrome, then PDF, then catalog)"
