
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import scipy.stats as stats
from pathlib import Path
from streamlit_extras.colored_header import colored_header
from streamlit_extras.metric_cards import style_metric_cards

# ==================== CONFIGURATION ====================
st.set_page_config(
    page_title="Market Sentiment AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for Premium UI
st.markdown("""
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 3rem;}
    h1 {text-align: center; font-size: 2.8rem; font-weight: 800; color: #1E293B; margin-bottom: 0px;}
    p {font-size: 1.1rem; color: #64748B;}

    /* Clean Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }

    /* List Styling */
    .list-item {
        display: flex;
        justify_content: space-between;
        align-items: center;
        padding: 10px 5px;
        border-bottom: 1px solid #F1F5F9;
        font-size: 1rem;
    }
    .score-pos { color: #16A34A; font-weight: 700; }
    .score-neg { color: #DC2626; font-weight: 700; }
    </style>
    """, unsafe_allow_html=True)

# Constants
BASE_PATH = Path(r"C:\Users\vmik5\OneDrive - Shri Vile Parle Kelavani Mandal\Documents\Python Scripts\Latent_data\Screener_Project")
EXCEL_FILE = BASE_PATH / "Sentiment_Analysis_Production.xlsx"

# HARDCODED MARKET CAP DATA
MARKET_CAP_DATA = {
    'ADANIENT': 274700, 'ADANIPORTS': 320000, 'APOLLOHOSP': 120000, 'ASIANPAINT': 290000,
    'AXISBANK': 430000, 'BAJAJ-AUTO': 200000, 'BAJFINANCE': 630000, 'BAJAJFINSV': 330000,
    'BEL': 220000, 'BHARTIARTL': 1250000, 'CIPLA': 140000, 'COALINDIA': 300000,
    'DRREDDY': 130000, 'EICHERMOT': 140000, 'ETERNAL': 12500,
    'GRASIM': 240000, 'HCLTECH': 450000, 'HDFCBANK': 1540000, 'HDFCLIFE': 140000,
    'HINDALCO': 130000, 'HINDUNILVR': 540000, 'ICICIBANK': 990000, 'ITC': 500000,
    'INFY': 660000, 'INDIGO': 150000, 'JSWSTEEL': 200000, 'JIOFIN': 180000,
    'KOTAKBANK': 420000, 'LT': 550000, 'M&M': 450000, 'MARUTI': 500000,
    'MAXHEALTH': 100000, 'NTPC': 310000, 'NESTLEIND': 250000, 'ONGC': 300000,
    'POWERGRID': 300000, 'RELIANCE': 2080000, 'SBILIFE': 140000, 'SHRIRAMFIN': 170000,
    'SBIN': 890000, 'SUNPHARMA': 430000, 'TCS': 1160000, 'TATACONSUM': 150000,
    'TMCV': 175000, 'TMPV': 175000, 'TATASTEEL': 200000, 'TECHM': 115000, 
    'TITAN': 340000, 'TRENT': 200000, 'ULTRACEMCO': 335000, 'WIPRO': 240000
}

# ==================== DATA LOADING ====================
@st.cache_data
def load_data():
    if not EXCEL_FILE.exists(): return None
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name='Quarterly Sentiment')
        df['Date_Str'] = df['Month'] + ' ' + df['Year'].astype(str)
        df['Date'] = pd.to_datetime(df['Date_Str'], format='%b %Y')
        df = df.sort_values(['Company', 'Date'])

        if 'Overall_Score' in df.columns: df['Score'] = df['Overall_Score']
        elif 'Overall_Sentiment' in df.columns: df['Score'] = df['Overall_Sentiment']

        df['Market_Cap'] = df['Company'].map(MARKET_CAP_DATA).fillna(0)
        return df
    except Exception as e:
        st.error(f"Error: {e}"); return None

# Helper for color conversion
def hex_to_rgba(hex_color, opacity):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{opacity})"
    return hex_color

# ==================== MAIN UI ====================
def main():
    df = load_data()
    if df is None: st.stop()

    # --- HEADER ---
    st.markdown("<h1>Indian Market Sentiment Tracker</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Analysis of Corporate Earnings Calls & Reports</p>", unsafe_allow_html=True)
    st.markdown("---")

    latest_df = df.sort_values('Date').groupby('Company').tail(1)

    # --- TOP METRICS ---
    c1, c2, c3 = st.columns(3)

    def render_list(title, data, color_hex):
        st.markdown(f'<div style="background:white; padding:15px; border-radius:12px; border:1px solid #E2E8F0; box-shadow:0 2px 4px rgba(0,0,0,0.05);">', unsafe_allow_html=True)
        colored_header(label=title, description="", color_name=color_hex)
        for _, row in data.iterrows():
            val_color = "score-pos" if row['Score'] > 0 else "score-neg"
            # FIX: ADDED COLON HERE
            st.markdown(f"""
            <div class="list-item">
                <span style="font-weight:600; color:#334155;">{row.name if 'Sector' not in row else row['Company']}</span>
                <span class="{val_color}">: {row['Score']:.2f}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c1: render_card = render_list("Top Positive", latest_df.sort_values('Score', ascending=False).head(5), "green-70")
    with c2: render_card = render_list("Top Negative", latest_df.sort_values('Score', ascending=True).head(5), "red-70")

    sector_avg = latest_df.groupby('Sector')['Score'].mean().sort_values(ascending=False).head(5)
    with c3: render_card = render_list("Sector Leaders", sector_avg.to_frame(name='Score'), "blue-70")

    st.markdown("###")

    # --- VISUALS ROW ---
    col_heat, col_dist = st.columns([1.8, 1.2])

    with col_heat:
        st.subheader("Sector Performance")
        sector_perf = latest_df.groupby('Sector')[['Score']].mean().reset_index()
        sector_perf['Count'] = latest_df.groupby('Sector')['Company'].count().values

        fig_heat = px.treemap(sector_perf, path=['Sector'], values='Count', color='Score', 
                              color_continuous_scale='RdYlGn', range_color=[-0.5, 0.5])
        fig_heat.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=340)
        st.plotly_chart(fig_heat, use_container_width=True)

    with col_dist:
        st.subheader("Market Spread (Bell Curve)")
        x_data = latest_df['Score']

        # Calculate Normal Distribution
        mu, std = x_data.mean(), x_data.std()
        x_range = np.linspace(-1, 1, 100)
        pdf = stats.norm.pdf(x_range, mu, std)

        # Scale curve to match histogram height
        counts, bins = np.histogram(x_data, bins=15, density=True)
        # scale_factor = len(x_data) * (bins[1] - bins[0]) # Not needed for density plot

        fig_dist = go.Figure()

        # 1. Histogram
        fig_dist.add_trace(go.Histogram(
            x=x_data, nbinsx=15, name='Companies', 
            marker_color='#636EFA', opacity=0.6,
            histnorm='probability density' 
        ))

        # 2. Bell Curve Line
        fig_dist.add_trace(go.Scatter(
            x=x_range, y=pdf, mode='lines', name='Normal Dist.',
            line=dict(color='black', width=2, dash='dot')
        ))

        # 3. Zero Line
        fig_dist.add_vline(x=0, line_width=2, line_color="#333")

        fig_dist.update_layout(
            margin=dict(t=0, l=0, r=0, b=0), height=340,
            xaxis_title="Sentiment Score", showlegend=False,
            template="plotly_white",
            xaxis=dict(range=[-1.1, 1.1], showgrid=False),
            yaxis=dict(showgrid=False, showticklabels=False)
        )
        st.plotly_chart(fig_dist, use_container_width=True)

    # --- DEEP DIVE ---
    colored_header(label="Filter & Compare", description="Detailed analysis with filters", color_name="blue-70")

    c_filt, c_graph = st.columns([1, 3])

    with c_filt:
        st.markdown("###### Filters")

        # Market Cap Filter
        c_min, c_max = st.columns(2)
        min_cap = c_min.number_input("Min Cap", 0, 2500000, 10000, step=10000)
        max_cap = c_max.number_input("Max Cap", 0, 2500000, 2500000, step=50000)

        # Sector Filter
        sectors = ["All Sectors"] + sorted(df['Sector'].unique().tolist())
        sel_sector = st.selectbox("Industry", sectors)

        # Logic
        filtered = df.copy()
        filtered = filtered[(filtered['Market_Cap'] >= min_cap) & (filtered['Market_Cap'] <= max_cap)]

        if sel_sector != "All Sectors":
            filtered = filtered[filtered['Sector'] == sel_sector]

        avail_comps = sorted(filtered['Company'].unique())

        if not avail_comps:
            st.warning("No companies match filters.")

        # Selector
        default = avail_comps[:2] if avail_comps else []
        sel_comps = st.multiselect("Select Companies", avail_comps, default=default)

    with c_graph:
        if sel_comps:
            # Dynamic Metrics
            cols = st.columns(min(len(sel_comps), 4))
            for i, comp in enumerate(sel_comps[:4]):
                row = latest_df[latest_df['Company'] == comp].iloc[0]
                cols[i].metric(label=comp, value=f"{row['Score']:.2f}", 
                               delta=f"₹{row['Market_Cap']/1000:.0f}k Cr", delta_color="off")

            style_metric_cards(border_left_color="#636EFA", border_radius_px=10, box_shadow=True)

            st.markdown("---")

            # Graph
            fig = go.Figure()
            colors = px.colors.qualitative.Plotly # Get nicer colors

            for i, comp in enumerate(sel_comps):
                data = df[df['Company'] == comp]
                width = 4 if len(sel_comps) == 1 else 2

                # Get dynamic color
                color_hex = colors[i % len(colors)]
                fill_color = hex_to_rgba(color_hex, 0.1)

                fig.add_trace(go.Scatter(
                    x=data['Date'], y=data['Score'], 
                    mode='lines+markers', name=comp, 
                    line=dict(width=width, color=color_hex),
                    fill='tozeroy', fillcolor=fill_color
                ))

            fig.add_hrect(y0=0, y1=1.5, fillcolor="green", opacity=0.05, line_width=0)
            fig.add_hrect(y0=-1.5, y1=0, fillcolor="red", opacity=0.05, line_width=0)

            fig.update_layout(title="Sentiment Trend", yaxis_title="Score", yaxis=dict(range=[-1.1, 1.1]),
                              height=450, hovermode="x unified", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("👈 Select companies to begin.")

    with st.expander("📄 View & Download Data"):
        st.dataframe(latest_df[['Company', 'Sector', 'Score', 'Market_Cap']].sort_values('Score', ascending=False), use_container_width=True)

if __name__ == "__main__":
    main()
