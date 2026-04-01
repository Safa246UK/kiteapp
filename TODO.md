# KiteApp — Planned Features & Known Tasks

## In Progress / Next Up
- Kite size calculator (suggests kite size based on wind speed + rider weight)
- WhatsApp notifications via Twilio (alert users when conditions are good at Alert Me spots)

## Planned Features
- Extend forecast from 3 days to 7 days
  - Change `forecast_days: 3 → 7` in Open-Meteo call
  - Change tidal API `duration: 4 → 7`
  - Update `range(3) → range(7)` in summary functions
  - Update dashboard card layout (day names instead of Today/Tomorrow/The next day)
- User-facing kite size calculator page
- Mobile / responsive layout testing and fixes

## Deployment
- Deploy to Render.com with PostgreSQL (replace SQLite)
- Set up GitHub Actions for scheduled daily conditions check (to trigger WhatsApp alerts)

## Done
- Day condition squares on dashboard (green/amber/grey)
- Per-user wind settings driving forecast colour coding
- Registration with first name, surname, weight, wind preferences
- Season windows per spot
- Landlocked spot toggle (tide ignored)
- Spots with no nearby UK tidal station treated as tide-irrelevant
- Admin unlimited spot creation (no auto-favourite for admins)
- Find Spots: map/card two-way highlighting, Add to Favourites in cards and popups
- User profile page with availability grid (day × morning/afternoon/evening)
- Refactor: shared bcrypt, deduplicated weather logic, removed debug route
