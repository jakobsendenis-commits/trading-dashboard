"""
TIA TRADING BOT - ALWAYS IN POSITION
Modtager signaler fra TradingView MA og handler automatisk på Bybit
Altid i position - enten LONG eller SHORT
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
BYBIT_API_KEY = "KM5qwqnm18X3NRufhA"  # Få fra Bybit (SAMME som BTC bot)
BYBIT_API_SECRET = "b7W10HlTPcggvszuDX1ukohXb5Q0E4szt3Gn"  # Få fra Bybit (SAMME som BTC bot)
TESTNET = False  # False = LIVE MODE (rigtige penge!)

# Trading indstillinger
SYMBOL = "TIAUSDT"
LEVERAGE = 8  # Gearing (1-100x)
POSITION_SIZE_USDT = 50
STOP_LOSS_PERCENT = 4.0  # Stop loss i procent
TAKE_PROFIT_PERCENT = 0  # Ingen TP - holder til næste signal

# Quad Take Profit Strategy
TP_LEVELS = [
    {"profit_pct": 10.0, "sell_pct": 0.15, "name": "TP1"},  # Ved 10% → Sælg 15%
    {"profit_pct": 15.0, "sell_pct": 0.25, "name": "TP2"},  # Ved 15% → Sælg 25%
    {"profit_pct": 30.0, "sell_pct": 0.40, "name": "TP3"},  # Ved 30% → Sælg 40%
]
# TP4 = Rest (20%) holder til signal skift

# Track hvilke TP levels der er ramt (gemmes i memory)
tp_levels_hit = {}

# Track last known position for SL detection
last_known_position = {
    'side': None,
    'size': 0,
    'avg_price': 0,
    'position_idx': 0
}

# CSV log fil sti - SAMLET FIL FOR ALLE BOTS
TRADE_LOG_FILE = os.path.expanduser("~/Desktop/bot/all_trades.csv")

# ====== WEBHOOK SERVER ======
app = Flask(__name__)

# Bybit forbindelse
if TESTNET:
    session = HTTP(testnet=True, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    print("🧪 TESTNET MODE - Ingen rigtige penge!")
else:
    session = HTTP(testnet=False, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    print("💰 LIVE MODE - Rigtige penge!")


def log(message):
    """Logger besked med timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def log_trade_to_csv(trade_type, signal, price, qty, profit=None, profit_pct=None, notes="", indicator="TIA MA Bot"):
    """Logger trade til CSV fil"""
    try:
        # Tjek om fil eksisterer
        file_exists = os.path.isfile(TRADE_LOG_FILE)
        
        # Åbn fil i append mode
        with open(TRADE_LOG_FILE, 'a', newline='') as csvfile:
            fieldnames = ['coin', 'timestamp', 'trade_type', 'signal', 'price', 'qty', 'value_usd', 'profit_usd', 'profit_pct', 'indicator', 'notes']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Skriv header hvis ny fil
            if not file_exists:
                writer.writeheader()
            
            # Beregn value
            value_usd = price * qty
            
            # Skriv trade
            writer.writerow({
                'coin': SYMBOL.replace('USDT', ''),  # TIA, BTC, osv.
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'trade_type': trade_type,  # ENTRY, EXIT, PARTIAL_TP
                'signal': signal,  # LONG, SHORT
                'price': round(price, 2),
                'qty': round(qty, 4),
                'value_usd': round(value_usd, 2),
                'profit_usd': round(profit, 2) if profit else '',
                'profit_pct': round(profit_pct, 2) if profit_pct else '',
                'indicator': indicator,
                'notes': notes
            })
            
        log(f"📝 Trade logged til {TRADE_LOG_FILE}")
        
    except Exception as e:
        log(f"❌ Fejl ved logging til CSV: {e}")


def get_current_price():
    """Hent nuværende TIA pris"""
    try:
        ticker = session.get_tickers(category="linear", symbol=SYMBOL)
        price = float(ticker['result']['list'][0]['lastPrice'])
        return price
    except Exception as e:
        log(f"❌ Fejl ved hentning af pris: {e}")
        return None


def get_current_position():
    """Tjek om vi har en åben position og hvilken side"""
    try:
        positions = session.get_positions(category="linear", symbol=SYMBOL)
        for pos in positions['result']['list']:
            size = float(pos['size'])
            if size > 0:
                avg_price = float(pos['avgPrice'])
                return pos['side'], size, int(pos['positionIdx']), avg_price
        return None, 0, 0, 0
    except Exception as e:
        log(f"❌ Fejl ved tjek af position: {e}")
        return None, 0, 0, 0


def check_partial_tp():
    """Tjek om vi skal tage partial profit på multiple levels"""
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
            profit_pct = price_change_pct * LEVERAGE  # Multiply by leverage
        else:  # Sell/Short
            price_change_pct = ((avg_price - current_price) / avg_price) * 100
            profit_pct = price_change_pct * LEVERAGE  # Multiply by leverage
        
        log(f"🔍 TP Check: {current_side} position, pris ændring: {price_change_pct:.2f}%, leveraged profit: {profit_pct:.2f}%")
        
        # Generer unik position ID
        position_id = f"{current_side}_{avg_price}"
        
        # Initialiser TP tracking for denne position hvis ny
        if position_id not in tp_levels_hit:
            tp_levels_hit[position_id] = []
        
        any_executed = False
        
        # Check hver TP level
        for tp_level in TP_LEVELS:
            tp_name = tp_level["name"]
            
            # Skip hvis allerede ramt
            if tp_name in tp_levels_hit[position_id]:
                continue
            
            # Hvis profit >= TP level
            if profit_pct >= tp_level["profit_pct"]:
                # Beregn hvor meget af ORIGINAL position vi skal sælge
                original_size = size / (1 - sum([tp["sell_pct"] for tp in TP_LEVELS if tp["name"] in tp_levels_hit[position_id]]))
                partial_size = round(original_size * tp_level["sell_pct"], 3)
                
                # Sikr vi ikke sælger mere end vi har
                if partial_size > int(size):
                    partial_size = int(size)
                
                if partial_size < 0.01:
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
                
                # Marker som ramt
                tp_levels_hit[position_id].append(tp_name)
                
                # Beregn actual profit baseret på price difference
                if current_side == "Buy":
                    profit_usd = partial_size * (current_price - avg_price)
                else:
                    profit_usd = partial_size * (avg_price - current_price)
                
                log(f"💰 {tp_name} RAMT! Lukkede {tp_level['sell_pct']*100}% ved {profit_pct:.2f}% profit")
                log(f"   Solgte: {partial_size} TIA til ${current_price}")
                log(f"   Profit: ${profit_usd:.2f}")
                
                # Log til CSV
                log_trade_to_csv(
                    trade_type="PARTIAL_TP",
                    signal=current_side,
                    price=current_price,
                    qty=partial_size,
                    profit=profit_usd,
                    profit_pct=profit_pct,
                    notes=f"{tp_name} - {tp_level['sell_pct']*100}% exit"
                )
                
                remaining_pct = (1 - sum([tp["sell_pct"] for tp in TP_LEVELS if tp["name"] in tp_levels_hit[position_id]])) * 100
                log(f"   Holder: {remaining_pct:.0f}% til næste level/signal")
                
                any_executed = True
        
        return any_executed
            
    except Exception as e:
        log(f"❌ Fejl ved partial TP check: {e}")
        return False


def tp_checker_loop():
    """Background thread der tjekker TP hvert 10. sekund og detecter SL hits"""
    log("🔄 TP Checker thread startet - tjekker hvert 10. sekund")
    while True:
        try:
            time.sleep(10)  # Vent 10 sekunder
            
            current_side, size, position_idx, avg_price = get_current_position()
            
            # Check for Stop Loss hit
            if last_known_position['side'] is not None and last_known_position['size'] > 0:
                # Hvis vi havde en position, men nu har vi ingen
                if current_side is None or size == 0:
                    # Position er lukket - sandsynligvis af SL
                    current_price = get_current_price()
                    if current_price:
                        # Beregn profit (vil være negativt ved SL)
                        old_side = last_known_position['side']
                        old_size = last_known_position['size']
                        old_avg_price = last_known_position['avg_price']
                        
                        if old_side == "Buy":
                            profit_pct = ((current_price - old_avg_price) / old_avg_price) * 100
                        else:
                            profit_pct = ((old_avg_price - current_price) / old_avg_price) * 100
                        
                        profit_usd = old_size * current_price * (profit_pct / 100)
                        
                        log(f"🛑 STOP LOSS RAMT! Position lukket automatisk af Bybit")
                        log(f"   {old_side} position: {old_size} TIA")
                        log(f"   Entry: ${old_avg_price:.2f}")
                        log(f"   Exit: ${current_price:.2f}")
                        log(f"   Tab: ${profit_usd:.2f} ({profit_pct:.2f}%)")
                        
                        # Log til CSV
                        log_trade_to_csv(
                            trade_type="EXIT",
                            signal="LONG" if old_side == "Buy" else "SHORT",
                            price=current_price,
                            qty=old_size,
                            profit=profit_usd,
                            profit_pct=profit_pct,
                            notes="Stop Loss ramt (automatisk lukket af Bybit)"
                        )
                        
                        # Reset last known position
                        last_known_position['side'] = None
                        last_known_position['size'] = 0
                        last_known_position['avg_price'] = 0
                        last_known_position['position_idx'] = 0
            
            # Update last known position
            if current_side and size > 0:
                last_known_position['side'] = current_side
                last_known_position['size'] = size
                last_known_position['avg_price'] = avg_price
                last_known_position['position_idx'] = position_idx
                
                # Check TP levels
                current_price = get_current_price()
                if current_price and avg_price > 0:
                    if current_side == "Buy":
                        profit_pct = ((current_price - avg_price) / avg_price) * 100
                    else:
                        profit_pct = ((avg_price - current_price) / avg_price) * 100
                    
                    log(f"🔍 TP Check: {current_side} position, profit: {profit_pct:.2f}%")
                    check_partial_tp()
                    
        except Exception as e:
            log(f"❌ Fejl i TP checker: {e}")
            time.sleep(30)


def close_position(side, size, position_idx, avg_price=None):
    """Luk en specifik position"""
    try:
        current_price = get_current_price()
        if not current_price:
            log(f"❌ Kunne ikke hente pris for EXIT logging")
            return False
            
        close_side = "Sell" if side == "Buy" else "Buy"
        
        session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=close_side,
            orderType="Market",
            qty=str(size),
            positionIdx=position_idx,
            reduceOnly=True
        )
        
        # Beregn profit hvis vi har avg_price
        profit_usd = None
        profit_pct = None
        if avg_price and avg_price > 0:
            if side == "Buy":  # LONG position
                profit_pct = ((current_price - avg_price) / avg_price) * 100
            else:  # SHORT position
                profit_pct = ((avg_price - current_price) / avg_price) * 100
            profit_usd = size * current_price * (profit_pct / 100)
        
        log(f"✅ Lukkede {side} position: {size} TIA")
        if profit_usd:
            log(f"   Profit: ${profit_usd:.2f} ({profit_pct:.2f}%)")
        
        # Log til CSV
        log_trade_to_csv(
            trade_type="EXIT",
            signal="LONG" if side == "Buy" else "SHORT",
            price=current_price,
            qty=size,
            profit=profit_usd,
            profit_pct=profit_pct,
            notes=f"Full exit på signal skift"
        )
        
        return True
    except Exception as e:
        log(f"❌ Fejl ved lukning af position: {e}")
        return False


def open_position(signal, price):
    """Åbn ny position (LONG eller SHORT)"""
    try:
        # Beregn position størrelse i TIA - med leverage
        qty_raw = (POSITION_SIZE_USDT * LEVERAGE) / price
        qty = int(qty_raw)  # TIA requires integer quantities
        
        # Sørg for minimum størrelse
        if qty < 1:
            qty = 1
            log(f"⚠️ Justerede qty til minimum: {qty} TIA")
        
        # Beregn stop loss baseret på signal type
        if signal == "LONG":
            side = "Buy"
            position_idx = 1  # Long side i Hedge Mode
            stop_loss = round(price * (1 - STOP_LOSS_PERCENT / 100), 2)
            take_profit = None if TAKE_PROFIT_PERCENT == 0 else round(price * (1 + TAKE_PROFIT_PERCENT / 100), 2)
        else:  # SHORT
            side = "Sell"
            position_idx = 2  # Short side i Hedge Mode
            stop_loss = round(price * (1 + STOP_LOSS_PERCENT / 100), 2)
            take_profit = None if TAKE_PROFIT_PERCENT == 0 else round(price * (1 - TAKE_PROFIT_PERCENT / 100), 2)
        
        # Åbn position
        order_params = {
            "category": "linear",
            "symbol": SYMBOL,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "positionIdx": position_idx,
            "stopLoss": str(stop_loss)
        }
        
        # Tilføj TP kun hvis defineret
        if take_profit:
            order_params["takeProfit"] = str(take_profit)
        
        order = session.place_order(**order_params)
        
        log(f"✅ Åbnede {side} position (idx={position_idx}):")
        log(f"   Størrelse: {qty} TIA (${POSITION_SIZE_USDT})")
        log(f"   Entry: ${price}")
        log(f"   Stop Loss: ${stop_loss}")
        if take_profit:
            log(f"   Take Profit: ${take_profit}")
        else:
            log(f"   Take Profit: Holder til næste signal")
        
        # Log til CSV
        log_trade_to_csv(
            trade_type="ENTRY",
            signal=signal,
            price=price,
            qty=qty,
            notes=f"SL: {stop_loss}, Leverage: {LEVERAGE}x"
        )
        
        return True
    except Exception as e:
        log(f"❌ Fejl ved åbning af position: {e}")
        return False


@app.route('/webhook', methods=['POST'])
def webhook():
    """Modtag signal fra TradingView"""
    try:
        data = request.json
        log(f"📡 Modtog signal: {data}")
        
        # Tjek hvilket signal vi fik
        signal = data.get('signal', '').upper()
        
        if signal not in ['LONG', 'SHORT']:
            return jsonify({'status': 'error', 'message': 'Ugyldigt signal - skal være LONG eller SHORT'}), 400
        
        # Hent nuværende pris
        price = get_current_price()
        if not price:
            return jsonify({'status': 'error', 'message': 'Kunne ikke hente pris'}), 500
        
        log(f"💰 Nuværende TIA pris: ${price}")
        
        # Tjek om vi har en eksisterende position
        current_side, current_size, position_idx, avg_price = get_current_position()
        
        # Hvis vi allerede er i den rigtige position, ignorer signal
        if current_side == "Buy" and signal == "LONG":
            log(f"⚠️ Allerede i LONG position - ignorer signal")
            return jsonify({'status': 'ignored', 'message': 'Already in LONG position'}), 200
        
        if current_side == "Sell" and signal == "SHORT":
            log(f"⚠️ Allerede i SHORT position - ignorer signal")
            return jsonify({'status': 'ignored', 'message': 'Already in SHORT position'}), 200
        
        # Luk modsat position hvis den eksisterer
        if current_side:
            log(f"🔄 Lukker {current_side} position før ny {signal} åbnes")
            close_position(current_side, current_size, position_idx, avg_price)
        
        # Åbn ny position
        success = open_position(signal, price)
        if success:
            # Update last known position efter åbning
            time.sleep(2)  # Vent lidt så position er registreret
            current_side, current_size, position_idx, avg_price = get_current_position()
            if current_side:
                last_known_position['side'] = current_side
                last_known_position['size'] = current_size
                last_known_position['avg_price'] = avg_price
                last_known_position['position_idx'] = position_idx
            
            return jsonify({'status': 'success', 'signal': signal, 'price': price}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Kunne ikke åbne position'}), 500
            
    except Exception as e:
        log(f"❌ Webhook fejl: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/check_tp', methods=['GET'])
def check_tp_endpoint():
    """Tjek og udfør partial TP hvis nødvendigt"""
    try:
        executed = check_partial_tp()
        return jsonify({'status': 'success', 'partial_tp_executed': executed}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status', methods=['GET'])
def status():
    """Tjek bot status"""
    try:
        price = get_current_price()
        positions = session.get_positions(category="linear", symbol=SYMBOL)
        current_side, current_size, _, avg_price = get_current_position()
        
        profit_pct = 0
        tp_status = "None"
        if current_side and avg_price > 0:
            if current_side == "Buy":
                price_change = ((price - avg_price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
            else:
                price_change = ((avg_price - price) / avg_price) * 100
                profit_pct = price_change * LEVERAGE
            
            # Check hvilke TP levels der er ramt
            position_id = f"{current_side}_{avg_price}"
            hit_levels = tp_levels_hit.get(position_id, [])
            if len(hit_levels) == 0:
                tp_status = "Waiting for TP1 (10%)"
            elif len(hit_levels) == 1:
                tp_status = "TP1 hit, waiting for TP2 (15%)"
            elif len(hit_levels) == 2:
                tp_status = "TP1+TP2 hit, waiting for TP3 (30%)"
            elif len(hit_levels) == 3:
                tp_status = "TP1+TP2+TP3 hit, holding 20% to signal"
        
        return jsonify({
            'status': 'online',
            'mode': 'TESTNET' if TESTNET else 'LIVE',
            'symbol': SYMBOL,
            'price': price,
            'current_position': current_side if current_side else 'None',
            'position_size': current_size,
            'avg_entry': avg_price,
            'profit_pct': round(profit_pct, 2),
            'tp_status': tp_status,
            'positions': positions['result']['list']
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    log("🤖 TIA Trading Bot starter...")
    log(f"📊 Symbol: {SYMBOL}")
    log(f"💵 Position size: ${POSITION_SIZE_USDT}")
    log(f"📉 Stop Loss: {STOP_LOSS_PERCENT}%")
    log(f"📈 Quad Take Profit:")
    log(f"   TP1: 10% profit → Sælg 15%")
    log(f"   TP2: 15% profit → Sælg 25%")
    log(f"   TP3: 30% profit → Sælg 40%")
    log(f"   TP4: Hold 20% til signal skift")
    log(f"⚡ Leverage: {LEVERAGE}x")
    log(f"🔄 Strategi: Altid i position (LONG eller SHORT)")
    log(f"🔄 Position Mode: Hedge Mode (idx 1=Long, 2=Short)")
    log(f"📝 Trade log: {TRADE_LOG_FILE}")
    log("")
    
    # Start TP checker thread
    tp_thread = threading.Thread(target=tp_checker_loop, daemon=True)
    tp_thread.start()
    
    log("✅ Bot kører! Venter på signaler...")
    log("🌐 Webhook URL: http://localhost:5002/webhook")
    log("📊 Status URL: http://localhost:5002/status")
    log("💰 Check TP: http://localhost:5002/check_tp")
    
    app.run(host='0.0.0.0', port=5006, debug=False)