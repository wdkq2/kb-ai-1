from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
import hashlib

from .utils import load_env

# load environment variables from .env file if present
load_env()

logger = logging.getLogger(__name__)


class KISClient:
    """
    Wrapper around the Korea Investment & Securities (KIS) open API.

    This client is designed to work with both the virtual trading environment
    (모의투자) and the real trading environment. Credentials and configuration
    values are loaded from environment variables to avoid hard‑coding secrets.

    Attributes
    ----------
    base_url : str
        Base URL for the KIS API. Defaults to the virtual domain.
    appkey : str
        Application key issued by KIS. Loaded from the environment.
    appsecret : str
        Application secret issued by KIS. Loaded from the environment.
    cano : str
        Customer account number (account prefix). Required for order APIs.
    acnt_prdt_cd : str
        Account product code. Required for order APIs.
    custtype : str
        Customer type. Defaults to "P" (individual).
    mode : str
        Trading mode. "virtual" for paper trading, "real" for live trading.
    mock : bool
        If true, the client returns stubbed data instead of calling KIS.
    token : Optional[str]
        Cached access token.
    expires : datetime
        Expiry time of the current token.
    token_strategy : str
        Token TTL strategy. "short" caches the token for 24 hours; "long" for 90 days.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443"
        )
        self.appkey = os.getenv("KIS_APP_KEY", "")
        self.appsecret = os.getenv("KIS_APP_SECRET", "")
        self.cano = os.getenv("KIS_CANO", "")
        self.acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD", "")
        self.custtype = os.getenv("KIS_CUSTTYPE", "P")
        self.mode = os.getenv("KIS_MODE", "virtual")
        self.mock = os.getenv("KIS_MOCK", "0") == "1"
        self.token: Optional[str] = None
        self.expires: datetime = datetime.min
        self.token_strategy = os.getenv("TOKEN_TTL_STRATEGY", "short")

        # Configure retry and timeout settings for outbound HTTP calls.  Using a
        # persistent client with a transport that supports retries avoids
        # repeatedly creating new TCP connections and improves resiliency to
        # transient network errors.  These values can be tuned via the
        # HTTP_TIMEOUT and HTTP_RETRIES environment variables.  See README for
        # guidance.
        try:
            retries_env = int(os.getenv("HTTP_RETRIES", "3"))
        except ValueError:
            retries_env = 3
        try:
            timeout_env = float(os.getenv("HTTP_TIMEOUT", "10"))
        except ValueError:
            timeout_env = 10.0
        # HTTPX 0.28 provides AsyncHTTPTransport with retry support
        self._transport = httpx.AsyncHTTPTransport(retries=retries_env)
        # Create one client for the lifetime of this KISClient instance.  The
        # underlying transport manages connection pooling.
        self._client = httpx.AsyncClient(timeout=timeout_env, transport=self._transport)

    async def get_access_token(
        self, appkey: Optional[str] = None, appsecret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a bearer token from KIS.

        If a token is already cached and still valid, it will be returned.
        Otherwise a new token will be requested from the API using either the
        credentials passed as arguments or those loaded from the environment.
        """
        # override credentials if provided at runtime (e.g. via API call)
        if appkey:
            self.appkey = appkey
        if appsecret:
            self.appsecret = appsecret
        now = datetime.utcnow()
        # return cached token if it hasn't expired
        if self.token and now < self.expires:
            return {"access_token": self.token, "expires_at": self.expires}
        # if mock mode is enabled, return a dummy token
        if self.mock:
            self.token = "MOCK_TOKEN"
            ttl = 24 if self.token_strategy == "short" else 24 * 90
            self.expires = now + timedelta(hours=ttl - 1)
            return {"access_token": self.token, "expires_at": self.expires}
        # build request
        url = f"{self.base_url}/oauth2/tokenP"
        data = {"grant_type": "client_credentials", "appkey": self.appkey, "appsecret": self.appsecret}
        headers = {"content-type": "application/json"}
        resp = await self._client.post(url, json=data, headers=headers)
        if resp.status_code != 200:
            # log and raise an error so the API endpoint can report a sensible message
            logger.error("token error %s %s", resp.status_code, resp.text)
            raise httpx.HTTPStatusError("token error", request=resp.request, response=resp)
        res = resp.json()
        # The API returns the token and its validity. We ignore expires_in and use our own TTL strategy.
        self.token = res.get("access_token")
        ttl = 24 if self.token_strategy == "short" else 24 * 90
        self.expires = now + timedelta(hours=ttl - 1)
        return {"access_token": self.token, "expires_at": self.expires}

    def hashkey(self, body: Dict[str, Any]) -> str:
        """Compute a SHA256 hash of the request body.

        KIS requires a hash key for POST requests to prevent tampering.
        """
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def headers_for(self, tr_id: str, is_post: bool = False, body: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Prepare HTTP headers for a given transaction ID.

        Parameters
        ----------
        tr_id : str
            Transaction identifier from the KIS API documentation. Determines the route and request semantics.
        is_post : bool, optional
            True if this will be a POST request, in which case the hashkey header is added.
        body : dict[str, Any] | None, optional
            Request body used to compute the hashkey for POST requests.
        """
        token_info = await self.get_access_token()
        headers = {
            "authorization": f"Bearer {token_info['access_token']}",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": tr_id,
            "custtype": self.custtype,
            "content-type": "application/json; charset=UTF-8",
        }
        if is_post and body is not None:
            headers["hashkey"] = self.hashkey(body)
        return headers

    async def inquire_daily_price(self, symbol: str, start: str, end: str) -> Dict[str, Any]:
        """Retrieve daily price information for a given symbol.

        The KIS API returns OHLCV data. When mock mode is enabled, a simple
        synthesized price based on the symbol is returned.
        """
        if self.mock:
            # return deterministic mock data to facilitate testing without network calls
            price = 50000 + (int(symbol[-2:]) * 10)
            today = datetime.today().strftime("%Y%m%d")
            return {
                "output2": [
                    {
                        "stck_bsop_date": today,
                        "stck_oprc": price,
                        "stck_hgpr": price,
                        "stck_lwpr": price,
                        "stck_clpr": price,
                        "acml_vol": 0,
                    }
                ]
            }
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        params = {
            "fid_cond_mrkt_div_code": "J",  # 주식 (코스피/코스닥)
            "fid_input_iscd": symbol,
            "fid_period_div_code": "D",  # daily
            "fid_org_adj_prc": "0",
        }
        headers = await self.headers_for("FHKST01010400")
        resp = await self._client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            logger.error("quote error %s %s", resp.status_code, resp.text)
            raise httpx.HTTPStatusError("quote error", request=resp.request, response=resp)
        return resp.json()

    async def order_cash(self, pdno: str, qty: int, price: str, side: str, ord_dvsn: str) -> Dict[str, Any]:
        """Place a cash order for a domestic stock.

        Parameters
        ----------
        pdno : str
            Product number (stock code).
        qty : int
            Quantity to order.
        price : str
            Price per unit; "0" for market orders.
        side : str
            "buy" or "sell".
        ord_dvsn : str
            Order type code (01=시장가, 00=지정가, etc.).
        """
        tr_base = "TTTC" if self.mode == "real" else "VTTC"
        tr_id = f"{tr_base}0802U" if side == "buy" else f"{tr_base}0801U"
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": pdno,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": price,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        if self.mock:
            # return the request payload for introspection in mock mode
            return {"mock": True, "tr_id": tr_id, "body": body}
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = await self.headers_for(tr_id, is_post=True, body=body)
        resp = await self._client.post(url, json=body, headers=headers)
        if resp.status_code != 200:
            logger.error("order error %s %s", resp.status_code, resp.text)
            raise httpx.HTTPStatusError("order error", request=resp.request, response=resp)
        return resp.json()


# instantiate a singleton client for use in the API
kis_client = KISClient()