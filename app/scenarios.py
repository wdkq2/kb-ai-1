"""Scenario based order planning.

This module defines simple preset trading scenarios and provides a function
to compute a list of orders for a single stock given a total amount of cash.

The scenarios are intentionally kept simple so that they can be encoded as a
combination of market and limit orders without any additional monitoring
infrastructure. Each scenario divides the available capital into one or more
tranches and assigns each tranche to either a market order executed
immediately at the current price or a limit order placed at a price
relative to the current price. The limit prices are expressed as a
percentage premium or discount from the current price.

The four supported scenarios are:

* ``basic`` (기본형): 50 % of cash is invested at market immediately and the
  remaining 50 % is placed as a limit order 3 % below the current price.
* ``confident`` (확신형): 100 % of cash is invested at market immediately.
* ``chase`` (추격매수형): 30 % is invested at market immediately, 30 % is
  placed as a limit order 5 % above the current price and the remaining
  40 % is placed as a limit order 10 % above the current price.  This
  reflects a strategy of adding to a position if the price rises.
* ``conservative`` (보수형): 30 % is invested at market immediately, 20 % is
  placed as a limit order 3 % below the current price and the remaining
  50 % is placed as a limit order 6 % below the current price.  This
  reflects a strategy of adding to a position only if the price falls.

To add or modify scenarios, edit the ``SCENARIO_DEFINITIONS`` mapping below.
"""

from __future__ import annotations

from math import floor
from typing import Dict, List, Tuple

from .schemas import (
    ScenarioType,
    ScenarioRequest,
    ScenarioOrderItem,
    ScenarioOrderPlan,
)


# Each entry defines a list of (ratio, price_offset) pairs.  A ratio is
# expressed as a fraction of the total cash (e.g. 0.5 for 50 %).  A
# ``price_offset`` of ``None`` means the tranche should be executed as a
# market order at the current price.  Otherwise the order is a limit
# order with the limit price calculated as ``current_price * (1 + price_offset)``.
SCENARIO_DEFINITIONS: Dict[ScenarioType, List[Tuple[float, float | None]]] = {
    ScenarioType.basic: [
        (0.5, None),  # 50 % market
        (0.5, -0.03),  # 50 % limit 3 % below
    ],
    ScenarioType.confident: [
        (1.0, None),  # 100 % market
    ],
    ScenarioType.chase: [
        (0.3, None),   # 30 % market
        (0.3, 0.05),   # 30 % limit 5 % above
        (0.4, 0.10),   # 40 % limit 10 % above
    ],
    ScenarioType.conservative: [
        (0.3, None),   # 30 % market
        (0.2, -0.03),  # 20 % limit 3 % below
        (0.5, -0.06),  # 50 % limit 6 % below
    ],
}


def calculate_plan(req: ScenarioRequest, current_price: float) -> ScenarioOrderPlan:
    """Compute a set of orders for the given scenario and stock price.

    Parameters
    ----------
    req : ScenarioRequest
        The user request containing the symbol, total cash, chosen scenario and reason.
    current_price : float
        The latest price of the stock, used to compute limit prices and
        quantities. If zero or negative, a ``ValueError`` is raised.

    Returns
    -------
    ScenarioOrderPlan
        A plan containing the list of orders with quantity and prices rounded to
        two decimal places where appropriate.
    """
    if current_price <= 0:
        raise ValueError("Invalid current price")

    definitions = SCENARIO_DEFINITIONS.get(req.scenario)
    if not definitions:
        raise ValueError(f"Unknown scenario {req.scenario}")

    orders: List[ScenarioOrderItem] = []
    for ratio, offset in definitions:
        cash = req.total_cash * ratio
        # Determine limit price; None implies a market order
        if offset is None:
            limit_price = 0.0
            price_for_qty = current_price
            order_type = "market"
        else:
            limit_price = round(current_price * (1 + offset), 2)
            price_for_qty = limit_price
            order_type = "limit"
        # Floor the quantity to avoid fractional shares
        qty = floor(cash / price_for_qty) if price_for_qty > 0 else 0
        orders.append(
            ScenarioOrderItem(
                order_type=order_type,
                qty=qty,
                price=limit_price,
                ratio=ratio,
            )
        )

    return ScenarioOrderPlan(
        symbol=req.symbol,
        scenario=req.scenario,
        total_cash=req.total_cash,
        price=round(current_price, 2),
        reason=req.reason,
        orders=orders,
    )