#!/usr/bin/env python3
"""
LocalEvent - ZileSiNopti.ro Scraper
Fetch events from zilesinopti.ro via:
  1. eveniment-sitemap.xml → list of all event URLs (1000+)
  2. Each event page → JSON-LD MusicEvent with structured data

ZileSiNopti.ro is Romania's largest cultural aggregator. The WordPress REST
API is blocked, but JSON-LD structured data on each page is gold: MusicEvent
schema with startDate, location (lat/lon), address, image.

Strategy:
- Fetch sitemap (1000 URLs)
- For each URL: fetch HTML, extract JSON-LD MusicEvent block
- Filter: skip past events (startDate < today) and non-EventScheduled
- Normalize to LocalEvent schema

Usage:
  python3 fetch_zilesinopti.py [--days 90] [--limit 200]

Output: JSON array [{slug, name, events: [...]}] on stdout.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: needs requests + beautifulsoup4. pip install requests beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)

SITEMAP_URL = "https://zilesinopti.ro/eveniment-sitemap.xml"

# Mapare categorii URL slug → LocalEvent category
CATEGORY_MAP = {
    "concerte": "concert",
    "festivaluri": "festival",
    "teatru": "teatru",
    "spectacole": "spectacol",
    "expozitii": "expozitie",
    "filme": "film",
    "stand-up": "standup",
    "petreceri": "party",
    "workshop-uri": "workshop",
    "conferinte": "conferinta",
    "sport": "sport",
    "familie": "familie",
    "copii": "familie",
    "targuri": "targ",
}

# Mapare oraș → slug LocalEvent
CITY_MAP = {
    "bucuresti": ("bucuresti", "București"),
    "bucurești": ("bucuresti", "București"),
    "cluj-napoca": ("cluj-napoca", "Cluj-Napoca"),
    "timisoara": ("timisoara", "Timișoara"),
    "timișoara": ("timisoara", "Timișoara"),
    "iasi": ("iasi", "Iași"),
    "iași": ("iasi", "Iași"),
    "constanta": ("constanta", "Constanța"),
    "constanța": ("constanta", "Constanța"),
    "sibiu": ("sibiu", "Sibiu"),
    "craiova": ("craiova", "Craiova"),
    "brasov": ("brasov", "Brașov"),
    "brașov": ("brasov", "Brașov"),
    "ploiesti": ("ploiesti", "Ploiești"),
    "oradea": ("oradea", "Oradea"),
    "arad": ("arad", "Arad"),
    "galati": ("galati", "Galați"),
    "braila": ("braila", "Brăila"),
    "pitesti": ("pitesti", "Pitești"),
    "targu-mures": ("targu-mures", "Târgu Mureș"),
    "suceava": ("suceava", "Suceava"),
    "bacau": ("bacau", "Bacău"),
    "baia-mare": ("baia-mare", "Baia Mare"),
    "buzau": ("buzau", "Buzău"),
    "satu-mare": ("satu-mare", "Satu Mare"),
    "piatra-neamt": ("piatra-neamt", "Piatra Neamț"),
    "drobeta-turnu-severin": ("drobeta-turnu-severin", "Drobeta-Turnu Severin"),
    "focsani": ("focsani", "Focșani"),
    "targoviste": ("targoviste", "Târgoviște"),
    "tulcea": ("tulcea", "Tulcea"),
    "alba-iulia": ("alba-iulia", "Alba Iulia"),
    "deva": ("deva", "Deva"),
    "resita": ("resita", "Reșița"),
    "slobozia": ("slobozia", "Slobozia"),
    "vaslui": ("vaslui", "Vaslui"),
    "calarasi": ("calarasi", "Călărași"),
    "botosani": ("botosani", "Botoșani"),
    "voluntari": ("voluntari", "Voluntari"),
    "otopeni": ("otopeni", "Otopeni"),
    "clinceni": ("clinceni", "Clinceni"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


def get_city_slug(name):
    """Normalize city name to LocalEvent slug."""
    if not name:
        return None, None
    slug_key = name.lower().strip().replace(" ", "-")
    return CITY_MAP.get(slug_key, (None, name))


def get_category_from_url(url):
    """Extract category from URL like /evenimente/concerte/.../"""
    # URL-urile au slugul evenimentului, NU categoria
    # Categoria e în JSON-LD sau în link-urile categorie-eveniment
    # Deci nu o putem extrage din URL direct — o setăm default
    return "concert"  # Majoritatea evenimentelor pe ZileSiNopți sunt concerte/muzică


def parse_jsonld(html_text):
    """Extract MusicEvent JSON-LD block from HTML."""
    # Caută toate blocurile JSON-LD
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    blocks = re.findall(pattern, html_text, re.DOTALL)

    for block in blocks:
        try:
            data = json.loads(block.strip())
            # Dacă e @graph, caut MusicEvent
            if isinstance(data, dict):
                graph = data.get("@graph", [data])
                for item in graph:
                    if isinstance(item, dict) and item.get("@type") == "MusicEvent":
                        return item
                    # Uneori @type e list
                    types = item.get("@type") if isinstance(item, dict) else None
                    if isinstance(types, list) and "MusicEvent" in types:
                        return item
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "MusicEvent":
                        return item
        except json.JSONDecodeError:
            continue
    return None


def normalize_event(event_data, source_url, event_id_counter):
    """Convert JSON-LD MusicEvent to LocalEvent schema."""
    name_raw = (event_data.get("name") or "").strip()
    # Decode HTML entities (some titles have them)
    name = (name_raw
            .replace("&#8211;", "–").replace("&#8212;", "—")
            .replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
            .replace("&#038;", "&").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&nbsp;", " "))
    if not name:
        return None

    # startDate
    start_str = event_data.get("startDate")
    if not start_str:
        return None
    try:
        # Format: "2026-10-23T19:00:00+03:00"
        dt = datetime.fromisoformat(start_str)
    except (ValueError, TypeError):
        return None

    event_date = dt.date()
    event_time = dt.strftime("%H:%M")

    # Skip past events
    today = date.today()
    if event_date < today:
        return None

    # Check status
    status = event_data.get("eventStatus", "")
    if status and "EventScheduled" not in status:
        # Skip cancelled/postponed
        if "EventCancelled" in status or "EventPostponed" in status:
            return None

    # Location
    location = event_data.get("location") or {}
    if not isinstance(location, dict):
        return None
    venue_name = (location.get("name") or "").strip()
    address = location.get("address") or {}
    if isinstance(address, dict):
        street = address.get("streetAddress", "") or ""
        city = (address.get("addressLocality", "") or "").strip()
    else:
        street = str(address) if address else ""
        city = ""

    geo = location.get("geo") or {}
    lat = geo.get("latitude") if isinstance(geo, dict) else None
    lon = geo.get("longitude") if isinstance(geo, dict) else None

    # Category - default "concert" pentru ZileSiNopți (majoritatea)
    # Vom rafina pe viitor
    category = get_category_from_url(source_url)

    # Description
    desc = (event_data.get("description") or "").strip()
    # Decode entities
    desc = (desc
            .replace("&#8211;", "–").replace("&#8212;", "—")
            .replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
            .replace("&#038;", "&").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&nbsp;", " "))
    if desc.startswith(name):
        # Uneori description începe cu numele, îl tăiem
        desc = desc[len(name):].strip()
    if len(desc) > 600:
        desc = desc[:597] + "..."

    # Image
    image = event_data.get("image") or []
    if isinstance(image, str):
        image = [image]
    image_url = image[0] if image else ""

    # URL
    url = event_data.get("url") or source_url

    # ID
    event_id_counter[0] += 1
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:30]
    event_id = f"zsn-{slug}-{event_id_counter[0]:04d}"

    return {
        "id": event_id,
        "title": name,
        "category": category,
        "vibe": "loud",  # Default pentru muzică/concerte
        "date": event_date.strftime("%Y-%m-%d"),
        "time": event_time,
        "venue": venue_name or city or "București",
        "address": f"{street}, {city}".strip(", "),
        "price": "unknown",  # JSON-LD nu include preț
        "price_value": 0,
        "source": "zilesinopti",
        "url": url,
        "description": desc,
        "highlights": [],
        "duration": "",
        "age": "",
        "tags": [],
        "map_url": f"https://maps.google.com/?q={venue_name.replace(' ', '+')}+{city}" if venue_name else "",
        "organizer": "zilesinopti.ro",
        "image": image_url,
        "lat": float(lat) if lat else 0.0,
        "lon": float(lon) if lon else 0.0,
        "city_locality": city,
    }


def fetch_event_page(session, url, event_id_counter):
    """Fetch single event page and extract event data."""
    try:
        r = session.get(url, timeout=15, headers=HEADERS)
        if r.status_code != 200:
            return None
        jsonld = parse_jsonld(r.text)
        if not jsonld:
            return None
        return normalize_event(jsonld, url, event_id_counter)
    except Exception as e:
        print(f"  ✗ Error on {url}: {e}", file=sys.stderr)
        return None


def fetch_sitemap_urls(session, limit=None):
    """Fetch and parse eveniment-sitemap.xml."""
    print(f"Fetching sitemap {SITEMAP_URL}...", file=sys.stderr)
    try:
        r = session.get(SITEMAP_URL, timeout=30, headers=HEADERS)
        if r.status_code != 200:
            print(f"  ✗ Sitemap HTTP {r.status_code}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"  ✗ Sitemap fetch failed: {e}", file=sys.stderr)
        return []

    # Parse URL-uri (cu sau fără namespace)
    urls = re.findall(r'<loc>(https://zilesinopti\.ro/evenimente/[^<]+)</loc>', r.text)
    # Skip the /evenimente/ index page itself
    urls = [u for u in urls if u.rstrip('/').split('/')[-1]]

    print(f"  ✓ Sitemap: {len(urls)} URLs", file=sys.stderr)

    if limit and len(urls) > limit:
        # Limităm la primele N pentru test rapid
        print(f"  ⚠️ Limiting to first {limit} URLs (for testing)", file=sys.stderr)
        urls = urls[:limit]

    return urls


def main():
    days = 90
    limit = None
    if "--days" in sys.argv:
        try:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass
    if "--limit" in sys.argv:
        try:
            idx = sys.argv.index("--limit")
            limit = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass

    print(f"Fetching from zilesinopti.ro (next {days} days, limit={limit})...", file=sys.stderr)

    session = requests.Session()
    urls = fetch_sitemap_urls(session, limit=limit)

    if not urls:
        print("No URLs found", file=sys.stderr)
        sys.exit(0)

    counter = [0]
    normalized = []
    skipped = 0
    past = 0

    # Fetch în paralel
    print(f"Fetching {len(urls)} event pages in parallel (max workers=10)...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_event_page, session, url, counter): url
            for url in urls
        }

        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 50 == 0:
                print(f"  → {done_count}/{len(urls)} processed", file=sys.stderr)

            result = future.result()
            if result is None:
                skipped += 1
            else:
                # Double-check date
                event_date = datetime.strptime(result["date"], "%Y-%m-%d").date()
                if event_date < date.today():
                    past += 1
                elif event_date > date.today() + timedelta(days=days):
                    skipped += 1
                else:
                    normalized.append(result)

    print(f"\n  → Processed: {done_count}, normalized: {len(normalized)}, past: {past}, skipped: {skipped}", file=sys.stderr)

    # Grupare pe orașe
    by_city = {}
    for ev in normalized:
        city_loc = ev.pop("city_locality", "")
        slug, name = get_city_slug(city_loc)
        if not slug:
            # Fallback: încearcă din address
            addr = ev.get("address", "")
            for key, (s, n) in CITY_MAP.items():
                if key in addr.lower():
                    slug = s
                    name = n
                    break
        if not slug:
            # Default la București
            slug = "bucuresti"
            name = "București"

        if slug not in by_city:
            by_city[slug] = {
                "slug": slug,
                "name": name,
                "events": []
            }
        by_city[slug]["events"].append(ev)

    output = list(by_city.values())
    output.sort(key=lambda c: c["name"])

    print(f"\n✓ Total: {len(normalized)} events from {len(output)} cities", file=sys.stderr)
    for c in output[:20]:
        print(f"  - {c['name']}: {len(c['events'])}", file=sys.stderr)

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
