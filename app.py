"""
INDIAN MARKET SENTIMENT TERMINAL - Advanced Dashboard
=====================================================
Flask app serving the Market Sentiment Terminal with Bloomberg-style UI.

Dashboard: https://YOUR-RAILWAY-URL.up.railway.app
"""

import os
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request
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

# Keywords for positive sentiment display
POSITIVE_KEYWORDS = {
    'HCLTECH': 'GenAI', 'TCS': 'Deal Wins', 'RELIANCE': 'New Energy', 'ITC': 'FMCG Growth',
    'LT': 'Order Book', 'INFY': 'Digital', 'BHARTIARTL': 'ARPU', 'ASIANPAINT': 'Volume',
}

NEGATIVE_KEYWORDS = {
    'BAJFINANCE': 'NIM Compression', 'INFY': 'Weak Volume', 'WIPRO': 'Attrition',
    'TATASTEEL': 'Europe Weakness', 'UPL': 'Inventory Loss',
}

# ==============================================================================
# HELPER FUNCTIONS FOR DASHBOARD
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
             'keyword': POSITIVE_KEYWORDS.get(row['Company'], 'Strong')} 
            for _, row in top.iterrows()]

def get_top_negative(n=5):
    latest = get_latest_sentiment()
    if latest is None:
        return []
    bottom = latest.nsmallest(n, 'Overall_Sentiment')
    return [{'symbol': row['Company'][:3].upper(), 'name': row['Company'], 
             'sector': row.get('Sector', 'Unknown'),
             'score': round(row['Overall_Sentiment'], 2),
             'keyword': NEGATIVE_KEYWORDS.get(row['Company'], 'Weak')} 
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
<div class="text-emerald-500 font-medium flex items-center justify-end">
<span class="material-symbols-outlined text-base mr-0.5">monitoring</span>
Analyzed
</div>
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

<!-- All Stocks Table -->
<section class="bg-surface-dark rounded-xl border border-slate-700/50 shadow-sm overflow-hidden mb-12">
<div class="p-6 border-b border-slate-700 flex flex-col md:flex-row md:items-center justify-between gap-4">
<div>
<h2 class="text-xl font-bold text-white">All Analyzed Stocks</h2>
<p class="text-sm text-slate-400">Detailed sentiment breakdown by entity</p>
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
<th class="px-6 py-4">Guidance</th>
<th class="px-6 py-4 text-right">Risk</th>
</tr>
</thead>
<tbody class="divide-y divide-slate-700 text-sm">
{% for stock in all_stocks %}
<tr class="hover:bg-slate-800/50 transition-colors cursor-pointer" onclick="addToChart('{{ stock.Company }}')">
<td class="px-6 py-4 font-bold text-white">{{ stock.Company }}</td>
<td class="px-6 py-4 text-slate-400">{{ stock.Sector }}</td>
<td class="px-6 py-4 text-slate-400">{{ stock.Month }} {{ stock.Year }}</td>
<td class="px-6 py-4">
<div class="flex items-center gap-3">
<span class="font-bold {% if stock.Overall_Sentiment > 0.2 %}text-emerald-500{% elif stock.Overall_Sentiment < -0.1 %}text-red-500{% else %}text-amber-500{% endif %} w-12 text-right font-mono">{{ "+%.2f"|format(stock.Overall_Sentiment) if stock.Overall_Sentiment >= 0 else "%.2f"|format(stock.Overall_Sentiment) }}</span>
<div class="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden relative">
<div class="absolute left-1/2 w-0.5 h-full bg-slate-500 opacity-50"></div>
{% if stock.Overall_Sentiment >= 0 %}
<div class="h-full bg-emerald-500 absolute left-1/2 rounded-r-full" style="width:{{ (stock.Overall_Sentiment * 50)|int }}%"></div>
{% else %}
<div class="h-full bg-red-500 absolute right-1/2 rounded-l-full" style="width:{{ (-stock.Overall_Sentiment * 50)|int }}%"></div>
{% endif %}
</div>
</div>
</td>
<td class="px-6 py-4 text-center text-slate-300 font-mono">{{ "%.3f"|format(stock.Polarity) }}</td>
<td class="px-6 py-4 {% if stock.Guidance > 0 %}text-emerald-500{% elif stock.Guidance < 0 %}text-red-500{% else %}text-slate-400{% endif %} font-medium">
{% if stock.Guidance > 0 %}Raised{% elif stock.Guidance < 0 %}Lowered{% else %}Maintained{% endif %}
</td>
<td class="px-6 py-4 text-right {% if stock.Risk > 0.7 %}text-red-500 font-bold{% elif stock.Risk > 0.4 %}text-amber-500{% else %}text-slate-400{% endif %}">{{ "%.2f"|format(stock.Risk) }}</td>
</tr>
{% endfor %}
{% if not all_stocks %}<tr><td colspan="7" class="py-8 text-center text-slate-500">No data available.</td></tr>{% endif %}
</tbody>
</table>
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

    // Collect all unique periods
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

    // Update legend
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

// Initialize with empty chart
document.addEventListener('DOMContentLoaded', () => {
    updateSelectedStocksUI();
});
</script>

</body></html>'''

@app.route('/')
def dashboard():
    df = load_sentiment_data()
    all_stocks = df.to_dict('records') if df is not None and not df.empty else []
    stats = get_summary_stats()
    mood, mood_color = get_market_mood(stats['avg_score'])
    
    return render_template_string(HTML_TEMPLATE,
        top_positive=get_top_positive(5),
        top_negative=get_top_negative(5),
        sector_leaders=get_sector_leaders(),
        stats=stats,
        mood=mood,
        mood_color=mood_color,
        all_stocks=all_stocks,
        all_companies=get_all_companies()
    )

@app.route('/api/data')
def api_data():
    stats = get_summary_stats()
    mood, mood_color = get_market_mood(stats['avg_score'])
    return jsonify({
        'top_positive': get_top_positive(5),
        'top_negative': get_top_negative(5),
        'sector_leaders': get_sector_leaders(),
        'stats': stats,
        'mood': mood,
        'all_companies': get_all_companies()
    })

@app.route('/api/timeseries')
def api_timeseries():
    companies = request.args.get('companies', '').split(',')
    companies = [c.strip() for c in companies if c.strip()]
    return jsonify(get_company_time_series(companies))

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
