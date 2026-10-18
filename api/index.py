import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Add project root directory to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set database path to /tmp for Vercel serverless environment
os.environ.setdefault("LISTING_PREFLIGHT_DB", "/tmp/listingpreflight.sqlite3")

import server

# Initialize SQLite database in /tmp
server.initialize_database()

# Subclass BaseHTTPRequestHandler directly so AST parser detects it immediately
class handler(server.PreflightHandler):
    pass

app = handler
application = handler
