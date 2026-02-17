"""
Vercel Serverless Entry Point
==============================
Imports the Flask app from unified_app.py for Vercel deployment.
Vercel automatically detects the 'app' variable as a WSGI application.
"""

import os
import sys

# Mark as running on Vercel serverless
os.environ['VERCEL'] = '1'

# Add parent directory to path so we can import unified_app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unified_app import app

# Vercel looks for 'app' as the WSGI handler
