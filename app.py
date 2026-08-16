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

# --- CSS STİL ENJEKSİYONU (UI VE RADAR KARTLARI DÜZELTMELERİ) ---
st.markdown("""
<style>
    :root {
        --primary: #3b82f6;
        --bg-dark: #070b12;
    }
    .stApp { background-color: var(--bg-dark); }
    .metric-card {
        background: #111827; border: 1px solid #1f293d; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .metric-title { font-size: 0.85rem; color: #94a3b8; font-weight: 700; text-transform: uppercase; margin-bottom: 8px; }
    .metric-val { font-size: 1.8rem; font-weight: 900; color: white; }
    
    .signal-buy { color: #10b981; font-weight: bold; }
    .signal-sell { color: #ef4444; font-weight: bold; }
    .signal-neutral { color: #94a3b8; font-weight: bold; }
    
    /* Metin Taşmalarını Önleme (Özellikle Balina/Insider için) */
    div[data-testid="stMetricValue"] > div {
        white-space: normal !important; word-wrap: break-word !important; font-size: 1.25rem !important; line-height: 1.4 !important;
    }
    div[data-testid="stMetricLabel"] {
        word-wrap: break-word !important; white-space: normal !important;
    }

    /* Radar Fırsat Kartları */
    .radar-card {
        background: linear-gradient(145deg, #131d2e, #0c1320);
        border: 1px solid #1f293d;
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 15px;
        border-left: 4px solid var(--primary);
    }
    .radar-title { font-size: 1.2rem; font-weight: 900; color: white; display: flex; justify-content: space-between; margin-bottom: 10px; }
    .radar-desc { font-size: 0.9rem; color: #94a3b8; line-height: 1.5; }
    .radar-highlight { font-weight: 800; font-size: 1.1rem; margin-top: 10px; }
</style>
""", unsafe_allow_html=True)

# --- GLOBAL AYARLAR, NLP VE HİSSE HAVUZU ---
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0" #[cite: 1]
US_STOCK_POOL = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","LLY","JPM","V","UNH","MA","XOM","JNJ","HD","PG","COST","MRK","ABBV","CRM","BAC","CVX","NFLX","AMD","KO","PEP","WMT","TMO","DIS","MCD","CSCO","ADBE","QCOM","INTC","TXN","IBM","AMGN","PFE","GE","NOW","INTU","CAT","VZ","HON","BA","NKE","GS","MS"] #[cite: 5]

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

# --- TAB-1 İZOLASYON ALANI: ÇEKİRDEK VERİ FONKSİYONLARI ---

@st.cache_data(ttl=3600)
def fetch_upcoming_earnings():
    url = "https://scanner.tradingview.com/america/scan?label-product=calendar-earnings"
    now = int(time.time())
    one_week_later = now + (7 * 24 * 60 * 60) 
    
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

@st.cache_data(ttl=3600)
def fetch_general_screener():
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock", "dr"]}],
        "options": {"lang": "en"},
        "markets": ["america"],
        "columns": ["name", "close", "price_52_week_low", "price_52_week_high", "Recommend.All", "market_cap_basic", "price_target_price_mean"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 2000]
    } #[cite: 4]

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json().get('data', [])
            parsed = []
            for item in data:
                sym = item['s'].split(':')[-1]
                d = item['d']
                close, low52, high52, rec, mcap, target_mean = d[1], d[2], d[3], d[4], d[5], d[6]
                
                dip_farki = ((close - low52) / low52) * 100 if close and low52 and low52 > 0 else 0
                target_pot = ((target_mean - close) / close) * 100 if target_mean and close and close > 0 else 0

                if rec is not None:
                    if rec >= 0.5: rec_str = "GÜÇLÜ AL 🔥"
                    elif rec >= 0.1: rec_str = "AL ✅"
                    elif rec <= -0.5: rec_str = "GÜÇLÜ SAT 🆘"
                    elif rec <= -0.1: rec_str = "SAT ⚠️"
                    else: rec_str = "NÖTR ⚖️"
                else: rec_str = "BİLİNMİYOR"
                    
                if mcap and mcap >= 1e9: mcap_str = f"${mcap/1e9:.2f}B"
                elif mcap and mcap >= 1e6: mcap_str = f"${mcap/1e6:.2f}M"
                else: mcap_str = "-"
                
                parsed.append({
                    "Hisse": sym, "Fiyat ($)": close, "52W Dip Farkı (%)": dip_farki, 
                    "Hedef Potansiyeli (%)": target_pot, "Teknik Sinyal": rec_str, 
                    "Market Cap": mcap_str, "TV_Rec": rec if rec else 0
                })
            return pd.DataFrame(parsed)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def fetch_finnhub_analysis(ticker):
    try:
        quote = requests.get(f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        metric = requests.get(f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_API_KEY}").json().get('metric', {})
        recs = requests.get(f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        insider = requests.get(f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}").json().get('data', []) #[cite: 1]

        curr_price = quote.get('c', 0)
        low_52 = metric.get('52WeekLow', 0)
        high_52 = metric.get('52WeekHigh', 0)
        
        r = recs[0] if recs else {}
        total_buy = r.get('buy',0) + r.get('strongBuy',0)
        total_sell = r.get('sell',0) + r.get('strongSell',0)
        analyst = f"Al:{total_buy} / Sat:{total_sell}"
        
        balina_str = "Yok"
        if insider:
            large_buys = [t for t in insider if t.get('share', 0) > 0]
            if large_buys:
                last_buy = large_buys[0]
                balina_str = f"Alım ({(last_buy.get('change', 0)):,} lot | {last_buy['filingDate']})" #[cite: 1]

        return curr_price, low_52, high_52, analyst, balina_str
    except:
        return 0, 0, 0, "Bilinmiyor", "Hata"

# --- UI BAŞLANGIÇ VE SEKMELER ---
st.title("⚡ ProPortföy Kantitatif Analiz Terminali")
st.markdown("<p style='color: #94a3b8; margin-top:-15px;'>Bağımsız katmanlı tarama ve derin teknik analiz sistemi.</p>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Ana Tarayıcı", 
    "📈 Teknik Grafikler", 
    "📰 Haber NLP",
    "🌍 Genel Piyasa",
    "⚡ Akıllı Para Radarları" # HTML Dosyasındaki Yeni Alan
])

# --- TAB 1: ÇEKİRDEK TARAYICI ---
with tab1:
    with st.spinner("TradingView ve Finnhub'dan veriler taranıyor..."):
        df_earnings = fetch_upcoming_earnings()
        
    if not df_earnings.empty:
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
            sc2.metric("52W Dip/Tepe", f"${low_52:.2f} - ${high_52:.2f}")
            sc3.metric("Analist Görüşü", analyst)
            sc4.metric("Balina / Insider", balina)
            
            dip_farki = ((curr_price - low_52) / low_52) * 100 if low_52 > 0 else 0
            if 0 < dip_farki <= 15:
                st.success(f"**Katı Teknik Sinyal:** Fiyat 52 haftalık dibe %{dip_farki:.1f} yakınlıkta. Potansiyel ALIM bölgesi.")
            elif dip_farki > 15:
                st.warning(f"**Katı Teknik Sinyal:** Fiyat dipten %{dip_farki:.1f} uzaklaşmış durumda.")
    else:
        st.warning("Önümüzdeki 1 hafta içinde bilanço açıklayacak uygun hisse bulunamadı.")


# --- TAB 2: TEKNİK GRAFİK ---
with tab2:
    if not df_earnings.empty:
        analyze_ticker = st.selectbox("Grafik için hisse seçin:", df_earnings["Hisse"].tolist(), key="tab2_ticker")
        with st.spinner(f"{analyze_ticker} Yahoo Finance verileri çekiliyor..."):
            hist_data = yf.download(analyze_ticker, period="6mo")
        
        if not hist_data.empty:
            hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
            hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
            
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, subplot_titles=(f'{analyze_ticker} Fiyat & SMA', 'Hacim'), row_width=[0.2, 0.7])
            fig.add_trace(go.Candlestick(x=hist_data.index, open=hist_data['Open'].squeeze(), high=hist_data['High'].squeeze(), low=hist_data['Low'].squeeze(), close=hist_data['Close'].squeeze(), name='Fiyat'), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['SMA_20'].squeeze(), line=dict(color='orange', width=1.5), name='SMA 20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist_data.index, y=hist_data['SMA_50'].squeeze(), line=dict(color='blue', width=1.5), name='SMA 50'), row=1, col=1)
            
            hist_open = hist_data['Open'].squeeze().tolist()
            hist_close = hist_data['Close'].squeeze().tolist()
            colors = ['red' if o > c else 'green' for o, c in zip(hist_open, hist_close)]
            fig.add_trace(go.Bar(x=hist_data.index, y=hist_data['Volume'].squeeze(), marker_color=colors, name='Hacim'), row=2, col=1)
            
            fig.update_layout(height=600, template="plotly_dark", showlegend=True, margin=dict(l=0, r=0, t=40, b=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
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


# --- TAB 3: HABER AKIŞI NLP ---
with tab3:
    if not df_earnings.empty:
        news_ticker = st.selectbox("Haberleri taranacak hisseyi seçin:", df_earnings["Hisse"].tolist(), key="tab3_ticker")
        with st.spinner("Finnhub'dan haberler ve duygu analizi yükleniyor..."):
            analyzer = get_nlp_analyzer()
            now = datetime.now()
            past_week = now - timedelta(days=7)
            
            news_url = f"https://finnhub.io/api/v1/company-news?symbol={news_ticker}&from={past_week.strftime('%Y-%m-%d')}&to={now.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
            try:
                news_data = requests.get(news_url).json()
                if news_data:
                    for n in news_data[:10]:
                        score = analyzer.polarity_scores(n['headline'])['compound']
                        if (now.timestamp() - n['datetime']) <= 86400: score *= 1.3
                        status, color = ("AL 🚀", "var(--success)") if score >= 0.15 else (("SAT ⚠️", "var(--danger)") if score <= -0.15 else ("NÖTR ⚖️", "#94a3b8"))
                        st.markdown(f"<div style='background:rgba(255,255,255,0.02); border:1px solid #1f293d; padding:15px; border-radius:10px; margin-bottom:10px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><a href='{n['url']}' target='_blank' style='color:white; font-weight:700; text-decoration:none;'>{n['headline']}</a><span style='color:{color}; font-weight:bold;'>{status} ({score:.2f})</span></div><div style='font-size:0.8rem; color:#94a3b8;'>{n['source']} &bull; {datetime.fromtimestamp(n['datetime']).strftime('%Y-%m-%d %H:%M')}</div></div>", unsafe_allow_html=True)
                else: st.info("Son 1 haftaya ait haber bulunamadı.")
            except: st.error("Haberler çekilemedi.")


# --- TAB 4: GENEL PİYASA RADARI ---
with tab4:
    with st.spinner("Genel piyasa taranıyor..."):
        df_general = fetch_general_screener()
    if not df_general.empty:
        st.dataframe(df_general.drop(columns=["TV_Rec"]), use_container_width=True, hide_index=True)


# --- TAB 5: HTML DOSYASINDAKİ AKILLI RADARLAR (YENİ ENTEGRASYON) ---
with tab5:
    st.markdown("### ⚡ Mega Fırsat Radarları (Premium HTML Algoritmaları)")
    st.markdown("<p style='color:#94a3b8; font-size:0.9rem;'>HTML dosyasında tasarlanan 6 farklı katı strateji filtresini çalıştırır.</p>", unsafe_allow_html=True) #[cite: 5]
    
    col_pool, col_radar = st.columns([1, 2])
    with col_pool:
        pool_limit = st.selectbox("Taranacak Havuz (En büyük hisseler):", [30, 50], index=1, help="Finnhub API limitlerini korumak için maksimum 50 adet önerilir.")
    with col_radar:
        scan_type = st.radio("Radar Stratejisi Seçin:", [
            "📉 52W Dip Radarı (Dipten <= %15)", 
            "🎯 Bilanço Sürprizi (> %5 Kâr Sürprizi)", 
            "🐋 Balina Alımları (Yönetici Alımları)", 
            "🚀 Hedef Fiyat Ucuzluk (Potansiyel > %15)",
            "🔥 Altın Kesişim (Dip + Balina + Sürpriz)"
        ], horizontal=True)

    if st.button("📡 Taramayı Başlat", use_container_width=True, type="primary"):
        symbols_to_scan = US_STOCK_POOL[:pool_limit] #[cite: 5]
        results = []
        
        # Daha hızlı sonuç için TradingView bulk datasını önbellekten çekiyoruz[cite: 4]
        tv_data = fetch_general_screener() 
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, sym in enumerate(symbols_to_scan):
            status_text.text(f"Analiz Ediliyor: {sym} ({i+1}/{pool_limit})")
            try:
                if "52W Dip" in scan_type:
                    row = tv_data[tv_data['Hisse'] == sym]
                    if not row.empty:
                        dip = row.iloc[0]['52W Dip Farkı (%)']
                        if 0 < dip <= 15.0:
                            results.append({"Hisse": sym, "Skor": dip, "Detay": f"Dipten Uzaklık: %{dip:.1f}", "Renk": "#3b82f6"}) #[cite: 5]
                            
                elif "Hedef Fiyat" in scan_type:
                    row = tv_data[tv_data['Hisse'] == sym]
                    if not row.empty:
                        pot = row.iloc[0]['Hedef Potansiyeli (%)']
                        if pot >= 15.0:
                            results.append({"Hisse": sym, "Skor": pot, "Detay": f"Ort. Analist Hedefine Potansiyel: +%{pot:.1f}", "Renk": "#ec4899"}) #[cite: 5]

                elif "Bilanço Sürprizi" in scan_type:
                    earn = requests.get(f"https://finnhub.io/api/v1/stock/earnings?symbol={sym}&token={FINNHUB_API_KEY}").json() #[cite: 1]
                    if earn and isinstance(earn, list) and len(earn) > 0:
                        if earn[0].get('actual') and earn[0].get('estimate'):
                            surp = ((earn[0]['actual'] - earn[0]['estimate']) / abs(earn[0]['estimate'])) * 100
                            if surp > 5.0:
                                results.append({"Hisse": sym, "Skor": surp, "Detay": f"Kâr Sürprizi: +%{surp:.1f}", "Renk": "#a855f7"}) #[cite: 5]
                    time.sleep(0.3) # API Limit koruması

                elif "Balina Alımları" in scan_type:
                    three_months_ago = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
                    insider = requests.get(f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={sym}&from={three_months_ago}&token={FINNHUB_API_KEY}").json().get('data', []) #[cite: 1]
                    total_bought = sum([(t.get('change',0) * t.get('transactionPrice',0)) for t in insider if t.get('change',0) > 0 and t.get('transactionPrice',0) > 0])
                    if total_bought > 500000:
                        results.append({"Hisse": sym, "Skor": total_bought, "Detay": f"Son 3 Ay Toplam İçeriden Alım: ${(total_bought/1000000):.1f} Milyon", "Renk": "#06b6d4"}) #[cite: 5]
                    time.sleep(0.3)
                    
                elif "Altın Kesişim" in scan_type:
                    row = tv_data[tv_data['Hisse'] == sym]
                    if not row.empty:
                        dip = row.iloc[0]['52W Dip Farkı (%)']
                        if 0 < dip <= 20.0:
                            insider = requests.get(f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={sym}&token={FINNHUB_API_KEY}").json().get('data', [])
                            total_bought = sum([(t.get('change',0) * t.get('transactionPrice',0)) for t in insider if t.get('change',0) > 0 and t.get('transactionPrice',0) > 0])
                            if total_bought > 200000:
                                earn = requests.get(f"https://finnhub.io/api/v1/stock/earnings?symbol={sym}&token={FINNHUB_API_KEY}").json()
                                surp = 0
                                if earn and len(earn) > 0 and earn[0].get('estimate'):
                                    surp = ((earn[0].get('actual',0) - earn[0]['estimate']) / abs(earn[0]['estimate'])) * 100
                                if surp > 2.0:
                                    results.append({"Hisse": sym, "Skor": dip, "Detay": f"Dip: +%{dip:.1f} | Balina: ${(total_bought/1000):.0f}K | Kâr: +%{surp:.1f}", "Renk": "#fbbf24"}) #[cite: 5]
                            time.sleep(0.4)

            except Exception as e:
                pass
            
            progress_bar.progress((i + 1) / pool_limit)
        
        status_text.empty()
        progress_bar.empty()
        
        if results:
            st.success(f"Tarama Tamamlandı! Kriterlere uyan {len(results)} fırsat bulundu.")
            cols = st.columns(3)
            for idx, res in enumerate(results):
                with cols[idx % 3]:
                    st.markdown(f"""
                    <div class="radar-card" style="border-left-color: {res['Renk']};">
                        <div class="radar-title"><span>{res['Hisse']}</span><span style="color:{res['Renk']};">⚡</span></div>
                        <div class="radar-desc">Uyumlu Fırsat Tespit Edildi</div>
                        <div class="radar-highlight" style="color:{res['Renk']};">{res['Detay']}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("Kriterlere uyan hisse bulunamadı.")
