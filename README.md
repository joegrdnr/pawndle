# Pawndle

Daily game: two real eBay sold items, pick the one that went for more. 10 rounds, one category a day.

## Files

- `index.html` — the game
- `admin.html` — private builder (not linked from the game)
- `items.json` — shared data file: `{ "settings": { "minPriceGap": 5 }, "items": [...] }`
- `images/` — put item photos here; items reference them by filename

## Deploy (GitHub Pages)

Push the folder to a repo, enable Pages on the main branch. No build step.
To test locally, run `python3 -m http.server` in the folder and open
http://localhost:8000 — opening index.html straight from disk won't work
because the browser blocks `fetch("items.json")` on file:// URLs.

## Workflow

1. Save item photos into `images/`.
2. Open `admin.html`, enter items (the batch autosaves in your browser).
3. **Export game data** → commit the downloaded `items.json` (listing URLs stripped).
4. **Export backup** → keep privately; this one includes `listingUrl`. Never commit it.

## Rules baked in

- A category needs **20+ items** to run (10 pairs, each item used once per game).
- Pairs only form when prices differ by more than `minPriceGap` (default 5).
- Daily category rotates through the sorted category list by date; the same
  day gives every player the same category and the same 10 pairs.
- Daily is locked to one play per day; free play is unlimited and doesn't
  touch the streak.
