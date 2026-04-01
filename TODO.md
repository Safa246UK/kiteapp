# KiteApp — Planned Features & Known Tasks

## In Progress / Next Up
- WhatsApp notifications via Twilio (alert users when conditions are good at Alert Me spots)
  - Admin button to force-send all WhatsApp alerts immediately, bypassing any "already sent today" check
- Kite size calculator (suggests kite size based on wind speed + rider weight)

## Security Enhancements
- **Email verification on registration** — new users must click a confirmation link before their account is activated; unverified accounts cannot log in
- **Stronger password rules** — enforce minimum length (e.g. 10 chars), at least one uppercase, one number, and one special character; apply to both registration and admin password reset
- **WhatsApp phone number verification** — phone number is optional; users without one can use the app fully. When a user *does* save a number, send a verification message via Twilio containing a one-time code; number is only activated once confirmed, to prevent someone entering another person's number. No verification needed if the user clears their number or has Alert Me turned off.

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
