"""
State Tracker
=============
Tracks processing state for incremental updates.
Only processes new/unprocessed company-quarter combinations.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class StateTracker:
    """
    Tracks which company-quarter combinations have been processed.
    Enables incremental updates (only new data) and force full re-runs.
    """
    
    def __init__(self, state_file: str = None):
        """
        Initialize the state tracker.
        
        Args:
            state_file: Path to JSON state file (default: processing_state.json)
        """
        base_path = Path(__file__).parent
        self.state_file = Path(state_file) if state_file else base_path / "processing_state.json"
        
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from JSON file."""
        if not self.state_file.exists():
            return {
                'processed': {},  # {company: {quarter: timestamp}}
                'last_full_run': None,
                'last_incremental_run': None,
                'stats': {
                    'total_processed': 0,
                    'total_companies': 0
                }
            }
        
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return {
                'processed': {},
                'last_full_run': None,
                'last_incremental_run': None,
                'stats': {'total_processed': 0, 'total_companies': 0}
            }
    
    def _save_state(self):
        """Save state to JSON file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")
    
    def is_processed(self, company: str, quarter: str) -> bool:
        """
        Check if a company-quarter combination has been processed.
        
        Args:
            company: Company NSE code
            quarter: Quarter string (e.g., "Jan_2024" or "Q3_2024")
            
        Returns:
            True if already processed
        """
        company_state = self.state.get('processed', {}).get(company.upper(), {})
        return quarter in company_state
    
    def mark_processed(self, company: str, quarter: str, metadata: Dict = None):
        """
        Mark a company-quarter as processed.
        
        Args:
            company: Company NSE code
            quarter: Quarter string
            metadata: Optional metadata to store (e.g., sentiment scores)
        """
        company_upper = company.upper()
        
        if 'processed' not in self.state:
            self.state['processed'] = {}
        
        if company_upper not in self.state['processed']:
            self.state['processed'][company_upper] = {}
        
        self.state['processed'][company_upper][quarter] = {
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        
        # Update stats
        self._update_stats()
        self._save_state()
    
    def mark_batch_processed(self, items: List[Tuple[str, str, Dict]]):
        """
        Mark multiple items as processed in one save operation.
        
        Args:
            items: List of (company, quarter, metadata) tuples
        """
        for company, quarter, metadata in items:
            company_upper = company.upper()
            
            if 'processed' not in self.state:
                self.state['processed'] = {}
            
            if company_upper not in self.state['processed']:
                self.state['processed'][company_upper] = {}
            
            self.state['processed'][company_upper][quarter] = {
                'timestamp': datetime.now().isoformat(),
                'metadata': metadata or {}
            }
        
        self._update_stats()
        self._save_state()
    
    def _update_stats(self):
        """Update processing statistics."""
        processed = self.state.get('processed', {})
        
        total_items = sum(len(quarters) for quarters in processed.values())
        total_companies = len(processed)
        
        self.state['stats'] = {
            'total_processed': total_items,
            'total_companies': total_companies
        }
    
    def get_unprocessed(self, available: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """
        Filter out already processed items.
        
        Args:
            available: List of (company, quarter) tuples to check
            
        Returns:
            List of unprocessed (company, quarter) tuples
        """
        unprocessed = []
        
        for company, quarter in available:
            if not self.is_processed(company, quarter):
                unprocessed.append((company, quarter))
        
        return unprocessed
    
    def get_processed_quarters(self, company: str) -> List[str]:
        """Get list of processed quarters for a company."""
        company_upper = company.upper()
        return list(self.state.get('processed', {}).get(company_upper, {}).keys())
    
    def get_company_status(self, company: str) -> Dict:
        """Get processing status for a company."""
        company_upper = company.upper()
        quarters = self.state.get('processed', {}).get(company_upper, {})
        
        return {
            'company': company_upper,
            'quarters_processed': len(quarters),
            'quarters': list(quarters.keys()),
            'last_processed': max(
                (q['timestamp'] for q in quarters.values()),
                default=None
            ) if quarters else None
        }
    
    def clear_company(self, company: str):
        """Clear processing state for a specific company."""
        company_upper = company.upper()
        
        if company_upper in self.state.get('processed', {}):
            del self.state['processed'][company_upper]
            self._update_stats()
            self._save_state()
            logger.info(f"Cleared state for company: {company_upper}")
    
    def clear_all(self):
        """
        Clear all processing state.
        Used for forcing a full re-run.
        """
        self.state = {
            'processed': {},
            'last_full_run': None,
            'last_incremental_run': None,
            'stats': {'total_processed': 0, 'total_companies': 0}
        }
        self._save_state()
        logger.info("Cleared all processing state")
    
    def record_run(self, run_type: str = 'incremental', stats: Dict = None):
        """
        Record a processing run.
        
        Args:
            run_type: 'full' or 'incremental'
            stats: Optional run statistics
        """
        timestamp = datetime.now().isoformat()
        
        if run_type == 'full':
            self.state['last_full_run'] = {
                'timestamp': timestamp,
                'stats': stats or {}
            }
        else:
            self.state['last_incremental_run'] = {
                'timestamp': timestamp,
                'stats': stats or {}
            }
        
        self._save_state()
    
    def get_run_history(self) -> Dict:
        """Get run history information."""
        return {
            'last_full_run': self.state.get('last_full_run'),
            'last_incremental_run': self.state.get('last_incremental_run'),
            'stats': self.state.get('stats', {})
        }
    
    def get_summary(self) -> Dict:
        """Get summary of processing state."""
        processed = self.state.get('processed', {})
        
        # Calculate per-company stats
        company_stats = []
        for company, quarters in processed.items():
            company_stats.append({
                'company': company,
                'quarters': len(quarters)
            })
        
        # Sort by number of quarters
        company_stats.sort(key=lambda x: x['quarters'], reverse=True)
        
        last_full = self.state.get('last_full_run')
        last_incr = self.state.get('last_incremental_run')
        
        return {
            'total_companies': len(processed),
            'total_quarters': sum(len(q) for q in processed.values()),
            'top_companies': company_stats[:10],
            'last_full_run': last_full.get('timestamp') if last_full else None,
            'last_incremental_run': last_incr.get('timestamp') if last_incr else None
        }


# Singleton instance
_tracker_instance = None

def get_state_tracker() -> StateTracker:
    """Get singleton StateTracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = StateTracker()
    return _tracker_instance


if __name__ == "__main__":
    # Test the state tracker
    print("Testing State Tracker...")
    print("=" * 50)
    
    tracker = StateTracker()
    
    # Test marking items as processed
    test_items = [
        ('RELIANCE', 'Jan_2024', {'sentiment': 0.5}),
        ('RELIANCE', 'Apr_2024', {'sentiment': 0.6}),
        ('TCS', 'Jan_2024', {'sentiment': 0.4}),
    ]
    
    print(f"Before: {tracker.get_summary()}")
    
    tracker.mark_batch_processed(test_items)
    
    print(f"After: {tracker.get_summary()}")
    
    # Test filtering
    available = [
        ('RELIANCE', 'Jan_2024'),
        ('RELIANCE', 'Jul_2024'),
        ('TCS', 'Apr_2024'),
    ]
    
    unprocessed = tracker.get_unprocessed(available)
    print(f"Unprocessed: {unprocessed}")
    
    # Clean up test data
    tracker.clear_all()
    print("State cleared for testing")
