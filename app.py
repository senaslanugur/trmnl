import streamlit as st
import requests
import json
import time
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="ProPortföy Kantitatif Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS STİL ENJEKSİYONU ---
st.markdown("""
<style>
    :root {
        --primary: #3b82f6;
        --bg-dark: #070b12;
    }
    .stApp {
        background-color: var(--bg-dark);
    }
    .metric-card {
        background: #111827;
        border: 1px solid #1f293d;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .metric-title {
        font-size: 0.85rem;
        color: #94a3b8;
        font-weight: 700;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .metric-val {
        font-size: 1.8rem;
        font-weight: 900;
        color: white;
    }
    .signal-buy { color: #10b981; font-weight: bold; }
    .signal-sell { color: #ef4444; font-weight: bold; }
    .signal-neutral { color: #94a3b8; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- GLOBAL AYARLAR VE NLP ---
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0" #[cite: 1]

@st.cache_resource
def get_nlp_analyzer():
    analyzer = SentimentIntensityAnalyzer()
    FINANCIAL_LEXICON = {
        'upgrade': 4.0, 'beat': 3.5, 'surge': 3.0, 'growth': 2.5, 'profit': 2.5,
        'outperform': 3.5, 'dividend': 2.0, 'positive': 2.0, 'exceed': 3.0,
        'downgrade': -4.0, 'miss': -4.0, 'layoff': -3.5, 'decline': -3.0,
        'underperform': -3.5, 'warning': -3.0, 'loss': -3.5, 'drop': -3.0,
        'crash': -4.0, 'bankruptcy': -5.0, 'shatter': 3.0
    }
    analyzer.lexicon.update(FINANCIAL_LEXICON) #[cite: 2]
    return analyzer

# --- VERİ ÇEKME FONKSİYONLARI ---

@st.cache_data(ttl=3600)
def fetch_upcoming_earnings():
    url = "https://scanner.tradingview.com/america/scan?label-product=calendar-earnings"
    now = int(time.time())
    one_week_later = now + (7 * 24 * 60 * 60) # Önümüzdeki 1 hafta (7 gün)
    
    payload = {
        "filter": [
            {"left": "earnings_release_next_date", "operation": "in_range", "right": [now, one_week_later]},
            {"left": "earnings_per_share_forecast_next_fq", "operation": "greater", "right": 0}
        ],
        "markets": ["america"],
        "columns": ["name", "earnings_per_share_forecast_next_fq", "earnings_release_next_date", "market_cap_basic"],
        "sort": {"sortBy": "earnings_release_next_date", "sortOrder": "asc"},
        "range": [0, 500] 
    } #[cite: 1, 3]

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json().get('data', [])
            
            # Saniye temizleme ve pazar değerine göre sıralama algoritması[cite: 3]
            def sort_key(x):
                d = x['d']
                ts = d[2]
                day_timestamp = ts - (ts % 86400)
                m_cap = d[3] if d[3] is not None else 0
                return (day_timestamp, -m_cap)
            
            data.sort(key=sort_key)
            
            parsed_data = []
            for item in data:
                ticker = item['s'].split(':')[-1]
                d = item['d']
                val = d[3] if d[3] else 0
                
                # Market Cap formatlaması[cite: 4]
                if val >= 1e12: m_cap_str = f"${val/1e12:.2f}T"
                elif val >= 1e9: m_cap_str = f"${val/1e9:.2f}B"
                elif val >= 1e6: m_cap_str = f"${val/1e6:.2f}M"
                else: m_cap_str = f"${val:.2f}"
                
                tarih = time.strftime('%Y-%m-%d', time.localtime(d[2]))
                parsed_data.append({
                    "Hisse": ticker,
                    "Tarih": tarih,
                    "Est. EPS": d[1],
                    "Market Cap": m_cap_str,
                    "Raw_Cap": val
                })
            return pd.DataFrame(parsed_data)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"TradingView API Hatası: {e}")
        return pd.DataFrame()

def fetch_finnhub_analysis(ticker):
    try:
        # Quote & Metrics[cite: 1]
        quote = requests.get(f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        metric = requests.get(f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_API_KEY}").json().get('metric', {})
        
        # Recommendations & Insider[cite: 1]
        recs = requests.get(f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        insider = requests.get(f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}").json().get('data', [])

        curr_price = quote.get('c', 0)
        low_52 = metric.get('52WeekLow', 0)
        high_52 = metric.get('52WeekHigh', 0)
        
        # Analist Konsensüsü
        r = recs[0] if recs else {}
        total_buy = r.get('buy',0) + r.get('strongBuy',0)
        total_sell = r.get('sell',0) + r.get('strongSell',0)
        analyst = f"Al: {total_buy} / Sat: {total_sell}"
        
        # Balina (Büyük Alım)[cite: 1]
        balina_str = "Yok"
        if insider:
            large_buys = [t for t in insider if t.get('share', 0) > 0]
            if large_buys:
                last_buy = large_buys[0]
                balina_str = f"Alım ({(last_buy.get('change', 0)):,} lot - {last_buy['filingDate']})"

        return curr_price, low_52, high_52, analyst, balina_str
    except:
        return 0, 0, 0, "Bilinmiyor", "Hata"

# --- UI BAŞLANGIÇ ---
st.title("⚡ ProPortföy Kantitatif Analiz Terminali")
st.markdown("<p style='color: #94a3b8; margin-top:-15px;'>Bağımsız katmanlı tarama ve derin teknik analiz sistemi.</p>", unsafe_allow_html=True)

# TABS (İzole Edilmiş Mimariler)
tab1, tab2, tab3 = st.tabs(["Ana Tarayıcı (Tab-1 Algoritma)", "Teknik ve Grafikler (Tab-2)", "Haber ve Duygu Analizi (Tab-3)"])

# --- TAB 1: ÇEKİRDEK TARAYICI (DOKUNULMAZ ALGORİTMA) ---
with tab1:
    st.markdown("### 🎯 1 Haftalık Bilanço & Fırsat Tarayıcı")
    
    with st.spinner("TradingView ve Finnhub'dan veriler taranıyor..."):
        df_earnings = fetch_upcoming_earnings()
        
    if not df_earnings.empty:
        # Kullanıcı etkileşimi için metrik kartları
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='metric-card'><div class='metric-title'>Taranan Hisse</div><div class='metric-val'>{len(df_earnings)}</div></div>", unsafe_allow_html=True)
        avg_eps = df_earnings["Est. EPS"].mean()
        c2.markdown(f"<div class='metric-card'><div class='metric-title'>Ortalama Est. EPS</div><div class='metric-val'>${avg_eps:.2f}</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='metric-card'><div class='metric-title'>Tarih Aralığı</div><div class='metric-val'>Önümüzdeki 7 Gün</div></div>", unsafe_allow_html=True)
        
        st.write("---")
        st.dataframe(df_earnings.drop(columns=["Raw_Cap"]), use_container_width=True, hide_index=True)
        
        st.markdown("### 🐋 Finnhub Derin Analiz (Seçili Hisseler)")
        selected_ticker = st.selectbox("Detaylı analiz edilecek hisseyi seçin:", df_earnings["Hisse"].tolist())
        
        if selected_ticker:
            curr_price, low_52, high_52, analyst, balina = fetch_finnhub_analysis(selected_ticker)
            
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Güncel Fiyat", f"${curr_price:.2f}")
            sc2.metric("52W Dip / Tepe", f"${low_52:.2f} - ${high_52:.2f}")
            sc3.metric("Analist Görüşü", analyst)
            sc4.metric("Balina / Insider", balina)
            
            # Formasyon Taraması (Dip Yakınlığı)
            dip_farki = ((curr_price - low_52) / low_52) * 100 if low_52 > 0 else 0
            if 0 < dip_farki <= 15:
                st.success(f"**Katı Teknik Sinyal:** Fiyat 52 haftalık dibe %{dip_farki:.1f} yakınlıkta. Potansiyel ALIM bölgesi.")
            elif dip_farki > 15:
                st.warning(f"**Katı Teknik Sinyal:** Fiyat dipten %{dip_farki:.1f} uzaklaşmış durumda.")
    else:
        st.warning("Önümüzdeki 1 hafta içinde bilanço açıklayacak uygun hisse bulunamadı.")


# --- TAB 2: TEKNİK GRAFİK VE YF ANALİZ (BAĞIMSIZ BÖLÜM) ---
with tab2:
    st.markdown("### 📈 Profesyonel Hacim ve Trend Analizi")
    if not df_earnings.empty:
        analyze_ticker = st.selectbox("Grafik için hisse seçin:", df_earnings["Hisse"].tolist(), key="tab2_ticker")
        
        with st.spinner(f"{analyze_ticker} Yahoo Finance verileri çekiliyor..."):
            hist_data = yf.download(analyze_ticker, period="6mo")
        
        if not hist_data.empty:
            # Hareketli Ortalamalar (Katı Teknik)
            hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
            hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
            
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, subplot_titles=(f'{analyze_ticker} Fiyat & SMA', 'Hacim'),
                                row_width=[0.2, 0.7])
            
            # Candlestick
            fig.add_trace(go.Candlestick(x=hist_data.index,
                            open=hist_data['Open'].squeeze(),
                            high=hist_data['High'].squeeze(),
                            low=hist_data['Low'].squeeze(),
                            close=hist_data['Close'].squeeze(),
                            name='Fiyat'), row=1, col=1)
            
            # SMA 20 & 50
            fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['SMA_20'].squeeze(), line=dict(color='orange', width=1.5), name='SMA 20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['SMA_50'].squeeze(), line=dict(color='blue', width=1.5), name='SMA 50'), row=1, col=1)
            
            # Hacim (Vektörel ve güvenli eşleştirme)
            hist_open = hist_data['Open'].squeeze().tolist()
            hist_close = hist_data['Close'].squeeze().tolist()
            colors = ['red' if o > c else 'green' for o, c in zip(hist_open, hist_close)]
            
            fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Volume'].squeeze(), marker_color=colors, name='Hacim'), row=2, col=1)
            
            fig.update_layout(height=600, template="plotly_dark", showlegend=True, margin=dict(l=0, r=0, t=40, b=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            # Kesişim Sinyali Kontrolü (Golden Cross / Death Cross)
            last_sma20 = hist_data['SMA_20'].iloc[-1].item()
            last_sma50 = hist_data['SMA_50'].iloc[-1].item()
            prev_sma20 = hist_data['SMA_20'].iloc[-2].item()
            prev_sma50 = hist_data['SMA_50'].iloc[-2].item()
            
            if prev_sma20 < prev_sma50 and last_sma20 > last_sma50:
                st.markdown("<h4 class='signal-buy'>🟢 SİNYAL: Kısa vadeli trend (SMA20), orta vadeli trendi (SMA50) yukarı kesti (BULLISH).</h4>", unsafe_allow_html=True)
            elif prev_sma20 > prev_sma50 and last_sma20 < last_sma50:
                st.markdown("<h4 class='signal-sell'>🔴 SİNYAL: Kısa vadeli trend, orta vadeli trendi aşağı kesti (BEARISH).</h4>", unsafe_allow_html=True)
            else:
                st.markdown("<h4 class='signal-neutral'>⚪ SİNYAL: Belirgin bir hareketli ortalama kesişimi yok (NÖTR).</h4>", unsafe_allow_html=True)

    else:
        st.info("Listede hisse bulunamadığı için grafik oluşturulamıyor.")


# --- TAB 3: HABER AKIŞI VE NLP DUYGU ANALİZİ ---
with tab3:
    st.markdown("### 📰 Şirket Haberleri ve Duygu Skoru (Son 1 Hafta)")
    if not df_earnings.empty:
        news_ticker = st.selectbox("Haberleri taranacak hisseyi seçin:", df_earnings["Hisse"].tolist(), key="tab3_ticker")
        
        with st.spinner("Finnhub'dan haberler ve duygu analizi yükleniyor..."):
            analyzer = get_nlp_analyzer()
            
            now = datetime.now()
            past_week = now - timedelta(days=7)
            to_date = now.strftime('%Y-%m-%d')
            from_date = past_week.strftime('%Y-%m-%d')
            
            news_url = f"https://finnhub.io/api/v1/company-news?symbol={news_ticker}&from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
            
            try:
                news_res = requests.get(news_url)
                if news_res.status_code == 200:
                    news_data = news_res.json()
                    
                    if news_data:
                        for n in news_data[:10]: # Son 10 haber[cite: 2, 5]
                            pub_date = datetime.fromtimestamp(n['datetime']).strftime('%Y-%m-%d %H:%M')
                            headline = n['headline']
                            url = n['url']
                            source = n['source']
                            
                            # Duygu Analizi Puanlaması[cite: 2]
                            score = analyzer.polarity_scores(headline)['compound']
                            
                            # Tazelik ağırlığı (son 24 saat ise skoru artır)[cite: 2]
                            if (now.timestamp() - n['datetime']) <= 86400:
                                score *= 1.3
                                
                            # Eşik belirleme
                            if score >= 0.15: 
                                status, color = "AL 🚀", "var(--success)"
                            elif score <= -0.15: 
                                status, color = "SAT ⚠️", "var(--danger)"
                            else: 
                                status, color = "NÖTR ⚖️", "#94a3b8"
                                
                            st.markdown(f"""
                            <div style='background:rgba(255,255,255,0.02); border:1px solid #1f293d; padding:15px; border-radius:10px; margin-bottom:10px;'>
                                <div style='display:flex; justify-content:space-between; margin-bottom:5px;'>
                                    <a href='{url}' target='_blank' style='color:white; font-weight:700; text-decoration:none;'>{headline}</a>
                                    <span style='color:{color}; font-weight:bold;'>{status} ({score:.2f})</span>
                                </div>
                                <div style='font-size:0.8rem; color:#94a3b8;'>{source} &bull; {pub_date}</div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("Son 1 haftaya ait haber bulunamadı.")
            except Exception as e:
                st.error(f"Haberler çekilirken hata oluştu: {e}")
