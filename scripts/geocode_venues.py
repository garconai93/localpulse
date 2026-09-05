#!/usr/bin/env python3
"""
LocalEvent - Venue Geocoder
Populează lat/lon real pentru evenimente care au lat=0, lon=0 sau lipsesc.

Folosește Nominatim (OpenStreetMap) — gratuit, 1 req/sec.

Usage:
  python3 geocode_venues.py [--dry-run]

Strategy:
- Citește events.json
- Colectează (venue, city_name) unice care au nevoie de geocoding
- Verifică cache local (geocode_cache.json) — nu re-bate Nominatim
- Trimite 1 request/sec la Nominatim cu query "{venue}, {city_name}, Romania"
- Dacă Nominatim nu găsește, încearcă fără venue: doar "{city_name}, Romania" (centrul orașului)
- Salvează rezultatele în events.json și actualizează cache-ul
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("ERROR: needs requests. pip install requests", file=sys.stderr)
    sys.exit(1)

# User-Agent OBLIGATORIU pentru Nominatim (altfel blochează request-ul)
USER_AGENT = "LocalEvent.ro/1.0 (https://localevent.ro; contact@localevent.ro) Python/geocoder"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CACHE_FILE = Path(__file__).parent.parent / "geocode_cache.json"

# Coords per oraș (fallback dacă Nominatim eșuează) - centre geografice
CITY_FALLBACK_COORDS = {
    "bucuresti":     (44.4268, 26.1025),
    "cluj-napoca":   (46.7712, 23.6236),
    "timisoara":     (45.7489, 21.2087),
    "iasi":          (47.1585, 27.6014),
    "constanta":     (44.1598, 28.6348),
    "sibiu":         (45.7983, 24.1256),
    "craiova":       (44.3302, 23.7949),
    "brasov":        (45.6427, 25.5887),
    "clinceni":      (44.3733, 25.9533),
    "alba-iulia":    (46.0733, 23.5805),
    "arad":          (46.1866, 21.3123),
    "baia-mare":     (47.6567, 23.5850),
    "deva":          (45.8780, 22.9144),
    "drobeta-turnu-severin": (44.6264, 22.6597),
    "galati":        (45.4353, 28.0080),
    "oradea":        (47.0465, 21.9189),
    "otopeni":       (44.5500, 26.0833),
    "pitesti":       (44.8565, 24.8697),
    "ploiesti":      (44.9367, 26.0129),
    "satu-mare":     (47.7900, 22.8850),
    "voluntari":     (44.4900, 26.1333),
}

# City name map (slug → nume pentru query Nominatim)
CITY_NAMES = {
    "bucuresti": "București",
    "cluj-napoca": "Cluj-Napoca",
    "timisoara": "Timișoara",
    "iasi": "Iași",
    "constanta": "Constanța",
    "sibiu": "Sibiu",
    "craiova": "Craiova",
    "brasov": "Brașov",
    "clinceni": "Clinceni",
    "alba-iulia": "Alba Iulia",
    "arad": "Arad",
    "baia-mare": "Baia Mare",
    "deva": "Deva",
    "drobeta-turnu-severin": "Drobeta-Turnu Severin",
    "galati": "Galați",
    "oradea": "Oradea",
    "otopeni": "Otopeni",
    "pitesti": "Pitești",
    "ploiesti": "Ploiești",
    "satu-mare": "Satu Mare",
    "voluntari": "Voluntari",
}


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def needs_geocoding(lat, lon):
    """Verifică dacă lat/lon sunt invalide (0,0 sau lipsă)."""
    if lat is None or lon is None:
        return True
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return True
    if lat_f == 0.0 and lon_f == 0.0:
        return True
    return False


def geocode_venue(venue, city_name, session):
    """Trimite request Nominatim pentru un venue. Returnează (lat, lon) sau None."""
    if not venue or not venue.strip():
        return None

    # Query 1: venue + oraș + România
    query = f"{venue}, {city_name}, Romania"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "ro",
    }
    try:
        r = session.get(NOMINATIM_URL, params=params, timeout=10)
        r.raise_for_status()
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"  ⚠️  Nominatim error: {e}", file=sys.stderr)
    return None


def geocode_city_only(city_name, session):
    """Fallback: geocodă doar orașul (centrul aproximativ)."""
    params = {
        "q": f"{city_name}, Romania",
        "format": "json",
        "limit": 1,
        "countrycodes": "ro",
    }
    try:
        r = session.get(NOMINATIM_URL, params=params, timeout=10)
        r.raise_for_status()
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"  ⚠️  Nominatim city error: {e}", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(description="Geocode venues with Nominatim")
    parser.add_argument("--dry-run", action="store_true", help="Don't write back to events.json")
    args = parser.parse_args()

    events_file = Path(__file__).parent.parent / "events.json"
    if not events_file.exists():
        print(f"ERROR: {events_file} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(events_file.read_text())
    cache = load_cache()

    # Colectează venue-uri unice care au nevoie de geocoding
    pending = {}  # key: (venue, city_slug) -> [event refs]
    total_events = 0
    total_missing = 0
    for city in data["cities"]:
        city_slug = city["slug"]
        for ev in city["events"]:
            total_events += 1
            if needs_geocoding(ev.get("lat"), ev.get("lon")):
                total_missing += 1
                venue = (ev.get("venue") or "").strip()
                key = (venue, city_slug)
                pending.setdefault(key, []).append(ev)

    print(f"📊 Total events: {total_events}", file=sys.stderr)
    print(f"❌ Need geocoding: {total_missing}", file=sys.stderr)
    print(f"🔍 Unique (venue, city) pairs: {len(pending)}", file=sys.stderr)

    if not pending:
        print("✅ All events already geocoded. Nothing to do.", file=sys.stderr)
        return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ro,en"})

    geocoded_count = 0
    city_fallback_count = 0
    api_calls = 0

    for (venue, city_slug), events_list in pending.items():
        city_name = CITY_NAMES.get(city_slug, city_slug.replace("-", " ").title())
        cache_key = f"{venue}::{city_slug}"

        # Verifică cache
        if cache_key in cache:
            lat, lon = cache[cache_key]
            source = "cache"
        else:
            print(f"🔍 Geocoding: {venue!r} in {city_name}", file=sys.stderr)
            coords = geocode_venue(venue, city_name, session)
            api_calls += 1
            time.sleep(1.1)  # Nominatim policy: max 1 req/sec

            if coords:
                lat, lon = coords
                source = "nominatim"
            else:
                # Fallback: orașul
                print(f"  ↪️  Fallback to city center: {city_name}", file=sys.stderr)
                coords = geocode_city_only(city_name, session)
                api_calls += 1
                time.sleep(1.1)
                if coords:
                    lat, lon = coords
                    source = "city_fallback"
                    city_fallback_count += 1
                else:
                    # Ultima soluție: hardcoded coords
                    fb = CITY_FALLBACK_COORDS.get(city_slug)
                    if fb:
                        lat, lon = fb
                        source = "hardcoded"
                    else:
                        print(f"  ❌ No coords for {venue!r} in {city_name}", file=sys.stderr)
                        continue

            cache[cache_key] = [lat, lon]

        # Update toate evenimentele cu acest venue+city
        for ev in events_list:
            ev["lat"] = lat
            ev["lon"] = lon
        geocoded_count += len(events_list)

        # Log primele câteva
        if source != "cache":
            print(f"  ✓ {venue!r} → {lat:.5f}, {lon:.5f} ({source}) [{len(events_list)} events]", file=sys.stderr)

    # Salvează
    save_cache(cache)

    if args.dry_run:
        print(f"\n🏁 DRY RUN: would update {geocoded_count} events ({api_calls} API calls, {city_fallback_count} city fallbacks)", file=sys.stderr)
        return

    data["last_geocoded"] = time.strftime("%Y-%m-%d")
    events_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n✅ Updated {geocoded_count} events ({api_calls} API calls, {city_fallback_count} city fallbacks)", file=sys.stderr)
    print(f"💾 Cache: {CACHE_FILE} ({len(cache)} entries)", file=sys.stderr)


if __name__ == "__main__":
    main()
