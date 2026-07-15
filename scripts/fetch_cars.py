#!/usr/bin/env python3
"""
fetch_cars.py — auction sold prices from Bring a Trailer's public results
pages, paired with openly licensed photos from Wikimedia Commons.

Prices/facts come from BaT's results listings (title, sold price, date).
Images are NOT taken from the listings: each car is matched to a stock
photo of that year/make/model on Wikimedia Commons. A credits file
(images/CREDITS-cars.txt) records the Commons source per image.

Usage:
  python3 scripts/fetch_cars.py             # ~40 cars
  python3 scripts/fetch_cars.py --count 60

Writes:
  out/car_items.json
  images/car-<slug>.jpg
  images/CREDITS-cars.txt

Scraping note: BaT can change their markup at any time; if this stops
finding results, the parser (not the idea) needs updating.
"""
import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

CATEGORY = "cars"
RESULTS_URL = "https://bringatrailer.com/auctions/results/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = "Pawndle/1.0 (personal price-guessing game; contact via github)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "images")
OUT_DIR = os.path.join(ROOT, "out")

def http_get(url, retries=3, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", UA)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(4 * (attempt + 1))

# ---------------- BaT results ----------------

def extract_embedded_json(html):
    """BaT embeds completed-auction data as a JS variable on the results page.
    Try the known variable names, then fall back to any large JSON array whose
    objects carry sold_text/title fields."""
    for var in ("auctionsCompletedInitialData", "auctionsInitialData"):
        m = re.search(var + r"\s*=\s*(\{.*?\}|\[.*?\]);\s*\n", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                items = data.get("items") if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    return items
            except json.JSONDecodeError:
                pass
    # generic fallback: any JSON array containing "sold_text"
    for m in re.finditer(r"(\[\{.{200,}?\}\])", html, re.S):
        chunk = m.group(1)
        if '"sold_text"' in chunk or '"sold_for"' in chunk:
            try:
                items = json.loads(chunk)
                if isinstance(items, list):
                    return items
            except json.JSONDecodeError:
                continue
    return None

def parse_html_results(html):
    """Last-ditch parser: pull title + 'Sold for $X on D/M/Y' pairs from raw HTML."""
    results = []
    pattern = re.compile(
        r'title="([^"]{10,140})"[^>]*>.{0,600}?Sold\s+for\s+\$?([\d,]+)\s+on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        re.S | re.I)
    for m in pattern.finditer(html):
        results.append({"title": m.group(1), "price": m.group(2), "date": m.group(3)})
    return results

def normalise(raw):
    """Normalise a raw record from any parser into {title, price, date, url}."""
    title = raw.get("title") or raw.get("name") or ""
    url = raw.get("url") or raw.get("permalink") or ""
    price = raw.get("price")
    date = raw.get("date")
    sold_text = raw.get("sold_text") or raw.get("sold_for") or ""
    if not price and sold_text:
        m = re.search(r"\$\s?([\d,]+)", sold_text)
        if m:
            price = m.group(1)
        m = re.search(r"on\s+(\d{1,2}/\d{1,2}/\d{2,4})", sold_text)
        if m:
            date = m.group(1)
        if re.search(r"bid to|reserve not met", sold_text, re.I):
            return None  # unsold
    if not (title and price):
        return None
    try:
        amount = float(str(price).replace(",", ""))
    except ValueError:
        return None
    if amount < 500:
        return None
    return {"title": title.strip(), "amount": amount, "date": date, "url": url}

def to_iso(d):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", d or "")
    if not m:
        return time.strftime("%Y-%m-%d")
    mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yr < 100:
        yr += 2000
    return f"{yr:04d}-{mo:02d}-{day:02d}"

def car_terms(title):
    """'1990 Porsche 911 Carrera 4' -> (1990, 'Porsche 911 Carrera')"""
    m = re.search(r"\b(19[2-9]\d|20[0-2]\d)\b", title)
    year = m.group(1) if m else None
    rest = title[m.end():].strip() if m else title
    rest = re.sub(r"^[^A-Za-z]*", "", rest)
    words = rest.split()
    core = " ".join(words[:3]) if words else ""
    return year, core

# ---------------- Wikimedia Commons ----------------

def commons_image(search):
    params = {
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": search,
        "gsrnamespace": "6", "gsrlimit": "8",
        "prop": "imageinfo", "iiprop": "url",
        "iiurlwidth": "800",
    }
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    try:
        data = json.loads(http_get(url))
    except Exception:
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        thumb = info.get("thumburl") or ""
        if re.search(r"\.(jpe?g|png)$", thumb, re.I):
            return {"thumb": thumb, "page": info.get("descriptionurl", "")}
    return None

# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--pages", type=int, default=3, help="results pages to try")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    raw = []
    for page in range(1, args.pages + 1):
        url = RESULTS_URL if page == 1 else f"{RESULTS_URL}?page={page}"
        print(f"fetching BaT results page {page}…")
        try:
            html = http_get(url).decode("utf-8", "ignore")
        except Exception as e:
            print(f"  page failed: {e}")
            continue
        found = extract_embedded_json(html)
        if found:
            raw.extend(found)
            print(f"  embedded JSON: {len(found)} records")
        else:
            found = parse_html_results(html)
            raw.extend(found)
            print(f"  html fallback: {len(found)} records")
        time.sleep(3)

    sold = []
    seen_titles = set()
    for r in raw:
        n = normalise(r)
        if n and n["title"] not in seen_titles:
            seen_titles.add(n["title"])
            sold.append(n)
    print(f"{len(sold)} unique sold results parsed")
    if not sold:
        print("ERROR: no results parsed — BaT markup has probably changed. "
              "Open the results page in a browser and check it still says 'Sold for $…'.")
        sys.exit(1)

    rng.shuffle(sold)
    items, credits = [], []
    for rec in sold:
        if len(items) >= args.count:
            break
        year, core = car_terms(rec["title"])
        if not core:
            continue
        search = f"{year} {core}" if year else core
        hit = commons_image(search)
        if not hit and year:
            hit = commons_image(core)  # retry without year
        if not hit:
            print(f"  no commons image for: {rec['title']} — skipped")
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", rec["title"].lower()).strip("-")[:60]
        fname = f"car-{slug}.jpg"
        fpath = os.path.join(IMG_DIR, fname)
        if not os.path.exists(fpath):
            print(f"[{len(items)+1}/{args.count}] {rec['title']}")
            try:
                with open(fpath, "wb") as f:
                    f.write(http_get(hit["thumb"]))
            except Exception as e:
                print(f"  image download failed: {e} — skipped")
                continue
            time.sleep(1)
        credits.append(f"{fname}\t{hit['page']}")
        items.append({
            "id": f"car-{slug}",
            "title": rec["title"] + " (stock photo)",
            "category": CATEGORY,
            "image": fname,
            "soldPrice": rec["amount"],
            "currency": "USD",
            "soldDate": to_iso(rec["date"]),
            "condition": "used",
            "saleType": "auction",
            "shippingIncluded": False,
            "isLot": False,
            "listingUrl": rec["url"]
        })

    with open(os.path.join(OUT_DIR, "car_items.json"), "w") as f:
        json.dump(items, f, indent=2)
    with open(os.path.join(IMG_DIR, "CREDITS-cars.txt"), "a") as f:
        f.write("\n".join(credits) + "\n")
    print(f"\nwrote {len(items)} items -> out/car_items.json")
    if len(items) < 20:
        print("WARNING: under 20 items — cars won't be playable yet. "
              "Re-run with more --pages.")
        sys.exit(1)

if __name__ == "__main__":
    main()
