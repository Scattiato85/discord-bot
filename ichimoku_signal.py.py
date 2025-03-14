
import os
import time
import requests
import discord
import asyncio
import pandas as pd

# ================================
# CONFIGURAZIONE VARIABILI D'AMBIENTE
# ================================
import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

if not DISCORD_TOKEN or not DISCORD_CHANNEL_ID:
    raise ValueError("Le variabili d'ambiente DISCORD_TOKEN e DISCORD_CHANNEL_ID non sono state impostate correttamente.")

DISCORD_CHANNEL_ID = int(DISCORD_CHANNEL_ID)  # Converti in intero per sicurezza

# ================================
# SCARICARE TUTTE LE MONETE DA BINANCE
# ================================
def get_all_binance_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return [symbol["symbol"] for symbol in data["symbols"] if symbol["symbol"].endswith("USDT")]
    except Exception as e:
        print(f"Errore nel recupero dei simboli da Binance: {e}")
        return ["BTCUSDT", "ETHUSDT"]  # Fallback

SYMBOLS = get_all_binance_symbols()
print(f"Monete caricate: {SYMBOLS}")

# ================================
# CONFIGURAZIONI API BINANCE
# ================================
BINANCE_API_URL = "https://api.binance.com/api/v3/klines"
TIMEFRAMES = {"4h": "4h", "1d": "1d"}
last_timestamps = {}

# ================================
# FUNZIONE: SCARICA LE CANDELE
# ================================
def fetch_candles(symbol, interval, limit=100):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(BINANCE_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        df = pd.DataFrame(data, columns=["open_time", "open", "high", "low", "close", "volume",
                                         "close_time", "quote_asset_volume", "number_of_trades",
                                         "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
        df = df[["open_time", "open", "high", "low", "close", "volume"]]
        df["open_time"] = df["open_time"].astype(int)
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] Errore nel fetch delle candele per {symbol} {interval}: {e}")
        return None

# ================================
# FUNZIONE: CALCOLO ICHIMOKU
# ================================
def calculate_ichimoku(df, period_tenkan=9, period_kijun=26, period_spanB=52, displacement=26):
    if df is None or len(df) < (period_spanB + displacement):
        return None
    tenkan = (df['high'].rolling(window=period_tenkan).max() + df['low'].rolling(window=period_tenkan).min()) / 2
    kijun = (df['high'].rolling(window=period_kijun).max() + df['low'].rolling(window=period_kijun).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(displacement)
    span_b = ((df['high'].rolling(window=period_spanB).max() + df['low'].rolling(window=period_spanB).min()) / 2).shift(displacement)
    chikou = df['close'].shift(-displacement)
    valid_index = df.dropna().index
    if len(valid_index) == 0:
        return None
    idx = valid_index[-1]
    return {
        "tenkan": tenkan.loc[idx],
        "kijun": kijun.loc[idx],
        "span_a": span_a.loc[idx],
        "span_b": span_b.loc[idx],
        "chikou": chikou.loc[idx],
        "close": df['close'].loc[idx]
    }

# ================================
# FUNZIONE: DETERMINARE IL SEGNALE ICHIMOKU
# ================================
def ichimoku_signal(df):
    ichi = calculate_ichimoku(df)
    if ichi is None:
        return "nessun segnale"
    close = ichi["close"]
    if close > max(ichi["span_a"], ichi["span_b"]) and ichi["tenkan"] > ichi["kijun"] and ichi["chikou"] > close:
        return "ichimoku_long"
    elif close < min(ichi["span_a"], ichi["span_b"]) and ichi["tenkan"] < ichi["kijun"] and ichi["chikou"] < close:
        return "ichimoku_short"
    else:
        return "nessun segnale"

# ================================
# SETUP DEL BOT DISCORD
# ================================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Bot connesso come {client.user}")
    client.loop.create_task(scan_ichimoku_signals())

# ================================
# TASK DI SCANSIONE DEI SEGNALI ICHIMOKU
# ================================
async def scan_ichimoku_signals():
    await client.wait_until_ready()
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        print("Errore: Canale Discord non trovato. Verifica DISCORD_CHANNEL_ID.")
        return
    while not client.is_closed():
        for symbol in SYMBOLS:
            for tf_label, tf_interval in TIMEFRAMES.items():
                df = fetch_candles(symbol, tf_interval, limit=100)
                if df is None or df.empty:
                    continue
                latest_open_time = df.iloc[-1]["open_time"]
                key = f"{symbol}_{tf_interval}"
                if key in last_timestamps and last_timestamps[key] == latest_open_time:
                    continue
                last_timestamps[key] = latest_open_time
                signal = ichimoku_signal(df)
                if signal in ["ichimoku_long", "ichimoku_short"]:
                    msg = f"{symbol} - Ichimoku {tf_label.upper()}: {signal.replace('ichimoku_', '').upper()}"
                    try:
                        await channel.send(msg)
                        print(f"Inviato: {msg}")
                    except Exception as e:
                        print(f"[ERROR] Impossibile inviare il messaggio per {symbol} {tf_label}: {e}")
        await asyncio.sleep(60)

# ================================
# AVVIO DEL BOT
# ================================
client.run(DISCORD_TOKEN)
