"""Serve the RFQ dashboard and its API on this computer."""
import argparse
import logging

from app.dashboard_api import serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        serve(port=args.port)  # localhost only: the data includes customer email addresses
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
