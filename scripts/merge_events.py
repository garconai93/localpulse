#!/usr/bin/env python3
"""
LocalEvent - Event Merger
Reads new events from stdin (JSON), merges into events.json, marks past events as past:true.

Usage:
  python3 fetch_events.py | python3 merge_events.py

Behavior:
- Loads existing events.json
- For each new city in input: append events that aren't already in events.json (by id)
- For each city in events.json: mark events with date < today as past:true (don't delete, just flag)
- Sorts events within each city by date
- Writes back to events.json
- Prints summary to stderr (count of new, count of past)
"""
import json
import sys
from datetime import datetime, date
from pathlib import Path


def main():
    events_file = Path(__file__).parent.parent / 'events.json'
    today_str = date.today().strftime("%Y-%m-%d")
    today = date.today()

    # Load existing
    data = {"cities": []}
    if events_file.exists():
        try:
            data = json.load(open(events_file))
        except Exception as e:
            print(f"ERROR: could not parse events.json: {e}", file=sys.stderr)
            sys.exit(1)

    # Read new events: from argv[1] (file) or stdin
    raw = ""
    if len(sys.argv) > 1 and sys.argv[1]:
        # File path passed
        input_path = Path(sys.argv[1])
        if not input_path.exists():
            print(f"No input file: {input_path}", file=sys.stderr)
            new_events_data = []
        else:
            raw = input_path.read_text().strip()
    else:
        # stdin (legacy mode)
        raw = sys.stdin.read().strip()

    if not raw:
        print("No new events to merge", file=sys.stderr)
        new_events_data = []
    else:
        try:
            new_events_data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"ERROR: could not parse input JSON: {e}", file=sys.stderr)
            sys.exit(1)

    # Index existing by city slug
    existing_by_city = {c['slug']: c for c in data.get('cities', [])}
    existing_ids_by_city = {
        c['slug']: {ev['id'] for ev in c.get('events', [])}
        for c in data.get('cities', [])
    }

    # Merge new events
    new_added = 0
    for city_data in new_events_data:
        slug = city_data['slug']
        if slug not in existing_by_city:
            # New city — initialize
            existing_by_city[slug] = {
                "slug": slug,
                "name": city_data['name'],
                "lat": city_data['events'][0].get('lat', 0) if city_data.get('events') else 0,
                "lon": city_data['events'][0].get('lon', 0) if city_data.get('events') else 0,
                "events": []
            }
            existing_ids_by_city[slug] = set()

        for ev in city_data.get('events', []):
            ev_id = ev.get('id', '')
            if ev_id not in existing_ids_by_city[slug]:
                # Add lat/lon from city defaults if missing
                if 'lat' not in ev and 'lat' in existing_by_city[slug]:
                    ev['lat'] = existing_by_city[slug]['lat']
                    ev['lon'] = existing_by_city[slug]['lon']
                existing_by_city[slug]['events'].append(ev)
                existing_ids_by_city[slug].add(ev_id)
                new_added += 1

    # Mark past events + sort within each city
    past_marked = 0
    cities_list = []
    for slug, city in existing_by_city.items():
        for ev in city.get('events', []):
            ev_date_str = ev.get('date', '')
            try:
                ev_date = datetime.strptime(ev_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            is_past = ev_date < today
            if is_past and not ev.get('past'):
                ev['past'] = True
                past_marked += 1
            elif not is_past and ev.get('past'):
                ev['past'] = False
        # Sort by date+time
        city['events'].sort(key=lambda e: (e.get('date', ''), e.get('time', '')))
        cities_list.append(city)

    # Sort cities alphabetically (stable order)
    cities_list.sort(key=lambda c: c['name'])

    # Update generated_at
    data = {
        "generated_at": today_str,
        "last_scraped": today_str,
        "cities": cities_list
    }

    # Write back
    with open(events_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total_events = sum(len(c['events']) for c in cities_list)
    future_events = sum(
        1 for c in cities_list
        for ev in c['events']
        if not ev.get('past', False)
    )
    past_events = total_events - future_events

    print(f"✓ Merged: {new_added} new events added", file=sys.stderr)
    print(f"✓ Total: {total_events} events across {len(cities_list)} cities", file=sys.stderr)
    print(f"  - Future: {future_events}", file=sys.stderr)
    print(f"  - Past:   {past_events} (marked with past:true, hidden from UI)", file=sys.stderr)


if __name__ == '__main__':
    main()
