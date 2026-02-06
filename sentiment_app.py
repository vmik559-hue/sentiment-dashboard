"""
INDIAN MARKET SENTIMENT TRACKER - Unified Web Application
==========================================================
Combined backend (sentiment analysis) + frontend (dashboard)

Usage:
    python sentiment_app.py                    # Start web server
    
Dashboard: http://localhost:5001
API Endpoints:
    /api/analyze?max=10     - Run analysis on stocks
    /api/data               - Get current sentiment data
"""

import os
import sys
import time
import re
import logging
import threading
from pathlib import Path
from urllib.parse import urljoin, quote, urlparse
from flask import Flask, render_template_string, jsonify, request, Response
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
import warnings

# Optional NLP imports
try:
    import PyPDF2
    from textblob import TextBlob
except ImportError:
    print("[!] Installing required packages...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "PyPDF2", "textblob", "openpyxl", "-q"], check=True)
    import PyPDF2
    from textblob import TextBlob

warnings.filterwarnings('ignore')
np.random.seed(42)

# ==================== CONFIGURATION ====================
BASE_PATH = Path(__file__).parent
CSV_FILE = BASE_PATH / "all-listed-companies.csv"
DOCUMENTS_ROOT = BASE_PATH / "Screener_Documents"
OUTPUT_FILE = BASE_PATH / "indian_stock_analysis_output.xlsx"

DOCUMENTS_ROOT.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Analysis state
analysis_status = {'running': False, 'progress': 0, 'total': 0, 'current': '', 'logs': []}

# ==================== SECTOR MAPPING ====================
SECTOR_MAPPING = {
    'ADANIENT': 'Infrastructure', 'ADANIPORTS': 'Infrastructure', 'APOLLOHOSP': 'Healthcare',
    'ASIANPAINT': 'Chemicals', 'AXISBANK': 'Banking', 'BAJAJ-AUTO': 'Auto',
    'BAJFINANCE': 'Finance', 'BAJAJFINSV': 'Finance', 'BEL': 'Defense',
    'BHARTIARTL': 'Telecom', 'CIPLA': 'Pharma', 'COALINDIA': 'Metals',
    'DRREDDY': 'Pharma', 'EICHERMOT': 'Auto', 'ETERNAL': 'Consumer',
    'GRASIM': 'Chemicals', 'HCLTECH': 'IT', 'HDFCBANK': 'Banking',
    'HDFCLIFE': 'Finance', 'HINDALCO': 'Metals', 'HINDUNILVR': 'FMCG',
    'ICICIBANK': 'Banking', 'ITC': 'FMCG', 'INFY': 'IT',
    'INDIGO': 'Airlines', 'JSWSTEEL': 'Metals', 'JIOFIN': 'Finance',
    'KOTAKBANK': 'Banking', 'LT': 'Infrastructure', 'M&M': 'Auto',
    'MARUTI': 'Auto', 'NTPC': 'Power', 'NESTLEIND': 'FMCG', 'ONGC': 'Energy',
    'POWERGRID': 'Power', 'RELIANCE': 'Energy', 'SBILIFE': 'Finance',
    'SBIN': 'Banking', 'SUNPHARMA': 'Pharma', 'TCS': 'IT',
    'TATACONSUM': 'FMCG', 'TATASTEEL': 'Metals', 'TECHM': 'IT',
    'TITAN': 'Consumer', 'TRENT': 'Retail', 'ULTRACEMCO': 'Cement', 'WIPRO': 'IT',
}

# ==============================================================================
# BACKEND: SCREENER DOWNLOADER
# ==============================================================================
class ScreenerDownloader:
    def __init__(self, output_folder):
        self.output_folder = Path(output_folder)
        self.base_url = "https://www.screener.in"
        self.impersonate_ver = "chrome120"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

    def get_company_page(self, symbol):
        url = f"{self.base_url}/company/{quote(symbol)}/consolidated/"
        try:
            response = cffi_requests.get(url, impersonate=self.impersonate_ver, headers=self.headers, timeout=30)
            return response.text if response.status_code == 200 else None
        except:
            return None

    def find_quarter_context(self, link_element):
        previous = link_element.find_previous()
        attempts = 0
        while previous and attempts < 10:
            text = previous.get_text(strip=True) if hasattr(previous, 'get_text') else str(previous)
            match = re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$', text)
            if match:
                return {'quarter': f"{match.group(1)} {match.group(2)}", 'year': match.group(2)}
            previous = previous.find_previous()
            attempts += 1
        return None

    def extract_date_from_url(self, url):
        match = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', url)
        if match:
            year = match.group(1)
            month_num = int(match.group(2))
            months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            month = months[month_num - 1] if 1 <= month_num <= 12 else 'Unknown'
            return {'quarter': f"{month}_{year}", 'year': year}
        return None

    def extract_concall_documents(self, html_content, symbol):
        soup = BeautifulSoup(html_content, 'html.parser')
        documents = []
        try:
            concalls_heading = None
            for heading in soup.find_all(['h2', 'h3', 'h4']):
                if heading.get_text(strip=True).lower() == 'concalls':
                    concalls_heading = heading
                    break
            if not concalls_heading:
                return []
            
            all_links = []
            current_element = concalls_heading.find_next()
            stop_keywords = ['announcements', 'annual reports', 'shareholding', 'quarters', 'documents']
            
            while current_element and len(all_links) < 300:
                if current_element.name in ['h2', 'h3', 'h4']:
                    if any(k in current_element.get_text(strip=True).lower() for k in stop_keywords):
                        break
                if current_element.name == 'a':
                    all_links.append(current_element)
                else:
                    all_links.extend(current_element.find_all('a', href=True) if hasattr(current_element, 'find_all') else [])
                current_element = current_element.find_next()
            
            seen_urls = set()
            for link in all_links:
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                if not href or href.startswith('#') or 'javascript:' in href:
                    continue
                if 'transcript' not in text:
                    continue
                
                quarter_info = self.find_quarter_context(link) or self.extract_date_from_url(href)
                current_quarter = quarter_info['quarter'] if quarter_info else 'Unknown'
                current_year = quarter_info['year'] if quarter_info else 'Unknown'
                full_url = urljoin(self.base_url, href)
                
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    documents.append({'symbol': symbol, 'quarter': current_quarter, 'year': current_year, 'url': full_url})
            return documents
        except:
            return []

    def download_file(self, url, save_path):
        try:
            response = cffi_requests.get(url, headers=self.headers, impersonate=self.impersonate_ver, timeout=60, allow_redirects=True)
            if response.status_code == 200:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                if save_path.stat().st_size < 100:
                    save_path.unlink()
                    return False
                return True
        except:
            pass
        return False

    def process_company(self, symbol, start_year=2015, end_year=2025):
        result = {'symbol': symbol, 'status': 'failed', 'downloaded': 0, 'skipped': 0}
        html = self.get_company_page(symbol)
        if not html:
            return result
        
        documents = self.extract_concall_documents(html, symbol)
        if not documents:
            result['status'] = 'no_documents'
            return result
        
        filtered_docs = []
        for doc in documents:
            if doc['year'] and doc['year'] != 'Unknown':
                try:
                    year_int = int(doc['year'])
                    if start_year <= year_int <= end_year:
                        filtered_docs.append(doc)
                except:
                    pass
        
        for doc in filtered_docs:
            doc_folder = self.output_folder / symbol / doc['year'] / 'Transcript'
            doc_folder.mkdir(parents=True, exist_ok=True)
            quarter_clean = re.sub(r'[^\w\s-]', '', doc['quarter']).replace(' ', '_')
            file_path = doc_folder / f"{symbol}_{quarter_clean}_Transcript.pdf"
            
            if file_path.exists():
                result['skipped'] += 1
            elif self.download_file(doc['url'], file_path):
                result['downloaded'] += 1
            time.sleep(0.5)
        
        result['status'] = 'success'
        return result

# ==============================================================================
# BACKEND: SENTIMENT ANALYZER
# ==============================================================================
class SentimentAnalyzer:
    def __init__(self, pdf_folder, output_file):
        self.pdf_folder = Path(pdf_folder)
        self.output_file = Path(output_file)
        self.existing_df = pd.DataFrame()
        self.processed_keys = set()
        self._load_existing_data()

    def _load_existing_data(self):
        if self.output_file.exists():
            try:
                df = pd.read_excel(self.output_file, sheet_name='Quarterly Sentiment')
                self.existing_df = df
                for _, row in df.iterrows():
                    self.processed_keys.add((str(row['Company']), str(row['Year']), str(row['Month'])))
            except:
                pass

    def extract_date_details(self, filename):
        pattern = r'([A-Z0-9&\-]+)_([A-Za-z]{3})_(\d{4})_Transcript'
        match = re.search(pattern, filename)
        if match:
            return match.group(2), match.group(3)
        return None, None

    def extract_text_from_pdf(self, pdf_path):
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages[:15]:
                    text += page.extract_text() or ""
            return text
        except:
            return ""

    def clean_text(self, text):
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\']', '', text)
        return text.strip()

    def get_polarity(self, text):
        if not text or len(text.split()) < 20:
            return 0.0
        return round(TextBlob(text).sentiment.polarity, 3)

    def get_keyword_sentiment(self, text):
        positive = ['strong', 'growth', 'improve', 'excellent', 'success', 'expand', 'opportunity', 'robust', 'resilient', 'positive', 'outperform', 'beat', 'exceed', 'momentum', 'strength']
        negative = ['weak', 'decline', 'challenge', 'pressure', 'concern', 'risk', 'uncertain', 'difficult', 'headwind', 'negative', 'underperform', 'miss', 'delay', 'slow', 'struggle']
        text_lower = text.lower()
        pos_count = sum(text_lower.count(' ' + kw + ' ') for kw in positive)
        neg_count = sum(text_lower.count(' ' + kw + ' ') for kw in negative)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return round(max(-1.0, min(1.0, (pos_count - neg_count) / total)), 3)

    def get_composite_score(self, polarity, keyword, text):
        guidance = 1.0 if re.search(r'rais.*guidance|exceed.*expectation', text.lower()) else (-1.0 if re.search(r'lower.*guidance|miss.*expectation', text.lower()) else 0.0)
        composite = (polarity * 0.40) + (keyword * 0.40) + (guidance * 0.20)
        return round(composite, 3), guidance

    def process_company(self, company_name):
        company_folder = self.pdf_folder / company_name
        if not company_folder.exists():
            return []
        
        sector = SECTOR_MAPPING.get(company_name.upper(), 'Unknown')
        results = []
        
        for year_folder in sorted([d for d in company_folder.iterdir() if d.is_dir()]):
            type_folder = year_folder / 'Transcript'
            if not type_folder.exists():
                continue
            
            for f in sorted(type_folder.glob("*.pdf")):
                month, year = self.extract_date_details(f.name)
                if not month or not year:
                    continue
                if (str(company_name), str(year), str(month)) in self.processed_keys:
                    continue
                
                raw_text = self.extract_text_from_pdf(f)
                if not raw_text or len(raw_text.split()) < 100:
                    continue
                
                text = self.clean_text(raw_text)
                polarity = self.get_polarity(text)
                keyword = self.get_keyword_sentiment(text)
                composite, guidance = self.get_composite_score(polarity, keyword, text)
                risk = round(text.lower().count('risk') / (len(text.split())/1000), 3) if len(text) > 0 else 0
                
                results.append({
                    'Company': company_name, 'Sector': sector, 'Year': year, 'Month': month,
                    'Overall_Sentiment': composite, 'Polarity': polarity, 'Keyword_Sentiment': keyword,
                    'Guidance': guidance, 'Risk': risk, 'File_Count': 1
                })
        return results

    def combine_and_save(self, all_results):
        if not all_results:
            return
        
        df = pd.DataFrame(all_results)
        grouped = df.groupby(['Company', 'Sector', 'Year', 'Month']).agg({
            'Overall_Sentiment': 'mean', 'Polarity': 'mean', 'Keyword_Sentiment': 'mean',
            'Guidance': 'mean', 'Risk': 'mean', 'File_Count': 'sum'
        }).reset_index()
        
        grouped['Sentiment_Category'] = grouped['Overall_Sentiment'].apply(
            lambda x: 'Positive' if x > 0.2 else ('Negative' if x < -0.1 else 'Neutral'))
        
        for col in ['Overall_Sentiment', 'Polarity', 'Keyword_Sentiment', 'Guidance', 'Risk']:
            grouped[col] = grouped[col].round(3)
        
        final_cols = ['Company', 'Sector', 'Year', 'Month', 'Overall_Sentiment', 'Sentiment_Category',
                      'Polarity', 'Keyword_Sentiment', 'Guidance', 'Risk', 'File_Count']
        new_df = grouped[final_cols]
        
        if not self.existing_df.empty:
            final_df = pd.concat([self.existing_df, new_df], ignore_index=True)
        else:
            final_df = new_df
        
        month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                     'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
        final_df['Month_Num'] = final_df['Month'].map(month_map)
        final_df = final_df.sort_values(['Company', 'Year', 'Month_Num'], ascending=[True, False, False])
        final_df = final_df.drop(columns=['Month_Num'])
        
        with pd.ExcelWriter(self.output_file, engine='openpyxl') as writer:
            final_df.to_excel(writer, sheet_name='Quarterly Sentiment', index=False)

# ==============================================================================
# HELPER FUNCTIONS FOR DASHBOARD
# ==============================================================================
def load_sentiment_data():
    if not OUTPUT_FILE.exists():
        return None
    try:
        return pd.read_excel(OUTPUT_FILE, sheet_name='Quarterly Sentiment')
    except:
        return None

def get_latest_sentiment():
    df = load_sentiment_data()
    if df is None or df.empty:
        return None
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df['Sort_Date'] = df['Year'].astype(str) + df['Month_Num'].astype(str).str.zfill(2)
    return df.sort_values('Sort_Date', ascending=False).groupby('Company').first().reset_index()

def convert_to_score_100(val):
    return int(round((val + 1) * 50))

def get_top_positive(n=5):
    latest = get_latest_sentiment()
    if latest is None:
        return []
    top = latest.nlargest(n, 'Overall_Sentiment')
    return [{'symbol': row['Company'][:3].upper(), 'name': row['Company'], 'sector': row['Sector'],
             'score': convert_to_score_100(row['Overall_Sentiment'])} for _, row in top.iterrows()]

def get_top_negative(n=5):
    latest = get_latest_sentiment()
    if latest is None:
        return []
    bottom = latest.nsmallest(n, 'Overall_Sentiment')
    return [{'symbol': row['Company'][:3].upper(), 'name': row['Company'], 'sector': row['Sector'],
             'score': convert_to_score_100(row['Overall_Sentiment'])} for _, row in bottom.iterrows()]

def get_sector_leaders():
    latest = get_latest_sentiment()
    if latest is None:
        return []
    sector_avg = latest.groupby('Sector')['Overall_Sentiment'].mean().sort_values(ascending=False)
    icons = {'Banking': 'account_balance', 'Finance': 'account_balance', 'Auto': 'directions_car',
             'IT': 'computer', 'Pharma': 'medication', 'Energy': 'bolt', 'Infrastructure': 'factory',
             'FMCG': 'shopping_cart', 'Consumer': 'shopping_cart', 'Unknown': 'analytics'}
    colors = ['indigo', 'orange', 'cyan', 'emerald', 'purple']
    results = []
    for i, (sector, score) in enumerate(sector_avg.head(5).items()):
        results.append({'sector': sector, 'score': round((score + 1) * 50, 1),
                        'icon': icons.get(sector, 'analytics'), 'color': colors[i % len(colors)]})
    return results

def get_summary_stats():
    latest = get_latest_sentiment()
    if latest is None:
        return {'total': 0, 'positive': 0, 'negative': 0, 'neutral': 0}
    return {
        'total': len(latest),
        'positive': len(latest[latest['Sentiment_Category'] == 'Positive']),
        'negative': len(latest[latest['Sentiment_Category'] == 'Negative']),
        'neutral': len(latest[latest['Sentiment_Category'] == 'Neutral']),
    }

def read_stock_symbols():
    if not CSV_FILE.exists():
        return []
    df = pd.read_csv(CSV_FILE)
    stocks = []
    for _, row in df.iterrows():
        name = str(row.get('Name', '')).strip()
        nse = str(row.get('NSE Code', '')).strip()
        bse = str(row.get('BSE Code', '')).strip()
        if nse.lower() == 'nan': nse = ''
        if bse.lower() == 'nan': bse = ''
        symbol = nse if nse else bse
        if symbol:
            stocks.append({'name': name, 'symbol': symbol})
    return stocks

# ==============================================================================
# FLASK APP
# ==============================================================================
app = Flask(__name__)

HTML_TEMPLATE = '''<!DOCTYPE html>
<html class="dark" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Market Sentiment Tracker Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
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
            fontFamily: { "display": ["Manrope", "sans-serif"] },
        },
    },
}
</script>
<style>
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
.glass-card { backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); }
</style>
</head>
<body class="font-display bg-background-dark text-slate-100 h-screen flex overflow-hidden selection:bg-accent/30">
<main class="flex-1 flex flex-col h-full overflow-hidden relative bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-blue-900/20">

<header class="flex-none glass-card bg-slate-900/80 border-b border-border-dark px-6 py-4 z-20 sticky top-0">
<div class="max-w-[1600px] mx-auto w-full flex items-center justify-between gap-4">
<div class="flex items-center gap-4">
<div class="size-10 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-lg shadow-blue-500/20">
<span class="material-symbols-outlined">analytics</span>
</div>
<div>
<h1 class="text-white text-xl font-bold leading-tight">Indian Market Sentiment Tracker</h1>
<p class="text-slate-400 text-xs font-medium">Tracking {{ stats.total }} Stocks &bull; Earnings Calls Analysis</p>
</div>
</div>
<div class="flex items-center gap-3">
<div class="hidden md:flex items-center px-3 py-1.5 bg-slate-800 rounded-full border border-slate-700">
<span class="size-2 rounded-full bg-emerald-500 animate-pulse mr-2"></span>
<span class="text-xs font-semibold text-slate-300">Data Loaded</span>
</div>
<button onclick="runAnalysis()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors flex items-center gap-2">
<span class="material-symbols-outlined text-sm">play_arrow</span> Run Analysis
</button>
<button onclick="location.reload()" class="p-2 text-slate-500 hover:text-white transition-colors">
<span class="material-symbols-outlined">refresh</span>
</button>
</div>
</div>
</header>

<div class="flex-1 overflow-y-auto">
<div class="max-w-[1600px] mx-auto w-full p-6 flex flex-col gap-6">

<!-- Analysis Status -->
<div id="analysisStatus" class="hidden glass-card bg-blue-900/30 p-4 rounded-xl border border-blue-700">
<div class="flex items-center gap-3">
<div class="animate-spin size-5 border-2 border-blue-400 border-t-transparent rounded-full"></div>
<span id="statusText" class="text-blue-300 font-medium">Starting analysis...</span>
</div>
<div class="mt-3 h-2 bg-slate-700 rounded-full overflow-hidden">
<div id="progressBar" class="h-full bg-blue-500 transition-all duration-300" style="width:0%"></div>
</div>
</div>

<!-- Top Cards -->
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">

<!-- Top Positive -->
<div class="glass-card bg-slate-800/60 p-0 rounded-xl border border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-emerald-500 text-sm">trending_up</span>
<h3 class="text-sm font-bold text-white uppercase tracking-wide">Top Positive</h3>
</div>
<span class="text-xs text-slate-400">Latest</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for stock in top_positive %}
<div class="flex items-center justify-between p-2 hover:bg-slate-700 rounded-lg transition-colors cursor-pointer">
<div class="flex items-center gap-3">
<div class="size-8 rounded bg-slate-700 flex items-center justify-center font-bold text-xs text-slate-300">{{ stock.symbol }}</div>
<div>
<p class="text-sm font-bold text-slate-200">{{ stock.name }}</p>
<p class="text-[10px] text-slate-400">{{ stock.sector }}</p>
</div>
</div>
<div class="text-right">
<span class="text-emerald-400 font-bold text-sm">{{ stock.score }}/100</span>
<div class="w-16 h-1 bg-slate-600 rounded-full mt-1 overflow-hidden">
<div class="h-full bg-emerald-500" style="width:{{ stock.score }}%"></div>
</div>
</div>
</div>
{% endfor %}
{% if not top_positive %}<p class="p-4 text-slate-500 text-sm">No data yet. Run analysis first.</p>{% endif %}
</div>
</div>

<!-- Top Negative -->
<div class="glass-card bg-slate-800/60 p-0 rounded-xl border border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-red-500 text-sm">trending_down</span>
<h3 class="text-sm font-bold text-white uppercase tracking-wide">Top Negative</h3>
</div>
<span class="text-xs text-slate-400">Latest</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for stock in top_negative %}
<div class="flex items-center justify-between p-2 hover:bg-slate-700 rounded-lg transition-colors cursor-pointer">
<div class="flex items-center gap-3">
<div class="size-8 rounded bg-slate-700 flex items-center justify-center font-bold text-xs text-slate-300">{{ stock.symbol }}</div>
<div>
<p class="text-sm font-bold text-slate-200">{{ stock.name }}</p>
<p class="text-[10px] text-slate-400">{{ stock.sector }}</p>
</div>
</div>
<div class="text-right">
<span class="text-red-400 font-bold text-sm">{{ stock.score }}/100</span>
<div class="w-16 h-1 bg-slate-600 rounded-full mt-1 overflow-hidden">
<div class="h-full bg-red-500" style="width:{{ stock.score }}%"></div>
</div>
</div>
</div>
{% endfor %}
{% if not top_negative %}<p class="p-4 text-slate-500 text-sm">No data yet.</p>{% endif %}
</div>
</div>

<!-- Sector Leaders -->
<div class="glass-card bg-slate-800/60 p-0 rounded-xl border border-border-dark shadow-sm flex flex-col">
<div class="p-4 border-b border-slate-700 flex justify-between items-center">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-blue-400 text-sm">leaderboard</span>
<h3 class="text-sm font-bold text-white uppercase tracking-wide">Sector Leaders</h3>
</div>
<span class="text-xs text-slate-400">Aggregated</span>
</div>
<div class="p-2 flex flex-col gap-1">
{% for sector in sector_leaders %}
<div class="flex items-center justify-between p-2 hover:bg-slate-700 rounded-lg transition-colors cursor-pointer">
<div class="flex items-center gap-3">
<div class="size-8 rounded-full bg-{{ sector.color }}-900/40 text-{{ sector.color }}-300 flex items-center justify-center">
<span class="material-symbols-outlined text-[18px]">{{ sector.icon }}</span>
</div>
<div>
<p class="text-sm font-bold text-slate-200">{{ sector.sector }}</p>
<p class="text-[10px] text-slate-400">Avg. Score</p>
</div>
</div>
<span class="text-{{ sector.color }}-400 font-bold text-sm">{{ sector.score }}</span>
</div>
{% endfor %}
{% if not sector_leaders %}<p class="p-4 text-slate-500 text-sm">No data yet.</p>{% endif %}
</div>
</div>
</div>

<!-- Summary Stats -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
<div class="glass-card bg-slate-800/60 p-4 rounded-xl border border-border-dark">
<p class="text-xs uppercase font-bold text-slate-400 mb-1">Total Stocks</p>
<p class="text-2xl font-bold text-white">{{ stats.total }}</p>
</div>
<div class="glass-card bg-emerald-900/20 p-4 rounded-xl border border-emerald-800">
<p class="text-xs uppercase font-bold text-emerald-500 mb-1">Positive</p>
<p class="text-2xl font-bold text-emerald-400">{{ stats.positive }}</p>
</div>
<div class="glass-card bg-amber-900/20 p-4 rounded-xl border border-amber-800">
<p class="text-xs uppercase font-bold text-amber-500 mb-1">Neutral</p>
<p class="text-2xl font-bold text-amber-400">{{ stats.neutral }}</p>
</div>
<div class="glass-card bg-red-900/20 p-4 rounded-xl border border-red-800">
<p class="text-xs uppercase font-bold text-red-500 mb-1">Negative</p>
<p class="text-2xl font-bold text-red-400">{{ stats.negative }}</p>
</div>
</div>

<!-- Data Table -->
<div class="glass-card bg-slate-800 rounded-xl border border-border-dark shadow-sm p-5">
<div class="flex justify-between items-center mb-4">
<h3 class="text-lg font-bold text-white">All Analyzed Stocks</h3>
<span class="text-xs text-slate-400">Sorted by Latest Sentiment</span>
</div>
<div class="overflow-x-auto">
<table class="w-full text-sm">
<thead>
<tr class="border-b border-slate-700">
<th class="text-left py-3 px-2 font-bold text-slate-300">Company</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Sector</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Period</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Sentiment</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Category</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Polarity</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Keyword</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Guidance</th>
<th class="text-left py-3 px-2 font-bold text-slate-300">Risk</th>
</tr>
</thead>
<tbody>
{% for stock in all_stocks %}
<tr class="border-b border-slate-700/50 hover:bg-slate-700/30">
<td class="py-3 px-2 font-bold text-white">{{ stock.Company }}</td>
<td class="py-3 px-2 text-slate-400">{{ stock.Sector }}</td>
<td class="py-3 px-2 text-slate-400">{{ stock.Month }} {{ stock.Year }}</td>
<td class="py-3 px-2"><span class="font-bold {% if stock.Overall_Sentiment > 0.2 %}text-emerald-400{% elif stock.Overall_Sentiment < -0.1 %}text-red-400{% else %}text-amber-400{% endif %}">{{ "%.3f"|format(stock.Overall_Sentiment) }}</span></td>
<td class="py-3 px-2"><span class="px-2 py-1 rounded text-xs font-bold {% if stock.Sentiment_Category == 'Positive' %}bg-emerald-900/30 text-emerald-400{% elif stock.Sentiment_Category == 'Negative' %}bg-red-900/30 text-red-400{% else %}bg-amber-900/30 text-amber-400{% endif %}">{{ stock.Sentiment_Category }}</span></td>
<td class="py-3 px-2 text-slate-400">{{ "%.3f"|format(stock.Polarity) }}</td>
<td class="py-3 px-2 text-slate-400">{{ "%.3f"|format(stock.Keyword_Sentiment) }}</td>
<td class="py-3 px-2 text-slate-400">{{ "%.1f"|format(stock.Guidance) }}</td>
<td class="py-3 px-2 text-slate-400">{{ "%.3f"|format(stock.Risk) }}</td>
</tr>
{% endfor %}
{% if not all_stocks %}<tr><td colspan="9" class="py-8 text-center text-slate-500">No data available. Click "Run Analysis" to start.</td></tr>{% endif %}
</tbody>
</table>
</div>
</div>

</div>
</div>
</main>

<script>
function runAnalysis() {
    const max = prompt("How many stocks to analyze? (Enter number or leave empty for 10)", "10");
    if (max === null) return;
    
    const num = parseInt(max) || 10;
    document.getElementById('analysisStatus').classList.remove('hidden');
    document.getElementById('statusText').textContent = 'Starting analysis...';
    document.getElementById('progressBar').style.width = '0%';
    
    const eventSource = new EventSource('/api/analyze?max=' + num);
    eventSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        document.getElementById('statusText').textContent = data.message;
        const progress = (data.progress / data.total * 100).toFixed(0);
        document.getElementById('progressBar').style.width = progress + '%';
        
        if (data.done) {
            eventSource.close();
            setTimeout(() => location.reload(), 1000);
        }
    };
    eventSource.onerror = function() {
        eventSource.close();
        document.getElementById('statusText').textContent = 'Analysis complete!';
        setTimeout(() => location.reload(), 1000);
    };
}
</script>
</body>
</html>'''

@app.route('/')
def dashboard():
    df = load_sentiment_data()
    all_stocks = df.to_dict('records') if df is not None and not df.empty else []
    return render_template_string(HTML_TEMPLATE,
        top_positive=get_top_positive(5),
        top_negative=get_top_negative(5),
        sector_leaders=get_sector_leaders(),
        stats=get_summary_stats(),
        all_stocks=all_stocks
    )

@app.route('/api/analyze')
def api_analyze():
    max_stocks = int(request.args.get('max', 10))
    
    def generate():
        stocks = read_stock_symbols()[:max_stocks]
        total = len(stocks)
        downloader = ScreenerDownloader(output_folder=DOCUMENTS_ROOT)
        analyzer = SentimentAnalyzer(pdf_folder=DOCUMENTS_ROOT, output_file=OUTPUT_FILE)
        all_results = []
        
        for i, stock in enumerate(stocks, 1):
            symbol = stock['symbol']
            yield f"data: {json.dumps({'message': f'[{i}/{total}] Processing {symbol}...', 'progress': i, 'total': total, 'done': False})}\n\n"
            
            try:
                downloader.process_company(symbol, 2015, 2025)
                results = analyzer.process_company(symbol)
                if results:
                    all_results.extend(results)
            except:
                pass
            time.sleep(0.5)
        
        if all_results:
            analyzer.combine_and_save(all_results)
        
        yield f"data: {json.dumps({'message': f'Complete! Analyzed {total} stocks.', 'progress': total, 'total': total, 'done': True})}\n\n"
    
    import json
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/data')
def api_data():
    return jsonify({
        'top_positive': get_top_positive(5),
        'top_negative': get_top_negative(5),
        'sector_leaders': get_sector_leaders(),
        'stats': get_summary_stats()
    })

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(" INDIAN MARKET SENTIMENT TRACKER")
    print("=" * 60)
    print(f" Dashboard: http://localhost:5001")
    print(f" Data File: {OUTPUT_FILE}")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
