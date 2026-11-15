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

# Konfiguracja precyzji dla obsługiwanych par (ilość miejsc po przecinku)
SYMBOL_CONFIG = {
    "BTCUSDT": {"qty_decimals": 3, "min_qty": 0.001, "price_decimals": 1},
    "ETHUSDT": {"qty_decimals": 2, "min_qty": 0.01, "price_decimals": 2},
}

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
    coins = account_list[0].get("coin", [])
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
        cfg = SYMBOL_CONFIG.get(symbol, {"qty_decimals": 3, "min_qty": 0.001, "price_decimals": 1})
        ensure_leverage(symbol, "5")

        if data.action in ["OPEN_LONG", "OPEN_SHORT"]:
            # 1. Sprawdzenie czy pozycja nie jest już otwarta
            if get_open_position_qty(symbol) > 0:
                return {"status": "ignored", "message": "Pozycja jest już otwarta"}

            balance = get_usdt_balance()
            if balance <= 10:
                return {"status": "error", "message": f"Zbyt niskie saldo USDT: {balance}"}

            if data.stop_distance <= 0 or data.entry_price <= 0:
                return {"status": "error", "message": "Nieprawidłowa wartość stop_distance lub entry_price"}

            # 2. Wyliczenie wielkości pozycji z limitem dla dźwigni 5x (bezpieczny mnożnik 4.5x)
            risk_usdt = balance * (data.risk_pct / 100.0)
            raw_qty = risk_usdt / data.stop_distance
            max_safe_qty = (balance * 4.5) / data.entry_price
            final_raw_qty = min(raw_qty, max_safe_qty)

            qty = max(cfg["min_qty"], round(final_raw_qty, cfg["qty_decimals"]))
            sl_rounded = round(data.sl_price, cfg["price_decimals"])
            side = "Buy" if data.action == "OPEN_LONG" else "Sell"

            order = session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(sl_rounded),
                slTriggerBy="LastPrice",
            )
            return {
                "status": "opened",
                "side": side,
                "qty": qty,
                "sl_price": sl_rounded,
                "balance_usdt": balance,
                "order": order,
            }

        elif data.action == "UPDATE_SL":
            current_qty = get_open_position_qty(symbol)
            if current_qty <= 0:
                return {"status": "ignored", "message": "Brak otwartej pozycji do aktualizacji SL"}

            if data.sl_price <= 0:
                return {"status": "error", "message": "Nieprawidłowa cena sl_price"}

            sl_rounded = round(data.sl_price, cfg["price_decimals"])
            res = session.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=str(sl_rounded),
                slTriggerBy="LastPrice",
                positionIdx=0,
            )
            return {
                "status": "sl_updated",
                "new_sl": sl_rounded,
                "response": res,
            }

        elif data.action in ["CLOSE_LONG", "CLOSE_SHORT"]:
            current_qty = get_open_position_qty(symbol)
            if current_qty <= 0:
                return {"status": "ignored", "message": "Brak otwartej pozycji (prawdopodobnie zamknięta przez SL)"}

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
