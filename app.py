import streamlit as st
import requests
import time
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta

# --- 1. SİSTEM YAPILANDIRMASI VE CSS ---
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
        --text-main: #e2e8f0;
        --text-muted: #64748b;
    }
    .stApp { background-color: var(--bg-dark); color: var(--text-main); font-family: 'Inter', sans-serif; }
    
    /* Kurumsal Dashboard Kartları */
    .quant-card {
        background: var(--panel-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        margin-bottom: 16px;
    }
    .quant-card-title {
        font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 8px;
    }
    .quant-card-value {
        font-size: 1.6rem; color: #ffffff; font-weight: 900; letter-spacing: -0.5px;
    }
    .badge-bullish { background: rgba(0, 200, 83, 0.15); color: var(--accent-green); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(0, 200, 83, 0.3); }
    .badge-bearish { background: rgba(213, 0, 0, 0.15); color: var(--accent-red); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(213, 0, 0, 0.3); }
    
    /* Streamlit Metric Overrides */
    div[data-testid="stMetricValue"] > div { font-size: 1.4rem !important; font-weight: 800 !important; white-space: normal !important; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; color: var(--text-muted) !important; text-transform: uppercase; }
</style>
""", unsafe_allow_html=True)

# --- 2. API VE NLP MOTORU ---
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0"

@st.cache_resource
def get_nlp_engine():
    analyzer = SentimentIntensityAnalyzer()
    lexicon = {
        'upgrade': 4.0, 'beat': 3.5, 'surge': 3.0, 'growth': 2.5, 'profit': 2.5,
        'outperform': 3.5, 'exceed': 3.0, 'downgrade': -4.0, 'miss': -4.0,
        'layoff': -3.5, 'decline': -3.0, 'underperform': -3.5, 'bankruptcy': -5.0
    }
    analyzer.lexicon.update(lexicon)
    return analyzer

# --- 3. İZOLE EDİLMİŞ ÇEKİRDEK ALGORİTMA (TAB-1 İÇİN) ---
@st.cache_data(ttl=3600)
def fetch_core_earnings():
    url = "https://scanner.tradingview.com/america/scan?label-product=calendar-earnings"
    now = int(time.time())
    one_month_later = now + (30 * 24 * 60 * 60)
    
    payload = {
        "filter": [
            {"left": "earnings_release_next_date", "operation": "in_range", "right": [now, one_month_later]},
            {"left": "earnings_per_share_forecast_next_fq", "operation": "greater", "right": 0}
        ],
        "markets": ["america"],
        "columns": ["name", "earnings_per_share_forecast_next_fq", "earnings_release_next_date", "market_cap_basic"],
        "sort": {"sortBy": "earnings_release_next_date", "sortOrder": "asc"},
        "range": [0, 5000]
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json().get('data', [])
            def sort_key(x):
                d = x['d']
                ts = d[2]
                return (ts - (ts % 86400), -(d[3] if d[3] else 0))
            data.sort(key=sort_key)
            
            parsed = []
            for item in data:
                ticker = item['s'].split(':')[-1]
                d = item['d']
                val = d[3] if d[3] else 0
                if val >= 1e9: m_cap_str = f"${val/1e9:.2f}B"
                elif val >= 1e6: m_cap_str = f"${val/1e6:.2f}M"
                else: m_cap_str = f"${val:.2f}"
                parsed.append({
                    "Hisse": ticker, "Est. EPS": d[1],
                    "Tarih": time.strftime('%Y-%m-%d', time.localtime(d[2])),
                    "Market Cap": m_cap_str
                })
            return pd.DataFrame(parsed)
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 4. KURUMSAL PİYASA TARAYICISI (NATIVE ABD HİSSELERİ) ---
@st.cache_data(ttl=1800)
def fetch_institutional_screener():
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}],
        "options": {"lang": "en"},
        "markets": ["america"],
        "columns": [
            "name", "close", "price_52_week_low", "price_52_week_high", 
            "Recommend.All", "market_cap_basic", "price_target_price_mean", "volume"
        ],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 5000]
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json().get('data', [])
            parsed = []
            for item in data:
                sym = item['s'].split(':')[-1]
                d = item['d']
                close, low52, high52, rec, mcap, target_mean, vol = d[0:7]
                
                dip_farki = ((close - low52) / low52) * 100 if close and low52 and low52 > 0 else 0
                target_pot = ((target_mean - close) / close) * 100 if target_mean and close and close > 0 else 0
                
                parsed.append({
                    "Ticker": sym, "Price": close, "Dip_Fark_Pct": dip_farki, 
                    "Upside_Pct": target_pot, "TV_Signal": rec if rec else 0, 
                    "Market_Cap": mcap, "Volume": vol
                })
            return pd.DataFrame(parsed)
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- UI ANA İSKELET ---
st.markdown("<h2 style='font-weight: 900; letter-spacing: -1px; margin-bottom: 0;'>QUANT CORE TERMINAL</h2>", unsafe_allow_html=True)
st.markdown("<p style='color: var(--text-muted); font-size: 0.9rem;'>Kurumsal Sinyal ve Risk Analiz Platformu</p>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs([
    "⚙️ TAB-1 (Ana Algoritma)", 
    "🌍 Kurumsal Tarayıcı", 
    "🔬 Kantitatif Derinlik", 
    "📰 Makro Haber & NLP"
])

# --- SEKME 1: ÇEKİRDEK (DOKUNULMAZ ALAN) ---
with tab1:
    st.markdown("##### Kazanç Takvimi ve Temel Analiz")
    df_core = fetch_core_earnings()
    if not df_core.empty:
        st.dataframe(df_core, use_container_width=True, hide_index=True)
    else:
        st.error("Çekirdek veri servisi şu an yanıt vermiyor.")

# --- SEKME 2: KURUMSAL TARAYICI (CEO DASHBOARD) ---
with tab2:
    df_inst = fetch_institutional_screener()
    if not df_inst.empty:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Aktif İzlenen Varlık</div><div class='quant-card-value'>{len(df_inst):,}</div></div>", unsafe_allow_html=True)
        with col2:
            strong_buys = len(df_inst[df_inst['TV_Signal'] >= 0.5])
            st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Kantitatif 'Güçlü Al' Sinyali</div><div class='quant-card-value' style='color: var(--accent-green);'>{strong_buys}</div></div>", unsafe_allow_html=True)
        with col3:
            deep_value = len(df_inst[(df_inst['Dip_Fark_Pct'] > 0) & (df_inst['Dip_Fark_Pct'] <= 5.0)])
            st.markdown(f"<div class='quant-card'><div class='quant-card-title'>Dip Noktasına <%5 Yakınlık</div><div class='quant-card-value' style='color: var(--accent-blue);'>{deep_value}</div></div>", unsafe_allow_html=True)

        st.markdown("---")
        
        filter_mode = st.selectbox("Sinyal Stratejisi:", [
            "1. Yüksek Potansiyelli Dip Fırsatları (Dip <%15 + Upside >%20)",
            "2. Momentum ve Güçlü Al Sinyalleri (Kusursuz Teknik)",
            "3. Tüm Piyasa Görünümü"
        ])
        
        df_view = df_inst.copy()
        
        if filter_mode.startswith("1"):
            df_view = df_view[(df_view['Dip_Fark_Pct'] <= 15.0) & (df_view['Upside_Pct'] >= 20.0)].sort_values(by='Dip_Fark_Pct')
        elif filter_mode.startswith("2"):
            df_view = df_view[df_view['TV_Signal'] >= 0.5].sort_values(by='TV_Signal', ascending=False)
            
        # Kurumsal Formatlama
        df_view['Price'] = df_view['Price'].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "-")
        df_view['Dip_Fark_Pct'] = df_view['Dip_Fark_Pct'].apply(lambda x: f"%{x:.1f}" if pd.notnull(x) else "-")
        df_view['Upside_Pct'] = df_view['Upside_Pct'].apply(lambda x: f"+%{x:.1f}" if pd.notnull(x) and x > 0 else ("-" if pd.isnull(x) else f"%{x:.1f}"))
        
        st.dataframe(df_view[['Ticker', 'Price', 'Dip_Fark_Pct', 'Upside_Pct', 'Market_Cap']], use_container_width=True, hide_index=True)
    else:
        st.warning("Kurumsal tarama verileri şu an alınamıyor.")

# --- SEKME 3: KANTİTATİF DERİNLİK VE YF GRAFİKLERİ ---
with tab3:
    if not df_inst.empty:
        target_ticker = st.selectbox("Teknik İnceleme İçin Varlık Seçin:", df_inst['Ticker'].head(500).tolist())
        
        with st.spinner("Mikro yapı ve fiyat hareketleri işleniyor..."):
            hist = yf.download(target_ticker, period="6mo", progress=False)
            
        if not hist.empty:
            hist['SMA_20'] = hist['Close'].rolling(window=20).mean()
            hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
            
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.25, 0.75], vertical_spacing=0.02)
            
            # Fiyat Hareketi
            fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'].squeeze(), high=hist['High'].squeeze(), low=hist['Low'].squeeze(), close=hist['Close'].squeeze(), name='Price'), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA_20'].squeeze(), line=dict(color='#ff9100', width=1.5), name='SMA 20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA_50'].squeeze(), line=dict(color='#2962ff', width=1.5), name='SMA 50'), row=1, col=1)
            
            # Hacim Profili
            hist_open = hist['Open'].squeeze().tolist()
            hist_close = hist['Close'].squeeze().tolist()
            vol_colors = ['rgba(213, 0, 0, 0.6)' if o > c else 'rgba(0, 200, 83, 0.6)' for o, c in zip(hist_open, hist_close)]
            fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'].squeeze(), marker_color=vol_colors, name='Volume'), row=2, col=1)
            
            fig.update_layout(height=650, margin=dict(l=0, r=0, t=10, b=0), template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            # Formasyon Kararı
            curr_20, curr_50 = hist['SMA_20'].iloc[-1].item(), hist['SMA_50'].iloc[-1].item()
            if curr_20 > curr_50:
                st.markdown("<div class='badge-bullish'>BULLISH YAPI: Kısa vadeli momentum, uzun vadeli trendin üzerinde konumlanıyor.</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='badge-bearish'>BEARISH YAPI: Kısa vadeli momentum baskı altında.</div>", unsafe_allow_html=True)

# --- SEKME 4: MAKRO HABER VE DUYGU ANALİZİ ---
with tab4:
    if not df_inst.empty:
        news_ticker = st.selectbox("Haber Akışı Analizi:", df_inst['Ticker'].head(500).tolist(), key="news_select")
        analyzer = get_nlp_engine()
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        url = f"https://finnhub.io/api/v1/company-news?symbol={news_ticker}&from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        
        try:
            news_res = requests.get(url).json()
            if news_res:
                for item in news_res[:8]:
                    score = analyzer.polarity_scores(item['headline'])['compound']
                    if score >= 0.15: 
                        sentiment_ui = f"<span class='badge-bullish'>POZİTİF ({score:.2f})</span>"
                    elif score <= -0.15: 
                        sentiment_ui = f"<span class='badge-bearish'>NEGATİF ({score:.2f})</span>"
                    else: 
                        sentiment_ui = f"<span style='color: var(--text-muted); font-size: 0.75rem; font-weight: bold;'>NÖTR ({score:.2f})</span>"
                        
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
                st.info("Kurumsal haber bülteninde son 7 güne ait majör bir veri bulunamadı.")
        except:
            st.error("Veri akışı sağlanamadı.")
