# WindChaser — Planned Features & Known Tasks

## In Progress / Next Up
- **WhatsApp production approval** — Twilio sandbox has 24h session window; WhatsApp and Both options are disabled in the UI until full Twilio production account is approved
- **Kite size calculator** — suggests kite size based on wind speed + rider weight

## Security Enhancements
- **Email verification on registration** — new users must click a confirmation link before their account is activated; unverified accounts cannot log in
- **Stronger password rules** — enforce minimum length (e.g. 10 chars), at least one uppercase, one number, and one special character; apply to both registration and admin password reset
- **WhatsApp phone number verification** — when a user saves a number, send a verification code via Twilio; number only activated once confirmed, to prevent someone entering another person's number

## Planned Features
- **Spot group chat** — WhatsApp-style chat room per spot, visible only to users who have that spot as an active alert spot (admins can see all chats):
  - One `SpotMessage` table (spot_id, user_id, body, created_at); simple migration
  - Users see last 5 days of messages; admins see full history with a delete button for moderation
  - Dedicated `/spots/<id>/chat` page linked from the spot card; keeps spot detail page uncluttered
  - New messages fetched via AJAX polling every ~10–15 seconds; no WebSockets needed at current scale
  - No push notifications for new messages — pull only (user visits the chat to see updates)
  - Access rule: posting and reading gated on `is_active=True` in `UserFavouriteSpot`; losing a spot from active alerts removes chat access
  - Estimated effort: ~6–8 hours (DB model, two routes, chat UI template, AJAX polling, admin moderation view)


- **Task queue (Celery + Redis)** — replace ThreadPoolExecutor with a proper distributed task queue for weather/tide fetching at scale; needed when spot count grows beyond ~200 and parallel HTTP calls risk Gunicorn timeouts even with --timeout 300; Celery workers run outside the web process so they never block HTTP requests

- **Find Spots filtering** — filter the spot list/map by country, and/or within X km of the user's current location (browser geolocation)
- **Kite size calculator page** — user-facing page suggesting kite size based on wind speed + rider weight
- **Internationalisation** — significant work needed to support spots and users outside the UK:
  - **Tidal data** — UK Admiralty API is UK-only; investigate global alternatives (NOAA for USA, CMEMS for Europe, WorldTides API). Likely need to detect spot country and route to the appropriate provider, or ringfence UK-only tide features behind a flag
  - **Weather timezone** — Open-Meteo forecast is fetched with `timezone: Europe/London`; needs to use the spot's local timezone so forecast hours display correctly for spots in other countries
  - **Forecast display** — all times shown in the app are currently UK local time; for international spots these should display in the spot's local timezone
  - **Scope note:** significant cross-cutting change; tackle after initial user feedback
- **Mobile / responsive layout** — remaining gaps:
  - Admin tables need mobile-friendly layout (stacked rows or horizontal scroll)
  - Full test pass on 390px-wide viewport
- **Database upgrade** — Render free PostgreSQL expires May 2026; needs upgrade or migration before then
- **Monetisation** — Stripe £3/month subscription model planned

## Done
- Day condition squares on dashboard (green/amber/grey)
- Per-user wind settings driving forecast colour coding
- Registration with first name, surname, weight, wind preferences, timezone
- Season windows per spot
- Landlocked spot toggle (tide ignored)
- Spots with no nearby UK tidal station treated as tide-irrelevant
- Admin unlimited spot creation (no auto-favourite for admins)
- Find Spots: map/card two-way highlighting, Add to Favourites in cards and popups
- User profile page with availability grid (day × morning/afternoon/evening)
- Refactor: shared bcrypt, deduplicated weather logic, removed debug route
- **Deployment to Render.com** with PostgreSQL
- **PWA — Web App Manifest** — app name, icons, theme colour, launch behaviour; Add to Home Screen on iOS and Android
- **PWA — Service Worker** — caches app shell; handles background push notifications
- **Push notifications** — VAPID-based; replaces WhatsApp as primary alert channel; users subscribe via browser permission prompt
- **Forecast extended to 7 days** — Open-Meteo call updated to `forecast_days: 7`
- **Navbar hamburger menu** — Bootstrap `navbar-expand-lg` collapse for mobile
- **Forecast table** — sticky first column, compact mobile layout, collapsible legend
- **Available row in forecast** — green/red per hour based on user's availability schedule
- **Direction ratings simplified** — Okay removed; now Perfect / Good / Poor / Dangerous only
- **Direction colours updated** — Good = orange, Poor = muted rose, Dangerous = dark grey
- **Shared compass partial** — `spots/_compass.html` used by both Add New Spot and Edit Spot; single source of truth
- **Role toggle in Manage Users** — admins can promote/demote users with password confirmation; `ken@hamptons.me.uk` permanently protected
- **WhatsApp alert timing** — alerts now sent at 7am in each user's stored timezone via hourly cron; uses Python `zoneinfo` for timezone conversion
- **Render Cron Job** — `windchaser-weather-refresh` runs every hour; handles weather refresh, tide refresh (24h guard), summaries, and due alerts; authenticated via `X-Cron-Secret` header
- **Priority dashboard refresh** — user's own spots refreshed synchronously on login if stale (> 1h); remaining spots refreshed in background thread
- **Cache protection** — `fetch_and_cache_weather()` validates API response before writing to DB; bad/error responses never overwrite good cached data
- **Tide refresh throttled** — Admiralty API called at most once per 24 hours per spot to protect daily quota
- **Manage Spots page** — Refresh Weather button moved here from Manage Users
- **Welcome page** — landing page for first-time visitors; extends base.html so navbar always visible

===================

# WindChaser Billing System — Full Specification

---

## Registration & Trial Period

When a new user registers, the system calculates their **first billing date** based on the following rule:

- If they register **on or before the 25th** of the month, their first payment is due on the **25th of the following month**
- If they register **after the 25th**, their first payment is due on the **25th of the month after that**

Examples:
| Register date | First billing date | Free period |
|---|---|---|
| 25th January | 25th February | 31 days |
| 26th January | 25th March | 58 days |
| 1st February | 25th March | 52 days |
| 24th February | 25th March | 29 days |

During registration, the user is told clearly: *"Your free trial runs until 25th March. No payment is required until then."* No card details are collected at this point.

A Stripe Customer record is created silently in the background at registration, ready to attach a payment method later. The user's `subscription_status` is set to `trial`.

---

## The Monthly Billing Cycle

All billing events happen on a fixed monthly schedule. The cycle runs from the **25th to the 25th**.

### 22nd — Warning Emails

Three days before the 25th, two groups of users receive emails:

**Group 1 — Users whose trial is ending (first payment due on 25th):**

> *"Hi [name], we hope you've been enjoying WindChaser. As mentioned when you signed up, WindChaser is a paid service at £3.00/month — less than a cup of coffee and we promise it will never cost more than that, will never include advertising, and your card details are handled securely by Stripe, not us.*
>
> *Your free trial ends on 25th [month]. Please click below to add your payment details — you won't be charged until the 25th.*
>
> *[Add payment details]*
>
> *If you decide WindChaser isn't for you, simply ignore this email and your account will be disabled on 1st [month]."*

**Group 2 — Existing paying users (renewal due on 25th):**

> *"Hi [name], another month of WindChaser is coming up on 25th [month] — £3.00 will be taken from your card on file.*
>
> *If for any reason you no longer feel WindChaser is worth the price of a cup of coffee a month, we completely understand. Click below and we'll cancel your subscription — you'll keep access until 1st [month] and can come back any time.*
>
> *[😊 Cancel my membership]*
>
> *Otherwise, do nothing — we'll take care of everything on the 25th."*

---

### 25th — Payment Day (6am UTC)

The system processes payments for all users whose `next_billing_date` is today. Three outcomes are possible:

**Outcome A — Payment succeeds:**
- User's `subscription_status` stays `active`
- `next_billing_date` advances by one month
- Stripe automatically sends the user a payment receipt email
- No further action needed

**Outcome B — Payment fails (card declined, expired, etc.):**
- User's `subscription_status` set to `unpaid`
- The app banner turns **red** and the app name changes to **"WindChaser Unpaid"**
- User receives an email:

> *"Hi [name], unfortunately we were unable to take your £3.00 payment for WindChaser on 25th [month]. This can happen for a number of reasons — expired card, insufficient funds etc.*
>
> *Please click below to update your payment details and your account will be reinstated immediately.*
>
> *[Update payment details]*
>
> *If we don't hear from you by 1st [month], your account will be suspended. You can come back at any time by emailing windchaser@hamptons.me.uk"*

**Outcome C — No payment method on file (trial user who ignored the 22nd email):**
- Same as Outcome B — `unpaid` status, red banner, reminder email with payment link

---

### 1st — Suspension Day

Any user still in `unpaid` status on the 1st of the month is **suspended**:
- `subscription_status` set to `cancelled`
- They can still log in but see a blank page:

> *"Your WindChaser account has been suspended as we were unable to process your £3.00 monthly payment.*
>
> *Click below to re-enter your payment details and get back on the water immediately.*
>
> *[Reactivate my account — £3.00/month]*
>
> *Or email us at windchaser@hamptons.me.uk if you have any questions."*

---

## Cancellation Flow

When a user clicks **"Cancel my membership"** in their renewal email, they land on a page:

> *"Are you sure you want to lose the amazing capabilities of WindChaser for just the cost of a cup of coffee a month? 😊*
>
> *[Yes, cancel my subscription] &nbsp;&nbsp; [Actually, keep my subscription]*"

If they confirm:
- `cancellation_requested` flag set to `True`
- They keep full access until the 1st of the following month
- On the 1st, no payment is attempted and the account is suspended
- They can reactivate at any time by emailing `windchaser@hamptons.me.uk`

---

## Reactivation

When a suspended user contacts you and you reinstate them via the admin panel, or when they click the payment link on the suspended screen:
- A Stripe Checkout page opens for them to enter / confirm payment details
- **£3.00 is charged immediately** (catch-up for the current month)
- On payment confirmation, Stripe fires a webhook to the app within seconds
- `subscription_status` is set to `active` **immediately**
- `next_billing_date` is set to the **next 25th**
- User is back in the app without needing to do anything else

---

## Free for Life Users

Certain users (beta testers, staff, special cases) are flagged `is_free_for_life` by an admin. These users:
- Never receive any billing emails
- Never see any payment screens
- Are completely invisible to the billing system
- Can be granted or revoked by an admin at any time

---

## What Stripe Handles

- **All card data** — you never see a card number, CVV or expiry date at any point. PCI compliance is entirely Stripe's responsibility
- **Currency conversion** — users with non-UK cards pay the GBP equivalent in their local currency automatically
- **Receipt emails** — Stripe sends a payment confirmation email automatically on each successful charge
- **Checkout pages** — Stripe hosts the card entry pages, styled with WindChaser branding

## What the App Handles

- Calculating trial periods and billing dates
- Sending warning and renewal emails on the 22nd
- Triggering payments via the Stripe API on the 25th
- Receiving Stripe webhooks and updating user status
- Showing the red banner / suspended screen
- Admin controls

---

## Admin Capabilities

The existing users table gains a **Billing Status** column showing one of:
`Trial (ends 25 Apr)` | `Active` | `Unpaid` | `Suspended` | `Cancelled` | `Free for life`

On each user's profile, admins can:
- Toggle `free_for_life` on/off
- Click **"Send payment email"** — fires the payment link email to that user immediately
- Reinstate a suspended user (which triggers the immediate catch-up payment flow)

---

## Future Considerations

- **VAT** — Stripe Tax can be enabled with a single flag when required. Minimal code change
- **Price changes** — to be designed if/when needed
- **Annual billing** — could be added as an option later

---

Does this match your vision? Any corrections or additions before we start building?