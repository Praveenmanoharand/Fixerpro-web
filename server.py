"""
ListingPreflight — Production-ready backend server.
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
from getpass import getpass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Generator
from urllib.parse import unquote, urlsplit

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
    """Send image to remove.bg and return the result PNG."""
    boundary = secrets.token_hex(16)
    body = b"".join(
        (
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="image_file"; filename="product-image"\r\n',
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            image,
            b"\r\n",
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="size"\r\n\r\nauto\r\n',
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="format"\r\n\r\npng\r\n',
            f"--{boundary}--\r\n".encode("ascii"),
        )
    )
    request = urllib.request.Request(
        REMOVE_BG_URL,
        data=body,
        headers={
            "X-Api-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = response.read(MAX_IMAGE_BYTES + 1)
            result_type = response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        if error.code in (402, 429):
            raise ImageProcessingError(
                "remove.bg plan credits or request limit reached. Check your remove.bg account."
            ) from error
        if error.code in (401, 403):
            raise ImageProcessingError(
                "remove.bg rejected the API key. Check REMOVE_BG_API_KEY in .env."
            ) from error
        if error.code in (400, 413):
            raise ImageProcessingError(
                "remove.bg could not process this image. Check format and size."
            ) from error
        raise ImageProcessingError(
            f"remove.bg is temporarily unavailable (HTTP {error.code})."
        ) from error
    except urllib.error.URLError as error:
        raise ImageProcessingError(
            "Could not connect to remove.bg. Check your internet connection."
        ) from error
    except TimeoutError as error:
        raise ImageProcessingError(
            "Background removal timed out. Try a smaller image."
        ) from error
    if len(result) > MAX_IMAGE_BYTES:
        raise ImageProcessingError("Processed image exceeded the 25 MB limit.")
    if not result or result_type != "image/png":
        raise ImageProcessingError(
            "remove.bg returned an unexpected result. Check your API key."
        )
    return result, result_type


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

@contextmanager
def connect_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections with WAL mode."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    """Create tables and ensure schema is up to date."""
    with connect_db() as connection:
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
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if "role" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
            )
        connection.execute(
            "UPDATE users SET plan='pro', role='admin' WHERE lower(email)=?",
            (OWNER_EMAIL,),
        )


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )


def public_user(row: sqlite3.Row) -> dict[str, str]:
    return {
        "name": row["name"],
        "email": row["email"],
        "plan": row["plan"],
        "role": row["role"],
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
    server_version = "ListingPreflight/2.0"

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
        # Rate limiting
        client_ip = self.address_string()
        if rate_limited(client_ip):
            self.send_json(429, {"error": "Too many requests. Please slow down."})
            return

        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host") and not os.environ.get("VERCEL"):
            self.send_json(403, {"error": "Cross-origin requests are not allowed."})
            return

        path = unquote(urlsplit(self.path).path)
        if not path.startswith("/api/"):
            if path.startswith("/image/") or path in ("/register", "/login", "/logout", "/forgot"):
                path = "/api" + path
            else:
                self.send_json(404, {"error": "Not found."})
                return

        if path == "/api/logout":
            self.logout()
            return
        if path == "/api/image/remove-background":
            self.remove_background_handler()
            return
        if path == "/api/image/review":
            self.review_image_handler()
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

    def remove_background_handler(self) -> None:
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
        api_key = os.environ.get("REMOVE_BG_API_KEY", "").strip()
        if not api_key:
            self.send_json(
                503,
                {
                    "error": "Background removal is not configured. Set REMOVE_BG_API_KEY in .env file."
                },
            )
            return
        try:
            result, result_type = remove_background(image, content_type, api_key)
        except ImageProcessingError as error:
            self.send_json(502, {"error": str(error)})
            return
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
        except sqlite3.IntegrityError:
            self.send_json(
                409,
                {
                    "error": "An account with this email already exists. Log in instead."
                },
            )
            return
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
    has_removebg = bool(os.environ.get("REMOVE_BG_API_KEY", "").strip())
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    httpd = ThreadingHTTPServer((HOST, PORT), PreflightHandler)
    print(f"\n{'='*60}")
    print(f"  ListingPreflight v2.0 - Production Ready")
    print(f"{'='*60}")
    print(f"  URL:          http://{HOST}:{httpd.server_port}/")
    print(f"  Database:     {DB_PATH}")
    print(f"  remove.bg:    {'[OK] Configured' if has_removebg else '[-] Not set (Amazon Fix disabled)'}")
    print(f"  Gemini AI:    {'[OK] Configured' if has_gemini else '[-] Not set (AI Review disabled)'}")
    print(f"  Owner email:  {OWNER_EMAIL}")
    print(f"{'='*60}")
    print(f"  Image checks run in the browser - no API keys needed!")
    print(f"  Set REMOVE_BG_API_KEY and GEMINI_API_KEY in .env for")
    print(f"  optional background removal and AI review features.")
    print(f"{'='*60}\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ListingPreflight.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()