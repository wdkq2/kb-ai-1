import json
import requests

BASE = "http://localhost:8000"

# get token (mock)
requests.post(f"{BASE}/api/kis/token", json={"appkey": "demo", "appsecret": "demo", "mode": "virtual"})

payload = {
    "total_cash": 1000000,
    "items": [
        {"symbol": "005930", "reason": "핵심 보유"},
        {"symbol": "000660", "reason": "장기 투자"},
    ],
    "initial_buy_ratio": 0.5,
    "discount_rate": 0.03,
}
weights = requests.post(f"{BASE}/api/portfolio/weights", json=payload).json()
preview = requests.post(f"{BASE}/api/orders/preview", json={"results": weights["results"], "total_cash": payload["total_cash"]}).json()
execute = requests.post(f"{BASE}/api/orders/execute", json=preview).json()
print(json.dumps(execute, indent=2, ensure_ascii=False))