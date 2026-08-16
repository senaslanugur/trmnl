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
    
    div[data-testid="stMetricValue"] > div {
        white-space: normal !important; word-wrap: break-word !important; font-size: 1.25rem !important; line-height: 1.4 !important;
    }
    div[data-testid="stMetricLabel"] {
        word-wrap: break-word !important; white-space: normal !important;
    }

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

# --- GLOBAL AYARLAR VE NLP ---
FINNHUB_API_KEY = "c94i99aad3if4j50rvn0"

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
    analyzer.lexicon.update(FINANCIAL_LEXICON)
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
    }

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

# --- SADECE AMERİKA HİSSELERİ (ADR/DR HARİÇ) BULK VERİ ÇEKİMİ ---
@st.cache_data(ttl=1800)
def fetch_general_screener(limit=5000):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        # Sadece orijinal 'stock' türündeki varlıkları al, yabancı ADR/DR'leri dışla
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}],
        "options": {"lang": "en"},
        "markets": ["america"],
        "columns": ["name", "close", "price_52_week_low", "price_52_week_high", "Recommend.All", "market_cap_basic", "price_target_price_mean", "volume"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, limit]
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json().get('data', [])
            parsed = []
            for item in data:
                sym = item['s'].split(':')[-1]
                d = item['d']
                
                name = d[0]
                close = d[1]
                low52 = d[2]
                high52 = d[3]
                rec = d[4]
                mcap = d[5]
                target_mean = d[6]
                vol = d[7] if len(d) > 7 else 0
                
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
                    "Market Cap": mcap_str, "Hacim": vol, "TV_Rec": rec if rec else 0
                })
            return pd.DataFrame(parsed)
        return pd.DataFrame()
    except Exception as e:
        print(f"Genel Tarayıcı Hatası: {e}")
        return pd.DataFrame()

def fetch_finnhub_analysis(ticker):
    try:
        quote = requests.get(f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        metric = requests.get(f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_API_KEY}").json().get('metric', {})
        recs = requests.get(f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={FINNHUB_API_KEY}").json()
        insider = requests.get(f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={FINNHUB_API_KEY}").json().get('data', [])

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
                balina_str = f"Alım ({(last_buy.get('change', 0)):,} lot | {last_buy['filingDate']})"

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
    "🌍 ABD Hisseleri (5000)",
    "⚡ Akıllı Para Radarları"
])

# --- TAB 1: ÇEKİRDEK TARAYICI (KESİNLİKLE DOKUNULMAMIŞTIR) ---
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
    st.markdown("### 🌍 Sadece ABD Hisseleri Radarı (Market Cap'e Göre En Büyük 5000 Hisse)")
    with st.spinner("Piyasadaki en büyük 5000 orijinal ABD hissesi TradingView üzerinden anlık taranıyor..."):
        df_general = fetch_general_screener(limit=5000)
        
    if not df_general.empty:
        filter_option = st.radio("Taramayı Filtrele:", ("Tümünü Göster", "🔥 52W Dibe En Yakın Olanlar (Potansiyel Dip)", "🚀 Katı Sinyal: GÜÇLÜ AL Verenler"), horizontal=True)
        df_filtered = df_general.copy()
        
        if filter_option == "🔥 52W Dibe En Yakın Olanlar (Potansiyel Dip)":
            df_filtered = df_filtered[df_filtered["52W Dip Farkı (%)"] <= 15.0].sort_values(by="52W Dip Farkı (%)", ascending=True)
        elif filter_option == "🚀 Katı Sinyal: GÜÇLÜ AL Verenler":
            df_filtered = df_filtered[df_filtered["Teknik Sinyal"] == "GÜÇLÜ AL 🔥"].sort_values(by="TV_Rec", ascending=False)
            
        df_filtered["Fiyat ($)"] = df_filtered["Fiyat ($)"].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "-")
        df_filtered["52W Dip Farkı (%)"] = df_filtered["52W Dip Farkı (%)"].apply(lambda x: f"%{x:.2f}")
        df_filtered["Hedef Potansiyeli (%)"] = df_filtered["Hedef Potansiyeli (%)"].apply(lambda x: f"%{x:.2f}")
        
        st.dataframe(df_filtered.drop(columns=["TV_Rec"]), use_container_width=True, hide_index=True)
    else:
        st.error("Veriler çekilemedi. API format değişikliği veya limit kısıtlaması yaşanmış olabilir.")

# --- TAB 5: AKILLI RADARLAR (5000 HİSSE & YAHOO FINANCE DESTEKLİ) ---
with tab5:
    st.markdown("### ⚡ Mega Fırsat Radarları (5000 Orijinal ABD Hissesi Havuzu)")
    st.markdown("<p style='color:#94a3b8; font-size:0.9rem;'>Piyasa değerine göre en büyük ABD hisselerini vektörel hızda analiz eder. Balina ve sürpriz kâr analizlerinde derin verilere inmek için Yahoo Finance altyapısı devreye girer.</p>", unsafe_allow_html=True)
    
    col_pool, col_radar = st.columns([1, 2])
    with col_pool:
        pool_limit = st.selectbox("Taranacak Havuz Büyüklüğü (Market Cap):", [1000, 3000, 5000], index=2)
    with col_radar:
        scan_type = st.radio("Radar Stratejisi Seçin:", [
            "📉 52W Dip Radarı (Dipten <= %15)", 
            "🚀 Hedef Fiyat Ucuzluk (Potansiyel > %20)",
            "🐋 Balina Alımları (Insider)", 
            "🔥 Altın Kesişim (Dip + Güçlü Sinyal)"
        ], horizontal=True)

    if st.button("📡 Taramayı Başlat", use_container_width=True, type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.text(f"TradingView'dan {pool_limit} orijinal ABD hissesi topluca indiriliyor...")
        tv_data = fetch_general_screener(limit=pool_limit)
        
        results = []
        
        if not tv_data.empty:
            if scan_type == "📉 52W Dip Radarı (Dipten <= %15)":
                filtered = tv_data[(tv_data['52W Dip Farkı (%)'] > 0) & (tv_data['52W Dip Farkı (%)'] <= 15.0)]
                filtered = filtered.sort_values(by="52W Dip Farkı (%)")
                for _, row in filtered.head(30).iterrows(): 
                    results.append({"Hisse": row['Hisse'], "Detay": f"Dipten Uzaklık: %{row['52W Dip Farkı (%)']:.1f}", "Renk": "#3b82f6"})
                    
            elif scan_type == "🚀 Hedef Fiyat Ucuzluk (Potansiyel > %20)":
                filtered = tv_data[tv_data['Hedef Potansiyeli (%)'] >= 20.0]
                filtered = filtered.sort_values(by="Hedef Potansiyeli (%)", ascending=False)
                for _, row in filtered.head(30).iterrows():
                    results.append({"Hisse": row['Hisse'], "Detay": f"Ort. Analist Hedefine Potansiyel: +%{row['Hedef Potansiyeli (%)']:.1f}", "Renk": "#ec4899"})
                    
            elif scan_type == "🐋 Balina Alımları (Insider)":
                status_text.text("Yahoo Finance üzerinden Insider işlemleri analiz ediliyor...")
                top_volume = tv_data.sort_values(by="Hacim", ascending=False).head(50)
                
                for count, (idx, row) in enumerate(top_volume.iterrows()):
                    sym = row['Hisse']
                    try:
                        ticker = yf.Ticker(sym)
                        insider = ticker.insider_purchases
                        if insider is not None and not insider.empty:
                            buy_shares = insider[insider['Shares'] > 0]['Shares'].sum()
                            if buy_shares > 100000: 
                                results.append({"Hisse": sym, "Detay": f"Güçlü İçeriden Alım Sinyali Tespit Edildi", "Renk": "#06b6d4"})
                    except:
                        pass
                    progress_bar.progress((count + 1) / len(top_volume))
                    
            elif scan_type == "🔥 Altın Kesişim (Dip + Güçlü Sinyal)":
                filtered = tv_data[(tv_data['52W Dip Farkı (%)'] > 0) & (tv_data['52W Dip Farkı (%)'] <= 20.0) & (tv_data['Teknik Sinyal'] == "GÜÇLÜ AL 🔥")]
                for _, row in filtered.head(30).iterrows():
                    results.append({"Hisse": row['Hisse'], "Detay": f"Dip: +%{row['52W Dip Farkı (%)']:.1f} | Sinyal: GÜÇLÜ AL 🔥", "Renk": "#fbbf24"})
            
            progress_bar.progress(1.0)
            status_text.empty()
            
            if results:
                st.success(f"Tarama Tamamlandı! {len(results)} fırsat bulundu.")
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
        else:
            status_text.empty()
            st.error("Veriler çekilemedi. API format değişikliği veya limit kısıtlaması yaşanmış olabilir.")
