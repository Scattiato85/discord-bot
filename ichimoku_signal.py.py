import os
import time
import requests
import discord
import asyncio
import pandas as pd

# ================================
# CONFIGURAZIONI (Variabili d'ambiente)
# ================================
# Imposta su Railway (o nel tuo ambiente) le seguenti variabili:
# DISCORD_TOKEN: il token del bot Discord
# DISCORD_CHANNEL_ID: l'ID del canale Discord in cui inviare i messaggi (es. "123456789012345678")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")

# ================================
# LISTA DEI SIMBOLI DA MONITORARE
# ================================
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT",
    "SOLUSDT", "DOGEUSDT", "DOTUSDT"
]

# ================================
# CONFIGURAZIONI API BINANCE
# ================================
# Utilizziamo l'endpoint pubblico di Binance per le candele (klines)
BINANCE_API_URL = "https://api.binance.com/api/v3/klines"
# Definiamo i timeframe che ci interessano:
TIMEFRAMES = {
    "4h": "4h",
    "1d": "1d"
}

# Dizionario per tenere traccia dell'ultimo timestamp (open_time) elaborato per ciascun simbolo e timeframe
last_timestamps = {}

# ================================
# FUNZIONE: FETCH CANDLE
# ================================
def fetch_candles(symbol, interval, limit=100):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(BINANCE_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        # Crea un DataFrame con le prime 6 colonne:
        # [open_time, open, high, low, close, volume]
        df = pd.DataFrame(data, columns=["open_time", "open", "high", "low", "close", "volume",
                                         "close_time", "quote_asset_volume", "number_of_trades", 
                                         "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
        df = df[["open_time", "open", "high", "low", "close", "volume"]]
        df["open_time"] = df["open_time"].astype(int)
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] Errore nel fetch delle candele per {symbol} {interval}: {e}")
        return None

# ================================
# FUNZIONE: CALCOLO ICHIMOKU (TECNICA ICHIMOKU REALE)
# ================================
def calculate_ichimoku(df, period_tenkan=9, period_kijun=26, period_spanB=52, displacement=26):
    # Assicuriamoci di avere abbastanza dati: serve almeno period_spanB + displacement candele
    if df is None or len(df) < (period_spanB + displacement):
        return None
    tenkan = (df['high'].rolling(window=period_tenkan).max() + df['low'].rolling(window=period_tenkan).min()) / 2
    kijun = (df['high'].rolling(window=period_kijun).max() + df['low'].rolling(window=period_kijun).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(displacement)
    span_b = ((df['high'].rolling(window=period_spanB).max() + df['low'].rolling(window=period_spanB).min()) / 2).shift(displacement)
    chikou = df['close'].shift(-displacement)
    # Trova l'ultimo indice valido (non NaN) nei dati calcolati
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
# FUNZIONE: DETERMINA IL SEGNALA ICHIMOKU
# ================================
def ichimoku_signal(df):
    ichi = calculate_ichimoku(df)
    if ichi is None:
        return "nessun segnale"
    close = ichi["close"]
    # Segnale LONG se:
    # - Il prezzo di chiusura è superiore al massimo tra Senkou Span A e Senkou Span B
    # - Tenkan-sen è superiore a Kijun-sen
    # - Chikou Span è superiore al prezzo di chiusura
    if close > max(ichi["span_a"], ichi["span_b"]) and ichi["tenkan"] > ichi["kijun"] and ichi["chikou"] > close:
        return "ichimoku_long"
    # Segnale SHORT se:
    # - Il prezzo di chiusura è inferiore al minimo tra Senkou Span A e Senkou Span B
    # - Tenkan-sen è inferiore a Kijun-sen
    # - Chikou Span è inferiore al prezzo di chiusura
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
    channel_id = int(DISCORD_CHANNEL_ID)
    channel = client.get_channel(channel_id)
    if channel is None:
        print("Errore: Canale Discord non trovato. Verifica DISCORD_CHANNEL_ID.")
        return
    while not client.is_closed():
        # Per ogni simbolo e per ciascun timeframe (4h e 1d)
        for symbol in SYMBOLS:
            for tf_label, tf_interval in TIMEFRAMES.items():
                df = fetch_candles(symbol, tf_interval, limit=100)
                if df is None or df.empty:
                    continue
                # Ottieni il timestamp della candela più recente
                latest_open_time = df.iloc[-1]["open_time"]
                key = f"{symbol}_{tf_interval}"
                if key in last_timestamps and last_timestamps[key] == latest_open_time:
                    # Candela già processata
                    continue
                last_timestamps[key] = latest_open_time
                signal = ichimoku_signal(df)
                if signal in ["ichimoku_long", "ichimoku_short"]:
                    # Costruisci il messaggio: ad es. "BTCUSDT - Ichimoku 4H: LONG"
                    msg = f"{symbol} - Ichimoku {tf_label.upper()}: {signal.replace('ichimoku_', '').upper()}"
                    try:
                        await channel.send(msg)
                        print(f"Inviato: {msg}")
                    except Exception as e:
                        print(f"[ERROR] Impossibile inviare il messaggio per {symbol} {tf_label}: {e}")
        await asyncio.sleep(60)  # Ripeti la scansione ogni 60 secondi

# ================================
# AVVIO DEL BOT
# ================================
client.run(DISCORD_TOKEN)
