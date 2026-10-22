# Fixerpro Test Cases & Security Verification Matrix

## Test Environment & Standards

- **Python Runtime:** Python 3.10+ on Windows / Linux (Compatible with Vercel Serverless Functions).
- **Core Dependencies:** Python standard library (`http.server`, `urllib`, `hashlib`, `hmac`, `secrets`, `smtplib`, `ssl`) + `psycopg2-binary` (PostgreSQL Session Pooler connection).
- **Database Architecture:**
  - **Cloud:** Supabase PostgreSQL with Transaction/Session Connection Pooler on port `6543`.
  - **Local/Offline:** SQLite file (`listingpreflight.sqlite3`) with WAL journal mode.
- **Payment Gateway:** Razorpay Standard Checkout + HMAC-SHA256 timing-safe callback verification.
- **Background Removal:** Poof.bg GPU Cloud AI (~1.5s) with seamless remove.bg fallback.
- **Email Delivery:** Direct SSL/TLS SMTP client authenticated via Gmail App Password.

---

## Automated Security & Functional Test Matrix (34 / 34 Tests Pass)

Execute the full automated test suite:
```cmd
python test_server.py
```

| ID | Suite | Scenario | Security / Privacy / Functional Objective | Expected Result |
|---|---|---|---|---|
| **AT-01** | Auth | Valid User Registration | Enforce length constraints, random 16-byte salt, and PBKDF2 hash | HTTP 201; user assigned `free` tier; HttpOnly, SameSite=Lax cookie set. |
| **AT-02** | Auth | Duplicate Email Registration | Prevent account collision and email enumeration abuse | HTTP 409; existing account intact without data exposure. |
| **AT-03** | Auth | Login Authentication | Timing-attack resistant password verification | Bad password returns HTTP 401; correct password returns HTTP 200 + session. |
| **AT-04** | Auth | Session Validation (`/api/me`) | Cookie integrity & expiration validation | Valid session returns user object; expired session returns `user: null`. |
| **AT-05** | Auth | User Logout | Invalidate session hash in DB and destroy client cookie | HTTP 200; `lp_session` cookie set with `Max-Age=0`. |
| **AT-06** | Auth | Claim Owner Identity | Prevent privilege escalation via public signup | HTTP 403; administrative email cannot be claimed publicly. |
| **AT-07** | Auth | Provision Owner | Secure CLI-based admin bootstrapping | PBKDF2 hashed salt stored; grants `pro` plan and `admin` role. |
| **AT-08** | Auth | Weak Password Guard | Enforce 12-char min for administrative accounts | Rejected with validation exception. |
| **AT-09** | Security | Admin Summary (Unauthenticated) | Information disclosure prevention | HTTP 401; metrics completely concealed. |
| **AT-10** | Security | Admin Summary (Non-Admin User) | Role-Based Access Control (RBAC) enforcement | HTTP 403; metrics hidden from standard users. |
| **AT-11** | Security | Admin Summary (Owner/Admin) | Authorized metric retrieval | HTTP 200 with total users, Pro users, and active sessions. |
| **AT-12** | Database | Automatic Schema Migration | Backward compatibility for evolving schemas | Auto-adds missing columns (`role`, `fixes_used`, `plan_expires_at`). |
| **AT-13** | Security | Unconfigured Reset Handling | Prevent false positives on unconfigured reset endpoints | HTTP 503 with configuration notice. |
| **AT-14** | Frontend | Responsive Viewport & Headers | Security and mobile responsiveness standards | HTTP 200; viewport, OpenGraph, and UTF-8 charset intact. |
| **AT-15** | Security | Background Removal Quota Guard | Protect upstream API keys on provider rate limits | HTTP 429 quota message returned without leaking secret API keys. |
| **AT-16** | AI / Review | Gemini Key Guard | Validate Gemini credentials before dispatch | HTTP 503 when key absent; no external call initiated. |
| **AT-17** | AI / Review | MIME & Marketplace Validation | Sanitize image payloads before external processing | HTTP 415 on bad MIME; HTTP 400 on bad marketplace. |
| **AT-18** | AI / Review | Safe Gemini Interaction | Secure AI review without cloud storage | HTTP 200; payload contains `store: false`; API key scrubbed from output. |
| **AT-19** | Quota | Fix Record (Unauthenticated) | Enforce account requirement for automated fixes | HTTP 401 with `auth_required: true`. |
| **AT-20** | Quota | Free Tier Usage Limit (5 Fixes) | Prevent free-tier abuse of background removal | 1–5 fixes succeed; 6th fix blocked with HTTP 403 (`upgrade: true`). |
| **AT-21** | Developer | Developer Account Privileges | Zero-friction developer testing access | Developer email (`praveenmanoharan.dev@gmail.com`) automatically has unlimited Pro & Admin role. |
| **AT-22** | Payment | Razorpay Order (Unauthenticated) | Prevent anonymous payment order attempts | HTTP 401 ("Please log in before upgrading to Pro"). |
| **AT-23** | Payment | Razorpay Order Creation | Correct currency (INR), amount, and receipt generation | HTTP 200; generates INR order with receipt notes. |
| **AT-24** | Payment | Razorpay HMAC SHA256 Signature Check | Prevent tampered or forged payment callbacks | Validates signature match; invalid signature returns HTTP 400. |
| **AT-25** | Payment | Pro Subscription Upgrade & 30-Day Window | Auto-upgrade and expiration calculation | Upgrades user to `pro`; sets `plan_expires_at` to exactly 30 days from now. |
| **AT-26** | Contact | Contact Form Validation | Prevent spam & empty submissions | Validates name (min 2), email format, and message (min 5). |
| **AT-27** | Contact | Contact Form SMTP Delivery | Direct delivery to official inbox without opening mail client | Sends SSL/TLS email to `officialfixerpro@gmail.com` with Reply-To set to user email. |
| **AT-28** | Security | Rate Limiting | Protect against brute-force & denial of service | IP-based token bucket throttles excessive burst requests (HTTP 429). |
| **AT-29** | Security | CSRF & Origin Validation | Cross-origin request forgery prevention | Validates request origin against host header on non-serverless requests. |
| **AT-30** | Security | Defensive HTTP Headers | Defensive browser attack surface reduction | Injects `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`. |
| **AT-31** | Database | Supabase IPv4 Pooler Compatibility | Support serverless environments without IPv6 routing | Successfully connects to AWS pooler port 6543 in transaction/session mode. |
| **AT-32** | Privacy | Zero Image Storage In DB | Complete privacy guarantee for ecommerce assets | Confirms image payloads are processed strictly in-memory; no database table stores image bytes. |
| **AT-33** | UI / Plan | Dynamic Pricing Status Display | Real-time UI indicator for customer active plans | Free card shows `Your Current Plan`; Pro card shows `✓ Active Plan` with days remaining. |
| **AT-34** | UI / Plan | Plan Reversion Upon Expiration | Automatic downgrade after 30 days | If `plan_expires_at < current_time`, `public_user` treats account as Free tier. |

---

## 🔒 User Privacy & Data Protection Audit Summary

1. **Product Images:**
   - **Never persisted** on any server hard drive, SQLite database, or Supabase PostgreSQL instance.
   - Processing happens in client browser memory (Canvas) or via ephemeral in-memory streams to the GPU cloud.
2. **User Credentials:**
   - Passwords are salt-hashed with PBKDF2-HMAC-SHA256 (310k+ iterations).
   - Cleartext passwords never stored anywhere.
3. **Session Cookies:**
   - Secured with `HttpOnly; SameSite=Lax; Path=/` flags to prevent JavaScript reading or cross-site leakage.
4. **Payment Transactions:**
   - Direct integration with Razorpay Checkout. Card and banking details never pass through our servers.