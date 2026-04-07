# WindChaser — Application Specification

**Version:** April 2026
**Live URL:** https://windchaser.onrender.com
**Repository:** https://github.com/Safa246UK/kiteapp
**Stack:** Python 3 · Flask · SQLAlchemy · PostgreSQL (prod) / SQLite (local) · Gunicorn · Render.com

---

## 1. Overview

WindChaser is a web application for kite surfers to monitor wind and tide conditions across their favourite spots. It provides personalised condition ratings based on each user's wind preferences, tide tolerances, and availability, and sends push notification alerts when conditions are favourable.

**Core value:** "Will it be good for kiting at my spots when I am free?"

---

## 2. Data Model

### 2.1 User
| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer PK | |
| `email` | String (unique) | Login identifier |
| `password` | String | bcrypt hashed |
| `first_name`, `last_name` | String | |
| `is_admin` | Boolean | First registered user auto-promoted |
| `is_active` | Boolean | Admins can disable accounts |
| `created_at` | DateTime | |
| `weight_kg` | Float | Default 75.0 kg |
| `min_wind` | Float | Default 12.0 kn — personal lower wind limit |
| `max_wind` | Float | Default 35.0 kn — personal upper wind limit |
| `kite_size_adjustment` | Float | +/- metres from ideal (future use) |
| `available_slots` | String | Comma-separated: `mon_morning,tue_afternoon,...` |
| `notification_type` | String | `push` / `whatsapp` / `both` / `none` |
| `whatsapp_dial_code` | String | Default `+44` |
| `whatsapp_number` | String (nullable) | Local format; leading 0 stripped on send |
| `whatsapp_today` | Boolean | Alert for today (default True) — also drives push alerts |
| `whatsapp_tomorrow` | Boolean | Alert for tomorrow |
| `whatsapp_day_after` | Boolean | Alert for day after tomorrow |
| `timezone` | String | IANA timezone e.g. `Europe/London` (default) |

**Availability slots** use the format `{day}_{period}` where:
- Day: `mon` `tue` `wed` `thu` `fri` `sat` `sun`
- Period: `morning` (sunrise→12:00) · `afternoon` (12:00→18:00 or sunset) · `evening` (18:00→sunset, ceiling-rounded)

### 2.2 Spot
| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer PK | |
| `name` | String | |
| `description` | String | |
| `latitude`, `longitude` | Float | Used for weather + tide lookups |
| `created_by` | FK → User | |
| `is_retired` | Boolean | Soft delete; hidden from non-admins |
| `is_landlocked` | Boolean | Skips all tide logic (lakes, reservoirs) |
| `min_tide_percent` | Integer | 0–100 (% from LAT to HAT) |
| `max_tide_percent` | Integer | 0–100 |
| `perfect_directions` | String | Comma-separated compass points e.g. `SW,WSW,W` |
| `good_directions` | String | |
| `poor_directions` | String | |
| `dangerous_directions` | String | Default for all unassigned compass points |
| `okay_directions` | String | Legacy field — cleared on every save, treated as dangerous |
| `season_start_month/day` | Integer (nullable) | If set, spot is out of season outside this window |
| `season_end_month/day` | Integer (nullable) | Wraps year if start > end (e.g. Oct→Mar) |

**16-point compass:** N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW

### 2.3 UserFavouriteSpot (join table)
| Field | Type | Notes |
|-------|------|-------|
| `user_id` | FK → User | |
| `spot_id` | FK → Spot | |
| `is_active` | Boolean | True = "Alert Me" enabled |
| `added_at` | DateTime | |

### 2.4 SpotNote
| Field | Type | Notes |
|-------|------|-------|
| `spot_id` | FK → Spot | |
| `user_id` | FK → User | |
| `note` | Text | |
| `created_at`, `updated_at` | DateTime | |

### 2.5 WeatherCache
| Field | Type | Notes |
|-------|------|-------|
| `spot_id` | FK → Spot (unique) | One row per spot |
| `fetched_at` | DateTime | UTC timestamp of last successful fetch |
| `forecast_json` | Text | Raw Open-Meteo response (weather + marine combined) |
| `day_summary_json` | Text | `{"2026-04-01": {"colour": "green", "hours": 5}}` |

### 2.6 TideCache
| Field | Type | Notes |
|-------|------|-------|
| `spot_id` | FK → Spot (unique) | One row per spot |
| `station_id`, `station_name` | String | Nearest UK Admiralty station |
| `station_distance_km` | Float | |
| `station_hat`, `station_lat` | Float | Highest/Lowest Astronomical Tide in metres |
| `fetched_at` | DateTime | UTC timestamp of last successful fetch |
| `events_json` | Text | High/low tide events with times and heights |

### 2.7 PushSubscription
| Field | Type | Notes |
|-------|------|-------|
| `id` | Integer PK | |
| `user_id` | FK → User | |
| `endpoint` | Text | Browser push endpoint URL |
| `p256dh` | Text | VAPID public key |
| `auth` | Text | VAPID auth secret |

### 2.8 AdminSettings (singleton)
| Field | Type | Default |
|-------|------|---------|
| `max_favourite_spots` | Integer | 3 |
| `max_active_spots` | Integer | 2 |
| `default_min_tide_percent` | Integer | 20 |
| `default_max_tide_percent` | Integer | 80 |

---

## 3. Routes & Blueprints

### 3.1 Auth (`auth.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/login` | GET/POST | Email + bcrypt password login |
| `/register` | GET/POST | New account with full profile, availability, notification setup |
| `/forgot-password` | GET/POST | Send password reset email |
| `/reset-password/<token>` | GET/POST | Token-based reset (1-hour expiry, itsdangerous) |
| `/profile` | GET | Redirects to own user detail page |
| `/logout` | GET | Sign out |

### 3.2 Main (`main.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Dashboard — favourites split into Alert Me / Favourites sections; triggers priority weather refresh for user's spots if stale |

### 3.3 Spots (`spots.py`)
| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/spots` | GET | User | Map + list of all active spots |
| `/spots/add` | POST | User | Create spot; auto-favourites creator if under limit; triggers immediate weather fetch |
| `/spots/<id>` | GET | User | Detail: 7-day forecast table, notes, watchers; triggers weather/tide refresh if stale |
| `/spots/<id>/favourite` | POST | User | Toggle favourite (limit enforced) |
| `/spots/<id>/activate` | POST | User | Toggle "Alert Me" (limit enforced) |
| `/spots/<id>/note` | POST | User | Add note to spot |
| `/spots/note/<id>/delete` | POST | User | Delete own note (admin can delete any) |
| `/spots/<id>/edit` | GET/POST | Admin | Edit spot metadata, directions, tide ranges, seasonality |
| `/spots/<id>/retire` | POST | Admin | Soft-delete toggle |
| `/spots/manage` | GET | Admin | All spots table with watcher counts + Refresh Weather button |
| `/spots/api/all` | GET | User | JSON — all spots for Leaflet map |

### 3.4 Admin (`admin.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/users` | GET | User list + global settings form + Send All Alerts button |
| `/admin/users/<id>` | GET | User detail: spots, alerts, profile edit |
| `/admin/users/<id>/edit` | POST | Update any user's profile |
| `/admin/users/<id>/toggle-active` | POST | Enable/disable account (not self) |
| `/admin/users/<id>/toggle-role` | POST | Toggle admin/user role; requires password confirmation; `ken@hamptons.me.uk` permanently protected |
| `/admin/users/<id>/set-password` | POST | Admin password reset |
| `/admin/users/<id>/send-whatsapp` | POST | Manual WA test message to user |
| `/admin/send-all-alerts` | POST | Immediately send alerts to all enabled users (no timezone filter) |
| `/admin/refresh-weather` | POST | Refresh weather + tides + summaries for all spots; also accepts `X-Cron-Secret` header for Render cron job |
| `/admin/settings` | POST | Update global limits |

### 3.5 Push Notifications
| Route | Method | Purpose |
|-------|--------|---------|
| `/push/subscribe` | POST | Register browser push subscription (VAPID) |
| `/push/unsubscribe` | POST | Remove push subscription |

---

## 4. Weather Logic (`weather.py`)

### 4.1 Data Sources
**Open-Meteo Weather API** — `https://api.open-meteo.com/v1/forecast`
- Hourly: wind speed (kn), direction (degrees), gusts (kn), weather code, temperature (°C)
- Daily: sunrise, sunset times
- 7-day forecast, timezone: Europe/London

**Open-Meteo Marine API** — `https://marine-api.open-meteo.com/v1/marine`
- Hourly: wave height (m)
- 7-day forecast

### 4.2 Rating System

**Wind direction** — four tiers (Okay removed):
| Rating | Colour | Meaning |
|--------|--------|---------|
| Perfect | Green `#4CAF50` | Ideal direction for this spot |
| Good | Orange `#FF9800` | Usable direction |
| Poor | Muted rose `#C07080` | Marginal direction |
| Dangerous | Dark grey `#9E9E9E` | Default for all unassigned directions |

**Wind speed** — rated against user's personal `min_wind` / `max_wind`:
- Below range → light blue
- In range → green
- Above range → red

**Gusts** — rated as % above wind speed:
- ≤ 30% → green · ≤ 50% → amber · > 50% → red
- If wind speed = 0 → green (no divide-by-zero)

**Tide** — rated against spot's `min_tide_percent` / `max_tide_percent`:
- Below min → too low (red)
- In range → usable (green)
- Above max → too high (blue)

**Overall slot colour (column header):**
- **Green (#4CAF50):** wind in range + direction Perfect/Good + tide usable (or landlocked/no data)
- Otherwise grey header; each row still shows its own colour so users can see why a slot isn't green

### 4.3 Forecast Table
- Shows 7 days of daylight hours (sunrise → sunset)
- Rows: Available · Wind (kn) · Direction · Gusts · Tide · Wave · Temp · Weather
- **Available row**: green ✓ / red ✗ based on user's availability schedule for that hour
- All rows always coloured (not just green-header columns)
- Collapsible legend — open by default on desktop, collapsed on mobile
- Sticky first column (label) for horizontal scrolling on mobile

### 4.4 Key Functions
| Function | Purpose |
|----------|---------|
| `fetch_and_cache_weather(spot)` | Call Open-Meteo APIs; raises exception if API returns error (never overwrites good cache with bad data) |
| `get_forecast_table(spot, user)` | Build hourly 7-day table; personalised to user's wind prefs and availability |
| `compute_and_cache_summary(spot)` | Store per-day colour/hours using default 12–35 kn range |
| `get_day_summaries_for_user(spot_id, user)` | Personalised 3-day pills using user's wind prefs + availability |
| `_available_slots_for_day(user, weekday)` | Returns set of slot names available on that weekday |
| `_slot_hours(slot, sunrise_h, sunset_h)` | Returns set of integer hours for a named slot; sunset uses ceiling (19:50 → hour 20) |
| `_contiguous_groups(slots, sunrise_h, sunset_h)` | Groups available slots into contiguous hour sets |
| `_good_hours_in_set(hour_set, ...)` | Counts good hours; returns (count, conditions_str, start_hour) |
| `_sun_hours(date_key, sun)` | Extracts sunrise/sunset hours for a given date |
| `_tide_irrelevant(spot)` | True if landlocked or nearest station > 100 km |

### 4.5 Contiguous Period Logic
- Morning + Afternoon are always contiguous (share the 12:00 boundary)
- Afternoon + Evening are contiguous only when sunset > 18:00
- This prevents a morning session and a separate evening session being counted as one block

### 4.6 Dashboard RAG Thresholds
- **Green:** any contiguous available period has ≥ 3 good hours
- **Amber:** any contiguous available period has ≥ 1 good hour
- **Grey:** no good hours within the user's available times

---

## 5. Weather & Tide Refresh Strategy

### 5.1 Cache Protection
`fetch_and_cache_weather()` validates the API response before writing to the database. If Open-Meteo returns an error response (or no `hourly` data), an exception is raised and the existing cache is left untouched. This prevents API outages from wiping good cached data.

### 5.2 Staleness Detection
A cache is considered stale if:
- No cache row exists, or
- `fetched_at` is null, or
- The `forecast_json` contains no usable `hourly.time` data (bad/error response), or
- `fetched_at` is older than the staleness threshold

### 5.3 Dashboard Priority Refresh (on login / page load)
When any user loads the dashboard (`/`):
1. Check all of the user's favourite spots for staleness (threshold: **1 hour**)
2. If any are stale, refresh them **synchronously** before rendering — so the user's cards are always current
3. Kick off a background thread to refresh all other stale spots (non-blocking)

### 5.4 Spot Detail Page Refresh
When a spot detail page loads:
- Weather refreshed if cache is stale (> 3 hours old or bad data)
- Tides refreshed if cache is stale (> 12 hours old)

### 5.5 Render Cron Job (primary refresh mechanism)
A Render Cron Job hits `POST /admin/refresh-weather` with `X-Cron-Secret` header every hour:
- `refresh_all_weather()` — fetches weather for all non-retired spots
- `refresh_all_tides()` — fetches tides only if cache > **24 hours** old (protects Admiralty API quota)
- `refresh_all_summaries()` — recomputes day summary colours for all spots
- `send_due_alerts()` — sends push/WhatsApp alerts to users for whom it is currently 7am in their timezone

---

## 6. Tide Logic (`tides.py`)

### 6.1 Data Source
UK Admiralty API — `https://admiraltyapi.azure-api.net/uktidalapi/api/V1`
- Requires `ADMIRALTY_API_KEY` environment variable
- UK tidal stations only; stations > 100 km from spot are ignored
- Refreshed at most once per 24 hours (cron guard)

### 6.2 Key Functions
| Function | Purpose |
|----------|---------|
| `find_nearest_station(lat, lng, api_key)` | Haversine search; returns station dict + distance km |
| `interpolate_height(events, dt)` | Cosine interpolation between high/low tide events |
| `tide_percentage(height, ref_low, ref_high)` | Converts height to 0–100% scale (LAT→HAT) |
| `tide_colour(pct, spot)` | Hex colour based on spot's min/max % thresholds |
| `get_tide_slots(spot, target_dates)` | Cache-first: serves from DB if < 12h old, only calls API when stale |

### 6.3 Fallback Behaviour
- API unavailable → use last `events_json` from TideCache
- No station within 100 km → spot treated as tide-irrelevant
- No API key → all tide logic skipped

---

## 7. Alert Logic (`alerts.py`)

### 7.1 Alert Computation — `get_alerts_for_user(user)`
1. Determine which days to check (`whatsapp_today/tomorrow/day_after` flags — used for all notification types)
2. For each active Alert Me spot:
   - Get user's available slots for that weekday
   - Group into contiguous periods (respecting sunrise/sunset)
   - Count good hours per period (wind + direction + tide)
   - Flag if any period has ≥ 3 good hours
3. Return list of `{spot, day_label, hours, conditions, start_hour}`

### 7.2 Message Format
```
🪁 *WindChaser* – your conditions update

*Today*
• Marske – Wind: 18kn SW · 5 good hours starting at 11am

*Tomorrow*
• Marske – Wind: 20kn WSW · 3 good hours starting at 2pm

🔗 https://windchaser.onrender.com
```
Returns `None` if no spots meet the threshold.

### 7.3 Send Functions
| Function | Purpose |
|----------|---------|
| `send_alerts_for_user(user, app_url)` | Compute + send for one user via push and/or WhatsApp; returns `(sent: bool, detail: str)` |
| `send_all_alerts(app_url)` | Send immediately to all enabled users — no timezone filter; used by manual admin button |
| `send_due_alerts(app_url)` | Send only to users for whom it is currently `ALERT_HOUR` (7am) in their stored timezone; called by hourly cron |

### 7.4 Timezone-Aware Delivery
- `ALERT_HOUR = 7` (constant in `alerts.py`, easily changed)
- Uses Python built-in `zoneinfo` (no third-party dependency)
- Falls back to `Europe/London` if user's stored timezone is invalid
- The hourly cron ensures every timezone gets its 7am alert within ±1 hour of the correct time

---

## 8. Push Notifications (`push.py`)

- Protocol: **Web Push / VAPID**
- Keys: `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` environment variables
- Service worker at `/sw.js` handles background receipt and display
- `send_push_to_user(user, title, body, url)` — sends to all of a user's registered subscriptions
- Subscription registered on browser permission grant; synced on every page load if already subscribed
- A `wc_push=1` cookie prevents re-prompting on devices that have already subscribed

---

## 9. WhatsApp Integration (`whatsapp.py`)

- Provider: **Twilio** (currently using sandbox: `whatsapp:+14155238886`)
- WhatsApp options (WhatsApp / Both) are disabled in the UI pending full Twilio production approval
- Phone formatting: dial code (e.g. `+44`) + local number with leading `0` stripped → E.164
- `send_whatsapp(dial_code, local_number, body)` → `(success: bool, sid_or_error: str)`

---

## 10. Scheduler (`scheduler.py`)

APScheduler is configured but **only runs under `python app.py`** (local dev). On Render it does not persist across restarts. Production scheduling is handled entirely by the Render Cron Job.

| Function | Purpose |
|----------|---------|
| `refresh_all_weather()` | `fetch_and_cache_weather()` for all non-retired spots |
| `refresh_all_tides()` | `fetch_and_cache_tides()` for spots with cache > 24h old |
| `refresh_all_summaries()` | `compute_and_cache_summary()` for all non-retired spots |

---

## 11. Templates

| Template | Purpose |
|----------|---------|
| `base.html` | Navbar (hamburger on mobile), flash messages, Bootstrap 5.3 + Leaflet.js CDN |
| `welcome.html` | Landing page for first-time visitors (extends base.html) |
| `auth/login.html` | Email + password login form |
| `auth/register.html` | Full registration: kite profile, availability lozenges, notification setup, timezone |
| `auth/forgot_password.html` | Email input to request reset link |
| `auth/reset_password.html` | New password form (token-gated, 1-hour expiry) |
| `dashboard.html` | My Spots: Alert Me cards (green border) + Favourites (blue border) with day pills |
| `spots/index.html` | Leaflet map + spot cards + Add New Spot modal |
| `spots/_compass.html` | **Shared partial** — compass rose buttons + hidden inputs + CSS; included by both index.html and edit.html |
| `spots/detail.html` | 7-day hourly forecast table, notes, watchers, favourite/alert toggles |
| `spots/edit.html` | Admin: edit spot with draggable Leaflet map for lat/lng |
| `spots/manage.html` | Admin: all spots table with retire toggle + Refresh Weather button |
| `admin/users.html` | User list, global settings, Send All Alerts button |
| `admin/user_detail.html` | Full user profile edit including availability, notification settings, timezone |

---

## 12. Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Prod only | — | PostgreSQL URL (Render injects automatically) |
| `SECRET_KEY` | Yes | `change-this-later` | Flask session signing key |
| `ADMIRALTY_API_KEY` | For tides | — | UK Admiralty tidal data API |
| `CRON_SECRET` | Prod | — | Shared secret for Render cron job; sent as `X-Cron-Secret` header |
| `VAPID_PUBLIC_KEY` | For push | — | Web Push VAPID public key |
| `VAPID_PRIVATE_KEY` | For push | — | Web Push VAPID private key |
| `VAPID_CLAIM_EMAIL` | For push | — | Contact email embedded in VAPID JWT |
| `TWILIO_ACCOUNT_SID` | For WA | — | Twilio account ID |
| `TWILIO_AUTH_TOKEN` | For WA | — | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | For WA | `whatsapp:+14155238886` | Sender number |
| `MAIL_SERVER` | For email | `smtp.gmail.com` | SMTP host |
| `MAIL_PORT` | For email | `587` | SMTP port |
| `MAIL_USE_TLS` | For email | `True` | TLS toggle |
| `MAIL_USERNAME` | For email | — | Gmail address |
| `MAIL_PASSWORD` | For email | — | Gmail app password |
| `MAIL_DEFAULT_SENDER` | For email | — | From address |

---

## 13. User Flows

### New User Registration
1. `/register` — enter name (required), email (required), password (min 6 chars)
2. Set kite profile: weight, min/max wind speed, timezone
3. Set availability: lozenge-style day selectors (Today / Tomorrow / Day after) × morning/afternoon/evening slots
4. Choose notification method: Phone App (push) / WhatsApp / Both / None
5. Submit → account created; first-ever user auto-becomes admin
6. Redirected to dashboard (empty — no spots added yet)

### Adding a Spot
1. Dashboard → "Find Spots" → "Add New Spot" modal
2. Enter name, description, lat/lng (or click map to fill automatically)
3. Set tide range (% of LAT→HAT)
4. Assign each compass point to Perfect / Good / Poor / Dangerous using the shared compass partial
5. Optional: set seasonal dates, mark as landlocked
6. Submit → weather fetched immediately; spot appears in favourites

### Checking Conditions
1. Dashboard shows day pills (green/amber/grey) for each favourite spot; cards always reflect fresh data (priority refresh on load)
2. Click "View" → 7-day hourly forecast table on spot detail page
3. All rows always coloured; green column header = all conditions good for that hour
4. Available row shows ✓/✗ based on the user's availability schedule

### Daily Alerts
1. Toggle "Alert Me" on a spot (max 2 per user by default)
2. Set notification type to Push, WhatsApp, or Both on profile
3. At 7am in the user's local timezone, the Render cron fires and sends their alert
4. Alert sent if any contiguous available period has ≥ 3 good hours
5. Admin can trigger immediately via "Send All Alerts Now" on the Manage Users screen

---

## 14. Business Rules

| Rule | Detail |
|------|--------|
| Favourite spot limit | Max 3 per user (admin-configurable) |
| Alert Me limit | Max 2 per user (must be ≤ favourite limit) |
| Delete restriction | Can't remove a spot from favourites while Alert Me is on |
| Admin exemption | Admins not subject to spot limits |
| First user | Automatically given admin role |
| Protected admin | `ken@hamptons.me.uk` is permanently admin and cannot be demoted |
| Role toggle | Admins can promote/demote other users; requires password re-entry; cannot change own role |
| Self-disable | Admins cannot disable their own account |
| Limit reduction | Admin can't reduce limits below current user usage |
| Seasonal spots | Forecast hidden out of season; spot still visible in list |
| Tide irrelevance | Landlocked spots, or spots > 100 km from any tidal station, skip tide checks |
| Alert threshold | ≥ 3 good hours in any single contiguous available period |
| Alert timing | Daily at 7am in each user's stored timezone (via hourly cron) |

---

## 15. Deployment

**Production:** Render.com
- **Web Service:** `gunicorn app:app` (free tier — 512 MB RAM, 0.1 CPU)
- **Database:** PostgreSQL 16 (free tier, expires May 2026 — upgrade or migrate)
- **Cron Job:** `windchaser-weather-refresh` — runs `0 * * * *` (top of every hour)
  - POSTs to `/admin/refresh-weather` with `X-Cron-Secret` header
  - Refreshes weather (all spots), tides (if > 24h old), summaries, and sends due alerts
- **Auto-deploy:** triggered on every push to `main` branch on GitHub
- **Free tier caveat:** service spins down after 15 min inactivity; cold start ~30–60 seconds

**Local dev:** `python app.py`
- SQLite at `instance/kiteapp.db`
- Secrets via `.env` (comment out `DATABASE_URL` to stay local)
- Werkzeug hot-reload; APScheduler starts in main process only (weather/summaries only — no alerts)

---

## 16. Known Limitations & TODO

- **UK-only tidal data:** Admiralty API is UK-only. International spots get no tide data.
- **WhatsApp production:** Twilio sandbox has 24-hour session window. WhatsApp and Both options are currently disabled in the UI pending full Twilio production approval.
- **Email verification:** Not implemented on registration.
- **Password strength:** Minimum 6 characters only; no complexity enforcement.
- **WhatsApp number verification:** No one-time-code check when a number is saved.
- **Monetisation:** Stripe £3/month subscriptions planned.
- **iOS push reliability:** First push notification after a long period of inactivity may be dropped due to iOS service worker suspension. Subsequent notifications reliable.
- **App name:** WindChaser (previously GoneKiting / Sendit).
- **Database expiry:** Render free PostgreSQL expires May 2026 — needs upgrade or migration.
