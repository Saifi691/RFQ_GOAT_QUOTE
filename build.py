"""Build an RFQ workbook and a reply draft from a MIME email."""
import argparse
import logging
from email import policy
from email.parser import BytesParser
from pathlib import Path

from app import store
from app.browser import BrowserUnavailable
from app.config import Settings
from app.options import add_source_options, apply_source_options
from app.pipeline import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", nargs="?", default="emails/email-1-ids-in-body.eml")
    parser.add_argument("--out", type=Path, default=Path("out"))
    add_source_options(parser)
    args = parser.parse_args()
    settings = apply_source_options(args, Settings.from_env())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    email_path = Path(args.email)
    request_id = None
    try:
        raw = email_path.read_bytes()
        request_id = store.start("file", BytesParser(policy=policy.default).parsebytes(raw), settings)
        result = build(raw, args.out / email_path.stem, settings)
        store.built(request_id, result)
    except (ValueError, OSError, BrowserUnavailable) as exc:
        store.failed(request_id, f"{type(exc).__name__}: {exc}")
        parser.exit(1, f"RFQ failed: {exc}\n")
    print(f"Workbook: {result['workbook']}\nReply draft: {result['reply']}")
    print(f"Processed {result['summary']['Products Processed']}; Not Found {result['summary']['Not Found']}")


if __name__ == "__main__":
    main()
