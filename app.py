"""
INDIAN MARKET SENTIMENT TERMINAL - Advanced Dashboard
=====================================================
Flask app serving the Market Sentiment Terminal with Bloomberg-style UI.
"""

import os
import io
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import json

# ==================== CONFIGURATION ====================
BASE_PATH = Path(__file__).parent
EXCEL_FILE = BASE_PATH / "Sentiment_Analysis_Production.xlsx"

# Logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== SECTOR MAPPING ====================
SECTOR_MAPPING = {
    'ADANIENT': 'Infrastructure', 'ADANIPORTS': 'Infrastructure', 'APOLLOHOSP': 'Healthcare',
    'ASIANPAINT': 'Chemicals', 'AXISBANK': 'Banking', 'BAJAJ-AUTO': 'Auto',
    'BAJFINANCE': 'Finance', 'BAJAJFINSV': 'Finance', 'BEL': 'Defense',
    'BHARTIARTL': 'Telecom', 'CIPLA': 'Pharma', 'COALINDIA': 'Metals',
    'DRREDDY': 'Pharma', 'EICHERMOT': 'Auto', 'ETERNAL': 'Consumer',
    'GRASIM': 'Chemicals', 'HCLTECH': 'IT Services', 'HDFCBANK': 'Banking',
    'HDFCLIFE': 'Finance', 'HINDALCO': 'Metals', 'HINDUNILVR': 'FMCG',
    'ICICIBANK': 'Banking', 'ITC': 'FMCG', 'INFY': 'IT Services',
    'INDIGO': 'Airlines', 'JSWSTEEL': 'Metals', 'JIOFIN': 'Finance',
    'KOTAKBANK': 'Banking', 'LT': 'Infrastructure', 'M&M': 'Auto',
    'MARUTI': 'Auto', 'NTPC': 'Power', 'NESTLEIND': 'FMCG', 'ONGC': 'Energy',
    'POWERGRID': 'Power', 'RELIANCE': 'Energy', 'SBILIFE': 'Finance',
    'SBIN': 'Banking', 'SUNPHARMA': 'Pharma', 'TCS': 'IT Services',
    'TATACONSUM': 'FMCG', 'TATASTEEL': 'Metals', 'TECHM': 'IT Services',
    'TITAN': 'Consumer', 'TRENT': 'Retail', 'ULTRACEMCO': 'Cement', 'WIPRO': 'IT Services',
}

# Keywords mapping
TOP_KEYWORDS = {
    'HCLTECH': 'GenAI', 'TCS': 'Deal Wins', 'RELIANCE': 'New Energy', 'ITC': 'FMCG Growth',
    'LT': 'Order Book', 'INFY': 'Digital', 'BHARTIARTL': 'ARPU', 'ASIANPAINT': 'Volume',
    'BAJFINANCE': 'NIM Comp.', 'WIPRO': 'Attrition', 'TATASTEEL': 'Europe', 'ADANIPORTS': 'Cargo Vol',
    'HDFCBANK': 'NII Growth', 'ICICIBANK': 'Retail', 'SBIN': 'NPAs', 'AXISBANK': 'Deposits',
    'SUNPHARMA': 'US Mkt', 'CIPLA': 'Generics', 'DRREDDY': 'Pipeline', 'MARUTI': 'SUV Mix',
}

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def load_sentiment_data():
    if not EXCEL_FILE.exists():
        logger.warning(f"Data file not found: {EXCEL_FILE}")
        return None
    try:
        return pd.read_excel(EXCEL_FILE, sheet_name='Quarterly Sentiment')
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return None

def get_all_data():
    df = load_sentiment_data()
    if df is None or df.empty:
        return None
    if 'Sector' not in df.columns:
        df['Sector'] = df['Company'].map(SECTOR_MAPPING).fillna('Unknown')
    return df

def get_latest_sentiment():
    df = get_all_data()
    if df is None or df.empty:
        return None
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df['Sort_Date'] = df['Year'].astype(str) + df['Month_Num'].astype(str).str.zfill(2)
    return df.sort_values('Sort_Date', ascending=False).groupby('Company').first().reset_index()

def get_top_positive(n=5):
    latest = get_latest_sentiment()
    if latest is None:
        return []
    top = latest.nlargest(n, 'Overall_Sentiment')
    return [{'symbol': row['Company'][:3].upper(), 'name': row['Company'], 
             'sector': row.get('Sector', 'Unknown'),
             'score': round(row['Overall_Sentiment'], 2),
             'keyword': TOP_KEYWORDS.get(row['Company'], 'Strong')} 
            for _, row in top.iterrows()]

def get_top_negative(n=5):
    latest = get_latest_sentiment()
    if latest is None:
        return []
    bottom = latest.nsmallest(n, 'Overall_Sentiment')
    return [{'symbol': row['Company'][:3].upper(), 'name': row['Company'], 
             'sector': row.get('Sector', 'Unknown'),
             'score': round(row['Overall_Sentiment'], 2),
             'keyword': TOP_KEYWORDS.get(row['Company'], 'Weak')} 
            for _, row in bottom.iterrows()]

def get_sector_leaders():
    latest = get_latest_sentiment()
    if latest is None:
        return []
    sector_avg = latest.groupby('Sector')['Overall_Sentiment'].mean().sort_values(ascending=False)
    results = []
    for sector, score in sector_avg.head(5).items():
        results.append({'sector': sector, 'score': round(score, 2)})
    return results

def get_sector_heatmap_data():
    """Calculate sector-wise sentiment for heatmap with size based on stock count"""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    sector_data = latest.groupby('Sector').agg({
        'Overall_Sentiment': 'mean',
        'Company': 'count'
    }).reset_index()
    sector_data.columns = ['sector', 'avg_sentiment', 'count']
    sector_data['avg_sentiment'] = sector_data['avg_sentiment'].round(2)
    
    # Calculate size ratio based on stock count (for visual sizing)
    max_count = sector_data['count'].max() if len(sector_data) > 0 else 1
    sector_data['size_ratio'] = (sector_data['count'] / max_count * 100).round(0).astype(int)
    sector_data['size_ratio'] = sector_data['size_ratio'].clip(lower=40)  # Minimum 40% size
    
    return sector_data.to_dict('records')

def get_sentiment_distribution():
    """Calculate sentiment distribution for histogram"""
    latest = get_latest_sentiment()
    if latest is None:
        return {'buckets': [], 'mean': 0}
    
    # Create buckets from -1 to +1 in steps of 0.2
    buckets = []
    ranges = [(-1.0, -0.8), (-0.8, -0.6), (-0.6, -0.4), (-0.4, -0.2), (-0.2, 0.0),
              (0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    
    for low, high in ranges:
        count = len(latest[(latest['Overall_Sentiment'] >= low) & (latest['Overall_Sentiment'] < high)])
        # Determine color based on range
        if high <= -0.5:
            color = 'red'
        elif low >= 0.5:
            color = 'emerald'
        elif high <= 0:
            color = 'rose'
        elif low >= 0:
            color = 'teal'
        else:
            color = 'amber'
        buckets.append({'range': f"{low:.1f} to {high:.1f}", 'count': count, 'low': low, 'high': high, 'color': color})
    
    mean_val = latest['Overall_Sentiment'].mean()
    return {'buckets': buckets, 'mean': round(mean_val, 2)}

def get_summary_stats():
    latest = get_latest_sentiment()
    if latest is None:
        return {'total': 0, 'positive': 0, 'negative': 0, 'neutral': 0, 'avg_score': 0}
    
    if 'Sentiment_Category' not in latest.columns:
        latest['Sentiment_Category'] = latest['Overall_Sentiment'].apply(
            lambda x: 'Positive' if x > 0.2 else ('Negative' if x < -0.1 else 'Neutral'))
    
    avg_score = latest['Overall_Sentiment'].mean()
    
    return {
        'total': len(latest),
        'positive': len(latest[latest['Sentiment_Category'] == 'Positive']),
        'negative': len(latest[latest['Sentiment_Category'] == 'Negative']),
        'neutral': len(latest[latest['Sentiment_Category'] == 'Neutral']),
        'avg_score': round(avg_score, 2)
    }

def get_market_mood(avg_score):
    if avg_score >= 0.5:
        return 'Extreme Greed', 'emerald'
    elif avg_score >= 0.2:
        return 'Greed', 'emerald'
    elif avg_score >= -0.2:
        return 'Neutral', 'amber'
    elif avg_score >= -0.5:
        return 'Fear', 'red'
    else:
        return 'Extreme Fear', 'red'

def get_paginated_stocks(page=1, per_page=5):
    latest = get_latest_sentiment()
    if latest is None:
        return [], 0, 0
    
    # Add top keyword
    latest['TopKeyword'] = latest['Company'].map(TOP_KEYWORDS).fillna('N/A')
    
    # Sort by sentiment descending
    latest = latest.sort_values('Overall_Sentiment', ascending=False)
    
    total = len(latest)
    total_pages = (total + per_page - 1) // per_page
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    page_data = latest.iloc[start_idx:end_idx]
    
    return page_data.to_dict('records'), total, total_pages

def get_company_time_series(companies):
    df = get_all_data()
    if df is None:
        return {}
    
    result = {}
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    
    for company in companies:
        company_data = df[df['Company'] == company].copy()
        if company_data.empty:
            continue
        company_data['Month_Num'] = company_data['Month'].map(month_map)
        company_data['Sort_Date'] = company_data['Year'].astype(str) + company_data['Month_Num'].astype(str).str.zfill(2)
        company_data = company_data.sort_values('Sort_Date')
        
        result[company] = [
            {'period': f"{row['Month']} {row['Year']}", 'score': round(row['Overall_Sentiment'], 3)}
            for _, row in company_data.iterrows()
        ]
    
    return result

def get_all_companies():
    latest = get_latest_sentiment()
    if latest is None:
        return []
    return sorted(latest['Company'].unique().tolist())

# ==============================================================================
# FLASK APP
# ==============================================================================
app = Flask(__name__)

HTML_TEMPLATE = '''<!DOCTYPE html>
<html class="dark" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Indian Stock Market Sentiment Terminal</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
<script>
tailwind.config = {
    darkMode: "class",
    theme: {
        extend: {
            fontFamily: {
                sans: ["Inter", "sans-serif"],
                mono: ["JetBrains Mono", "monospace"],
            },
            colors: {
                background: { light: "#f3f4f6", dark: "#0f172a" },
                surface: { light: "#ffffff", dark: "#1e293b", darker: "#0b1120" },
                primary: "#3b82f6",
                accent: { green: "#10b981", red: "#ef4444", amber: "#f59e0b", neon: "#a3e635", electric: "#22d3ee" }
            },
        },
    },
};
</script>
<style>
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
.glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); }
</style>
</head>
<body class="bg-background-dark text-slate-200 font-sans min-h-screen selection:bg-primary selection:text-white pb-12">

<header class="sticky top-0 z-50 bg-surface-darker/90 backdrop-blur-md border-b border-slate-800">
<div class="max-w-[1600px] mx-auto px-4 h-16 flex items-center justify-between">
<div class="flex items-center gap-4">
<div class="w-10 h-10 bg-primary rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/20">
<span class="material-symbols-outlined text-white">analytics</span>
</div>
<div>
<h1 class="text-xl font-bold tracking-tight text-white leading-none">Indian Stock Market Sentiment Terminal</h1>
<p class="text-xs text-slate-400 mt-1">Historical Analysis View • Earnings Calls Analysis</p>
</div>
</div>
<div class="flex items-center gap-4">
<div class="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-full">
<div class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
<span class="text-xs font-medium text-emerald-400">Data Loaded</span>
</div>
<button onclick="location.reload()" class="p-2 text-slate-400 hover:text-white transition-colors">
<span class="material-symbols-outlined text-xl">refresh</span>
</button>
</div>
</div>
</header>

<main class="max-w-[1600px] mx-auto px-4 mt-6 space-y-6">

<!-- Market Overview Cards -->
<section class="grid grid-cols-1 md:grid-cols-4 gap-4">
<div class="bg-surface-dark p-4 rounded-xl border border-slate-700/50 shadow-sm flex items-center justify-between">
<div>
<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Stocks</span>
<div class="text-xl font-bold text-white mt-1">{{ stats.total }}</div>
</div>
<div class="text-right">
<span class="material-symbols-outlined text-primary text-2xl">monitoring</span>
</div>
</div>
<div class="bg-surface-dark p-4 rounded-xl border border-slate-700/50 shadow-sm flex items-center justify-between">
<div>
<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Positive</span>
<div class="text-xl font-bold text-emerald-400 mt-1">{{ stats.positive }}</div>
</div>
<div class="text-right">
<span class="material-symbols-outlined text-emerald-500 text-2xl">trending_up</span>
</div>
</div>
<div class="bg-surface-dark p-4 rounded-xl border border-slate-700/50 shadow-sm flex items-center justify-between">
<div>
<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Negative</span>
<div class="text-xl font-bold text-red-400 mt-1">{{ stats.negative }}</div>
</div>
<div class="text-right">
<span class="material-symbols-outlined text-red-500 text-2xl">trending_down</span>
</div>
</div>
<div class="bg-surface-dark p-4 rounded-xl border border-slate-700/50 shadow-sm flex items-center gap-4 relative overflow-hidden group">
<div class="absolute right-0 top-0 bottom-0 w-1 bg-{{ mood_color }}-500"></div>
<div class="p-3 bg-{{ mood_color }}-500/10 rounded-full">
<span class="material-symbols-outlined text-{{ mood_color }}-500 text-2xl">speed</span>
</div>
<div>
<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Market Mood</span>
<div class="text-xl font-bold text-{{ mood_color }}-500 mt-1">{{ mood }}</div>
<span class="text-xs text-slate-500">Score: {{ stats.avg_score }}</span>
</div>
</div>
</section>

<!-- Top Sentiment Cards -->
<section class="grid grid-cols-1 md:grid-cols-3 gap-6">
<!-- Top Positive -->
<div class="bg-surface-dark rounded-xl border border-slate-700/50 p-5 shadow-sm flex flex-col h-[380px]">
<div class="flex items-center justify-between mb-4 border-b border-slate-700 pb-2">
<h3 class="text-sm font-semibold text-slate-300 uppercase tracking-wide">Top Positive Sentiment</h3>
<span class="material-symbols-outlined text-emerald-500 text-lg">arrow_upward</span>
</div>
<div class="space-y-3 overflow-y-auto pr-2">
{% for stock in top_positive %}
<div class="flex items-center justify-between group cursor-pointer hover:bg-slate-800/50 p-2 rounded-lg transition-colors" onclick="addToChart('{{ stock.name }}')">
<div class="flex items-center gap-3">
<div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center text-[10px] font-bold">{{ stock.symbol }}</div>
<div>
<div class="text-sm font-semibold text-white">{{ stock.name }}</div>
<div class="text-xs text-emerald-500">{{ stock.keyword }}</div>
</div>
</div>
<div class="text-right">
<div class="text-sm font-bold text-emerald-400 font-mono">{{ "+%.2f"|format(stock.score) if stock.score >= 0 else "%.2f"|format(stock.score) }}</div>
<div class="w-16 h-1 bg-slate-700 rounded-full mt-1"><div class="h-full bg-emerald-500 rounded-full" style="width:{{ ((stock.score + 1) / 2 * 100)|int }}%"></div></div>
</div>
</div>
{% endfor %}
{% if not top_positive %}<p class="p-4 text-slate-500 text-sm">No data available.</p>{% endif %}
</div>
</div>

<!-- Top Negative -->
<div class="bg-surface-dark rounded-xl border border-slate-700/50 p-5 shadow-sm flex flex-col h-[380px]">
<div class="flex items-center justify-between mb-4 border-b border-slate-700 pb-2">
<h3 class="text-sm font-semibold text-slate-300 uppercase tracking-wide">Top Negative Risks</h3>
<span class="material-symbols-outlined text-red-500 text-lg">priority_high</span>
</div>
<div class="space-y-3 overflow-y-auto pr-2">
{% for stock in top_negative %}
<div class="flex items-center justify-between group cursor-pointer hover:bg-slate-800/50 p-2 rounded-lg transition-colors" onclick="addToChart('{{ stock.name }}')">
<div class="flex items-center gap-3">
<div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center text-[10px] font-bold">{{ stock.symbol }}</div>
<div>
<div class="text-sm font-semibold text-white">{{ stock.name }}</div>
<div class="text-xs text-red-400">{{ stock.keyword }}</div>
</div>
</div>
<div class="text-right">
<div class="text-sm font-bold text-red-400 font-mono">{{ "%.2f"|format(stock.score) }}</div>
<div class="w-16 h-1 bg-slate-700 rounded-full mt-1"><div class="h-full bg-red-500 rounded-full ml-auto" style="width:{{ ((1 - stock.score) / 2 * 100)|int }}%"></div></div>
</div>
</div>
{% endfor %}
{% if not top_negative %}<p class="p-4 text-slate-500 text-sm">No data available.</p>{% endif %}
</div>
</div>

<!-- Sector Leaders -->
<div class="bg-surface-dark rounded-xl border border-slate-700/50 p-5 shadow-sm flex flex-col h-[380px]">
<div class="flex items-center justify-between mb-4 border-b border-slate-700 pb-2">
<h3 class="text-sm font-semibold text-slate-300 uppercase tracking-wide">Sector Leaders</h3>
<span class="material-symbols-outlined text-primary text-lg">pie_chart</span>
</div>
<div class="space-y-4 overflow-y-auto pr-2">
{% for sector in sector_leaders %}
<div class="flex items-center justify-between">
<span class="text-sm text-slate-300">{{ sector.sector }}</span>
<div class="flex items-center gap-2">
<div class="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
<div class="h-full {% if sector.score >= 0 %}bg-emerald-500{% else %}bg-red-500{% endif %}" style="width:{{ ((sector.score + 1) / 2 * 100)|int }}%"></div>
</div>
<span class="text-xs font-mono text-white w-12 text-right">{{ "+%.2f"|format(sector.score) if sector.score >= 0 else "%.2f"|format(sector.score) }}</span>
</div>
</div>
{% endfor %}
{% if not sector_leaders %}<p class="p-4 text-slate-500 text-sm">No data available.</p>{% endif %}
</div>
</div>
</section>

<!-- Sector Heatmap & Distribution -->
<section class="grid grid-cols-1 lg:grid-cols-3 gap-6">
<!-- Sector Heatmap -->
<div class="lg:col-span-2 bg-surface-dark rounded-xl border border-slate-700/50 p-5 shadow-sm">
<div class="flex items-center justify-between mb-4">
<h3 class="text-lg font-bold text-white">Sector Heatmap</h3>
<div class="flex gap-4 text-[10px] text-slate-400">
<span class="flex items-center"><div class="w-3 h-3 bg-emerald-500 mr-1 rounded-sm"></div> Bullish (&gt; +0.5)</span>
<span class="flex items-center"><div class="w-3 h-3 bg-red-500 mr-1 rounded-sm"></div> Bearish (&lt; -0.5)</span>
</div>
</div>
<div id="sectorHeatmap" class="flex flex-wrap gap-1 min-h-[180px]">
{% for sector in sector_heatmap %}
<div class="rounded-sm cursor-pointer hover:ring-2 ring-white relative group flex items-center justify-center transition-all
{% if sector.avg_sentiment >= 0.5 %}bg-emerald-600{% elif sector.avg_sentiment >= 0.3 %}bg-emerald-500{% elif sector.avg_sentiment >= 0.1 %}bg-emerald-400{% elif sector.avg_sentiment >= -0.1 %}bg-amber-500{% elif sector.avg_sentiment >= -0.3 %}bg-red-400{% elif sector.avg_sentiment >= -0.5 %}bg-red-500{% else %}bg-red-600{% endif %}"
style="width: {{ sector.size_ratio * 1.2 }}px; height: {{ sector.size_ratio }}px; min-width: 60px; min-height: 45px;">
<div class="opacity-0 group-hover:opacity-100 transition-opacity absolute inset-0 flex flex-col items-center justify-center bg-black/70 rounded-sm p-1 z-10">
<span class="text-[10px] font-bold text-white text-center leading-tight">{{ sector.sector }}</span>
<span class="text-[11px] font-mono text-white font-bold">{{ "+%.2f"|format(sector.avg_sentiment) if sector.avg_sentiment >= 0 else "%.2f"|format(sector.avg_sentiment) }}</span>
<span class="text-[8px] text-slate-300">{{ sector.count }} stocks</span>
</div>
<span class="text-[9px] font-bold text-white/90 group-hover:opacity-0 text-center px-1">{{ sector.sector[:4] }}</span>
</div>
{% endfor %}
</div>
</div>

<!-- Sentiment Distribution -->
<div class="bg-surface-dark rounded-xl border border-slate-700/50 p-5 shadow-sm flex flex-col">
<h3 class="text-lg font-bold text-white mb-4">Sentiment Distribution</h3>
<div class="flex-1 flex items-end justify-center relative w-full px-2 min-h-[150px]">
<div class="absolute bottom-6 left-0 right-0 h-px bg-slate-700"></div>
<div class="flex items-end gap-1 h-32 w-full justify-center">
{% set max_count = sentiment_dist.buckets|map(attribute='count')|max if sentiment_dist.buckets else 1 %}
{% for bucket in sentiment_dist.buckets %}
<div class="flex-1 flex flex-col items-center relative group">
{% set height_pct = (bucket.count / max_count * 100) if max_count > 0 else 0 %}
<div class="w-full rounded-t transition-all hover:opacity-80
{% if bucket.high <= -0.4 %}bg-red-500/80{% elif bucket.high <= 0 %}bg-red-400/60{% elif bucket.low >= 0.4 %}bg-emerald-500/80{% elif bucket.low >= 0 %}bg-emerald-400/60{% else %}bg-amber-400/60{% endif %}"
style="height:{{ height_pct|int }}%"></div>
{% if bucket.low <= sentiment_dist.mean < bucket.high %}
<div class="absolute -top-8 left-1/2 -translate-x-1/2 bg-slate-800 text-[9px] text-white px-2 py-0.5 rounded border border-slate-600 whitespace-nowrap z-10">Mean</div>
{% endif %}
<span class="absolute -bottom-4 text-[8px] text-slate-500 opacity-0 group-hover:opacity-100">{{ bucket.count }}</span>
</div>
{% endfor %}
</div>
</div>
<div class="flex justify-between text-xs text-slate-500 mt-6 px-2">
<span>-1.0</span>
<span>0.0</span>
<span>+1.0</span>
</div>
</div>
</section>

<!-- Time Series Chart -->
<section class="bg-surface-dark rounded-xl border border-slate-700/50 p-6 shadow-lg">
<div class="flex flex-col xl:flex-row xl:items-center justify-between mb-6 gap-4">
<div>
<h2 class="text-xl font-bold text-white">Sentiment Time Series</h2>
<p class="text-sm text-slate-400">Compare vs. Market or Sector</p>
</div>
<div class="flex flex-wrap items-center gap-3">
<div class="flex-1 xl:flex-none flex items-center gap-3">
<div class="relative group w-full xl:w-96">
<div id="stockSelector" class="flex flex-wrap items-center gap-2 p-2 bg-slate-900 border border-slate-700 rounded-lg min-h-[42px] cursor-text" onclick="document.getElementById('stockInput').focus()">
<span class="text-slate-400 pointer-events-none">
<span class="material-symbols-outlined text-sm">search</span>
</span>
<div id="selectedStocks" class="flex flex-wrap gap-1"></div>
<input id="stockInput" class="flex-1 bg-transparent border-none text-sm text-white focus:ring-0 p-0 min-w-[100px] placeholder:text-slate-500" placeholder="Add stock..." type="text" list="stockList" onkeydown="handleStockInput(event)"/>
<datalist id="stockList">
{% for company in all_companies %}
<option value="{{ company }}">
{% endfor %}
</datalist>
</div>
</div>
<button onclick="addStockFromInput()" class="px-3 py-2 bg-primary hover:bg-blue-600 text-white rounded-lg text-sm font-medium flex items-center gap-1">
<span class="material-symbols-outlined text-sm">add</span> Add
</button>
</div>
</div>
</div>

<div id="chartContainer" class="relative w-full h-[350px] bg-surface-darker rounded-lg border border-slate-800/50 p-4">
<div id="chartLoading" class="absolute inset-0 flex items-center justify-center text-slate-500">
<span>Select stocks to view time series...</span>
</div>
<canvas id="sentimentChart" class="hidden"></canvas>
</div>

<div id="chartLegend" class="flex items-center justify-center gap-6 mt-4 flex-wrap"></div>
</section>

<!-- Paginated Stock Table -->
<section class="bg-surface-dark rounded-xl border border-slate-700/50 shadow-sm overflow-hidden mb-12">
<div class="p-6 border-b border-slate-700 flex flex-col md:flex-row md:items-center justify-between gap-4">
<div>
<h2 class="text-xl font-bold text-white">All Analyzed Stocks</h2>
<p class="text-sm text-slate-400">Detailed sentiment breakdown by entity</p>
</div>
<div class="flex gap-3">
<button class="flex items-center gap-2 px-4 py-2 border border-slate-600 rounded-lg text-sm text-slate-300 hover:bg-slate-800 transition-colors">
<span class="material-symbols-outlined text-sm">filter_list</span>
Filter
</button>
<button onclick="exportExcel()" class="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm transition-colors shadow-lg shadow-emerald-500/20">
<span class="material-symbols-outlined text-sm">download</span>
Export Excel
</button>
</div>
</div>
<div class="overflow-x-auto">
<table class="w-full text-left border-collapse">
<thead>
<tr class="border-b border-slate-700 text-xs uppercase tracking-wider text-slate-400 font-medium">
<th class="px-6 py-4">Company</th>
<th class="px-6 py-4">Sector</th>
<th class="px-6 py-4">Period</th>
<th class="px-6 py-4 w-64">Sentiment Score (-1 to +1)</th>
<th class="px-6 py-4 text-center">Polarity</th>
<th class="px-6 py-4">Top Keyword</th>
<th class="px-6 py-4">Guidance</th>
<th class="px-6 py-4 text-right">Risk</th>
</tr>
</thead>
<tbody id="stockTableBody" class="divide-y divide-slate-700 text-sm">
</tbody>
</table>
</div>
<div class="px-6 py-4 border-t border-slate-700 flex items-center justify-between text-sm text-slate-400">
<span id="paginationInfo">Showing 1–5 of {{ stats.total }} Stocks</span>
<div id="paginationControls" class="flex items-center gap-1"></div>
</div>
</section>

</main>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// Chart colors
const CHART_COLORS = ['#22d3ee', '#a3e635', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6', '#f43f5e'];
let selectedStocks = [];
let chartInstance = null;
let stockTimeSeriesData = {};
let currentPage = 1;
const perPage = 5;
let totalStocks = {{ stats.total }};

// ==================== PAGINATION ====================
function loadStockTable(page = 1) {
    currentPage = page;
    fetch(`/api/stocks?page=${page}&per_page=${perPage}`)
        .then(res => res.json())
        .then(data => {
            renderStockTable(data.stocks);
            updatePagination(data.total, data.total_pages, page);
        })
        .catch(err => console.error('Error loading stocks:', err));
}

function renderStockTable(stocks) {
    const tbody = document.getElementById('stockTableBody');
    tbody.innerHTML = stocks.map(stock => {
        const score = stock.Overall_Sentiment;
        const scoreClass = score > 0.2 ? 'text-emerald-500' : (score < -0.1 ? 'text-red-500' : 'text-amber-500');
        const guidanceText = stock.Guidance > 0 ? 'Raised' : (stock.Guidance < 0 ? 'Lowered' : 'Maintained');
        const guidanceClass = stock.Guidance > 0 ? 'text-emerald-500' : (stock.Guidance < 0 ? 'text-red-500' : 'text-slate-400');
        const riskClass = stock.Risk > 0.7 ? 'text-red-500 font-bold' : (stock.Risk > 0.4 ? 'text-amber-500' : 'text-slate-400');
        
        const barWidth = Math.abs(score) * 50;
        const barClass = score >= 0 ? 'bg-emerald-500' : 'bg-red-500';
        const barPosition = score >= 0 ? 'left-1/2' : 'right-1/2';
        const barRound = score >= 0 ? 'rounded-r-full' : 'rounded-l-full';
        
        return `
        <tr class="hover:bg-slate-800/50 transition-colors cursor-pointer" onclick="addToChart('${stock.Company}')">
            <td class="px-6 py-4 font-bold text-white">${stock.Company}</td>
            <td class="px-6 py-4 text-slate-400">${stock.Sector || 'Unknown'}</td>
            <td class="px-6 py-4 text-slate-400">${stock.Month} ${stock.Year}</td>
            <td class="px-6 py-4">
                <div class="flex items-center gap-3">
                    <span class="font-bold ${scoreClass} w-12 text-right font-mono">${score >= 0 ? '+' : ''}${score.toFixed(2)}</span>
                    <div class="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden relative">
                        <div class="absolute left-1/2 w-0.5 h-full bg-slate-500 opacity-50"></div>
                        <div class="h-full ${barClass} absolute ${barPosition} ${barRound}" style="width:${barWidth}%"></div>
                    </div>
                </div>
            </td>
            <td class="px-6 py-4 text-center text-slate-300 font-mono">${(stock.Polarity || 0).toFixed(3)}</td>
            <td class="px-6 py-4">
                <span class="px-2 py-1 bg-slate-700 rounded text-xs text-slate-300">${stock.TopKeyword || 'N/A'}</span>
            </td>
            <td class="px-6 py-4 ${guidanceClass} font-medium">${guidanceText}</td>
            <td class="px-6 py-4 text-right ${riskClass}">${(stock.Risk || 0).toFixed(2)}</td>
        </tr>`;
    }).join('');
}

function updatePagination(total, totalPages, currentPage) {
    const start = (currentPage - 1) * perPage + 1;
    const end = Math.min(currentPage * perPage, total);
    document.getElementById('paginationInfo').textContent = `Showing ${start}–${end} of ${total} Stocks`;
    
    const controls = document.getElementById('paginationControls');
    let html = `<button onclick="loadStockTable(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''} class="px-3 py-1 border border-slate-700 rounded hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed">Prev</button>`;
    
    for (let i = 1; i <= Math.min(totalPages, 5); i++) {
        if (i === currentPage) {
            html += `<button class="px-3 py-1 bg-primary text-white rounded">${i}</button>`;
        } else {
            html += `<button onclick="loadStockTable(${i})" class="px-3 py-1 border border-slate-700 rounded hover:bg-slate-800">${i}</button>`;
        }
    }
    
    html += `<button onclick="loadStockTable(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''} class="px-3 py-1 border border-slate-700 rounded hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>`;
    
    controls.innerHTML = html;
}

function exportExcel() {
    window.location.href = '/api/export';
}

// ==================== CHART FUNCTIONS ====================
function addToChart(stockName) {
    if (!selectedStocks.includes(stockName)) {
        selectedStocks.push(stockName);
        updateSelectedStocksUI();
        fetchAndUpdateChart();
    }
}

function removeFromChart(stockName) {
    selectedStocks = selectedStocks.filter(s => s !== stockName);
    updateSelectedStocksUI();
    fetchAndUpdateChart();
}

function handleStockInput(event) {
    if (event.key === 'Enter') {
        addStockFromInput();
    }
}

function addStockFromInput() {
    const input = document.getElementById('stockInput');
    const value = input.value.trim().toUpperCase();
    if (value && !selectedStocks.includes(value)) {
        selectedStocks.push(value);
        updateSelectedStocksUI();
        fetchAndUpdateChart();
    }
    input.value = '';
}

function updateSelectedStocksUI() {
    const container = document.getElementById('selectedStocks');
    container.innerHTML = selectedStocks.map((stock, idx) => `
        <div class="flex items-center gap-1 px-2 py-0.5 bg-slate-800 rounded-md border border-slate-700">
            <div class="w-2 h-2 rounded-full" style="background-color: ${CHART_COLORS[idx % CHART_COLORS.length]}"></div>
            <span class="text-xs text-slate-200 font-medium">${stock}</span>
            <button class="text-slate-500 hover:text-white" onclick="event.stopPropagation(); removeFromChart('${stock}')">
                <span class="material-symbols-outlined text-[12px]">close</span>
            </button>
        </div>
    `).join('');
}

function fetchAndUpdateChart() {
    if (selectedStocks.length === 0) {
        document.getElementById('chartLoading').classList.remove('hidden');
        document.getElementById('chartLoading').innerHTML = '<span>Select stocks to view time series...</span>';
        document.getElementById('sentimentChart').classList.add('hidden');
        document.getElementById('chartLegend').innerHTML = '';
        if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
        return;
    }

    document.getElementById('chartLoading').innerHTML = '<span class="animate-pulse">Loading data...</span>';
    
    fetch('/api/timeseries?companies=' + encodeURIComponent(selectedStocks.join(',')))
        .then(res => res.json())
        .then(data => {
            stockTimeSeriesData = data;
            renderChart();
        })
        .catch(err => {
            console.error(err);
            document.getElementById('chartLoading').innerHTML = '<span class="text-red-400">Error loading data</span>';
        });
}

function renderChart() {
    document.getElementById('chartLoading').classList.add('hidden');
    const canvas = document.getElementById('sentimentChart');
    canvas.classList.remove('hidden');

    let allPeriods = new Set();
    Object.values(stockTimeSeriesData).forEach(series => {
        series.forEach(d => allPeriods.add(d.period));
    });
    const labels = Array.from(allPeriods).sort();

    const datasets = selectedStocks.map((stock, idx) => {
        const series = stockTimeSeriesData[stock] || [];
        const dataMap = {};
        series.forEach(d => { dataMap[d.period] = d.score; });
        
        return {
            label: stock,
            data: labels.map(l => dataMap[l] ?? null),
            borderColor: CHART_COLORS[idx % CHART_COLORS.length],
            backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] + '20',
            fill: true,
            tension: 0.4,
            pointRadius: 4,
            pointHoverRadius: 6,
            spanGaps: true,
        };
    });

    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1e293b',
                    titleColor: '#fff',
                    bodyColor: '#94a3b8',
                    borderColor: '#334155',
                    borderWidth: 1,
                }
            },
            scales: {
                y: {
                    min: -1, max: 1,
                    grid: { color: '#334155' },
                    ticks: { color: '#64748b', callback: v => v.toFixed(1) }
                },
                x: {
                    grid: { color: '#1e293b' },
                    ticks: { color: '#64748b' }
                }
            }
        }
    });

    const legendContainer = document.getElementById('chartLegend');
    legendContainer.innerHTML = selectedStocks.map((stock, idx) => {
        const series = stockTimeSeriesData[stock] || [];
        const latestScore = series.length > 0 ? series[series.length - 1].score : 0;
        const color = CHART_COLORS[idx % CHART_COLORS.length];
        return `
            <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-full" style="background-color: ${color}; box-shadow: 0 0 6px ${color}80"></span>
                <span class="text-xs font-semibold text-slate-300">${stock}</span>
                <span class="text-[10px] font-mono ml-1" style="color: ${color}">${latestScore >= 0 ? '+' : ''}${latestScore.toFixed(2)}</span>
            </div>
        `;
    }).join('');
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadStockTable(1);
    updateSelectedStocksUI();
});
</script>

</body></html>'''

@app.route('/')
def dashboard():
    stats = get_summary_stats()
    mood, mood_color = get_market_mood(stats['avg_score'])
    
    return render_template_string(HTML_TEMPLATE,
        top_positive=get_top_positive(5),
        top_negative=get_top_negative(5),
        sector_leaders=get_sector_leaders(),
        sector_heatmap=get_sector_heatmap_data(),
        sentiment_dist=get_sentiment_distribution(),
        stats=stats,
        mood=mood,
        mood_color=mood_color,
        all_companies=get_all_companies()
    )

@app.route('/api/stocks')
def api_stocks():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 5))
    stocks, total, total_pages = get_paginated_stocks(page, per_page)
    return jsonify({
        'stocks': stocks,
        'total': total,
        'total_pages': total_pages,
        'current_page': page
    })

@app.route('/api/data')
def api_data():
    stats = get_summary_stats()
    mood, mood_color = get_market_mood(stats['avg_score'])
    return jsonify({
        'top_positive': get_top_positive(5),
        'top_negative': get_top_negative(5),
        'sector_leaders': get_sector_leaders(),
        'sector_heatmap': get_sector_heatmap_data(),
        'sentiment_distribution': get_sentiment_distribution(),
        'stats': stats,
        'mood': mood,
        'all_companies': get_all_companies()
    })

@app.route('/api/timeseries')
def api_timeseries():
    companies = request.args.get('companies', '').split(',')
    companies = [c.strip() for c in companies if c.strip()]
    return jsonify(get_company_time_series(companies))

@app.route('/api/export')
def api_export():
    """Export ALL time period data to Excel (full historical data)"""
    df = get_all_data()
    if df is None:
        return jsonify({'error': 'No data available'}), 404
    
    # Add top keyword
    df['TopKeyword'] = df['Company'].map(TOP_KEYWORDS).fillna('N/A')
    
    # Sort by Company and Date
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df = df.sort_values(['Company', 'Year', 'Month_Num'], ascending=[True, False, False])
    
    # Select relevant columns
    export_cols = ['Company', 'Sector', 'Year', 'Month', 'Overall_Sentiment', 
                   'Polarity', 'Keyword_Sentiment', 'Guidance', 'Risk', 'TopKeyword']
    export_df = df[[c for c in export_cols if c in df.columns]]
    
    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df.to_excel(writer, sheet_name='Sentiment Analysis (All Periods)', index=False)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='sentiment_analysis_all_periods.xlsx'
    )

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'data_loaded': EXCEL_FILE.exists()})

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    print("\n" + "=" * 60)
    print(" INDIAN STOCK MARKET SENTIMENT TERMINAL")
    print("=" * 60)
    print(f" Dashboard: http://localhost:{port}")
    print(f" Data File: {EXCEL_FILE}")
    print(f" Data Exists: {EXCEL_FILE.exists()}")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=port, debug=False)
