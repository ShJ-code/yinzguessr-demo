# YinzGuessr — local demo

A single-player version of the YinzGuessr final-project idea. You're dropped into a
random Google Street View panorama in Pittsburgh. You look around 360°, walk down
the street, then pin your guess on a Google map. Three rounds, up to 5,000 points
each.

This demo has no accounts and no multiplayer. It's plain Django + SQLite, so it
runs with one `runserver`.

## Run it

You need Python 3.12 (what the course uses; 3.10+ works), a Google Maps Platform
API key, and internet access.

```bash
cd yinzguessr-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then paste your key after GOOGLE_MAPS_API_KEY=
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000.

**Getting the key:**

1. In the [Google Cloud console](https://console.cloud.google.com/), create a
   project and link a billing account. Google needs a card on file even when
   usage stays inside the free monthly amounts.
2. Under **APIs & Services → Library**, enable **Maps JavaScript API** and
   **Street View Static API**.
3. Under **APIs & Services → Credentials**, create an API key and restrict it to
   those two APIs.
4. Optionally, cap daily usage on each API's **Quotas** page so the key can never
   cost money.

**Tests** (no network needed; Google is faked):

```bash
python manage.py test
```

## How a round works

1. The page calls `POST /api/games`.
2. The server picks a random point inside a rectangle around Pittsburgh. It asks
   Google's free
   [Street View metadata](https://developers.google.com/maps/documentation/streetview/metadata)
   endpoint for an outdoor panorama within 300 m of it. It keeps only Google's own
   imagery (not user photo spheres) and tries another point, up to 15 times, when
   there's none.
3. The round stores only the **panorama ID**. The browser gets the ID and shows it
   with Google's Street View viewer. The address and street-name labels are
   hidden, but you can look around and walk.
4. The player clicks the Google map and presses **Guess**.
5. `POST /api/rounds/<id>/guess` looks the panorama's location up again (free) and
   scores the guess with the haversine distance: `round(5000 · e^(−d / 2500 m))`.
   Being 1 km off keeps about 67% of the points (3,352), and 5 km off keeps about
   14% (677). The true location is returned once, for the reveal map, and is never
   saved. The distance is always measured from the panorama the round started on.

### Why the location isn't stored

Google's terms allow keeping panorama IDs but don't give permission to store
Street View coordinates. They also say not to rely on a panorama ID long-term,
because IDs can change. A round lasts minutes, so keeping the ID for the round
and looking up the location at guess time stays inside both rules.

## Google usage and cost

| What | Billed as | Free per month |
| --- | --- | --- |
| Street View metadata lookups (server) | Street View Metadata | Unlimited, no charge |
| Showing a panorama in the browser | Dynamic Street View | 5,000 |
| The guess and reveal maps | Dynamic Maps | 10,000 |

A 3-round game uses about 3 panoramas and a few map loads. Current prices are on
[Google's pricing page](https://developers.google.com/maps/billing-and-pricing/pricing).

## API

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/games` | Start a game; returns round 1 (panorama ID only) |
| `POST` | `/api/rounds/<id>/guess` | Body `{"lat": .., "lng": ..}`; returns distance, score, true location |
| `POST` | `/api/games/<id>/rounds` | Start the next round (only after the current one is guessed) |
| `GET` | `/api/games/<id>` | Summary for the results screen (no true locations) |

Errors come back as `{"error": "..."}` with these statuses: 400 for a bad guess
body, 404 for an unknown id, 409 when the request doesn't fit the game state (for
example guessing twice), and 503 when Google has no panorama, can't be reached, or
rejects the key. POSTs use Django's CSRF protection. The page sends the
`csrftoken` cookie back as `X-CSRFToken`.

## Where things are

| File | What it holds |
| --- | --- |
| `game/streetview.py` | Random panorama picking and panorama lookups through Street View metadata |
| `game/scoring.py` | Haversine distance and the score curve |
| `game/services.py` | Game rules: start game, next round, submit guess |
| `game/views.py`, `game/urls.py` | The page and the JSON API |
| `game/models.py` | `Game` and `Round` |
| `game/templates/game/index.html` | The single page (start, play, reveal, results) |
| `game/static/game/game.js` | Front-end logic: Google Maps loader, Street View, maps, fetch calls |
| `game/static/game/game.css` | Steel + bridge-gold styling |
| `game/tests.py` | 27 tests: scoring, panorama picking, full 3-round API flow, CSRF |

## Google's rules this follows

- **Google maps only.** Street View can't share a screen with a non-Google map
  ([terms §3.2.3(e)](https://cloud.google.com/maps-platform/terms)), so both the
  guess map and the reveal map are Google maps.
- **Attribution stays visible.** Google's logo and copyright stay on the panorama
  and the maps. The guess panel sits above the attribution row.
- **No pegman.** The maps hide the Street View pegman, so players can't drop into
  Street View from the guess map.
- **Map ID:** markers need one. `DEMO_MAP_ID` (the default) is Google's testing
  ID; set `GOOGLE_MAPS_MAP_ID` to your own for the real project.
- **Referrer policy:** settings send `Referrer-Policy: strict-origin-when-cross-origin`.
  If you later restrict the key to your website, Google can then see the page's
  origin.
- **Splitting the key:** a key restricted to your website can't be used for the
  server's metadata lookups. When deploying, use two keys: a browser key
  restricted to your site, and a server key restricted to your server.

## Known limits of the demo

- **Spots can fall outside the city.** They're drawn from a rectangle around
  Pittsburgh, so a few rounds land just outside city limits.
- **Best with WebGL.** Street View works best with WebGL. In Chrome, keep
  **Settings → System → Use graphics acceleration when available** turned on.
- **A determined player can cheat.** The browser receives the panorama ID, and
  someone could look it up. That's fine for casual play.

## Troubleshooting

| You see | Do this |
| --- | --- |
| "Google Maps API key missing" on the start page | Put your key on the `GOOGLE_MAPS_API_KEY=` line of `.env` and restart `runserver` |
| "Google Street View answered REQUEST_DENIED" | Enable the **Street View Static API** for the key, and check the key isn't restricted to websites |
| "Google rejected the Maps API key" | Enable the **Maps JavaScript API** for the key, and check billing is linked |
| "No Street View panorama found after 15 random spots" | Press **Try again** |
| Maps show "For development purposes only" | Billing isn't linked to the key's project |

## Citations

- [Django](https://www.djangoproject.com/) 5.2: web framework (BSD)
- [Google Maps JavaScript API](https://developers.google.com/maps/documentation/javascript):
  Street View and maps. Includes Google's bootstrap loader snippet (Apache 2.0).
- [Street View Static API metadata](https://developers.google.com/maps/documentation/streetview/metadata):
  free panorama lookups
- [Barlow Semi Condensed](https://fonts.google.com/specimen/Barlow+Semi+Condensed):
  typeface (SIL OFL), via Google Fonts
- [requests](https://requests.readthedocs.io/) and
  [python-dotenv](https://github.com/theskumar/python-dotenv)
- AI assistance: the initial demo scaffold was generated with Claude (Anthropic) and
  reviewed by the team. *(Add your own notes here on how you used and verified it,
  as the course's AI policy requires.)*
