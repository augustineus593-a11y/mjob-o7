"""
Kuvukiland Job Bot - Multi-source with direct article URLs
Uses lxml as fallback for feeds with malformed/invalid XML characters
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
    "Bronkhorstspruit", "Cullinan", "Rayton", "Bapsfontein",
    "Durban CBD", "Umlazi", "KwaMashu", "Inanda", "Phoenix",
    "Chatsworth", "Isipingo", "Pinetown", "Westville", "Hillcrest",
    "Amanzimtoti", "Umhlanga", "Ballito", "Tongaat", "Verulam",
    "Waterloo", "Newlands West", "Sydenham", "Berea", "Glenwood",
    "Bluff", "Wentworth", "Merebank",
    "Pietermaritzburg", "Edendale", "Plessislaer", "Northdale",
    "Howick", "Hilton", "Mooi River",
    "Stanger", "KwaDukuza", "Mandeni", "Gingindlovu",
    "Eshowe", "Empangeni", "Richards Bay",
    "Ulundi", "Nongoma", "Vryheid", "Paulpietersburg", "Louwsburg",
    "Nqutu", "Msinga", "Tugela Ferry", "Pongola", "Mkuze",
    "Hluhluwe", "Mtubatuba", "Jozini",
    "Port Shepstone", "Margate", "Scottburgh", "Umkomaas",
    "Hibberdene", "Uvongo", "Shelly Beach",
    "Newcastle", "Madadeni", "Osizweni", "Dundee", "Glencoe",
    "Ladysmith", "Estcourt", "Bergville", "Winterton",
    "Underberg", "Ixopo", "Umzimkulu", "Kokstad",
    "Harding", "Kranskop", "Greytown",
    "Gqeberha", "Uitenhage", "Despatch", "East London",
    "Mdantsane", "Bhisho", "King William's Town",
    "Mthatha", "Butterworth", "Lusikisiki", "Flagstaff",
    "Port St Johns", "Queenstown", "Aliwal North",
    "Cradock", "Graaff-Reinet", "Makhanda",
    "Fort Beaufort", "Jeffreys Bay", "Humansdorp",
    "Cape Town CBD", "Bellville", "Mitchells Plain", "Khayelitsha",
    "Gugulethu", "Nyanga", "Langa", "Delft", "Kuils River",
    "Kraaifontein", "Stellenbosch", "Somerset West",
    "Gordon's Bay", "Strand", "Paarl", "Wellington", "Franschhoek",
    "George", "Knysna", "Mossel Bay", "Oudtshoorn", "Beaufort West",
    "Worcester", "Robertson", "Swellendam", "Hermanus", "Grabouw",
    "Caledon", "Bredasdorp", "Malmesbury", "Vredenburg",
    "Langebaan", "Saldanha", "Vredendal", "Clanwilliam",
    "Polokwane", "Seshego", "Lebowakgomo", "Mokopane",
    "Modimolle", "Bela-Bela", "Thabazimbi", "Lephalale",
    "Tzaneen", "Phalaborwa", "Giyani", "Thohoyandou",
    "Makhado", "Louis Trichardt", "Musina",
    "Marble Hall", "Groblersdal", "Burgersfort",
    "Nelspruit", "Mbombela", "Witbank", "Emalahleni",
    "Middelburg MP", "Secunda", "Standerton", "Ermelo",
    "Piet Retief", "Barberton", "Hazyview", "White River",
    "Bloemfontein", "Mangaung", "Botshabelo", "Welkom",
    "Kroonstad", "Phuthaditjhaba", "Bethlehem", "Harrismith",
    "Sasolburg", "Parys",
    "Mahikeng", "Rustenburg", "Brits", "Klerksdorp",
    "Potchefstroom", "Lichtenburg", "Hartbeespoort",
    "Kimberley", "Upington", "Springbok", "De Aar", "Kuruman",
    "South Africa (Nationwide)",
]

GOOD_KEYWORDS = [
    "learnership", "internship", "apprentice", "trainee",
    "vacancy", "vacancies", "entry level", "entry-level",
    "graduate", "youth", "matric", "grade 12",
]

BAD_KEYWORDS = [
    "honours", "masters", "phd", "postgraduate",
    "5 years", "10 years", "executive", "head of", "director",
    "scam", "fake", "fraud", "warning", "not offering", "beware",
    "hoax", "misleading", "bursary", "suspended", "arrested",
    "court", "murder", "killed", "died", "protest", "strike",
    "looting", "crime", "convicted", "tender", "parliament",
    "survey", "study", "guide to", "what is",
    "celebrating", "unemployment", "economy", "graduation",
    "graduates celebrated", "top 10", "list of", "here are",
    "how to", "everything you need", "2025",
]

RSS_SOURCES = [
    {
        "url": "https://www.salearnership.co.za/feed/",
        "source": "SA Learnership",
    },
    {
        "url": "https://mabumbe.com/feed/",
        "source": "Mabumbe",
    },
    {
        "url": "https://www.afterschoolafrica.com/feed/",
        "source": "After School Africa",
    },
    {
        "url": "https://learnerships.net/feed/",
        "source": "Learnerships.net",
    },
    {
        "url": "https://southafricain.com/feed/",
        "source": "South Africa In",
    },
    {
        "url": "https://www.jobvine.co.za/rss/",
        "source": "Jobvine",
    },
    {
        "url": "https://zaboutjobs.com/feed/",
        "source": "SA Jobs",
    },
    {
        "url": "https://www.prostudy.co.za/feed/",
        "source": "ProStudy",
    },
]


# ─────────────────────────────────────────────
# XML PARSING WITH DEBUG LOGGING
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
    """
    Try 3 strategies to parse RSS feed bytes.
    Logs exactly what went wrong at each stage for debugging.
    """
    # Strategy 1: aggressive clean + ET
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
        text = aggressive_clean_xml(text)
        root = ET.fromstring(text.encode("utf-8"))
        items = root.findall(".//item")
        if items:
            print(f"    [Strategy 1 - ET] parsed OK")
            return items
        else:
            print(f"    [Strategy 1 - ET] parsed but 0 <item> tags found")
    except ET.ParseError as e:
        print(f"    [Strategy 1 - ET] ParseError: {e}")

    # Strategy 2: lxml recover=True
    if LXML_AVAILABLE:
        try:
            parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
            root = lxml_etree.fromstring(raw_bytes, parser=parser)
            items = root.findall(".//item")
            if items:
                print(f"    [Strategy 2 - lxml XML] parsed OK")
                return items
            else:
                print(f"    [Strategy 2 - lxml XML] parsed but 0 <item> tags found")
        except Exception as e:
            print(f"    [Strategy 2 - lxml XML] error: {e}")

        # Strategy 3: lxml HTML parser
        try:
            root = lxml_etree.fromstring(
                raw_bytes,
                lxml_etree.HTMLParser(recover=True)
            )
            items = root.findall(".//item")
            if items:
                print(f"    [Strategy 3 - lxml HTML] parsed OK")
                return items
            else:
                print(f"    [Strategy 3 - lxml HTML] parsed but 0 <item> tags found")
        except Exception as e:
            print(f"    [Strategy 3 - lxml HTML] error: {e}")

    # Log the first 300 chars of what we actually received
    try:
        preview = raw_bytes[:300].decode("utf-8", errors="replace")
        print(f"    [DEBUG] Response preview: {repr(preview)}")
    except Exception:
        pass

    return []


# ─────────────────────────────────────────────
# UNIVERSAL URL VALIDATION
# ─────────────────────────────────────────────

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
        if is_real_article_url(u) and "google.com" not in u:
            if u not in found:
                found.append(u)
    return found


def get_text(element):
    if element is None:
        return ""
    return (element.text or "").strip()


def get_item_link(item):
    l = item.find("link")
    link_text = get_text(l)
    if is_real_article_url(link_text):
        return link_text

    d = item.find("description")
    if d is not None and d.text:
        desc = unescape(d.text)
        urls = extract_urls_from_html(desc)
        if urls:
            return urls[0]

    s = item.find("source")
    if s is not None:
        src_url = (s.get("url") or "").strip()
        if is_real_article_url(src_url) and "google.com" not in src_url:
            return src_url

    return None


def shorten_url(long_url):
    try:
        r = requests.get(
            f"https://tinyurl.com/api-create.php?url={long_url}",
            timeout=10,
        )
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except Exception:
        pass
    return long_url


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
            print("   ℹ️  No closing date found")
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


# ─────────────────────────────────────────────
# FETCH ALL LISTINGS
# ─────────────────────────────────────────────

def fetch_all_listings():
    all_listings = []
    for src in RSS_SOURCES:
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=20)
            print(f"  {src['source']}: HTTP {r.status_code}, {len(r.content)} bytes")

            if r.status_code != 200:
                print(f"    ⚠️  Non-200 response — skipping")
                time.sleep(1)
                continue

            items = parse_feed_xml(r.content, src["source"])

            if not items:
                time.sleep(1)
                continue

            print(f"  {src['source']}: {len(items)} items")
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

    seen, unique = set(), []
    for j in all_listings:
        key = make_key(j["title"])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    random.shuffle(unique)
    return unique


# ─────────────────────────────────────────────
# POST BUILDING & FACEBOOK
# ─────────────────────────────────────────────

def build_post(job, apply_link, closing_date, location):
    cl = (
        f"📅 Closing Date: {closing_date}"
        if closing_date
        else "📅 Closing Date: See link"
    )
    return (
        f"🔌 Nasi iSpan 🚨\n\n"
        f"{job['title']}\n\n"
        f"✔ Grade 12 / Matric\n"
        f"✔ No experience required\n"
        f"📍 {location}\n"
        f"{cl}\n"
        f"🌐 Source: {job.get('source', 'Online')}\n\n"
        f"👇 Apply directly here:\n"
        f"{apply_link}\n\n"
        f"💡 Share this — help a young person!\n"
        f"👉 Follow Kuvukiland for daily opportunities\n\n"
        f"#Learnership #EntryLevel #Grade12Jobs #YouthEmployment "
        f"#SouthAfrica #Matric #NoExperience #KuvukilandJobs "
        f"#Internship #GovernmentJobs #SETA"
    )


def post_to_facebook(message):
    if not PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set.")
        return None
    payload = {
        "message": message,
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
        print("✅ lxml available — malformed feeds will be recovered\n")
    else:
        print("⚠️  lxml not available — only clean feeds will parse\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs\n")
    print("Fetching listings...\n")

    listings = fetch_all_listings()
    print(f"\n✅ Total unique listings: {len(listings)}\n")

    if not listings:
        print("⚠️ No listings found this run.")
        return

    for listing in listings:
        key = make_key(listing["title"])
        if key in already_posted:
            print(f"⏭  Already posted: {listing['title'][:50]}")
            continue

        print(f"\n📤 Trying: {listing['title'][:70]}")
        print(f"   URL: {listing['link'][:80]}")

        print("🔍 Checking closing date...")
        closing = extract_closing_date(listing["link"])
        if closing == "EXPIRED":
            save_posted(key)
            continue

        short = shorten_url(listing["link"])
        print(f"   Short link: {short}")

        location = random.choice(SA_LOCATIONS)
        post = build_post(listing, short, closing, location)

        print("\n--- POST PREVIEW ---")
        print(post)
        print("--------------------\n")

        result = post_to_facebook(post)
        if result:
            save_posted(key)
            print("✅ Done.")
        break


if __name__ == "__main__":
    main()
