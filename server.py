"""
Fixerpro — Production-ready backend server.
Serves the SPA frontend plus REST API for auth, background removal, and AI review.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from contextlib import contextmanager
from email.message import EmailMessage
from getpass import getpass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import smtplib
import ssl
from typing import Any, Generator
from urllib.parse import unquote, urlsplit

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

# ── Configuration ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "index.html"
ENV_FILE = ROOT / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict, supporting quotes and export prefix."""
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


for _key, _value in read_env_file(ENV_FILE).items():
    os.environ.setdefault(_key, _value)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
PRO_PLAN_PRICE = int(os.environ.get("PRO_PLAN_PRICE", "499"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "officialverdictv@gmail.com").strip()
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "").strip()

if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp/listingpreflight.sqlite3")
else:
    DB_PATH = Path(os.environ.get("LISTING_PREFLIGHT_DB", ROOT / "listingpreflight.sqlite3"))
HOST = os.environ.get("LISTING_PREFLIGHT_HOST", "127.0.0.1")
PORT = int(os.environ.get("LISTING_PREFLIGHT_PORT", "8000"))
OWNER_EMAIL = (
    os.environ.get("LISTING_PREFLIGHT_OWNER_EMAIL", "praveenmanoharan.dev@gmail.com")
    .strip()
    .lower()
)
SESSION_SECONDS = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 310_000
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
REMOVE_BG_URL = "https://api.remove.bg/v1.0/removebg"
POOF_BG_URL = "https://api.poof.bg/v1/remove"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_URL = GEMINI_INTERACTIONS_URL
MAX_GEMINI_RESPONSE_BYTES = 256 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_REQUEST_BODY = 50 * 1024 * 1024

# ── Rate Limiting ──────────────────────────────────────────────────────────

_rate_buckets: dict[str, list[float]] = defaultdict(list)
RATE_WINDOW = 60  # seconds
RATE_LIMIT = 30   # requests per window per IP


def rate_limited(ip: str) -> bool:
    """Simple sliding window rate limiter."""
    now = time.time()
    bucket = _rate_buckets[ip]
    # Prune old entries
    _rate_buckets[ip] = [t for t in bucket if now - t < RATE_WINDOW]
    if len(_rate_buckets[ip]) >= RATE_LIMIT:
        return True
    _rate_buckets[ip].append(now)
    return False


# ── Image Processing ───────────────────────────────────────────────────────

class ImageProcessingError(Exception):
    pass


def remove_background(image: bytes, content_type: str, api_key: str) -> tuple[bytes, str]:
    """Send image to Poof.bg (or remove.bg fallback) and return transparent PNG."""
    is_poof = api_key.startswith("pk_") or "poof" in api_key.lower()
    endpoint = POOF_BG_URL if is_poof else REMOVE_BG_URL
    header_key = "x-api-key" if is_poof else "X-Api-Key"

    boundary = secrets.token_hex(16)
    crlf = b"\r\n"
    parts = [
        b"--" + boundary.encode("ascii") + crlf,
        b'Content-Disposition: form-data; name="image_file"; filename="product.png"' + crlf,
        f"Content-Type: {content_type}".encode("ascii") + crlf + crlf,
        image,
        crlf,
        b"--" + boundary.encode("ascii") + crlf,
        b'Content-Disposition: form-data; name="size"' + crlf + crlf + b"auto" + crlf,
        b"--" + boundary.encode("ascii") + crlf,
        b'Content-Disposition: form-data; name="format"' + crlf + crlf + b"png" + crlf,
        b"--" + boundary.encode("ascii") + b"--" + crlf,
    ]
    body = b"".join(parts)

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            header_key: api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarketPro/2.0",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    provider_name = "Poof.bg" if is_poof else "remove.bg"
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (402, 429):
            raise ImageProcessingError(
                f"{provider_name} plan credits or request limit reached. Check your API account."
            ) from error
        if error.code in (401, 403):
            raise ImageProcessingError(
                f"{provider_name} rejected the API key. Check POOF_BG_API_KEY / REMOVE_BG_API_KEY in .env."
            ) from error
        if error.code in (400, 413):
            raise ImageProcessingError(
                f"{provider_name} could not process this image. Check format and size."
            ) from error
        raise ImageProcessingError(
            f"{provider_name} is temporarily unavailable (HTTP {error.code})."
        ) from error
    except urllib.error.URLError as error:
        raise ImageProcessingError(
            f"Could not connect to {provider_name}. Check your internet connection."
        ) from error
    except TimeoutError as error:
        raise ImageProcessingError(
            "Background removal timed out. Try a smaller image."
        ) from error
    if len(result) > MAX_IMAGE_BYTES:
        raise ImageProcessingError("Processed image exceeded the 25 MB limit.")
    if not result:
        raise ImageProcessingError(
            f"{provider_name} returned an unexpected empty result. Check your API key."
        )
    return result, "image/png"


def review_image_with_gemini(
    image: bytes, content_type: str, marketplace: str, api_key: str
) -> str:
    """Send image to Gemini for AI review and return the feedback text."""
    prompt = (
        f"Review this {marketplace} product listing photo for a seller. Give "
        "concise, practical visual feedback about product visibility, framing, "
        "background, lighting, and likely listing-readiness. For Amazon, mention "
        "that the main image generally needs a pure white background and the "
        "product should be prominent. For Etsy, focus on clear, attractive "
        "presentation. Do not claim to certify marketplace compliance or "
        "measure exact pixel rules. Do not suggest changing the product itself; "
        "do not infer details that are not visible. Clearly say this is an AI "
        "visual assessment and must be checked by the seller."
    )

    request_payload = {
        "model": "gemini-3.8-flash",
        "store": False,
        "input": [
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "mime_type": content_type,
                "data": base64.b64encode(image).decode("ascii"),
            },
        ],
    }
    body = json.dumps(request_payload).encode("utf-8")

    request = urllib.request.Request(
        GEMINI_INTERACTIONS_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read(MAX_GEMINI_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise ImageProcessingError(
                "Gemini quota or rate limit reached. Try again in a minute."
            ) from error
        if error.code in (401, 403):
            raise ImageProcessingError(
                "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
            ) from error
        if error.code in (400, 413):
            raise ImageProcessingError(
                "Gemini could not review this image. Check format and size."
            ) from error
        raise ImageProcessingError(
            f"Gemini is temporarily unavailable (HTTP {error.code})."
        ) from error
    except urllib.error.URLError as error:
        raise ImageProcessingError(
            "Could not connect to Gemini. Check your internet connection."
        ) from error
    except TimeoutError as error:
        raise ImageProcessingError("Gemini review timed out. Try again.") from error

    if len(response_body) > MAX_GEMINI_RESPONSE_BYTES:
        raise ImageProcessingError("Gemini response exceeded the server limit.")
    try:
        payload = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImageProcessingError("Gemini returned an invalid response.") from error
    if not isinstance(payload, dict):
        raise ImageProcessingError("Gemini returned an invalid response.")

    # Extract text from Gemini response (handles Interactions API, test mocks, and generateContent)
    review_parts = []

    # 1. Google Gemini Interactions API format (steps -> content -> text)
    steps = payload.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and step.get("type") == "model_output":
                content = step.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            text = item["text"]
                            if isinstance(text, str) and text.strip():
                                review_parts.append(text.strip())

    # 2. Direct outputs format
    outputs = payload.get("outputs", [])
    if isinstance(outputs, list):
        for out in outputs:
            if isinstance(out, dict) and "text" in out:
                review_parts.append(out["text"])

    # 3. Standard generateContent format
    candidates = payload.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                content = candidate.get("content", {})
                if isinstance(content, dict):
                    parts = content.get("parts", [])
                    if isinstance(parts, list):
                        for part in parts:
                            if isinstance(part, dict) and "text" in part:
                                text = part["text"]
                                if isinstance(text, str) and text.strip():
                                    review_parts.append(text.strip())

    review = "\n\n".join(part for part in review_parts if part)
    if not review:
        raise ImageProcessingError(
            "Gemini returned no text review. Try again."
        )
    return review[:12_000]


# ── Database ───────────────────────────────────────────────────────────────

class DBConnectionWrapper:
    def __init__(self, raw_conn, is_pg: bool):
        self.raw_conn = raw_conn
        self.is_pg = is_pg
        self.lastrowid = None

    def _convert_query(self, query: str) -> str:
        if self.is_pg:
            return query.replace("?", "%s")
        return query

    def execute(self, query: str, params: tuple | list = ()):
        q = self._convert_query(query)
        if self.is_pg:
            cur = self.raw_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(q, params)
            if cur.description:
                rows = cur.fetchall()
                cur.close()
                return DBResultWrapper(rows)
            cur.close()
            return DBResultWrapper([])
        else:
            return self.raw_conn.execute(q, params)

    def executescript(self, script: str):
        if self.is_pg:
            cur = self.raw_conn.cursor()
            cur.execute(script)
            cur.close()
        else:
            self.raw_conn.executescript(script)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()


class DBResultWrapper:
    def __init__(self, rows: list):
        self.rows = rows
        self._idx = 0

    def fetchone(self):
        if self.rows:
            return self.rows[0]
        return None

    def fetchall(self):
        return self.rows


@contextmanager
def connect_db() -> Generator[Any, None, None]:
    """Context manager for Database connection (Supabase Postgres or SQLite)."""
    if DATABASE_URL and psycopg2:
        conn = psycopg2.connect(DATABASE_URL)
        wrapper = DBConnectionWrapper(conn, is_pg=True)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw_conn = sqlite3.connect(DB_PATH, timeout=10)
        raw_conn.row_factory = sqlite3.Row
        wrapper = DBConnectionWrapper(raw_conn, is_pg=False)
    try:
        yield wrapper
        wrapper.commit()
    except Exception:
        wrapper.rollback()
        raise
    finally:
        wrapper.close()


DEV_EMAIL = "praveenmanoharan.dev@gmail.com"
DEV_PASSWORD = "1234567890@PR"


def initialize_database() -> None:
    """Create tables and ensure schema is up to date."""
    with connect_db() as connection:
        if connection.is_pg:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    salt BYTEA NOT NULL,
                    password_hash BYTEA NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'free',
                    role TEXT NOT NULL DEFAULT 'user',
                    fixes_used INTEGER NOT NULL DEFAULT 0,
                    plan_expires_at BIGINT DEFAULT 0,
                    created_at BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at BIGINT NOT NULL
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at BIGINT DEFAULT 0;
                """
            )
        else:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'free',
                    role TEXT NOT NULL DEFAULT 'user',
                    fixes_used INTEGER NOT NULL DEFAULT 0,
                    plan_expires_at INTEGER DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
            if "role" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
            if "fixes_used" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN fixes_used INTEGER NOT NULL DEFAULT 0")
            if "plan_expires_at" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN plan_expires_at INTEGER DEFAULT 0")

        # Ensure developer owner account exists with Pro + Admin privileges
        dev_salt = secrets.token_bytes(16)
        dev_pw_hash = password_hash(DEV_PASSWORD, dev_salt)
        connection.execute(
            """
            INSERT INTO users (name, email, salt, password_hash, plan, role, fixes_used, created_at)
            VALUES (?, ?, ?, ?, 'pro', 'admin', 0, ?)
            ON CONFLICT(email) DO UPDATE SET
                password_hash=excluded.password_hash,
                salt=excluded.salt,
                plan='pro',
                role='admin'
            """,
            ("Praveen (Developer)", DEV_EMAIL, dev_salt, dev_pw_hash, int(time.time())),
        )
        connection.execute(
            "UPDATE users SET plan='pro', role='admin' WHERE lower(email)=?",
            (OWNER_EMAIL,),
        )


def password_hash(password: str, salt: bytes) -> bytes:
    # Convert memoryview/bytes safely
    salt_bytes = bytes(salt) if not isinstance(salt, bytes) else salt
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, PASSWORD_ITERATIONS
    )


def public_user(row: Any) -> dict[str, object]:
    fixes_used = 0
    try:
        fixes_used = row["fixes_used"]
    except (IndexError, KeyError, TypeError):
        pass

    plan = row["plan"]
    plan_expires_at = 0
    try:
        plan_expires_at = int(row["plan_expires_at"] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        pass

    now = int(time.time())
    # If Pro plan has expired, treat as free
    if plan == "pro" and plan_expires_at > 0 and plan_expires_at < now and row["role"] != "admin":
        plan = "free"

    days_left = 0
    if plan == "pro" and plan_expires_at > now:
        days_left = max(1, int((plan_expires_at - now) / 86400))

    return {
        "name": row["name"],
        "email": row["email"],
        "plan": plan,
        "role": row["role"],
        "fixes_used": fixes_used,
        "plan_expires_at": plan_expires_at,
        "days_left": days_left,
        "max_free_fixes": 5,
        "unlimited": plan == "pro",
    }


def provision_owner(email: str, name: str, password: str) -> None:
    """Create or update the admin/owner account."""
    normalized_email = email.strip().lower()
    if normalized_email != OWNER_EMAIL:
        raise ValueError("Owner email must match LISTING_PREFLIGHT_OWNER_EMAIL.")
    if not 2 <= len(name.strip()) <= 100:
        raise ValueError("Owner name must be between 2 and 100 characters.")
    if len(password) < 12:
        raise ValueError("Owner password must be at least 12 characters.")

    salt = secrets.token_bytes(16)
    with connect_db() as connection:
        connection.execute(
            "INSERT INTO users (name, email, salt, password_hash, plan, role, created_at) "
            "VALUES (?, ?, ?, ?, 'pro', 'admin', ?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, salt=excluded.salt, "
            "password_hash=excluded.password_hash, plan='pro', role='admin'",
            (
                name.strip(),
                normalized_email,
                salt,
                password_hash(password, salt),
                int(time.time()),
            ),
        )


# ── HTTP Handler ───────────────────────────────────────────────────────────

class PreflightHandler(BaseHTTPRequestHandler):
    server_version = "Fixerpro/2.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _security_headers(self) -> None:
        """Add common security headers to every response."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")

    def send_json(
        self, status: int, payload: dict, set_cookie: str | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_image(self, image: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(image)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(image)

    def send_html_file(self, filepath: Path) -> None:
        """Serve an HTML file with proper headers."""
        try:
            body = filepath.read_bytes()
        except OSError:
            self.send_json(500, {"error": "Frontend file could not be read."})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Marketplace, Cookie")
        self.end_headers()

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if not path.startswith("/api/"):
            if path in ("/me", "/health", "/admin/summary"):
                path = "/api" + path

        # API endpoints
        if path == "/api/me":
            row = self.current_user()
            self.send_json(200, {"user": public_user(row) if row else None})
            return

        if path == "/api/admin/summary":
            user = self.current_user()
            if user is None:
                self.send_json(401, {"error": "Log in to continue."})
                return
            if user["role"] != "admin":
                self.send_json(403, {"error": "Admin access is required."})
                return
            now = int(time.time())
            with connect_db() as connection:
                connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                summary = connection.execute(
                    "SELECT COUNT(*) AS users, "
                    "SUM(CASE WHEN plan='pro' THEN 1 ELSE 0 END) AS pro_users "
                    "FROM users"
                ).fetchone()
                active_sessions = connection.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()[0]
            self.send_json(
                200,
                {
                    "users": summary["users"],
                    "pro_users": summary["pro_users"] or 0,
                    "active_sessions": active_sessions,
                },
            )
            return

        # Health check
        if path == "/api/health":
            self.send_json(200, {
                "status": "healthy",
                "timestamp": int(time.time()),
                "version": "2.0",
            })
            return

        # Serve main SPA — all non-API GET requests serve index.html
        if path == "/" or not path.startswith("/api/"):
            self.send_html_file(HTML_FILE)
            return

        self.send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        try:
            self._do_POST_internal()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json(500, {"error": f"Internal server error: {e}"})

    def _do_POST_internal(self) -> None:
        # Rate limiting
        client_ip = self.headers.get("x-forwarded-for", "").split(",")[0].strip() or self.address_string()
        if rate_limited(client_ip):
            self.send_json(429, {"error": "Too many requests. Please slow down."})
            return

        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host") and not os.environ.get("VERCEL"):
            self.send_json(403, {"error": "Cross-origin requests are not allowed."})
            return

        path = unquote(urlsplit(self.path).path)
        if not path.startswith("/api/"):
            if path.startswith("/image/") or path in ("/register", "/login", "/logout", "/forgot", "/contact"):
                path = "/api" + path
            else:
                self.send_json(404, {"error": "Not found."})
                return

        if path == "/api/logout":
            self.logout()
            return
        if path == "/api/payment/create-order":
            self.create_payment_order_handler()
            return
        if path == "/api/payment/verify":
            self.verify_payment_handler()
            return
        if path == "/api/image/remove-background":
            self.remove_background_handler()
            return
        if path == "/api/image/review":
            self.review_image_handler()
            return
        if path == "/api/image/record-fix":
            self.record_fix_handler()
            return
        if path == "/api/contact":
            self.contact_handler()
            return
        if path == "/api/forgot":
            self.send_json(
                503,
                {"error": "Password reset email is not configured on this server."},
            )
            return
        if path not in ("/api/register", "/api/login"):
            self.send_json(404, {"error": "Not found."})
            return

        data = self.read_json()
        if data is None:
            return
        if path == "/api/register":
            self.register(data)
        else:
            self.login(data)

    def create_payment_order_handler(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Please log in before upgrading to Pro."})
            return
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            self.send_json(503, {"error": "Payment gateway is not configured on this server."})
            return

        amount_in_paise = PRO_PLAN_PRICE * 100
        receipt = f"rcpt_{user['id']}_{int(time.time())}"
        order_payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {
                "user_id": str(user["id"]),
                "email": user["email"],
                "plan": "pro"
            }
        }
        auth_bytes = base64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode("ascii")).decode("ascii")
        req = urllib.request.Request(
            "https://api.razorpay.com/v1/orders",
            data=json.dumps(order_payload).encode("utf-8"),
            headers={
                "Authorization": f"Basic {auth_bytes}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                order_data = json.loads(res.read().decode("utf-8"))
        except Exception as err:
            self.send_json(502, {"error": f"Failed to initialize payment with Razorpay: {err}"})
            return

        self.send_json(200, {
            "order_id": order_data.get("id"),
            "amount": amount_in_paise,
            "currency": "INR",
            "key_id": RAZORPAY_KEY_ID,
            "user_name": user["name"],
            "user_email": user["email"]
        })

    def verify_payment_handler(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Please log in."})
            return
        data = self.read_json()
        if not data:
            return

        order_id = data.get("razorpay_order_id", "").strip()
        payment_id = data.get("razorpay_payment_id", "").strip()
        signature = data.get("razorpay_signature", "").strip()

        if not (order_id and payment_id and signature):
            self.send_json(400, {"error": "Missing payment verification parameters."})
            return

        # HMAC SHA256 verification
        expected_sig = hmac.new(
            RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{order_id}|{payment_id}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, signature):
            self.send_json(400, {"error": "Payment verification failed. Invalid signature."})
            return

        # Upgrade user in Database with 30-day validity
        now = int(time.time())
        expires_at = now + (30 * 86400)  # 30 days in seconds
        with connect_db() as connection:
            connection.execute(
                "UPDATE users SET plan = 'pro', fixes_used = 0, plan_expires_at = ? WHERE id = ?",
                (expires_at, user["id"])
            )
            updated_user = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user["id"],)
            ).fetchone()

        self.send_json(200, {
            "ok": True,
            "message": "Payment verified! Your account is now upgraded to Pro.",
            "user": public_user(updated_user) if updated_user else None
        })

    def contact_handler(self) -> None:
        data = self.read_json()
        if not data:
            return

        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip()
        message = str(data.get("message", "")).strip()

        if not name or len(name) < 2:
            self.send_json(400, {"error": "Please provide your name (at least 2 characters)."})
            return
        if not email or not EMAIL_RE.fullmatch(email):
            self.send_json(400, {"error": "Please provide a valid email address."})
            return
        if not message or len(message) < 5:
            self.send_json(400, {"error": "Message must be at least 5 characters long."})
            return

        if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
            self.send_json(503, {"error": "Email service is not configured on this server."})
            return

        try:
            msg = EmailMessage()
            msg["Subject"] = f"New Contact Message from Fixerpro - {name}"
            msg["From"] = f"Fixerpro Contact Form <{SMTP_EMAIL}>"
            msg["To"] = SMTP_EMAIL
            msg["Reply-To"] = email
            msg.set_content(
                f"You received a new message from the Fixerpro contact form:\n\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
                f"--------------------------------------------------\n"
                f"Message:\n{message}\n"
                f"--------------------------------------------------\n\n"
                f"You can simply reply to this email to respond directly to {name}."
            )

            context = ssl.create_default_context()
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
                server.starttls(context=context)
                server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
                server.send_message(msg)

            self.send_json(200, {
                "ok": True,
                "message": "Thank you! Your message has been sent successfully. We will get back to you shortly."
            })
        except Exception as err:
            self.send_json(502, {"error": f"Failed to deliver message: {err}"})

    def record_fix_handler(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json(
                401,
                {"error": "Please log in to fix images.", "auth_required": True},
            )
            return

        if user["plan"] != "pro" and user["fixes_used"] >= 5:
            self.send_json(
                403,
                {
                    "error": "You have used all 5 free fixes for this email. Upgrade to Pro for unlimited AI fixes!",
                    "upgrade": True,
                    "fixes_used": user["fixes_used"],
                    "limit": 5,
                },
            )
            return

        with connect_db() as connection:
            connection.execute(
                "UPDATE users SET fixes_used = fixes_used + 1 WHERE id = ?",
                (user["id"],),
            )
            updated = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user["id"],)
            ).fetchone()

        self.send_json(
            200,
            {
                "ok": True,
                "fixes_used": updated["fixes_used"],
                "plan": updated["plan"],
                "remaining": (
                    999999 if updated["plan"] == "pro" else max(0, 5 - updated["fixes_used"])
                ),
            },
        )

    def remove_background_handler(self) -> None:
        user = self.current_user()
        if user:
            if user["plan"] != "pro" and user["fixes_used"] >= 5:
                self.send_json(
                    403,
                    {
                        "error": "You have used all 5 free fixes for this email. Upgrade to Pro for unlimited AI fixes!",
                        "upgrade": True,
                        "fixes_used": user["fixes_used"],
                        "limit": 5,
                    },
                )
                return

        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type not in IMAGE_TYPES:
            self.send_json(
                415,
                {"error": "Use a JPG, PNG, or WebP image for background removal."},
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid image upload."})
            return
        if length < 1 or length > MAX_IMAGE_BYTES:
            self.send_json(400, {"error": "Image must be between 1 byte and 25 MB."})
            return
        image = self.rfile.read(length)
        if len(image) != length:
            self.send_json(
                400, {"error": "Image upload was incomplete. Please try again."}
            )
            return
        api_key = os.environ.get("REMOVE_BG_API_KEY", "").strip() or os.environ.get("POOF_BG_API_KEY", "").strip()
        if not api_key:
            self.send_json(
                503,
                {
                    "error": "Background removal is not configured. Set REMOVE_BG_API_KEY or POOF_BG_API_KEY in .env file."
                },
            )
            return
        try:
            result, result_type = remove_background(image, content_type, api_key)
        except ImageProcessingError as error:
            self.send_json(502, {"error": str(error)})
            return

        if user:
            with connect_db() as connection:
                connection.execute(
                    "UPDATE users SET fixes_used = fixes_used + 1 WHERE id = ?",
                    (user["id"],),
                )

        self.send_image(result, result_type)

    def review_image_handler(self) -> None:
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type not in IMAGE_TYPES:
            self.send_json(
                415,
                {"error": "Use a JPG, PNG, or WebP image for Gemini review."},
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid image upload."})
            return
        if length < 1 or length > MAX_IMAGE_BYTES:
            self.send_json(400, {"error": "Image must be between 1 byte and 25 MB."})
            return
        image = self.rfile.read(length)
        if len(image) != length:
            self.send_json(
                400, {"error": "Image upload was incomplete. Please try again."}
            )
            return
        marketplace = self.headers.get("X-Marketplace", "").strip().lower()
        if marketplace not in {"amazon", "etsy"}:
            self.send_json(
                400, {"error": "Choose Amazon or Etsy before requesting a review."}
            )
            return
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            self.send_json(
                503,
                {
                    "error": "Gemini review is not configured. Set GEMINI_API_KEY in .env file."
                },
            )
            return
        try:
            review = review_image_with_gemini(
                image, content_type, marketplace, api_key
            )
        except ImageProcessingError as error:
            self.send_json(502, {"error": str(error)})
            return
        self.send_json(200, {"review": review})

    def read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid request body."})
            return None
        if length < 1 or length > 65_536:
            self.send_json(400, {"error": "Request body must be under 64 KB."})
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            self.send_json(415, {"error": "Send this request as JSON."})
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON request body."})
            return None
        if not isinstance(data, dict):
            self.send_json(400, {"error": "Request body must be a JSON object."})
            return None
        return data

    def register(self, data: dict) -> None:
        name = data.get("name")
        email = data.get("email")
        password = data.get("password")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            self.send_json(
                400, {"error": "Name must be between 2 and 100 characters."}
            )
            return
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
            self.send_json(400, {"error": "Enter a valid email address."})
            return
        if not isinstance(password, str) or not 8 <= len(password) <= 1024:
            self.send_json(
                400, {"error": "Password must be at least 8 characters."}
            )
            return

        normalized_email = email.strip().lower()
        if normalized_email == OWNER_EMAIL:
            self.send_json(
                403,
                {
                    "error": "The owner account must be set up by the server administrator."
                },
            )
            return
        salt = secrets.token_bytes(16)
        try:
            with connect_db() as connection:
                if connection.is_pg:
                    res = connection.execute(
                        "INSERT INTO users (name, email, salt, password_hash, created_at) "
                        "VALUES (?, ?, ?, ?, ?) RETURNING id",
                        (
                            name.strip(),
                            normalized_email,
                            salt,
                            password_hash(password, salt),
                            int(time.time()),
                        ),
                    )
                    user_id = res.fetchone()["id"]
                else:
                    cursor = connection.execute(
                        "INSERT INTO users (name, email, salt, password_hash, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            name.strip(),
                            normalized_email,
                            salt,
                            password_hash(password, salt),
                            int(time.time()),
                        ),
                    )
                    user_id = cursor.lastrowid
        except Exception as exc:
            err_str = str(exc).lower()
            if "unique" in err_str or "duplicate" in err_str or "integrity" in err_str:
                self.send_json(
                    409,
                    {
                        "error": "An account with this email already exists. Log in instead."
                    },
                )
                return
            raise
        self.create_session(user_id, 201)

    def login(self, data: dict) -> None:
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
            self.send_json(400, {"error": "Enter a valid email address."})
            return
        if not isinstance(password, str) or not password or len(password) > 1024:
            self.send_json(400, {"error": "Enter your password."})
            return
        with connect_db() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        candidate = password_hash(password, row["salt"] if row else bytes(16))
        if not row or not hmac.compare_digest(candidate, row["password_hash"]):
            self.send_json(401, {"error": "Email or password is not correct."})
            return
        self.create_session(row["id"], 200)

    def create_session(self, user_id: int, status: int) -> None:
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + SESSION_SECONDS
        with connect_db() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),)
            )
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (
                    hashlib.sha256(token.encode("ascii")).hexdigest(),
                    user_id,
                    expires_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        cookie = f"lp_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}"
        self.send_json(status, {"user": public_user(row)}, cookie)

    def current_user(self) -> sqlite3.Row | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("lp_session")
        if morsel is None:
            return None
        token_hash = hashlib.sha256(
            morsel.value.encode("ascii", "ignore")
        ).hexdigest()
        now = int(time.time())
        with connect_db() as connection:
            row = connection.execute(
                "SELECT users.*, sessions.expires_at FROM sessions "
                "JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row and row["expires_at"] <= now:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                )
                return None
            return row

    def logout(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("lp_session")
        if morsel is not None:
            token_hash = hashlib.sha256(
                morsel.value.encode("ascii", "ignore")
            ).hexdigest()
            with connect_db() as connection:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                )
        expired_cookie = "lp_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
        self.send_json(200, {"ok": True}, expired_cookie)


# ── Entry Point ────────────────────────────────────────────────────────────

def main() -> None:
    if sys.argv[1:] == ["--create-owner"]:
        email = input(f"Owner email [{OWNER_EMAIL}]: ").strip() or OWNER_EMAIL
        name = input("Owner name: ").strip()
        password = getpass("Owner password (12+ characters; input hidden): ")
        confirmation = getpass("Confirm owner password: ")
        if password != confirmation:
            raise SystemExit("Passwords did not match; owner account was not changed.")
        initialize_database()
        provision_owner(email, name, password)
        print(f"Admin and Pro owner account configured for {OWNER_EMAIL}.")
        return

    initialize_database()

    # Check for API keys
    has_removebg = bool(os.environ.get("POOF_BG_API_KEY", "").strip() or os.environ.get("REMOVE_BG_API_KEY", "").strip())
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    httpd = ThreadingHTTPServer((HOST, PORT), PreflightHandler)
    print(f"\n{'='*60}")
    print(f"  Fixerpro v2.0 - Better Images. Higher Sales.")
    print(f"{'='*60}")
    print(f"  URL:          http://{HOST}:{httpd.server_port}/")
    print(f"  Database:     {DB_PATH}")
    print(f"  AI Remover:   {'[OK] Configured (Poof.bg/Cloud GPU)' if has_removebg else '[-] Not set (Amazon Fix disabled)'}")
    print(f"  Gemini AI:    {'[OK] Configured' if has_gemini else '[-] Not set (AI Review disabled)'}")
    print(f"  Owner email:  {OWNER_EMAIL}")
    print(f"{'='*60}")
    print(f"  Image checks run in the browser - no API keys needed!")
    print(f"  Set POOF_BG_API_KEY and GEMINI_API_KEY in .env for")
    print(f"  optional background removal and AI review features.")
    print(f"{'='*60}\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Fixerpro.")
    finally:
        httpd.server_close()


handler = PreflightHandler
app = PreflightHandler
application = PreflightHandler


if __name__ == "__main__":
    main()