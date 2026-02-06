"""
FinBERT Sentiment Analyzer
==========================
Cloud-based financial sentiment analysis using FinBERT model.
Processes transcripts directly from URLs without downloading to disk.

Features:
- In-memory PDF extraction from screener.in URLs
- FinBERT-based sentiment scoring (positive/negative/neutral)
- Chunked processing for long documents (512 token limit)
- Composite scoring with guidance and risk detection
"""

import io
import re
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, quote

import numpy as np
import pandas as pd

# HTTP client
try:
    from curl_cffi import requests as cffi_requests
    USE_CFFI = True
except ImportError:
    import requests as cffi_requests
    USE_CFFI = False

# PDF extraction
try:
    import PyPDF2
except ImportError:
    print("[!] PyPDF2 not installed. Run: pip install PyPDF2")
    raise

# FinBERT model
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False
    print("[!] Transformers/torch not installed. Falling back to TextBlob.")
    print("    For FinBERT, run: pip install transformers torch")

# Fallback to TextBlob if transformers not available
if not FINBERT_AVAILABLE:
    try:
        from textblob import TextBlob
    except ImportError:
        print("[!] TextBlob not installed. Run: pip install textblob")
        raise

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class FinBERTAnalyzer:
    """
    Financial sentiment analyzer using FinBERT model.
    Processes PDF transcripts directly from URLs (no disk writes).
    """
    
    def __init__(self, model_name: str = "ProsusAI/finbert", use_gpu: bool = False):
        """
        Initialize the FinBERT analyzer.
        
        Args:
            model_name: HuggingFace model name (default: ProsusAI/finbert)
            use_gpu: Whether to use GPU if available
        """
        self.model_name = model_name
        self.use_finbert = FINBERT_AVAILABLE
        self.device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        
        # HTTP settings
        self.base_url = "https://www.screener.in"
        self.impersonate_ver = "chrome120"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        # Load FinBERT model
        if self.use_finbert:
            logger.info(f"Loading FinBERT model: {model_name} on {self.device}")
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.to(self.device)
            self.model.eval()
            logger.info("FinBERT model loaded successfully")
        else:
            logger.warning("Using TextBlob fallback (FinBERT not available)")
        
        # Financial keywords for enhanced analysis
        self.positive_keywords = [
            'strong', 'growth', 'improve', 'excellent', 'success', 'expand', 
            'opportunity', 'robust', 'resilient', 'positive', 'outperform', 
            'beat', 'exceed', 'momentum', 'strength', 'record', 'surge',
            'optimistic', 'confident', 'upgrade', 'bullish'
        ]
        self.negative_keywords = [
            'weak', 'decline', 'challenge', 'pressure', 'concern', 'risk',
            'uncertain', 'difficult', 'headwind', 'negative', 'underperform',
            'miss', 'delay', 'slow', 'struggle', 'downturn', 'volatile',
            'cautious', 'bearish', 'downgrade'
        ]
    
    def _fetch_url(self, url: str, timeout: int = 60) -> Optional[bytes]:
        """Fetch content from URL."""
        try:
            if USE_CFFI:
                response = cffi_requests.get(
                    url, 
                    headers=self.headers, 
                    impersonate=self.impersonate_ver,
                    timeout=timeout,
                    allow_redirects=True
                )
            else:
                response = cffi_requests.get(
                    url, 
                    headers=self.headers, 
                    timeout=timeout,
                    allow_redirects=True
                )
            
            if response.status_code == 200:
                return response.content
            else:
                logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def extract_pdf_from_url(self, url: str) -> Optional[str]:
        """
        Fetch PDF from URL and extract text in-memory (no disk save).
        
        Args:
            url: URL of the PDF file
            
        Returns:
            Extracted text or None if failed
        """
        content = self._fetch_url(url)
        if not content:
            return None
        
        try:
            pdf_file = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text = ""
            # Process first 15 pages (earnings call transcripts are usually within this)
            for page in pdf_reader.pages[:15]:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            return text if text.strip() else None
            
        except Exception as e:
            logger.error(f"Error extracting PDF from {url}: {e}")
            return None
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\'\"]', '', text)
        return text.strip()
    
    def _chunk_text(self, text: str, max_tokens: int = 450) -> List[str]:
        """
        Split text into chunks that fit FinBERT's 512 token limit.
        Uses word-based splitting with overlap.
        """
        words = text.split()
        chunks = []
        
        # Approximate 1 token = 0.75 words (rough estimate)
        words_per_chunk = int(max_tokens * 0.75)
        overlap = int(words_per_chunk * 0.1)  # 10% overlap
        
        start = 0
        while start < len(words):
            end = min(start + words_per_chunk, len(words))
            chunk = ' '.join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start = end - overlap if end < len(words) else len(words)
        
        return chunks if chunks else [text[:2000]]  # Fallback
    
    def analyze_text_finbert(self, text: str) -> Dict[str, float]:
        """
        Analyze text sentiment using FinBERT.
        
        Returns:
            Dict with 'positive', 'negative', 'neutral' probabilities and 'compound_score'
        """
        if not self.use_finbert:
            # Fallback to TextBlob
            return self._analyze_text_textblob(text)
        
        chunks = self._chunk_text(text)
        all_scores = []
        
        with torch.no_grad():
            for chunk in chunks:
                inputs = self.tokenizer(
                    chunk, 
                    return_tensors="pt", 
                    truncation=True, 
                    max_length=512,
                    padding=True
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                outputs = self.model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                
                # FinBERT outputs: [positive, negative, neutral]
                scores = probs[0].cpu().numpy()
                all_scores.append(scores)
        
        # Average across chunks
        avg_scores = np.mean(all_scores, axis=0)
        
        # Convert to compound score (-1 to +1)
        # positive contribution minus negative contribution
        compound = float(avg_scores[0] - avg_scores[1])
        
        return {
            'positive': float(avg_scores[0]),
            'negative': float(avg_scores[1]),
            'neutral': float(avg_scores[2]),
            'compound_score': round(compound, 3)
        }
    
    def _analyze_text_textblob(self, text: str) -> Dict[str, float]:
        """Fallback TextBlob analysis."""
        if not text or len(text.split()) < 20:
            return {'positive': 0.33, 'negative': 0.33, 'neutral': 0.34, 'compound_score': 0.0}
        
        polarity = TextBlob(text).sentiment.polarity
        
        # Convert polarity to pseudo-probabilities
        if polarity > 0:
            positive = 0.5 + polarity * 0.5
            negative = 0.1
            neutral = 1 - positive - negative
        elif polarity < 0:
            negative = 0.5 + abs(polarity) * 0.5
            positive = 0.1
            neutral = 1 - positive - negative
        else:
            positive = 0.25
            negative = 0.25
            neutral = 0.5
        
        return {
            'positive': round(positive, 3),
            'negative': round(negative, 3),
            'neutral': round(neutral, 3),
            'compound_score': round(polarity, 3)
        }
    
    def get_keyword_sentiment(self, text: str) -> float:
        """Analyze keyword-based sentiment."""
        text_lower = text.lower()
        words = text_lower.split()
        
        pos_count = sum(1 for word in words if word in self.positive_keywords)
        neg_count = sum(1 for word in words if word in self.negative_keywords)
        
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        
        score = (pos_count - neg_count) / total
        return round(max(-1.0, min(1.0, score)), 3)
    
    def detect_guidance(self, text: str) -> float:
        """Detect guidance changes in transcript."""
        text_lower = text.lower()
        
        positive_patterns = [
            r'rais.*guidance', r'upgrad.*guidance', r'exceed.*expectation',
            r'beat.*estimate', r'above.*consensus', r'stronger.*outlook',
            r'increas.*forecast', r'revis.*upward'
        ]
        negative_patterns = [
            r'lower.*guidance', r'cut.*guidance', r'miss.*expectation',
            r'below.*estimate', r'weaker.*outlook', r'decreas.*forecast',
            r'revis.*downward', r'disappoint'
        ]
        
        pos_matches = sum(1 for p in positive_patterns if re.search(p, text_lower))
        neg_matches = sum(1 for p in negative_patterns if re.search(p, text_lower))
        
        if pos_matches > neg_matches:
            return 1.0
        elif neg_matches > pos_matches:
            return -1.0
        return 0.0
    
    def calculate_risk_score(self, text: str) -> float:
        """Calculate risk score based on risk-related keywords."""
        text_lower = text.lower()
        words = text_lower.split()
        word_count = len(words)
        
        if word_count == 0:
            return 0.0
        
        risk_terms = ['risk', 'uncertain', 'volatile', 'challenge', 'headwind', 
                      'concern', 'threat', 'exposure', 'vulnerability']
        
        risk_count = sum(text_lower.count(term) for term in risk_terms)
        
        # Normalize per 1000 words
        risk_score = (risk_count / word_count) * 1000
        
        return round(min(1.0, risk_score / 10), 3)  # Cap at 1.0
    
    def analyze_transcript(self, text: str) -> Dict[str, float]:
        """
        Full analysis of a transcript.
        
        Returns:
            Dict with all sentiment metrics
        """
        if not text or len(text.split()) < 50:
            return {
                'finbert_score': 0.0,
                'finbert_positive': 0.33,
                'finbert_negative': 0.33,
                'finbert_neutral': 0.34,
                'keyword_sentiment': 0.0,
                'guidance': 0.0,
                'risk': 0.0,
                'overall_sentiment': 0.0
            }
        
        cleaned_text = self.clean_text(text)
        
        # FinBERT analysis
        finbert_result = self.analyze_text_finbert(cleaned_text)
        
        # Keyword analysis
        keyword_score = self.get_keyword_sentiment(cleaned_text)
        
        # Guidance detection
        guidance = self.detect_guidance(cleaned_text)
        
        # Risk score
        risk = self.calculate_risk_score(cleaned_text)
        
        # Composite overall sentiment
        # Weighted: FinBERT 50%, Keywords 30%, Guidance 20%
        overall = (
            finbert_result['compound_score'] * 0.50 +
            keyword_score * 0.30 +
            guidance * 0.20
        )
        
        return {
            'finbert_score': finbert_result['compound_score'],
            'finbert_positive': finbert_result['positive'],
            'finbert_negative': finbert_result['negative'],
            'finbert_neutral': finbert_result['neutral'],
            'keyword_sentiment': keyword_score,
            'guidance': guidance,
            'risk': risk,
            'overall_sentiment': round(overall, 3)
        }
    
    def analyze_url(self, pdf_url: str) -> Optional[Dict[str, float]]:
        """
        Analyze a transcript directly from URL.
        
        Args:
            pdf_url: URL to the PDF transcript
            
        Returns:
            Analysis results or None if extraction failed
        """
        text = self.extract_pdf_from_url(pdf_url)
        if not text:
            return None
        
        return self.analyze_transcript(text)


# Convenience function for quick testing
def analyze_sample_text(text: str) -> Dict:
    """Quick analysis of sample text for testing."""
    analyzer = FinBERTAnalyzer()
    return analyzer.analyze_transcript(text)


if __name__ == "__main__":
    # Test with sample financial text
    sample = """
    We are pleased to report strong quarterly results with revenue growth of 15% year-over-year.
    Our profit margins have improved significantly, exceeding analyst expectations.
    We are raising our full-year guidance based on robust demand across all segments.
    While we remain cautious about macroeconomic headwinds, our diversified portfolio
    provides resilience against market volatility.
    """
    
    print("Testing FinBERT Analyzer...")
    print("=" * 50)
    
    analyzer = FinBERTAnalyzer()
    result = analyzer.analyze_transcript(sample)
    
    print(f"FinBERT Score: {result['finbert_score']}")
    print(f"  - Positive: {result['finbert_positive']:.2%}")
    print(f"  - Negative: {result['finbert_negative']:.2%}")
    print(f"  - Neutral: {result['finbert_neutral']:.2%}")
    print(f"Keyword Sentiment: {result['keyword_sentiment']}")
    print(f"Guidance: {result['guidance']}")
    print(f"Risk Score: {result['risk']}")
    print(f"Overall Sentiment: {result['overall_sentiment']}")
