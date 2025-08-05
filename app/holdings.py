"""Simple persistent storage for user holdings.

The competition demo is stateless by default and does not persist any
executed orders.  To enable a holdings page that survives across API
calls, this module stores aggregated holdings in a JSON file.  Each
holding entry contains the quantity, average purchase price, the last
selected scenario and the user's reason for the purchase.  Additional
metadata such as sectors are derived elsewhere.

The storage format is a mapping from stock code to a dictionary:

```
{
    "005930": {
        "quantity": 10,
        "avg_price": 70000.0,
        "scenario": "basic",
        "reason": "장기 보유"
    },
    ...
}
```

The JSON file location can be overridden via the ``HOLDINGS_FILE``
environment variable.  By default it is stored under ``data/holdings.json``
relative to the project root.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict


# File used to persist holdings.  A relative path will be resolved
# relative to the current working directory.  You can override this
# location by setting the ``HOLDINGS_FILE`` environment variable.
HOLDINGS_FILE: str = os.getenv("HOLDINGS_FILE", "data/holdings.json")


def _ensure_dir(path: str) -> None:
    """Ensure that the parent directory of ``path`` exists."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)


def load_holdings() -> Dict[str, Any]:
    """Load holdings from disk.

    If the file does not exist or cannot be parsed, an empty
    dictionary is returned.
    """
    if not os.path.isfile(HOLDINGS_FILE):
        return {}
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_holdings(data: Dict[str, Any]) -> None:
    """Persist holdings to disk.

    The underlying directory will be created on first use.
    """
    _ensure_dir(HOLDINGS_FILE)
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_holding(symbol: str, qty: int, price: float, scenario: str, reason: str) -> None:
    """Add or update a holding.

    When a new order is executed this function should be called to
    accumulate the quantity and recompute the volume‑weighted average
    purchase price.  The scenario and reason associated with the most
    recent purchase are also stored.
    """
    if qty <= 0 or price <= 0:
        return
    holdings = load_holdings()
    entry = holdings.get(symbol)
    if entry:
        # compute new average price
        prev_qty = entry.get("quantity", 0)
        prev_avg_price = entry.get("avg_price", 0.0)
        total_qty = prev_qty + qty
        if total_qty > 0:
            avg_price = ((prev_avg_price * prev_qty) + (price * qty)) / total_qty
        else:
            avg_price = price
        entry["quantity"] = total_qty
        entry["avg_price"] = round(avg_price, 2)
        entry["scenario"] = scenario
        entry["reason"] = reason
    else:
        holdings[symbol] = {
            "quantity": qty,
            "avg_price": round(price, 2),
            "scenario": scenario,
            "reason": reason,
        }
    save_holdings(holdings)


# A simple static mapping from stock codes to sectors.  In a real
# application you would query a database or API to obtain this
# information.  The mapping here covers some common Korean large caps
# and a handful of US examples for demonstration.  Unknown codes map to
# "기타" (others).
SECTOR_MAP: Dict[str, str] = {
    # Korean semiconductor
    "005930": "반도체",
    "005935": "반도체",
    "000660": "반도체",
    "005380": "자동차",
    "035420": "인터넷",
    "035720": "인터넷",
    "051910": "배터리",
    # US examples
    "AAPL": "기술",
    "GOOGL": "기술",
    "TSLA": "자동차",
    "AMZN": "소비재",
    "KO": "음료",
}


def get_sector(symbol: str) -> str:
    """Return the sector name for a given stock code.

    Unknown symbols default to "기타" (others).
    """
    return SECTOR_MAP.get(symbol.upper(), "기타")