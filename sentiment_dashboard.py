"""
SENTIMENT DASHBOARD - Web Application
======================================
Flask app that serves the Market Sentiment Tracker dashboard
with live data from indian_stock_analysis_output.xlsx

Usage: python sentiment_dashboard.py
Then open: http://localhost:5001
"""

import os
import sys
from pathlib import Path
from flask import Flask, render_template_string, jsonify
import pandas as pd
import numpy as np

app = Flask(__name__)

# ==================== CONFIGURATION ====================
BASE_PATH = Path(__file__).parent
EXCEL_FILE = BASE_PATH / "indian_stock_analysis_output.xlsx"

# ==================== DATA LOADING ====================
def load_sentiment_data():
    """Load sentiment data from Excel file"""
    if not EXCEL_FILE.exists():
        return None
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name='Quarterly Sentiment')
        return df
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def get_latest_sentiment():
    """Get the latest sentiment score for each company"""
    df = load_sentiment_data()
    if df is None or df.empty:
        return None
    
    # Convert to proper date for sorting
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6, 
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df['Sort_Date'] = df['Year'].astype(str) + df['Month_Num'].astype(str).str.zfill(2)
    
    # Get latest entry per company
    latest = df.sort_values('Sort_Date', ascending=False).groupby('Company').first().reset_index()
    return latest

def convert_to_score_100(sentiment_value):
    """Convert -1 to 1 sentiment to 0-100 scale"""
    return int(round((sentiment_value + 1) * 50))

def get_top_positive(n=5):
    """Get top N positive sentiment stocks"""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    top = latest.nlargest(n, 'Overall_Sentiment')
    results = []
    for _, row in top.iterrows():
        results.append({
            'symbol': row['Company'][:3].upper(),
            'name': row['Company'],
            'sector': row['Sector'],
            'score': convert_to_score_100(row['Overall_Sentiment']),
            'raw_score': round(row['Overall_Sentiment'], 3)
        })
    return results

def get_top_negative(n=5):
    """Get top N negative sentiment stocks"""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    bottom = latest.nsmallest(n, 'Overall_Sentiment')
    results = []
    for _, row in bottom.iterrows():
        results.append({
            'symbol': row['Company'][:3].upper(),
            'name': row['Company'],
            'sector': row['Sector'],
            'score': convert_to_score_100(row['Overall_Sentiment']),
            'raw_score': round(row['Overall_Sentiment'], 3)
        })
    return results

def get_sector_leaders():
    """Get average sentiment by sector"""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    sector_avg = latest.groupby('Sector')['Overall_Sentiment'].mean().sort_values(ascending=False)
    results = []
    icons = {
        'Banking': 'account_balance', 'Finance': 'account_balance',
        'Auto': 'directions_car', 'IT': 'computer', 
        'Pharma': 'medication', 'Healthcare': 'local_hospital',
        'Energy': 'bolt', 'Power': 'bolt',
        'Infrastructure': 'factory', 'Metals': 'factory',
        'FMCG': 'shopping_cart', 'Consumer': 'shopping_cart',
        'Telecom': 'cell_tower', 'Cement': 'apartment',
        'Unknown': 'analytics'
    }
    colors = ['indigo', 'orange', 'cyan', 'emerald', 'purple']
    
    for i, (sector, score) in enumerate(sector_avg.head(5).items()):
        results.append({
            'sector': sector,
            'score': round((score + 1) * 50, 1),
            'icon': icons.get(sector, 'analytics'),
            'color': colors[i % len(colors)],
            'description': 'Avg. Score'
        })
    return results

def get_distribution_data():
    """Get sentiment distribution for histogram"""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    # Create bins from -1 to 1
    bins = np.linspace(-1, 1, 11)
    hist, edges = np.histogram(latest['Overall_Sentiment'], bins=bins)
    
    max_count = max(hist) if len(hist) > 0 else 1
    results = []
    for i, count in enumerate(hist):
        results.append({
            'bin': i,
            'count': int(count),
            'height': int((count / max_count) * 100) if max_count > 0 else 0,
            'color': 'red' if i < 4 else ('amber' if i < 6 else 'emerald')
        })
    return results

def get_summary_stats():
    """Get summary statistics"""
    latest = get_latest_sentiment()
    if latest is None:
        return {'total': 0, 'positive': 0, 'negative': 0, 'neutral': 0}
    
    return {
        'total': len(latest),
        'positive': len(latest[latest['Sentiment_Category'] == 'Positive']),
        'negative': len(latest[latest['Sentiment_Category'] == 'Negative']),
        'neutral': len(latest[latest['Sentiment_Category'] == 'Neutral']),
        'avg_sentiment': round(latest['Overall_Sentiment'].mean(), 3)
    }

# ==================== HTML TEMPLATE ====================
HTML_TEMPLATE = '''<!DOCTYPE html>
<html class="dark" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Market Sentiment Tracker Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#0f172a",
                        "accent": "#3b82f6",
                        "background-light": "#f8fafc",
                        "background-dark": "#0f172a",
                        "surface-light": "rgba(255, 255, 255, 0.7)",
                        "surface-dark": "rgba(30, 41, 59, 0.7)",
                        "border-light": "rgba(226, 232, 240, 0.8)",
                        "border-dark": "rgba(51, 65, 85, 0.8)",
                    },
                    fontFamily: {
                        "display": ["Manrope", "sans-serif"]
                    },
                    borderRadius: { "DEFAULT": "0.25rem", "lg": "0.5rem", "xl": "0.75rem", "2xl": "1rem", "full": "9999px" },
                },
            },
        }
    </script>
<style>
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
.dark ::-webkit-scrollbar-thumb { background: #475569; }
.glass-card { backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }
</style>
</head>
<body class="font-display bg-background-light dark:bg-background-dark text-slate-800 dark:text-slate-100 h-screen flex overflow-hidden selection:bg-accent/30">
<main class="flex-1 flex flex-col h-full overflow-hidden relative bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-blue-100/50 via-transparent to-transparent dark:from-blue-900/20">

<header class="flex-none glass-card bg-white/80 dark:bg-slate-900/80 border-b border-border-light dark:border-border-dark px-6 py-4 z-20 sticky top-0">
<div class="max-w-[1600px] mx-auto w-full flex items-center justify-between gap-4">
<div class="flex items-center gap-4">
<div class="size-10 rounded-lg bg-primary dark:bg-blue-600 flex items-center justify-center text-white shadow-lg shadow-blue-500/20">
<span class="material-symbols-outlined">analytics</span>
</div>
<div>
<h1 class="text-slate-900 dark:text-white text-xl font-bold leading-tight">Indian Market Sentiment Tracker</h1>
<p class="text-slate-500 dark:text-slate-400 text-xs font-medium">Tracking {{ stats.total }} Stocks • Earnings Calls Analysis</p>
</div>
</div>
<div class="flex items-center gap-3">
<div class="hidden md:flex items-center px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-full border border-slate-200 dark:border-slate-700">
<span class="size-2 rounded-full bg-emerald-500 animate-pulse mr-2"></span>
<span class="text-xs font-semibold text-slate-600 dark:text-slate-300">Data Loaded</span>
</div>
<button onclick="location.reload()" class="p-2 text-slate-500 hover:text-primary dark:hover:text-white transition-colors" title="Refresh">
<span class="material-symbols-outlined">refresh</span>
</button>
</div>
</div>
</header>

<div class="flex-1 overflow-y-auto">
<div class="max-w-[1600px] mx-auto w-full p-6 flex flex-col gap-6">

<!-- Top 3 Cards -->
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
<!-- Top Positive -->
<div class="glass-card bg-white/60 dark:bg-slate-800/60 p-0 rounded-xl border border-border-light dark:border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-emerald-500 text-sm">trending_up</span>
<h3 class="text-sm font-bold text-slate-800 dark:text-white uppercase tracking-wide">Top Positive</h3>
</div>
<span class="text-xs text-slate-400">Latest</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for stock in top_positive %}
<div class="flex items-center justify-between p-2 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors cursor-pointer group">
<div class="flex items-center gap-3">
<div class="size-8 rounded bg-slate-100 dark:bg-slate-700 flex items-center justify-center font-bold text-xs text-slate-600 dark:text-slate-300">{{ stock.symbol }}</div>
<div>
<p class="text-sm font-bold text-slate-700 dark:text-slate-200">{{ stock.name }}</p>
<p class="text-[10px] text-slate-400">{{ stock.sector }}</p>
</div>
</div>
<div class="text-right">
<span class="text-emerald-600 dark:text-emerald-400 font-bold text-sm">{{ stock.score }}/100</span>
<div class="w-16 h-1 bg-slate-200 dark:bg-slate-600 rounded-full mt-1 overflow-hidden">
<div class="h-full bg-emerald-500" style="width:{{ stock.score }}%"></div>
</div>
</div>
</div>
{% endfor %}
</div>
</div>

<!-- Top Negative -->
<div class="glass-card bg-white/60 dark:bg-slate-800/60 p-0 rounded-xl border border-border-light dark:border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-red-500 text-sm">trending_down</span>
<h3 class="text-sm font-bold text-slate-800 dark:text-white uppercase tracking-wide">Top Negative</h3>
</div>
<span class="text-xs text-slate-400">Latest</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for stock in top_negative %}
<div class="flex items-center justify-between p-2 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors cursor-pointer group">
<div class="flex items-center gap-3">
<div class="size-8 rounded bg-slate-100 dark:bg-slate-700 flex items-center justify-center font-bold text-xs text-slate-600 dark:text-slate-300">{{ stock.symbol }}</div>
<div>
<p class="text-sm font-bold text-slate-700 dark:text-slate-200">{{ stock.name }}</p>
<p class="text-[10px] text-slate-400">{{ stock.sector }}</p>
</div>
</div>
<div class="text-right">
<span class="text-red-600 dark:text-red-400 font-bold text-sm">{{ stock.score }}/100</span>
<div class="w-16 h-1 bg-slate-200 dark:bg-slate-600 rounded-full mt-1 overflow-hidden">
<div class="h-full bg-red-500" style="width:{{ stock.score }}%"></div>
</div>
</div>
</div>
{% endfor %}
</div>
</div>

<!-- Sector Leaders -->
<div class="glass-card bg-white/60 dark:bg-slate-800/60 p-0 rounded-xl border border-border-light dark:border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-primary dark:text-blue-400 text-sm">leaderboard</span>
<h3 class="text-sm font-bold text-slate-800 dark:text-white uppercase tracking-wide">Sector Leaders</h3>
</div>
<span class="text-xs text-slate-400">Aggregated</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for sector in sector_leaders %}
<div class="flex items-center justify-between p-2 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors cursor-pointer group">
<div class="flex items-center gap-3">
<div class="size-8 rounded-full bg-{{ sector.color }}-100 text-{{ sector.color }}-600 dark:bg-{{ sector.color }}-900/40 dark:text-{{ sector.color }}-300 flex items-center justify-center">
<span class="material-symbols-outlined text-[18px]">{{ sector.icon }}</span>
</div>
<div>
<p class="text-sm font-bold text-slate-700 dark:text-slate-200">{{ sector.sector }}</p>
<p class="text-[10px] text-slate-400">{{ sector.description }}</p>
</div>
</div>
<div class="text-right">
<span class="text-{{ sector.color }}-600 dark:text-{{ sector.color }}-400 font-bold text-sm">{{ sector.score }}</span>
</div>
</div>
{% endfor %}
</div>
</div>
</div>

<!-- Summary Stats -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
<div class="glass-card bg-white/60 dark:bg-slate-800/60 p-4 rounded-xl border border-border-light dark:border-border-dark">
<p class="text-xs uppercase font-bold text-slate-400 mb-1">Total Stocks</p>
<p class="text-2xl font-bold text-slate-800 dark:text-white">{{ stats.total }}</p>
</div>
<div class="glass-card bg-emerald-50 dark:bg-emerald-900/20 p-4 rounded-xl border border-emerald-200 dark:border-emerald-800">
<p class="text-xs uppercase font-bold text-emerald-600 mb-1">Positive</p>
<p class="text-2xl font-bold text-emerald-700 dark:text-emerald-400">{{ stats.positive }}</p>
</div>
<div class="glass-card bg-amber-50 dark:bg-amber-900/20 p-4 rounded-xl border border-amber-200 dark:border-amber-800">
<p class="text-xs uppercase font-bold text-amber-600 mb-1">Neutral</p>
<p class="text-2xl font-bold text-amber-700 dark:text-amber-400">{{ stats.neutral }}</p>
</div>
<div class="glass-card bg-red-50 dark:bg-red-900/20 p-4 rounded-xl border border-red-200 dark:border-red-800">
<p class="text-xs uppercase font-bold text-red-600 mb-1">Negative</p>
<p class="text-2xl font-bold text-red-700 dark:text-red-400">{{ stats.negative }}</p>
</div>
</div>

<!-- All Stocks Table -->
<div class="glass-card bg-white dark:bg-slate-800 rounded-xl border border-border-light dark:border-border-dark shadow-sm p-5">
<div class="flex justify-between items-center mb-4">
<h3 class="text-lg font-bold text-slate-900 dark:text-white">All Analyzed Stocks</h3>
<span class="text-xs text-slate-400">Sorted by Latest Sentiment</span>
</div>
<div class="overflow-x-auto">
<table class="w-full text-sm">
<thead>
<tr class="border-b border-slate-200 dark:border-slate-700">
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Company</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Sector</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Period</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Sentiment</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Category</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Polarity</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Keyword</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Guidance</th>
<th class="text-left py-3 px-2 font-bold text-slate-600 dark:text-slate-300">Risk</th>
</tr>
</thead>
<tbody>
{% for stock in all_stocks %}
<tr class="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/30">
<td class="py-3 px-2 font-bold text-slate-800 dark:text-white">{{ stock.Company }}</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ stock.Sector }}</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ stock.Month }} {{ stock.Year }}</td>
<td class="py-3 px-2">
<span class="font-bold {% if stock.Overall_Sentiment > 0.2 %}text-emerald-600{% elif stock.Overall_Sentiment < -0.1 %}text-red-600{% else %}text-amber-600{% endif %}">
{{ "%.3f"|format(stock.Overall_Sentiment) }}
</span>
</td>
<td class="py-3 px-2">
<span class="px-2 py-1 rounded text-xs font-bold {% if stock.Sentiment_Category == 'Positive' %}bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400{% elif stock.Sentiment_Category == 'Negative' %}bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400{% else %}bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400{% endif %}">
{{ stock.Sentiment_Category }}
</span>
</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ "%.3f"|format(stock.Polarity) }}</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ "%.3f"|format(stock.Keyword_Sentiment) }}</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ "%.1f"|format(stock.Guidance) }}</td>
<td class="py-3 px-2 text-slate-600 dark:text-slate-400">{{ "%.3f"|format(stock.Risk) }}</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div>

</div>
</div>

</main>
</body>
</html>'''

# ==================== ROUTES ====================
@app.route('/')
def dashboard():
    """Main dashboard page"""
    df = load_sentiment_data()
    
    if df is None or df.empty:
        return render_template_string('''
        <html><body style="font-family:sans-serif;text-align:center;padding:50px">
        <h1>No Data Available</h1>
        <p>Please run batch_stock_analyzer.py first to generate sentiment data.</p>
        <p>Expected file: <code>{{ file }}</code></p>
        </body></html>
        ''', file=str(EXCEL_FILE))
    
    return render_template_string(
        HTML_TEMPLATE,
        top_positive=get_top_positive(5),
        top_negative=get_top_negative(5),
        sector_leaders=get_sector_leaders(),
        stats=get_summary_stats(),
        all_stocks=df.to_dict('records')
    )

@app.route('/api/data')
def api_data():
    """API endpoint for raw data"""
    return jsonify({
        'top_positive': get_top_positive(5),
        'top_negative': get_top_negative(5),
        'sector_leaders': get_sector_leaders(),
        'stats': get_summary_stats()
    })

# ==================== MAIN ====================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(" SENTIMENT DASHBOARD")
    print("=" * 60)
    print(f" Data File: {EXCEL_FILE}")
    print(f" URL: http://localhost:5001")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5001, debug=True)
