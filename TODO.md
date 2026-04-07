# WindChaser — Planned Features & Known Tasks

## In Progress / Next Up
- **WhatsApp production approval** — Twilio sandbox has 24h session window; WhatsApp and Both options are disabled in the UI until full Twilio production account is approved
- **Kite size calculator** — suggests kite size based on wind speed + rider weight

## Security Enhancements
- **Email verification on registration** — new users must click a confirmation link before their account is activated; unverified accounts cannot log in
- **Stronger password rules** — enforce minimum length (e.g. 10 chars), at least one uppercase, one number, and one special character; apply to both registration and admin password reset
- **WhatsApp phone number verification** — when a user saves a number, send a verification code via Twilio; number only activated once confirmed, to prevent someone entering another person's number

## Planned Features
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
