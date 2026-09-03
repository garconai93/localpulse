# LocalPulse

**LocalPulse** — agregator de evenimente mici din 5 orașe mari din România (București, Cluj-Napoca, Timișoara, Iași, Constanța).

În loc să cauți pe 12 surse (FB Events, IG, site-uri locale, Eventbrite), LocalPulse îți dă un singur feed curat, cu filtre pe dată, preț și vibe.

## Funcționalități MVP

- ✅ **5 orașe** cu evenimente reale din septembrie 2026 (colectate din iabilet.ro, ticketstore.ro, clujtourism.ro, litoralpress.ro)
- ✅ **Detectare automată a orașului** pe baza geolocației (haversine pe lat/lon)
- ✅ **Dropdown manual** pentru schimbare oraș
- ✅ **Filtre** — perioadă (azi / weekend / 7 zile / toate), preț (gratuit / plătit), vibe (intim / loud / casual / family)
- ✅ **Salvare automată** a orașului ales (localStorage)
- ✅ **Statistici live** — total, gratis, weekend, categorii
- ✅ **Mobile-first responsive** cu dark mode premium
- ✅ **Date reale** — 39 evenimente cu titlu, dată, oră, locație, preț, link bilete

## Stack

- HTML/CSS/JS vanilla (zero build tools)
- `events.json` static, încărcat via `fetch`
- GitHub Pages hosting

## Demo

https://garconai93.github.io/localpulse/

## Cum adaugi evenimente noi

Editează `events.json` și adaugă obiect nou în array-ul `events` al orașului dorit:

```json
{
  "id": "buc-011",
  "title": "Titlu eveniment",
  "category": "concert",
  "vibe": "loud",
  "date": "2026-09-20",
  "time": "21:00",
  "venue": "Sala X",
  "price": "paid",
  "price_value": 100,
  "source": "iabilet",
  "url": "https://..."
}
```

Categorii acceptate: `concert`, `teatru`, `standup`, `party`, `expo`, `cinema`, `festival`, `boardgames`, `workshop`, `family`, `conferinta`, `spectacol`, `sport`.

Vibe-uri acceptate: `intim`, `loud`, `casual`, `family`.

## License

MIT
