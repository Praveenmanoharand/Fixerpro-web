# Verdict Test Cases & Security Verification

## Test Environment

- **Python Version:** Python 3.10+ on Windows / Linux (Vercel Serverless environment supported).
- **Core Dependencies:** Python standard library (`http.server`, `urllib`, `hashlib`, `hmac`, `secrets`, `smtplib`, `ssl`) + `psycopg2-binary` (for PostgreSQL connection pooling).
- **Database Support:** Dual-mode architecture:
  - **Cloud:** Supabase PostgreSQL with Transaction/Session Connection Pooler on port `6543`.
  - **Local/Offline:** SQLite file (`listingpreflight.sqlite3`) with WAL journal mode.
- **Payment Gateway:** Razorpay Standard Checkout + HMAC SHA256 Webhook/Callback verification.
- **Email Delivery:** Direct SSL/TLS SMTP client authenticated with Google Gmail App Passwords.

---

## Automated Security & Integration Tests

Run test suite anytime:
```cmd
python test_server.py
```

### Complete Test Matrix (34 / 34 Automated Tests Pass)

| ID | Suite | Scenario | Security / Functional Goal | Expected Result |
|---|---|---|---|---|
| **AT-01** | Auth | Valid User Registration | Enforce min/max length, salt & PBKDF2 hash (600,000 iterations) | HTTP 201; user assigned `free` tier; HttpOnly, SameSite=Lax cookie. |
| **AT-02** | Auth | Duplicate Email Registration | Prevent account collisions and email overwriting | HTTP 409; existing account intact. |
| **AT-03** | Auth | Login Authentication | Timing-attack resistant password verification | Bad password returns HTTP 401; correct password returns HTTP 200 + session. |
| **AT-04** | Auth | Session Validation (`/api/me`) | Cookie integrity & expiration verification | Valid session returns user object; expired session returns `user: null`. |
| **AT-05** | Auth | User Logout | Invalidate session in DB and clear client cookie | HTTP 200; `lp_session` set with `Max-Age=0`. |
| **AT-06** | Auth | Claim Owner Identity | Prevent privilege escalation via public registration | HTTP 403; owner email cannot be registered publicly. |
| **AT-07** | Auth | Provision Owner | CLI-based admin bootstrapping | PBKDF2 hashed salt stored; grants `pro` plan and `admin` role. |
| **AT-08** | Auth | Weak Password Guard | Enforce 12-char min for administrative accounts | Rejected with validation exception. |
| **AT-09** | Security | Admin Summary (Unauthenticated) | Information disclosure prevention | HTTP 401; metrics hidden. |
| **AT-10** | Security | Admin Summary (Non-Admin User) | Role-Based Access Control (RBAC) | HTTP 403; metrics hidden from standard users. |
| **AT-11** | Security | Admin Summary (Owner/Admin) | Authorized metric retrieval | HTTP 200 with total users, Pro users, and active sessions. |
| **AT-12** | Database | Automatic Schema Migration | Backward compatibility for legacy databases | Auto-adds missing columns (`role`, `fixes_used`, `plan_expires_at`). |
| **AT-13** | Security | Unconfigured Reset Handling | Prevent false positives on unconfigured endpoints | HTTP 503 with helpful config requirement. |
| **AT-14** | Frontend | Responsive Viewport Headers | Mobile & desktop standards check | HTTP 200; viewport, OpenGraph, and charset metadata intact. |
| **AT-15** | Security | remove.bg Quota Limiting | Protect upstream API keys on provider failure | HTTP 429 quota message returned without leaking API keys. |
| **AT-16** | AI / Review | Gemini Key Guard | Validate Gemini credentials before dispatch | HTTP 503 when key absent; no external call initiated. |
| **AT-17** | AI / Review | MIME & Marketplace Validation | Sanitize image payloads before external processing | HTTP 415 on bad MIME; HTTP 400 on bad marketplace. |
| **AT-18** | AI / Review | Safe Gemini Interaction | Secure AI review without cloud storage | HTTP 200; payload contains `store: false`; API key scrubbed from output. |
| **AT-19** | Quota | Fix Record (Unauthenticated) | Enforce account requirement for automated fixes | HTTP 401 with `auth_required: true`. |
| **AT-20** | Quota | Free Tier Usage Limit (5 Fixes) | Prevent free-tier abuse of background removal | 1–5 fixes succeed; 6th fix blocked with HTTP 403 (`upgrade: true`). |
| **AT-21** | Developer | Developer Account Privileges | Zero-friction developer testing access | Developer email (`praveenmanoharan.dev@gmail.com`) automatically has unlimited Pro & Admin role. |
| **AT-22** | Payment | Razorpay Order (Unauthenticated) | Prevent anonymous payment attempts | HTTP 401 ("Please log in before upgrading to Pro"). |
| **AT-23** | Payment | Razorpay Order Creation | Correct currency, amount, and metadata generation | HTTP 200; generates INR order with receipt notes. |
| **AT-24** | Payment | Razorpay HMAC SHA256 Signature Check | Prevent tampered or forged payment callbacks | Validates signature match; invalid signature returns HTTP 400. |
| **AT-25** | Payment | Pro Subscription Upgrade & 30-Day Window | Auto-upgrade and expiration calculation | Upgrades user to `pro`; sets `plan_expires_at` to exactly 30 days from now. |
| **AT-26** | Contact | Contact Form Validation | Prevent spam & empty submissions | Validates name (min 2), email format, and message (min 5). |
| **AT-27** | Contact | Contact Form SMTP Delivery | Direct delivery to official inbox without opening mail client | Sends SSL TLS email to `officialverdictv@gmail.com` with Reply-To set to user email. |
| **AT-28** | Security | Rate Limiting | Protect against brute-force & denial of service | IP-based token bucket throttles excessive burst requests (HTTP 429). |
| **AT-29** | Security | CSRF & Origin Validation | Cross-origin request forgery prevention | Validates request origin against host header on non-serverless requests. |
| **AT-30** | Security | Security Response Headers | Defensive browser headers | Injects `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`. |
| **AT-31** | Database | Supabase IPv4 Pooler Compatibility | Support serverless environments without IPv6 routing | Successfully connects to AWS pooler port 6543 in transaction/session mode. |
| **AT-32** | Privacy | Zero Image Storage In DB | Privacy guarantee for ecommerce product assets | Confirms image payloads are processed strictly in-memory; no database table stores image bytes. |
| **AT-33** | UI / Plan | Dynamic Pricing Status Display | Real-time UI indicator for customer active plans | Free card shows `Your Current Plan`; Pro card shows `✓ Active Plan` with days remaining. |
| **AT-34** | UI / Plan | Plan Reversion Upon Expiration | Automatic downgrade after 30 days | If `plan_expires_at < current_time`, `public_user` treats account as Free tier. |

---

## Manual Verification Guide

### 1. Razorpay Payment Gateway End-to-End
1. Open `https://market-pro-seven.vercel.app/#/pricing`.
2. Click **Get Pro** or navigate to `#/checkout?plan=pro`.
3. Fill details and click **Continue to secure payment**.
4. Razorpay test modal opens (`rzp_test_...`).
5. Select Test Payment -> Success.
6. Verify modal confirms payment and upgrades plan without page reload.
7. Return to `#/pricing` -> Pro card now highlights: **✓ Current Plan (30 days left)**.

### 2. Contact Us Form Delivery
1. Navigate to `#/contact`.
2. Fill Name: `Praveen`, Email: `test@example.com`, Message: `Testing contact form delivery`.
3. Click **Send message**.
4. Spinner shows `Delivering your message to our inbox...`
5. Green success banner appears: `Thank you! Your message has been sent successfully.`
6. Check inbox of `officialverdictv@gmail.com` -> Message arrives with user's email set as `Reply-To`.