"""Client minimal pour l'API Alpaca, VERROUILLÉ sur le compte de démonstration.

L'adresse du compte réel n'apparaît nulle part dans ce code, et le client
refuse de démarrer si on lui en donne une autre que celle du « paper trading ».
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

PAPER_URL = "https://paper-api.alpaca.markets"


class BrokerError(RuntimeError):
    pass


class AlpacaPaper:
    def __init__(self, key: str, secret: str, base_url: str = PAPER_URL, timeout: int = 20):
        if base_url.rstrip("/") != PAPER_URL:
            raise BrokerError("Sécurité : ce robot ne parle qu'au compte de démonstration Alpaca.")
        if not key or not secret:
            raise BrokerError("Clés Alpaca manquantes (secrets ALPACA_API_KEY / ALPACA_SECRET_KEY).")
        self.base = PAPER_URL
        self.timeout = timeout
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                         "Content-Type": "application/json"}

    def _req(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise BrokerError(f"{method} {path} -> HTTP {e.code} : {e.read().decode(errors='replace')[:300]}")

    # -------- lecture
    def clock(self) -> dict:
        return self._req("GET", "/v2/clock")

    def account(self) -> dict:
        return self._req("GET", "/v2/account")

    def positions(self) -> dict[str, float]:
        return {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/v2/positions")}

    def order(self, order_id: str) -> dict:
        return self._req("GET", f"/v2/orders/{order_id}")

    # -------- écriture (compte de démonstration uniquement)
    def submit(self, symbol: str, qty: int, side: str) -> dict:
        assert side in ("buy", "sell") and qty > 0
        return self._req("POST", "/v2/orders", {
            "symbol": symbol, "qty": str(int(qty)), "side": side,
            "type": "market", "time_in_force": "day",
        })

    def wait_filled(self, order_id: str, timeout_s: int = 90) -> dict:
        deadline = time.time() + timeout_s
        o = self.order(order_id)
        while o["status"] not in ("filled", "canceled", "expired", "rejected") and time.time() < deadline:
            time.sleep(3)
            o = self.order(order_id)
        return o
