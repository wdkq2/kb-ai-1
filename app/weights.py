from __future__ import annotations

from typing import List

from .schemas import PortfolioItem, WeightResult, WeightsRequest, WeightsResponse


# keywords that, when found in the reason, slightly boost allocation
KEYWORDS = ["핵심", "최우선", "강한확신", "장기"]


def calculate_weights(req: WeightsRequest, prices: dict[str, float]) -> WeightsResponse:
    """Allocate weights to portfolio items based on user hints and keyword boosts.

    The algorithm distributes equal weights across items, boosts those containing
    certain Korean keywords in the reason, then clips the weights to stay within
    10–40 percent and renormalizes. It also computes the initial and DCA cash
    allocations and limit price hints based off current prices.
    """
    n = len(req.items)
    if n == 0:
        return WeightsResponse(results=[])

    base = 1 / n
    weights: list[list[str, float]] = []
    for item in req.items:
        w = base
        if any(k in item.reason for k in KEYWORDS):
            w += 0.05
        weights.append([item.symbol, w])

    # normalize
    total = sum(w for _, w in weights)
    weights = [[sym, w / total] for sym, w in weights]

    # clip to the range 10–40 % to prevent too high or too low allocations
    clipped: list[list[str, float]] = []
    for sym, w in weights:
        w = max(0.10, min(0.40, w))
        clipped.append([sym, w])
    # renormalize
    total = sum(w for _, w in clipped)
    clipped = [[sym, w / total] for sym, w in clipped]

    results: List[WeightResult] = []
    for sym, w in clipped:
        price = prices.get(sym, 0)
        initial_cash = req.total_cash * w * req.initial_buy_ratio
        dca_cash = req.total_cash * w * (1 - req.initial_buy_ratio)
        limit_price = price * (1 - req.discount_rate) if price else 0
        results.append(
            WeightResult(
                symbol=sym,
                weight=round(w, 4),
                initial_buy_cash=round(initial_cash, 2),
                dca_cash=round(dca_cash, 2),
                limit_price_hint=round(limit_price, 2),
            )
        )

    return WeightsResponse(results=results)