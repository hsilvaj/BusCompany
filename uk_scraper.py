import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from duckduckgo_search import DDGS

WIKI_API_URL = (
    "https://uktransport.fandom.com/api.php"
    "?action=parse"
    "&page=List_of_bus_operators_of_the_United_Kingdom"
    "&prop=wikitext"
    "&format=json"
)
LOGO_DEV_API_KEY = "sk_d3rKWV-7RTOYvh5fKGGIDQ"
LOGO_DEV_SEARCH = "https://api.logo.dev/search"
LOGOS_DIR = Path("logos_uk")
CSV_OUTPUT = Path("uk_companies.csv")
JSON_OUTPUT = Path("uk_companies.json")
CSV_FIELDS = ["id", "operator", "country", "state", "company_type", "domain", "logo_url", "logo_file"]
COUNTRY = "United Kingdom"

# delay between DuckDuckGo searches to avoid throttling
SEARCH_DELAY = 1.5

# domains that are NOT company websites — skip these in search results
SKIP_DOMAINS = {
    "wikipedia.org", "fandom.com", "wikimedia.org", "wikidata.org",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "youtube.com", "tiktok.com",
    "yell.com", "yelp.com", "trustpilot.com", "checkatrade.com",
    "tripadvisor.com", "tripadvisor.co.uk",
    "indeed.com", "glassdoor.com", "reed.co.uk",
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "companies-house.gov.uk", "find-and-update.company-information.service.gov.uk",
    "companieshouse.gov.uk", "gov.uk",
    "busesforsale.co.uk", "trucklocator.co.uk", "autotrader.co.uk",
    "transportfocus.org.uk", "dft.gov.uk",
    "busweb.co.uk", "travelinesoutheast.org.uk", "traveline.info",
    "roblox.com", "marketwatch.com", "bloomberg.com", "reuters.com",
    "yellowpages.com", "whitepages.com", "bizapedia.com", "Companies-House.gov.uk",
    "rightmove.co.uk", "zoopla.co.uk", "booking.com", "airbnb.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TOURISM_KEYWORDS = ("coach", "tour", "travel")
INTERCITY_KEYWORDS = ("express", "intercity", "lines")


def fetch_wikitext() -> str:
    print("Fetching wikitext from MediaWiki API ...")
    resp = requests.get(WIKI_API_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["parse"]["wikitext"]["*"]


def parse_company_names(wikitext: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []

    for line in wikitext.splitlines():
        line = line.strip()
        if not line.startswith("*"):
            continue
        content = re.sub(r"^\*+\s*", "", line)
        content = content.replace("''", "").replace("'''", "")
        content = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]+)\]\]", r"\1", content)
        content = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", content)
        content = re.sub(r"[\[\]{}|<>]", "", content).strip()
        content = re.sub(r"\s*\(.*\)\s*$", "", content).strip()

        if not content or len(content) < 3:
            continue
        key = content.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(content)

    print(f"Extracted {len(names)} unique company names from wikitext.")
    return names


def classify_company(name: str) -> str | None:
    lower = name.lower()
    if any(kw in lower for kw in TOURISM_KEYWORDS):
        return "TOURISM"
    if any(kw in lower for kw in INTERCITY_KEYWORDS):
        return "INTERCITY"
    return None


def is_skip_domain(domain: str) -> bool:
    for skip in SKIP_DOMAINS:
        if domain == skip or domain.endswith("." + skip):
            return True
    return False


def search_company_domain(name: str) -> str:
    """Search DuckDuckGo for the company's official website, return its domain."""
    query = f'"{name}" bus coach UK official site'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=8))
        for r in results:
            url = r.get("href", "")
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc.lower().removeprefix("www.")
            if not domain or is_skip_domain(domain):
                continue
            return domain
    except Exception as e:
        print(f"  [warn] Search failed for '{name}': {e}")
    finally:
        time.sleep(SEARCH_DELAY)
    return ""


def fetch_and_save_logo(domain: str) -> tuple[str, str]:
    """
    Queries Logo.dev search by domain to get the signed logo_url (with pk_ token),
    then downloads the image to logos_uk/. Returns (logo_url, logo_file).
    """
    if not domain:
        return "", ""
    try:
        resp = requests.get(
            LOGO_DEV_SEARCH,
            params={"q": domain},
            headers={**HEADERS, "Authorization": f"Bearer {LOGO_DEV_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data if isinstance(data, list) else data.get("value", [])
        if not results:
            return "", ""
        logo_url = results[0].get("logo_url", "")
        if not logo_url:
            return "", ""
    except Exception as e:
        print(f"  [warn] Logo.dev search failed for '{domain}': {e}")
        return "", ""
    finally:
        time.sleep(0.25)

    # download the image
    safe_name = re.sub(r"[^\w.\-]", "_", domain) + ".png"
    dest = LOGOS_DIR / safe_name
    try:
        img_resp = requests.get(logo_url, headers=HEADERS, timeout=15)
        img_resp.raise_for_status()
        if len(img_resp.content) < 500:  # skip blank placeholders
            return logo_url, ""
        dest.write_bytes(img_resp.content)
        return logo_url, safe_name
    except Exception as e:
        print(f"  [warn] Logo download failed for '{domain}': {e}")
        return logo_url, ""


def save_csv(companies: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(companies)
    print(f"Saved {path} ({len(companies)} rows)")


def save_json(companies: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"Saved {path} ({len(companies)} entries)")


def main() -> None:
    LOGOS_DIR.mkdir(exist_ok=True)

    wikitext = fetch_wikitext()
    all_names = parse_company_names(wikitext)

    companies: list[dict] = []
    id_counter = 1

    for name in all_names:
        company_type = classify_company(name)
        if company_type is None:
            continue

        domain = search_company_domain(name)
        logo_url, logo_file = fetch_and_save_logo(domain)

        status = f"-> {domain}" + (f" (logo saved)" if logo_file else " (no logo)") if domain else "-> no domain"
        print(f"  [{id_counter:03d}] [{company_type}] {name} {status}")

        companies.append({
            "id": id_counter,
            "operator": name,
            "country": COUNTRY,
            "state": "",
            "company_type": company_type,
            "domain": domain,
            "logo_url": logo_url,
            "logo_file": logo_file,
        })
        id_counter += 1

    if not companies:
        print("No companies matched TOURISM or INTERCITY criteria.")
        return

    save_csv(companies, CSV_OUTPUT)
    save_json(companies, JSON_OUTPUT)

    with_logo = sum(1 for c in companies if c["logo_file"])
    print(
        f"\nDone. {len(companies)} companies collected, "
        f"{with_logo} logos downloaded to logos_uk/."
    )


if __name__ == "__main__":
    main()
