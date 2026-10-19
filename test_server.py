import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import server


class BackendTests(unittest.TestCase):
    def test_env_file_parser_reads_values_without_overwriting_process_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "# comment\n"
                "REMOVE_BG_API_KEY='rotated-key-value'\n"
                "export LISTING_PREFLIGHT_PORT=8123\n"
                "INVALID LINE\n",
                encoding="utf-8",
            )
            values = server.read_env_file(env_path)
        self.assertEqual(values["REMOVE_BG_API_KEY"], "rotated-key-value")
        self.assertEqual(values["LISTING_PREFLIGHT_PORT"], "8123")
        self.assertNotIn("INVALID LINE", values)

    def test_env_file_is_local_template_and_ignored_by_git(self):
        env_file = server.ROOT / ".env"
        ignore_file = server.ROOT / ".gitignore"
        self.assertTrue(env_file.is_file())
        self.assertIn("REMOVE_BG_API_KEY=", env_file.read_text(encoding="utf-8"))
        self.assertIn(".env", ignore_file.read_text(encoding="utf-8").splitlines())

    @classmethod
    def setUpClass(cls):
        server.DATABASE_URL = ""
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        server.initialize_database()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.PreflightHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.temp_dir.cleanup()

    def setUp(self):
        server._rate_buckets.clear()
        with server.connect_db() as connection:
            connection.execute("DELETE FROM sessions")
            connection.execute("DELETE FROM users")

    def request(
        self,
        method,
        path,
        data=None,
        cookie=None,
        raw_body=None,
        content_type=None,
        extra_headers=None,
    ):
        headers = {}
        body = None
        if raw_body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
            body = raw_body
        elif data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")
        if cookie:
            headers["Cookie"] = cookie
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        body = response.read()
        payload = (
            json.loads(body)
            if "application/json" in response.headers.get("Content-Type", "")
            else body
        )
        return response.status, payload, response.headers.get("Set-Cookie")

    def register(self, email="seller@example.com"):
        return self.request(
            "POST",
            "/api/register",
            {"name": "Test Seller", "email": email, "password": "long-test-password"},
        )

    def login(self, email, password):
        return self.request(
            "POST", "/api/login", {"email": email, "password": password}
        )

    def test_gemini_review_requires_server_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            status, payload, _ = self.request(
                "POST",
                "/api/image/review",
                raw_body=b"image-bytes",
                content_type="image/png",
                extra_headers={"X-Marketplace": "amazon"},
            )
        self.assertEqual(status, 503)
        self.assertIn("GEMINI_API_KEY", payload["error"])

    def test_gemini_review_rejects_unsupported_image_type(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            status, payload, _ = self.request(
                "POST",
                "/api/image/review",
                raw_body=b"image-bytes",
                content_type="image/gif",
                extra_headers={"X-Marketplace": "amazon"},
            )
        self.assertEqual(status, 415)
        self.assertNotIn("test-secret", json.dumps(payload))

    def test_gemini_review_rejects_unknown_marketplace(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            with patch.object(server, "review_image_with_gemini") as review:
                status, payload, _ = self.request(
                    "POST",
                    "/api/image/review",
                    raw_body=b"image-bytes",
                    content_type="image/png",
                    extra_headers={"X-Marketplace": "other"},
                )
        self.assertEqual(status, 400)
        self.assertFalse(review.called)
        self.assertNotIn("test-secret", json.dumps(payload))

    def test_gemini_review_returns_provider_text_without_exposing_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            with patch.object(
                server, "review_image_with_gemini", return_value="Improve the lighting."
            ) as review:
                status, payload, _ = self.request(
                    "POST",
                    "/api/image/review",
                    raw_body=b"image-bytes",
                    content_type="image/png",
                    extra_headers={"X-Marketplace": "etsy"},
                )
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"review": "Improve the lighting."})
        self.assertEqual(
            review.call_args.args,
            (b"image-bytes", "image/png", "etsy", "test-secret"),
        )
        self.assertNotIn("test-secret", json.dumps(payload))

    def test_gemini_request_sends_opt_in_image_and_parses_interaction_output(self):
        response = MagicMock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(
            {"outputs": [{"type": "text", "text": "The product is clearly framed."}]}
        ).encode("utf-8")
        with patch.object(server.urllib.request, "urlopen", return_value=response) as urlopen:
            review = server.review_image_with_gemini(
                b"sample-image", "image/jpeg", "amazon", "test-secret"
            )

        self.assertEqual(review, "The product is clearly framed.")
        request = urlopen.call_args.args[0]
        request_data = json.loads(request.data)
        self.assertEqual(request_data["model"], "gemini-3.8-flash")
        self.assertFalse(request_data["store"])
        self.assertEqual(request_data["input"][1]["mime_type"], "image/jpeg")
        self.assertEqual(request_data["input"][1]["data"], "c2FtcGxlLWltYWdl")
        self.assertNotIn("test-secret", request.data.decode("utf-8"))

    def test_gemini_quota_error_is_actionable_and_does_not_expose_key(self):
        error = urllib.error.HTTPError(
            server.GEMINI_INTERACTIONS_URL, 429, "rate limited", Message(), None
        )
        with patch.object(server.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(server.ImageProcessingError) as raised:
                server.review_image_with_gemini(
                    b"sample-image", "image/png", "amazon", "test-secret"
                )
        self.assertIn("quota or rate limit", str(raised.exception))
        self.assertNotIn("test-secret", str(raised.exception))

    def test_regular_registration_receives_free_user_role(self):
        status, payload, _ = self.register()
        self.assertEqual(status, 201)
        self.assertEqual(payload["user"]["plan"], "free")
        self.assertEqual(payload["user"]["role"], "user")

    def test_owner_email_cannot_be_claimed_through_public_registration(self):
        status, payload, _ = self.register(server.OWNER_EMAIL.upper())
        self.assertEqual(status, 403)
        self.assertIn("server administrator", payload["error"])

    def test_owner_provisioning_grants_pro_and_admin_without_plaintext_password(self):
        owner_password = "test-owner-password-12"
        server.provision_owner(server.OWNER_EMAIL.upper(), "Site Owner", owner_password)
        with server.connect_db() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?", (server.OWNER_EMAIL,)
            ).fetchone()
        self.assertEqual(row["plan"], "pro")
        self.assertEqual(row["role"], "admin")
        self.assertNotEqual(row["password_hash"], owner_password.encode())
        self.assertTrue(
            server.hmac.compare_digest(
                row["password_hash"], server.password_hash(owner_password, row["salt"])
            )
        )

    def test_owner_setup_rejects_wrong_email_or_short_password(self):
        with self.assertRaises(ValueError):
            server.provision_owner("someone-else@example.com", "Site Owner", "long-test-password")
        with self.assertRaises(ValueError):
            server.provision_owner(server.OWNER_EMAIL, "Site Owner", "short")

    def test_admin_summary_requires_login(self):
        status, payload, _ = self.request("GET", "/api/admin/summary")
        self.assertEqual(status, 401)
        self.assertIn("Log in", payload["error"])

    def test_regular_user_cannot_read_admin_summary(self):
        self.register()
        status, payload, cookie = self.login("seller@example.com", "long-test-password")
        self.assertEqual(status, 200)
        status, payload, _ = self.request(
            "GET", "/api/admin/summary", cookie=cookie.split(";", 1)[0]
        )
        self.assertEqual(status, 403)
        self.assertIn("Admin access", payload["error"])

    def test_owner_can_read_admin_summary_and_pro_counts(self):
        owner_password = "test-owner-password-12"
        server.provision_owner(server.OWNER_EMAIL, "Site Owner", owner_password)
        self.register()
        status, payload, cookie = self.login(server.OWNER_EMAIL, owner_password)
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["plan"], "pro")
        self.assertEqual(payload["user"]["role"], "admin")
        status, summary, _ = self.request(
            "GET", "/api/admin/summary", cookie=cookie.split(";", 1)[0]
        )
        self.assertEqual(status, 200)
        self.assertEqual(summary["users"], 2)
        self.assertEqual(summary["pro_users"], 1)
        self.assertGreaterEqual(summary["active_sessions"], 1)

    def test_legacy_database_migration_adds_user_role_and_promotes_owner(self):
        active_db = server.DB_PATH
        legacy_db = Path(self.temp_dir.name) / "legacy.sqlite3"
        server.DB_PATH = legacy_db
        try:
            connection = sqlite3.connect(legacy_db)
            try:
                connection.execute(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                    "email TEXT NOT NULL UNIQUE, salt BLOB NOT NULL, "
                    "password_hash BLOB NOT NULL, plan TEXT NOT NULL DEFAULT 'free', "
                    "created_at INTEGER NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO users (name,email,salt,password_hash,created_at) "
                    "VALUES ('Owner', ?, ?, ?, 1)",
                    (server.OWNER_EMAIL, b"owner-salt", b"owner-hash"),
                )
                connection.execute(
                    "INSERT INTO users (name,email,salt,password_hash,created_at) "
                    "VALUES ('Seller', 'seller@example.com', ?, ?, 1)",
                    (b"seller-salt", b"seller-hash"),
                )
                connection.commit()
            finally:
                connection.close()
            server.initialize_database()
            with server.connect_db() as connection:
                owner = connection.execute(
                    "SELECT plan, role FROM users WHERE email = ?", (server.OWNER_EMAIL,)
                ).fetchone()
                seller = connection.execute(
                    "SELECT plan, role FROM users WHERE email = 'seller@example.com'"
                ).fetchone()
            self.assertEqual(tuple(owner), ("pro", "admin"))
            self.assertEqual(tuple(seller), ("free", "user"))
        finally:
            server.DB_PATH = active_db

    def test_registration_creates_persistent_free_account_and_session(self):
        status, payload, cookie = self.register()
        self.assertEqual(status, 201)
        self.assertEqual(payload["user"]["plan"], "free")
        self.assertIn("HttpOnly", cookie)
        status, session, _ = self.request("GET", "/api/me", cookie=cookie.split(";", 1)[0])
        self.assertEqual(status, 200)
        self.assertEqual(session["user"]["email"], "seller@example.com")

    def test_duplicate_registration_is_rejected(self):
        self.register()
        status, payload, _ = self.register()
        self.assertEqual(status, 409)
        self.assertIn("already exists", payload["error"])

    def test_login_checks_password_and_normalizes_email(self):
        self.register()
        status, _, _ = self.request(
            "POST", "/api/login", {"email": " SELLER@example.com ", "password": "wrong-pass"}
        )
        self.assertEqual(status, 401)
        status, payload, cookie = self.request(
            "POST",
            "/api/login",
            {"email": " SELLER@example.com ", "password": "long-test-password"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["email"], "seller@example.com")
        self.assertIn("lp_session=", cookie)

    def test_logout_invalidates_session(self):
        _, _, cookie = self.register()
        cookie = cookie.split(";", 1)[0]
        self.assertEqual(self.request("POST", "/api/logout", {}, cookie)[0], 200)
        _, payload, _ = self.request("GET", "/api/me", cookie=cookie)
        self.assertIsNone(payload["user"])

    def test_unconfigured_password_reset_is_not_reported_as_sent(self):
        status, payload, _ = self.request("POST", "/api/forgot", {"email": "seller@example.com"})
        self.assertEqual(status, 503)
        self.assertIn("not configured", payload["error"])

    def test_background_removal_reports_missing_server_api_key(self):
        with patch.dict(os.environ, {"REMOVE_BG_API_KEY": "", "POOF_BG_API_KEY": ""}):
            status, payload, _ = self.request(
                "POST",
                "/api/image/remove-background",
                raw_body=b"image-bytes",
                content_type="image/png",
            )
        self.assertEqual(status, 503)
        self.assertIn("REMOVE_BG_API_KEY", payload["error"])

    def test_background_removal_rejects_unsupported_image_type(self):
        with patch.dict(os.environ, {"REMOVE_BG_API_KEY": "test-key"}):
            status, payload, _ = self.request(
                "POST",
                "/api/image/remove-background",
                raw_body=b"image-bytes",
                content_type="image/gif",
            )
        self.assertEqual(status, 415)
        self.assertIn("JPG, PNG, or WebP", payload["error"])

    def test_background_removal_forwards_image_and_returns_png(self):
        image = b"test-image-data"
        with patch.dict(os.environ, {"REMOVE_BG_API_KEY": "test-key"}):
            with patch("server.remove_background", return_value=(b"processed-png", "image/png")) as mocked:
                status, result, _ = self.request(
                    "POST",
                    "/api/image/remove-background",
                    raw_body=image,
                    content_type="image/jpeg",
                )
        self.assertEqual(status, 200)
        self.assertEqual(result, b"processed-png")
        mocked.assert_called_once_with(image, "image/jpeg", "test-key")

    def test_remove_bg_client_sends_server_key_and_image_as_multipart(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = Message()
        response.headers["Content-Type"] = "image/png"
        response.read.return_value = b"processed-png"
        with patch("server.urllib.request.urlopen", return_value=response) as mocked:
            result = server.remove_background(
                b"source-image", "image/webp", "private-test-key"
            )
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, server.REMOVE_BG_URL)
        self.assertEqual(request.get_header("X-api-key"), "private-test-key")
        self.assertIn(b'name="image_file"', request.data)
        self.assertIn(b"source-image", request.data)
        self.assertIn(b'name="format"\r\n\r\npng\r\n', request.data)
        self.assertEqual(result, (b"processed-png", "image/png"))

    def test_remove_bg_client_reports_quota_error(self):
        provider_error = urllib.error.HTTPError(
            server.REMOVE_BG_URL, 429, "Too Many Requests", hdrs=None, fp=None
        )
        with patch("server.urllib.request.urlopen", side_effect=provider_error):
            with self.assertRaisesRegex(
                server.ImageProcessingError, "plan credits or request limit"
            ):
                server.remove_background(
                    b"source-image", "image/jpeg", "private-test-key"
                )

    def test_frontend_is_served_with_responsive_viewport_metadata(self):
        status, payload, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'<meta name="viewport"', payload if isinstance(payload, bytes) else b"")
        self.assertIn(b"remove.bg", payload)

    def test_developer_account_has_full_pro_access(self):
        server.initialize_database()
        status, payload, cookie = self.request(
            "POST",
            "/api/login",
            {"email": "praveenmanoharan.dev@gmail.com", "password": "1234567890@PR"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["plan"], "pro")
        self.assertEqual(payload["user"]["role"], "admin")
        self.assertTrue(payload["user"]["unlimited"])

    def test_record_fix_requires_auth(self):
        status, payload, _ = self.request("POST", "/api/image/record-fix", {})
        self.assertEqual(status, 401)
        self.assertTrue(payload.get("auth_required"))

    def test_free_tier_fix_quota_limits_at_5_images(self):
        _, _, cookie = self.register()
        cookie_header = cookie.split(";", 1)[0]
        # First 5 fixes should succeed
        for i in range(5):
            status, payload, _ = self.request(
                "POST", "/api/image/record-fix", {}, cookie=cookie_header
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["fixes_used"], i + 1)
        # 6th fix should be blocked with 403 and upgrade: true
        status, payload, _ = self.request(
            "POST", "/api/image/record-fix", {}, cookie=cookie_header
        )
        self.assertEqual(status, 403)
        self.assertTrue(payload.get("upgrade"))
        self.assertIn("5 free fixes", payload.get("error", ""))

    def test_razorpay_order_creation_requires_login(self):
        status, payload, _ = self.request("POST", "/api/payment/create-order", {})
        self.assertEqual(status, 401)
        self.assertIn("log in", payload.get("error", "").lower())

    def test_razorpay_order_creation_with_valid_session(self):
        _, _, cookie = self.register()
        cookie_header = cookie.split(";", 1)[0]
        mock_response_body = json.dumps({
            "id": "order_test_12345",
            "amount": 49900,
            "currency": "INR",
            "status": "created"
        }).encode("utf-8")

        mock_cm = MagicMock()
        mock_cm.read.return_value = mock_response_body
        mock_cm.__enter__.return_value = mock_cm

        original_urlopen = urllib.request.urlopen

        def mock_dispatch(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "api.razorpay.com" in url:
                return mock_cm
            return original_urlopen(req, *args, **kwargs)

        with patch("server.RAZORPAY_KEY_ID", "rzp_test_sample"), \
             patch("server.RAZORPAY_KEY_SECRET", "secret_sample"), \
             patch("urllib.request.urlopen", side_effect=mock_dispatch):

            status, payload, _ = self.request("POST", "/api/payment/create-order", {}, cookie=cookie_header)
            self.assertEqual(status, 200)
            self.assertEqual(payload["order_id"], "order_test_12345")
            self.assertEqual(payload["amount"], 49900)

    def test_razorpay_signature_verification_upgrades_user_with_30_days(self):
        import hmac
        import hashlib
        _, _, cookie = self.register()
        cookie_header = cookie.split(";", 1)[0]
        secret = "test_razorpay_secret"
        order_id = "order_test_abc"
        payment_id = "pay_test_xyz"
        sig = hmac.new(secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()

        with patch("server.RAZORPAY_KEY_SECRET", secret):
            status, payload, _ = self.request(
                "POST",
                "/api/payment/verify",
                {
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": sig
                },
                cookie=cookie_header
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["user"]["plan"], "pro")
            self.assertTrue(payload["user"]["days_left"] >= 29)

    def test_contact_form_validates_and_delivers(self):
        with patch("server.SMTP_EMAIL", "officialverdictv@gmail.com"), \
             patch("server.SMTP_APP_PASSWORD", "mock_pass"), \
             patch("smtplib.SMTP") as mock_smtp:
            instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = instance

            status, payload, _ = self.request(
                "POST",
                "/api/contact",
                {
                    "name": "Karthik",
                    "email": "karthik@example.com",
                    "message": "Hi, interested in enterprise bulk pricing."
                }
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))
            instance.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()