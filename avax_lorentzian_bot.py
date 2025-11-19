"""
AVAX LORENTZIAN BOT - HEDGE MODE VERSION
Modtager signaler fra TradingView Lorentzian Classification og handler automatisk på Bybit
"""

from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import json
from datetime import datetime
import csv
import os
import threading
import time

# ====== INDSTILLINGER - REDIGER DISSE ======
BYBIT_API_KEY = "KM5qwqnm18X3NRufhA"
BYBIT_API_SECRET = "b7W10HlTPcggvszuDX1ukohXb5Q0E4szt3Gn"
TESTNET = False  # False = LIVE MODE

# Trading indstillinger
SYMBOL = "AVAXUSDT"
LEVERAGE = 8
POSITION_SIZE_USDT = 50
STOP_LOSS_PERCENT = 4.0
TAKE_PROFIT_PERCENT = 0  # Ingen TP - holder til næste signal

# Quad Take Profit Strategy
TP_LEVELS = [
    {"profit_pct": 10.0, "sell_pct": 0.15, "name": "TP1"},
    {"profit_pct": 15.0, "sell_pct": 0.25, "name": "TP2"},
    {"profit_pct": 30.0, "sell_pct": 0.40, "name": "TP3"},
]

# Track TP levels og position
tp_levels_hit = {}
last_known_position = {
    'side': None,
    'size': 0,
    'avg_price': 0,
    'position_idx': 0
}

# CSV log fil
TRADE_LOG_FILE = os.path.expanduser("~/Desktop/bot/all_trades.csv")

# ====== WEBHOOK SERVER ======
app = Flask(__name__)

if TESTNET:
    session = HTTP(testnet=True, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    print("🧪 TESTNET MODE")
else:
    session = HTTP(testnet=False, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    print("💰 LIVE MODE")


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def log_trade_to_csv(trade_type, signal, price, qty, profit=None, profit_pct=None, notes="", indicator="Lorentzian Bot"):
    try:
        file_exists = os.path.isfile(TRADE_LOG_FILE)
        
        with open(TRADE_LOG_FILE, 'a', newline='') as csvfile:
            fieldnames = ['coin', 'timestamp', 'trade_type', 'signal', 'price', 'qty', 'value_usd', 'profit_usd', 'profit_pct', 'indicator', 'notes']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            value_usd = price * qty
            
            writer.writerow({
                'coin': SYMBOL.replace('USDT', ''),
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'trade_type': trade_type,
                'signal': signal,
                'price': round(price, 4),
                'qty': round(qty, 2),
                'value_usd': round(value_usd, 2),
                'profit_usd': round(profit, 2) if profit else '',
                'profit_pct': round(profit_pct, 2) if profit_pct else '',
                'indicator': indicator,
                'notes': notes
            })
            
        log(f"📝 Trade logged")
        
    except Exception as e:
        log(f"❌ CSV logging error: {e}")


def get_current_price():
    try:
        ticker = session.get_tickers(category="linear", symbol=SYMBOL)
        price = float(ticker['result']['list'][0]['lastPrice'])
        return price
    except Exception as e:
        log(f"❌ Price fetch error: {e}")
        return None


def get_current_position():
    try:
        positions = session.get_positions(category="linear", symbol=SYMBOL)
        for pos in positions['result']['list']:
            size = float(pos['size'])
            if size > 0:
                avg_price = float(pos['avgPrice'])
                return pos['side'], size, int(pos['positionIdx']), avg_price
        return None, 0, 0, 0
    except Exception as e:
        log(f"❌ Position check error: {e}")
        return None, 0, 0, 0


def check_partial_tp():
    try:
        current_side, size, position_idx, avg_price = get_current_position()
        
        if not current_side or size == 0:
            return False
        
        current_price = get_current_price()
        if not current_price:
            return False
        
        # Beregn profit % MED LEVERAGE
        if current_side == "Buy":
            price_change_pct = ((current_price - avg_price) / avg_price) * 100
            profit_pct = price_change_pct * LEVERAGE
        else:
            price_change_pct = ((avg_price - current_price) / avg_price) * 100
            profit_pct = price_change_pct * LEVERAGE
        
        log(f"🔍 TP Check: {current_side} position, pris ændring: {price_change_pct:.2f}%, leveraged profit: {profit_pct:.2f}%")
        
        position_id = f"{current_side}_{avg_price}"
        
        if position_id not in tp_levels_hit:
            tp_levels_hit[position_id] = []
        
        any_executed = False
        
        for tp_level in TP_LEVELS:
            tp_name = tp_level["name"]
            
            if tp_name in tp_levels_hit[position_id]:
                continue
            
            if profit_pct >= tp_level["profit_pct"]:
                original_size = size / (1 - sum([tp["sell_pct"] for tp in TP_LEVELS if tp["name"] in tp_levels_hit[position_id]]))
                partial_size = round(original_size * tp_level["sell_pct"], 1)
                
                if partial_size > size:
                    partial_size = size
                
                if partial_size < 0.1:
                    log(f"⚠️ {tp_name} size for lille ({partial_size}), springer over")
                    continue
                
                close_side = "Sell" if current_side == "Buy" else "Buy"
                
                session.place_order(
                    category="linear",
                    symbol=SYMBOL,
                    side=close_side,
                    orderType="Market",
                    qty=str(partial_size),
                    positionIdx=position_idx,
                    reduceOnly=True
                )
                
                tp_levels_hit[position_id].append(tp_name)
                
                # Beregn actual profit baseret på price difference
                if current_side == "Buy":
                    profit_usd = partial_size * (current_price - avg_price)
                else:
                    profit_usd = partial_size * (avg_price - current_price)
                
                log(f"💰 {tp_name} RAMT! Lukkede {tp_level['sell_pct']*100}% ved {profit_pct:.2f}% profit")
                log(f"   Solgte: {partial_size} AVAX til ${current_price}")
                log(f"   Profit: ${profit_usd:.2f}")
                
                log_trade_to_csv(
                    trade_type="PARTIAL_TP",
                    signal=current_side,
                    price=current_price,
                    qty=partial_size,
                    profit=profit_usd,
                    profit_pct=profit_pct,
                    notes=f"{tp_name} - {tp_level['sell_pct']*100}% exit"
                )
                
                any_executed = True
        
        return any_executed
            
    except Exception as e:
        log(f"❌ Partial TP check error: {e}")
        return False


def tp_checker_loop():
    log("🔄 TP Checker thread startet - tjekker hvert 10. sekund")
    while True:
        try:
            time.sleep(10)
            
            current_side, size, position_idx, avg_price = get_current_position()
            
            # Check for Stop Loss hit
            if last_known_position['side'] is not None and last_known_position['size'] > 0:
                if current_side is None or size == 0:
                    current_price = get_current_price()
                    if current_price:
                        old_side = last_known_position['side']
                        old_size = last_known_position['size']
                        old_avg_price = last_known_position['avg_price']
                        
                        if old_side == "Buy":
                            price_change = ((current_price - old_avg_price) / old_avg_price) * 100
                            profit_pct = price_change * LEVERAGE
                        else:
                            price_change = ((old_avg_price - current_price) / old_avg_price) * 100
                            profit_pct = price_change * LEVERAGE
                        
                        profit_usd = old_size * current_price * (price_change / 100)
                        
                        log(f"🛑 STOP LOSS RAMT!")
                        log(f"   Tab: ${profit_usd:.2f} ({profit_pct:.2f}%)")
                        
                        log_trade_to_csv(
                            trade_type="EXIT",
                            signal=old_side.upper(),
                            price=current_price,
                            qty=old_size,
                            profit=profit_usd,
                            profit_pct=profit_pct,
                            notes="Stop Loss ramt (automatisk lukket af Bybit)"
                        )
                        
                        last_known_position['side'] = None
                        last_known_position['size'] = 0
                        last_known_position['avg_price'] = 0
            
            # Check for partial TP
            if current_side and size > 0:
                check_partial_tp()
                
                last_known_position['side'] = current_side
                last_known_position['size'] = size
                last_known_position['avg_price'] = avg_price
                last_known_position['position_idx'] = position_idx
                
        except Exception as e:
            log(f"❌ TP Checker loop error: {e}")


def close_position(current_side, size, position_idx, avg_price):
    try:
        current_price = get_current_price()
        
        profit_pct = None
        profit_usd = None
        if avg_price > 0 and current_price:
            if current_side == "Buy":
                price_change = ((current_price - avg_price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
            else:
                price_change = ((avg_price - current_price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
            profit_usd = size * current_price * (price_change / 100)
        
        close_side = "Sell" if current_side == "Buy" else "Buy"
        
        session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=close_side,
            orderType="Market",
            qty=str(size),
            positionIdx=position_idx,
            reduceOnly=True
        )
        
        log(f"✅ Lukkede {current_side} position: {size} AVAX")
        if profit_usd:
            log(f"   Profit: ${profit_usd:.2f} ({profit_pct:.2f}%)")
        
        log_trade_to_csv(
            trade_type="EXIT",
            signal=current_side.upper(),
            price=current_price,
            qty=size,
            profit=profit_usd,
            profit_pct=profit_pct,
            notes="Full exit på signal skift"
        )
        
        return True
    except Exception as e:
        log(f"❌ Close position error: {e}")
        return False


def open_position(signal, price):
    try:
        qty = round((POSITION_SIZE_USDT * LEVERAGE) / price, 1)
        
        if qty < 0.1:
            qty = 0.1
        
        if signal == "LONG":
            side = "Buy"
            position_idx = 1
            stop_loss = round(price * (1 - STOP_LOSS_PERCENT / 100), 4)
            take_profit = None
        else:
            side = "Sell"
            position_idx = 2
            stop_loss = round(price * (1 + STOP_LOSS_PERCENT / 100), 4)
            take_profit = None
        
        order_params = {
            "category": "linear",
            "symbol": SYMBOL,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "positionIdx": position_idx,
            "stopLoss": str(stop_loss)
        }
        
        order = session.place_order(**order_params)
        
        log(f"✅ Åbnede {side} position:")
        log(f"   Størrelse: {qty} AVAX (${POSITION_SIZE_USDT})")
        log(f"   Entry: ${price}")
        log(f"   Stop Loss: ${stop_loss}")
        
        log_trade_to_csv(
            trade_type="ENTRY",
            signal=signal,
            price=price,
            qty=qty,
            notes=f"SL: {stop_loss}, Leverage: {LEVERAGE}x"
        )
        
        return True
    except Exception as e:
        log(f"❌ Open position error: {e}")
        return False


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        log(f"📡 Signal modtaget: {data}")
        
        signal = data.get('signal', '').upper()
        
        if signal not in ['LONG', 'SHORT', 'CLOSE']:
            return jsonify({'status': 'error', 'message': 'Invalid signal'}), 400
        
        price = get_current_price()
        if not price:
            return jsonify({'status': 'error', 'message': 'Could not fetch price'}), 500
        
        log(f"💰 Nuværende AVAX pris: ${price}")
        
        current_side, current_size, position_idx, avg_price = get_current_position()
        
        # Hvis CLOSE signal - luk position og stop
        if signal == 'CLOSE':
            if current_side:
                log(f"🔴 CLOSE signal - lukker {current_side} position")
                close_position(current_side, current_size, position_idx, avg_price)
                return jsonify({'status': 'success', 'signal': 'CLOSE'}), 200
            else:
                log(f"⚠️ Ingen position at lukke")
                return jsonify({'status': 'ignored', 'message': 'No position to close'}), 200
        
        if current_side == "Buy" and signal == "LONG":
            log(f"⚠️ Allerede i LONG - ignorer")
            return jsonify({'status': 'ignored'}), 200
        
        if current_side == "Sell" and signal == "SHORT":
            log(f"⚠️ Allerede i SHORT - ignorer")
            return jsonify({'status': 'ignored'}), 200
        
        if current_side:
            log(f"🔄 Lukker {current_side} før ny {signal}")
            close_position(current_side, current_size, position_idx, avg_price)
        
        success = open_position(signal, price)
        if success:
            time.sleep(2)
            current_side, current_size, position_idx, avg_price = get_current_position()
            if current_side:
                last_known_position['side'] = current_side
                last_known_position['size'] = current_size
                last_known_position['avg_price'] = avg_price
                last_known_position['position_idx'] = position_idx
            
            return jsonify({'status': 'success', 'signal': signal, 'price': price}), 200
        else:
            return jsonify({'status': 'error'}), 500
            
    except Exception as e:
        log(f"❌ Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status', methods=['GET'])
def status():
    try:
        price = get_current_price()
        positions = session.get_positions(category="linear", symbol=SYMBOL)
        current_side, current_size, _, avg_price = get_current_position()
        
        profit_pct = 0
        if current_side and avg_price > 0:
            if current_side == "Buy":
                price_change = ((price - avg_price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
            else:
                price_change = ((avg_price - price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
        
        return jsonify({
            'status': 'online',
            'mode': 'TESTNET' if TESTNET else 'LIVE',
            'symbol': SYMBOL,
            'price': price,
            'current_position': current_side if current_side else 'None',
            'position_size': current_size,
            'avg_entry': avg_price,
            'profit_pct': round(profit_pct, 2)
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    log("🤖 AVAX Lorentzian Bot starter...")
    log(f"📊 Symbol: {SYMBOL}")
    log(f"💵 Position size: ${POSITION_SIZE_USDT}")
    log(f"📉 Stop Loss: {STOP_LOSS_PERCENT}%")
    log(f"⚡ Leverage: {LEVERAGE}x")
    log(f"🔄 Strategi: Altid i position (LONG eller SHORT)")
    log(f"📝 Trade log: {TRADE_LOG_FILE}")
    log("")
    
    tp_thread = threading.Thread(target=tp_checker_loop, daemon=True)
    tp_thread.start()
    
    log("✅ Bot kører! Venter på signaler...")
    log("🌐 Webhook URL: http://localhost:5004/webhook")
    log("📊 Status URL: http://localhost:5004/status")
    
    app.run(host='0.0.0.0', port=5004, debug=False)
