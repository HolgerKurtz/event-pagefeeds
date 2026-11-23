"""Jazzfest Rottweil (jazzfest-rottweil.de) – one item per upcoming concert.

Source: the homepage (WordPress/Elementor) is the programme. Each concert is an
Elementor section with date + time ("SA, 01.05.2027 20:30 Uhr"), venue, image,
title and an "Infos & Details" link to its own page. Entries without such a page
(e.g. the free "JAZZ IN TOWN" in the old town) count as events but aren't in the feeds.

Elementor keeps unused buttons in the HTML ("ausverkauft", "Tickets ab ... bestellen",
"Aktuell keine Tickets verfügbar") and hides them on all devices; those widgets are
dropped before parsing, so only what visitors actually see counts.

Labels: venue slug, e.g. "alte-stallhalle".
Price: the regular advance price "VVK: 40,00 EUR" on the concert page (not the reduced
member / 14–25 prices).
Availability: out of stock if a visible "ausverkauft" or "keine Tickets" shows on the
homepage entry or the concert page. Sold-out concerts are left out of the page feed.
Image: the homepage entry's image, largest size in its srcset; some are WebP, so
CONVERT_IMAGES routes them through wsrv.nl. The concert page's slider uses the same
picture (set via CSS), so there's no additional_image_link.
Description: the text below the concert page's subtitle.
The ticket shop (Reservix) blocks scripted requests (HTTP 403) and isn't needed.
Concert page details are cached in feeds/jazzfest-details.json (30 days, see DetailsCache).

The festival runs once a year (spring); between festivals the programme can be empty,
which makes the run fail (MIN_EVENTS). Set ACTIVE = False then.
"""
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pagefeed import DetailsCache, FeedError, fetch

ACTIVE = True            # False = skipped when running all clients
BASE = "https://www.jazzfest-rottweil.de"
LINK = BASE + "/"
BRAND = "Jazzfest Rottweil"
CONVERT_IMAGES = True
MIN_EVENTS = 1           # small festival: currently 4 entries
MAX_INCOMPLETE = 0.5     # few items, so one without price mustn't fail the run
TZ = ZoneInfo("Europe/Berlin")
HIDDEN = ("elementor-hidden-desktop", "elementor-hidden-tablet", "elementor-hidden-mobile")
SOLD_OUT = ("ausverkauft", "keine tickets")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def visible(section):
    """Section HTML without the Elementor widgets hidden on every device."""
    parts = section.split('<div class="elementor-element ')
    return parts[0] + "".join('<div class="elementor-element ' + p for p in parts[1:]
                              if not all(h in p.split('"', 1)[0] for h in HIDDEN))


def slug(s):
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def largest_image(section):
    img = re.search(r"<img [^>]*>", section)
    if not img:
        return None
    srcset = re.search(r'srcset="([^"]+)"', img.group(0))
    if srcset:
        sizes = [(int(w), u) for u, w in re.findall(r"(\S+) (\d+)w", srcset.group(1))]
        if sizes:
            return html.unescape(max(sizes)[1])
    src = re.search(r'src="([^"]+)"', img.group(0))
    return html.unescape(src.group(1)) if src else None


def load_details(url):
    page = visible(fetch(url))
    price = re.search(r"VVK:\s*(?:</?\w+[^>]*>|\s)*(\d+(?:,\d\d)?)\s*(?:EUR|€)", page)
    # Description: text editor right after the subtitle (h2) that follows the slider.
    desc = re.search(r'elementor-widget-slides.*?<h2[^>]*>.*?</h2>.*?'
                     r'data-widget_type="text-editor\.default">(.*?)</div>\s*</div>', page, re.S)
    return {"price": float(price.group(1).replace(",", ".")) if price else None,
            "description": text(desc.group(1))[:5000] if desc else "",
            "sold_out": any(s in text(page).lower() for s in SOLD_OUT)}


def scrape():
    home = fetch(BASE + "/")
    sections = [visible(s) for s in home.split('<section class="elementor-section elementor-top-section')[1:]]
    cache = DetailsCache("jazzfest")
    now = datetime.now(TZ)
    n_events, items = 0, []
    for sec in sections:
        d = re.search(r"<p>\w+, <strong>(\d\d)\.(\d\d)\.(\d{4})(?:<br />)?</strong>\s*(\d{1,2}):(\d\d) Uhr", sec)
        if not d:
            continue
        n_events += 1
        start = datetime(int(d.group(3)), int(d.group(2)), int(d.group(1)),
                         int(d.group(4)), int(d.group(5)), tzinfo=TZ)
        link = re.search(r'<a href="(' + re.escape(BASE) + r'/[^"]+/)"[^>]*>\s*Infos &amp; Details', sec)
        if start < now or not link:
            continue
        url = link.group(1)
        title = re.search(r"<h2[^>]*>(.*?)</h2>", sec, re.S)
        venue = re.search(r'data-widget_type="text-editor\.default">\s*<div class="elementor-widget-container">'
                          r"(.*?)</div>", sec[d.end():], re.S)
        if not title or not venue:
            raise FeedError(f"{url}: title or venue not found – markup may have changed.")
        venue = text(venue.group(1))
        details = cache.get(url, load_details, fields=("price", "description", "sold_out"))
        price = details.get("price")
        sold_out = details.get("sold_out") or any(s in text(sec).lower() for s in SOLD_OUT)
        items.append({
            "id": url.rstrip("/").rsplit("/", 1)[1],
            "url": url,
            "title": text(title.group(1)),
            "description": details.get("description") or text(title.group(1)),
            "date": start,
            "venue": venue,
            "labels": [slug(re.sub(r"\s*Rottweil$", "", venue))],
            "available": not sold_out,
            "price": f"{price:.2f} EUR" if price is not None else None,  # none: left out of product feed
            "image_url": largest_image(sec),
        })
    cache.save()
    return n_events, items
