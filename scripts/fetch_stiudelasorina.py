#!/usr/bin/env python3
"""
LocalEvent - StiuDeLaSorina.ro Scraper
Fetch events from stiudelasorina.ro via The Events Calendar REST API.

Site uses WordPress + The Events Calendar (TEC) plugin which exposes
a clean REST API at /wp-json/tribe/events/v1/events.

Returns 500+ events focused on family/kids activities in Bucuresti.

Usage:
  python3 fetch_stiudelasorina.py [--days 90]

Output: JSON array [{slug, name, events: [...]}] on stdout.
"""
import json
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: needs requests. pip install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://stiudelasorina.ro/wp-json/tribe/events/v1/events"

# Mapare categorii stiudelasorina -> categorii LocalEvent
CATEGORY_MAP = {
    "atelier": "atelier",
    "spectacol": "spectacol",
    "spectacol-de-teatru": "teatru",
    "spectacol-atelier": "atelier",
    "spectacol-de-magie": "spectacol",
    "concert": "concert",
    "film": "film",
    "festival": "festival",
    "expozitie": "expozitie",
    "targ": "targ",
    "curs": "atelier",
    "tabara": "workshop",
    "sport": "sport",
    "activitate-in-aer-liber": "outdoor",
    "in-familie": "familie",
    "pentru-parinti": "familie",
    "play-session": "familie",
}

# Mapare vibe bazat pe categorie
VIBE_MAP = {
    "familie": "family",
    "atelier": "intim",
    "spectacol": "intim",
    "teatru": "intim",
    "concert": "loud",
    "festival": "loud",
    "sport": "casual",
    "outdoor": "casual",
    "film": "intim",
    "expozitie": "intim",
    "targ": "casual",
    "workshop": "intim",
}

# Bucuresti coords (default pentru evenimente fără venue precis)
BUCHAREST_LAT = 44.4268
BUCHAREST_LON = 26.1025

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def clean_html(text):
    """Strip HTML tags and decode entities. Cheap but effective."""
    if not text:
        return ""
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&#8211;", "–").replace("&#8212;", "—")
    text = text.replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
    text = text.replace("&#038;", "&").replace("&#39;", "'")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_cost(cost_str):
    """Convert 'Lei90' or '90 Lei' or 'Gratuit' to {price, price_value}."""
    if not cost_str:
        return ("unknown", None)
    cost_lower = cost_str.lower()
    if "gratuit" in cost_lower or "free" in cost_lower or cost_str.strip() == "":
        return ("free", 0)
    # Extract number
    m = re.search(r"(\d+)", cost_str)
    if m:
        return ("paid", int(m.group(1)))
    return ("unknown", None)


def map_category(category_slugs):
    """Map source category slugs to LocalEvent category."""
    if not category_slugs:
        return "familie"  # default for this site
    # First mapped category wins
    for cat in category_slugs:
        mapped = CATEGORY_MAP.get(cat)
        if mapped:
            return mapped
    return "familie"


def map_vibe(category_slugs):
    """Map source categories to LocalEvent vibe."""
    if not category_slugs:
        return "family"
    for cat in category_slugs:
        mapped = VIBE_MAP.get(cat)
        if mapped:
            return mapped
    return "family"


def normalize_event(ev, event_id_counter):
    """Convert TEC API event to LocalEvent schema."""
    # Parse date and time
    start_str = ev.get("start_date", "")  # "2026-09-04 09:00:00"
    end_str = ev.get("end_date", "")
    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        date_str = start_dt.strftime("%Y-%m-%d")
        time_str = start_dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return None

    # Venue
    venue = ev.get("venue") or {}
    venue_name = clean_html(venue.get("venue", "") or "")
    city_name = clean_html(venue.get("city", "") or "București")
    address = clean_html(venue.get("address", "") or "")
    lat = venue.get("latitude") or BUCHAREST_LAT
    lon = venue.get("longitude") or BUCHAREST_LON

    # Categories
    cats = ev.get("categories") or []
    cat_slugs = [c.get("slug", "") for c in cats]
    category = map_category(cat_slugs)
    vibe = map_vibe(cat_slugs)

    # Cost
    cost_str = ev.get("cost", "") or ""
    price, price_value = parse_cost(cost_str)

    # Description (cleaned)
    desc = clean_html(ev.get("description", "") or ev.get("excerpt", "") or "")
    if len(desc) > 500:
        desc = desc[:497] + "..."

    # Title
    title = clean_html(ev.get("title", "") or "")
    if not title:
        return None

    # Build LocalEvent schema
    event_id_counter[0] += 1
    return {
        "id": f"sorina-{event_id_counter[0]:04d}",
        "title": title,
        "category": category,
        "vibe": vibe,
        "date": date_str,
        "time": time_str,
        "venue": venue_name or "București",
        "address": f"{address}, {city_name}".strip(", "),
        "price": price,
        "price_value": price_value if price_value is not None else 0,
        "source": "stiudelasorina",
        "url": ev.get("url", ""),
        "description": desc,
        "highlights": [],
        "duration": "",
        "age": "",
        "tags": cat_slugs,
        "map_url": f"https://maps.google.com/?q={venue_name.replace(' ', '+')}+{city_name}" if venue_name else "",
        "organizer": "StiuDeLaSorina.ro",
        "lat": float(lat) if lat else BUCHAREST_LAT,
        "lon": float(lon) if lon else BUCHAREST_LON,
    }


def fetch_all_events(days_ahead=90):
    """Fetch all upcoming events from TEC API with pagination."""
    start_date = date.today().strftime("%Y-%m-%d")
    end_date = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT23:59:59")

    all_events = []
    page = 1
    per_page = 100

    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "start_date": start_date,
            "end_date": end_date,
            "status": "publish",
        }

        try:
            r = requests.get(API_BASE, params=params, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"  ⚠️ HTTP {r.status_code} on page {page}", file=sys.stderr)
                break

            data = r.json()
            events = data.get("events", [])
            total = data.get("total", 0)
            total_pages = data.get("total_pages", 1)

            print(f"  ✓ Page {page}/{total_pages} ({len(events)} events)", file=sys.stderr)
            all_events.extend(events)

            if page >= total_pages or not events:
                break
            page += 1
            time.sleep(0.5)  # politeness

        except requests.RequestException as e:
            print(f"  ✗ Request failed on page {page}: {e}", file=sys.stderr)
            break

    return all_events


def main():
    days = 90
    if len(sys.argv) > 2 and sys.argv[1] == "--days":
        try:
            days = int(sys.argv[2])
        except ValueError:
            pass

    print(f"Fetching from stiudelasorina.ro (next {days} days)...", file=sys.stderr)

    raw_events = fetch_all_events(days_ahead=days)
    print(f"  → Raw events fetched: {len(raw_events)}", file=sys.stderr)

    counter = [0]
    normalized = []
    skipped = 0
    for ev in raw_events:
        result = normalize_event(ev, counter)
        if result:
            normalized.append(result)
        else:
            skipped += 1

    print(f"  → Normalized: {len(normalized)}, skipped: {skipped}", file=sys.stderr)

    # Group by city (mostly Bucuresti)
    by_city = {}
    for ev in normalized:
        # Extract city from address or default
        addr = ev.get("address", "")
        if "Voluntari" in addr:
            city_slug = "voluntari"
            city_name = "Voluntari"
        elif "Otopeni" in addr:
            city_slug = "otopeni"
            city_name = "Otopeni"
        elif "Clinceni" in addr:
            city_slug = "clinceni"
            city_name = "Clinceni"
        elif "București" in addr or "Bucuresti" in addr:
            city_slug = "bucuresti"
            city_name = "București"
        else:
            city_slug = "bucuresti"
            city_name = "București"

        if city_slug not in by_city:
            by_city[city_slug] = {
                "slug": city_slug,
                "name": city_name,
                "events": []
            }
        by_city[city_slug]["events"].append(ev)

    output = list(by_city.values())
    output.sort(key=lambda c: c["name"])

    print(f"\n✓ Total: {len(normalized)} events from {len(output)} cities", file=sys.stderr)
    for c in output:
        print(f"  - {c['name']}: {len(c['events'])} events", file=sys.stderr)

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
