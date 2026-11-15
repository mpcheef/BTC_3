# Bot Tradingowy BTCUSDT (TradingView + Render + Bybit Futures)

Zautomatyzowany system handlu algorytmicznego dla pary **BTCUSDT (USDT Perpetual)** na interwale **4h**, oparty o strategię podążającą za trendem (*Trend Following / Donchian Breakout*) z filtrami zmienności (ATR) oraz siły trendu (ADX).

---

## 1. Architektura systemu i wyniki testów (2022–2026)

* **Nazwa strategii w TradingView:** `N3 BTCUSDT 4H Trend + ADX [Render API Webhook]`
* **Rynek:** BTCUSDT Perpetual Futures (Bybit)
* **Interwał:** 4h (czterogodzinowy)
* **Zarządzanie ryzykiem:** Dynamiczny *Position Sizing* — ryzyko **2,5%** aktualnego salda konta na jedną transakcję (wyliczane automatycznie przez serwer na podstawie `stop_distance`).
* **Ustawienia konta Bybit:** Tryb depozytu **Cross**, dźwignia maksymalna **5x** (ustawiana automatycznie przez API bota), tryb pozycji **One-Way Mode**, opcja *TP/SL Price Protection* **wyłączona (OFF)**.
* **Wyniki historyczne (styczeń 2022 – listopad 2026):**
  * Zysk netto z procentem składanym: **~228%** (**~27,6% CAGR rocznie** / **~46,8% średniorocznie bez procentu składanego**)
  * Maksymalne obsunięcie kapitału (*Max Drawdown*): **~22%**
  * Współczynnik zysku (*Profit Factor*): **~1,62**

---

## 2. Konfiguracja serwera na Render

* **Build Command:** `pip install -r requirements.txt`
* **Start Command:** `uvicorn main:app --host 0.0.0.0 --port 10000`
* **Endpointy serwera:**
  * `GET /health` — sprawdzanie statusu serwera (zwraca `{"status":"ok","mode":"TESTNET"}` lub `"REAL"`).
  * `POST /webhook` — odbiór sygnałów JSON z TradingView.
  * `GET /docs` — wbudowany panel testowy FastAPI do ręcznego wysyłania zleceń próbnych.

### Zmienne środowiskowe (Environment Variables na Render)

| Nazwa zmiennej (`Key`) | Opis i wartość (`Value`) |
| :--- | :--- |
| `BYBIT_API_KEY` | Klucz API z konta Bybit (uprawnienia: *Contract - Orders & Positions*, *Unified Trading*) |
| `BYBIT_API_SECRET` | Sekretny klucz API z konta Bybit |
| `WEBHOOK_SECRET` | Tajne hasło autoryzacji (musi być identyczne jak w polu `webhookSecret` w TradingView, obecnie: `LIS`) |
| `BYBIT_TESTNET` | `true` dla środowiska testowego (`://bybit.com`) lub `false` dla prawdziwego konta (`bybit.com`) |

---

## 3. Utrzymywanie serwera 24/7 (UptimeRobot)

Darmowy plan Render usypia serwer po 15 minutach bezczynności (wybudzenie trwa ok. 30–50 sekund, co przekracza limit czasu oczekiwania TradingView).
* **Rozwiązanie:** W darmowym serwisie **UptimeRobot** należy utrzymywać aktywny monitor **HTTP(s)** wskazujący na `https://<twoja-domena>://` z interwałem sprawdzania co **5 minut**.

---

## 4. Konfiguracja alertu w TradingView

1. Wykres: **BTCUSDT.P (Bybit)**, interwał **4h**.
2. Warunek (*Condition*): Nazwa strategii (`N3 BTCUSDT 4H Trend + ADX [Render API Webhook]`).
3. Wygaśnięcie (*Expiration*): **Otwarty (*Open-ended*)**.
4. Wiadomość (*Message*):
   ```text
   {{strategy.order.alert_message}}
   ```
5. Powiadomienia (*Notifications*): Zaznacz **Webhook URL** i wpisz `https://<twoja-domena>://`.
6. **Ważne:** Po każdej zmianie parametrów w ustawieniach strategii (np. zmiana `riskPerTrade` lub `webhookSecret`) należy **usunąć stary alert i utworzyć go na nowo**.

---

## 5. Przejście z Bybit Testnet na prawdziwe konto (Mainnet)

1. Utwórz na głównym koncie **Bybit** (`bybit.com`) dedykowane **Subkonto** (Subaccount) wyłącznie pod bota i przelej tam kapitał startowy (np. 100 USDT lub 1000 USDT) na portfel **Unified Trading**.
2. Wygeneruj nowe klucze API dla tego Subkonta (z uprawnieniami *Contract - Orders & Positions* oraz *Unified Trading*).
3. W panelu **Render -> Environment** zaktualizuj trzy zmienne:
   * `BYBIT_TESTNET` = `false`
   * `BYBIT_API_KEY` = nowy klucz z głównego Bybit
   * `BYBIT_API_SECRET` = nowy sekret z głównego Bybit
4. Zapisz zmiany (*Save Changes*) — bot automatycznie odczyta nowe saldo z giełdy przy kolejnym sygnale.

---

## 6. Aktualny kod Pine Script v5 (TradingView)

```pinescript
//@version=5
strategy("N3 BTCUSDT 4H Trend + ADX [Render API Webhook]", overlay=true, 
     initial_capital=100, 
     currency=currency.USDT,
     default_qty_type=strategy.cash,
     margin_long=20, // Odpowiednik dźwigni 5x w testerze TradingView
     margin_short=20, // Odpowiednik dźwigni 5x w testerze TradingView
     commission_type=strategy.commission.percent, 
     commission_value=0.055,
     slippage=2)

// === 1. ZARZĄDZANIE RYZYKIEM I AUTORYZACJA ===
riskPerTrade = input.float(2.5, "Ryzyko na transakcję (% salda na Bybit)", minval=0.5, maxval=5.0, step=0.1)
webhookSecret = input.string("LIS", "Hasło autoryzacji dla serwera Render")

// === 2. PARAMETRY STRATEGII ===
donchianLen = input.int(24, "Okres wybicia (świece 4H)", minval=10)
emaFilterLen = input.int(200, "Filtr głównego trendu (EMA)", minval=50)
atrLen = input.int(14, "Okres zmienności ATR", minval=5)
atrMult = input.float(3.0, "Mnożnik ATR dla Stop Lossa", minval=1.0, step=0.1)

// === 3. FILTR SIŁY TRENDU (ADX) ===
useAdx = input.bool(true, "Włącz filtr ADX (unikaj konsolidacji)")
adxLen = input.int(14, "Okres ADX", minval=5)
adxThreshold = input.int(20, "Minimalny poziom ADX dla wejścia", minval=10, maxval=40)

// === 4. OBLICZENIA WSKAŹNIKÓW (Poprzednia świeca) ===
prevHigh = high[1]
prevLow = low[1]
upperBand = ta.highest(prevHigh, donchianLen)
lowerBand = ta.lowest(prevLow, donchianLen)
emaTrend = ta.ema(close, emaFilterLen)
atr = ta.atr(atrLen)
[diPlus, diMinus, adx] = ta.dmi(adxLen, adxLen)

// === 5. WARUNKI WEJŚCIA ===
adxCondition = useAdx ? (adx > adxThreshold) : true
longCondition = ta.crossover(close, upperBand) and close > emaTrend and adxCondition
shortCondition = ta.crossunder(close, lowerBand) and close < emaTrend and adxCondition

// === 6. OBLICZENIA DO BACKTESTU I DLA SERWERA RENDER ===
stopDistance = atr * atrMult
riskAmount = strategy.equity * (riskPerTrade / 100)
rawQty = riskAmount / stopDistance
positionSize = math.max(0.001, math.round(rawQty * 1000) / 1000)

// Wyliczenie poziomów SL dla informacji wysyłanej do bota na Render
longSlPrice = close - stopDistance
shortSlPrice = close + stopDistance

// === 7. SZABLONY JSON DLA SERWERA NA RENDER ===
msgOpenLong   = '{"secret":"' + webhookSecret + '","symbol":"BTCUSDT","action":"OPEN_LONG","risk_pct":' + str.tostring(riskPerTrade) + ',"stop_distance":' + str.tostring(stopDistance) + ',"sl_price":' + str.tostring(longSlPrice) + ',"entry_price":' + str.tostring(close) + '}'
msgOpenShort  = '{"secret":"' + webhookSecret + '","symbol":"BTCUSDT","action":"OPEN_SHORT","risk_pct":' + str.tostring(riskPerTrade) + ',"stop_distance":' + str.tostring(stopDistance) + ',"sl_price":' + str.tostring(shortSlPrice) + ',"entry_price":' + str.tostring(close) + '}'
msgCloseLong  = '{"secret":"' + webhookSecret + '","symbol":"BTCUSDT","action":"CLOSE_LONG","exit_price":' + str.tostring(close) + '}'
msgCloseShort = '{"secret":"' + webhookSecret + '","symbol":"BTCUSDT","action":"CLOSE_SHORT","exit_price":' + str.tostring(close) + '}'

// === 8. EGZEKUCJA ZLECEŃ ===
if (longCondition and strategy.position_size == 0)
    strategy.entry("Long", strategy.long, qty=positionSize, alert_message=msgOpenLong)

if (shortCondition and strategy.position_size == 0)
    strategy.entry("Short", strategy.short, qty=positionSize, alert_message=msgOpenShort)

// === 9. NATYCHMIASTOWY KROCZĄCY STOP LOSS ===
var float trailStop = na

if (strategy.position_size > 0)
    newStop = close - stopDistance
    trailStop := na(trailStop) ? newStop : math.max(trailStop, newStop)
    strategy.exit("Exit Long", "Long", stop=trailStop, alert_message=msgCloseLong)

else if (strategy.position_size < 0)
    newStop = close + stopDistance
    trailStop := na(trailStop) ? newStop : math.min(trailStop, newStop)
    strategy.exit("Exit Short", "Short", stop=trailStop, alert_message=msgCloseShort)
else
    trailStop := na

// === 10. WIZUALIZACJA ===
plot(upperBand, "Poziom wybicia Long", color=color.new(color.green, 40))
plot(lowerBand, "Poziom wybicia Short", color=color.new(color.red, 40))
plot(emaTrend, "EMA 200 (Filtr trendu)", color=color.orange, linewidth=2)
plot(strategy.position_size != 0 ? trailStop : na, "Kroczący Stop Loss", color=color.fuchsia, style=plot.style_linebr, linewidth=2)
```
