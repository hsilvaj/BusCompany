import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE_URL = "https://traveling.com/en-us/companies"
LOGOS_DIR = Path("logos_global")
CSV_OUTPUT = Path("global_companies.csv")
JSON_OUTPUT = Path("global_companies.json")
RAW_CACHE = Path("companies_raw.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

CSV_FIELDS = [
    "id", "operator", "country", "transport_type",
    "logo_url", "logo_file", "rating", "number_of_routes", "profile_url",
]


def fetch_companies() -> list[dict]:
    if RAW_CACHE.exists():
        print(f"Loading cached data from {RAW_CACHE} ...")
        # Accept cache files saved both with and without a UTF-8 BOM.
        with RAW_CACHE.open(encoding="utf-8-sig") as f:
            return json.load(f)

    print(f"Fetching {BASE_URL} ...")
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    match = re.search(r'data-companies="([^"]*(?:""[^"]*)*)"', resp.text)
    if not match:
        raise ValueError("Could not find data-companies attribute in page")

    raw = match.group(1)
    raw = (
        raw.replace("&quot;", '"')
           .replace("&amp;", "&")
           .replace("&#039;", "'")
           .replace("&lt;", "<")
           .replace("&gt;", ">")
    )
    data = json.loads(raw)
    with RAW_CACHE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Cached {len(data)} companies to {RAW_CACHE}")
    return data


def transport_type(company: dict) -> str:
    return "FERRY" if company.get("isFerryCompany") else "BUS"


def logo_filename(logo_url: str) -> str:
    path = urlparse(logo_url).path
    return path.rstrip("/").split("/")[-1]


def download_logo(url: str, dest: Path) -> bool:
    if not url or dest.exists():
        return dest.exists()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        if len(resp.content) < 200:
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"  [warn] Logo download failed for {url}: {e}")
        return False


def main() -> None:
    LOGOS_DIR.mkdir(exist_ok=True)

    raw_companies = fetch_companies()
    print(f"Processing {len(raw_companies)} companies ...")

    companies: list[dict] = []
    for i, raw in enumerate(raw_companies, 1):
        name = raw.get("Name", "").strip()
        country = raw.get("country_name", "").strip()
        transport = transport_type(raw)
        logo_url = raw.get("logoUrl", "") or ""

        profile_url = ""
        profiles = raw.get("companyProfiles") or []
        if profiles:
            profile_url = profiles[0].get("companyProfileUrl", "")

        logo_file = ""
        if logo_url:
            fname = logo_filename(logo_url)
            dest = LOGOS_DIR / fname
            if download_logo(logo_url, dest):
                logo_file = fname

        status = f"-> {logo_file}" if logo_file else "-> no logo"
        print(f"  [{i:04d}] [{transport}] {name} ({country}) {status}")

        companies.append({
            "id": i,
            "operator": name,
            "country": country,
            "transport_type": transport,
            "logo_url": logo_url,
            "logo_file": logo_file,
            "rating": raw.get("rating", ""),
            "number_of_routes": raw.get("numberOfRoutes", ""),
            "profile_url": profile_url,
        })

        time.sleep(0.05)

    with CSV_OUTPUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(companies)
    print(f"\nSaved {CSV_OUTPUT} ({len(companies)} rows)")

    with JSON_OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"Saved {JSON_OUTPUT} ({len(companies)} entries)")

    with_logo = sum(1 for c in companies if c["logo_file"])
    print(
        f"\nDone. {len(companies)} companies, "
        f"{with_logo} logos downloaded to {LOGOS_DIR}/."
    )


if __name__ == "__main__":
    main()
