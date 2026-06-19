"""Order repository — mocked store behind a clean interface.

Loads fake orders from app/data/orders.json. Tools call these methods rather
than touching data directly, so a real e-commerce backend can be swapped in
later without changing agent code.

M0 provides read access (get_order). Write methods (refund, cancel, etc.) are
stubbed and filled in at M3/M4.
"""
import json
from pathlib import Path

_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "orders.json"


class OrderRepository:
    def __init__(self, data_file: Path = _DATA_FILE):
        self._orders = {o["order_id"]: o for o in json.loads(data_file.read_text())}

    def get_order(self, order_id: str) -> dict | None:
        return self._orders.get(order_id)

    # TODO(M3/M4): process_refund, cancel_order, change_address, initiate_return.
