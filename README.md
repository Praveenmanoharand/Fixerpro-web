# 🚀 ListingPreflight — Production-Ready Amazon & Etsy Image Validator & Optimizer

**Developed & Maintained by Praveen**

[![Tests](https://img.shields.io/badge/tests-27%20passed-00d4aa?style=for-the-badge)](file:///d:/MARKET/test_server.py)
[![Architecture](https://img.shields.io/badge/frontend-Zero--Dependency%20SPA-blue?style=for-the-badge)](file:///d:/MARKET/index.html)
[![Backend](https://img.shields.io/badge/backend-Python%20ThreadingHTTPServer-brightgreen?style=for-the-badge)](file:///d:/MARKET/server.py)
[![Platform](https://img.shields.io/badge/platform-Amazon%20%7C%20Etsy-orange?style=for-the-badge)](file:///d:/MARKET/index.html)

---

## 🌟 Executive Summary

**ListingPreflight** is a high-performance, resilient, production-ready web application engineered for e-commerce sellers on **Amazon** and **Etsy**. It validates listing photos against marketplace standards, automatically fixes background and dimensional issues, provides optional AI visual critiques, and allows bulk ZIP export — all with a sleek, ultra-responsive modern UI.

---

## ✨ Key Features & Architecture

### 1. 🛡️ High-Traffic Resilient Server Architecture
- **Multi-Threaded Server**: Powered by Python's built-in `ThreadingHTTPServer` to handle concurrent user traffic without blocking or crashing.
- **Sliding-Window Rate Limiter**: IP-based rate limiting (30 requests/minute default) prevents abuse, scraping, and DoS spikes.
- **Robust SQLite Database with WAL Mode**: `listingpreflight.sqlite3` operates with Write-Ahead Logging (WAL) and automatic rollback context managers, preventing database locks during simultaneous writes.
- **Stateless Zero-Key Browser Validation**: Core image checking (aspect ratios, minimum/maximum resolutions, sRGB/RGB color profile, pure white background detection, product fill percentage) runs **directly inside the client's browser using HTML5 Canvas & TypedArrays**. Even under thousands of concurrent users, the server load for inspections remains virtually zero.

### 2. 🎨 Premium UI & Wow Design Aesthetics
- **Dark Neon Glassmorphism**: Tailored HSL palette with rich slate backgrounds (`#0a0f1a`), vibrant cyber-mint accents (`#00d4aa`), glass backdrop filters, and subtle ambient glows.
- **Light / Dark Mode Switcher**: Seamless theme switcher that persists across visits.
- **Fluid Micro-Animations**:
  - Scanning radar beam and corner targeting animations while analyzing photos.
  - Interactive status badges with spring physics bounces.
  - Smooth loading spinners and button transitions on **Fix**, **Check**, and **AI Review**.
- **Interactive Lightbox Preview**: Click any thumbnail to trigger the cinematic fullscreen preview modal with keyboard navigation (Esc to exit, Arrow keys to navigate, before/after toggle).
- **Animated 404 Experience**: Interactive particle physics animation for missing routes with instant recovery links.
- **Toast & Error Animations**: Shaking, glowing alert banners for actionable error notifications.

### 3. 🔑 Intelligent API Key Management (Browser-First & Optional)
- **Do Users Need an API Key?**
  - **NO!** Image inspections, validation results, Etsy auto-resizing, and ZIP downloads work **100% out of the box without any API keys or configuration**.
- **When are API Keys Used?**
  - **Amazon Background Removal**: Uses `remove.bg` API.
  - **Gemini AI Critique**: Uses Google's `gemini-3.8-flash` Interactions API.
- **Secure Server-Side Configuration**:
  - Sellers never expose API keys on the frontend or network requests.
  - The server reads `REMOVE_BG_API_KEY` and `GEMINI_API_KEY` securely from `.env`.
  - If a key is missing, the application does not crash; instead, it provides friendly, helpful instructions on how to enable that specific optional feature.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+ (Standard library only; **no external pip packages required**!)

### 1. Start the Server
On Windows, you can simply run:
```powershell
start.bat
```
Or directly from PowerShell:
```powershell
python server.py
```
The server will boot up and bind to:
👉 **`http://127.0.0.1:8000/`**

### 2. Stop the Server
```powershell
stop.bat
```

### 3. Run Automated Unit Tests
To verify all 27 unit tests pass:
```powershell
python -m unittest test_server.py
```
*(All 27 test cases pass with 100% success!)*

---

## ⚙️ Configuration & Environment (.env)

The server automatically loads configuration from `.env`:

```env
# Server Binding
LISTING_PREFLIGHT_HOST=127.0.0.1
LISTING_PREFLIGHT_PORT=8000

# Database path (optional, defaults to listingpreflight.sqlite3)
LISTING_PREFLIGHT_DB=listingpreflight.sqlite3

# Owner / Admin Email (receives Pro & Admin capabilities)
LISTING_PREFLIGHT_OWNER_EMAIL=praveenmanoharan.dev@gmail.com

# Optional Third-Party Services
REMOVE_BG_API_KEY=your_remove_bg_api_key_here
GEMINI_API_KEY=your_google_gemini_api_key_here
```

> **Security Note:** `.env` is listed in `.gitignore`. Never commit API keys to version control.

---

## 👑 Owner & Admin Setup

To initialize the owner administrator account:
```powershell
python server.py --create-owner
```
You will be prompted to enter a secure password. Once created, logging in with this account grants full **Pro privileges** and access to the **Admin Dashboard** (`#/admin`) displaying real-time platform metrics, active sessions, and registered users.

---

## 🧪 Marketplace Validation Rules

### Amazon Main Product Image Rules
- **Color Mode**: RGB or sRGB (CMYK rejected).
- **Format**: JPEG, PNG, or WebP.
- **Minimum Resolution**: At least 1,000 px on longest side (1,600 px recommended for full zoom).
- **Maximum Resolution**: Up to 10,000 px.
- **Pure White Background**: RGB (255, 255, 255) corner and border analysis.
- **Product Fill Area**: Product must occupy at least 85% of image frame.

### Etsy Listing Photo Rules
- **Resolution**: At least 2,000 px on shortest side recommended.
- **Aspect Ratio**: Recommended 4:3 or 1:1 framing for search thumbnails.
- **File Size**: Under 25 MB.
- **Color Profile**: sRGB color space.

---

## 📁 Project Structure

```
d:\MARKET\
├── index.html               # Complete, self-contained responsive SPA (Vanilla JS + Modern CSS)
├── server.py                # ThreadingHTTPServer backend, SQLite auth, rate-limiter, API proxy
├── test_server.py           # Comprehensive unittest suite (27 passing tests)
├── TEST_CASES.md            # Documented manual and automated QA scenarios
├── start.bat                # 1-click Windows server starter
├── stop.bat                 # 1-click Windows server stopper
├── .env                     # Local environment configuration
├── listingpreflight.sqlite3 # Persistent SQLite database (WAL mode)
└── README.md                # Comprehensive documentation (Created by Praveen)
```

---

## 👨‍💻 Author & Credits

- **Creator & Lead Developer**: **Praveen** (`praveenmanoharan.dev@gmail.com`)
- **Product**: ListingPreflight v2.0
- Built with high attention to performance, resilience, and UI/UX craftsmanship.