from __future__ import annotations

import logging
import os
from math import floor
from typing import List

from .utils import load_env
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .schemas import (
    OrderExecuteRequest,
    OrderExecuteResponse,
    OrderPreviewItem,
    OrderPreviewRequest,
    OrderPreviewResponse,
    QuoteResponse,
    TokenRequest,
    TokenResponse,
    WeightsRequest,
    WeightsResponse,
    ScenarioRequest,
    ScenarioOrderPlan,
    ScenarioType,
    ScenarioOrderItem,
    Holding,
    HoldingsResponse,
    ReportRequest,
    ReportResponse,
)
from .weights import calculate_weights
from .scenarios import calculate_plan
from .holdings import load_holdings, add_holding, get_sector
from .kis_client import kis_client

# load environment variables at startup
load_env()

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()

# serve static assets (if any) from the templates directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def index(request: Request):
    """Serve the main single‑page application."""
    return templates.TemplateResponse("index.html", {"request": request})


# Additional pages for scenario trading and portfolio overview
@app.get("/scenario")
async def scenario_page(request: Request):
    """Serve the scenario trading page."""
    return templates.TemplateResponse("scenario.html", {"request": request})


@app.get("/portfolio")
async def portfolio_page(request: Request):
    """Serve the portfolio overview page."""
    return templates.TemplateResponse("portfolio.html", {"request": request})


@app.get("/api/health")
async def health():
    """Basic health check returning current mode and base URL."""
    return {"mode": kis_client.mode, "base_url": kis_client.base_url}


@app.post("/api/kis/token", response_model=TokenResponse)
async def api_token(req: TokenRequest):
    """Issue a new token using the provided credentials or fallback values."""
    # allow overriding the client mode (virtual vs real) at runtime
    if req.mode:
        kis_client.mode = req.mode
    try:
        data = await kis_client.get_access_token(req.appkey, req.appsecret)
    except Exception as e:  # broad catch to return json
        raise HTTPException(status_code=500, detail=str(e))
    return TokenResponse(access_token=data["access_token"], expires_at=data["expires_at"])


# === Scenario trading APIs ===

@app.post("/api/scenario/preview", response_model=ScenarioOrderPlan)
async def scenario_preview(req: ScenarioRequest):
    """Generate a scenario order plan for a single stock.

    This endpoint fetches the latest price for ``req.symbol`` and uses
    ``calculate_plan`` to build a list of market and limit orders
    according to the selected scenario.
    """
    try:
        data = await kis_client.inquire_daily_price(req.symbol, "", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    price = float(data.get("output2", [{}])[0].get("stck_clpr", 0))
    if price <= 0:
        raise HTTPException(status_code=400, detail="Invalid price for symbol")
    try:
        plan = calculate_plan(req, price)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return plan


@app.post("/api/scenario/execute", response_model=OrderExecuteResponse)
async def scenario_execute(plan: ScenarioOrderPlan):
    """Execute a scenario order plan and record the resulting holding.

    Each order in the plan is executed either as a market or limit
    order.  After placing the order the holding record is updated to
    accumulate quantity and average price.  The response mirrors
    ``/api/orders/execute`` but is tailored to a single stock.
    """
    results = []
    for order in plan.orders:
        if order.qty <= 0:
            continue
        try:
            if order.order_type == "market":
                resp = await kis_client.order_cash(
                    pdno=plan.symbol, qty=order.qty, price="0", side="buy", ord_dvsn="01"
                )
                price_used = plan.price
            else:
                resp = await kis_client.order_cash(
                    pdno=plan.symbol,
                    qty=order.qty,
                    price=str(order.price),
                    side="buy",
                    ord_dvsn="00",
                )
                price_used = order.price
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        # update holdings after successful order
        add_holding(plan.symbol, order.qty, price_used, plan.scenario.value, plan.reason)
        results.append(
            {
                "symbol": plan.symbol,
                "order_type": order.order_type,
                "qty": order.qty,
                "price": price_used,
                "response": resp,
            }
        )
    return OrderExecuteResponse(results=results)


# === Holdings and report APIs ===

@app.get("/api/holdings", response_model=HoldingsResponse)
async def api_holdings() -> HoldingsResponse:
    """Return a summary of all held positions and sector distribution.

    For each held symbol the current price is fetched, the market
    value is computed, and a sector is assigned.  The sector
    distribution is expressed as a percentage of the total portfolio
    value.
    """
    holdings_raw = load_holdings()
    holdings: List[Holding] = []
    total_value: float = 0.0
    # First accumulate the data and compute total value
    for symbol, info in holdings_raw.items():
        qty = int(info.get("quantity", 0))
        avg_price = float(info.get("avg_price", 0.0))
        scenario = info.get("scenario")
        reason = info.get("reason")
        # fetch current price
        try:
            data = await kis_client.inquire_daily_price(symbol, "", "")
            price = float(data.get("output2", [{}])[0].get("stck_clpr", 0))
        except Exception:
            price = 0.0
        value = price * qty
        total_value += value
        holdings.append(
            Holding(
                symbol=symbol,
                quantity=qty,
                avg_price=avg_price,
                scenario=scenario,
                reason=reason,
                sector=get_sector(symbol),
                current_price=round(price, 2) if price else None,
                value=round(value, 2) if value else None,
            )
        )
    # Compute sector distribution
    sector_values: Dict[str, float] = {}
    for h in holdings:
        if h.value is None:
            continue
        sector_values[h.sector] = sector_values.get(h.sector, 0.0) + h.value
    sector_distribution: Dict[str, float] = {}
    for sector, val in sector_values.items():
        sector_distribution[sector] = round((val / total_value) * 100, 2) if total_value > 0 else 0.0
    return HoldingsResponse(holdings=holdings, sector_distribution=sector_distribution)


@app.post("/api/report", response_model=ReportResponse)
async def api_report(req: ReportRequest) -> ReportResponse:
    """Generate a textual investment report for a single holding or the full portfolio.

    The report is generated by constructing a prompt containing the
    relevant data (symbol, scenario, reason, quantity, prices) and
    optionally sending it to the OpenAI API.  If no API key is
    configured or if the API call fails, a simple summary report is
    returned instead.
    """
    # Gather portfolio information
    holdings_raw = load_holdings()
    if req.symbol:
        # report for a single symbol
        if req.symbol not in holdings_raw:
            raise HTTPException(status_code=404, detail="Symbol not found in holdings")
        symbols = [req.symbol]
    else:
        symbols = list(holdings_raw.keys())
    # Build context for the report
    context_lines: List[str] = []
    total_value = 0.0
    for symbol in symbols:
        info = holdings_raw[symbol]
        qty = int(info.get("quantity", 0))
        avg_price = float(info.get("avg_price", 0.0))
        scenario = info.get("scenario")
        reason = info.get("reason")
        try:
            data = await kis_client.inquire_daily_price(symbol, "", "")
            price = float(data.get("output2", [{}])[0].get("stck_clpr", 0))
        except Exception:
            price = 0.0
        value = qty * price
        total_value += value
        context_lines.append(
            f"종목 {symbol}: 보유수량 {qty}주, 평균매수가 {avg_price:.2f}원, 현재가 {price:.2f}원, 시나리오 {scenario}, 매매이유 {reason}, 평가금액 {value:.2f}원"
        )
    portfolio_summary = f"총 평가금액: {total_value:.2f}원"
    # Compose prompt for OpenAI
    prompt = (
        "아래 투자 포트폴리오 정보를 바탕으로 투자 보고서를 작성해 주세요. "
        "종목별 투자 이유와 시나리오를 요약하고 향후 전망과 리스크 요인도 함께 서술해 주세요.\n\n"
        + "\n".join(context_lines)
        + "\n\n"
        + portfolio_summary
    )
    # Try to call OpenAI if API key is provided
    report_text: str
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            import openai

            openai.api_key = api_key
            response = await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7,
            )
            report_text = response.choices[0].message.content.strip()
        except Exception:
            # fallback to simple report
            report_text = "\n".join(context_lines) + "\n" + portfolio_summary
    else:
        # no API key – return a basic report
        report_text = "\n".join(context_lines) + "\n" + portfolio_summary
    return ReportResponse(report=report_text)


@app.get("/api/quotes/daily", response_model=QuoteResponse)
async def quotes_daily(symbol: str, start: str, end: str):
    """Return a list of OHLCV entries for the given symbol and date range."""
    try:
        data = await kis_client.inquire_daily_price(symbol, start, end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    prices = [
        {
            "date": item.get("stck_bsop_date"),
            "open": float(item.get("stck_oprc")),
            "high": float(item.get("stck_hgpr")),
            "low": float(item.get("stck_lwpr")),
            "close": float(item.get("stck_clpr")),
            "volume": float(item.get("acml_vol")),
        }
        for item in data.get("output2", [])
    ]
    return QuoteResponse(symbol=symbol, prices=prices)


@app.post("/api/portfolio/weights", response_model=WeightsResponse)
async def portfolio_weights(req: WeightsRequest):
    """Calculate recommended weights for a portfolio.

    Prices are fetched via the client and used to compute initial and DCA cash.
    """
    prices: dict[str, float] = {}
    for item in req.items:
        try:
            data = await kis_client.inquire_daily_price(item.symbol, "", "")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        price = float(data.get("output2", [{}])[0].get("stck_clpr", 0))
        prices[item.symbol] = price
    result = calculate_weights(req, prices)
    return result


@app.post("/api/orders/preview", response_model=OrderPreviewResponse)
async def order_preview(req: OrderPreviewRequest):
    """Generate a preview of market and limit orders from weight results."""
    items: List[OrderPreviewItem] = []
    total_needed = 0.0
    for r in req.results:
        try:
            data = await kis_client.inquire_daily_price(r.symbol, "", "")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        price = float(data.get("output2", [{}])[0].get("stck_clpr", 0))
        qty_market = floor(r.initial_buy_cash / price) if price else 0
        qty_limit = floor(r.dca_cash / r.limit_price_hint) if r.limit_price_hint else 0
        cash = qty_market * price + qty_limit * r.limit_price_hint
        total_needed += cash
        items.append(
            OrderPreviewItem(
                symbol=r.symbol,
                weight=r.weight,
                price=price,
                qty_market=qty_market,
                qty_limit=qty_limit,
                limit_price=r.limit_price_hint,
                cash_needed=round(cash, 2),
            )
        )
    return OrderPreviewResponse(items=items, total_cash_needed=round(total_needed, 2))


@app.post("/api/orders/execute", response_model=OrderExecuteResponse)
async def order_execute(req: OrderExecuteRequest):
    """Execute the market and limit orders defined in a preview request."""
    results = []
    for item in req.items:
        try:
            if item.qty_market > 0:
                resp_market = await kis_client.order_cash(
                    pdno=item.symbol, qty=item.qty_market, price="0", side="buy", ord_dvsn="01"
                )
                results.append(
                    {
                        "symbol": item.symbol,
                        "order_type": "market",
                        "qty": item.qty_market,
                        "price": 0,
                        "response": resp_market,
                    }
                )
            if item.qty_limit > 0:
                resp_limit = await kis_client.order_cash(
                    pdno=item.symbol,
                    qty=item.qty_limit,
                    price=str(item.limit_price),
                    side="buy",
                    ord_dvsn="00",
                )
                results.append(
                    {
                        "symbol": item.symbol,
                        "order_type": "limit",
                        "qty": item.qty_limit,
                        "price": item.limit_price,
                        "response": resp_limit,
                    }
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return OrderExecuteResponse(results=results)