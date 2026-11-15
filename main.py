import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI()

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
USE_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"

session = HTTP(
    testnet=USE_TESTNET,
    api_key=API_KEY,
    api_secret=API_SECRET,
)

class WebhookPayload(BaseModel):
    secret: str
    symbol: str
    action: str
    risk_pct: float = 2.5
    stop_distance: float = 0.0
    sl_price: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0

def ensure_leverage(symbol: str, leverage: str = "5"):
    try:
        session.set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=leverage,
            sellLeverage=leverage,
        )
    except Exception:
        pass

def get_usdt_balance() -> float:
    res = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    account_list = res.get("result", {}).get("list", [])
    if not account_list:
        return 0.0
    first_account = account_list[0]
    coins = first_account.get("coin", [])
    for c in coins:
        if c.get("coin") == "USDT":
            return float(c.get("walletBalance", 0.0))
    return 0.0

def get_open_position_qty(symbol: str) -> float:
    res = session.get_positions(category="linear", symbol=symbol)
    positions = res.get("result", {}).get("list", [])
    if not positions:
        return 0.0
    return float(positions[0].get("size", 0.0))

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "mode": "TESTNET" if USE_TESTNET else "REAL"}

@app.post("/webhook")
def receive_webhook(data: WebhookPayload):
    if not WEBHOOK_SECRET or data.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Nieprawidłowe hasło webhooka")

    try:
        symbol = data.symbol
        ensure_leverage(symbol, "5")

        if data.action in ["OPEN_LONG", "OPEN_SHORT"]:
            balance = get_usdt_balance()
            if balance <= 10:
                return {"status": "error", "message": f"Zbyt niskie saldo USDT: {balance}"}

            if data.stop_distance <= 0:
                return {"status": "error", "message": "Nieprawidłowa wartość stop_distance"}

            risk_usdt = balance * (data.risk_pct / 100.0)
            raw_qty = risk_usdt / data.stop_distance
            qty = max(0.001, round(raw_qty, 3))
            side = "Buy" if data.action == "OPEN_LONG" else "Sell"

            order = session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(round(data.sl_price, 1)),
                slTriggerBy="LastPrice",
            )
            return {
                "status": "opened",
                "side": side,
                "qty": qty,
                "balance_usdt": balance,
                "order": order,
            }

        elif data.action in ["CLOSE_LONG", "CLOSE_SHORT"]:
            current_qty = get_open_position_qty(symbol)
            if current_qty <= 0:
                return {"status": "ignored", "message": "Brak otwartej pozycji do zamknięcia"}

            close_side = "Sell" if data.action == "CLOSE_LONG" else "Buy"
            order = session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(current_qty),
                reduceOnly=True,
            )
            return {
                "status": "closed",
                "side": close_side,
                "qty": current_qty,
                "order": order,
            }

        return {"status": "ignored", "message": "Nieznana akcja"}

    except Exception as e:
        return {"status": "bybit_error", "details": str(e)}
