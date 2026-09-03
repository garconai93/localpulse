#!/usr/bin/env python3
"""
LocalEvent - Event Scraper
Scrape events from iabilet.ro for all 7 cities and emit new events to stdout (JSON).

Output: JSON array of new events, one per city, ready to be merged into events.json.

Usage:
  python3 fetch_events.py [--days 30]

Strategy:
- For each city, scrape iabilet.ro/bilete-in-{slug}
- Parse event blocks: title, date, time, venue, category, price, url
- Skip events already in input events.json (passed as first arg or read from disk)
- Output: list of {city, events: [...]} for the merge step
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: needs requests + beautifulsoup4. pip install requests beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)

CITIES = {
    "bucuresti":   "București",
    "cluj-napoca": "Cluj-Napoca",
    "timisoara":   "Timișoara",
    "iasi":        "Iași",
    "constanta":   "Constanța",
    "sibiu":       "Sibiu",
    "craiova":     "Craiova",
}

# Romanian month abbreviations (iabilet format)
RO_MONTHS = {
    'ian': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'mai': '05', 'iun': '06',
    'iul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'noi': '11', 'dec': '12',
}
RO_DOW = {
    'Lu': 0, 'Ma': 1, 'Mi': 2, 'Jo': 3, 'Vi': 4, 'Sâ': 5, 'Sâ': 5, 'Sâm': 5, 'Du': 6,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


def normalize_date(text):
    """Parse Romanian dates like 'Vi, 4 sep', 'Sâ, 5 sep', '1-3 sep', '18-19 sep', '4 sep'."""
    text = text.strip().lower()
    text = text.replace('â', 'a').replace('î', 'i')  # Normalize diacritics

    # Range: '1-3 sep' or '18-19 sep'
    m = re.search(r'(\d{1,2})-(\d{1,2})\s+([a-z]{3})', text)
    if m:
        return None, None  # multi-day events — skip for now (too complex for MVP)

    # Single: 'Vi, 4 sep'
    m = re.search(r'(\d{1,2})\s+([a-z]{3})', text)
    if m:
        day, mon = m.groups()
        mm = RO_MONTHS.get(mon)
        if mm:
            # Year: assume current year
            from datetime import datetime
            year = datetime.now().year
            return f"{year}-{mm}-{int(day):02d}"

    return None


def normalize_category(text):
    """Map Romanian category labels to our taxonomy."""
    text = text.lower().strip()
    mapping = {
        'concert': 'concert', 'concerte': 'concert', 'rock': 'concert', 'pop': 'concert',
        'pop rock': 'concert', 'metal': 'concert', 'folk': 'concert', 'jazz': 'concert',
        'hip hop': 'concert', 'latino': 'concert', 'world music': 'concert',
        'muzica lautareasca': 'concert', 'muzica de petrecere': 'concert',
        'electronica': 'party', 'party': 'party', 'trap': 'concert', 'k-pop': 'concert',
        'teatru': 'teatru', 'spectacol': 'spectacol', 'spectacole culturale': 'teatru',
        'spectacole pentru copii': 'family',
        'stand-up': 'standup', 'stand-up comedy': 'standup',
        'festival': 'festival', 'festivaluri': 'festival',
        'expo': 'expo', 'expo / muzee': 'expo',
        'cinema': 'cinema',
        'workshop': 'workshop', 'conferinta': 'conferinta', 'conferinte': 'conferinta',
        'boardgames': 'boardgames',
        'clasică': 'concert', 'clasica si balet': 'concert', 'musical': 'spectacol',
        'sport': 'sport', 'degustari': 'workshop', 'retro': 'concert',
        'blues': 'concert',
        'colinde': 'concert', 'populara': 'concert', 'muzica populara': 'concert',
        'turneu': 'concert', 'merchandise': 'concert',
        'book club': 'workshop', 'spiritualitate': 'workshop',
        'alcool': '',  # skip
    }
    for key, val in mapping.items():
        if key in text:
            return val
    return 'concert'  # default fallback


def determine_vibe(category):
    """Heuristic vibe mapping."""
    vibe_map = {
        'concert': 'loud',
        'teatru': 'intim',
        'standup': 'loud',
        'party': 'loud',
        'expo': 'intim',
        'cinema': 'intim',
        'festival': 'casual',
        'boardgames': 'casual',
        'workshop': 'casual',
        'family': 'family',
        'conferinta': 'intim',
        'spectacol': 'intim',
        'sport': 'casual',
    }
    return vibe_map.get(category, 'casual')


def scrape_city(city_slug, city_name, existing_ids, days=30):
    """Scrape iabilet.ro for one city, return list of new events."""
    url = f"https://m.iabilet.ro/bilete-in-{city_slug}/"
    print(f"[{city_slug}] Fetching {url}...", file=sys.stderr)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[{city_slug}] ERROR: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, 'lxml')
    events = []
    today = time.strftime("%Y-%m-%d")

    # Find all event blocks: links followed by content
    # iabilet pattern: each event is wrapped in <a> with class containing "TownPage"
    event_links = soup.find_all('a', href=re.compile(r'/bilete-'))

    for link in event_links:
        try:
            href = link.get('href', '')
            if not href:
                continue

            # Extract slug from URL for unique ID
            url_slug = re.search(r'/bilete-(.+?)-(?:12|13)\d{3,4}/?$', href)
            if not url_slug:
                url_slug = re.search(r'/bilete-(.+?)/?$', href)
            if not url_slug:
                continue
            event_id_base = url_slug.group(1)

            # Generate unique ID (city-event)
            full_id = f"{city_slug[:3]}-{event_id_base[:30]}-{hash(href) % 10000}"
            if full_id in existing_ids:
                continue  # skip duplicate

            # Extract text content
            full_text = link.get_text(' ', strip=True)
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]

            # Title is usually the longest non-empty line before the venue
            title = None
            venue = None
            date_text = None
            category_text = None

            # Look for category first (italic span)
            cat_span = link.find('span', class_=re.compile(r'(Stand-up|Teatru|Concert|Festival|Expo)'))
            if cat_span:
                category_text = cat_span.get_text(strip=True)

            # Title — find longest text in link
            for line in lines:
                if len(line) > 20 and not any(d in line.lower() for d in ['/', 'bilete', 'categorii']):
                    if not title:
                        title = line
                        break

            # Venue — text after "//" pattern
            venue_match = re.search(r'//\s*([^/]+?)(?:,\s*\w+)?$', full_text)
            if venue_match:
                venue = venue_match.group(1).strip()

            # Date — look for day + month pattern
            date_match = re.search(r'(\d{1,2}\s+(?:ian|feb|mar|apr|mai|iun|iul|aug|sep|oct|noi|dec))', full_text.lower())
            if date_match:
                date_text = date_match.group(0)
            # Or check parent for day names
            if not date_text:
                # Look for sibling/parent text containing date
                parent_text = link.parent.get_text() if link.parent else ''
                date_match = re.search(r'\b(Lu|Ma|Mi|Jo|Vi|Sa|Du),?\s+(\d{1,2}\s+\w{3})\b', parent_text)
                if date_match:
                    date_text = date_match.group(2)

            if not title or not date_text:
                continue

            # Normalize date
            iso_date = normalize_date(date_text)
            if not iso_date or iso_date < today:
                continue  # skip past or unparseable

            # Time — not always available, default to 20:00
            time_match = re.search(r'(\d{1,2}):(\d{2})', full_text)
            event_time = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else "20:00"

            # Category fallback
            category = normalize_category(category_text) if category_text else 'concert'

            # Price — usually "GRATUIT" or empty for paid (we'll mark paid with default 50 lei)
            is_free = 'GRATUIT' in full_text.upper() or 'gratuit' in full_text.lower()

            full_url = urljoin('https://m.iabilet.ro', href)

            event = {
                "id": full_id,
                "title": title[:120],
                "category": category,
                "vibe": determine_vibe(category),
                "date": iso_date,
                "time": event_time,
                "venue": venue or f"loc în {city_name}",
                "address": venue or f"loc în {city_name}",
                "price": "free" if is_free else "paid",
                "price_value": 0 if is_free else 60,
                "source": "iabilet",
                "url": full_url,
                "description": f"{title} — eveniment la {venue or 'locație necunoscută'} din {city_name}.",
                "highlights": [f"dată: {iso_date}", f"ora: {event_time}", f"categorie: {category}"],
                "duration": "1h 30min",
                "age": "All ages",
                "tags": [category, city_slug],
                "map_url": f"https://maps.google.com/?q={venue or city_name}".replace(' ', '+'),
                "organizer": "iabilet.ro",
                "scraped_at": today,
            }
            events.append(event)
            existing_ids.add(full_id)

        except Exception as e:
            print(f"[{city_slug}] Parse error: {e}", file=sys.stderr)
            continue

    print(f"[{city_slug}] Found {len(events)} new events", file=sys.stderr)
    return events



def scrape_bilete_ro(city_slug, city_name, existing_ids, days=30):
    """Scrape bilete.ro/calendar/ for events across all cities.
    Bilete.ro nu filtreaza pe oras in URL, deci luam calendarul complet."""
    url = "https://www.bilete.ro/calendar/"
    print(f"[bilete.ro] Fetching calendar {url}...", file=sys.stderr)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[bilete.ro] ERROR: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, 'lxml')
    events = []
    today = time.strftime("%Y-%m-%d")

    # Calendar links: /calendar/septembrie-2026/05/ for each day
    day_links = soup.find_all('a', href=re.compile(r'/calendar/[^/]+/\d+/'))

    for link in day_links:
        href = link.get('href', '')
        date_match = re.search(r'/(\d+)/$', href)
        if not date_match:
            continue
        day_num = int(date_match.group(1))
        # Get month from surrounding context (e.g., "Septembrie 2026")
        parent = link.parent
        month_year_text = ''
        for sibling in parent.find_previous_siblings():
            if '2026' in sibling.get_text():
                month_year_text = sibling.get_text()
                break
        # Simple month detection (will be improved if needed)
        if 'Septembrie' in month_year_text or not month_year_text:
            month_num = 9
        elif 'Octombrie' in month_year_text:
            month_num = 10
        else:
            continue  # skip non-relevant months

        iso_date = f"2026-{month_num:02d}-{day_num:02d}"
        if iso_date < today:
            continue

        # Fetch the day page for actual events
        try:
            day_url = urljoin('https://www.bilete.ro', href)
            day_resp = requests.get(day_url, headers=HEADERS, timeout=20)
            day_resp.raise_for_status()
            day_soup = BeautifulSoup(day_resp.text, 'lxml')
        except Exception as e:
            continue

        # Find event links on day page (they're in a list)
        event_links = day_soup.find_all('a', href=re.compile(r'/(?!calendar|categorii|info)[a-z0-9-]+/?$'))

        for ev_link in event_links:
            try:
                ev_href = ev_link.get('href', '')
                if not ev_href or ev_href.startswith('#') or '/mvc/' in ev_href:
                    continue

                # Get event title
                title_el = ev_link.find(['h3', 'h2', 'span'])
                title = title_el.get_text(strip=True) if title_el else ev_link.get_text(strip=True).split('\n')[0]
                if not title or len(title) < 5:
                    continue

                # Get city from text near title (usually "Bucuresti" appears after)
                text_content = ev_link.get_text(' ', strip=True)
                # City detection
                detected_city = None
                for slug, name in CITIES.items():
                    if name in text_content or name.lower() in text_content.lower():
                        detected_city = (slug, name)
                        break
                if not detected_city:
                    continue  # skip if not in our 7 cities

                # Unique ID
                slug_part = re.sub(r'[^a-z0-9-]', '', ev_href)[:30]
                full_id = f"{detected_city[0][:3]}-br-{slug_part}-{hash(ev_href) % 10000}"
                if full_id in existing_ids:
                    continue

                # Time — try to extract from event page later, default 20:00
                event_time = "20:00"

                # Price — default paid 60 lei unless we find 'GRATUIT'
                is_free = 'GRATUIT' in text_content.upper()

                # Venue — usually in title's parent or surrounding
                venue_match = re.search(r'@\s*([^,]+(?:,\s*\w+)*)', text_content)
                venue = venue_match.group(1).strip() if venue_match else f"loc în {detected_city[1]}"

                full_url = urljoin('https://www.bilete.ro', ev_href)

                # Category detection from title keywords
                title_lower = title.lower()
                if any(k in title_lower for k in ['teatru', 'spectacol', 'comedie', 'shakespeare', 'willy']):
                    category = 'teatru'
                elif any(k in title_lower for k in ['concert', 'coma', 'jazz', 'rock', 'metal', 'party']):
                    category = 'concert'
                elif any(k in title_lower for k in ['copii', 'capra', 'ursul', 'pestelui', 'pisici']):
                    category = 'family'
                elif any(k in title_lower for k in ['fotbal', 'fc ', 'meci', 'liga']):
                    category = 'sport'
                else:
                    category = 'concert'

                vibe_map = {
                    'concert': 'loud', 'teatru': 'intim', 'family': 'family',
                    'sport': 'casual'
                }

                event = {
                    "id": full_id,
                    "title": title[:120],
                    "category": category,
                    "vibe": vibe_map.get(category, 'casual'),
                    "date": iso_date,
                    "time": event_time,
                    "venue": venue,
                    "address": venue,
                    "price": "free" if is_free else "paid",
                    "price_value": 0 if is_free else 60,
                    "source": "bilete.ro",
                    "url": full_url,
                    "description": f"{title} - eveniment la {venue} din {detected_city[1]}, conform calendarului bilete.ro.",
                    "highlights": [f"data: {iso_date}", f"loc: {venue}", f"categorie: {category}"],
                    "duration": "1h 30min",
                    "age": "All ages",
                    "tags": [category, "bilete-ro"],
                    "map_url": f"https://maps.google.com/?q={venue}".replace(' ', '+'),
                    "organizer": "bilete.ro",
                    "scraped_at": today,
                }
                events.append(event)
                existing_ids.add(full_id)

            except Exception as e:
                continue

    # Group by city
    by_city = {}
    for ev in events:
        # Re-detect city from event object (we already filtered to our 7)
        for slug, name in CITIES.items():
            if name in ev.get('venue', '') or name in ev.get('description', ''):
                if slug not in by_city:
                    by_city[slug] = []
                by_city[slug].append(ev)
                break

    print(f"[bilete.ro] Found {len(events)} new events", file=sys.stderr)
    return by_city


def main():
    days = 30
    if '--days' in sys.argv:
        i = sys.argv.index('--days')
        days = int(sys.argv[i + 1])

    # Load existing events.json to skip duplicates
    events_file = Path(__file__).parent.parent / 'events.json'
    existing_ids = set()
    if events_file.exists():
        try:
            data = json.load(open(events_file))
            for city in data.get('cities', []):
                for ev in city.get('events', []):
                    existing_ids.add(ev.get('id', ''))
        except Exception as e:
            print(f"WARN: could not parse events.json: {e}", file=sys.stderr)

    print(f"Existing IDs in events.json: {len(existing_ids)}", file=sys.stderr)

    # Scrape iabilet.ro per city
    all_new = []
    for slug, name in CITIES.items():
        new_events = scrape_city(slug, name, existing_ids, days)
        if new_events:
            all_new.append({"slug": slug, "name": name, "events": new_events})
        time.sleep(2)  # polite delay between cities

    # Scrape bilete.ro (covers all cities in one go)
    bilete_by_city = scrape_bilete_ro(None, None, existing_ids, days)
    if bilete_by_city:
        for slug, events in bilete_by_city.items():
            existing_entry = next((c for c in all_new if c['slug'] == slug), None)
            if existing_entry:
                existing_entry['events'].extend(events)
            else:
                all_new.append({"slug": slug, "name": CITIES[slug], "events": events})
        time.sleep(2)

    # Output: JSON to stdout (merge script reads this)
    print(json.dumps(all_new, ensure_ascii=False))


if __name__ == '__main__':
    main()
