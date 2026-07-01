"""One-off: push app/data/orders.json into the configured Google Sheet.

Run once to populate a fresh sheet so the live backend has data to read:

    python -m app.scripts.seed_sheet

It writes a header row matching the dict keys the tools expect, plus the two
extra columns the write methods fill (refunded_amount, shipping_address). `items`
is stored as a comma-joined string; SheetsOrderRepository._coerce splits it back
into a list on read.

Requires GOOGLE_SHEET_ID set in .env.dev and the service account (whose email is
in service_account.json) shared on the sheet with Editor access.
"""
import json
from pathlib import Path

import gspread

from app import config

_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "orders.json"

HEADERS = [
    "order_id", "customer", "items", "total", "status", "eta",
    "tracking_number", "refunded_amount", "shipping_address",
]


def _row(order: dict) -> list:
    return [
        order.get("order_id", ""),
        order.get("customer", ""),
        ", ".join(order.get("items", [])),
        order.get("total", ""),
        order.get("status", ""),
        order.get("eta", ""),
        order.get("tracking_number") or "",
        order.get("refunded_amount", ""),
        order.get("shipping_address", ""),
    ]


def main() -> None:
    if not config.GOOGLE_SHEET_ID:
        raise SystemExit("GOOGLE_SHEET_ID is not set in .env.dev")

    gc = gspread.service_account(filename=config.GOOGLE_SHEET_CREDENTIALS)
    ws = gc.open_by_key(config.GOOGLE_SHEET_ID).sheet1

    orders = json.loads(_DATA_FILE.read_text())
    rows = [HEADERS] + [_row(o) for o in orders]

    ws.clear()
    # Drop any leftover merged ranges from the old dashboard. Writing into a
    # merged block only fills its top-left cell and silently drops the rest, so
    # an unmerged grid is required for row/column writes to land correctly.
    ws.unmerge_cells(1, 1, ws.row_count, ws.col_count)
    # RAW: store values exactly as sent. Without this, Sheets parses them under
    # the spreadsheet's locale — e.g. a French-locale sheet reads 64.99 as
    # "64 thousand" (dot = thousands separator) and stores 6499. RAW avoids that.
    ws.update(rows, "A1", value_input_option="RAW")
    print(f"Seeded {len(orders)} orders into sheet {config.GOOGLE_SHEET_ID}.")


if __name__ == "__main__":
    main()
