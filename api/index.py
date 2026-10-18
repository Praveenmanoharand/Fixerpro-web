import os
import sys
from pathlib import Path

# Add project root directory to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set database path to /tmp for Vercel read-only serverless environment
os.environ.setdefault("LISTING_PREFLIGHT_DB", "/tmp/listingpreflight.sqlite3")

import server

# Initialize SQLite database in /tmp
server.initialize_database()

# Export handler for Vercel Python Serverless Runtime
handler = server.PreflightHandler
