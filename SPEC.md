# KiteApp — Full Product Specification

## 1. Overview

KiteApp is a multi-user web application that helps kite surfers decide when and where to kite. It aggregates wind, weather, and tidal forecast data for a set of saved spots and presents a clear go/no-go summary for each location over the next three days. Each user has their own wind preferences, so the same spot can appear green for one rider and amber for another.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite (via SQLAlchemy ORM) |
| Auth | Flask-Login + Flask-Bcrypt (bcrypt password hashing) |
| Frontend | Bootstrap 5, Jinja2 templates |
| Maps | Leaflet.js + OpenStreetMap tiles |
| Weather API | Open-Meteo (free, no key required) |
| Marine API | Open-Meteo Marine (wave height) |
| Tides API | UK Admiralty API (requires subscription key) |
| Email | Flask-Mail (SMTP, password reset) |
| Scheduling | APScheduler (hourly background jobs) |
| Deployment target | Render.com + PostgreSQL (planned) |

---

## 3. User Roles

### Regular User
- Can register and log in
- Can browse all active spots on the Find Spots map
- Can favourite up to N spots (admin-controlled limit, default 3)
- Can enable "Alert Me" on up to M spots (admin-controlled limit, default 2)
- Can view full forecast detail for any spot
- Can add notes to spots
- Can view and edit their own profile
- Can create new spots (auto-added to favourites if under limit)

### Admin
- All regular user capabilities, plus:
- Can create unlimited spots (not auto-favourited)
- Can edit and retire any spot
- Can manage all users (view, disable/enable, reset password)
- Can set global app settings (favourite limits, default tide thresholds)
- Sees retired spots on the Find Spots and Manage Spots screens

---

## 4. Data Models

### User
| Field | Type | Notes |
|---|---|---|
| email | String | Unique, used for login |
| password | String | Bcrypt hashed |
| first_name | String | |
| last_name | String | |
| is_admin | Boolean | First registered user becomes admin |
| is_active | Boolean | Disabled users cannot log in |
| weight_kg | Float | Default 75kg, used for future kite size calculator |
| min_wind | Float | Personal min wind (knots), default 12 |
| max_wind | Float | Personal max wind (knots), default 35 |
| whatsapp_number | String | For future alert notifications |
| available_slots | Text | Comma-separated day_time slots e.g. `mon_morning,sat_afternoon` |

### Spot
| Field | Type | Notes |
|---|---|---|
| name | String | |
| latitude / longitude | Float | |
| description | Text | |
| min_wind / max_wind | Float | Spot-level wind range (knots) |
| min_tide_percent | Float | Unusable below this % of tidal range |
| max_tide_percent | Float | Unusable above this % of tidal range |
| perfect/good/okay/poor/dangerous_directions | String | Comma-separated 16-point compass values |
| is_landlocked | Boolean | Skips all tide logic if true |
| is_retired | Boolean | Hidden from regular users |
| season_start/end month+day | Integer | Optional seasonal window |

### UserFavouriteSpot
Junction table between User and Spot. Has an `is_active` flag — active = "Alert Me" is on.

### SpotNote
Free-text notes left by users on a spot. Visible to all users viewing that spot.

### WeatherCache
One row per spot. Stores the raw Open-Meteo JSON response and a computed `day_summary_json` (green/amber/grey + hours count for today/tomorrow/the next day).

### TideCache
One row per spot. Stores the nearest Admiralty station ID/name/distance and the raw tidal event JSON. If the nearest station is >100km away, the row is created but `station_id` is left null to indicate "no usable station found".

### AdminSettings
Single-row global config: `max_favourite_spots`, `max_active_spots`, `default_min_tide_percent`, `default_max_tide_percent`.

---

## 5. Screens & Features

### Login / Register
- Login with email + password
- Registration collects: first name, surname, email, password, weight (kg), min wind, max wind
- Password reset via emailed token link (1 hour expiry)
- First user to register is automatically made admin

### My Spots (Dashboard)
The main landing page after login.

- Displays the user's favourite spots split into two sections: **Alert Me** (active) and **Favourites**
- Each spot card shows:
  - Spot name (links to detail page)
  - Short description
  - Alert Me toggle switch
  - Three day-condition pills: Today / Tomorrow / The next day
- **Day-condition pills** are coloured:
  - 🟢 Green — 3 or more good hours in daylight
  - 🟡 Amber — 1–2 good hours
  - ⬜ Grey — no good hours or no data yet
  - Shows the count of good hours (e.g. "4h")
- If a spot is currently out of season, the pills are replaced with a grey "🚫 Out of Season" badge
- Counts show current usage vs limits (e.g. "3/4 favourites | 1/2 alert-me")
- **+ Find / Add Spot** button — greyed out with tooltip if user is at their favourite limit (admins always see it active)
- Spots with Alert Me active cannot be removed until Alert Me is turned off

### Find Spots
A map + card grid of all spots.

**Map (Leaflet)**
- All spots plotted as markers
- Clicking a marker opens a popup showing name, description, watcher count, View Details link, and Add to Favourites button
- Retired spots shown at 40% opacity

**Spot cards (below map)**
- Displayed in alphabetical order
- Each card shows: name, description excerpt, watcher count, wind range, favourite/active status badge
- Card footer: View Details button + Add to Favourites button (or "Favourited" if already saved, or disabled with tooltip if at limit)
- **Two-way highlighting**: clicking a card pans the map to that marker and opens its popup; clicking a map marker highlights the corresponding card with a blue outline and scrolls it into view

**Add New Spot button**
- Opens a modal with full spot creation form (see below)
- Greyed out with tooltip for regular users at their favourite limit; always active for admins

**Add Spot form fields:**
- Name, description, latitude/longitude (can be filled by clicking the map)
- Min/max wind (knots)
- Wind direction compass (interactive SVG — click slices to assign ratings: Perfect / Good / Okay / Poor / Dangerous)
- Tide settings: unusable below % / unusable above %
- Landlocked toggle
- Seasonal toggle with start/end date pickers

### Spot Detail
Full forecast for a single spot, personalised to the logged-in user's wind settings.

**Forecast table**
- Columns = one per daylight hour across 3 days
- Sticky date/label column on the left
- Rows:
  - **Time** — background colour = overall slot rating (green = all conditions met, grey = not)
  - **Wind speed** — coloured blue (too light), green (in range), red (too strong) — always coloured
  - **Wind direction** — compass point, coloured by direction rating — only coloured if wind is in range
  - **Gusts** — only coloured if overall slot is green
  - **Weather** — emoji icon + temperature
  - **Wave height** — metres (hidden for landlocked spots)
  - **Tide height** — metres, coloured by usability — only coloured if overall slot is green (hidden for landlocked/no-station spots)
- A time slot is **green** when: wind in user's range AND direction is Perfect/Good/Okay AND tide is usable (or tide is irrelevant)

**Slot rating colours:**
- Perfect: light green
- Good: light blue
- Okay: light yellow
- Poor: light orange
- Dangerous / out of range: light grey

**Out of season banner** — shown above the table when the spot is currently out of season; table is hidden

**Right-hand info panel:**
- Spot description, wind settings, watcher count
- Wind direction compass (read-only, colour-coded)
- Tide Settings card:
  - Shows min/max tide % thresholds
  - Shows "Tide ignored — landlocked body of water" for landlocked spots
  - Shows "No UK tidal station found within range" for spots too far from any station
- Add/remove favourite button
- Alert Me toggle
- Notes section (add note, view existing notes with delete option)

### Profile
Accessible to every user via the Profile nav button, and to admins via Manage Users → View.

Shows:
- Name, email, phone/WhatsApp, weight, wind range, role, join date
- Availability grid (read-only): rows = Morning / Afternoon / Evening, columns = Mon–Sun, ✅ or — in each cell
- Favourite spots (badges)
- Alert Me spots (badges)
- Spots created by this user (badges, linked)
- **Edit button** — opens modal to change: first name, surname, phone, weight, min/max wind, availability grid
- Email address is not editable
- Admins also see: Change Password form, Enable/Disable Account button (not available on own account)

### Manage Spots (Admin only)
Table of all spots with watcher counts, edit and retire/enable buttons.

### Manage Users (Admin only)
- Global settings form: max favourites, max alert-me spots, default min/max tide %
- User table: email, name, phone, role, status, View button

---

## 6. Business Rules

### Condition Evaluation
A time slot is considered **good** when all of the following are true:
1. Wind speed is within the **user's** personal min–max range (not the spot's)
2. Wind direction rating is Perfect, Good, or Okay (as configured per spot)
3. One of:
   - Tide is within the spot's usable % range, OR
   - Spot is landlocked, OR
   - Spot has no UK tidal station within 100km

### Colour Coding (Forecast Table)
- **Wind speed**: always coloured regardless of other conditions
- **Wind direction**: only coloured if wind is in range AND direction is usable
- **Gusts**: only coloured if the whole time slot is green
- **Tide**: only coloured if the whole time slot is green

### Day Summary Pills (Dashboard)
- Computed per user (respects each user's wind settings)
- Green = ≥ 3 good daylight hours
- Amber = 1–2 good daylight hours
- Grey = 0 good hours
- Summaries are pre-computed by the scheduler and cached; no API calls on dashboard load

### Favourite / Alert Me Limits
- Regular users: limited to N favourites and M alert-me spots (admin-set, defaults 3/2)
- Admins: no limit on spot creation, but still subject to favourite and alert-me limits
- A spot with Alert Me active cannot be removed from favourites until Alert Me is turned off
- When a regular user creates a new spot, it is automatically added to their favourites (if under the limit)

### Seasons
- Spots can have an optional seasonal window (start day/month → end day/month)
- Year-wrapping seasons are supported (e.g. November–March)
- Out-of-season spots show a badge on the dashboard and hide the forecast table on the detail page

### Tidal Stations
- The nearest UK Admiralty station is found on first visit and cached
- If the nearest station is >100km away, a record is saved to mark "checked, none found" and the spot is treated as tide-irrelevant from that point
- Live tidal data is fetched on each detail page visit; the last successful response is stored as a fallback if the API is unavailable

---

## 7. Background Processing (APScheduler)

Two jobs run in the background when the server starts:

| Job | Frequency | What it does |
|---|---|---|
| Refresh weather | Hourly | Calls Open-Meteo for all spots and updates WeatherCache |
| Refresh tides | Hourly | Calls Admiralty API for all spots with a valid station and updates TideCache |
| Refresh summaries | Hourly (after weather) | Recomputes day_summary_json for all spots using spot-level wind settings |

On startup, all three jobs also run immediately so data is available without waiting an hour.

---

## 8. External APIs

### Open-Meteo Weather
- **Endpoint**: `api.open-meteo.com/v1/forecast`
- **Data**: hourly wind speed (knots), wind direction, gusts, weather code, temperature; daily sunrise/sunset
- **Window**: 3 days
- **Cost**: free, no key required

### Open-Meteo Marine
- **Endpoint**: `marine-api.open-meteo.com/v1/marine`
- **Data**: hourly wave height
- **Notes**: returns an error for inland locations; handled gracefully

### UK Admiralty Tidal API
- **Endpoint**: `admiraltyapi.azure-api.net/uktidalapi/api/V1`
- **Data**: list of all UK tidal stations; high/low tide events for a given station
- **Key**: required (`ADMIRALTY_API_KEY` environment variable)
- **Limit**: free tier has a daily request quota — the app caches aggressively to minimise calls
- **Coverage**: UK coastal stations only; spots >100km from any station are treated as tide-irrelevant

---

## 9. Configuration (Environment Variables)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing key |
| `ADMIRALTY_API_KEY` | UK tidal API key |
| `MAIL_SERVER` | SMTP server (default: smtp.gmail.com) |
| `MAIL_PORT` | SMTP port (default: 587) |
| `MAIL_USE_TLS` | TLS on/off (default: True) |
| `MAIL_USERNAME` | SMTP login |
| `MAIL_PASSWORD` | SMTP password |
| `MAIL_DEFAULT_SENDER` | From address for password reset emails |

---

## 10. Planned / Not Yet Built

- **Kite size calculator** — suggest kite size from wind speed + rider weight
- **WhatsApp alerts via Twilio** — notify Alert Me users when conditions are good
- **7-day forecast** — extend from 3 days to 7 (Open-Meteo and Admiralty both support this)
- **GitHub Actions** — scheduled daily conditions check to trigger WhatsApp alerts
- **Deploy to Render.com** — swap SQLite for PostgreSQL for production
- **Mobile responsive testing**
