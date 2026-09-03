# LocalPulse — ce se întâmplă diseară în orașul tău

Landing page pentru **LocalPulse** — aplicație care agregă evenimentele locale (concerte, expoziții, filme indie, târguri, teatru, sport) din 20+ surse într-un singur feed cronologic, cu filtre inteligente, Personal Radar și weekly digest.

## Ce rezolvă

În orașele mari, informația despre evenimentele culturale și alternative e fragmentată: Facebook Events, Instagram, Eventbrite, site-uri de cinema, panouri fizice, grupuri de Telegram. LocalPulse le pune pe toate într-un singur loc, cu focus pe „diseară" și „weekend", în 30 de secunde — nu 40 de minute de scroll.

## Stack landing

- **Single-file** `index.html` — fără build tools, fără framework
- **Dark mode** cu accent ember/amber (warm city pulse)
- **Mobile-first** responsive (320px → 1440px+)
- **Semantic HTML5** + ARIA labels + skip link
- **Vanilla CSS** cu design tokens (custom properties)
- **Google Fonts** (Inter + Space Grotesk) — fără alte CDN-uri
- **Zero JS deps** — doar IntersectionObserver pentru reveal-on-scroll
- **Performance**: ~47KB total, single request, no images

## Structură secțiuni

1. **Nav** sticky cu backdrop-blur
2. **Hero** — titlu, lede, CTA, mockup telefon cu 4 evenimente simulate
3. **Problem** — 3 dureri (scroll infinit, recomandări generice, grup WhatsApp haos)
4. **Features** — 6 capabilități (feed agregat, filtre, Personal Radar, save+invite, ambasadori locali, anti-evenimente-fantomă)
5. **How it works** — 3 pași
6. **Sources trust strip** — 7+ surse etalate
7. **Pricing** — 3 planuri (Free, Pro 19.99 lei/lună, Organizatori 29€/lună)
8. **FAQ** — 6 întrebări (lansare, surse, preț, privacy, organizatori, platforme)
9. **CTA banner** — formular de email pentru lista de așteptare
10. **Footer** — brand, linkuri, legal

## Cum se publică

Deja live la:
**https://garconai93.github.io/localpulse/**

Prin GitHub Pages de pe branch `main`, root `/`.

## Cum se dezvoltă ulterior

```bash
# local preview
open index.html
# sau:
python3 -m http.server 8000
```

Iterări viitoare:
- Adăuga PWA manifest + service worker (offline)
- Înlocuiește mockup-ul telefon cu screenshot-uri reale după beta
- Adaugă testimoniale de la ambasadori locali
- Integrează un formular de email real (ConvertKit / Buttondown / Resend)

## Licență

Conținut și design © 2026 LocalPulse. Toate drepturile rezervate.
Codul este furnizat ca MVP demonstrativ.
