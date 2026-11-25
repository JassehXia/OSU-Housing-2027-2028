"""
Scraper for Columbus / Ohio State University 4-bedroom rental listings
from major local OSU landlord websites:
  - AppFolio portals (Peak Property Group, Northsteppe Realty, Stratagem Management,
    My 1st Place Realty, Columbus Realty, OSU Properties, OSU Live, Buckeye Real Estate)
  - Hometeam Properties
  - Pella Co

Outputs strictly 4-bedroom, Columbus/Central Ohio listings to data/raw_landlords.json.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OSU_LAT = 40.0
OSU_LNG = -83.0145
MAX_DEG_DELTA = 0.35

COLUMBUS_CITIES = [
    "columbus",
    "grandview",
    "grandview heights",
    "upper arlington",
    "clintonville",
    "worthington",
    "westerville",
    "dublin",
    "hilliard",
    "grove city",
    "bexley",
    "whitehall",
    "gahanna",
    "reynoldsburg",
    "powell",
    "new albany",
    "marble cliff",
    "blacklick",
    "canal winchester",
    "groveport",
    "pickerington",
    "delaware",
    "sunbury",
]

KNOWN_NEIGHBORHOODS = [
    "North Campus",
    "South Campus",
    "East Campus",
    "West Campus",
    "Central Campus",
    "University District",
    "Short North",
    "Victorian Village",
    "Italian Village",
    "Old North",
    "Old North Columbus",
    "Clintonville",
    "Grandview",
    "Grandview Heights",
    "Upper Arlington",
    "German Village",
    "Weinland Park",
    "SoHud",
    "Harrison West",
    "Fifth by Northwest",
    "Franklinton",
    "Bexley",
    "Worthington",
    "Westerville",
    "Dublin",
    "Hilliard",
    "Grove City",
    "Gahanna",
    "Whitehall",
    "Reynoldsburg",
    "New Albany",
    "Powell",
    "Merion Village",
    "Brewery District",
    "Olde Towne East",
    "King-Lincoln",
    "Linden",
    "North Linden",
    "Eastmoor",
    "Berwick",
]

APPFOLIO_PORTALS = [
    ("peak", "Peak Property Group", "https://peakpropertygroup.appfolio.com"),
    ("northsteppe", "Northsteppe Realty", "https://northsteppe.appfolio.com"),
    ("stratagem", "Stratagem Management", "https://stratagemmgmt.appfolio.com"),
    ("my1stplace", "My 1st Place Realty", "https://my1stplace.appfolio.com"),
    ("columbusrealty", "Columbus Realty", "https://columbusrealty.appfolio.com"),
    ("osuproperties", "OSU Properties", "https://osuproperties.appfolio.com"),
    ("osulive", "OSU Live", "https://osulive.appfolio.com"),
    ("buckeye", "Buckeye Real Estate", "https://buckeye.appfolio.com"),
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch_html(url: str, timeout: int = 25, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (404, 410):
                return None
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(0.8 * (attempt + 1))
    return None


def is_columbus_area(lat: float | None, lng: float | None, address: str) -> bool:
    if lat is not None and lng is not None:
        return abs(lat - OSU_LAT) <= MAX_DEG_DELTA and abs(lng - OSU_LNG) <= MAX_DEG_DELTA
    addr_low = (address or "").lower()
    if any(city in addr_low for city in COLUMBUS_CITIES):
        return True
    if re.search(r"\boh\s*43[012]\d{2}\b", addr_low):
        return True
    return False


def ensure_columbus_address(address: str) -> str:
    addr = re.sub(r"\s+", " ", (address or "").strip())
    if not addr:
        return addr
    addr_low = addr.lower()
    if ", oh" not in addr_low and " oh " not in addr_low and not addr_low.endswith(" oh"):
        if not any(city in addr_low for city in COLUMBUS_CITIES):
            addr = f"{addr}, Columbus, OH"
        else:
            addr = f"{addr}, OH"
    return addr


def parse_rent_number(text: str | None) -> int | None:
    if not text:
        return None
    # Match first dollar amount or number like $2,400 or 2400.00
    m = re.search(r"\$?\s*([0-9][0-9,]*(?:\.\d{1,2})?)", text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
        return int(round(val)) if val > 0 else None
    except ValueError:
        return None


def parse_bedrooms_strict(text: str | None) -> int | None:
    if not text:
        return None
    # Reject ranges like "3-4 bd" or "4-5 bd"
    if re.search(r"\b\d+\s*[-–/]\s*\d+\s*(?:bd|br|bed|bedroom)", text, re.I):
        return None
    m = re.search(r"\b(\d+)\s*(?:\+)?\s*(?:bd|br|bed|beds|bedroom|bedrooms)\b", text, re.I)
    if not m:
        return None
    # Reject "4+" or "5+"
    if "+" in m.group(0):
        return None
    return int(m.group(1))


def parse_bathrooms(text: str | None) -> float | None:
    if not text:
        return None
    t = text.replace("½", ".5").replace("1/2", ".5")
    # Handle "1 .5" from "1 ½"
    t = re.sub(r"(\d)\s+\.5", r"\1.5", t)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|baths|bathroom|bathrooms)\b", t, re.I)
    if not m:
        # Fallback: bare number if called on a bath-only field
        m2 = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", t)
        if m2:
            return float(m2.group(1))
        return None
    return float(m.group(1))


def parse_sqft(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"([0-9][0-9,]{2,5})\s*(?:sq\.?\s*ft\.?|sqft|square\s*feet)?", text, re.I)
    if not m:
        return None
    try:
        val = int(m.group(1).replace(",", ""))
        return val if 300 <= val <= 20000 else None
    except ValueError:
        return None


def infer_parking(text: str, amenities: list[str]) -> str | None:
    combined = " ".join([text or ""] + amenities).lower()
    if not combined:
        return None
    if "garage" in combined and "off-street" in combined:
        return "Garage & Off-street"
    if "attached garage" in combined or "detached garage" in combined or "garage" in combined:
        return "Garage"
    if "free parking" in combined or "parking included" in combined:
        return "Included"
    if "permit parking" in combined or "parking pass" in combined:
        return "Permit Parking"
    if "off-street" in combined or "off street" in combined or "private lot" in combined or "driveway" in combined:
        return "Off-street"
    if "on-street" in combined or "street parking" in combined:
        return "Street"
    if "parking" in combined:
        return "Available"
    return None


def parse_pets(pet_policy: str | None, text: str, amenities: list[str]) -> tuple[bool | None, str | None]:
    policy = re.sub(r"\s+", " ", (pet_policy or "").strip()) or None
    if policy:
        low = policy.lower()
        if "no pets" in low or "cats not allowed, dogs not allowed" in low or ("not allowed" in low and "allowed" not in low.replace("not allowed", "")):
            return False, policy
        if "allowed" in low or "pet friendly" in low or "cats" in low or "dogs" in low:
            return True, policy
    combined = " ".join([text or ""] + amenities).lower()
    if "no pets" in combined or "pets not allowed" in combined:
        return False, policy or "No pets allowed"
    if "pets allowed" in combined or "pet friendly" in combined or "pet-friendly" in combined:
        return True, policy or "Pets allowed"
    return None, policy


def infer_neighborhood(text: str, address: str) -> str | None:
    combined = f"{text} {address}"
    for nb in KNOWN_NEIGHBORHOODS:
        if re.search(rf"\b{re.escape(nb)}\b", combined, re.I):
            return nb
    return None


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_appfolio_markers(html: str) -> dict[str, dict[str, Any]]:
    """Extract AppFolio embedded markers JSON keyed by listing_id and detail_page_url."""
    markers_by_id: dict[str, dict[str, Any]] = {}
    m = re.search(r"markers:\s*(\[.*?\])\s*,?\s*\n", html, re.S)
    if not m:
        m = re.search(r"markers:\s*(\[.*?\])", html, re.S)
    if not m:
        return markers_by_id
    try:
        arr = json.loads(m.group(1))
        for mk in arr:
            lid = mk.get("listing_id")
            if lid is not None:
                markers_by_id[str(lid)] = mk
            durl = mk.get("detail_page_url")
            if durl:
                markers_by_id[durl] = mk
    except json.JSONDecodeError:
        pass
    return markers_by_id


def enrich_appfolio_detail(listing: dict[str, Any]) -> dict[str, Any]:
    """Fetch AppFolio detail page to get full gallery photos, untruncated description, amenities, and lease term."""
    html = fetch_html(listing["url"], timeout=20, retries=1)
    if not html:
        return listing
    soup = BeautifulSoup(html, "lxml")

    # Photos from gallery links (prefer large.jpeg / large.png)
    photos: list[str] = []
    seen_photos: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "images.cdn.appfolio.com" in href and href not in seen_photos:
            seen_photos.add(href)
            photos.append(href)
    if not photos:
        for img in soup.select("img"):
            src = img.get("data-original") or img.get("src") or ""
            if "images.cdn.appfolio.com" in src and "place_holder" not in src:
                # Upgrade medium to large if possible
                if src not in seen_photos:
                    seen_photos.add(src)
                    photos.append(src)
    if photos:
        listing["photos"] = photos

    # Full description
    desc_el = soup.select_one(".listing-detail__description")
    if desc_el:
        full_desc = clean_text(desc_el.get_text(" ", strip=True))
        if len(full_desc) > len(listing.get("description") or ""):
            listing["description"] = full_desc

    # Amenities list from detail page
    detail_amenities: list[str] = []
    for li in soup.select(".list--amenities li, .listing-detail__amenities li"):
        t = clean_text(li.get_text(" ", strip=True))
        if t and t not in detail_amenities:
            detail_amenities.append(t)
    # Also check header/section titled Amenities
    if not detail_amenities:
        for h in soup.find_all(["h2", "h3", "h4"]):
            if "amenities" in h.get_text(strip=True).lower():
                ul = h.find_next_sibling("ul")
                if ul:
                    for li in ul.find_all("li"):
                        t = clean_text(li.get_text(" ", strip=True))
                        if t and t not in detail_amenities:
                            detail_amenities.append(t)
    if detail_amenities:
        listing["amenities"] = detail_amenities

    # Lease term & pet policy from detail sections
    full_page_text = clean_text(soup.get_text(" ", strip=True))
    if not listing.get("leaseTerm"):
        m_lease = re.search(
            r"(?:Lease\s*Terms?|Term)\s*[:\-]?\s*(\d+\s*Months?|1\s*Year|12\s*Months?|Month[- ]to[- ]Month|Flexible)",
            full_page_text,
            re.I,
        )
        if m_lease:
            listing["leaseTerm"] = m_lease.group(1).strip()

    # Re-evaluate parking & pets with full description/amenities
    if not listing.get("parking"):
        listing["parking"] = infer_parking(listing["description"], listing["amenities"])
    pets_allowed, pet_policy = parse_pets(
        listing.get("petPolicy"), listing["description"], listing["amenities"]
    )
    if listing.get("petsAllowed") is None and pets_allowed is not None:
        listing["petsAllowed"] = pets_allowed
    if not listing.get("petPolicy") and pet_policy:
        listing["petPolicy"] = pet_policy

    return listing


def scrape_appfolio_portal(prefix: str, source_name: str, base_url: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    next_url: str | None = f"{base_url}/listings"
    page_num = 0

    while next_url and page_num < 15:
        page_num += 1
        html = fetch_html(next_url)
        if not html:
            break

        markers_map = extract_appfolio_markers(html)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".js-listing-item")

        for card in cards:
            # Quick facts
            facts: dict[str, str] = {}
            for item in card.select(".detail-box__item"):
                dt = item.select_one("dt")
                dd = item.select_one("dd")
                if dt and dd:
                    facts[clean_text(dt.get_text()).lower()] = clean_text(dd.get_text())

            # Detail URL
            link = card.select_one("a.js-link-to-detail, .js-listing-title a, a[href*='/listings/detail/']")
            detail_path = link.get("href") if link else None
            if not detail_path:
                continue
            detail_url = urljoin(base_url, detail_path)
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            # Marker lookup
            card_id = (card.get("id") or "").replace("listing_", "").strip()
            marker = markers_map.get(card_id) or markers_map.get(detail_path) or {}

            # Strict 4-bedroom check
            bed_bath_str = facts.get("bed / bath") or ""
            if not bed_bath_str:
                bb_el = card.select_one(".js-listing-blurb-bed-bath")
                bed_bath_str = clean_text(bb_el.get_text()) if bb_el else ""
            if not bed_bath_str:
                bed_bath_str = marker.get("unit_specs") or ""

            bedrooms = parse_bedrooms_strict(bed_bath_str)
            if bedrooms != 4:
                continue

            # Address & Lat/Lng
            addr_el = card.select_one(".js-listing-address")
            address = clean_text(addr_el.get_text()) if addr_el else (marker.get("address") or "")
            lat = marker.get("latitude")
            lng = marker.get("longitude")
            try:
                lat = float(lat) if lat is not None else None
                lng = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lat, lng = None, None

            # Strict Columbus / Central Ohio check
            if not is_columbus_area(lat, lng, address):
                continue

            address = ensure_columbus_address(address)

            # Title
            title_el = card.select_one(".js-listing-title")
            title = clean_text(title_el.get_text()) if title_el else address

            # Rent
            rent_str = facts.get("rent") or ""
            if not rent_str:
                r_el = card.select_one(".js-listing-blurb-rent")
                rent_str = clean_text(r_el.get_text()) if r_el else (marker.get("rent_range") or "")
            rent_val = parse_rent_number(rent_str)
            if not rent_val or rent_val <= 0:
                continue

            # Description
            desc_el = card.select_one(".js-listing-description")
            description = clean_text(desc_el.get_text(" ", strip=True)) if desc_el else ""

            # Check if explicitly listed per-bed / per-person
            per_bed_check = f"{rent_str} {title} {description}".lower()
            if rent_val < 1300 and re.search(
                r"\b(?:per\s*bed|per\s*person|/\s*bed|/\s*person|by\s*the\s*bed)\b",
                per_bed_check,
            ):
                rent_total = rent_val * 4
            else:
                rent_total = rent_val

            # Bathrooms & sqft
            bathrooms = parse_bathrooms(bed_bath_str)
            sqft = parse_sqft(facts.get("square feet") or marker.get("unit_specs"))

            # Available date
            avail_str = facts.get("available")
            if not avail_str:
                av_el = card.select_one(".js-listing-available")
                avail_str = clean_text(av_el.get_text()).replace("Available ", "") if av_el else None
            available_date = avail_str if avail_str else None

            # Amenities from card (will be replaced with full list from detail page)
            amenities: list[str] = []
            for p in card.select("p"):
                txt = clean_text(p.get_text(" ", strip=True))
                if "Amenities:" in txt:
                    am_part = txt.split("Amenities:", 1)[1]
                    if "Pet Policy:" in am_part:
                        am_part = am_part.split("Pet Policy:", 1)[0]
                    for a_item in am_part.split(","):
                        a_clean = a_item.strip(" .")
                        if a_clean and a_clean != "...":
                            amenities.append(a_clean)

            # Pet policy
            pet_el = card.select_one(".js-listing-pet-policy")
            pet_policy_raw = None
            if pet_el:
                pet_policy_raw = clean_text(pet_el.get_text(" ", strip=True))
                pet_policy_raw = re.sub(r"^Pet\s*Policy:\s*", "", pet_policy_raw, flags=re.I).strip()
            pets_allowed, pet_policy = parse_pets(pet_policy_raw, description, amenities)

            # Photos (prefer marker's large default_photo_url)
            photos: list[str] = []
            default_photo = marker.get("default_photo_url")
            if default_photo and "place_holder" not in default_photo:
                photos.append(default_photo)
            else:
                img = card.select_one("img.js-listing-image")
                if img:
                    src = img.get("data-original") or img.get("src") or ""
                    if src and "place_holder" not in src:
                        photos.append(src)

            # Stable UID from detail URL UUID
            uid_match = re.search(r"/listings/detail/([a-zA-Z0-9\-]+)", detail_url)
            uid = uid_match.group(1) if uid_match else (card_id or str(len(results)))

            results.append(
                {
                    "id": f"{prefix}-{uid}",
                    "source": source_name,
                    "title": title or address,
                    "address": address,
                    "neighborhood": infer_neighborhood(f"{title} {description}", address),
                    "lat": lat,
                    "lng": lng,
                    "rentTotal": rent_total,
                    "rentPerPerson": round(rent_total / 4),
                    "bedrooms": 4,
                    "bathrooms": bathrooms,
                    "sqft": sqft,
                    "availableDate": available_date,
                    "leaseTerm": None,
                    "landlord": source_name,
                    "parking": infer_parking(description, amenities),
                    "petsAllowed": pets_allowed,
                    "petPolicy": pet_policy,
                    "amenities": amenities,
                    "description": description,
                    "photos": photos,
                    "url": detail_url,
                }
            )

        # Pagination
        nxt = soup.select_one("a.next_page, a[rel=next]")
        if nxt and nxt.get("href"):
            next_url = urljoin(base_url, nxt["href"])
        else:
            next_url = None

    # Enrich 4BR listings with detail pages concurrently
    if results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(enrich_appfolio_detail, results))

    return results


def enrich_hometeam_detail(listing: dict[str, Any]) -> dict[str, Any]:
    """Fetch Hometeam Properties detail page for lat/lng (JSON-LD), sqft, full description, photos, amenities, pets."""
    html = fetch_html(listing["url"], timeout=20, retries=1)
    if not html:
        return listing
    soup = BeautifulSoup(html, "lxml")

    # 1. JSON-LD for exact Latitude/Longitude
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        if "Latitude" in raw and "Longitude" in raw:
            m_lat = re.search(r'"name"\s*:\s*"Latitude"\s*,\s*"value"\s*:\s*"([0-9.\-]+)"', raw)
            m_lng = re.search(r'"name"\s*:\s*"Longitude"\s*,\s*"value"\s*:\s*"([0-9.\-]+)"', raw)
            if m_lat and m_lng:
                try:
                    listing["lat"] = float(m_lat.group(1))
                    listing["lng"] = float(m_lng.group(1))
                except ValueError:
                    pass

    # 2. Photos (exclude icons/svgs)
    photos: list[str] = []
    seen_photos: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if (
            "website-files.com" in src
            and not src.lower().endswith(".svg")
            and "logo" not in src.lower()
            and "icon" not in src.lower()
            and "6348a05920f3e17d9dcdf422" in src
            and src not in seen_photos
        ):
            seen_photos.add(src)
            photos.append(src)
    if photos:
        listing["photos"] = photos

    # 3. Sqft, Description, Amenities from page text
    page_text = clean_text(soup.get_text(" ", strip=True))

    m_sqft = re.search(r"([0-9][0-9,]{2,4})\s*(?:&nbsp;?|\s)*Square\s*Feet", page_text, re.I)
    if m_sqft:
        listing["sqft"] = parse_sqft(m_sqft.group(1))

    # Extract main property description paragraph
    desc_candidates: list[str] = []
    for p in soup.find_all(["p", "div"]):
        cls = " ".join(p.get("class") or []).lower()
        if any(k in cls for k in ["description", "rich-text", "about-property", "unit-desc"]):
            t = clean_text(p.get_text(" ", strip=True))
            if len(t) > 80 and t not in desc_candidates:
                desc_candidates.append(t)
    if desc_candidates:
        # Pick the longest clean description
        best_desc = max(desc_candidates, key=len)
        listing["description"] = best_desc
    else:
        m_welcome = re.search(r"(Welcome to [^.]+\.(?:[^.]+\.){1,6})", page_text)
        if m_welcome:
            listing["description"] = clean_text(m_welcome.group(1))

    # Amenities / Features
    amenities: list[str] = list(listing.get("amenities") or [])
    for feature_label in [
        "Air Conditioning",
        "Central A/C",
        "Dishwasher",
        "Washer/Dryer",
        "Washer / Dryer",
        "In-Unit Laundry",
        "Laundry",
        "Hardwood Floors",
        "Stainless Steel Appliances",
        "Granite Countertops",
        "Front Porch",
        "Backyard",
        "Patio",
        "Balcony",
        "Off-Street Parking",
        "Free Parking",
        "Furnished",
        "Furniture Included",
        "Utilities Included",
        "24hr Emergency Maintenance",
    ]:
        if re.search(re.escape(feature_label), page_text, re.I) and feature_label not in amenities:
            amenities.append(feature_label)
    listing["amenities"] = amenities

    # Parking refinement
    if "free parking" in page_text.lower():
        listing["parking"] = "Free / Included"
    elif not listing.get("parking"):
        listing["parking"] = infer_parking(page_text, amenities)

    # Pets
    pets_allowed, pet_policy = parse_pets(None, listing["description"] or page_text, amenities)
    listing["petsAllowed"] = pets_allowed
    listing["petPolicy"] = pet_policy

    return listing


def scrape_hometeam() -> list[dict[str, Any]]:
    base_url = "https://www.hometeamproperties.net"
    endpoints = [
        ("/for-rent/available-fall/all-unit-listings", "Fall 2027"),
        ("/for-rent/available-now/all-unit-listings", "Available Now"),
    ]
    by_slug: dict[str, dict[str, Any]] = {}

    for path, default_avail in endpoints:
        url: str | None = base_url + path
        page_num = 0
        while url and page_num < 30:
            page_num += 1
            html = fetch_html(url)
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".collection-item-unit-listing-v3.w-dyn-item, .w-dyn-item")
            if not cards:
                break

            for card in cards:
                link = card.find("a", href=re.compile(r"^/unit-listings/"))
                if not link:
                    continue
                href = link["href"]
                slug = href.rstrip("/").split("/")[-1]
                if slug in by_slug:
                    continue

                # Read Webflow Finsweet metadata fields
                fs_fields: dict[str, str] = {}
                for el in card.find_all(attrs={"fs-cmsfilter-field": True}):
                    key = el.get("fs-cmsfilter-field")
                    val = clean_text(el.get_text(" ", strip=True))
                    if key and val and key not in fs_fields:
                        fs_fields[key] = val

                # Strict 4-bedroom check
                bed_str = fs_fields.get("bed-string") or ""
                if not bed_str:
                    tt = card.select_one(".type-title")
                    bed_str = clean_text(tt.get_text()) if tt else ""
                if parse_bedrooms_strict(bed_str) != 4:
                    continue

                # Skip explicitly unavailable items if flagged false
                if fs_fields.get("available", "").lower() == "false":
                    continue

                # Rent
                rent_total = parse_rent_number(fs_fields.get("rent-fall"))
                if not rent_total:
                    rent_total = parse_rent_number(fs_fields.get("rent-now") or fs_fields.get("rent"))
                if not rent_total:
                    btb = parse_rent_number(fs_fields.get("rent-fall-btb") or fs_fields.get("rent-btb"))
                    if btb:
                        rent_total = btb * 4
                if not rent_total:
                    # Fallback to visible rent text in card
                    card_txt = clean_text(card.get_text(" ", strip=True))
                    m_r = re.search(r"\$\s*([0-9,]+)\s*per\s*month", card_txt, re.I)
                    if m_r:
                        rent_total = parse_rent_number(m_r.group(1))
                if not rent_total or rent_total <= 0:
                    continue

                # Bathrooms
                bath_str = fs_fields.get("bath-string") or ""
                if not bath_str:
                    tt = card.select_one(".type-title")
                    bath_str = clean_text(tt.get_text()) if tt else ""
                bathrooms = parse_bathrooms(bath_str)

                # Title / Address / Neighborhood / Parking
                name = fs_fields.get("name") or slug.replace("-", " ").title()
                raw_addr = fs_fields.get("address") or name
                address = ensure_columbus_address(raw_addr)
                neighborhood = fs_fields.get("neighborhood") or None
                parking = fs_fields.get("parking") or None
                style = fs_fields.get("style") or None

                # Thumbnail photo
                photos: list[str] = []
                img = card.select_one("img.image-unit-listing")
                if img and img.get("src"):
                    photos.append(img["src"])

                amenities = [style] if style else []

                by_slug[slug] = {
                    "id": f"hometeam-{slug}",
                    "source": "Hometeam Properties",
                    "title": name,
                    "address": address,
                    "neighborhood": neighborhood,
                    "lat": None,
                    "lng": None,
                    "rentTotal": rent_total,
                    "rentPerPerson": round(rent_total / 4),
                    "bedrooms": 4,
                    "bathrooms": bathrooms,
                    "sqft": None,
                    "availableDate": default_avail,
                    "leaseTerm": "12 Months",
                    "landlord": "Hometeam Properties",
                    "parking": parking,
                    "petsAllowed": None,
                    "petPolicy": None,
                    "amenities": amenities,
                    "description": "",
                    "photos": photos,
                    "url": urljoin(base_url, href),
                }

            nxt = soup.select_one("a.w-pagination-next")
            if nxt and nxt.get("href"):
                nhref = nxt["href"]
                url = (base_url + path + nhref) if nhref.startswith("?") else urljoin(base_url, nhref)
            else:
                url = None

    listings = list(by_slug.values())
    if listings:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            listings = list(ex.map(enrich_hometeam_detail, listings))

    # Filter to Columbus area
    return [item for item in listings if is_columbus_area(item["lat"], item["lng"], item["address"])]


def enrich_pella_detail(listing: dict[str, Any]) -> dict[str, Any]:
    """Fetch Pella Co detail page for bathrooms, full description, amenities, address, and gallery photos."""
    html = fetch_html(listing["url"], timeout=20, retries=1)
    if not html:
        return listing
    soup = BeautifulSoup(html, "lxml")

    page_text = clean_text(soup.get_text(" ", strip=True))

    # Bathrooms
    if listing.get("bathrooms") is None:
        listing["bathrooms"] = parse_bathrooms(page_text)

    # Full address (e.g. "50 W Northwood Ave Columbus OH, 43201")
    addr_el = soup.select_one(".property-address, .field--name-field-address")
    if addr_el:
        raw_addr = clean_text(addr_el.get_text(" ", strip=True))
        raw_addr = re.sub(r"\s+Columbus\s+OH,?\s*", ", Columbus, OH ", raw_addr, flags=re.I)
        listing["address"] = ensure_columbus_address(raw_addr)
    else:
        m_zip = re.search(r"Columbus\s+OH,?\s*(43\d{3})", page_text, re.I)
        if m_zip and m_zip.group(1) not in listing["address"]:
            listing["address"] = f"{listing['address']} {m_zip.group(1)}"

    # Description
    desc_el = soup.select_one(".field--name-body, .property-description, .node__content p")
    if desc_el:
        listing["description"] = clean_text(desc_el.get_text(" ", strip=True))

    # Amenities
    amenities: list[str] = []
    for h in soup.find_all(["h2", "h3", "h4", "div"]):
        if clean_text(h.get_text()).lower() == "amenities":
            nxt = h.find_next_sibling()
            if nxt:
                for item in nxt.find_all(["li", "div", "span"]):
                    t = clean_text(item.get_text(" ", strip=True))
                    if t and len(t) < 40 and t not in amenities:
                        amenities.append(t)
            break
    if not amenities:
        for am in ["A/C", "Dishwasher", "Parking", "Laundry"]:
            if re.search(rf"\b{re.escape(am)}\b", page_text):
                amenities.append(am)
    listing["amenities"] = amenities

    # Gallery photos
    photos: list[str] = []
    seen_photos: set[str] = set()
    for img in soup.select("img"):
        src = img.get("src") or ""
        if "/sites/default/files/styles/property_slider/" in src:
            full_src = urljoin("https://pellaco.com", src)
            if full_src not in seen_photos:
                seen_photos.add(full_src)
                photos.append(full_src)
    if photos:
        listing["photos"] = photos

    listing["parking"] = infer_parking(listing["description"], amenities)
    pets_allowed, pet_policy = parse_pets(None, listing["description"], amenities)
    listing["petsAllowed"] = pets_allowed
    listing["petPolicy"] = pet_policy

    return listing


def scrape_pella() -> list[dict[str, Any]]:
    base_url = "https://pellaco.com"
    # field_bedrooms_target_id=16 is strictly "4 Bedrooms" on Pella Co
    map_url = f"{base_url}/property-search/map?field_bedrooms_target_id=16"
    html = fetch_html(map_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", {"data-drupal-selector": "drupal-settings-json"})
    if not script or not script.string:
        return []

    try:
        settings = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    def find_features(obj: Any) -> list[dict[str, Any]] | None:
        if isinstance(obj, dict):
            if "features" in obj and isinstance(obj["features"], list):
                return obj["features"]
            for v in obj.values():
                res = find_features(v)
                if res is not None:
                    return res
        elif isinstance(obj, list):
            for v in obj:
                res = find_features(v)
                if res is not None:
                    return res
        return None

    features = find_features(settings) or []
    listings: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for feat in features:
        props = feat.get("properties") or {}
        desc_html = props.get("description") or ""
        # Skip units explicitly marked "Not Available"
        if "not-available" in desc_html.lower():
            continue

        card = BeautifulSoup(desc_html, "lxml")
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"].replace("/index.php/", "/")
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        card_text = clean_text(card.get_text(" ", strip=True))
        if parse_bedrooms_strict(card_text) != 4:
            continue

        m_pella_rent = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", card_text)
        rent_total = parse_rent_number(m_pella_rent.group(1)) if m_pella_rent else None
        if not rent_total or rent_total <= 0:
            continue

        # Coordinates [lng, lat]
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        lng = float(coords[0]) if len(coords) >= 2 else None
        lat = float(coords[1]) if len(coords) >= 2 else None

        # Title & Neighborhood
        h2 = card.find("h2")
        title = clean_text(h2.get_text()) if h2 else (props.get("tooltip") or "")
        address = ensure_columbus_address(title)

        avail_el = card.select_one(".available-date")
        available_date = clean_text(avail_el.get_text()) if avail_el else None

        hover_divs = card.select(".hover-details > div")
        neighborhood = clean_text(hover_divs[-1].get_text()) if len(hover_divs) >= 2 else None

        img = card.find("img")
        photos = [urljoin(base_url, img["src"])] if img and img.get("src") else []

        slug = href.rstrip("/").split("/")[-1]
        if not is_columbus_area(lat, lng, address):
            continue

        listings.append(
            {
                "id": f"pella-{slug}",
                "source": "Pella Co",
                "title": title,
                "address": address,
                "neighborhood": neighborhood,
                "lat": lat,
                "lng": lng,
                "rentTotal": rent_total,
                "rentPerPerson": round(rent_total / 4),
                "bedrooms": 4,
                "bathrooms": None,
                "sqft": None,
                "availableDate": available_date,
                "leaseTerm": "12 Months",
                "landlord": "Pella Co",
                "parking": None,
                "petsAllowed": None,
                "petPolicy": None,
                "amenities": [],
                "description": "",
                "photos": photos,
                "url": full_url,
            }
        )

    if listings:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            listings = list(ex.map(enrich_pella_detail, listings))

    return listings


def main() -> None:
    all_listings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    print("Scraping AppFolio portals...")
    for prefix, source_name, base_url in APPFOLIO_PORTALS:
        t0 = time.time()
        try:
            items = scrape_appfolio_portal(prefix, source_name, base_url)
            counts[source_name] = len(items)
            all_listings.extend(items)
            print(f"  [OK] {source_name}: {len(items)} 4BR Columbus listings ({time.time() - t0:.1f}s)")
        except Exception as exc:
            counts[source_name] = 0
            print(f"  [ERR] {source_name}: {exc}")

    print("Scraping Hometeam Properties...")
    t0 = time.time()
    try:
        ht_items = scrape_hometeam()
        counts["Hometeam Properties"] = len(ht_items)
        all_listings.extend(ht_items)
        print(f"  [OK] Hometeam Properties: {len(ht_items)} 4BR Columbus listings ({time.time() - t0:.1f}s)")
    except Exception as exc:
        counts["Hometeam Properties"] = 0
        print(f"  [ERR] Hometeam Properties: {exc}")

    print("Scraping Pella Co...")
    t0 = time.time()
    try:
        pella_items = scrape_pella()
        counts["Pella Co"] = len(pella_items)
        all_listings.extend(pella_items)
        print(f"  [OK] Pella Co: {len(pella_items)} 4BR Columbus listings ({time.time() - t0:.1f}s)")
    except Exception as exc:
        counts["Pella Co"] = 0
        print(f"  [ERR] Pella Co: {exc}")

    # Final deduplication by id
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in all_listings:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            deduped.append(item)

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "raw_landlords.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print("\n=== SUMMARY ===")
    for src, cnt in counts.items():
        print(f"  {src}: {cnt}")
    print(f"  TOTAL: {len(deduped)} listings written to {out_path}")


if __name__ == "__main__":
    main()
