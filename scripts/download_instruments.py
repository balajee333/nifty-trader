"""Download and cache DhanHQ instrument master file."""

import csv
import io
import sys
from pathlib import Path

import httpx

INSTRUMENT_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"

MCX_COMMODITY_SYMBOLS = ["GOLDM", "CRUDEOILM", "NATURALGAS", "GOLD", "SILVER", "SILVERM"]


def download():
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "instruments.csv"

    print(f"Downloading instrument master from {INSTRUMENT_URL}...")
    resp = httpx.get(INSTRUMENT_URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    output_path.write_bytes(resp.content)
    print(f"Saved to {output_path}")

    rows = list(csv.DictReader(io.StringIO(resp.text)))

    # Count and show NIFTY FNO entries
    nifty_fno = [
        row for row in rows
        if row.get("SEM_TRADING_SYMBOL", "").startswith("NIFTY")
        and row.get("SEM_EXM_EXCH_ID") == "NSE"
        and row.get("SEM_SEGMENT") == "D"
    ]
    print(f"Found {len(nifty_fno)} NIFTY FNO instruments")

    # Count and show MCX OPTFUT entries
    mcx_optfut = [
        row for row in rows
        if row.get("SEM_EXM_EXCH_ID") == "MCX"
        and row.get("SEM_INSTRUMENT_NAME") == "OPTFUT"
    ]
    print(f"Found {len(mcx_optfut)} MCX OPTFUT instruments")

    # Show commodity breakdown
    for symbol in MCX_COMMODITY_SYMBOLS:
        matching = [
            r for r in mcx_optfut
            if r.get("SEM_TRADING_SYMBOL", "").startswith(symbol)
        ]
        if matching:
            print(f"  {symbol}: {len(matching)} option contracts")


def find_security_id(symbol: str, instrument_path: str | Path | None = None):
    """Find security IDs for a given commodity symbol from the instrument master.

    Useful for populating the instrument.security_id in settings.yaml.
    Looks for the underlying futures contract (FUTCOM) for the given symbol.
    """
    if instrument_path is None:
        instrument_path = OUTPUT_DIR / "instruments.csv"
    instrument_path = Path(instrument_path)

    if not instrument_path.exists():
        print(f"Instrument file not found: {instrument_path}")
        print("Run 'python scripts/download_instruments.py' first")
        return

    with open(instrument_path) as f:
        reader = csv.DictReader(f)
        matches = []
        for row in reader:
            trading_sym = row.get("SEM_TRADING_SYMBOL", "")
            exch = row.get("SEM_EXM_EXCH_ID", "")
            inst_name = row.get("SEM_INSTRUMENT_NAME", "")
            if (
                trading_sym.startswith(symbol)
                and exch == "MCX"
                and inst_name in ("FUTCOM", "OPTFUT")
            ):
                matches.append({
                    "security_id": row.get("SEM_SMST_SECURITY_ID"),
                    "symbol": trading_sym,
                    "instrument": inst_name,
                    "expiry": row.get("SEM_EXPIRY_DATE", ""),
                    "lot_size": row.get("SEM_LOT_UNITS", ""),
                })

    if not matches:
        print(f"No MCX instruments found for symbol: {symbol}")
        return

    # Show futures first, then options
    futures = [m for m in matches if m["instrument"] == "FUTCOM"]
    options = [m for m in matches if m["instrument"] == "OPTFUT"]

    print(f"\n--- {symbol} on MCX ---")
    if futures:
        print("Futures (use security_id for underlying):")
        for f in sorted(futures, key=lambda x: x["expiry"]):
            print(f"  ID={f['security_id']}  {f['symbol']}  expiry={f['expiry']}  lot={f['lot_size']}")
    print(f"Options: {len(options)} OPTFUT contracts available")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--find":
        symbol = sys.argv[2] if len(sys.argv) > 2 else "GOLDM"
        find_security_id(symbol)
    else:
        download()
