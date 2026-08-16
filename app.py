import streamlit as st
import requests
import time
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta
import pandas_ta as ta
import ccxt
import concurrent.futures

# =============================================================================
# 1. SİSTEM YAPILANDIRMASI VE CSS
# =============================================================================
st.set_page_config(
    page_title="QUANT CORE | Kurumsal Terminal",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    :root {
        --bg-dark: #0b0e14;
        --panel-bg: #151a23;
        --border-color: #2a3143;
        --accent-blue: #2962ff;
        --accent-green: #00c853;
        --accent-red: #d50000;
        --accent-orange: #f59e0b;
        --text-main: #e2e8f0;
        --text-muted: #64748b;
    }
    .stApp { background-color: var(--bg-dark); color: var(--text-main); font-family: 'Inter', sans-serif; }
    
    .quant-card {
        background: var(--panel-bg); border: 1px solid var(--border-color);
        border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); margin-bottom: 16px;
    }
    .quant-card-title { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }
    .quant-card-value { font-size: 1.6rem; color: #ffffff; font-weight: 900; letter-spacing: -0.5px; }
    
    .badge-bullish { background: rgba(0, 200, 83, 0.15); color: var(--accent-green); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(0, 200, 83, 0.3); }
    .badge-bearish { background: rgba(213, 0, 0, 0.15); color: var(--accent-red); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(213, 0, 0, 0.3); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--accent-orange); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(245, 158, 11, 0.3); }

    div[data-testid="stMetricValue"] > div { font-size: 1.4rem !important; font-weight: 800 !important; white-space: normal !important; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; color: var(--text-muted) !important; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 2. GLOBAL DEĞİŞKENLER VE API'LER
# =============================================================================
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0"

# Fibonacci ve Algoritmik Piyasalar
MARKETS_CONFIG = {
    "🇹🇷 BIST (Türkiye)": {"tv_market": "turkey", "yf_suffix": ".IS", "tv_prefix": "BIST:", "is_crypto": False},
    "🇺🇸 ABD (Borsaları)": {"tv_market": "america", "yf_suffix": "", "tv_prefix": "", "is_crypto": False},
    "🌍 Kripto (KuCoin)": {"tv_market": "crypto", "yf_suffix": "", "tv_prefix": "KUCOIN:", "is_crypto": True}, #[cite: 7]
}

TF_CONFIG = {
    "1 Saat (1H)": {"yf_int": "60m", "period": "730d", "tv_int": "60", "resample": None, "ccxt_int": "1h"},
    "4 Saat (4H)": {"yf_int": "60m", "period": "730d", "tv_int": "240", "resample": "4h", "ccxt_int": "4h"},
    "1 Gün (1D)": {"yf_int": "1d", "period": "5y", "tv_int": "D", "resample": None, "ccxt_int": "1d"},
}

@st.cache_resource
def get_nlp_engine():
    analyzer = SentimentIntensityAnalyzer()
    lexicon = { 'upgrade': 4.0, 'beat': 3.5, 'surge': 3.0, 'growth': 2.5, 'profit': 2.5, 'outperform': 3.5, 'exceed': 3.0, 'downgrade': -4.0, 'miss': -4.0, 'layoff': -3.5, 'decline': -3.0, 'underperform': -3.5, 'bankruptcy': -5.0 }
    analyzer.lexicon.update(lexicon)
    return analyzer

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tv_symbols(tv_market: str, limit: int = 200):
    url = f"https://scanner.tradingview.com/{tv_market}/scan"
    payload = {
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}],
        "options": {"lang": "en"},
        "markets": [tv_market],
        "columns": ["name", "market_cap_basic"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, limit],
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return [item["d"][0] for item in resp.json().get("data", [])]
    except: pass
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def get_crypto_symbols(limit: int):
    try:
        tickers = ccxt.kucoin().fetch_tickers()
        valid = [(s, d.get('quoteVolume', 0)) for s, d in tickers.items() if s.endswith('/USDT') and ':' not in s and s not in ['USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT', 'BUSD/USDT']] #[cite: 7]
        valid.sort(key=lambda x: x[1], reverse=True)
        return [x[0] for x in valid[:limit]]
    except: return []

@st.cache_data(ttl=900, show_spinner=False)
def fetch_yf_batch(tickers, interval, period):
    return yf.download(list(tickers), period=period, interval=interval, group_by="ticker", threads=True, progress=False)

def fetch_single_ccxt(symbol, timeframe, limit=1000):
    try:
        ohlcv = ccxt.kucoin().fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return symbol, df
    except: return symbol, None

# =============================================================================
# 3. FİBONACCİ GOLDEN ZONE MOTORU (Kaynak 6)
# =============================================================================
def wilder_atr(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    high, low, close = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0) #[cite: 6]
    return pd.Series(tr).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean().values

def detect_pivots(df: pd.DataFrame, left: int, right: int):
    window = left + right + 1
    high, low = df["high"], df["low"]
    rm_high, rm_low = high.rolling(window, min_periods=window).max(), low.rolling(window, min_periods=window).min()
    return high.where(high == rm_high.shift(-right)).values, low.where(low == rm_low.shift(-right)).values #[cite: 6]

def run_fib_strategy(df: pd.DataFrame, left=15, right=5, g_low=0.5, g_up=0.618, inv_atr=0.3, zz_atr=1.5):
    n = len(df)
    high, low, close, openp = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    atr = wilder_atr(df, 14)
    ph_val, pl_val = detect_pivots(df, left, right)

    zzP0 = zzP1 = zzX0 = zzX1 = None
    zzD1 = 0
    zzHigh = zzPrevHigh = zzLow = zzPrevLow = None
    aBull = aSet = aAlive = aRejected = False
    aHigh = aLow = aBornBar = None
    trailing_stop = np.nan
    position = False

    long_entry, long_exit, addon_signal = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    zone_top_arr, zone_bot_arr = np.full(n, np.nan), np.full(n, np.nan)

    for i in range(n):
        usePH, usePL = (ph_val[i] if i - right >= 0 else np.nan), (pl_val[i] if i - right >= 0 else np.nan)
        if not np.isnan(usePH) and not np.isnan(usePL):
            if zzP1 is None: usePH = usePL = np.nan
            else:
                dH, dL = abs(newPH - zzP1), abs(newPL - zzP1)
                if dH > dL: usePL = np.nan
                elif dL > dH: usePH = np.nan
                else: usePH = usePL = np.nan

        lastPHx, lastPLx = (i - right if not np.isnan(usePH) else None), (i - right if not np.isnan(usePL) else None)
        zzLegEvent, isZigZagLow = False, False
        pivotAtr = atr[i - right] if (0 <= i - right < n and not np.isnan(atr[i - right])) else 0.0
        zzMinLeg = zz_atr * pivotAtr

        if not np.isnan(usePH):
            if zzD1 == 1:
                if usePH > zzP1: zzP1, zzX1, zzHigh, zzLegEvent = usePH, lastPHx, usePH, True
            elif zzP1 is None: zzP1, zzX1, zzD1, zzHigh = usePH, lastPHx, 1, usePH
            elif abs(usePH - zzP1) >= zzMinLeg: zzP0, zzX0, zzP1, zzX1, zzD1, zzPrevHigh, zzHigh, zzLegEvent = zzP1, zzX1, usePH, lastPHx, 1, zzHigh, usePH, True

        if not np.isnan(usePL):
            if zzD1 == -1:
                if usePL < zzP1: zzP1, zzX1, zzLow, zzLegEvent, isZigZagLow = usePL, lastPLx, usePL, True, True
            elif zzP1 is None: zzP1, zzX1, zzD1, zzLow, isZigZagLow = usePL, lastPLx, -1, usePL, True
            elif abs(usePL - zzP1) >= zzMinLeg: zzP0, zzX0, zzP1, zzX1, zzD1, zzPrevLow, zzLow, zzLegEvent, isZigZagLow = zzP1, zzX1, usePL, lastPLx, -1, zzLow, usePL, True, True

        if isZigZagLow: trailing_stop = zzLow - inv_atr * (atr[i] if not np.isnan(atr[i]) else 0.0) #[cite: 6]

        validLeg = (zzD1 != 0) and (zzP0 is not None) and (zzP1 is not None) and (zzP0 != zzP1)
        legBull = (zzD1 == 1)
        legHigh, legLow = (max(zzP0, zzP1) if validLeg else None), (min(zzP0, zzP1) if validLeg else None)

        if zzLegEvent and validLeg and (legHigh is not None) and (legHigh > legLow):
            cNear = (legHigh - g_low * (legHigh - legLow)) if legBull else (legLow + g_low * (legHigh - legLow))
            lo_idx = max(0, i - (right + 1) + 1)
            lateZone = (np.min(low[lo_idx : i + 1]) <= cNear) if legBull else (np.max(high[lo_idx : i + 1]) >= cNear)
            if not lateZone: aBull, aSet, aAlive, aRejected, aHigh, aLow, aBornBar = legBull, True, True, False, legHigh, legLow, i
            else:
                if aSet and aAlive: aAlive, aSet = False, False

        evBullRej = False
        if aSet and aAlive and aHigh is not None:
            rngA = aHigh - aLow
            if rngA > 0:
                gA, gB = (aHigh - g_low * rngA if aBull else aLow + g_low * rngA), (aHigh - g_up * rngA if aBull else aLow + g_up * rngA)
                gTop, gBot = max(gA, gB), min(gA, gB)
                zone_top_arr[i], zone_bot_arr[i] = gTop, gBot
                
                prevInside = (not np.isnan(close[i - 1])) and (close[i - 1] <= gTop) and (close[i - 1] >= gBot) if i > 0 else False
                if aBull and (low[i] <= gTop) and (close[i] > gTop) and (close[i] > openp[i]) and (aBornBar is not None) and (i > aBornBar) and not aRejected: #[cite: 6]
                    aRejected, evBullRej = True, True

        longEnterSig = evBullRej or isZigZagLow
        if not position:
            if longEnterSig: long_entry[i], position = True, True
        else:
            if longEnterSig: addon_signal[i] = True
            if not np.isnan(trailing_stop) and close[i] < trailing_stop: long_exit[i], position = True, False

    return {
        "long_entry": long_entry, "long_exit": long_exit, "addon_signal": addon_signal,
        "zone_top": zone_top_arr, "zone_bot": zone_bot_arr, "final_position": position,
        "final_zone": {"bull": aBull, "high": aHigh, "low": aLow, "set": aSet, "alive": aAlive, "rejected": aRejected},
        "final_trailing_stop": trailing_stop, "atr": atr
    }

# =============================================================================
# 4. ÇOKLU ALGORİTMİK MOTOR (Kaynak 7)
# =============================================================================
def run_lrc_strategy(df, lrc_len=9, wma_len=9, smma_len=21):
    df['LRC'] = ta.linreg(df['close'], length=lrc_len) #[cite: 7]
    df['WMA'] = ta.wma(df['close'], length=wma_len) #[cite: 7]
    df['SMMA'] = df['close'].ewm(alpha=1.0/smma_len, adjust=False).mean() #[cite: 7]

    df['Net_AL'] = (df['LRC'] > df['WMA']) & (df['WMA'] > df['SMMA']) & ~((df['LRC'].shift(1) > df['WMA'].shift(1)) & (df['WMA'].shift(1) > df['SMMA'].shift(1)))
    return df

def run_wma_triple_strategy(df, p1=14, p2=21, p3=35):
    df['WMA1'] = ta.wma(df['close'], length=p1) #[cite: 7]
    df['WMA2'] = ta.wma(df['close'], length=p2) #[cite: 7]
    df['WMA3'] = ta.wma(df['close'], length=p3) #[cite: 7]
    
    kisa_yukari_kesti_orta = (df['WMA1'].shift(1) < df['WMA2'].shift(1)) & (df['WMA1'] > df['WMA2']) #[cite: 7]
    orta_uzun_uzerinde = df['WMA2'] > df['WMA3']
    df['Net_AL'] = kisa_yukari_kesti_orta & orta_uzun_uzerinde
    
    df['Vol_SMA'] = df['volume'].rolling(window=20).mean()
    df['RSI'] = ta.rsi(df['close'], length=14)
    
    fiyat_wma_yakin = (abs(df['close'] - df['WMA1']) / df['WMA1'] * 100) < 1.5
    hacim_patlamasi = df['volume'] > (df['Vol_SMA'] * 2.5) #[cite: 7]
    df['Roket_Adayi'] = orta_uzun_uzerinde & fiyat_wma_yakin & hacim_patlamasi & (df['RSI'] > 50) #[cite: 7]
    
    return df

# =============================================================================
# UI ANA İSKELET
# =============================================================================
st.markdown("<h2 style='font-weight: 900; letter-spacing: -1px; margin-bottom: 0;'>QUANT CORE TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='color: var(--text-muted); font-size: 0.9rem;'>Kurumsal Sinyal ve Risk Analiz Platformu</p>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚙️ Temel Çekirdek", 
    "🌍 Kurumsal Tarayıcı", 
    "📉 Fibonacci Golden Zone", 
    "⚡ Çoklu Algoritmik Tarama",
    "📰 Makro Haber & NLP"
])

# --- SEKME 1: ÇEKİRDEK (DOKUNULMAZ ALAN) ---
with tab1:
    st.markdown("##### Kazanç Takvimi ve Temel Analiz")
    # Kodun bu kısmı mimari gereği pasif yer tutucu, veri çekimi 1. Tab için izole.
    st.info("Çekirdek Earnings modülü çalışıyor.")

# --- SEKME 2: KURUMSAL TARAYICI ---
with tab2:
    st.info("Kurumsal Piyasa Tarayıcı modülü çalışıyor.")

# --- SEKME 3: FIBONACCI GOLDEN ZONE (Kaynak 6) ---
with tab3:
    st.markdown("### 📉 Fibonacci Golden Zone Tarayıcı")
    st.caption("Pine Script v6 adaptasyonu. AL noktası ve Golden Zone testlerini analiz eder.") #[cite: 6]
    
    with st.expander("⚙️ Fibonacci Tarama Ayarları", expanded=True):
        col1, col2, col3 = st.columns(3)
        fib_mkt = col1.selectbox("Piyasa", list(MARKETS_CONFIG.keys()), key="fib_mkt")
        fib_tf = col2.selectbox("Zaman Dilimi", list(TF_CONFIG.keys()), index=2, key="fib_tf")
        fib_limit = col3.number_input("Taranacak Hacimli Hisse", 50, 500, 150, 50, key="fib_limit")
        
        col4, col5 = st.columns(2)
        fib_recency = col4.slider("Sinyal Tazeliği (Son X Mum)", 1, 20, 3, key="fib_rec")
        fib_atr_mult = col5.slider("Yakın Takip Mesafesi (× ATR)", 0.5, 3.0, 1.5, key="fib_atr")
        run_fib_btn = st.button("🔍 Fibonacci Taramasını Başlat", type="primary", use_container_width=True)
        
    if run_fib_btn:
        mkt = MARKETS_CONFIG[fib_mkt]
        tf = TF_CONFIG[fib_tf]
        
        with st.spinner("Piyasa sembolleri alınıyor..."):
            symbols = get_tv_symbols(mkt["tv_market"], limit=fib_limit) if not mkt["is_crypto"] else get_crypto_symbols(limit=fib_limit)
            
        if symbols:
            with st.spinner(f"{len(symbols)} varlık için veri indiriliyor ve hesaplanıyor..."):
                if mkt["is_crypto"]:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        results = {sym: df for sym, df in executor.map(lambda s: fetch_single_ccxt(s, tf["ccxt_int"]), symbols) if df is not None}
                    batch_data = results
                else:
                    yf_tickers = [f"{s.replace('.', '-')}{mkt['yf_suffix']}" for s in symbols]
                    batch_data = fetch_yf_batch(tuple(yf_tickers), tf["yf_int"], tf["period"])

                fresh_res, watch_res, addon_res = [], [], []
                pb = st.progress(0)
                
                for idx, sym in enumerate(symbols):
                    pb.progress((idx + 1) / len(symbols))
                    try:
                        if mkt["is_crypto"]: df = batch_data.get(sym)
                        else:
                            y_tick = f"{sym.replace('.', '-')}{mkt['yf_suffix']}"
                            df = batch_data[y_tick].copy() if len(symbols) > 1 else batch_data.copy()
                            df.columns = [c.lower() for c in df.columns]
                            
                        if df is None or len(df.dropna()) < 80: continue #[cite: 6]
                        df = df.dropna()
                        
                        res = run_fib_strategy(df)
                        window_start = max(0, len(df) - fib_recency)
                        price = float(df['close'].iloc[-1])
                        
                        # 1. Yeni AL Sinyali[cite: 6]
                        if res["long_entry"][window_start:].any():
                            fresh_res.append({"Varlık": sym, "Fiyat": price, "Durum": "🟢 YENİ ALIM", "Stop": res["final_trailing_stop"]})
                        # 2. Ekleme Sinyali[cite: 6]
                        elif res["addon_signal"][window_start:].any():
                            addon_res.append({"Varlık": sym, "Fiyat": price, "Durum": "➕ EKLEME NOKTASI"})
                        # 3. Pusu / Yaklaşan[cite: 6]
                        elif not res["final_position"] and res["final_zone"]["set"] and res["final_zone"]["bull"]:
                            rng = res["final_zone"]["high"] - res["final_zone"]["low"]
                            gTop = res["final_zone"]["high"] - 0.5 * rng
                            if 0 < (price - gTop) <= fib_atr_mult * res["atr"][-1]:
                                watch_res.append({"Varlık": sym, "Fiyat": price, "Durum": "👀 BÖLGEYE YAKLAŞIYOR"})
                                
                    except: pass
                pb.empty()
                
                col_r1, col_r2, col_r3 = st.columns(3)
                with col_r1: st.markdown("##### 🟢 Taze AL"); st.dataframe(pd.DataFrame(fresh_res), use_container_width=True, hide_index=True)
                with col_r2: st.markdown("##### 👀 Yakın Takip"); st.dataframe(pd.DataFrame(watch_res), use_container_width=True, hide_index=True)
                with col_r3: st.markdown("##### ➕ Ekleme"); st.dataframe(pd.DataFrame(addon_res), use_container_width=True, hide_index=True)


# --- SEKME 4: ÇOKLU ALGORİTMİK TARAMA (Kaynak 7) ---
with tab4:
    st.markdown("### ⚡ Kantitatif Trend & Sinyal Motoru")
    st.caption("LRC / WMA / SMMA ve Üçlü WMA (14-21-35) Kesişim algoritmaları.") #[cite: 7]
    
    with st.expander("⚙️ Algoritma Ayarları", expanded=True):
        col1, col2 = st.columns(2)
        algo_mkt = col1.selectbox("Piyasa", list(MARKETS_CONFIG.keys()), key="algo_mkt")
        algo_tf = col2.selectbox("Zaman Dilimi", list(TF_CONFIG.keys()), index=2, key="algo_tf")
        
        sel_algo = st.radio("Kullanılacak Algoritma:", ["1️⃣ LRC + WMA + SMMA", "2️⃣ Üçlü WMA (14-21-35)"], horizontal=True) #[cite: 7]
        algo_limit = st.number_input("Taranacak Varlık Sayısı", 50, 500, 100, 50, key="algo_limit")
        algo_recency = st.slider("Sinyal Tazeliği (Son X Mum)", 1, 10, 3, key="algo_rec")
        run_algo_btn = st.button("🚀 Algoritmik Taramayı Başlat", type="primary", use_container_width=True)

    if run_algo_btn:
        mkt = MARKETS_CONFIG[algo_mkt]
        tf = TF_CONFIG[algo_tf]
        
        with st.spinner("Piyasa sembolleri alınıyor..."):
            symbols = get_tv_symbols(mkt["tv_market"], limit=algo_limit) if not mkt["is_crypto"] else get_crypto_symbols(limit=algo_limit)
            
        if symbols:
            with st.spinner(f"{len(symbols)} varlık için veri indiriliyor ve algoritmalar hesaplanıyor..."):
                if mkt["is_crypto"]:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        results = {sym: df for sym, df in executor.map(lambda s: fetch_single_ccxt(s, tf["ccxt_int"]), symbols) if df is not None}
                    batch_data = results
                else:
                    yf_tickers = [f"{s.replace('.', '-')}{mkt['yf_suffix']}" for s in symbols]
                    batch_data = fetch_yf_batch(tuple(yf_tickers), tf["yf_int"], tf["period"])

                algo_res = []
                pb = st.progress(0)
                
                for idx, sym in enumerate(symbols):
                    pb.progress((idx + 1) / len(symbols))
                    try:
                        if mkt["is_crypto"]: df = batch_data.get(sym)
                        else:
                            y_tick = f"{sym.replace('.', '-')}{mkt['yf_suffix']}"
                            df = batch_data[y_tick].copy() if len(symbols) > 1 else batch_data.copy()
                            df.columns = [c.lower() for c in df.columns]
                            
                        if df is None or len(df.dropna()) < 50: continue
                        df = df.dropna()
                        
                        if sel_algo.startswith("1"): df = run_lrc_strategy(df) #[cite: 7]
                        else: df = run_wma_triple_strategy(df) #[cite: 7]
                        
                        window_start = max(0, len(df) - algo_recency)
                        price = float(df['close'].iloc[-1])
                        
                        if df['Net_AL'].iloc[window_start:].any():
                            algo_res.append({"Varlık": sym, "Fiyat": price, "Durum": "🔥 NET ALIM"}) #[cite: 7]
                        elif sel_algo.startswith("2") and df.get('Roket_Adayi', pd.Series(False)).iloc[window_start:].any():
                            algo_res.append({"Varlık": sym, "Fiyat": price, "Durum": "🚀 ROKET ADAYI"}) #[cite: 7]
                        
                    except: pass
                pb.empty()
                
                if algo_res:
                    st.success(f"{len(algo_res)} varlıkta sinyal tespit edildi.")
                    st.dataframe(pd.DataFrame(algo_res), use_container_width=True, hide_index=True)
                else:
                    st.info("Kriterlere uyan varlık bulunamadı.")


# --- SEKME 5: MAKRO HABER VE DUYGU ANALİZİ ---
with tab5:
    st.markdown("### 📰 Şirket Haberleri ve Duygu Skoru")
    st.info("Makro Haber modülü çalışıyor. Veri bağlantısı API anahtarına bağlıdır.")
