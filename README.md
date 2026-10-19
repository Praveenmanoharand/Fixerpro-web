# 🚀 Fixerpro — Production E-Commerce Image Validator & Studio Optimizer

**Better Images. Higher Sales.**  
**Developed & Maintained by Praveen** (`praveenmanoharan.dev@gmail.com`)  
**Official Support:** `officialverdictv@gmail.com`  
**Live Production URL:** [https://market-pro-seven.vercel.app/](https://market-pro-seven.vercel.app/)

[![Tests](https://img.shields.io/badge/tests-34%20passed-00d4aa?style=for-the-badge)](file:///d:/MARKET/test_server.py)
[![Database](https://img.shields.io/badge/database-Supabase%20PostgreSQL%20%7C%20SQLite-3ecf8e?style=for-the-badge)](https://supabase.com)
[![Payments](https://img.shields.io/badge/payments-Razorpay%20Verified%20Live-0c2340?style=for-the-badge)](https://razorpay.com)
[![AI Engine](https://img.shields.io/badge/AI%20Engine-Poof.bg%20Cloud%20GPU%20%2B%20Remove.bg-7928ca?style=for-the-badge)](https://poof.bg)
[![Platform](https://img.shields.io/badge/platform-Amazon%20%7C%20Etsy-orange?style=for-the-badge)](file:///d:/MARKET/index.html)

---

## 🌟 Executive Summary

**Fixerpro** is an enterprise-grade, privacy-first image validation and studio-enhancement suite engineered specifically for e-commerce merchants selling on **Amazon** and **Etsy**. 

It validates listing photos against strict marketplace guidelines, automatically fixes backgrounds into **Amazon-compliant pure white canvases (#FFFFFF)** using GPU-accelerated cloud AI, delivers optional Gemini visual critiques, enables bulk ZIP downloads, and features an end-to-end subscription & checkout workflow powered by **Razorpay** (verified live) and **Supabase**.

---

## 🛡️ Enterprise Security & Strict Privacy Architecture

### 1. Zero Image Storage & Ephemeral Memory Guarantee
- **Strict Seller Privacy:** Fixerpro **never stores, logs, or writes product image bytes or thumbnails to disk, database, or external object storage**.
- All dimension checks, cropping, alpha-channel inspections, aspect ratio checks, and pure white canvas generations execute **ephemerally inside the merchant's browser memory (HTML5 Canvas)**.
- Upstream background removals via **Poof.bg GPU Cloud** (or remove.bg fallback) are streamed through Python in-memory buffers (`BytesIO`) and discarded immediately upon response delivery.

### 2. High-Entropy Authentication & PBKDF2 Password Hashing
- User passwords are protected using **PBKDF2-HMAC-SHA256 with 310,000 to 600,000 rounds** and cryptographically secure random 16-byte salts generated via `secrets.token_bytes()`.
- Session tokens are stored in the database exclusively as **SHA-256 digests** (single-way hash) and transported in **HttpOnly, SameSite=Lax** cookies, providing defense against Cross-Site Scripting (XSS) and token harvesting.

### 3. Payment Security & Real-Time HMAC-SHA256 Verification
- Merchant payment flow runs via **Razorpay Standard Checkout SDK**. Sensitive credit card numbers, CVVs, and UPI pins never enter or touch our application server.
- The server verifies payment authenticity using constant-time string comparison (`hmac.compare_digest`) against server-generated HMAC-SHA256 signatures of `order_id|payment_id` using the secret key.

### 4. Zero Secret Leakage & Sanitized Public Repositories
- All production credentials, database URLs, SMTP passwords, and API keys are strictly confined to `.env` (guarded by `.gitignore`).
- Git commit histories, client-side JavaScript bundles, and API response payloads are sanitized against secret exposure.

### 5. DDoS Protection & Defensive HTTP Headers
- Built-in token bucket sliding-window rate limiter restricts burst traffic to **30 requests per minute per IP**.
- Every HTTP response automatically injects protective headers:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`

---

## 🗄️ Database Architecture (Dual-Mode Resilient Engine)

Fixerpro features a unified database abstraction layer supporting both production cloud databases and offline local development:

1. **Production (Supabase PostgreSQL):**
   - Connects using Supabase's IPv4 **Session Pooler** on port `6543` (`aws-0-ap-southeast-2.pooler.supabase.com`).
   - Completely resolves serverless cold-start bottlenecks and IPv6 routing limits on Vercel.
2. **Local Fallback (SQLite):**
   - Automatically activates offline or when `DATABASE_URL` is omitted, operating in WAL (Write-Ahead Logging) mode.
   - Self-healing migrations ensure schema consistency across versions without downtime.

---

## 💎 Pricing, Quotas & Subscription Lifecycle

- **Free Tier:**
  - 5 checks per batch.
  - 5 automated Amazon Studio White fixes.
  - Clear real-time status: `✓ Your Current Plan`.
- **Pro Tier (₹499 / $9):**
  - Up to 200 images per batch.
  - Unlimited automated background fixes and studio optimizations.
  - CSV reports and direct email support.
  - Dynamic UI indicator: `✓ Active Plan · 30 days remaining`.
  - Automatic grace period & lifecycle: Accounts gracefully revert to Free upon plan expiration without losing account settings.

---

## ⚡ Background Removal Providers (Poof.bg + remove.bg)

Fixerpro integrates a resilient dual-provider architecture for background removal:
- **Primary Engine (Poof.bg GPU Cloud AI):**
  - ~1.5-second processing time with fine edge detection for complex product photos.
  - Output is auto-composed onto a **pure white #FFFFFF Amazon-standard canvas** with 85% optimal product fill.
- **Secondary Engine (remove.bg):**
  - Automatic fallback handler if configured in `.env`.

---

## 🧪 Automated Test Suite (34 / 34 Tests Pass)

Execute the comprehensive automated test suite anytime:
```cmd
python test_server.py
```

Expected output:
```text
Ran 34 tests in ~4.7s
OK
```

All 34 test scenarios, threat models, and verification steps are documented in [TEST_CASES.md](file:///d:/MARKET/TEST_CASES.md).

---

## ⚙️ Environment Variables Reference (`.env`)

```env
# AI & Image Processing
POOF_BG_API_KEY=your_poof_bg_api_key_here
REMOVE_BG_API_KEY=your_remove_bg_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Cloud Database (Supabase PostgreSQL Pooler)
DATABASE_URL=postgresql://user:password@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres

# Razorpay Payments (Live / Test)
RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxx
PRO_PLAN_PRICE=499

# Direct Support Email (SMTP)
SMTP_EMAIL=officialverdictv@gmail.com
SMTP_APP_PASSWORD=your_gmail_app_password_here
```