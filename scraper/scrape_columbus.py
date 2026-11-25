"""
Broader Columbus / Central Ohio 4-bedroom rental listings scraper.

Sources:
  1. Rent.com (Columbus + surrounding suburbs: houses & apartments, 4-bedroom)
  2. Craigslist Columbus (4-bedroom apartments/houses)
  3. Broader Columbus AppFolio portals:
       - Evernest (filtered strictly to Central Ohio / Columbus)
       - Real Estate Opportunity
       - Lykens Companies
       - Wood Companies
       - Columbus PM
       - Ohio State Properties

Outputs strictly 4-bedroom, Central Ohio listings to data/raw_columbus.json.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
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

# Strict Central Ohio / Columbus bounding box (~20-25 min drive radius around OSU)
LAT_MIN = 39.75
LAT_MAX = 40.25
LNG_MIN = -83.30
LNG_MAX = -82.70

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
    "lewis center",
    "galena",
    "galloway",
    "west jefferson",
    "pataskala",
    "short north",
    "victorian village",
    "italian village",
    "german village",
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
    "Grandview Heights",
    "Grandview",
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
    "Lewis Center",
    "Blacklick",
    "Pickerington",
    "Canal Winchester",
    "Groveport",
    "Galloway",
    "Merion Village",
    "Brewery District",
    "Olde Towne East",
    "King-Lincoln",
    "Linden",
    "North Linden",
    "Eastmoor",
    "Berwick",
    "Beechwold",
    "Downtown",
]

RENTCOM_SUBURBS = [
    "columbus",
    "dublin",
    "westerville",
    "hilliard",
    "grove-city",
    "worthington",
    "upper-arlington",
    "gahanna",
    "reynoldsburg",
    "bexley",
    "whitehall",
    "grandview-heights",
    "new-albany",
    "powell",
]

APPFOLIO_PORTALS = [
    ("evernest", "Evernest", "https://evernest.appfolio.com", 30),
    ("reo", "Real Estate Opportunity", "https://realestateopportunity.appfolio.com", 15),
    ("lykens", "Lykens Companies", "https://lykens.appfolio.com", 15),
    ("wood", "Wood Companies", "https://woodcompanies.appfolio.com", 10),
    ("columbuspm", "Columbus PM", "https://columbuspm.appfolio.com", 5),
    ("ohiostateproperties", "Ohio State Properties", "https://ohiostateproperties.appfolio.com", 5),
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


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def is_central_ohio(lat: float | None, lng: float | None, address: str) -> bool:
    if lat is not None and lng is not None:
        return LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX
    addr_low = (address or "").lower()
    if any(city in addr_low for city in COLUMBUS_CITIES):
        if re.search(r",\s*[a-z]{2}\b", addr_low) and not re.search(r",\s*oh\b|\bohio\b", addr_low):
            return False
        return True
    if re.search(r"\boh\s*43[012]\d{2}\b", addr_low):
        return True
    return False


def ensure_ohio_address(address: str) -> str:
    addr = clean_text(address)
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
    m = re.search(r"\$?\s*([0-9][0-9,]*(?:\.\d{1,2})?)", str(text))
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
    if re.search(r"\b\d+\s*[-–/]\s*\d+\s*(?:bd|br|bed|bedroom)", text, re.I):
        return None
    m = re.search(r"\b(\d+)\s*(?:\+)?\s*(?:bd|br|bed|beds|bedroom|bedrooms)\b", text, re.I)
    if not m:
        return None
    if "+" in m.group(0):
        return None
    return int(m.group(1))


def parse_bathrooms(text: str | None) -> float | None:
    if not text:
        return None
    t = str(text).replace("½", ".5").replace("1/2", ".5")
    t = re.sub(r"(\d)\s+\.5", r"\1.5", t)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath|baths|bathroom|bathrooms)\b", t, re.I)
    if not m:
        m2 = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", t)
        if m2:
            return float(m2.group(1))
        return None
    return float(m.group(1))


def parse_sqft(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"([0-9][0-9,]{2,5})\s*(?:sq\.?\s*ft\.?|sqft|ft\s*2|square\s*feet)?", str(text), re.I)
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
    policy = clean_text(pet_policy) or None
    if policy:
        low = policy.lower()
        if (
            "no pets" in low
            or "cats not allowed, dogs not allowed" in low
            or ("not allowed" in low and "allowed" not in low.replace("not allowed", ""))
        ):
            return False, policy
        if "allowed" in low or "pet friendly" in low or "pet-friendly" in low or "cats" in low or "dogs" in low:
            return True, policy
    combined = " ".join([text or ""] + amenities).lower()
    if "no pets" in combined or "pets not allowed" in combined:
        return False, policy or "No pets allowed"
    if (
        "pets allowed" in combined
        or "pet friendly" in combined
        or "pet-friendly" in combined
        or "cats are ok" in combined
        or "dogs are ok" in combined
    ):
        return True, policy or "Pets allowed"
    return None, policy


def infer_neighborhood(text: str, address: str) -> str | None:
    combined = f"{text} {address}"
    for nb in KNOWN_NEIGHBORHOODS:
        if re.search(rf"\b{re.escape(nb)}\b", combined, re.I):
            return nb
    return None


def normalize_rent(rent_val: int | None, context_text: str) -> int | None:
    """Apply per-person multiplier if labeled per-person, and reject < $900 spam."""
    if not rent_val or rent_val <= 0:
        return None
    low = context_text.lower()
    is_per_person = bool(
        re.search(
            r"\b(?:per\s*bed|per\s*person|/\s*bed|/\s*person|by\s*the\s*bed|each\s*person)\b",
            low,
        )
    )
    if rent_val < 1300 and is_per_person:
        rent_val = rent_val * 4
    if rent_val < 900:
        return None
    return rent_val


# ---------------------------------------------------------------------------
# 1. Rent.com Scraper
# ---------------------------------------------------------------------------
def _extract_rentcom_4br_specs(item: dict[str, Any]) -> tuple[int | None, float | None, int | None]:
    """Return (rent_total, bathrooms, sqft) strictly for 4-bedroom configuration."""
    fps = [fp for fp in (item.get("floorPlans") or []) if fp.get("bedCount") == 4]
    if fps:
        rents: list[int] = []
        baths: list[float] = []
        sqfts: list[int] = []
        for fp in fps:
            pr = fp.get("priceRange") or {}
            r_min = pr.get("min") or pr.get("max")
            if isinstance(r_min, (int, float)) and r_min > 0:
                rents.append(int(round(r_min)))
            else:
                for u in fp.get("units") or []:
                    u_rent = parse_rent_number(u.get("rent"))
                    if u_rent:
                        rents.append(u_rent)
            bc = fp.get("bathCount")
            if isinstance(bc, (int, float)) and bc > 0:
                baths.append(float(bc))
            sr = fp.get("sqFtRange") or {}
            s_min = sr.get("min") or sr.get("max")
            if isinstance(s_min, (int, float)) and 300 <= s_min <= 20000:
                sqfts.append(int(round(s_min)))
        rent_val = min(rents) if rents else None
        bath_val = baths[0] if baths else parse_bathrooms(item.get("bathText"))
        sqft_val = min(sqfts) if sqfts else parse_sqft(item.get("squareFeetText"))
        if rent_val:
            return rent_val, bath_val, sqft_val

    # Fallback: check bedCountData or bedRange/bedText
    bed_range = item.get("bedRange") or {}
    b_min = bed_range.get("min")
    b_max = bed_range.get("max")
    bed_text = item.get("bedText") or ""
    strict_4br = (b_min == 4 and b_max == 4) or (parse_bedrooms_strict(bed_text) == 4)

    bed_count_data = [b for b in (item.get("bedCountData") or []) if b.get("beds") == 4]
    if not strict_4br and not bed_count_data:
        return None, None, None

    rent_val: int | None = None
    if bed_count_data:
        low_p = (bed_count_data[0].get("prices") or {}).get("low")
        if isinstance(low_p, (int, float)) and low_p > 0:
            rent_val = int(round(low_p))
    if not rent_val and strict_4br:
        pr = item.get("priceRange") or {}
        p_raw = pr.get("min") or item.get("price") or parse_rent_number(item.get("priceText"))
        if isinstance(p_raw, (int, float)) and p_raw > 0:
            rent_val = int(round(p_raw))

    if not rent_val:
        return None, None, None

    bath_val = parse_bathrooms(item.get("bathText")) if strict_4br else None
    sqft_val = parse_sqft(item.get("squareFeetText")) if strict_4br else None
    return rent_val, bath_val, sqft_val


def scrape_rentcom() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # Build seed URLs: Columbus paginated + suburb pages
    seed_bases: list[tuple[str, int]] = [
        ("https://www.rent.com/ohio/columbus-houses/4-bedroom", 10),
        ("https://www.rent.com/ohio/columbus-apartments/4-bedroom", 10),
    ]
    for sub in RENTCOM_SUBURBS:
        if sub == "columbus":
            continue
        seed_bases.append((f"https://www.rent.com/ohio/{sub}-houses/4-bedroom", 3))
        seed_bases.append((f"https://www.rent.com/ohio/{sub}-apartments/4-bedroom", 3))

    for base_url, max_pages in seed_bases:
        for page in range(1, max_pages + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            html = fetch_html(url)
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")
            nd = soup.find("script", id="__NEXT_DATA__")
            if not nd or not nd.string:
                break
            try:
                data = json.loads(nd.string)
            except json.JSONDecodeError:
                break

            ls = (
                data.get("props", {})
                .get("pageProps", {})
                .get("pageData", {})
                .get("location", {})
                .get("listingSearch", {})
            )
            listings = ls.get("listings") or []
            if not listings:
                break

            total = ls.get("total") or 0
            new_on_page = 0

            for item in listings:
                rid = str(item.get("id") or "")
                if not rid or rid in seen_ids:
                    continue

                loc = item.get("location") or {}
                lat = loc.get("lat")
                lng = loc.get("lng")
                try:
                    lat = float(lat) if lat is not None else None
                    lng = float(lng) if lng is not None else None
                except (TypeError, ValueError):
                    lat, lng = None, None

                address = clean_text(item.get("addressFull") or item.get("address") or "")
                if not is_central_ohio(lat, lng, address):
                    continue
                address = ensure_ohio_address(address)

                rent_raw, bathrooms, sqft = _extract_rentcom_4br_specs(item)
                title = clean_text(item.get("name") or item.get("address") or address)
                rent_total = normalize_rent(rent_raw, f"{title} {item.get('priceText') or ''}")
                if not rent_total:
                    continue

                seen_ids.add(rid)
                new_on_page += 1

                url_path = item.get("urlPathname") or ""
                full_url = urljoin("https://www.rent.com", url_path) if url_path else url

                # Photos
                photos: list[str] = []
                seen_p: set[str] = set()
                for ph in item.get("photos") or []:
                    pid = ph.get("id")
                    if pid and pid not in seen_p:
                        seen_p.add(pid)
                        photos.append(f"https://i.rent.com/t_3x2_fixed_webp_lg/{pid}")
                if not photos:
                    for fp in item.get("floorPlans") or []:
                        if fp.get("bedCount") == 4:
                            for ph in fp.get("photos") or []:
                                pid = ph.get("id")
                                if pid and pid not in seen_p:
                                    seen_p.add(pid)
                                    photos.append(f"https://i.rent.com/t_3x2_fixed_webp_lg/{pid}")

                amenities = [clean_text(a) for a in (item.get("amenitiesHighlighted") or []) if clean_text(a)]
                highlights = [clean_text(h) for h in (item.get("uniqueHighlights") or []) if clean_text(h)]
                for h_item in highlights:
                    if h_item not in amenities:
                        amenities.append(h_item)

                pmc = (item.get("propertyManagementCompany") or {}).get("name")
                landlord = clean_text(pmc) or "Rent.com Listing"

                prop_type = (item.get("propertyType") or "").replace("_", " ").title()
                desc_parts = [p for p in [prop_type, item.get("unitsAvailableText"), ", ".join(highlights)] if p]
                description = clean_text(" - ".join(desc_parts)) or f"4-bedroom rental at {address}"

                lease_terms = item.get("leasingTerms") or []
                lease_term = ", ".join(str(t) for t in lease_terms if t) or None

                avail_status = item.get("availabilityStatus")
                available_date = "Available Now" if avail_status == "TODAY" else (str(avail_status) if avail_status else None)

                pets_allowed, pet_policy = parse_pets(None, description, amenities)
                parking = infer_parking(description, amenities)
                city_str = clean_text(loc.get("city") or "")
                neighborhood = infer_neighborhood(f"{title} {city_str}", address) or (city_str if city_str and city_str.lower() != "columbus" else None)

                results.append(
                    {
                        "id": f"rentcom-{rid}",
                        "source": "Rent.com",
                        "title": title,
                        "address": address,
                        "neighborhood": neighborhood,
                        "lat": lat,
                        "lng": lng,
                        "rentTotal": rent_total,
                        "rentPerPerson": round(rent_total / 4),
                        "bedrooms": 4,
                        "bathrooms": bathrooms,
                        "sqft": sqft,
                        "availableDate": available_date,
                        "leaseTerm": lease_term,
                        "landlord": landlord,
                        "parking": parking,
                        "petsAllowed": pets_allowed,
                        "petPolicy": pet_policy,
                        "amenities": amenities,
                        "description": description,
                        "photos": photos,
                        "url": full_url,
                    }
                )

            if total and page * 30 >= total:
                break
            if new_on_page == 0 and page > 1:
                break

    print(f"  [Rent.com] {len(results)} 4BR Central Ohio listings")
    return results


# ---------------------------------------------------------------------------
# 2. Craigslist Columbus Scraper
# ---------------------------------------------------------------------------
def _enrich_craigslist_detail(item: dict[str, Any]) -> dict[str, Any]:
    html = fetch_html(item["url"], timeout=20, retries=1)
    if not html:
        return item
    soup = BeautifulSoup(html, "lxml")

    # Photos from var imgList
    photos: list[str] = []
    seen_p: set[str] = set()
    m_img = re.search(r"var imgList\s*=\s*(\[.*?\]);", html, re.S)
    if m_img:
        try:
            imgs = json.loads(m_img.group(1))
            for im in imgs:
                u = im.get("url")
                if u and u not in seen_p:
                    seen_p.add(u)
                    photos.append(u)
        except json.JSONDecodeError:
            pass
    if not photos:
        for img in soup.select("#postingbody img, .gallery img, img"):
            src = img.get("src") or ""
            if "images.craigslist.org" in src and "50x50" not in src and src not in seen_p:
                seen_p.add(src)
                photos.append(src)
    if photos:
        item["photos"] = photos

    # Body description
    body = soup.select_one("#postingbody")
    if body:
        # Remove QR code notice
        for qr in body.select(".print-information"):
            qr.decompose()
        desc = clean_text(body.get_text(" ", strip=True))
        desc = re.sub(r"^QR Code Link to This Post\s*", "", desc, flags=re.I)
        if desc:
            item["description"] = desc

    # Attributes (.attrgroup)
    attrs: list[str] = []
    for el in soup.select(".attrgroup span, .attrgroup .attr"):
        t = clean_text(el.get_text(" ", strip=True))
        if t and t not in attrs:
            attrs.append(t)

    attr_text = " ".join(attrs)
    if not item.get("sqft"):
        item["sqft"] = parse_sqft(attr_text)
    if not item.get("bathrooms"):
        item["bathrooms"] = parse_bathrooms(attr_text)

    for a in attrs:
        low = a.lower()
        if "available" in low and not item.get("availableDate"):
            item["availableDate"] = a
        elif any(k in low for k in ("cats", "dogs", "pets", "garage", "parking", "laundry", "w/d", "air conditioning", "furnished", "wheelchair")):
            if a not in item["amenities"]:
                item["amenities"].append(a)

    # Map address if more specific
    map_addr = soup.select_one(".mapaddress")
    if map_addr:
        ma = clean_text(map_addr.get_text(" ", strip=True))
        if ma and len(ma) > len(item["address"]):
            item["address"] = ensure_ohio_address(ma)

    # Re-evaluate pets, parking, neighborhood, and per-person check
    pets_allowed, pet_policy = parse_pets(item.get("petPolicy"), f"{item['description']} {attr_text}", item["amenities"])
    item["petsAllowed"] = pets_allowed
    if pet_policy:
        item["petPolicy"] = pet_policy
    if not item.get("parking"):
        item["parking"] = infer_parking(f"{item['description']} {attr_text}", item["amenities"])
    if not item.get("neighborhood"):
        item["neighborhood"] = infer_neighborhood(f"{item['title']} {item['description']}", item["address"])

    return item


def scrape_craigslist() -> list[dict[str, Any]]:
    url = "https://columbus.craigslist.org/search/apa?min_bedrooms=4&max_bedrooms=4&availabilityMode=0"
    html = fetch_html(url)
    if not html:
        print("  [Craigslist] Failed to fetch search page")
        return []

    soup = BeautifulSoup(html, "lxml")

    # Parse ld+json itemListElement
    ld_items: list[dict[str, Any]] = []
    for ld in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(ld.string or "{}")
            if isinstance(d, dict) and "itemListElement" in d:
                ld_items = d["itemListElement"]
                break
        except json.JSONDecodeError:
            pass

    cards = soup.select("li.cl-static-search-result")
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for idx, card in enumerate(cards):
        a_tag = card.select_one("a[href]")
        if not a_tag:
            continue
        detail_url = a_tag["href"]
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)

        title_el = card.select_one(".title")
        price_el = card.select_one(".price")
        loc_el = card.select_one(".location")

        title = clean_text(title_el.get_text()) if title_el else ""
        price_str = clean_text(price_el.get_text()) if price_el else ""
        loc_str = clean_text(loc_el.get_text()) if loc_el else ""

        ld_item = (ld_items[idx].get("item") or {}) if idx < len(ld_items) else {}

        # Strict 4BR check
        beds_ld = ld_item.get("numberOfBedrooms")
        if beds_ld is not None and beds_ld != 4:
            continue
        if beds_ld is None:
            parsed_beds = parse_bedrooms_strict(title)
            if parsed_beds is not None and parsed_beds != 4:
                continue

        # Lat / Lng
        lat = ld_item.get("latitude")
        lng = ld_item.get("longitude")
        try:
            lat = float(lat) if lat is not None else None
            lng = float(lng) if lng is not None else None
        except (TypeError, ValueError):
            lat, lng = None, None

        addr_obj = ld_item.get("address") or {}
        street = clean_text(addr_obj.get("streetAddress") or "")
        locality = clean_text(addr_obj.get("addressLocality") or "")
        region = clean_text(addr_obj.get("addressRegion") or "")
        postal = clean_text(addr_obj.get("postalCode") or "")
        ld_addr = ", ".join(p for p in [street, locality, f"{region} {postal}".strip()] if p)
        address = loc_str or ld_addr or "Columbus, OH"

        if not is_central_ohio(lat, lng, address):
            continue
        address = ensure_ohio_address(address)

        rent_raw = parse_rent_number(price_str)
        # Craigslist prompt rule: skip posts with rent < $800 (likely per-room/spam) unless clearly per-person or whole 4BR
        if not rent_raw:
            continue
        if rent_raw < 1300 and re.search(r"\b(?:per\s*bed|per\s*person|/\s*bed|/\s*person|each)\b", title, re.I):
            rent_total = rent_raw * 4
        elif rent_raw < 800:
            continue
        else:
            rent_total = rent_raw

        baths = ld_item.get("numberOfBathroomsTotal")
        try:
            bathrooms = float(baths) if baths is not None else None
        except (TypeError, ValueError):
            bathrooms = None

        # Unique ID from trailing Craigslist ID segment
        cl_id = detail_url.rstrip("/").split("/")[-1]
        neighborhood = infer_neighborhood(f"{title} {loc_str}", address)

        candidates.append(
            {
                "id": f"cl-{cl_id}",
                "source": "Craigslist",
                "title": title or address,
                "address": address,
                "neighborhood": neighborhood,
                "lat": lat,
                "lng": lng,
                "rentTotal": rent_total,
                "rentPerPerson": round(rent_total / 4),
                "bedrooms": 4,
                "bathrooms": bathrooms,
                "sqft": None,
                "availableDate": None,
                "leaseTerm": None,
                "landlord": "Craigslist",
                "parking": None,
                "petsAllowed": None,
                "petPolicy": None,
                "amenities": [],
                "description": title,
                "photos": [],
                "url": detail_url,
            }
        )

    # Enrich detail pages concurrently
    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            candidates = list(ex.map(_enrich_craigslist_detail, candidates))

    # Post-enrichment filter for per-bed spam discovered in description
    final_cl: list[dict[str, Any]] = []
    for item in candidates:
        low_desc = f"{item['title']} {item['description']}".lower()
        if item["rentTotal"] < 900:
            if re.search(r"\b(?:per\s*bed|per\s*person|/\s*bed|/\s*person|by\s*the\s*bed)\b", low_desc):
                item["rentTotal"] = item["rentTotal"] * 4
                item["rentPerPerson"] = round(item["rentTotal"] / 4)
            elif not re.search(r"\b(?:4\s*br|4\s*bed|4\s*bedroom|whole\s*house|entire)\b", low_desc):
                continue
        # Reject if description explicitly says 1/2/3/5 bedroom and not 4
        if re.search(r"\b(?:1|2|3|5|6)\s*(?:br|bed|bedroom)s?\b", low_desc) and not re.search(r"\b4\s*(?:br|bed|bedroom)s?\b", low_desc):
            continue
        final_cl.append(item)

    print(f"  [Craigslist] {len(final_cl)} 4BR Central Ohio listings")
    return final_cl


# ---------------------------------------------------------------------------
# 3. AppFolio Portals Scraper
# ---------------------------------------------------------------------------
def extract_appfolio_markers(html: str) -> dict[str, dict[str, Any]]:
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
    html = fetch_html(listing["url"], timeout=20, retries=1)
    if not html:
        return listing
    soup = BeautifulSoup(html, "lxml")

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
            if "images.cdn.appfolio.com" in src and "place_holder" not in src and src not in seen_photos:
                seen_photos.add(src)
                photos.append(src)
    if photos:
        listing["photos"] = photos

    desc_el = soup.select_one(".listing-detail__description")
    if desc_el:
        full_desc = clean_text(desc_el.get_text(" ", strip=True))
        if len(full_desc) > len(listing.get("description") or ""):
            listing["description"] = full_desc

    detail_amenities: list[str] = []
    for li in soup.select(".list--amenities li, .listing-detail__amenities li"):
        t = clean_text(li.get_text(" ", strip=True))
        if t and t not in detail_amenities:
            detail_amenities.append(t)
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

    full_page_text = clean_text(soup.get_text(" ", strip=True))
    if not listing.get("leaseTerm"):
        m_lease = re.search(
            r"(?:Lease\s*Terms?|Term)\s*[:\-]?\s*(\d+\s*Months?|1\s*Year|12\s*Months?|Month[- ]to[- ]Month|Flexible)",
            full_page_text,
            re.I,
        )
        if m_lease:
            listing["leaseTerm"] = m_lease.group(1).strip()

    if not listing.get("parking"):
        listing["parking"] = infer_parking(listing["description"], listing["amenities"])
    pets_allowed, pet_policy = parse_pets(listing.get("petPolicy"), listing["description"], listing["amenities"])
    if listing.get("petsAllowed") is None and pets_allowed is not None:
        listing["petsAllowed"] = pets_allowed
    if not listing.get("petPolicy") and pet_policy:
        listing["petPolicy"] = pet_policy

    return listing


def scrape_appfolio_portal(prefix: str, source_name: str, base_url: str, max_pages: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    next_url: str | None = f"{base_url}/listings"
    page_num = 0

    while next_url and page_num < max_pages:
        page_num += 1
        html = fetch_html(next_url)
        if not html:
            break

        markers_map = extract_appfolio_markers(html)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".js-listing-item")
        if not cards:
            break

        for card in cards:
            facts: dict[str, str] = {}
            for item in card.select(".detail-box__item"):
                dt = item.select_one("dt")
                dd = item.select_one("dd")
                if dt and dd:
                    facts[clean_text(dt.get_text()).lower()] = clean_text(dd.get_text())

            link = card.select_one("a.js-link-to-detail, .js-listing-title a, a[href*='/listings/detail/']")
            detail_path = link.get("href") if link else None
            if not detail_path:
                continue
            detail_url = urljoin(base_url, detail_path)
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            card_id = (card.get("id") or "").replace("listing_", "").strip()
            marker = markers_map.get(card_id) or markers_map.get(detail_path) or {}

            bed_bath_str = facts.get("bed / bath") or ""
            if not bed_bath_str:
                bb_el = card.select_one(".js-listing-blurb-bed-bath")
                bed_bath_str = clean_text(bb_el.get_text()) if bb_el else ""
            if not bed_bath_str:
                bed_bath_str = marker.get("unit_specs") or ""

            bedrooms = parse_bedrooms_strict(bed_bath_str)
            if bedrooms != 4:
                continue

            addr_el = card.select_one(".js-listing-address")
            address = clean_text(addr_el.get_text()) if addr_el else (marker.get("address") or "")
            lat = marker.get("latitude")
            lng = marker.get("longitude")
            try:
                lat = float(lat) if lat is not None else None
                lng = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lat, lng = None, None

            if not is_central_ohio(lat, lng, address):
                continue
            address = ensure_ohio_address(address)

            title_el = card.select_one(".js-listing-title")
            title = clean_text(title_el.get_text()) if title_el else address

            rent_str = facts.get("rent") or ""
            if not rent_str:
                r_el = card.select_one(".js-listing-blurb-rent")
                rent_str = clean_text(r_el.get_text()) if r_el else (marker.get("rent_range") or "")
            rent_val = parse_rent_number(rent_str)

            desc_el = card.select_one(".js-listing-description")
            description = clean_text(desc_el.get_text(" ", strip=True)) if desc_el else ""

            rent_total = normalize_rent(rent_val, f"{rent_str} {title} {description}")
            if not rent_total:
                continue

            bathrooms = parse_bathrooms(bed_bath_str)
            sqft = parse_sqft(facts.get("square feet") or marker.get("unit_specs"))

            avail_str = facts.get("available")
            if not avail_str:
                av_el = card.select_one(".js-listing-available")
                avail_str = clean_text(av_el.get_text()).replace("Available ", "") if av_el else None
            available_date = avail_str if avail_str else None

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

            pet_el = card.select_one(".js-listing-pet-policy")
            pet_policy_raw = None
            if pet_el:
                pet_policy_raw = clean_text(pet_el.get_text(" ", strip=True))
                pet_policy_raw = re.sub(r"^Pet\s*Policy:\s*", "", pet_policy_raw, flags=re.I).strip()
            pets_allowed, pet_policy = parse_pets(pet_policy_raw, description, amenities)

            photos: list[str] = []
            img_el = card.select_one("img.listing-item__image, img")
            if img_el:
                img_src = img_el.get("data-original") or img_el.get("src") or ""
                if img_src and "place_holder" not in img_src:
                    photos.append(urljoin(base_url, img_src))
            if not photos and marker.get("default_photo_url"):
                photos.append(urljoin(base_url, marker["default_photo_url"]))

            listing_uid = card_id or detail_path.rstrip("/").split("/")[-1]
            results.append(
                {
                    "id": f"{prefix}-{listing_uid}",
                    "source": source_name,
                    "title": title,
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
                    "description": description or f"4-bedroom rental at {address}",
                    "photos": photos,
                    "url": detail_url,
                }
            )

        next_link = soup.select_one("a.next_page, .pagination a[rel='next'], a[rel='next']")
        if next_link and next_link.get("href"):
            next_url = urljoin(base_url, next_link["href"])
        else:
            next_url = None

    if results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(enrich_appfolio_detail, results))

    print(f"  [{source_name}] {len(results)} 4BR Central Ohio listings (pages={page_num})")
    return results


def main() -> None:
    print("Starting broader Columbus / Central Ohio 4-bedroom scraper...")
    all_listings: list[dict[str, Any]] = []

    print("\n1. Scraping Rent.com...")
    all_listings.extend(scrape_rentcom())

    print("\n2. Scraping Craigslist Columbus...")
    all_listings.extend(scrape_craigslist())

    print("\n3. Scraping Central Ohio AppFolio portals...")
    for prefix, name, url, max_pages in APPFOLIO_PORTALS:
        all_listings.extend(scrape_appfolio_portal(prefix, name, url, max_pages))

    # Deduplicate by ID and URL
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for item in all_listings:
        if item["id"] in seen_ids or item["url"] in seen_urls:
            continue
        if item["bedrooms"] != 4 or item["rentTotal"] <= 0:
            continue
        seen_ids.add(item["id"])
        seen_urls.add(item["url"])
        deduped.append(item)

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw_columbus.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(deduped)} total 4BR listings to {out_path}")


if __name__ == "__main__":
    main()
