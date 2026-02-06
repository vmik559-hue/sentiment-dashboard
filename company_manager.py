"""
Company Manager
===============
Single source of truth for Nifty 500 company data.
Handles dynamic sector mapping, company validation, and custom company addition.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote

import pandas as pd

# HTTP client for validation
try:
    from curl_cffi import requests as cffi_requests
    USE_CFFI = True
except ImportError:
    import requests as cffi_requests
    USE_CFFI = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class CompanyManager:
    """
    Manages company data from nse-500-stocks.csv.
    Single source of truth for company identification and sector mapping.
    """
    
    def __init__(self, csv_path: str = None, custom_companies_file: str = None):
        """
        Initialize the company manager.
        
        Args:
            csv_path: Path to nse-500-stocks.csv (default: same directory as this file)
            custom_companies_file: JSON file for storing custom companies
        """
        base_path = Path(__file__).parent
        
        self.csv_path = Path(csv_path) if csv_path else base_path / "nse-500-stocks.csv"
        self.custom_file = Path(custom_companies_file) if custom_companies_file else base_path / "custom_companies.json"
        
        # HTTP settings for validation
        self.base_url = "https://www.screener.in"
        self.impersonate_ver = "chrome120"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        # Load data
        self.nifty500_df = self._load_nifty500()
        self.custom_companies = self._load_custom_companies()
        
        # Build lookup indices
        self._build_indices()
    
    def _load_nifty500(self) -> pd.DataFrame:
        """Load Nifty 500 companies from CSV."""
        if not self.csv_path.exists():
            logger.warning(f"Nifty 500 CSV not found: {self.csv_path}")
            return pd.DataFrame(columns=['Name', 'BSE Code', 'NSE Code', 'Industry', 'Market Capitalization'])
        
        try:
            df = pd.read_csv(self.csv_path)
            # Clean column names
            df.columns = df.columns.str.strip()
            
            # Fill missing values
            df['NSE Code'] = df['NSE Code'].fillna('')
            df['BSE Code'] = df['BSE Code'].fillna('')
            df['Industry'] = df['Industry'].fillna('Unknown')
            df['Market Capitalization'] = df['Market Capitalization'].fillna(0)
            
            logger.info(f"Loaded {len(df)} companies from Nifty 500 CSV")
            return df
            
        except Exception as e:
            logger.error(f"Error loading Nifty 500 CSV: {e}")
            return pd.DataFrame(columns=['Name', 'BSE Code', 'NSE Code', 'Industry', 'Market Capitalization'])
    
    def _load_custom_companies(self) -> List[Dict]:
        """Load custom companies from JSON file."""
        if not self.custom_file.exists():
            return []
        
        try:
            with open(self.custom_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading custom companies: {e}")
            return []
    
    def _save_custom_companies(self):
        """Save custom companies to JSON file."""
        try:
            with open(self.custom_file, 'w') as f:
                json.dump(self.custom_companies, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving custom companies: {e}")
    
    def _build_indices(self):
        """Build lookup indices for fast access."""
        self.nse_to_info = {}
        self.bse_to_info = {}
        self.name_to_info = {}
        
        # Index Nifty 500 companies
        for _, row in self.nifty500_df.iterrows():
            info = {
                'name': str(row['Name']).strip(),
                'nse_code': str(row['NSE Code']).strip(),
                'bse_code': str(row['BSE Code']).strip(),
                'industry': str(row['Industry']).strip(),
                'market_cap': float(row['Market Capitalization']) if pd.notna(row['Market Capitalization']) else 0,
                'source': 'nifty500'
            }
            
            if info['nse_code'] and info['nse_code'].lower() != 'nan':
                self.nse_to_info[info['nse_code'].upper()] = info
            if info['bse_code'] and info['bse_code'].lower() != 'nan':
                self.bse_to_info[info['bse_code']] = info
            if info['name']:
                self.name_to_info[info['name'].upper()] = info
        
        # Index custom companies
        for company in self.custom_companies:
            info = {
                'name': company.get('name', ''),
                'nse_code': company.get('nse_code', ''),
                'bse_code': company.get('bse_code', ''),
                'industry': company.get('industry', 'Unknown'),
                'market_cap': company.get('market_cap', 0),
                'source': 'custom'
            }
            
            if info['nse_code']:
                self.nse_to_info[info['nse_code'].upper()] = info
            if info['bse_code']:
                self.bse_to_info[info['bse_code']] = info
            if info['name']:
                self.name_to_info[info['name'].upper()] = info
    
    def get_all_companies(self) -> List[Dict]:
        """
        Get all companies (Nifty 500 + custom).
        
        Returns:
            List of company info dicts
        """
        companies = []
        
        # Add Nifty 500 companies
        for _, row in self.nifty500_df.iterrows():
            nse_code = str(row['NSE Code']).strip()
            if nse_code and nse_code.lower() != 'nan':
                companies.append({
                    'name': str(row['Name']).strip(),
                    'nse_code': nse_code,
                    'bse_code': str(row['BSE Code']).strip() if pd.notna(row['BSE Code']) else '',
                    'industry': str(row['Industry']).strip(),
                    'market_cap': float(row['Market Capitalization']) if pd.notna(row['Market Capitalization']) else 0,
                    'source': 'nifty500'
                })
        
        # Add custom companies
        for company in self.custom_companies:
            companies.append({
                'name': company.get('name', ''),
                'nse_code': company.get('nse_code', ''),
                'bse_code': company.get('bse_code', ''),
                'industry': company.get('industry', 'Unknown'),
                'market_cap': company.get('market_cap', 0),
                'source': 'custom'
            })
        
        return companies
    
    def get_company_by_nse(self, nse_code: str) -> Optional[Dict]:
        """Get company info by NSE code."""
        return self.nse_to_info.get(nse_code.upper())
    
    def get_company_by_bse(self, bse_code: str) -> Optional[Dict]:
        """Get company info by BSE code."""
        return self.bse_to_info.get(str(bse_code))
    
    def get_company_by_name(self, name: str) -> Optional[Dict]:
        """Get company info by name."""
        return self.name_to_info.get(name.upper())
    
    def get_company(self, identifier: str) -> Optional[Dict]:
        """
        Get company by any identifier (NSE, BSE, or name).
        Tries NSE first, then BSE, then name.
        """
        result = self.get_company_by_nse(identifier)
        if result:
            return result
        
        result = self.get_company_by_bse(identifier)
        if result:
            return result
        
        return self.get_company_by_name(identifier)
    
    def get_sector(self, identifier: str) -> str:
        """
        Get sector/industry for a company.
        
        Args:
            identifier: NSE code, BSE code, or company name
            
        Returns:
            Industry/sector string or 'Unknown'
        """
        company = self.get_company(identifier)
        if company:
            return company.get('industry', 'Unknown')
        return 'Unknown'
    
    def get_nse_codes(self) -> List[str]:
        """Get all NSE codes for analysis."""
        codes = []
        for company in self.get_all_companies():
            if company['nse_code']:
                codes.append(company['nse_code'])
        return codes
    
    def validate_on_screener(self, nse_code: str) -> bool:
        """
        Validate that a company exists on screener.in.
        
        Args:
            nse_code: NSE code to validate
            
        Returns:
            True if company page exists
        """
        url = f"{self.base_url}/company/{quote(nse_code)}/consolidated/"
        
        try:
            if USE_CFFI:
                response = cffi_requests.get(
                    url, 
                    headers=self.headers, 
                    impersonate=self.impersonate_ver,
                    timeout=10
                )
            else:
                response = cffi_requests.get(url, headers=self.headers, timeout=10)
            
            return response.status_code == 200
            
        except Exception as e:
            logger.warning(f"Validation failed for {nse_code}: {e}")
            return False
    
    def add_custom_company(
        self,
        name: str,
        nse_code: str = None,
        bse_code: str = None,
        industry: str = "Unknown",
        market_cap: float = 0,
        validate: bool = True
    ) -> Dict:
        """
        Add a custom company to the list.
        
        Args:
            name: Company name
            nse_code: NSE trading symbol
            bse_code: BSE code (optional)
            industry: Industry/sector
            market_cap: Market capitalization in crores
            validate: Whether to validate on screener.in
            
        Returns:
            Result dict with 'success' and 'message' keys
        """
        # Validation
        if not name:
            return {'success': False, 'message': 'Company name is required'}
        
        if not nse_code and not bse_code:
            return {'success': False, 'message': 'At least one of NSE code or BSE code is required'}
        
        # Check if already exists
        if nse_code and nse_code.upper() in self.nse_to_info:
            return {'success': False, 'message': f'Company with NSE code {nse_code} already exists'}
        
        # Validate on screener.in if requested
        if validate and nse_code:
            if not self.validate_on_screener(nse_code):
                return {'success': False, 'message': f'Company {nse_code} not found on screener.in'}
        
        # Add to custom companies
        company = {
            'name': name,
            'nse_code': nse_code.upper() if nse_code else '',
            'bse_code': str(bse_code) if bse_code else '',
            'industry': industry,
            'market_cap': market_cap
        }
        
        self.custom_companies.append(company)
        self._save_custom_companies()
        self._build_indices()  # Rebuild indices
        
        logger.info(f"Added custom company: {name} ({nse_code})")
        
        return {
            'success': True, 
            'message': f'Company {name} added successfully',
            'company': company
        }
    
    def remove_custom_company(self, nse_code: str) -> Dict:
        """Remove a custom company."""
        nse_upper = nse_code.upper()
        
        # Find and remove
        original_len = len(self.custom_companies)
        self.custom_companies = [
            c for c in self.custom_companies 
            if c.get('nse_code', '').upper() != nse_upper
        ]
        
        if len(self.custom_companies) < original_len:
            self._save_custom_companies()
            self._build_indices()
            return {'success': True, 'message': f'Company {nse_code} removed'}
        
        return {'success': False, 'message': f'Custom company {nse_code} not found'}
    
    def get_companies_by_industry(self, industry: str) -> List[Dict]:
        """Get all companies in a specific industry."""
        industry_lower = industry.lower()
        return [
            c for c in self.get_all_companies()
            if industry_lower in c.get('industry', '').lower()
        ]
    
    def get_companies_by_market_cap(
        self, 
        min_cap: float = 0, 
        max_cap: float = float('inf')
    ) -> List[Dict]:
        """Get companies within a market cap range."""
        return [
            c for c in self.get_all_companies()
            if min_cap <= c.get('market_cap', 0) <= max_cap
        ]
    
    def get_statistics(self) -> Dict:
        """Get summary statistics."""
        all_companies = self.get_all_companies()
        
        # Count by source
        nifty_count = sum(1 for c in all_companies if c['source'] == 'nifty500')
        custom_count = sum(1 for c in all_companies if c['source'] == 'custom')
        
        # Count unique industries
        industries = set(c['industry'] for c in all_companies)
        
        return {
            'total_companies': len(all_companies),
            'nifty500_count': nifty_count,
            'custom_count': custom_count,
            'unique_industries': len(industries),
            'industries': sorted(industries)
        }


# Singleton instance for easy import
_manager_instance = None

def get_company_manager() -> CompanyManager:
    """Get singleton CompanyManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = CompanyManager()
    return _manager_instance


if __name__ == "__main__":
    # Test the company manager
    print("Testing Company Manager...")
    print("=" * 50)
    
    manager = CompanyManager()
    stats = manager.get_statistics()
    
    print(f"Total Companies: {stats['total_companies']}")
    print(f"  - Nifty 500: {stats['nifty500_count']}")
    print(f"  - Custom: {stats['custom_count']}")
    print(f"Unique Industries: {stats['unique_industries']}")
    
    # Test lookups
    print("\nSample Lookups:")
    for code in ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY']:
        info = manager.get_company_by_nse(code)
        if info:
            print(f"  {code}: {info['name']} - {info['industry']}")
        else:
            print(f"  {code}: Not found")
