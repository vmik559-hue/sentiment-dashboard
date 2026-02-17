"""
UNIFIED SENTIMENT PIPELINE
==========================
Complete sentiment analysis system with:
- FinBERT-based analysis (or TextBlob fallback)
- Cloud-based PDF processing (no file downloads)
- Nifty 500 company support
- Incremental processing (only new data)
- Dynamic company addition
- Force full re-run capability

API Endpoints:
    GET  /                          - Dashboard
    GET  /api/data                  - Get current sentiment data
    GET  /api/companies             - List all companies
    GET  /api/status                - Get processing status
    POST /api/analyze/incremental   - Run on new data only
    POST /api/analyze/full          - Force complete re-run
    POST /api/company/add           - Add custom company
    POST /api/company/{code}/analyze - Analyze single company
    GET  /api/export                - Export to Excel
"""

import os
import io
import re
import json
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, quote

from flask import Flask, render_template, render_template_string, jsonify, request, Response, send_file
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup

# HTTP client
try:
    from curl_cffi import requests as cffi_requests
    USE_CFFI = True
except ImportError:
    import requests as cffi_requests
    USE_CFFI = False

# Local modules
from finbert_analyzer import FinBERTAnalyzer
from company_manager import CompanyManager, get_company_manager
from state_tracker import StateTracker, get_state_tracker

# ==================== CONFIGURATION ====================
BASE_PATH = Path(__file__).parent
OUTPUT_FILE = BASE_PATH / "Sentiment_Analysis_Production.xlsx"

# Detect serverless environment (Vercel)
IS_SERVERLESS = os.environ.get('VERCEL', '') == '1'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Global processing state
processing_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'current_company': '',
    'mode': 'idle',  # 'idle', 'incremental', 'full', 'single'
    'start_time': None,
    'logs': []
}


# ==============================================================================
# CLOUD TRANSCRIPT FETCHER
# ==============================================================================
class CloudTranscriptFetcher:
    """
    Fetches transcripts directly from screener.in without saving to disk.
    Returns text content for analysis.
    """
    
    def __init__(self):
        self.base_url = "https://www.screener.in"
        self.impersonate_ver = "chrome120"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
    
    def _fetch(self, url: str, timeout: int = 30) -> str:
        """Fetch HTML content from URL."""
        try:
            if USE_CFFI:
                response = cffi_requests.get(
                    url, 
                    headers=self.headers,
                    impersonate=self.impersonate_ver,
                    timeout=timeout
                )
            else:
                response = cffi_requests.get(url, headers=self.headers, timeout=timeout)
            
            return response.text if response.status_code == 200 else ""
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return ""
    
    def get_company_page(self, symbol: str) -> str:
        """Get company page HTML."""
        url = f"{self.base_url}/company/{quote(symbol)}/consolidated/"
        return self._fetch(url)
    
    def _extract_date_from_context(self, link_element) -> dict:
        """Extract date from surrounding context."""
        previous = link_element.find_previous()
        attempts = 0
        
        while previous and attempts < 10:
            text = previous.get_text(strip=True) if hasattr(previous, 'get_text') else str(previous)
            match = re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$', text)
            if match:
                return {'month': match.group(1), 'year': match.group(2)}
            previous = previous.find_previous()
            attempts += 1
        return None
    
    def _extract_date_from_url(self, url: str) -> dict:
        """Extract date from URL pattern."""
        match = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', url)
        if match:
            year = match.group(1)
            month_num = int(match.group(2))
            months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            month = months[month_num - 1] if 1 <= month_num <= 12 else 'Unknown'
            return {'month': month, 'year': year}
        return None
    
    def get_transcript_urls(self, symbol: str, start_year: int = 2015, end_year: int = 2026) -> list:
        """
        Get list of transcript URLs for a company.
        
        Returns:
            List of dicts with 'url', 'month', 'year' keys
        """
        html = self.get_company_page(symbol)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        transcripts = []
        
        try:
            # Method 1: Find section by ID (some pages use id="concalls")
            concalls_section = soup.find(id='concalls')
            
            # Method 2: Find heading with 'concalls' text (case-insensitive)
            if not concalls_section:
                for heading in soup.find_all(['h2', 'h3', 'h4', 'div', 'section']):
                    heading_text = heading.get_text(strip=True).lower()
                    if 'concalls' in heading_text or 'con calls' in heading_text:
                        concalls_section = heading
                        break
            
            # Method 3: Search within Documents section
            if not concalls_section:
                for heading in soup.find_all(['h2', 'h3']):
                    if 'documents' in heading.get_text(strip=True).lower():
                        # Look for Concalls within this section
                        sibling = heading.find_next()
                        while sibling:
                            sibling_text = sibling.get_text(strip=True).lower() if hasattr(sibling, 'get_text') else ''
                            if 'concalls' in sibling_text:
                                concalls_section = sibling
                                break
                            # Stop if we hit another major section
                            if sibling.name in ['h2'] and sibling != heading:
                                break
                            sibling = sibling.find_next()
                        break
            
            if not concalls_section:
                return []
            
            # Collect all links from the concalls section
            all_links = []
            current = concalls_section.find_next() if concalls_section.name in ['h2', 'h3', 'h4'] else concalls_section
            stop_keywords = ['announcements', 'annual reports', 'shareholding', 'quarters', 'credit ratings']
            
            while current and len(all_links) < 300:
                if current.name in ['h2', 'h3', 'h4']:
                    text = current.get_text(strip=True).lower()
                    if any(k in text for k in stop_keywords):
                        break
                
                if current.name == 'a':
                    all_links.append(current)
                elif hasattr(current, 'find_all'):
                    all_links.extend(current.find_all('a', href=True))
                
                current = current.find_next()
            
            # Filter transcript links
            seen_urls = set()
            for link in all_links:
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                
                if not href or href.startswith('#') or 'javascript:' in href:
                    continue
                if 'transcript' not in text:
                    continue
                
                # Get date
                date_info = self._extract_date_from_context(link) or self._extract_date_from_url(href)
                if not date_info:
                    continue
                
                # Filter by year
                try:
                    year = int(date_info['year'])
                    if not (start_year <= year <= end_year):
                        continue
                except:
                    continue
                
                full_url = urljoin(self.base_url, href)
                
                # Only use BSE India links (reliable), skip external company websites
                # BSE India hosts official filings that don't disappear
                if 'bseindia.com' not in full_url:
                    continue
                
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    transcripts.append({
                        'url': full_url,
                        'month': date_info['month'],
                        'year': date_info['year'],
                        'quarter': f"{date_info['month']}_{date_info['year']}"
                    })
            
            return transcripts
            
        except Exception as e:
            logger.error(f"Error extracting transcripts for {symbol}: {e}")
            return []


# ==============================================================================
# LOCAL TRANSCRIPT PROCESSOR
# ==============================================================================
class LocalTranscriptProcessor:
    """
    Processes transcript PDFs from local file system.
    Folder structure: {pdf_folder}/{Company}/{Year}/Transcript/*.pdf
    """
    
    def __init__(self, pdf_folder: Path = None):
        # Default to Screener_Documents folder relative to parent directory
        if pdf_folder is None:
            self.pdf_folder = BASE_PATH.parent / "Screener_Documents"
        else:
            self.pdf_folder = Path(pdf_folder)
    
    def _extract_date_from_filename(self, filename: str) -> dict:
        """Extract month and year from filename patterns."""
        import re
        
        # Common patterns in transcript filenames
        # Pattern: "Company_Q1_FY24_transcript.pdf" or similar
        # Pattern: "2024-01-15_transcript.pdf"
        # Pattern: "Jan_2024_concall.pdf"
        
        months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                  'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
        month_map = {m: m.capitalize()[:3] for m in months}
        full_months = ['january', 'february', 'march', 'april', 'may', 'june',
                       'july', 'august', 'september', 'october', 'november', 'december']
        full_month_map = {m: months[i][:3].capitalize() for i, m in enumerate(full_months)}
        
        fn = filename.lower()
        
        # Try to find month name
        found_month = None
        for full_m in full_months:
            if full_m in fn:
                found_month = full_month_map[full_m]
                break
        if not found_month:
            for m in months:
                if m in fn:
                    found_month = month_map[m]
                    break
        
        # Try to find year (4 digit number 2015-2026)
        year_match = re.search(r'20(1[5-9]|2[0-6])', fn)
        found_year = year_match.group(0) if year_match else None
        
        # If no month found, try date pattern YYYY-MM-DD or DD-MM-YYYY
        if not found_month and found_year:
            date_match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', fn)
            if date_match:
                month_num = int(date_match.group(2))
                if 1 <= month_num <= 12:
                    found_month = months[month_num - 1].capitalize()[:3]
        
        # Quarter-based patterns
        if not found_month:
            q_match = re.search(r'q([1-4])', fn)
            fy_match = re.search(r'fy[- ]?(\d{2,4})', fn)
            if q_match:
                quarter = int(q_match.group(1))
                # FY Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar
                quarter_months = {1: 'Jun', 2: 'Sep', 3: 'Dec', 4: 'Mar'}
                found_month = quarter_months.get(quarter, 'Unknown')
        
        return {
            'month': found_month or 'Unknown',
            'year': found_year or 'Unknown'
        }
    
    def get_local_transcripts(self, company: str, start_year: int = 2015, end_year: int = 2026) -> list:
        """
        Get list of local transcript files for a company.
        
        Returns:
            List of dicts with 'path', 'month', 'year' keys
        """
        company_folder = self.pdf_folder / company
        if not company_folder.exists():
            return []
        
        transcripts = []
        
        for year_folder in sorted(company_folder.iterdir()):
            if not year_folder.is_dir():
                continue
            
            try:
                year = int(year_folder.name)
                if year < start_year or year > end_year:
                    continue
            except ValueError:
                continue
            
            transcript_folder = year_folder / 'Transcript'
            if not transcript_folder.exists():
                continue
            
            for pdf_file in sorted(transcript_folder.glob('*.pdf')):
                date_info = self._extract_date_from_filename(pdf_file.name)
                
                # Override year from folder if not found in filename
                if date_info['year'] == 'Unknown':
                    date_info['year'] = str(year)
                
                transcripts.append({
                    'path': pdf_file,
                    'month': date_info['month'],
                    'year': date_info['year'],
                    'quarter': f"{date_info['month']} {date_info['year']}"
                })
        
        return transcripts
    
    def get_all_companies(self) -> list:
        """Get list of all company folders in the PDF directory."""
        if not self.pdf_folder.exists():
            return []
        
        return [d.name for d in self.pdf_folder.iterdir() if d.is_dir()]
    
    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from a local PDF file."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
        except ImportError:
            # Fallback to pdfplumber
            try:
                import pdfplumber
                text = ""
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        text += page.extract_text() or ""
                return text.strip()
            except ImportError:
                logger.error("Neither PyMuPDF nor pdfplumber installed. Run: pip install pymupdf pdfplumber")
                return ""
        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path}: {e}")
            return ""


# ==============================================================================
# ANALYSIS ENGINE
# ==============================================================================
class AnalysisEngine:
    """
    Orchestrates the full analysis pipeline.
    """
    
    def __init__(self):
        self.fetcher = CloudTranscriptFetcher()
        self.analyzer = FinBERTAnalyzer()
        self.company_mgr = get_company_manager()
        self.state_tracker = get_state_tracker()
        self.output_file = OUTPUT_FILE
    
    def _load_existing_data(self) -> pd.DataFrame:
        """Load existing analysis data."""
        if self.output_file.exists():
            try:
                return pd.read_excel(self.output_file, sheet_name='Quarterly Sentiment')
            except:
                pass
        return pd.DataFrame()
    
    def analyze_company(self, nse_code: str, force: bool = False) -> list:
        """
        Analyze a single company.
        
        Args:
            nse_code: NSE trading symbol
            force: If True, re-analyze even if already processed
            
        Returns:
            List of result dicts for each quarter
        """
        results = []
        company_info = self.company_mgr.get_company(nse_code)
        sector = company_info['industry'] if company_info else 'Unknown'
        
        # Get transcript URLs
        transcripts = self.fetcher.get_transcript_urls(nse_code)
        
        if not transcripts:
            logger.info(f"No transcripts found for {nse_code}")
            return []
        
        for transcript in transcripts:
            quarter = transcript['quarter']
            
            # Skip if already processed (unless force)
            if not force and self.state_tracker.is_processed(nse_code, quarter):
                logger.debug(f"Skipping {nse_code} {quarter} (already processed)")
                continue
            
            # Fetch and analyze
            text = self.analyzer.extract_pdf_from_url(transcript['url'])
            if not text or len(text.split()) < 100:
                continue
            
            analysis = self.analyzer.analyze_transcript(text)
            
            result = {
                'Company': nse_code,
                'Sector': sector,
                'Year': transcript['year'],
                'Month': transcript['month'],
                'Overall_Sentiment': analysis['overall_sentiment'],
                'Polarity': analysis['finbert_score'],
                'Keyword_Sentiment': analysis['keyword_sentiment'],
                'Guidance': analysis['guidance'],
                'Risk': analysis['risk'],
                'FinBERT_Positive': analysis['finbert_positive'],
                'FinBERT_Negative': analysis['finbert_negative'],
                'FinBERT_Neutral': analysis['finbert_neutral'],
                'File_Count': 1,
                'Analyzed_At': datetime.now().isoformat()
            }
            
            results.append(result)
            
            # Mark as processed
            self.state_tracker.mark_processed(nse_code, quarter, {
                'sentiment': analysis['overall_sentiment']
            })
            
            # Small delay to be nice to screener.in
            time.sleep(0.3)
        
        return results
    
    def save_results(self, new_results: list, mode: str = 'append'):
        """
        Save analysis results to Excel.
        
        Args:
            new_results: List of result dicts
            mode: 'append' or 'replace'
        """
        if not new_results:
            return
        
        new_df = pd.DataFrame(new_results)
        
        if mode == 'append':
            existing_df = self._load_existing_data()
            if not existing_df.empty:
                # Remove duplicates (keep new)
                existing_df = existing_df[~existing_df.apply(
                    lambda row: (row['Company'], row['Year'], row['Month']) in 
                    [(r['Company'], r['Year'], r['Month']) for r in new_results],
                    axis=1
                )]
                final_df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                final_df = new_df
        else:
            final_df = new_df
        
        # Add sentiment category
        final_df['Sentiment_Category'] = final_df['Overall_Sentiment'].apply(
            lambda x: 'Positive' if x > 0.2 else ('Negative' if x < -0.1 else 'Neutral')
        )
        
        # Sort by company and date
        month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                     'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
        final_df['Month_Num'] = final_df['Month'].map(month_map)
        final_df = final_df.sort_values(
            ['Company', 'Year', 'Month_Num'], 
            ascending=[True, False, False]
        )
        final_df = final_df.drop(columns=['Month_Num'])
        
        # Save
        with pd.ExcelWriter(self.output_file, engine='openpyxl') as writer:
            final_df.to_excel(writer, sheet_name='Quarterly Sentiment', index=False)
        
        logger.info(f"Saved {len(new_results)} new results to {self.output_file}")
    
    def run_incremental(self, max_companies: int = None, callback=None) -> dict:
        """
        Run incremental analysis (only new data).
        
        Args:
            max_companies: Maximum number of companies to process
            callback: Function to call with progress updates
            
        Returns:
            Summary dict
        """
        global processing_status
        
        processing_status['running'] = True
        processing_status['mode'] = 'incremental'
        processing_status['start_time'] = datetime.now().isoformat()
        processing_status['logs'] = []
        
        try:
            companies = self.company_mgr.get_nse_codes()
            if max_companies:
                companies = companies[:max_companies]
            
            processing_status['total'] = len(companies)
            all_results = []
            
            for i, nse_code in enumerate(companies, 1):
                processing_status['progress'] = i
                processing_status['current_company'] = nse_code
                
                if callback:
                    callback({
                        'progress': i,
                        'total': len(companies),
                        'current': nse_code,
                        'done': False
                    })
                
                try:
                    results = self.analyze_company(nse_code, force=False)
                    if results:
                        all_results.extend(results)
                        processing_status['logs'].append(
                            f"[{i}/{len(companies)}] {nse_code}: {len(results)} quarters analyzed"
                        )
                        
                        # Batch save every 10 companies
                        if i % 10 == 0:
                            self.save_results(all_results, mode='append')
                            # Clear saved results from memory to avoid duplicates if we save again later
                            # But wait, save_results logic handles deduplication.
                            # Better approach: keep accumulating but save the snapshot.
                            logger.info(f"Batch save at {i} companies")
                            
                except Exception as e:
                    processing_status['logs'].append(f"[{i}/{len(companies)}] {nse_code}: Error - {e}")
                
                time.sleep(1.0)  # Increased delay to be polite
            
            # Save final results
            if all_results:
                self.save_results(all_results, mode='append')
            
            # Record run
            self.state_tracker.record_run('incremental', {
                'companies_processed': len(companies),
                'new_quarters': len(all_results)
            })
            
            return {
                'success': True,
                'companies_processed': len(companies),
                'new_quarters': len(all_results)
            }
            
        finally:
            processing_status['running'] = False
            processing_status['mode'] = 'idle'
    
    def run_full(self, max_companies: int = None, callback=None) -> dict:
        """
        Run full analysis (re-process everything).
        """
        # Clear state
        self.state_tracker.clear_all()
        
        processing_status['mode'] = 'full'
        return self.run_incremental(max_companies, callback)
    
    def analyze_local_company(self, company_name: str, local_processor: 'LocalTranscriptProcessor', force: bool = False) -> list:
        """
        Analyze transcripts from local files for a single company.
        
        Args:
            company_name: Company folder name (e.g., "20MICRONS", "TCS")
            local_processor: LocalTranscriptProcessor instance
            force: If True, re-analyze even if already processed
            
        Returns:
            List of result dicts for each quarter
        """
        results = []
        
        # Get company info from manager
        company_info = self.company_mgr.get_company(company_name)
        sector = company_info['industry'] if company_info else 'Unknown'
        
        # Get local transcripts
        transcripts = local_processor.get_local_transcripts(company_name)
        
        if not transcripts:
            logger.debug(f"No local transcripts found for {company_name}")
            return []
        
        for transcript in transcripts:
            quarter = transcript['quarter']
            
            # Skip if already processed (unless force)
            if not force and self.state_tracker.is_processed(company_name, quarter):
                logger.debug(f"Skipping {company_name} {quarter} (already processed)")
                continue
            
            # Extract text from local PDF
            text = local_processor.extract_text_from_pdf(transcript['path'])
            if not text or len(text.split()) < 100:
                logger.debug(f"Insufficient text in {transcript['path']}")
                continue
            
            # Analyze
            analysis = self.analyzer.analyze_transcript(text)
            
            result = {
                'Company': company_name,
                'Sector': sector,
                'Year': transcript['year'],
                'Month': transcript['month'],
                'Overall_Sentiment': analysis['overall_sentiment'],
                'Polarity': analysis['finbert_score'],
                'Keyword_Sentiment': analysis['keyword_sentiment'],
                'Guidance': analysis['guidance'],
                'Risk': analysis['risk'],
                'FinBERT_Positive': analysis.get('finbert_positive', 0),
                'FinBERT_Negative': analysis.get('finbert_negative', 0),
                'FinBERT_Neutral': analysis.get('finbert_neutral', 0),
                'File_Count': 1,
                'Source': 'local',
                'Analyzed_At': datetime.now().isoformat()
            }
            
            results.append(result)
            
            # Mark as processed
            self.state_tracker.mark_processed(company_name, quarter, {
                'sentiment': analysis['overall_sentiment'],
                'source': 'local'
            })
        
        return results
    
    def run_local_analysis(self, pdf_folder: Path = None, max_companies: int = None, 
                           force: bool = False, callback=None) -> dict:
        """
        Analyze all local PDF transcripts in the specified folder.
        
        Args:
            pdf_folder: Path to folder containing company folders (default: Screener_Documents)
            max_companies: Maximum number of companies to process
            force: If True, re-analyze even if already processed
            callback: Function to call with progress updates
            
        Returns:
            Summary dict
        """
        global processing_status
        
        processing_status['running'] = True
        processing_status['mode'] = 'local'
        processing_status['start_time'] = datetime.now().isoformat()
        processing_status['logs'] = []
        
        try:
            local_processor = LocalTranscriptProcessor(pdf_folder)
            companies = local_processor.get_all_companies()
            
            if not companies:
                logger.warning(f"No company folders found in {local_processor.pdf_folder}")
                return {'success': False, 'error': 'No company folders found'}
            
            if max_companies:
                companies = companies[:max_companies]
            
            processing_status['total'] = len(companies)
            all_results = []
            
            for i, company in enumerate(companies, 1):
                processing_status['progress'] = i
                processing_status['current_company'] = company
                
                if callback:
                    callback({
                        'progress': i,
                        'total': len(companies),
                        'current': company,
                        'done': False
                    })
                
                try:
                    results = self.analyze_local_company(company, local_processor, force=force)
                    if results:
                        all_results.extend(results)
                        processing_status['logs'].append(
                            f"[{i}/{len(companies)}] {company}: {len(results)} quarters analyzed"
                        )
                except Exception as e:
                    processing_status['logs'].append(f"[{i}/{len(companies)}] {company}: Error - {e}")
                    logger.error(f"Error analyzing {company}: {e}")
            
            # Save results
            if all_results:
                self.save_results(all_results, mode='append')
            
            # Record run
            self.state_tracker.record_run('local', {
                'companies_processed': len(companies),
                'new_quarters': len(all_results),
                'pdf_folder': str(local_processor.pdf_folder)
            })
            
            if callback:
                callback({'done': True, 'new_quarters': len(all_results)})
            
            return {
                'success': True,
                'companies_processed': len(companies),
                'new_quarters': len(all_results),
                'pdf_folder': str(local_processor.pdf_folder)
            }
            
        finally:
            processing_status['running'] = False
            processing_status['mode'] = 'idle'


# ==============================================================================
# FLASK APPLICATION
# ==============================================================================
app = Flask(__name__, template_folder='templates')

# Initialize engine (lazy)
_engine = None
def get_engine() -> AnalysisEngine:
    global _engine
    if _engine is None:
        _engine = AnalysisEngine()
    return _engine


# ==================== DATA HELPERS ====================
def load_sentiment_data():
    """Load sentiment data from Excel."""
    if not OUTPUT_FILE.exists():
        return None
    try:
        return pd.read_excel(OUTPUT_FILE, sheet_name='Quarterly Sentiment')
    except:
        return None


def get_latest_sentiment():
    """Get latest sentiment per company."""
    df = load_sentiment_data()
    if df is None or df.empty:
        return None
    
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df['Sort_Date'] = df['Year'].astype(str) + df['Month_Num'].astype(str).str.zfill(2)
    return df.sort_values('Sort_Date', ascending=False).groupby('Company').first().reset_index()


def get_summary_stats():
    """Get summary statistics."""
    latest = get_latest_sentiment()
    if latest is None:
        return {'total': 0, 'positive': 0, 'negative': 0, 'neutral': 0, 'avg_score': 0}
    
    if 'Sentiment_Category' not in latest.columns:
        latest['Sentiment_Category'] = latest['Overall_Sentiment'].apply(
            lambda x: 'Positive' if x > 0.2 else ('Negative' if x < -0.1 else 'Neutral')
        )
    
    return {
        'total': len(latest),
        'positive': len(latest[latest['Sentiment_Category'] == 'Positive']),
        'negative': len(latest[latest['Sentiment_Category'] == 'Negative']),
        'neutral': len(latest[latest['Sentiment_Category'] == 'Neutral']),
        'avg_score': round(latest['Overall_Sentiment'].mean(), 3) if len(latest) > 0 else 0
    }


def get_top_stocks(n: int = 5, ascending: bool = False):
    """Get top/bottom stocks by sentiment.
    
    For ascending=False: Returns stocks with highest positive scores (> 0.2)
    For ascending=True: Returns stocks with actual negative scores (< -0.1)
    """
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    if ascending:
        # Only show actually negative stocks (score < -0.1)
        negative_stocks = latest[latest['Overall_Sentiment'] < -0.1]
        if negative_stocks.empty:
            return []  # No negative stocks to show
        stocks = negative_stocks.nsmallest(n, 'Overall_Sentiment')
    else:
        # Only show actually positive stocks (score > 0.2)
        positive_stocks = latest[latest['Overall_Sentiment'] > 0.2]
        if positive_stocks.empty:
            return []  # No positive stocks to show
        stocks = positive_stocks.nlargest(n, 'Overall_Sentiment')
    
    return [{
        'symbol': row['Company'][:4].upper(),
        'name': row['Company'],
        'sector': row.get('Sector', 'Unknown'),
        'score': round(row['Overall_Sentiment'], 3)
    } for _, row in stocks.iterrows()]


def get_sector_summary():
    """Get sector-level summary."""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    
    sector_avg = latest.groupby('Sector')['Overall_Sentiment'].agg(['mean', 'count'])
    sector_avg = sector_avg.sort_values('mean', ascending=False)
    return [{
        'sector': sector,
        'score': round(row['mean'], 3),
        'count': int(row['count'])
    } for sector, row in sector_avg.head(10).iterrows()]


def get_sentiment_changes():
    """
    Detect stocks that changed sentiment category between their last two periods.
    
    Returns:
        List of dicts with company, old_score, new_score, change, direction
        sorted by absolute change (highest first)
    """
    df = load_sentiment_data()
    if df is None or df.empty:
        return []
    
    # Add sort date
    month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                 'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
    df['Month_Num'] = df['Month'].map(month_map)
    df['Sort_Date'] = df['Year'].astype(str) + df['Month_Num'].astype(str).str.zfill(2)
    df = df.sort_values(['Company', 'Sort_Date'], ascending=[True, False])
    
    changes = []
    
    for company in df['Company'].unique():
        company_data = df[df['Company'] == company].head(2)  # Get last 2 periods
        
        if len(company_data) < 2:
            continue  # Need at least 2 periods to compare
        
        latest = company_data.iloc[0]
        previous = company_data.iloc[1]
        
        new_score = latest['Overall_Sentiment']
        old_score = previous['Overall_Sentiment']
        change = new_score - old_score
        abs_change = abs(change)
        
        # Determine categories
        def get_category(score):
            if score > 0.2:
                return 'Positive'
            elif score < -0.1:
                return 'Negative'
            return 'Neutral'
        
        new_cat = get_category(new_score)
        old_cat = get_category(old_score)
        
        # Include if:
        # 1. Category changed (any transition: Positive↔Neutral↔Negative)
        # 2. OR significant change (>0.1 absolute change)
        if old_cat != new_cat or abs_change >= 0.1:
            
            direction = 'downgrade' if new_score < old_score else 'upgrade'
            
            changes.append({
                'company': company,
                'symbol': company[:4].upper(),
                'sector': latest.get('Sector', 'Unknown'),
                'old_score': round(old_score, 3),
                'new_score': round(new_score, 3),
                'change': round(change, 3),
                'abs_change': abs_change,
                'direction': direction,
                'old_category': old_cat,
                'new_category': new_cat,
                'old_period': f"{previous['Month']} {previous['Year']}",
                'new_period': f"{latest['Month']} {latest['Year']}"
            })
    
    # Sort by absolute change (highest first)
    changes.sort(key=lambda x: x['abs_change'], reverse=True)
    return changes


# Keywords mapping for top stocks
TOP_KEYWORDS = {
    'HCLTECH': 'GenAI', 'TCS': 'Deal Wins', 'RELIANCE': 'New Energy', 'ITC': 'FMCG Growth',
    'LT': 'Order Book', 'INFY': 'Digital', 'BHARTIARTL': 'ARPU', 'ASIANPAINT': 'Volume',
    'BAJFINANCE': 'NIM Comp.', 'WIPRO': 'Attrition', 'TATASTEEL': 'Europe', 'ADANIPORTS': 'Cargo Vol',
    'HDFCBANK': 'NII Growth', 'ICICIBANK': 'Retail', 'SBIN': 'NPAs', 'AXISBANK': 'Deposits',
    'SUNPHARMA': 'US Mkt', 'CIPLA': 'Generics', 'DRREDDY': 'Pipeline', 'MARUTI': 'SUV Mix',
}


def get_sector_heatmap_data():
    """Calculate sector-wise sentiment for heatmap with size based on stock count."""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    sector_data = latest.groupby('Sector').agg({
        'Overall_Sentiment': 'mean',
        'Company': 'count'
    }).reset_index()
    sector_data.columns = ['sector', 'avg_sentiment', 'count']
    sector_data['avg_sentiment'] = sector_data['avg_sentiment'].round(2)
    
    max_count = sector_data['count'].max() if len(sector_data) > 0 else 1
    sector_data['size_ratio'] = (sector_data['count'] / max_count * 100).round(0).astype(int)
    sector_data['size_ratio'] = sector_data['size_ratio'].clip(lower=40)
    
    return sector_data.to_dict('records')


def get_sentiment_distribution():
    """Calculate sentiment distribution for histogram."""
    latest = get_latest_sentiment()
    if latest is None:
        return {'buckets': [], 'mean': 0}
    
    buckets = []
    ranges = [(-1.0, -0.8), (-0.8, -0.6), (-0.6, -0.4), (-0.4, -0.2), (-0.2, 0.0),
              (0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    
    for low, high in ranges:
        count = len(latest[(latest['Overall_Sentiment'] >= low) & (latest['Overall_Sentiment'] < high)])
        buckets.append({'range': f"{low:.1f} to {high:.1f}", 'count': count, 'low': low, 'high': high})
    
    mean_val = latest['Overall_Sentiment'].mean()
    return {'buckets': buckets, 'mean': round(mean_val, 2)}


def get_market_mood(avg_score):
    """Determine market mood based on average score."""
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
    """Get paginated stock list for the table."""
    latest = get_latest_sentiment()
    if latest is None:
        return [], 0, 0
    
    latest['TopKeyword'] = latest['Company'].map(TOP_KEYWORDS).fillna('N/A')
    latest = latest.sort_values('Overall_Sentiment', ascending=False)
    
    total = len(latest)
    total_pages = (total + per_page - 1) // per_page
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    page_data = latest.iloc[start_idx:end_idx]
    
    return page_data.to_dict('records'), total, total_pages


def get_company_time_series(companies):
    """Get time series data for multiple companies."""
    df = load_sentiment_data()
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


def get_all_company_list():
    """Get list of all companies for autocomplete."""
    latest = get_latest_sentiment()
    if latest is None:
        return []
    return sorted(latest['Company'].unique().tolist())


# ==================== ROUTES ====================
@app.route('/')
def dashboard():
    """Main dashboard."""
    stats = get_summary_stats()
    tracker = get_state_tracker()
    run_history = tracker.get_run_history()
    
    # Safely extract last run timestamp
    last_incr = run_history.get('last_incremental_run')
    last_run = last_incr.get('timestamp', 'Never') if last_incr else 'Never'
    
    # Get market mood
    mood, mood_color = get_market_mood(stats.get('avg_score', 0))
    
    return render_template('dashboard.html',
        stats=stats,
        top_positive=get_top_stocks(5, ascending=False),
        top_negative=get_top_stocks(5, ascending=True),
        sector_leaders=get_sector_summary(),
        sector_heatmap=get_sector_heatmap_data(),
        sentiment_dist=get_sentiment_distribution(),
        sentiment_changes=get_sentiment_changes(),
        all_companies=get_all_company_list(),
        processing=processing_status,
        last_run=last_run,
        mood=mood,
        mood_color=mood_color
    )


@app.route('/api/data')
def api_data():
    """Get all analysis data."""
    df = load_sentiment_data()
    if df is None:
        return jsonify({'error': 'No data available'}), 404
    
    # Replace NaN with None for JSON serialization
    df = df.where(df.notna(), None)
    
    return jsonify({
        'stats': get_summary_stats(),
        'top_positive': get_top_stocks(5),
        'top_negative': get_top_stocks(5, ascending=True),
        'sectors': get_sector_summary(),
        'data': df.to_dict('records')
    })


@app.route('/api/companies')
def api_companies():
    """List all companies."""
    mgr = get_company_manager()
    companies = mgr.get_all_companies()
    
    return jsonify({
        'total': len(companies),
        'companies': companies,
        'stats': mgr.get_statistics()
    })


@app.route('/api/status')
def api_status():
    """Get processing status."""
    tracker = get_state_tracker()
    
    return jsonify({
        'processing': processing_status,
        'run_history': tracker.get_run_history(),
        'summary': tracker.get_summary()
    })


@app.route('/api/analyze/incremental', methods=['GET', 'POST'])
def api_analyze_incremental():
    """Run incremental analysis."""
    if IS_SERVERLESS:
        return jsonify({'error': 'Analysis is not available in serverless mode. Run analysis locally and push the updated Excel file.'}), 503
    if processing_status['running']:
        return jsonify({'error': 'Analysis already running'}), 409
    
    max_companies = request.json.get('max_companies') if request.json else None
    
    def generate():
        engine = get_engine()
        
        def callback(status):
            yield f"data: {json.dumps(status)}\n\n"
        
        result = engine.run_incremental(max_companies, callback)
        yield f"data: {json.dumps({'done': True, **result})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/analyze/full', methods=['GET', 'POST'])
def api_analyze_full():
    """Run full analysis (force re-run all)."""
    if IS_SERVERLESS:
        return jsonify({'error': 'Full analysis is not available in serverless mode. Run analysis locally and push the updated Excel file.'}), 503
    if processing_status['running']:
        return jsonify({'error': 'Analysis already running'}), 409
    
    max_companies = request.json.get('max_companies') if request.json else None
    
    def generate():
        engine = get_engine()
        
        def callback(status):
            yield f"data: {json.dumps(status)}\n\n"
        
        result = engine.run_full(max_companies, callback)
        yield f"data: {json.dumps({'done': True, **result})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/analyze/local', methods=['POST', 'GET'])
def api_analyze_local():
    """Analyze all local PDF transcript files from Screener_Documents folder."""
    if IS_SERVERLESS:
        return jsonify({'error': 'Local analysis is not available in serverless mode.'}), 503
    if processing_status['running']:
        return jsonify({'error': 'Analysis already running'}), 409
    
    # Get parameters
    if request.method == 'POST' and request.json:
        max_companies = request.json.get('max_companies')
        force = request.json.get('force', False)
        pdf_folder = request.json.get('pdf_folder')
    else:
        max_companies = request.args.get('max_companies', type=int)
        force = request.args.get('force', 'false').lower() == 'true'
        pdf_folder = request.args.get('pdf_folder')
    
    def generate():
        engine = get_engine()
        
        def callback(status):
            yield f"data: {json.dumps(status)}\n\n"
        
        result = engine.run_local_analysis(
            pdf_folder=Path(pdf_folder) if pdf_folder else None,
            max_companies=max_companies,
            force=force,
            callback=callback
        )
        yield f"data: {json.dumps({'done': True, **result})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/upload', methods=['POST'])
def api_upload_pdfs():
    """Upload and analyze PDF files directly."""
    if IS_SERVERLESS:
        return jsonify({'error': 'PDF upload is not available in serverless mode. Run analysis locally.'}), 503
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': 'No files selected'}), 400
    
    results = []
    engine = get_engine()
    local_processor = LocalTranscriptProcessor()
    
    for file in files:
        if not file.filename.endswith('.pdf'):
            results.append({
                'filename': file.filename,
                'success': False,
                'error': 'Not a PDF file'
            })
            continue
        
        try:
            # Save temporarily
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                file.save(tmp.name)
                tmp_path = Path(tmp.name)
            
            # Extract text
            text = local_processor.extract_text_from_pdf(tmp_path)
            
            if not text or len(text.split()) < 50:
                results.append({
                    'filename': file.filename,
                    'success': False,
                    'error': 'Could not extract text from PDF'
                })
                tmp_path.unlink()
                continue
            
            # Analyze
            analysis = engine.analyzer.analyze_transcript(text)
            
            # Extract company name from filename if possible
            company_name = file.filename.replace('.pdf', '').replace('_', ' ').replace('-', ' ')
            
            result = {
                'filename': file.filename,
                'success': True,
                'company': company_name,
                'overall_sentiment': round(analysis['overall_sentiment'], 3),
                'category': 'Positive' if analysis['overall_sentiment'] > 0.2 else (
                    'Negative' if analysis['overall_sentiment'] < -0.1 else 'Neutral'),
                'finbert_score': round(analysis['finbert_score'], 3),
                'keyword_sentiment': round(analysis['keyword_sentiment'], 3),
                'guidance': analysis['guidance'],
                'risk': round(analysis['risk'], 3),
                'word_count': len(text.split())
            }
            
            results.append(result)
            
            # Clean up temp file
            tmp_path.unlink()
            
        except Exception as e:
            results.append({
                'filename': file.filename,
                'success': False,
                'error': str(e)
            })
    
    # Calculate summary
    successful = [r for r in results if r.get('success')]
    
    return jsonify({
        'total_files': len(files),
        'successful': len(successful),
        'failed': len(files) - len(successful),
        'avg_sentiment': round(sum(r['overall_sentiment'] for r in successful) / len(successful), 3) if successful else 0,
        'results': results
    })


@app.route('/api/company/add', methods=['POST'])
def api_add_company():
    """Add a custom company."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    mgr = get_company_manager()
    result = mgr.add_custom_company(
        name=data.get('name', ''),
        nse_code=data.get('nse_code'),
        bse_code=data.get('bse_code'),
        industry=data.get('industry', 'Unknown'),
        market_cap=data.get('market_cap', 0),
        validate=data.get('validate', True)
    )
    
    if result['success']:
        return jsonify(result), 201
    return jsonify(result), 400


@app.route('/api/company/<nse_code>/analyze', methods=['POST'])
def api_analyze_single(nse_code):
    """Analyze a single company immediately."""
    if IS_SERVERLESS:
        return jsonify({'error': 'Company analysis is not available in serverless mode.'}), 503
    if processing_status['running']:
        return jsonify({'error': 'Analysis already running'}), 409
    
    force = request.json.get('force', False) if request.json else False
    
    try:
        processing_status['running'] = True
        processing_status['mode'] = 'single'
        processing_status['current_company'] = nse_code
        
        engine = get_engine()
        results = engine.analyze_company(nse_code, force=force)
        
        if results:
            engine.save_results(results, mode='append')
        
        return jsonify({
            'success': True,
            'company': nse_code,
            'quarters_analyzed': len(results),
            'results': results
        })
        
    finally:
        processing_status['running'] = False
        processing_status['mode'] = 'idle'


@app.route('/api/export')
def api_export():
    """Export data to Excel."""
    if not OUTPUT_FILE.exists():
        return jsonify({'error': 'No data to export'}), 404
    
    return send_file(
        OUTPUT_FILE,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='Sentiment_Analysis_Export.xlsx'
    )


@app.route('/api/stocks')
def api_stocks():
    """Get paginated stocks for table."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    
    stocks, total, total_pages = get_paginated_stocks(page, per_page)
    
    return jsonify({
        'stocks': stocks,
        'total': total,
        'total_pages': total_pages,
        'current_page': page
    })


@app.route('/api/timeseries')
def api_timeseries():
    """Get time series data for selected companies."""
    companies = request.args.get('companies', '')
    if not companies:
        return jsonify({'error': 'No companies specified'}), 400
    
    company_list = [c.strip() for c in companies.split(',') if c.strip()]
    data = get_company_time_series(company_list)
    
    return jsonify(data)


@app.route('/api/sector-heatmap')
def api_sector_heatmap():
    """Get sector heatmap data."""
    return jsonify(get_sector_heatmap_data())


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'data_loaded': OUTPUT_FILE.exists(),
        'processing': processing_status['running']
    })


@app.route('/api/warmup', methods=['GET', 'POST'])
def api_warmup():
    """
    Pre-load the FinBERT model to avoid timeout on first upload.
    Call this endpoint when the dashboard loads.
    """
    try:
        engine = get_engine()
        # Check if model is already loaded
        if hasattr(engine.analyzer, '_model_loaded') and engine.analyzer._model_loaded:
            return jsonify({
                'status': 'ready',
                'message': 'FinBERT model is already loaded',
                'model_loaded': True
            })
        
        # Trigger model loading by accessing the model property
        # This will lazy-load the model if not already loaded
        if engine.analyzer.use_finbert:
            engine.analyzer._ensure_model_loaded()
            return jsonify({
                'status': 'ready',
                'message': 'FinBERT model loaded successfully',
                'model_loaded': True
            })
        else:
            return jsonify({
                'status': 'ready',
                'message': 'Using TextBlob fallback (FinBERT not available)',
                'model_loaded': False,
                'using_fallback': True
            })
    except Exception as e:
        logger.error(f"Error warming up model: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'model_loaded': False
        }), 500


@app.route('/api/model-status')
def api_model_status():
    """Check if the FinBERT model is loaded."""
    try:
        engine = get_engine()
        model_loaded = hasattr(engine.analyzer, '_model_loaded') and engine.analyzer._model_loaded
        return jsonify({
            'model_loaded': model_loaded,
            'using_finbert': engine.analyzer.use_finbert
        })
    except Exception as e:
        return jsonify({
            'model_loaded': False,
            'error': str(e)
        })



if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    
    print("\n" + "=" * 60)
    print(" UNIFIED SENTIMENT PIPELINE")
    print("=" * 60)
    print(f" Dashboard: http://localhost:{port}")
    print(f" Output File: {OUTPUT_FILE}")
    print(" Endpoints:")
    print("   POST /api/analyze/incremental  - Run on new data")
    print("   POST /api/analyze/full         - Force re-run all")
    print("   POST /api/company/add          - Add custom company")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
