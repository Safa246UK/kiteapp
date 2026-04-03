# GoneKiting — Application Specification

**Version:** April 2026
**Live URL:** https://gonekiting.onrender.com
**Repository:** https://github.com/Safa246UK/kiteapp
**Stack:** Python 3 · Flask · SQLAlchemy · PostgreSQL (prod) / SQLite (local) · Gunicorn · Render.com

---

## 1. Overview

GoneKiting is a web application for kite surfers to monitor wind and tide conditions across their favourite spots. It provides personalised condition ratings based on each user's wind preferences, tide tolerances, and availability, and sends WhatsApp alerts when conditions are favourable.

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
| `whatsapp_enabled` | Boolean | Master switch for all WA alerts |
| `whatsapp_dial_code` | String | Default `+44` |
| `whatsapp_number` | String (nullable) | Local format; leading 0 stripped on send |
| `whatsapp_today` | Boolean | Alert for today (default True) |
| `whatsapp_tomorrow` | Boolean | Alert for tomorrow |
| `whatsapp_day_after` | Boolean | Alert for day after tomorrow |
| `timezone` | String | Default `Europe/London` |

**Availability slots** use the format `{day}_{period}` where:
- Day: `mon` `tue` `wed` `thu` `fri` `sat` `sun`
- Period: `morning` (sunrise→12:00) · `afternoon` (12:00→18:00 or sunset) · `evening` (18:00→sunset)

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
| `okay_directions` | String | |
| `poor_directions` | String | |
| `dangerous_directions` | String | |
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
| `fetched_at` | DateTime | |
| `forecast_json` | Text | Raw Open-Meteo response (weather + marine combined) |
| `day_summary_json` | Text | `{"2026-04-01": {"colour": "green", "hours": 5}}` |

### 2.6 TideCache
| Field | Type | Notes |
|-------|------|-------|
| `spot_id` | FK → Spot (unique) | One row per spot |
| `station_id`, `station_name` | String | Nearest UK Admiralty station |
| `station_distance_km` | Float | |
| `station_hat`, `station_lat` | Float | Highest/Lowest Astronomical Tide in metres |
| `fetched_at` | DateTime | |
| `events_json` | Text | High/low tide events with times and heights |

### 2.7 AdminSettings (singleton)
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
| `/register` | GET/POST | New account with full profile, availability, optional WhatsApp |
| `/forgot-password` | GET/POST | Send password reset email |
| `/reset-password/<token>` | GET/POST | Token-based reset (1-hour expiry, itsdangerous) |
| `/profile` | GET | Redirects to own user detail page |
| `/logout` | GET | Sign out |

### 3.2 Main (`main.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Dashboard — favourites split into Alert Me / Favourites sections |

### 3.3 Spots (`spots.py`)
| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/spots` | GET | User | Map + list of all active spots |
| `/spots/add` | POST | User | Create spot; auto-favourites creator if under limit |
| `/spots/<id>` | GET | User | Detail: 3-day forecast table, notes, watchers |
| `/spots/<id>/favourite` | POST | User | Toggle favourite (limit enforced) |
| `/spots/<id>/activate` | POST | User | Toggle "Alert Me" (limit enforced) |
| `/spots/<id>/note` | POST | User | Add note to spot |
| `/spots/note/<id>/delete` | POST | User | Delete own note (admin can delete any) |
| `/spots/<id>/edit` | GET/POST | Admin | Edit spot metadata, directions, tide ranges, seasonality |
| `/spots/<id>/retire` | POST | Admin | Soft-delete toggle |
| `/spots/manage` | GET | Admin | All spots table with watcher counts |
| `/spots/api/all` | GET | User | JSON — all spots for Leaflet map |

### 3.4 Admin (`admin.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/users` | GET | User list + global settings form + Send All Alerts button |
| `/admin/users/<id>` | GET | User detail: spots, alerts, profile edit |
| `/admin/users/<id>/edit` | POST | Update any user's profile |
| `/admin/users/<id>/toggle-active` | POST | Enable/disable account (not self) |
| `/admin/users/<id>/set-password` | POST | Admin password reset |
| `/admin/users/<id>/send-whatsapp` | POST | Manual WA test message to user |
| `/admin/send-all-alerts` | POST | Trigger alerts for all enabled users |
| `/admin/settings` | POST | Update global limits |

---

## 4. Weather Logic (`weather.py`)

### 4.1 Data Sources
**Open-Meteo Weather API** — `https://api.open-meteo.com/v1/forecast`
- Hourly: wind speed (kn), direction (degrees), gusts (kn), weather code, temperature (°C)
- Daily: sunrise, sunset times
- 3-day forecast, timezone: Europe/London

**Open-Meteo Marine API** — `https://marine-api.open-meteo.com/v1/marine`
- Hourly: wave height (m)
- 3-day forecast

### 4.2 Rating System

**Wind speed** — rated against user's personal `min_wind` / `max_wind`:
- Below range → too weak
- In range → good
- Above range → too strong

**Wind direction** — rated against spot's compass point lists:
- `perfect` → `good` → `okay` → `poor` → `dangerous` (default if unassigned)

**Tide** — rated against spot's `min_tide_percent` / `max_tide_percent`:
- Below min → too low (red)
- In range → usable (green)
- Above max → too high (blue)
- No data → grey

**Overall slot colour:**
- **Green (#4CAF50):** wind in range + direction usable + tide usable (or landlocked/no data)
- **Amber (#FFD54F):** some conditions met, but not enough for green threshold
- **Grey (#e0e0e0):** no good hours

### 4.3 Key Functions

| Function | Purpose |
|----------|---------|
| `fetch_and_cache_weather(spot)` | Call Open-Meteo APIs, store combined JSON in WeatherCache |
| `get_forecast_table(spot, user)` | Build hourly 3-day table for detail page; personalised to user's wind prefs |
| `compute_and_cache_summary(spot)` | Store per-day colour/hours using default 12–35 kn range |
| `get_day_summaries_for_user(spot_id, user)` | Personalised 3-day pills using user's wind prefs + availability |
| `_available_slots_for_day(user, weekday)` | Returns set of slot names available on that weekday |
| `_contiguous_groups(slots, sunrise_h, sunset_h)` | Groups available slots into contiguous hour sets |
| `_good_hours_in_set(hour_set, ...)` | Counts good hours; returns (count, conditions_str, start_hour) |
| `_sun_hours(date_key, sun)` | Extracts float sunrise/sunset hours for a given date |
| `_tide_irrelevant(spot)` | True if landlocked or nearest station > 100 km |

### 4.4 Contiguous Period Logic
- Morning + Afternoon are always contiguous (share the 12:00 boundary)
- Afternoon + Evening are contiguous only when sunset > 18:00
- This prevents a morning session and a separate evening session being counted as one block

### 4.5 Dashboard RAG Thresholds
- **Green:** any contiguous available period has ≥ 3 good hours
- **Amber:** any contiguous available period has ≥ 1 good hour
- **Grey:** no good hours within the user's available times

---

## 5. Tide Logic (`tides.py`)

### 5.1 Data Source
UK Admiralty API — `https://admiraltyapi.azure-api.net/uktidalapi/api/V1`
- Requires `ADMIRALTY_API_KEY` environment variable
- UK tidal stations only; stations > 100 km from spot are ignored

### 5.2 Key Functions
| Function | Purpose |
|----------|---------|
| `find_nearest_station(lat, lng, api_key)` | Haversine search; returns station dict + distance km |
| `interpolate_height(events, dt)` | Cosine interpolation between high/low tide events |
| `tide_percentage(height, ref_low, ref_high)` | Converts height to 0–100% scale (LAT→HAT) |
| `tide_colour(pct, spot)` | Hex colour based on spot's min/max % thresholds |
| `get_tide_slots(spot, target_dates)` | Fetches + caches; falls back to last cached data |

### 5.3 Fallback Behaviour
- API unavailable → use last `events_json` from TideCache
- No station within 100 km → spot treated as tide-irrelevant
- No API key → all tide logic skipped

---

## 6. Alert Logic (`alerts.py`)

### 6.1 Alert Computation — `get_alerts_for_user(user)`
1. Skip if `whatsapp_enabled=False` or no active favourite spots
2. Determine which days to check (`whatsapp_today/tomorrow/day_after`)
3. For each day:
   - Get user's available slots for that weekday
   - Group into contiguous periods (respecting sunrise/sunset)
   - Count good hours per period (wind + direction + tide)
   - Flag if any period has ≥ 3 good hours
4. Return list of `{spot, day_label, hours, conditions, start_hour}`

### 6.2 Message Format
```
🪁 *KiteApp* – your conditions update

*Today*
• Marske – Wind: 18kn SW · 5 good hours starting at 11am

*Tomorrow*
• Marske – Wind: 20kn WSW · 3 good hours starting at 2pm

🔗 https://gonekiting.onrender.com
```
Returns `None` if no spots meet the threshold.

### 6.3 Send Functions
| Function | Purpose |
|----------|---------|
| `send_alerts_for_user(user, app_url)` | Compute + send for one user; returns `(sent: bool, detail: str)` |
| `send_all_alerts(app_url)` | Loops all `whatsapp_enabled=True, is_active=True` users |

---

## 7. WhatsApp Integration (`whatsapp.py`)

- Provider: **Twilio** (currently using sandbox: `whatsapp:+14155238886`)
- Phone formatting: dial code (e.g. `+44`) + local number with leading `0` stripped → E.164
- `send_whatsapp(dial_code, local_number, body)` → `(success: bool, sid_or_error: str)`

---

## 8. Scheduler (`scheduler.py`)

Uses **APScheduler BackgroundScheduler** (timezone: Europe/London).

| Job | Frequency | Action |
|-----|-----------|--------|
| `refresh_all_weather` | Hourly | `fetch_and_cache_weather()` for all non-retired spots |
| `refresh_all_summaries` | Hourly | `compute_and_cache_summary()` for all non-retired spots |

> **Note:** APScheduler only runs under `python app.py` (local dev). On Render.com it does not persist. WhatsApp alerts need to be triggered via a Render Cron Job — this is a known TODO.

---

## 9. Templates

| Template | Purpose |
|----------|---------|
| `base.html` | Navbar, flash messages, Bootstrap 5.3 + Leaflet.js CDN |
| `auth/login.html` | Email + password login form |
| `auth/register.html` | Full registration: kite profile, availability grid, WhatsApp setup |
| `auth/forgot_password.html` | Email input to request reset link |
| `auth/reset_password.html` | New password form (token-gated, 1-hour expiry) |
| `dashboard.html` | My Spots: Alert Me cards (green border) + Favourites (blue border) with day pills |
| `spots/index.html` | Leaflet map + spot cards + Add New Spot modal |
| `spots/detail.html` | 3-day hourly forecast table, notes, watchers, favourite/alert toggles |
| `spots/edit.html` | Admin: edit spot with draggable Leaflet map for lat/lng |
| `spots/manage.html` | Admin: all spots table with retire toggle |
| `admin/users.html` | User list, global settings, Send All Alerts button, manual WA compose |
| `admin/user_detail.html` | Full user profile edit including availability grid and WhatsApp settings |

---

## 10. Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Prod only | — | PostgreSQL URL (Render injects this automatically) |
| `SECRET_KEY` | Yes | `change-this-later` | Flask session signing key |
| `ADMIRALTY_API_KEY` | For tides | — | UK Admiralty tidal data API |
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

## 11. User Flows

### New User Registration
1. `/register` — enter name, email, password (min 6 chars)
2. Set kite profile: weight, min/max wind speed
3. Set availability: tick days × morning/afternoon/evening slots
4. Optional: enter WhatsApp number, choose which days to receive alerts
5. Submit → account created; first-ever user auto-becomes admin
6. Redirected to dashboard (empty — no spots added yet)

### Adding a Spot
1. Dashboard → "+ Find / Add Spot" or `/spots` → "Add New Spot" modal
2. Enter name, description, lat/lng (or click map to fill automatically)
3. Set tide range (% of LAT→HAT)
4. Assign each compass point to a wind direction rating tier
5. Optional: set seasonal dates, mark as landlocked
6. Submit → weather fetched immediately; spot appears in favourites

### Checking Conditions
1. Dashboard shows day pills (green/amber/grey) for each favourite spot
2. Click "View" → 3-day hourly forecast table on spot detail page
3. Cell colours show suitability per hour for wind speed, direction, and tide
4. Green column header = all conditions good for that hour

### WhatsApp Alerts
1. Toggle "Alert Me" on a spot (max 2 per user by default)
2. Ensure WhatsApp is enabled on profile with a phone number saved
3. At the scheduled trigger time, system checks each enabled user's active spots
4. Message sent if any contiguous available period has ≥ 3 good hours
5. Admin can trigger manually via "Send All Alerts Now" on the Manage Users screen

---

## 12. Business Rules

| Rule | Detail |
|------|--------|
| Favourite spot limit | Max 3 per user (admin-configurable) |
| Alert Me limit | Max 2 per user (must be ≤ favourite limit) |
| Delete restriction | Can't remove a spot from favourites while Alert Me is on |
| Admin exemption | Admins not subject to spot limits |
| First user | Automatically given admin role |
| Self-disable | Admins cannot disable their own account |
| Limit reduction | Admin can't reduce limits below current user usage |
| Seasonal spots | Forecast hidden out of season; spot still visible in list |
| Tide irrelevance | Landlocked spots, or spots >100 km from any tidal station, skip tide checks |
| Alert threshold | ≥ 3 good hours in any single contiguous available period |

---

## 13. Deployment

**Production:** Render.com (Frankfurt region)
- Web Service: `gunicorn app:app` (free tier — 512 MB RAM, 0.1 CPU)
- Database: PostgreSQL 16 (free tier, expires May 2026 — upgrade or migrate)
- Auto-deploy: triggered on every push to `main` branch on GitHub
- Free tier caveat: service spins down after 15 min inactivity; cold start ~30–60 seconds

**Local dev:** `python app.py`
- SQLite at `instance/kiteapp.db`
- Secrets via `.env` (comment out `DATABASE_URL` to stay local)
- Werkzeug hot-reload; APScheduler starts in main process only

---

## 14. Known Limitations & TODO

See `TODO.md` for full detail. Key items:

- **Scheduled alerts on Render:** APScheduler doesn't persist on free-tier Render. Replace with a Render Cron Job calling a `/cron/send-alerts` endpoint.
- **UK-only tidal data:** Admiralty API is UK-only. International spots get no tide data.
- **Timezone display:** All times shown as Europe/London. International spots need per-spot timezone from Open-Meteo.
- **Mobile layout:** Not fully responsive. Needs Bootstrap grid work for small screens.
- **Email verification:** Not implemented on registration.
- **Password strength:** Minimum 6 characters only; no complexity enforcement.
- **WhatsApp number verification:** No one-time-code check when a number is saved.
- **Monetisation:** Stripe £3/month subscriptions planned (see TODO.md).
- **Forecast range:** Currently 3 days; plan to extend to 7 days.
- **App name:** Deciding between GoneKiting and Sendit.
