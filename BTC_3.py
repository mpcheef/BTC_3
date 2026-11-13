import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pybit.unified_trading import HTTP

app = FastAPI()

# Pobieranie kluczy ze zmiennych środowiskowych na Render
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "MOJE_TAJNE_HASLO_123")
USE_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"  # Domyślnie tryb TESTNET

# Połączenie z API Bybit Testnet (://bybit.com)
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
    coins = res["result"]["list"]["coin"]
    for c in coins:
        if c["coin"] == "USDT":
            return float(c["walletBalance"])
    return 0.0

def get_open_position_qty(symbol: str) -> float:
    res = session.get_positions(category="linear", symbol=symbol)
    positions = res["result"]["list"]
    if positions:
        return float(positions["size"])
    return 0.0

@app.get("/health")
def health_check():
    return {"status": "ok", "mode": "TESTNET" if USE_TESTNET else "REAL"}

@app.post("/webhook")
def receive_webhook(data: WebhookPayload):
    if data.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Nieprawidłowe hasło webhooka")

    symbol = data.symbol
    ensure_leverage(symbol, "5")

    # === OTWARCIE POZYCJI ===
    if data.action in ["OPEN_LONG", "OPEN_SHORT"]:
        balance = get_usdt_balance()
        if balance <= 10:
            return {"status": "error", "message": "Zbyt niskie saldo USDT"}

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
        return {"status": "opened", "side": side, "qty": qty, "balance": balance, "order": order}

    # === ZAMKNIĘCIE POZYCJI ===
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
        return {"status": "closed", "side": close_side, "qty": current_qty, "order": order}

    return {"status": "ignored", "message": "Nieznana akcja"}
