import streamlit as st
import requests
import time
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta
import pandas_ta as ta
import ccxt
import concurrent.futures

# =============================================================================
# 1. SİSTEM YAPILANDIRMASI VE HAFIZA YÖNETİMİ (SESSION STATE)
# =============================================================================
st.set_page_config(
    page_title="QUANT CORE | Kurumsal Terminal",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Tab-1 Çekirdek Haber Hafızası
if "core_news_cache" not in st.session_state:
    st.session_state.core_news_cache = {}

# Tab-2 Kurumsal Tarayıcı Hafızası
if "tab2_scanned" not in st.session_state:
    st.session_state.tab2_scanned = False
    st.session_state.tab2_df = pd.DataFrame()

# Tab-3 Fibonacci Hafızası 
if 'fresh_results' not in st.session_state: st.session_state.fresh_results = []
if 'watch_results' not in st.session_state: st.session_state.watch_results = []
if 'addon_results' not in st.session_state: st.session_state.addon_results = []
if 'scan_meta' not in st.session_state: st.session_state.scan_meta = {}

# Tab-4 Çoklu Algoritma Hafızası 
if 'tarama_tamamlandi' not in st.session_state: st.session_state['tarama_tamamlandi'] = False
if 'sonuclar_hafiza' not in st.session_state: st.session_state['sonuclar_hafiza'] = []
if 'grafik_hafiza' not in st.session_state: st.session_state['grafik_hafiza'] = {}
if 'secili_strateji_ismi' not in st.session_state: st.session_state['secili_strateji_ismi'] = ""

st.markdown("""
<style>
    :root {
        --bg-dark: #0b0e14; --panel-bg: #151a23; --border-color: #2a3143;
        --accent-blue: #2962ff; --accent-green: #00c853; --accent-red: #d50000;
        --accent-orange: #f59e0b; --text-main: #e2e8f0; --text-muted: #64748b;
    }
    .stApp { background-color: var(--bg-dark); color: var(--text-main); font-family: 'Inter', sans-serif; }
    .quant-card { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); margin-bottom: 16px; }
    .quant-card-title { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }
    .quant-card-value { font-size: 1.6rem; color: #ffffff; font-weight: 900; letter-spacing: -0.5px; }
    .badge-bullish { background: rgba(0, 200, 83, 0.15); color: var(--accent-green); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(0, 200, 83, 0.3); }
    .badge-bearish { background: rgba(213, 0, 0, 0.15); color: var(--accent-red); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(213, 0, 0, 0.3); }
    .info-box { background: rgba(41, 98, 255, 0.1); border-left: 4px solid var(--accent-blue); padding: 12px; margin-bottom: 16px; border-radius: 4px; font-size: 0.9rem; line-height: 1.5; }
    div[data-testid="stMetricValue"] > div { font-size: 1.4rem !important; font-weight: 800 !important; white-space: normal !important; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; color: var(--text-muted) !important; text-transform: uppercase; }
    .terminal-box { background-color: #000000; color: #00ff00; font-family: 'Courier New', Courier, monospace; padding: 10px; border-radius: 5px; height: 200px; overflow-y: auto; border: 1px solid #333; margin-bottom: 15px;}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 2. ÇEKİRDEK (TAB-1) & KURUMSAL (TAB-2) FONKSİYONLARI 
# =============================================================================
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0"

@st.cache_resource
def get_nlp_engine():
    analyzer = SentimentIntensityAnalyzer()
    lexicon = { 'upgrade': 4.0, 'beat': 3.5, 'surge': 3.0, 'growth': 2.5, 'profit': 2.5, 'outperform': 3.5, 'exceed': 3.0, 'downgrade': -4.0, 'miss': -4.0, 'layoff': -3.5, 'decline': -3.0, 'underperform': -3.5, 'bankruptcy': -5.0 }
    analyzer.lexicon.update(lexicon)
    return analyzer

def fetch_core_earnings(terminal_ui):
    terminal_ui.code("[*] TradingView Kazanç Takvimi ve Hedef Fiyat API'sine bağlanılıyor...\n", language="bash")
    time.sleep(0.5)
    url = "https://scanner.tradingview.com/america/scan"
    now = int(time.time())
    one_month_later = now + (30 * 24 * 60 * 60)
    
    # TV'den bilançosu yaklaşan EN BÜYÜK 25 hisseyi ve analist hedeflerini çekiyoruz
    payload = {
        "filter": [
            {"left": "earnings_release_next_date", "operation": "in_range", "right": [now, one_month_later]}, 
            {"left": "earnings_per_share_forecast_next_fq", "operation": "greater", "right": 0}
        ],
        "markets": ["america"],
        "columns": ["name", "earnings_per_share_forecast_next_fq", "earnings_release_next_date", "market_cap_basic", "close", "price_target_price_mean"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 25] # Hızlı haber taraması için limit 25
    }
    
    analyzer = get_nlp_engine()
    st.session_state.core_news_cache = {}
    
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json().get('data', [])
            terminal_ui.code(f"[*] TradingView'dan {len(data)} büyük hisse alındı.\n[*] Finnhub üzerinden her hisse için NLP Haber Analizi başlatılıyor...\n", language="bash")
            
            parsed = []
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            for i, item in enumerate(data):
                sym = item['s'].split(':')[-1]
                d = item['d']
                eps, date_ts, mcap, close, target_mean = d[1], d[2], d[3] or 0, d[4], d[5]
                
                m_cap_str = f"${mcap/1e9:.2f}B" if mcap >= 1e9 else (f"${mcap/1e6:.2f}M" if mcap >= 1e6 else f"${mcap:.2f}")
                target_str = f"${target_mean:.2f}" if target_mean else "Belirsiz"
                
                # Haberleri Çek ve Analiz Et
                news_count = 0
                signal_str = "NÖTR ⚖️"
                
                try:
                    news_url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={start_date}&to={end_date}&token={FINNHUB_API_KEY}"
                    news_data = requests.get(news_url).json()
                    
                    if news_data and isinstance(news_data, list):
                        news_count = len(news_data)
                        st.session_state.core_news_cache[sym] = news_data[:5] # Detay paneli için son 5 haberi kaydet
                        
                        if news_count > 0:
                            # Son haberin duygusal skoru
                            latest_score = analyzer.polarity_scores(news_data[0]['headline'])['compound']
                            if latest_score >= 0.15: signal_str = "AL 🚀"
                            elif latest_score <= -0.15: signal_str = "SAT ⚠️"
                except:
                    pass
                
                parsed.append({
                    "Hisse": sym, 
                    "Fiyat": f"${close:.2f}",
                    "Analist Hedefi": target_str,
                    "Tarih": time.strftime('%d-%m-%Y', time.localtime(date_ts)), 
                    "Haber Adedi": news_count,
                    "Son Haber Sinyali": signal_str,
                    "Detaylar": "Aşağıdan Seçin 👇"
                })
                
                terminal_ui.code(f"   [{i+1}/{len(data)}] {sym} analiz edildi. Haber: {news_count} | Sinyal: {signal_str}", language="bash")
                
            terminal_ui.code(f"\n[+] İşlem Başarılı!\n", language="bash")
            return pd.DataFrame(parsed)
    except Exception as e: 
        terminal_ui.code(f"[!] HATA OLUŞTU: {e}\n", language="bash")
    return pd.DataFrame()

def fetch_institutional_screener(terminal_ui):
    terminal_ui.code("[*] Kurumsal Tarayıcı: TradingView ABD Borsaları sorgulanıyor...\n", language="bash")
    time.sleep(0.5)
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}],
        "options": {"lang": "en"},
        "markets": ["america"],
        "columns": ["name", "close", "price_52_week_low", "price_52_week_high", "Recommend.All", "market_cap_basic", "price_target_price_mean", "volume"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 5000]
    }
    try:
        resp = requests.post(url, json=payload)
        terminal_ui.code(f"[*] API Yanıtı: {resp.status_code}. Matematiksel modellemeler ve Kurumsal Karar Gerekçeleri oluşturuluyor...\n", language="bash")
        if resp.status_code == 200:
            parsed = []
            for item in resp.json().get('data', []):
                sym, d = item['s'].split(':')[-1], item['d']
                close = float(d[1]) if len(d) > 1 and d[1] is not None else 0.0
                low52 = float(d[2]) if len(d) > 2 and d[2] is not None else 0.0
                target_mean = float(d[6]) if len(d) > 6 and d[6] is not None else 0.0
                tv_signal = d[4] if len(d) > 4 and d[4] is not None else 0.0
                
                dip_farki = ((close - low52) / low52) * 100 if low52 > 0 else 0
                target_pot = ((target_mean - close) / close) * 100 if close > 0 else 0
                
                # Karar Gerekçesi (Neden Alınmalı?) Oluşturma
                reasons = []
                if dip_farki <= 10.0: reasons.append("52W Dibe Çok Yakın (Düşük Risk)")
                if target_pot >= 20.0: reasons.append(f"Analistlere Göre %{target_pot:.0f} İskontolu")
                if tv_signal >= 0.5: reasons.append("Güçlü Kurumsal Para Girişi")
                
                rationale = " + ".join(reasons) if reasons else "Standart Trend Takibi"
                
                parsed.append({
                    "Ticker": sym, 
                    "Price": close, 
                    "Dip_Fark_Pct": dip_farki, 
                    "Upside_Pct": target_pot, 
                    "TV_Signal": tv_signal, 
                    "Neden Alınmalı? (Stratejik Gerekçe)": rationale
                })
            terminal_ui.code(f"[+] Başarılı! Toplam {len(parsed)} hisse skorlandı.\n", language="bash")
            return pd.DataFrame(parsed)
    except Exception as e: 
        terminal_ui.code(f"[!] HATA: {e}\n", language="bash")
    return pd.DataFrame()

# =============================================================================
# 3. FİBONACCİ GOLDEN ZONE FONKSİYONLARI 
# =============================================================================
FIB_MARKET_CONFIGS = {
    "🇹🇷 BIST (Türkiye)": {"tv_market": "turkey", "yf_suffix": ".IS", "tv_prefix": "BIST:"},
    "🇺🇸 ABD (NASDAQ / NYSE)": {"tv_market": "america", "yf_suffix": "", "tv_prefix": ""},
}
FIB_TIMEFRAME_CONFIGS = {
    "1 Saat (1H)":  {"yf_interval": "60m", "resample": None, "period": "730d", "tv_interval": "60"},
    "2 Saat (2H)":  {"yf_interval": "60m", "resample": "2h", "period": "730d", "tv_interval": "120"},
    "4 Saat (4H)":  {"yf_interval": "60m", "resample": "4h", "period": "730d", "tv_interval": "240"},
    "1 Gün (1D)":   {"yf_interval": "1d",  "resample": None, "period": "5y",  "tv_interval": "D"},
    "1 Hafta (1W)": {"yf_interval": "1wk", "resample": None, "period": "10y", "tv_interval": "W"},
}
MIN_BARS_REQUIRED = 80

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_market_symbols(tv_market: str, limit: int = 5000):
    url = f"https://scanner.tradingview.com/{tv_market}/scan"
    payload = {"filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}], "options": {"lang": "en"}, "markets": [tv_market], "symbols": {"query": {"types": []}, "tickers": []}, "columns": ["name", "market_cap_basic"], "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}, "range": [0, limit]}
    try:
        resp = requests.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if resp.status_code == 200: return [item["d"][0] for item in resp.json().get("data", [])]
    except: pass
    return []

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_batch(tickers: tuple, yf_interval: str, period: str):
    try: return yf.download(list(tickers), period=period, interval=yf_interval, group_by="ticker", threads=True, progress=False, auto_adjust=False)
    except: return pd.DataFrame()

def extract_symbol_df(batch: pd.DataFrame, yf_ticker: str, single_ticker: bool) -> pd.DataFrame:
    try:
        if single_ticker: df = batch.copy()
        else:
            if not hasattr(batch.columns, "levels") or yf_ticker not in batch.columns.levels[0]: return None
            df = batch[yf_ticker].copy()
        if df is None or df.empty: return None
        df.columns = [str(c).lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except: return None

def wilder_atr(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    high, low, close = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0)
    return pd.Series(tr).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean().values

def detect_pivots(df: pd.DataFrame, left: int, right: int):
    window = left + right + 1
    high, low = df["high"], df["low"]
    rm_high, rm_low = high.rolling(window, min_periods=window).max(), low.rolling(window, min_periods=window).min()
    return high.where(high == rm_high.shift(-right)).values, low.where(low == rm_low.shift(-right)).values

def run_strategy(df: pd.DataFrame, left: int = 15, right: int = 5, golden_lower: float = 0.5, golden_upper: float = 0.618, inv_buf_atr: float = 0.3, zz_dev_atr: float = 1.5, touch_wick: bool = True, skip_late: bool = True):
    n = len(df)
    high, low, close, openp = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float), df["open"].values.astype(float)
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
        newPH, newPL = (ph_val[i] if i - right >= 0 else np.nan), (pl_val[i] if i - right >= 0 else np.nan)
        usePH, usePL = newPH, newPL
        if not np.isnan(newPH) and not np.isnan(newPL):
            if zzP1 is None: usePH, usePL = np.nan, np.nan
            else:
                dH, dL = abs(usePH - zzP1), abs(usePL - zzP1)
                if dH > dL: usePL = np.nan
                elif dL > dH: usePH = np.nan
                else: usePH, usePL = np.nan, np.nan
        lastPHx, lastPLx = (i - right if not np.isnan(usePH) else None), (i - right if not np.isnan(usePL) else None)
        zzLegEvent, isZigZagLow = False, False
        pivot_atr_idx = i - right
        pivotAtr = atr[pivot_atr_idx] if (0 <= pivot_atr_idx < n and not np.isnan(atr[pivot_atr_idx])) else 0.0
        zzMinLeg = 0.0 if zz_dev_atr == 0.0 else zz_dev_atr * pivotAtr

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

        if isZigZagLow: trailing_stop = zzLow - inv_buf_atr * (atr[i] if not np.isnan(atr[i]) else 0.0)

        validLeg = (zzD1 != 0) and (zzP0 is not None) and (zzP1 is not None) and (zzP0 != zzP1)
        legBull = zzD1 == 1
        legHigh, legLow = (max(zzP0, zzP1) if validLeg else None), (min(zzP0, zzP1) if validLeg else None)
        candidateEvent = zzLegEvent and validLeg and (legHigh is not None) and (legHigh > legLow)

        if candidateEvent:
            dirBull = legBull
            cRng = legHigh - legLow
            cNear = (legHigh - near_ratio * cRng) if dirBull else (legLow + near_ratio * cRng)
            w = right + 1
            lo_idx = max(0, i - w + 1)
            if touch_wick:
                bullLate, bearLate = np.min(low[lo_idx : i + 1]) <= cNear, np.max(high[lo_idx : i + 1]) >= cNear
            else:
                bullLate, bearLate = np.min(close[lo_idx : i + 1]) <= cNear, np.max(close[lo_idx : i + 1]) >= cNear
            lateZone = bullLate if dirBull else bearLate
            if (not skip_late) or (not lateZone): aBull, aSet, aAlive, aRejected, aHigh, aLow, aBornBar = dirBull, True, True, False, legHigh, legLow, i
            else:
                if aSet and aAlive: aAlive, aSet = False, False

        evBullRej = False
        if aSet and aAlive and aHigh is not None:
            rngA = aHigh - aLow
            if rngA > 0:
                gA = (aHigh - golden_lower * rngA) if aBull else (aLow + golden_lower * rngA)
                gB = (aHigh - golden_upper * rngA) if aBull else (aLow + golden_upper * rngA)
                gTop, gBot = max(gA, gB), min(gA, gB)
                zone_top_arr[i], zone_bot_arr[i] = gTop, gBot
                
                prevInside = (not np.isnan(close[i - 1])) and (close[i - 1] <= gTop) and (close[i - 1] >= gBot) if i > 0 else False
                if aBull and (low[i] <= gTop) and (close[i] > gTop) and (close[i] > openp[i]) and (aBornBar is not None) and (i > aBornBar) and not aRejected:
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

def _golden_bounds(fz, g_lower, g_upper):
    if not fz["set"] or fz["high"] is None or fz["low"] is None: return np.nan, np.nan
    rng = fz["high"] - fz["low"]
    if rng <= 0: return np.nan, np.nan
    gA = fz["high"] - g_lower * rng if fz["bull"] else fz["low"] + g_lower * rng
    gB = fz["high"] - g_upper * rng if fz["bull"] else fz["low"] + g_upper * rng
    return min(gA, gB), max(gA, gB)

def build_chart(df: pd.DataFrame, res: dict, symbol: str, tf_label: str, show_bars: int = 250):
    n = len(df); show_n = min(show_bars, n); d = df.iloc[-show_n:]; idx0 = n - show_n
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=d.index, open=d["open"], high=d["high"], low=d["low"], close=d["close"], name=symbol, increasing_line_color="#10b981", decreasing_line_color="#ef4444"))
    entries = np.where(res["long_entry"][idx0:])[0]
    exits = np.where(res["long_exit"][idx0:])[0]
    if len(entries): fig.add_trace(go.Scatter(x=d.index[entries], y=d["low"].values[entries] * 0.99, mode="markers", marker=dict(symbol="triangle-up", size=13, color="#22c55e", line=dict(width=1, color="white")), name="AL"))
    if len(exits): fig.add_trace(go.Scatter(x=d.index[exits], y=d["high"].values[exits] * 1.01, mode="markers", marker=dict(symbol="triangle-down", size=13, color="#ef4444", line=dict(width=1, color="white")), name="SAT"))
    fz = res["final_zone"]
    if fz["set"] and fz["high"] is not None and fz["low"] is not None:
        rng = fz["high"] - fz["low"]
        if rng > 0:
            gA, gB = (fz["high"] - 0.5 * rng if fz["bull"] else fz["low"] + 0.5 * rng), (fz["high"] - 0.618 * rng if fz["bull"] else fz["low"] + 0.618 * rng)
            fig.add_hrect(y0=min(gA, gB), y1=max(gA, gB), fillcolor="rgba(217,119,6,0.18)", line_width=1, line_color="rgba(217,119,6,0.6)", annotation_text="GOLDEN ZONE", annotation_position="top left")
    ts = res.get("final_trailing_stop", np.nan)
    if not np.isnan(ts): fig.add_hline(y=ts, line_dash="dot", line_color="#facc15", annotation_text="Trailing Stop")
    fig.update_layout(template="plotly_dark", height=620, xaxis_rangeslider_visible=False, title=f"{symbol} — {tf_label}", margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    return fig

# =============================================================================
# 4. ÇOKLU ALGORİTMİK MOTOR FONKSİYONLARI 
# =============================================================================
ALGO_MARKETS = {
    "🇹🇷 BIST (Türkiye)": {"tv_market": "turkey", "yf_suffix": ".IS", "tv_prefix": "BIST:", "is_crypto": False},
    "🇺🇸 ABD (Borsaları)": {"tv_market": "america", "yf_suffix": "", "tv_prefix": "", "is_crypto": False},
    "🌍 Kripto (KuCoin)": {"tv_market": "crypto", "yf_suffix": "", "tv_prefix": "KUCOIN:", "is_crypto": True},
}
ALGO_TIMEFRAMES = {
    "1 Saat (1H)": {"yf_int": "60m", "period": "730d", "tv_int": "60", "ccxt_int": "1h"},
    "4 Saat (4H)": {"yf_int": "60m", "period": "730d", "tv_int": "240", "resample": "4h", "ccxt_int": "4h"}, 
    "1 Gün (1D)": {"yf_int": "1d", "period": "5y", "tv_int": "D", "ccxt_int": "1d"},
    "1 Hafta (1W)": {"yf_int": "1wk", "period": "10y", "tv_int": "W", "ccxt_int": "1w"},
}

@st.cache_data(ttl=3600, show_spinner=False)
def get_tv_symbols(tv_market: str, limit: int):
    url = f"https://scanner.tradingview.com/{tv_market}/scan"
    payload = {"filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}], "options": {"lang": "en"}, "markets": [tv_market], "symbols": {"query": {"types": []}, "tickers": []}, "columns": ["name", "market_cap_basic"], "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}, "range": [0, limit]}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200: return [item["d"][0] for item in resp.json().get("data", [])]
    except: pass
    return []

@st.cache_data(ttl=900, show_spinner=False)
def fetch_yf_data(tickers, interval, period):
    return yf.download(list(tickers), period=period, interval=interval, group_by="ticker", threads=True, progress=False)

@st.cache_data(ttl=3600, show_spinner=False)
def get_crypto_symbols(limit: int):
    exchange = ccxt.kucoin()
    try:
        tickers = exchange.fetch_tickers()
        excluded = ['USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT', 'BUSD/USDT', 'USDP/USDT']
        valid_pairs = [(sym, data.get('quoteVolume', 0)) for sym, data in tickers.items() if sym.endswith('/USDT') and sym not in excluded and ':' not in sym and data.get('quoteVolume', 0) is not None]
        valid_pairs.sort(key=lambda x: x[1], reverse=True)
        return [x[0] for x in valid_pairs[:limit]]
    except: return []

def fetch_single_ccxt(symbol, timeframe, limit=1500):
    exchange = ccxt.kucoin()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return symbol, df
    except: return symbol, None

@st.cache_data(ttl=300, show_spinner=False)
def fetch_ccxt_batch(symbols, timeframe):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for future in concurrent.futures.as_completed([executor.submit(fetch_single_ccxt, sym, timeframe) for sym in symbols]):
            sym, df = future.result()
            if df is not None and len(df) > 50: results[sym] = df
    return results

def run_lrc_strategy(df, lrc_len=9, wma_len=9, smma_len=21):
    df['LRC'], df['WMA'], df['SMMA'] = ta.linreg(df['close'], length=lrc_len), ta.wma(df['close'], length=wma_len), df['close'].ewm(alpha=1.0/smma_len, adjust=False).mean()
    trend_yukari, trend_asagi = (df['LRC'] > df['WMA']) & (df['WMA'] > df['SMMA']), (df['LRC'] < df['WMA']) & (df['WMA'] < df['SMMA'])
    durum = 0
    net_al, net_sat, durum_liste = [], [], []
    for i in range(len(df)):
        al, sat = trend_yukari.iloc[i] and (durum != 1), trend_asagi.iloc[i] and (durum != -1)
        if al: durum = 1
        elif sat: durum = -1
        net_al.append(al); net_sat.append(sat); durum_liste.append(durum)
    df['Net_AL'], df['Net_SAT'], df['Durum'] = net_al, net_sat, durum_liste
    return df

def run_wma_triple_strategy(df, p1=14, p2=21, p3=35):
    df['WMA1'], df['WMA2'], df['WMA3'] = ta.wma(df['close'], length=p1), ta.wma(df['close'], length=p2), ta.wma(df['close'], length=p3)
    wma1_prev, wma2_prev = df['WMA1'].shift(1), df['WMA2'].shift(1)
    df['Net_AL'] = ((wma1_prev < wma2_prev) & (df['WMA1'] > df['WMA2'])) & (df['WMA2'] > df['WMA3'])
    df['Yaklasan'] = (df['WMA1'] < df['WMA2']) & ((df['WMA2'] - df['WMA1']) < (wma2_prev - wma1_prev)) & (((df['WMA2'] - df['WMA1']) / df['WMA2'] * 100) < 1.5) & (df['WMA2'] > df['WMA3'])
    df['Vol_SMA'], df['RSI'] = df['volume'].rolling(window=20).mean(), ta.rsi(df['close'], length=14)
    df['Roket_Adayi'] = (df['WMA2'] > df['WMA3']) & ((abs(df['close'] - df['WMA1']) / df['WMA1'] * 100) < 1.5) & (df['volume'] > (df['Vol_SMA'] * 2.5)) & ((df['RSI'] > 50) & (df['RSI'] > df['RSI'].shift(1)))
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

# --- SEKME 1: ÇEKİRDEK KAZANÇ TAKVİMİ ---
with tab1:
    st.markdown("##### 🎯 Analist Destekli Kazanç Takvimi ve Haber Analizi")
    if st.button("Verileri Çek / Güncelle (Tab-1)"):
        term_ui1 = st.empty()
        df_core = fetch_core_earnings(term_ui1)
        if not df_core.empty:
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"<div class='quant-card'><div class='quant-card-title'>Taranan Hisse (Top 25)</div><div class='quant-card-value'>{len(df_core)}</div></div>", unsafe_allow_html=True)
            avg_eps = pd.to_numeric(df_core["Est. EPS"], errors='coerce').mean()
            c2.markdown(f"<div class='quant-card'><div class='quant-card-title'>Ortalama Est. EPS</div><div class='quant-card-value'>${avg_eps:.2f}</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='quant-card'><div class='quant-card-title'>Tarih Aralığı</div><div class='quant-card-value'>Gelecek 30 Gün</div></div>", unsafe_allow_html=True)
            
            st.dataframe(df_core, use_container_width=True, hide_index=True)
            
    # Tıklama yerine selectbox ile haber detaylarını gösterme mantığı
    if st.session_state.core_news_cache:
        st.write("---")
        st.markdown("##### 📰 Hisse Haber Detayları")
        selected_news_ticker = st.selectbox("Tablodaki sinyallere göre işlem yapmak için aşağıdan hisseyi seçip haber detaylarını ve analist beklentilerini görüntüleyin:", list(st.session_state.core_news_cache.keys()))
        
        if selected_news_ticker:
            news_items = st.session_state.core_news_cache[selected_news_ticker]
            if news_items:
                analyzer = get_nlp_engine()
                for item in news_items:
                    score = analyzer.polarity_scores(item['headline'])['compound']
                    if score >= 0.15: sentiment_ui = f"<span class='badge-bullish'>AL ({score:.2f})</span>"
                    elif score <= -0.15: sentiment_ui = f"<span class='badge-bearish'>SAT ({score:.2f})</span>"
                    else: sentiment_ui = f"<span style='color: var(--text-muted); font-size: 0.75rem; font-weight: bold;'>NÖTR ({score:.2f})</span>"
                    
                    st.markdown(f"""
                    <div class='quant-card' style='padding: 12px;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;'>
                            <a href='{item['url']}' target='_blank' style='color: white; font-weight: 700; text-decoration: none; font-size: 1rem;'>{item['headline']}</a>
                            {sentiment_ui}
                        </div>
                        <div style='font-size: 0.75rem; color: var(--text-muted);'>{item['source']} • {datetime.fromtimestamp(item['datetime']).strftime('%d %b %Y, %H:%M')}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Bu hisse için son 7 güne ait haber bulunamadı.")

# --- SEKME 2: KURUMSAL TARAYICI ---
with tab2:
    st.markdown("##### 🌍 Kurumsal Piyasa Tarayıcısı (ABD Native)")
    st.markdown("""
    <div class='info-box'>
        <b>Bu Tarayıcı Nasıl Çalışır ve Neden Alım Yapmalısınız?</b><br>
        Kurumsal fon yöneticilerinin kullandığı <b>Asimetrik Risk/Getiri</b> modeline göre çalışır. Bir hissenin sadece düşmüş olması yetmez; dönüş sinyali (Momentum) ve analist onayı gerektirir.<br>
        • <b>52W Dibe Çok Yakın:</b> Düşüş trendi bitmiş, riskin en düşük olduğu giriş fırsatı.<br>
        • <b>İskontolu (Upside):</b> Wall Street analistlerinin belirlediği hedef fiyata göre en az %20 yukarı potansiyel barındırır.<br>
        • <b>Kurumsal Para Girişi:</b> TradingView konsensüsü güçlü "AL" veriyorsa momentum destekleniyor demektir.
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Piyasayı Tara (Tab-2)"):
        term_ui2 = st.empty()
        st.session_state.tab2_df = fetch_institutional_screener(term_ui2)
        st.session_state.tab2_scanned = True
        
    if st.session_state.tab2_scanned and not st.session_state.tab2_df.empty:
        df_inst = st.session_state.tab2_df
        col1, col2, col3 = st.columns(3)
        with col1: st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Aktif İzlenen Varlık</div><div class='quant-card-value'>{len(df_inst):,}</div></div>", unsafe_allow_html=True)
        with col2: st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Kantitatif 'Güçlü Al' Sinyali</div><div class='quant-card-value' style='color: var(--accent-green);'>{len(df_inst[df_inst['TV_Signal'] >= 0.5])}</div></div>", unsafe_allow_html=True)
        with col3: st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Dip Noktasına <%5 Yakınlık</div><div class='quant-card-value' style='color: var(--accent-blue);'>{len(df_inst[(df_inst['Dip_Fark_Pct'] > 0) & (df_inst['Dip_Fark_Pct'] <= 5.0)])}</div></div>", unsafe_allow_html=True)

        filter_mode = st.selectbox("Sinyal Stratejisi Filtresi:", [
            "1. Yüksek Potansiyelli Dip Fırsatları (Dip <%15 + Upside >%20)",
            "2. Momentum ve Güçlü Al Sinyalleri (Kusursuz Teknik)",
            "3. Tüm Piyasa Görünümü"
        ])
        
        df_view = df_inst.copy()
        if filter_mode.startswith("1"): df_view = df_view[(df_view['Dip_Fark_Pct'] <= 15.0) & (df_view['Upside_Pct'] >= 20.0)].sort_values(by='Dip_Fark_Pct')
        elif filter_mode.startswith("2"): df_view = df_view[df_view['TV_Signal'] >= 0.5].sort_values(by='TV_Signal', ascending=False)
            
        df_view['Price'] = df_view['Price'].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "-")
        df_view['Dip_Fark_Pct'] = df_view['Dip_Fark_Pct'].apply(lambda x: f"%{x:.1f}" if pd.notnull(x) else "-")
        df_view['Upside_Pct'] = df_view['Upside_Pct'].apply(lambda x: f"+%{x:.1f}" if pd.notnull(x) and x > 0 else ("-" if pd.isnull(x) else f"%{x:.1f}"))
        
        # Karar Gerekçesi Sütunu Dahil
        st.dataframe(df_view[['Ticker', 'Price', 'Dip_Fark_Pct', 'Upside_Pct', 'Neden Alınmalı? (Stratejik Gerekçe)']], use_container_width=True, hide_index=True)

# --- SEKME 3: FIBONACCI GOLDEN ZONE ---
with tab3:
    st.markdown("### 📉 Fibonacci Golden Zone Tarayıcı")
    with st.expander("⚙️ Fibonacci Tarama Ayarları", expanded=True):
        col1, col2, col3 = st.columns(3)
        fib_mkt = col1.selectbox("Piyasa", list(FIB_MARKET_CONFIGS.keys()), key="fib_mkt")
        fib_tf = col2.selectbox("Zaman Dilimi", list(FIB_TIMEFRAME_CONFIGS.keys()), index=3, key="fib_tf")
        fib_limit = col3.number_input("Taranacak Hacimli Hisse (Sınır Kaldırıldı)", min_value=10, max_value=10000, value=5000, step=100, key="fib_limit")
        
        col4, col5 = st.columns(2)
        fib_recency = col4.slider("Sinyal Tazeliği (Son X Mum)", 1, 20, 3, key="fib_rec")
        fib_atr_mult = col5.slider("Yakın Takip Mesafesi (× ATR)", 0.2, 5.0, 1.5, step=0.1, key="fib_atr")
        
        pivot_len, confirm_bars = 15, 5
        golden_lower, golden_upper = 0.5, 0.618
        inv_buf_atr, zz_dev_atr = 0.3, 1.5
        touch_wick, skip_late = True, True
        only_after_sell = True
        
        run_fib_btn = st.button("🔍 Fibonacci Taramasını Başlat", type="primary", use_container_width=True)
        
    if run_fib_btn:
        mkt_cfg, tf_cfg = FIB_MARKET_CONFIGS[fib_mkt], FIB_TIMEFRAME_CONFIGS[fib_tf]
        term_ui3 = st.empty()
        term_ui3.code(f"[*] {fib_mkt} sembol listesi alınıyor...\n", language="bash")
        
        symbols = get_market_symbols(mkt_cfg["tv_market"], limit=fib_limit)
        if symbols:
            yf_tickers = [f"{s.replace('.', '-')}{mkt_cfg['yf_suffix']}" for s in symbols]
            term_ui3.code(f"[*] {len(yf_tickers)} hisse için {fib_tf} verisi indiriliyor...\n", language="bash")
            batch = fetch_batch(tuple(yf_tickers), tf_cfg["yf_interval"], tf_cfg["period"])

            fresh_results, watch_results, addon_results = [], [], []
            stored_dfs, stored_res = {}, {}
            single_ticker = len(yf_tickers) == 1
            processed_ok = 0
            pb = st.progress(0)

            for idx, (sym, yf_t) in enumerate(zip(symbols, yf_tickers)):
                pb.progress((idx + 1) / len(symbols))
                df = extract_symbol_df(batch, yf_t, single_ticker)
                if df is None or len(df) < MIN_BARS_REQUIRED: continue
                if tf_cfg["resample"]:
                    try: df = _resample_ohlcv(df, tf_cfg["resample"])
                    except: continue
                    if len(df) < MIN_BARS_REQUIRED: continue

                try:
                    res = run_strategy(df, left=pivot_len, right=confirm_bars, golden_lower=golden_lower, golden_upper=golden_upper, inv_buf_atr=inv_buf_atr, zz_dev_atr=zz_dev_atr, touch_wick=touch_wick, skip_late=skip_late)
                except: continue

                processed_ok += 1
                n = len(df); last_idx = n - 1; window_start = max(0, n - int(fib_recency))
                price_now = float(df["close"].iloc[-1])
                tv_url = f"https://www.tradingview.com/chart/?symbol={mkt_cfg['tv_prefix']}{sym}&interval={tf_cfg['tv_interval']}"
                symbol_used = False

                entry_hits = np.where(res["long_entry"][window_start:])[0]
                if len(entry_hits):
                    entry_idx = window_start + int(entry_hits[-1])
                    had_prior_exit = bool(np.any(res["long_exit"][:entry_idx]))
                    if had_prior_exit or not only_after_sell:
                        sig_type = "🟡 Golden Zone Reddi" if res["entry_from_gz"][entry_idx] else "🔵 ZigZag Dip Onayı"
                        gLow, gTop = _golden_bounds(res["final_zone"], golden_lower, golden_upper)
                        fresh_results.append({"Hisse": sym, "Sinyal Tipi": sig_type, "Sinyal Bar (geriye dönük)": n - 1 - entry_idx, "Güncel Fiyat": round(price_now, 4), "Golden Zone Alt": round(float(gLow), 4) if not np.isnan(gLow) else None, "Golden Zone Üst": round(float(gTop), 4) if not np.isnan(gTop) else None, "Trailing Stop": round(float(res["final_trailing_stop"]), 4) if not np.isnan(res["final_trailing_stop"]) else None, "Önceki SAT Var mı": "Evet" if had_prior_exit else "Hayır (İlk Sinyal)", "Bağlantı": tv_url})
                        symbol_used = True

                addon_hits = np.where(res["addon_signal"][window_start:])[0]
                if res["final_position"] and len(addon_hits):
                    addon_idx = window_start + int(addon_hits[-1])
                    sig_type = "🟡 Golden Zone Reddi" if res["addon_from_gz"][addon_idx] else "🔵 ZigZag Dip Onayı"
                    gLow, gTop = _golden_bounds(res["final_zone"], golden_lower, golden_upper)
                    open_idx = res.get("open_entry_idx")
                    open_price = round(float(df["close"].iloc[open_idx]), 4) if open_idx is not None else None
                    addon_results.append({"Hisse": sym, "Ekleme Sinyal Tipi": sig_type, "Sinyal Bar (geriye dönük)": n - 1 - addon_idx, "Güncel Fiyat": round(price_now, 4), "İlk Alım Fiyatı": open_price, "Golden Zone Alt": round(float(gLow), 4) if not np.isnan(gLow) else None, "Golden Zone Üst": round(float(gTop), 4) if not np.isnan(gTop) else None, "Trailing Stop": round(float(res["final_trailing_stop"]), 4) if not np.isnan(res["final_trailing_stop"]) else None, "Bağlantı": tv_url})
                    symbol_used = True

                fz = res["final_zone"]
                if (not res["final_position"]) and fz["set"] and fz["alive"] and fz["bull"] and not fz["rejected"]:
                    gLow, gTop = _golden_bounds(fz, golden_lower, golden_upper)
                    atr_last = res["atr"][last_idx]
                    if not np.isnan(gLow) and not np.isnan(atr_last):
                        last_low = float(df["low"].iloc[-1])
                        invalid_level = gLow - fib_atr_mult * atr_last
                        if price_now >= invalid_level:
                            if last_low <= gTop and price_now >= gLow - 0.15 * atr_last: status_txt = "🟠 Bölgede — Onay Bekleniyor"
                            elif 0 < (price_now - gTop) <= fib_atr_mult * atr_last: status_txt = "👀 Yaklaşıyor"
                            else: status_txt = None
                            if status_txt:
                                watch_results.append({"Hisse": sym, "Durum": status_txt, "Güncel Fiyat": round(price_now, 4), "Golden Zone Alt": round(float(gLow), 4), "Golden Zone Üst": round(float(gTop), 4), "Zone'a Uzaklık (ATR)": round((price_now - gTop) / atr_last, 2) if atr_last > 0 else None, "Bağlantı": tv_url})
                                symbol_used = True

                if symbol_used: stored_dfs[sym], stored_res[sym] = df, res

            pb.empty()
            term_ui3.code(f"[+] Tarama tamamlandı: {processed_ok} hisse başarıyla işlendi.\n", language="bash")
            st.session_state.fresh_results, st.session_state.watch_results, st.session_state.addon_results = fresh_results, watch_results, addon_results
            st.session_state.scan_meta = {"dfs": stored_dfs, "res": stored_res, "tf_label": fib_tf, "market_label": fib_mkt}

    if st.session_state.fresh_results or st.session_state.watch_results or st.session_state.addon_results:
        f_res, w_res, a_res, meta = st.session_state.fresh_results, st.session_state.watch_results, st.session_state.addon_results, st.session_state.scan_meta
        st.write("---")
        t1, t2, t3 = st.tabs([f"🎯 Taze AL Sinyalleri ({len(f_res)})", f"👀 Yakın Takip ({len(w_res)})", f"➕ Ekleme / İkinci Alım ({len(a_res)})"])
        with t1:
            if f_res: st.dataframe(pd.DataFrame(f_res), use_container_width=True, hide_index=True, column_config={"Bağlantı": st.column_config.LinkColumn("TradingView", display_text="📊 Grafiği Aç")})
        with t2:
            if w_res: st.dataframe(pd.DataFrame(w_res), use_container_width=True, hide_index=True, column_config={"Bağlantı": st.column_config.LinkColumn("TradingView", display_text="📊 Grafiği Aç")})
        with t3:
            if a_res: st.dataframe(pd.DataFrame(a_res), use_container_width=True, hide_index=True, column_config={"Bağlantı": st.column_config.LinkColumn("TradingView", display_text="📊 Grafiği Aç")})
            
        st.subheader("🔬 Grafik İnceleme İstasyonu")
        symbols_available = list(meta.get("dfs", {}).keys())
        if symbols_available:
            selected = st.selectbox("İncelemek için hisse seçin:", symbols_available, key="fib_chart_sel")
            if selected:
                col_chart, col_info = st.columns([4, 1])
                with col_chart:
                    st.plotly_chart(build_chart(meta["dfs"][selected], meta["res"][selected], selected, meta["tf_label"]), use_container_width=True)

# --- SEKME 4: ÇOKLU ALGORİTMİK TARAMA ---
with tab4:
    st.markdown("### ⚡ Kantitatif Trend & Sinyal Motoru")
    with st.expander("⚙️ Algoritma Ayarları", expanded=True):
        col1, col2 = st.columns(2)
        algo_mkt = col1.selectbox("Piyasa", list(ALGO_MARKETS.keys()), key="algo_mkt")
        algo_tf = col2.selectbox("Zaman Dilimi", list(ALGO_TIMEFRAMES.keys()), index=2, key="algo_tf")
        sel_algo = st.radio("Kullanılacak Algoritma:", ["1️⃣ LRC + WMA + SMMA", "2️⃣ Üçlü WMA (14-21-35)"], horizontal=True)
        algo_limit = st.number_input("Taranacak Varlık Sayısı (Sınır Kaldırıldı)", min_value=10, max_value=10000, value=5000, step=100, key="algo_limit")
        algo_recency = st.slider("Sinyal Tazeliği (Son X Mum)", 1, 10, 3, key="algo_rec")
        
        lrc_len, wma_len, smma_len = 9, 9, 21
        p1, p2, p3 = 14, 21, 35
        run_algo_btn = st.button("🚀 Algoritmik Taramayı Başlat", type="primary", use_container_width=True)

    if run_algo_btn:
        st.session_state['sonuclar_hafiza'] = []
        st.session_state['grafik_hafiza'] = {}
        st.session_state['secili_strateji_ismi'] = sel_algo.split(' ')[1]
        
        mkt, tf = ALGO_MARKETS[algo_mkt], ALGO_TIMEFRAMES[algo_tf]
        term_ui4 = st.empty()
        term_ui4.code(f"[*] {sel_algo} Motoru Başlatıldı...\n", language="bash")
        
        symbols = get_tv_symbols(mkt["tv_market"], limit=algo_limit) if not mkt["is_crypto"] else get_crypto_symbols(limit=algo_limit)
        if symbols:
            term_ui4.code(f"[*] {len(symbols)} varlık için derin veriler indiriliyor...\n", language="bash")
            if mkt["is_crypto"]:
                kripto_veriler = fetch_ccxt_batch(symbols, tf["ccxt_int"])
                batch_data = kripto_veriler
            else:
                yf_tickers = [f"{s.replace('.', '-')}{mkt['yf_suffix']}" for s in symbols]
                batch_data = fetch_yf_data(tuple(yf_tickers), tf["yf_int"], tf["period"])

            pb = st.progress(0)
            for idx, sym in enumerate(symbols):
                pb.progress((idx + 1) / len(symbols))
                try:
                    if mkt["is_crypto"]: df = batch_data.get(sym)
                    else:
                        y_tick = f"{sym.replace('.', '-')}{mkt['yf_suffix']}"
                        df = batch_data.copy() if len(symbols) == 1 else batch_data[y_tick].copy()
                        df.columns = [c.lower() for c in df.columns]
                        
                    if df is None or len(df.dropna()) < 50: continue
                    df = df.dropna()
                    
                    if "resample" in tf:
                        df = df.resample(tf["resample"]).agg({"open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"}).dropna()
                    if len(df) < 50: continue
                    
                    if sel_algo.startswith("1"): df = run_lrc_strategy(df, lrc_len, wma_len, smma_len)
                    else: df = run_wma_triple_strategy(df, p1, p2, p3)
                    
                    window_start = max(0, len(df) - algo_recency)
                    son_fiyat = round(float(df['close'].iloc[-1]), 4)
                    son_bar = df.iloc[-1]
                    tv_url = f"https://www.tradingview.com/chart/?symbol={mkt['tv_prefix']}{sym}&interval={tf['tv_int']}"
                    
                    al_vurdu = df['Net_AL'].iloc[window_start:].any()
                    yaklasan_vurdu = df['Yaklasan'].iloc[window_start:].any() if 'Yaklasan' in df.columns else False
                    roket_vurdu = df['Roket_Adayi'].iloc[window_start:].any() if 'Roket_Adayi' in df.columns else False
                    
                    if al_vurdu:
                        if sel_algo.startswith("1"):
                            st.session_state['sonuclar_hafiza'].append({"Varlık": sym, "Durum": "🔥 NET ALIM", "Fiyat": son_fiyat, "LRC (Mavi)": round(float(son_bar['LRC']), 4), "WMA (Turuncu)": round(float(son_bar['WMA']), 4), "SMMA (Mor)": round(float(son_bar['SMMA']), 4), "Link": tv_url})
                        else:
                            st.session_state['sonuclar_hafiza'].append({"Varlık": sym, "Durum": "🔥 NET ALIM", "Fiyat": son_fiyat, f"WMA {p1}": round(float(son_bar['WMA1']), 4), f"WMA {p2}": round(float(son_bar['WMA2']), 4), f"WMA {p3}": round(float(son_bar['WMA3']), 4), "Link": tv_url})
                        st.session_state['grafik_hafiza'][sym] = df
                    elif roket_vurdu and sel_algo.startswith("2"):
                        st.session_state['sonuclar_hafiza'].append({"Varlık": sym, "Durum": "🚀 ROKET ADAYI (Hacim+RSI)", "Fiyat": son_fiyat, f"WMA {p1}": round(float(son_bar['WMA1']), 4), f"WMA {p2}": round(float(son_bar['WMA2']), 4), f"WMA {p3}": round(float(son_bar['WMA3']), 4), "Link": tv_url})
                        st.session_state['grafik_hafiza'][sym] = df
                    elif yaklasan_vurdu and sel_algo.startswith("2"):
                        st.session_state['sonuclar_hafiza'].append({"Varlık": sym, "Durum": "👀 YAKLAŞIYOR (Pusu)", "Fiyat": son_fiyat, f"WMA {p1}": round(float(son_bar['WMA1']), 4), f"WMA {p2}": round(float(son_bar['WMA2']), 4), f"WMA {p3}": round(float(son_bar['WMA3']), 4), "Link": tv_url})
                        st.session_state['grafik_hafiza'][sym] = df
                except: pass
            pb.empty()
            term_ui4.code("[+] Analiz Tamamlandı!\n", language="bash")
            st.session_state['tarama_tamamlandi'] = True

    if st.session_state.get('tarama_tamamlandi') and st.session_state.get('sonuclar_hafiza'):
        st.success(f"Tarama Tamamlandı! {len(st.session_state['sonuclar_hafiza'])} adet varlık bulundu.")
        st.markdown(f"### 📊 Tarama Özeti ({st.session_state['secili_strateji_ismi']})")
        st.dataframe(pd.DataFrame(st.session_state['sonuclar_hafiza']), use_container_width=True, hide_index=True, column_config={"Link": st.column_config.LinkColumn("TradingView'da Aç")})
        
        st.write("---")
        st.markdown("### 🔬 Grafik İnceleme İstasyonu")
        secilen_varlik = st.selectbox("Grafiğini Görmek İstediğiniz Varlığı Seçin:", list(st.session_state['grafik_hafiza'].keys()), key="algo_chart_sel")
        if secilen_varlik:
            g_df = st.session_state['grafik_hafiza'][secilen_varlik].iloc[-150:]
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=g_df.index, open=g_df["open"], high=g_df["high"], low=g_df["low"], close=g_df["close"], name="Fiyat"))
            if "LRC" in st.session_state['secili_strateji_ismi']:
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['LRC'], line=dict(color='#3b82f6', width=2), name='LRC'))
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['WMA'], line=dict(color='#f97316', width=2), name='WMA'))
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['SMMA'], line=dict(color='#a855f7', width=2), name='SMMA'))
            else:
                p1_val, p2_val, p3_val = 14, 21, 35
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['WMA1'], line=dict(color='blue', width=2), name=f'WMA {p1_val}'))
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['WMA2'], line=dict(color='orange', width=2), name=f'WMA {p2_val}'))
                fig.add_trace(go.Scatter(x=g_df.index, y=g_df['WMA3'], line=dict(color='red', width=2), name=f'WMA {p3_val}'))
            
            al_noktasi = g_df[g_df['Net_AL'] == True]
            if not al_noktasi.empty: fig.add_trace(go.Scatter(x=al_noktasi.index, y=al_noktasi["low"] * 0.98, mode="markers+text", marker=dict(symbol="triangle-up", size=14, color="#22c55e"), text="AL", textposition="bottom center", name="Al Sinyali"))
            
            if "WMA" in st.session_state['secili_strateji_ismi']:
                if 'Yaklasan' in g_df.columns:
                    yaklasan_noktasi = g_df[(g_df['Yaklasan'] == True) & (g_df['Net_AL'] == False) & (g_df['Roket_Adayi'] == False)]
                    if not yaklasan_noktasi.empty: fig.add_trace(go.Scatter(x=yaklasan_noktasi.index, y=yaklasan_noktasi["low"] * 0.98, mode="markers+text", marker=dict(symbol="circle", size=10, color="#eab308"), text="PUSU", textposition="bottom center", name="Yaklaşan Sinyal"))
                if 'Roket_Adayi' in g_df.columns:
                    roket_noktasi = g_df[(g_df['Roket_Adayi'] == True) & (g_df['Net_AL'] == False)]
                    if not roket_noktasi.empty: fig.add_trace(go.Scatter(x=roket_noktasi.index, y=roket_noktasi["low"] * 0.96, mode="markers+text", marker=dict(symbol="star", size=12, color="#a855f7"), text="ROKET", textposition="bottom center", name="Roket Adayı"))
                
            fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False, title=f"{secilen_varlik} Görünümü", margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig, use_container_width=True)

# --- SEKME 5: MAKRO HABER VE DUYGU ANALİZİ ---
with tab5:
    st.markdown("### 📰 Şirket Haberleri ve Duygu Skoru")
    
    col_news1, col_news2 = st.columns([3, 1])
    with col_news1:
        news_ticker = st.text_input("Haberlerini Çekmek İstediğiniz Hisse Sembolü (Örn: AAPL, MSFT):", "AAPL")
    with col_news2:
        st.write("") 
        st.write("")
        run_news = st.button("Haberleri Getir", use_container_width=True)
        
    if run_news:
        term_ui5 = st.empty()
        term_ui5.code(f"[*] {news_ticker} için Finnhub API'sine bağlanılıyor...\n", language="bash")
        analyzer = get_nlp_engine()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        url = f"https://finnhub.io/api/v1/company-news?symbol={news_ticker}&from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        
        try:
            news_res = requests.get(url).json()
            if news_res:
                term_ui5.code(f"[+] {len(news_res)} haber bulundu. NLP analizleri yapılıyor...\n", language="bash")
                for item in news_res[:10]:
                    score = analyzer.polarity_scores(item['headline'])['compound']
                    if score >= 0.15: sentiment_ui = f"<span class='badge-bullish'>POZİTİF ({score:.2f})</span>"
                    elif score <= -0.15: sentiment_ui = f"<span class='badge-bearish'>NEGATİF ({score:.2f})</span>"
                    else: sentiment_ui = f"<span style='color: var(--text-muted); font-size: 0.75rem; font-weight: bold;'>NÖTR ({score:.2f})</span>"
                        
                    st.markdown(f"""
                    <div class='quant-card' style='padding: 12px;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;'>
                            <a href='{item['url']}' target='_blank' style='color: white; font-weight: 700; text-decoration: none; font-size: 1rem;'>{item['headline']}</a>
                            {sentiment_ui}
                        </div>
                        <div style='font-size: 0.75rem; color: var(--text-muted);'>{item['source']} • {datetime.fromtimestamp(item['datetime']).strftime('%d %b %Y, %H:%M')}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else: 
                term_ui5.code("[-] Son 7 güne ait majör bir haber bulunamadı.\n", language="bash")
        except Exception as e: 
            term_ui5.code(f"[!] HATA: Veri akışı sağlanamadı. Nedeni: {e}\n", language="bash")
