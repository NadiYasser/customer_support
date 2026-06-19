"""Order repository — mocked store behind a clean interface.

Loads fake orders from app/data/orders.json. Tools call these methods rather
than touching data directly, so a real e-commerce backend can be swapped in
later without changing agent code.

M0 provides read access (get_order). M3 adds the write methods (refund, cancel,
change address, initiate return).
"""
import json
from pathlib import Path

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
