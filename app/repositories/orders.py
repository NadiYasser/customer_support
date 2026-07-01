"""Order repository — swappable store behind a clean interface.

Two backends live here, side by side, exposing the SAME method surface:

- OrderRepository       — loads fake orders from app/data/orders.json (the mock).
- SheetsOrderRepository — reads/writes a live Google Sheet via gspread.

Tools call these methods (get_order, process_refund, ...) and never touch data
directly, so we can switch backends by changing ONE factory call — no agent or
tool code changes. That's the whole point of the interface. get_order_repository()
picks the backend from config at startup.

M0 provides read access (get_order). M3 adds the write methods (refund, cancel,
change address, initiate return). Google Sheet backend added later.
"""
import json
from pathlib import Path

from app import config

_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "orders.json"


class OrderRepository:
    def __init__(self, data_file: Path = _DATA_FILE):
        self._orders = {o["order_id"]: o for o in json.loads(data_file.read_text())}

    def get_order(self, order_id: str) -> dict | None:
        return self._orders.get(order_id)

    # Write methods. These mutate the in-memory dict only — fine for a learning
    # build. A real backend would persist and return richer results; the tool
    # layer above wouldn't change.

    def process_refund(self, order_id: str, amount: float) -> dict | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        order["status"] = "refunded"
        order["refunded_amount"] = amount
        return order

    def cancel_order(self, order_id: str) -> dict | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        order["status"] = "cancelled"
        return order

    def change_address(self, order_id: str, address: str) -> dict | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        order["shipping_address"] = address
        return order

    def initiate_return(self, order_id: str) -> dict | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        order["status"] = "return_initiated"
        return order


class SheetsOrderRepository:
    """Live Google Sheet backend — same method surface as OrderRepository.

    Row 1 of the sheet is the header; column names must match the dict keys the
    tools read: order_id, customer, items, total, status, eta, tracking_number.
    Write methods (refund/cancel/...) also write the columns refunded_amount and
    shipping_address, so add those headers too (they can start empty).

    Reads are LIVE: every get_order() call fetches the sheet fresh, so an edit
    made in the browser shows up on the next lookup with no restart. The cost is
    a ~0.5-1s API round-trip per read and exposure to gspread's rate limits — a
    deliberate trade we chose for always-current data in this learning build.
    """

    # Columns we coerce out of the sheet's all-strings into real Python types.
    _FLOAT_FIELDS = ("total", "refunded_amount")

    def __init__(self, sheet_id: str, credentials_file: str):
        import gspread  # local import so the JSON backend needs no gspread installed
        from gspread.utils import rowcol_to_a1

        self._rowcol_to_a1 = rowcol_to_a1
        self._gc = gspread.service_account(filename=credentials_file)
        # .sheet1 is the first tab; switch to .worksheet("name") for a named tab.
        self._ws = self._gc.open_by_key(sheet_id).sheet1

    def _coerce(self, row: dict) -> dict:
        """Sheets returns every cell as a string. Restore the types the tools
        expect: total/refunded_amount as float, items as a list, empty tracking
        as None — so the order dict matches what orders.json produced."""
        order = dict(row)
        order["order_id"] = str(order.get("order_id", "")).strip()
        for f in self._FLOAT_FIELDS:
            if order.get(f) not in (None, ""):
                order[f] = float(order[f])
        if isinstance(order.get("items"), str):
            order["items"] = [i.strip() for i in order["items"].split(",") if i.strip()]
        if not order.get("tracking_number"):
            order["tracking_number"] = None
        return order

    def _find_row(self, order_id: str) -> int | None:
        """Return the 1-based sheet row for order_id, or None. Row 1 is the
        header, so data starts at row 2 — hence the +2 offset."""
        ids = self._ws.col_values(self._col_index("order_id"))
        for i, value in enumerate(ids[1:]):  # skip header
            if str(value).strip() == order_id:
                return i + 2
        return None

    def _col_index(self, name: str) -> int:
        """1-based column number for a header name (gspread cells are 1-based)."""
        return self._ws.row_values(1).index(name) + 1

    def get_order(self, order_id: str) -> dict | None:
        # Live read: pull all rows as dicts keyed by header, find the match.
        # UNFORMATTED_VALUE returns the underlying number (64.99), not the
        # locale-formatted display string ("64,99" on a French sheet) which
        # would otherwise be mis-parsed on coercion.
        records = self._ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
        for row in records:
            if str(row.get("order_id", "")).strip() == order_id:
                return self._coerce(row)
        return None

    def _update_cell(self, order_id: str, column: str, value) -> dict | None:
        row = self._find_row(order_id)
        if row is None:
            return None
        # RAW so Sheets stores the value verbatim instead of reparsing it under
        # the sheet's locale (a French-locale sheet would turn 64.99 into 6499).
        cell = self._rowcol_to_a1(row, self._col_index(column))
        self._ws.update([[value]], cell, value_input_option="RAW")
        return self.get_order(order_id)

    def process_refund(self, order_id: str, amount: float) -> dict | None:
        if self._update_cell(order_id, "status", "refunded") is None:
            return None
        return self._update_cell(order_id, "refunded_amount", amount)

    def cancel_order(self, order_id: str) -> dict | None:
        return self._update_cell(order_id, "status", "cancelled")

    def change_address(self, order_id: str, address: str) -> dict | None:
        return self._update_cell(order_id, "shipping_address", address)

    def initiate_return(self, order_id: str) -> dict | None:
        return self._update_cell(order_id, "status", "return_initiated")


def get_order_repository():
    """Pick the order backend from config, once, at import time.

    If GOOGLE_SHEET_ID is set we use the live sheet; otherwise we fall back to
    the local JSON mock. Tools call this instead of constructing a repository
    directly, so the choice lives in exactly one place.
    """
    if config.GOOGLE_SHEET_ID:
        return SheetsOrderRepository(
            config.GOOGLE_SHEET_ID, config.GOOGLE_SHEET_CREDENTIALS
        )
    return OrderRepository()
