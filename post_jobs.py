"""
Kuvukiland Job Bot — Fixed Version
Fixes:
  1. No repeated posts (posted.txt properly persisted via GitHub Actions)
  2. No TinyURL — direct article URLs used
  3. Dead sources removed, edupstairs.org + strong SA sources added
  4. Post links go directly to the actual job/learnership article page
"""

import os, re, time, requests, random
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

try:
    from lxml import etree as lxml_etree
    LXML_AVAILABLE = True
except ImportError:
    LXML_AVAILABLE = False

PAGE_ID     = os.environ.get("FB_PAGE_ID", "")
PAGE_TOKEN  = os.environ.get("FB_PAGE_TOKEN", "")
GRAPH_URL   = f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed"
POSTED_FILE = "posted.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-ZA,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}

SA_LOCATIONS = [
    "Johannesburg CBD", "Soweto", "Sandton", "Randburg", "Roodepoort",
    "Fourways", "Midrand", "Diepsloot", "Orange Farm", "Lenasia",
    "Eldorado Park", "Ennerdale", "Alexandra", "Westdene", "Melville",
    "Parktown", "Braamfontein", "Newtown", "Jeppestown", "Yeoville",
    "Boksburg", "Benoni", "Brakpan", "Springs", "Nigel",
    "Alberton", "Germiston", "Ekurhuleni", "Tembisa", "Kempton Park",
    "Edenvale", "Bedfordview", "Katlehong", "Thokoza", "Vosloorus",
    "Daveyton", "Tsakane", "Krugersdorp", "Randfontein", "Westonaria",
    "Carletonville", "Kagiso", "Vereeniging", "Vanderbijlpark",
    "Sebokeng", "Evaton", "Meyerton", "Heidelberg Gauteng",
    "Pretoria CBD", "Centurion", "Soshanguve", "Mamelodi",
    "Atteridgeville", "Mabopane", "Garankuwa", "Hammanskraal",
    "Temba", "Winterveld", "Hatfield", "Menlyn", "Lynnwood",
    "Montana", "Akasia", "Wonderboom", "Eersterust", "Silverton",
    "Durban CBD", "Umlazi", "KwaMashu", "Inanda", "Phoenix",
    "Chatsworth", "Isipingo", "Pinetown", "Westville", "Hillcrest",
    "Amanzimtoti", "Umhlanga", "Ballito", "Tongaat", "Richards Bay",
    "Newcastle", "Ladysmith", "Pietermaritzburg", "Edendale",
    "Gqeberha", "Uitenhage", "East London", "Mthatha", "Queenstown",
    "Cape Town CBD", "Bellville", "Mitchells Plain", "Khayelitsha",
    "Gugulethu", "Nyanga", "Langa", "Delft", "Stellenbosch",
    "George", "Knysna", "Mossel Bay", "Paarl", "Worcester",
    "Polokwane", "Seshego", "Mokopane", "Tzaneen", "Thohoyandou",
    "Nelspruit", "Witbank", "Emalahleni", "Middelburg MP", "Secunda",
    "Bloemfontein", "Mangaung", "Welkom", "Kroonstad", "Sasolburg",
    "Rustenburg", "Klerksdorp", "Potchefstroom", "Mahikeng", "Brits",
    "Kimberley", "Upington",
    "South Africa (Nationwide)",
]

GOOD_KEYWORDS = [
    "learnership", "internship", "apprentice", "trainee",
    "vacancy", "vacancies", "entry level", "entry-level",
    "graduate", "youth", "matric", "grade 12", "bursary",
    "yes programme", "nyda", "seta", "nqf",
]

BAD_KEYWORDS = [
    "honours", "masters", "phd", "postgraduate",
    "5 years experience", "10 years", "executive", "head of", "director",
    "scam", "fake", "fraud", "warning", "not offering", "beware",
    "hoax", "misleading", "suspended", "arrested",
    "court", "murder", "killed", "died", "protest", "strike",
    "looting", "crime", "convicted", "tender", "parliament",
    "survey", "guide to", "what is",
    "celebrating", "top 10", "list of", "here are",
    "everything you need", "2024",
]

# ─────────────────────────────────────────────
# RSS SOURCES — dead ones removed, strong ones added
# edupstairs.org does not have an RSS feed so we scrape it directly
# ─────────────────────────────────────────────
RSS_SOURCES = [
    {
        "url": "https://www.salearnership.co.za/feed/",
        "source": "SA Learnership",
    },
    {
        "url": "https://learnerships24.co.za/feed/",
        "source": "Learnerships24",
    },
    {
        "url": "https://www.myjobmag.co.za/rss/jobs.xml",
        "source": "MyJobMag SA",
    },
    {
        "url": "https://www.careers24.com/rss/jobs/",
        "source": "Careers24",
    },
    {
        "url": "https://southafricain.com/feed/",
        "source": "South Africa In",
    },
    {
        "url": "https://www.prostudy.co.za/feed/",
        "source": "ProStudy",
    },
    {
        "url": "https://zaboutjobs.com/feed/",
        "source": "ZA Jobs",
    },
    {
        "url": "https://www.jobplacements.com/rss/allrss.asp",
        "source": "Job Placements SA",
    },
    {
        "url": "https://mabumbe.com/jobs/feed/",
        "source": "Mabumbe Jobs",
    },
    {
        "url": "https://www.afterschoolafrica.com/feed/",
        "source": "After School Africa",
    },
    {
        "url": "https://youthvillage.co.za/feed/",
        "source": "Youth Village SA",
    },
    {
        "url": "https://skillsportal.co.za/feed/",
        "source": "Skills Portal",
    },
]

# ─────────────────────────────────────────────
# EDUPSTAIRS DIRECT SCRAPER (no RSS available)
# ─────────────────────────────────────────────
def scrape_edupstairs():
    listings = []
    try:
        url = "https://www.edupstairs.org/"
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  Edupstairs: HTTP {r.status_code} — skipping")
            return listings

        # Extract all article/post links from the homepage
        links = re.findall(r'href=["\']((https?://www\.edupstairs\.org/[^"\']+))["\']', r.text)
        seen = set()
        for _, link in links:
            link = link.rstrip("/")
            # Skip category/tag/page links, only take article links
            if any(x in link for x in ["/category/", "/tag/", "/page/", "/author/", "/#", "/feed"]):
                continue
            if link in seen or len(link) < 40:
                continue
            seen.add(link)

            # Get the page title from the link text or fetch it
            # Try to extract title from surrounding anchor text
            pattern = rf'href=["\']({re.escape(link)})["\'][^>]*>([^<]{{5,100}})<'
            m = re.search(pattern, r.text)
            title = m.group(2).strip() if m else ""

            if not title:
                # Try to fetch page and get title tag
                try:
                    pr = requests.get(link, headers=HEADERS, timeout=10)
                    tm = re.search(r'<title>([^<]+)</title>', pr.text)
                    title = unescape(tm.group(1)).split("|")[0].strip() if tm else ""
                except Exception:
                    title = link.split("/")[-1].replace("-", " ").title()

            if not title:
                continue

            # Filter relevance
            if is_relevant(title, ""):
                listings.append({
                    "title": title[:120],
                    "link": link,
                    "source": "Edupstairs",
                })
                print(f"    Edupstairs ✔ {title[:60]}")

        print(f"  Edupstairs: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Edupstairs error: {e}")
    return listings


# ─────────────────────────────────────────────
# XML PARSING
# ─────────────────────────────────────────────
def aggressive_clean_xml(text):
    text = text.lstrip('\ufeff')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('\x00', '')
    replacements = {
        '\x80': '', '\x81': '', '\x82': "'", '\x83': 'f',
        '\x84': '"', '\x85': '...', '\x86': '+', '\x87': '+',
        '\x88': '^', '\x89': '', '\x8a': 'S', '\x8b': '<',
        '\x8c': 'OE', '\x8d': '', '\x8e': 'Z', '\x8f': '',
        '\x90': '', '\x91': "'", '\x92': "'", '\x93': '"',
        '\x94': '"', '\x95': '*', '\x96': '-', '\x97': '-',
        '\x98': '~', '\x99': '', '\x9a': 's', '\x9b': '>',
        '\x9c': 'oe', '\x9d': '', '\x9e': 'z', '\x9f': 'Y',
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def parse_feed_xml(raw_bytes, source_name=""):
    # Strategy 1: aggressive clean + ET
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
        text = aggressive_clean_xml(text)
        root = ET.fromstring(text.encode("utf-8"))
        items = root.findall(".//item")
        if items:
            print(f"    [ET] parsed OK — {len(items)} items")
            return items
    except ET.ParseError as e:
        print(f"    [ET] ParseError: {e}")

    # Strategy 2: lxml recover
    if LXML_AVAILABLE:
        try:
            parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
            root = lxml_etree.fromstring(raw_bytes, parser=parser)
            items = root.findall(".//item")
            if items:
                print(f"    [lxml XML] parsed OK — {len(items)} items")
                return items
        except Exception as e:
            print(f"    [lxml XML] error: {e}")

        try:
            root = lxml_etree.fromstring(raw_bytes, lxml_etree.HTMLParser(recover=True))
            items = root.findall(".//item")
            if items:
                print(f"    [lxml HTML] parsed OK — {len(items)} items")
                return items
        except Exception as e:
            print(f"    [lxml HTML] error: {e}")

    try:
        preview = raw_bytes[:200].decode("utf-8", errors="replace")
        print(f"    [DEBUG] Preview: {repr(preview)}")
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted(key):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(key + "\n")


def make_key(title):
    return re.sub(r'\s+', ' ', title[:60].lower().strip())


def is_relevant(title, summary=""):
    text = (title + " " + summary).lower()
    action = [
        "apply", "application", "opportunity",
        "hiring", "opening", "available", "2026", "invited",
    ]
    has_job = any(k in text for k in GOOD_KEYWORDS)
    has_act = any(k in text for k in action)
    has_bad = any(k in text for k in BAD_KEYWORDS)
    return has_job and has_act and not has_bad


def is_real_article_url(url):
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url.startswith("http"):
        return False
    if "google.com" in url:
        return False
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path or len(path) < 4:
            return False
        if len(url) < 35:
            return False
        return True
    except Exception:
        return False


def extract_urls_from_html(html_text):
    found = []
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text)
    for h in hrefs:
        h = h.rstrip('.,;)')
        if is_real_article_url(h) and "google.com" not in h:
            found.append(h)
    plain = re.findall(r'https?://[^\s"\'<>]+', html_text)
    for u in plain:
        u = u.rstrip('.,;)')
        if is_real_article_url(u) and u not in found:
            found.append(u)
    return found


def get_text(element):
    if element is None:
        return ""
    return (element.text or "").strip()


def get_item_link(item):
    # Try <link> tag first
    l = item.find("link")
    link_text = get_text(l)
    if is_real_article_url(link_text):
        return link_text

    # Try <description> for embedded URLs
    d = item.find("description")
    if d is not None and d.text:
        desc = unescape(d.text)
        urls = extract_urls_from_html(desc)
        if urls:
            return urls[0]

    return None


# ─────────────────────────────────────────────
# CLOSING DATE EXTRACTION
# ─────────────────────────────────────────────
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def parse_date(s):
    s = s.strip()
    for fmt in ["%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.title(), fmt)
        except ValueError:
            continue
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', s, re.I)
    if m:
        day, mon, yr = m.groups()
        month = MONTH_MAP.get(mon.lower())
        if month:
            try:
                return datetime(int(yr), month, int(day))
            except ValueError:
                pass
    return None


def extract_closing_date(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        text = r.text
        patterns = [
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Cc]loses?\s+[Oo]n\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Dd]eadline\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Aa]pply\s+[Bb]efore\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Aa]pplications?\s+[Cc]lose\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'(\d{1,2}\s+(?:January|February|March|April|May|June|'
            r'July|August|September|October|November|December)\s+202[567])',
            r'(\d{1,2}/\d{1,2}/202[567])',
        ]
        found = []
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                parsed = parse_date(m.group(1))
                if parsed:
                    found.append(parsed)
        if not found:
            print("   ℹ️  No closing date found on page")
            return None
        latest = max(found)
        fmt = latest.strftime("%d %B %Y")
        if latest > datetime.now():
            print(f"   ✅ Closing date: {fmt}")
            return fmt
        else:
            print(f"   ❌ EXPIRED: {fmt}")
            return "EXPIRED"
    except Exception as e:
        print(f"   ⚠️  Could not read article: {e}")
        return None


def extract_job_snippet(url):
    """
    Pull a 2-line description snippet from the article page
    to make the Facebook post more informative.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        text = r.text
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Find section with useful content (after "Requirements" or "Description")
        match = re.search(
            r'(?:requirements?|qualifications?|description|overview)[:\s]+(.{80,400})',
            clean, re.I
        )
        if match:
            snippet = match.group(1).strip()[:280]
            # Cut at sentence boundary
            cut = re.search(r'[.!?]', snippet[60:])
            if cut:
                snippet = snippet[:60 + cut.start() + 1]
            return snippet
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────
# FETCH ALL RSS LISTINGS
# ─────────────────────────────────────────────
def fetch_rss_listings():
    all_listings = []
    for src in RSS_SOURCES:
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=20)
            print(f"  {src['source']}: HTTP {r.status_code}, {len(r.content)} bytes")

            if r.status_code != 200:
                print(f"    ⚠️  Non-200 — skipping")
                time.sleep(1)
                continue

            items = parse_feed_xml(r.content, src["source"])
            if not items:
                time.sleep(1)
                continue

            accepted = 0
            for item in items[:20]:
                t = item.find("title")
                d = item.find("description")
                title = get_text(t)
                if title:
                    title = unescape(title)

                summary = ""
                if d is not None and d.text:
                    summary = re.sub(r"<[^>]+>", "", unescape(d.text))

                # Clean source suffix from title
                title = re.sub(r'\s*[|\-–]\s*[^|\-–]+$', '', title).strip()

                link = get_item_link(item)
                if not link:
                    continue

                if is_relevant(title, summary):
                    all_listings.append({
                        "title": title[:120],
                        "link": link,
                        "source": src["source"],
                    })
                    accepted += 1

            print(f"    → {accepted} relevant listings accepted")
            time.sleep(1.5)

        except requests.exceptions.ConnectionError:
            print(f"  {src['source']} — could not connect, skipping")
        except Exception as e:
            print(f"  {src['source']} error: {e}")

    return all_listings


def fetch_all_listings():
    all_listings = fetch_rss_listings()

    # Add edupstairs scrape
    edupstairs = scrape_edupstairs()
    all_listings.extend(edupstairs)

    # Deduplicate by title key
    seen, unique = set(), []
    for j in all_listings:
        key = make_key(j["title"])
        if key not in seen:
            seen.add(key)
            unique.append(j)

    random.shuffle(unique)
    return unique


# ─────────────────────────────────────────────
# POST BUILDING
# ─────────────────────────────────────────────
def build_post(job, direct_url, closing_date, location, snippet=""):
    cl = (
        f"📅 Closing Date: {closing_date}"
        if closing_date
        else "📅 Closing Date: Check the link below"
    )
    snippet_line = f"\n📝 {snippet}\n" if snippet else "\n"
    return (
        f"🔌 Nasi iSpan 🚨\n\n"
        f"💼 {job['title']}\n"
        f"{snippet_line}"
        f"✔ Grade 12 / Matric\n"
        f"✔ No experience required\n"
        f"📍 {location}\n"
        f"{cl}\n"
        f"🌐 Source: {job.get('source', 'Online')}\n\n"
        f"👇 Click to read full details & apply:\n"
        f"{direct_url}\n\n"
        f"💡 Share this — help a young person!\n"
        f"👉 Follow Kuvukiland for daily opportunities\n\n"
        f"#Learnership #EntryLevel #Grade12Jobs #YouthEmployment "
        f"#SouthAfrica #Matric #NoExperience #KuvukilandJobs "
        f"#Internship #GovernmentJobs #SETA #Kuvukiland"
    )


def post_to_facebook(message, link):
    if not PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set.")
        return None
    payload = {
        "message": message,
        "link": link,          # Facebook will auto-generate a rich preview card
        "access_token": PAGE_TOKEN,
        "published": "true",
    }
    try:
        r = requests.post(GRAPH_URL, data=payload, timeout=20)
        result = r.json()
        if "id" in result:
            print(f"  ✅ Posted! ID: {result['id']}")
            return result["id"]
        else:
            print(f"  ❌ Failed: {result}")
            return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print(
        f"\n🤖 Kuvukiland Job Bot — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if LXML_AVAILABLE:
        print("✅ lxml available\n")
    else:
        print("⚠️  lxml not available\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs\n")
    print("Fetching listings...\n")

    listings = fetch_all_listings()
    print(f"\n✅ Total unique listings: {len(listings)}\n")

    if not listings:
        print("⚠️ No listings found this run.")
        return

    posted_this_run = 0
    MAX_PER_RUN = 1  # Post 1 per run (runs every 30 min = ~48/day max)

    for listing in listings:
        if posted_this_run >= MAX_PER_RUN:
            break

        key = make_key(listing["title"])
        if key in already_posted:
            print(f"⏭  Already posted: {listing['title'][:50]}")
            continue

        print(f"\n📤 Trying: {listing['title'][:70]}")
        print(f"   URL: {listing['link'][:80]}")

        print("🔍 Checking closing date...")
        closing = extract_closing_date(listing["link"])
        if closing == "EXPIRED":
            save_posted(key)   # Mark expired so we never try again
            continue

        # ── Use the direct article URL — NO TinyURL ──
        direct_url = listing["link"]
        print(f"   Direct link: {direct_url}")

        # Pull a description snippet from the article
        print("   Extracting snippet...")
        snippet = extract_job_snippet(direct_url)

        location = random.choice(SA_LOCATIONS)
        post = build_post(listing, direct_url, closing, location, snippet)

        print("\n--- POST PREVIEW ---")
        print(post)
        print("--------------------\n")

        result = post_to_facebook(post, direct_url)
        if result:
            save_posted(key)
            posted_this_run += 1
            print("✅ Done.")


if __name__ == "__main__":
    main()
