# ListingPreflight Test Cases

## Test Environment

- Python 3.10 or newer on Windows.
- Project dependencies: Python standard library only.
- Database: isolated temporary SQLite file for automated tests; local `listingpreflight.sqlite3` for manual tests.
- Start the app with `start.bat`; use `http://127.0.0.1:8000/`.
- For owner setup, stop the server first, run `py server.py --create-owner`, enter the owner password only at the hidden terminal prompt, then restart the server.
- Do not include real passwords in screenshots, test fixtures, source code, or this document.

## Automated Tests

Run `py -m unittest -v test_server`.

| ID | Scenario | Expected result |
|---|---|---|
| AT-01 | Register a valid non-owner account | HTTP 201; account has `free` plan and `user` role; an HttpOnly session is issued. |
| AT-02 | Register the same email twice | Second request returns HTTP 409; only one account exists. |
| AT-03 | Log in with incorrect password, then correct password | Incorrect password returns HTTP 401 without a session; correct password logs in and normalizes email case/whitespace. |
| AT-04 | Read `/api/me` with and without a valid cookie | Valid session returns the user; absent or logged-out session returns `user: null`. |
| AT-05 | Log out | HTTP 200; session is invalidated and cookie is expired. |
| AT-06 | Register the configured owner email publicly | HTTP 403; the owner identity cannot be claimed through public registration. |
| AT-07 | Provision the configured owner | Account has `pro` plan and `admin` role; only a salted PBKDF2 hash is stored, not the password. |
| AT-08 | Provision owner with a different email or password shorter than 12 characters | Setup raises a validation error and does not create/update an owner account. |
| AT-09 | Request `/api/admin/summary` without a session | HTTP 401; no account counts are disclosed. |
| AT-10 | Request `/api/admin/summary` as an ordinary user | HTTP 403; no account counts are disclosed. |
| AT-11 | Request `/api/admin/summary` as the owner | HTTP 200 with total users, Pro users, and active sessions. |
| AT-12 | Migrate a legacy database with no role column | Existing users remain; `role` is added as `user`; the configured owner is promoted to `admin` and `pro`. |
| AT-13 | Request password reset while email delivery is unconfigured | HTTP 503 with a clear configuration message; no false success is shown. |
| AT-14 | Request the frontend root | HTTP 200 and responsive viewport metadata is present. |
| AT-15 | Simulate a remove.bg HTTP 429 quota response | The backend returns a clear provider quota/plan message without exposing the API key. |
| AT-16 | Request Gemini review without a configured key | HTTP 503 with a clear server configuration message; no provider request is made. |
| AT-17 | Request Gemini review with an unsupported MIME type or marketplace | HTTP 415 or 400 respectively; the Gemini helper is not called. |
| AT-18 | Mock a successful Gemini review | HTTP 200 returns review text; the Interactions API request contains the selected image, marketplace prompt, and `store: false`, while the API key remains out of the request body and response. |

## Manual Owner Tests

### MT-01: First Owner Setup

**Preconditions:** The project database is accessible; the server is stopped; no owner account has been set up.

**Steps:**
1. Run `py server.py --create-owner` from the project folder.
2. Accept the configured owner email or enter the configured owner email.
3. Enter an owner display name.
4. Enter a new 12-character-or-longer password at the hidden prompt and confirm it.
5. Start the app with `start.bat`.

**Expected:** Setup succeeds without printing the password. The owner account is stored with `admin` role and `pro` plan. Database password material is salted and hashed.

### MT-02: Owner Login and Pro Features

**Preconditions:** MT-01 passed and the app is running.

**Steps:**
1. Open `http://127.0.0.1:8000/#/login`.
2. Sign in as the configured owner with the password entered during setup.
3. Open the account menu and the Account page.
4. Open Pricing and return to the image checker.

**Expected:** The account page shows `Pro` and `Admin`; the account menu contains Admin dashboard; the checker accepts the Pro batch limit (200); Pro-only CSV controls are enabled.

### MT-03: Owner Dashboard

**Preconditions:** Owner is signed in.

**Steps:** Open Admin dashboard from the account menu.

**Expected:** The page loads account, Pro-plan, and active-session totals. The summary endpoint is requested using the authenticated HttpOnly session.

### MT-04: Owner Account Cannot Be Claimed

**Preconditions:** Owner is signed out.

**Steps:** Open Create account and attempt to register the configured owner email.

**Expected:** Registration is rejected with a message that owner setup must be performed by the server administrator. No owner account is created by this route.

### MT-05: Regular User Isolation

**Preconditions:** Owner setup has completed.

**Steps:** Create and sign in to an account with a different email. Try navigating directly to `/#/admin` and request `/api/admin/summary` with that account’s session.

**Expected:** The account remains Free/User. The UI redirects away from the admin page, and the API returns HTTP 403 without summary data.

### MT-06: Logout and Session Expiry Behavior

**Preconditions:** Owner is signed in.

**Steps:** Log out, then revisit `/#/account` and `/#/admin`.

**Expected:** The session is invalidated. Protected pages require login; admin data is not available after logout.

## Manual Image Workflow Tests

### MT-07: Amazon Single-Image Fix

**Steps:** Select Amazon, add an image with non-white background and insufficient dimensions, run Check images, then choose Fix and download.

**Expected:** With `REMOVE_BG_API_KEY` configured, the source image is sent via the backend to remove.bg. A JPG is downloaded at 2000×2000 with the transparent cutout placed on white and scaled to about 88% of the canvas. The original remains available in the preview comparison. Background and product-fill checks are re-run; significant upscaling is flagged. Without the key, Fix reports a clear configuration error and does not claim the image was fixed.

### MT-08: Batch Fix and ZIP

**Steps:** Add at least two images, run Check images, then choose Fix all images.

**Expected:** Amazon images are processed by remove.bg through the backend; Etsy images are resized locally. Every output is rechecked without automatically downloading. Each result provides a fixed-image download, and the preview can switch between the original and fixed versions.

### MT-09: ZIP Download

**Steps:** After checking at least two images, choose Fix all and download ZIP.

**Expected:** The ZIP contains one fixed file per input. Amazon backgrounds are removed through remove.bg and replaced with white; Etsy photos are resized/padded locally. Result cards show each fixed file and any remaining checks.

### MT-10: Etsy Resize and Ratio

**Steps:** Select Etsy, add a low-resolution/non-4:3 image, run the checker, and choose Fix and download.

**Expected:** A JPG at 2000×1500 is downloaded and rechecked; the full source is fit proportionally on a 4:3 white canvas without cropping or external background processing. Width/ratio checks report the output canvas, and low-resolution upscaling is flagged.

### MT-11: Manual-Only Image Content

**Steps:** Use an image containing text, a logo, border, or watermark.

**Expected:** The app does not claim to remove or detect that content reliably. It retains a manual-review note; the seller must inspect the image.

### MT-12: Compare Original and Fixed Preview

**Steps:** Check and fix an image, open its full-screen preview, then switch between the original and fixed image.

**Expected:** The viewer shows both full-resolution versions with a brief transition, the correct filename/version status, keyboard navigation, and reduced-motion support. Closing the viewer restores focus to the preview thumbnail.

### MT-13: Optional Gemini Image Review

**Preconditions:** Set `GEMINI_API_KEY` on the server and ensure the Google project has Gemini 3.8 Flash quota. Review Google's Gemini API terms before using real product photos.

**Steps:** Check an image, then click **Review with Gemini** on its result card. Separately try **Fix** and **Fix and download** to verify their existing behavior remains unchanged.

**Expected:** The chosen image is sent to the server and then Google only after the review button is clicked. A loading state is shown, followed by escaped text feedback. The review does not edit or download the image and is explicitly presented as advisory, not compliance approval. Review and image-fix actions do not run concurrently. If the key is missing or quota is exhausted, a clear error appears without claiming review succeeded.