from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

from enum import Enum


class TokenRequest(BaseModel):
    appkey: Optional[str] = None
    appsecret: Optional[str] = None
    mode: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    expires_at: datetime


class QuoteRequest(BaseModel):
    symbol: str
    start: str
    end: str


class OHLCV(BaseModel):
    date: str = Field(..., description="YYYYMMDD")
    open: float
    high: float
    low: float
    close: float
    volume: float


class QuoteResponse(BaseModel):
    symbol: str
    prices: List[OHLCV]


class PortfolioItem(BaseModel):
    symbol: str
    reason: str


class WeightsRequest(BaseModel):
    total_cash: float = Field(..., gt=0)
    items: List[PortfolioItem]
    initial_buy_ratio: float = 0.5
    discount_rate: float = 0.03


class WeightResult(BaseModel):
    symbol: str
    weight: float
    initial_buy_cash: float
    dca_cash: float
    limit_price_hint: float


class WeightsResponse(BaseModel):
    results: List[WeightResult]


class OrderPreviewRequest(WeightsResponse):
    total_cash: float


class OrderPreviewItem(BaseModel):
    symbol: str
    weight: float
    price: float
    qty_market: int
    qty_limit: int
    limit_price: float
    cash_needed: float


class OrderPreviewResponse(BaseModel):
    items: List[OrderPreviewItem]
    total_cash_needed: float


class OrderExecuteRequest(OrderPreviewResponse):
    pass


class OrderResult(BaseModel):
    symbol: str
    order_type: str
    qty: int
    price: float
    response: dict


class OrderExecuteResponse(BaseModel):
    results: List[OrderResult]

# === Scenario trading models ===

class ScenarioType(str, Enum):
    """Enumeration of supported scenario identifiers.

    The values correspond to the strings used on the front end.  See
    ``app/scenarios.py`` for the logic associated with each scenario.
    """

    basic = "basic"
    confident = "confident"
    chase = "chase"
    conservative = "conservative"


class ScenarioRequest(BaseModel):
    """Request body for scenario order planning.

    Parameters
    ----------
    symbol : str
        Stock code (e.g. "005930").
    total_cash : float
        Total amount of cash available for this trade.
    scenario : ScenarioType
        One of the defined scenarios.
    reason : str
        User's description of why they are entering the trade.
    """

    symbol: str
    total_cash: float
    scenario: ScenarioType
    reason: str


class ScenarioOrderItem(BaseModel):
    """A single order generated for a scenario plan."""

    order_type: str  # "market" or "limit"
    qty: int
    price: float  # 0 for market orders, limit price otherwise
    ratio: float  # fraction of total cash allocated to this order


class ScenarioOrderPlan(BaseModel):
    """A fully computed scenario plan ready for preview or execution."""

    symbol: str
    scenario: ScenarioType
    total_cash: float
    price: float  # latest market price used for calculations
    reason: str
    orders: List[ScenarioOrderItem]


# === Holdings and portfolio models ===

class Holding(BaseModel):
    """Representation of a held position along with derived metadata."""

    symbol: str
    quantity: int
    avg_price: float
    scenario: Optional[ScenarioType] = None
    reason: Optional[str] = None
    sector: str
    current_price: Optional[float] = None
    value: Optional[float] = None


class HoldingsResponse(BaseModel):
    """Response model for the holdings API."""

    holdings: List[Holding]
    sector_distribution: Dict[str, float]


# === Report models ===

class ReportRequest(BaseModel):
    """Request body for generating a report.  If ``symbol`` is omitted,
    the report covers the entire portfolio."""

    symbol: Optional[str] = None


class ReportResponse(BaseModel):
    """A simple wrapper for a generated textual report."""

    report: str