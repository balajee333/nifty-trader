"""Download and cache DhanHQ instrument master file."""

import csv
import io
import sys
from pathlib import Path

import httpx

INSTRUMENT_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"


def download():
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "instruments.csv"

    print(f"Downloading instrument master from {INSTRUMENT_URL}...")
    resp = httpx.get(INSTRUMENT_URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    output_path.write_bytes(resp.content)
    print(f"Saved to {output_path}")

    # Count and show NIFTY FNO entries
    reader = csv.DictReader(io.StringIO(resp.text))
    nifty_fno = [
        row for row in reader
        if row.get("SEM_TRADING_SYMBOL", "").startswith("NIFTY")
        and row.get("SEM_EXM_EXCH_ID") == "NSE"
        and row.get("SEM_SEGMENT") == "D"
    ]
    print(f"Found {len(nifty_fno)} NIFTY FNO instruments")


if __name__ == "__main__":
    download()
