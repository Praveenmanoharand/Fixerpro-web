# 🚀 Verdict — Production E-Commerce Image Validator & Optimizer

**Developed & Maintained by Praveen** (`praveenmanoharan.dev@gmail.com`)  
**Official Support:** `officialverdictv@gmail.com`  
**Live Production URL:** [https://market-pro-seven.vercel.app/](https://market-pro-seven.vercel.app/)

[![Tests](https://img.shields.io/badge/tests-34%20passed-00d4aa?style=for-the-badge)](file:///d:/MARKET/test_server.py)
[![Database](https://img.shields.io/badge/database-Supabase%20PostgreSQL%20%7C%20SQLite-3ecf8e?style=for-the-badge)](https://supabase.com)
[![Payments](https://img.shields.io/badge/payments-Razorpay%20Standard%20Checkout-0c2340?style=for-the-badge)](https://razorpay.com)
[![Platform](https://img.shields.io/badge/platform-Amazon%20%7C%20Etsy-orange?style=for-the-badge)](file:///d:/MARKET/index.html)

---

## 🌟 Executive Summary

**Verdict** is a high-performance, resilient, production-grade web application engineered for e-commerce sellers on **Amazon** and **Etsy**. It checks listing photos against marketplace standards, automatically fixes background and dimensional issues, provides optional AI visual critiques, allows bulk ZIP export, and includes an end-to-end subscription & payments workflow powered by **Razorpay** and **Supabase**.

---

## 🛡️ Enterprise Security & Privacy Guarantees

### 1. Zero Image Storage in Cloud Database
- **Privacy-First Promise:** Verdict **never** stores product image bytes, thumbnails, or raw visual files in any cloud database or server disk.
- All checks, cropping, scaling, and canvas analyses occur **ephemerally in the seller's browser**.
- Upstream background removals via remove.bg and AI visual critiques via Gemini are handled in-memory and discarded immediately after response transmission.

### 2. High-Grade Authentication & PBKDF2 Password Hashing
- User passwords are protected using **PBKDF2-HMAC-SHA256 with 600,000 rounds** and cryptographically secure 16-byte random salts.
- Sessions are stored in the database as single-way SHA256 hashes and delivered via **HttpOnly, SameSite=Lax** cookies, defending against Cross-Site Scripting (XSS) and token theft.

### 3. Payment Security & HMAC SHA256 Verification
- Client-side checkout interacts directly with **Razorpay Checkout SDK**. Sensitive card numbers and UPI credentials never touch our application server.
- The backend verifies payment callbacks by comparing server-generated HMAC SHA256 signatures against `razorpay_signature` using timing-safe constant-time string comparisons (`hmac.compare_digest`).

### 4. Sliding-Window Rate Limiting & DoS Defense
- IP-based token-bucket rate limiter throttles burst requests at 30 requests/minute.
- Automatic `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and strict referrer policy headers are injected into every HTTP response.

---

## 🗄️ Database Architecture (Dual-Mode)

Verdict incorporates a unified database wrapper supporting both cloud and offline development:

1. **Production (Supabase PostgreSQL):**
   - Connects using Supabase's IPv4 **Session Pooler** on port `6543` (`aws-0-ap-southeast-2.pooler.supabase.com`).
   - Handles serverless function cold-starts smoothly without IPv6 timeout bottlenecks.
2. **Local Fallback (SQLite):**
   - Operates in WAL (Write-Ahead Logging) mode when offline or without `DATABASE_URL`.
   - Automatic migrations ensure tables (`users`, `sessions`) and columns (`role`, `fixes_used`, `plan_expires_at`) exist without manual intervention.

---

## 💎 Pricing, Subscriptions & 30-Day Plan Lifecycle

- **Free Tier:**
  - 5 checks per batch.
  - 5 automated Amazon fixes.
  - Pricing page highlights `✓ Your Current Plan`.
- **Pro Tier (₹499 / $9):**
  - Up to 200 images per batch.
  - Unlimited automated fixes.
  - CSV reports and email support.
  - Dynamic UI indicator: `✓ Active Plan · 30 days remaining`.
  - Automatic expiration: When `current_time > plan_expires_at`, account gracefully returns to Free tier without disruption.

---

## 📬 Direct Contact Form (SMTP SSL/TLS)

- Rather than forcing users into external mail apps via `mailto:`, the contact page posts directly to `/api/contact`.
- Utilizes Python's `smtplib` over port `587` with TLS encryption.
- Delivers buyer messages straight to `officialverdictv@gmail.com` with the sender's email configured in the `Reply-To` header for 1-click email replies.

---

## 🧪 Testing & Verification

Run the full automated test suite (34 tests):
```cmd
python test_server.py
```

Expected output:
```text
Ran 34 tests in ~4.6s
OK
```

Detailed test scenario descriptions and audit items are maintained in [TEST_CASES.md](file:///d:/MARKET/TEST_CASES.md).

---

## ⚙️ Environment Variables Reference (`.env.example`)

```env
# Optional External API Keys
GEMINI_API_KEY=your_gemini_api_key_here
REMOVE_BG_API_KEY=your_remove_bg_api_key_here

# Supabase Cloud Database (IPv4 Pooler port 6543)
DATABASE_URL=postgresql://postgres.your_project_id:your_password@aws-0-region.pooler.supabase.com:6543/postgres

# Razorpay Payment Gateway (Test or Live)
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
PRO_PLAN_PRICE=499

# Contact Form Gmail SMTP Credentials
SMTP_EMAIL=your_support_email@gmail.com
SMTP_APP_PASSWORD=your_gmail_16_digit_app_password
```

---

## 🚀 Deployment & Operations

### Local Development:
Double-click `start.bat` or run:
```cmd
python server.py
```
App runs at `http://127.0.0.1:8000/`.

### Pushing Updates to Production:
Double-click `push_to_github.bat` to push to `https://github.com/Praveenmanoharand/MarketPro.git`. Vercel will automatically build and deploy the updated code to `https://market-pro-seven.vercel.app/`.