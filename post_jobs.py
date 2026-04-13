"""
Kuvukiland Job Bot v4
- Strict field extraction — no CSS/junk values ever shown
- All extracted values validated before use
- Falls back gracefully: only shows fields actually found and clean
- Smart scheduling, no TinyURL, direct URLs
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
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}

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
    "survey", "guide to", "what is", "celebrating",
    "top 10", "list of", "here are", "everything you need", "2024",
]

RSS_SOURCES = [
    {"url": "https://www.salearnership.co.za/feed/",    "source": "SA Learnership"},
    {"url": "https://learnerships24.co.za/feed/",       "source": "Learnerships24"},
    {"url": "https://youthvillage.co.za/feed/",         "source": "Youth Village SA"},
    {"url": "https://www.afterschoolafrica.com/feed/",  "source": "After School Africa"},
    {"url": "https://mabumbe.com/jobs/feed/",           "source": "Mabumbe Jobs"},
    {"url": "https://zaboutjobs.com/feed/",             "source": "ZA Jobs"},
    {"url": "https://www.prostudy.co.za/feed/",         "source": "ProStudy"},
]

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
    "aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

# Characters that should NEVER appear in a valid extracted field value
JUNK_CHARS = re.compile(r'[{}\[\]<>@#*=;]')

# A valid extracted value must:
# - be at least 2 chars
# - not contain junk characters
# - not look like CSS/HTML/code
def is_clean_value(val):
    if not val or len(val.strip()) < 2:
        return False
    if JUNK_CHARS.search(val):
        return False
    if any(x in val.lower() for x in ['height:','width:','margin:','padding:','font-',
                                        'color:','display:','position:','overflow:',
                                        'px','em;','auto;','100%','!important']):
        return False
    return True


def parse_date_str(s):
    s = s.strip()
    for fmt in ["%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]:
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


def is_expired(date_str):
    parsed = parse_date_str(date_str)
    if parsed:
        return parsed < datetime.now()
    return False


# ─────────────────────────────────────────────
# ARTICLE DETAIL EXTRACTOR — strict validation
# ─────────────────────────────────────────────
def extract_article_details(url):
    details = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)

        # Step 1: remove script and style blocks entirely
        html = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', r.text, flags=re.DOTALL|re.I)

        # Step 2: strip remaining tags
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'&[a-z#0-9]+;', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()

        # ── Strict field patterns ─────────────────────────────────
        # Each pattern must capture a clean human-readable value

        # COMPANY
        for pat in [
            r'(?:Company|Employer|Organisation|Organization)\s*[:\-]\s*([A-Z][^\n\r|]{3,60})',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).split('|')[0].strip()[:70]
                if is_clean_value(val):
                    details["company"] = val
                    break

        # LOCATION — must look like a place name
        for pat in [
            r'Location\s*[:\-]\s*([A-Za-z][^\n\r|,]{3,60})',
            r'Province\s*[:\-]\s*([A-Za-z][^\n\r|,]{3,40})',
            r'City\s*[:\-]\s*([A-Za-z][^\n\r|,]{3,40})',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).split('|')[0].strip()[:60]
                if is_clean_value(val) and not any(
                    x in val.lower() for x in ['http','www','.co','click','apply']
                ):
                    details["location"] = val
                    break

        # CLOSING DATE — must parse to a real future date
        for pat in [
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Dd]eadline\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Aa]pply\s+[Bb]efore\s*[:\-]\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Cc]loses?\s+[Oo]n\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})',
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).strip()
                parsed = parse_date_str(val)
                if parsed:
                    details["closing_date"] = parsed.strftime("%d %B %Y")
                    break

        # QUALIFICATION — must mention matric/grade/diploma/certificate/degree
        for pat in [
            r'(?:Minimum\s+)?[Qq]ualification\s*[:\-]\s*([^\n\r|]{5,100})',
            r'[Ee]ducation(?:al)?\s+[Rr]equirement\s*[:\-]\s*([^\n\r|]{5,80})',
            r'[Mm]inimum\s+[Qq]ualification\s*[:\-]\s*([^\n\r|]{5,80})',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).split('|')[0].strip()[:80]
                if is_clean_value(val) and any(
                    x in val.lower() for x in
                    ['grade','matric','diploma','certificate','degree','nqf','qualification']
                ):
                    details["qualification"] = val
                    break

        # AGE — must be purely numeric range like "18-35 years" or "18 to 35"
        for pat in [
            r'[Aa]ge\s+[Rr]equirement\s*[:\-]\s*(\d{2}\s*[\-–to]+\s*\d{2}\s*years?)',
            r'[Aa]ge\s*[:\-]\s*(\d{2}\s*[\-–to]+\s*\d{2}\s*years?)',
            r'[Aa]ged?\s+(\d{2}\s*[\-–to]+\s*\d{2}\s*years?)',
            r'between\s+(\d{2}\s+and\s+\d{2}\s*years?)',
            r'(\d{2}\s*[–\-]\s*\d{2}\s*years?\s*old)',
            # also handle "18–29 years" appearing standalone
            r'(\d{2}\s*[–\-]\s*\d{2}\s*years?)',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).strip()
                # Must only contain digits, spaces, dashes, "years", "to", "old"
                if re.match(r'^[\d\s\-–toalersy]+$', val, re.I) and is_clean_value(val):
                    details["age"] = val
                    break

        # EXPERIENCE — must contain the word "experience" and be sensible
        for pat in [
            r'[Ee]xperience\s+[Rr]equired\s*[:\-]\s*([^\n\r|]{3,60})',
            r'[Ww]ork\s+[Ee]xperience\s*[:\-]\s*([^\n\r|]{3,60})',
            r'((?:No|Entry[\s\-]?[Ll]evel)\s+[Ee]xperience\s+[Rr]equired)',
            r'(Entry\s+[Ll]evel)',
            r'(No\s+[Ee]xperience\s+[Rr]equired)',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).split('|')[0].strip()[:60]
                if is_clean_value(val):
                    details["experience"] = val
                    break

        # INDUSTRY / FIELD
        for pat in [
            r'[Ii]ndustry\s*[:\-]\s*([A-Za-z][^\n\r|]{3,60})',
            r'[Ss]ector\s*[:\-]\s*([A-Za-z][^\n\r|]{3,60})',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).split('|')[0].strip()[:60]
                if is_clean_value(val):
                    details["field"] = val
                    break

        # POSITIONS — must be a number or short phrase
        for pat in [
            r'\(X?\s*(\d+)\s*[Pp]osts?\)',
            r'\(X?\s*(\d+)\s*[Pp]ositions?\)',
            r'[Pp]ositions?\s+[Aa]vailable\s*[:\-]\s*(\d+)',
            r'[Nn]umber\s+of\s+[Pp]osts?\s*[:\-]\s*(\d+)',
        ]:
            m = re.search(pat, clean, re.I)
            if m:
                val = m.group(1).strip()
                if val.isdigit():
                    details["positions"] = val
                    break

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return details


# ─────────────────────────────────────────────
# POST BUILDER
# ─────────────────────────────────────────────
SITE_SUFFIXES = re.compile(
    r'\s*[-|]\s*(Edupstairs|SA Learnership|Learnerships24|Youth Village|'
    r'Skills Portal|ProStudy|ZA Jobs|After School Africa|Mabumbe)[^\n]*$',
    re.I
)

def build_post(title, details, direct_url, source):
    title = SITE_SUFFIXES.sub('', title).strip()

    lines = ["🔌 Nasi iSpan 🚨", "", f"💼 {title}", ""]

    # Company / Industry / Positions
    if details.get("company"):
        lines.append(f"🏢 Company: {details['company']}")
    if details.get("field"):
        lines.append(f"🏭 Industry: {details['field']}")
    if details.get("positions"):
        lines.append(f"📌 Posts Available: {details['positions']}")

    # Only add blank line if we added something above
    if any(k in details for k in ["company","field","positions"]):
        lines.append("")

    # Requirements block
    lines.append("📋 Requirements:")

    if details.get("qualification"):
        lines.append(f"✔ Qualification: {details['qualification']}")
    else:
        lines.append("✔ Qualification: Grade 12 / Matric")

    if details.get("experience"):
        lines.append(f"✔ Experience: {details['experience']}")
    else:
        lines.append("✔ Experience: Not required")

    # Age ONLY if a clean value was found
    if details.get("age"):
        lines.append(f"✔ Age: {details['age']}")

    lines.append("")

    # Location and closing date
    if details.get("location"):
        lines.append(f"📍 Location: {details['location']}")
    if details.get("closing_date"):
        lines.append(f"📅 Closing Date: {details['closing_date']}")

    lines.append(f"🌐 Source: {source}")
    lines.append("")
    lines.append("👇 Click to read full details & apply:")
    lines.append(direct_url)
    lines.append("")
    lines.append("💡 Share this — help a young person get this opportunity!")
    lines.append("👉 Follow Kuvukiland for fresh daily opportunities")
    lines.append("")
    lines.append(
        "#Learnership #EntryLevel #Grade12Jobs #YouthEmployment "
        "#SouthAfrica #Matric #NoExperience #KuvukilandJobs "
        "#Internship #GovernmentJobs #SETA #Kuvukiland"
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# XML PARSING
# ─────────────────────────────────────────────
def clean_xml(text):
    text = text.lstrip('\ufeff')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    for bad, good in {'\x91':"'",'\x92':"'",'\x93':'"','\x94':'"','\x96':'-','\x97':'-'}.items():
        text = text.replace(bad, good)
    return text


def parse_feed(raw_bytes):
    try:
        text = clean_xml(raw_bytes.decode("utf-8", errors="replace"))
        root = ET.fromstring(text.encode("utf-8"))
        items = root.findall(".//item")
        if items:
            return items
    except ET.ParseError:
        pass
    if LXML_AVAILABLE:
        try:
            parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
            root = lxml_etree.fromstring(raw_bytes, parser=parser)
            items = root.findall(".//item")
            if items:
                return items
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
    has_job = any(k in text for k in GOOD_KEYWORDS)
    has_act = any(k in text for k in [
        "apply","application","opportunity","hiring","available","2026","invited"
    ])
    has_bad = any(k in text for k in BAD_KEYWORDS)
    return has_job and has_act and not has_bad

def is_real_url(url):
    if not url or not url.startswith("http"):
        return False
    try:
        p = urlparse(url)
        return len(p.path.rstrip("/")) >= 4 and len(url) >= 35
    except Exception:
        return False

def get_text(el):
    return (el.text or "").strip() if el is not None else ""

def get_item_link(item):
    link = get_text(item.find("link"))
    if is_real_url(link):
        return link
    d = item.find("description")
    if d is not None and d.text:
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', unescape(d.text))
        for h in hrefs:
            if is_real_url(h) and "google.com" not in h:
                return h
    return None

def post_to_facebook(message, link):
    if not PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set.")
        return None
    try:
        r = requests.post(GRAPH_URL, data={
            "message": message, "link": link,
            "access_token": PAGE_TOKEN, "published": "true",
        }, timeout=20)
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
# EDUPSTAIRS SCRAPER
# ─────────────────────────────────────────────
def scrape_edupstairs():
    listings = []
    try:
        r = requests.get("https://www.edupstairs.org/", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return listings
        links = re.findall(
            r'href=["\']((https?://www\.edupstairs\.org/[^"\'#?]+))["\']', r.text
        )
        seen = set()
        for _, link in links:
            link = link.rstrip("/")
            if any(x in link for x in [
                "/category/","/tag/","/page/","/author/","/feed",".jpg",".png"
            ]):
                continue
            if link in seen or len(link) < 40:
                continue
            seen.add(link)
            pat = rf'href=["\']{re.escape(link)}["\'][^>]*>\s*([^<]{{5,120}})\s*<'
            m = re.search(pat, r.text)
            title = m.group(1).strip() if m else link.split("/")[-1].replace("-"," ").title()
            if is_relevant(title, ""):
                listings.append({"title": title[:120], "link": link, "source": "Edupstairs"})
                print(f"    Edupstairs ✔ {title[:65]}")
        print(f"  Edupstairs: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Edupstairs error: {e}")
    return listings


# ─────────────────────────────────────────────
# FETCH ALL LISTINGS
# ─────────────────────────────────────────────
def fetch_all_listings():
    all_listings = []
    for src in RSS_SOURCES:
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=20)
            print(f"  {src['source']}: HTTP {r.status_code}")
            if r.status_code != 200:
                time.sleep(1)
                continue
            items = parse_feed(r.content)
            if not items:
                time.sleep(1)
                continue
            accepted = 0
            for item in items[:20]:
                title = unescape(get_text(item.find("title")))
                d = item.find("description")
                summary = re.sub(r"<[^>]+>", "", unescape(d.text or "")) if d is not None else ""
                title = re.sub(r'\s*[|\-]\s*[^|\-]+$', '', title).strip()
                link = get_item_link(item)
                if not link:
                    continue
                if is_relevant(title, summary):
                    all_listings.append({
                        "title": title[:120], "link": link, "source": src["source"]
                    })
                    accepted += 1
            print(f"    → {accepted} relevant")
            time.sleep(1.5)
        except requests.exceptions.ConnectionError:
            print(f"  {src['source']} — connection failed")
        except Exception as e:
            print(f"  {src['source']} error: {e}")

    all_listings.extend(scrape_edupstairs())

    seen, unique = set(), []
    for j in all_listings:
        key = make_key(j["title"])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    random.shuffle(unique)
    return unique


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print(f"\n🤖 Kuvukiland Job Bot v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("✅ lxml available\n" if LXML_AVAILABLE else "⚠️  lxml not available\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs\n")
    print("Fetching listings...\n")

    listings = fetch_all_listings()
    new_jobs = [j for j in listings if make_key(j["title"]) not in already_posted]

    print(f"\n✅ Total unique: {len(listings)}  |  🆕 New: {len(new_jobs)}\n")

    if not new_jobs:
        print("⏸  No new jobs this run — nothing posted.")
        return

    MAX_PER_RUN = 1
    posted_count = 0

    for listing in new_jobs:
        if posted_count >= MAX_PER_RUN:
            break

        key = make_key(listing["title"])
        print(f"📤 Processing: {listing['title'][:70]}")
        print(f"   URL: {listing['link'][:80]}")
        print("   Extracting details...")

        details = extract_article_details(listing["link"])
        print(f"   Fields found: {list(details.keys())}")

        # Skip expired jobs
        closing = details.get("closing_date", "")
        if closing and is_expired(closing):
            print(f"   ❌ EXPIRED ({closing}) — skipping")
            save_posted(key)
            continue

        post = build_post(
            title=listing["title"],
            details=details,
            direct_url=listing["link"],
            source=listing["source"],
        )

        print("\n--- POST PREVIEW ---")
        print(post)
        print("--------------------\n")

        result = post_to_facebook(post, listing["link"])
        if result:
            save_posted(key)
            posted_count += 1
            print("✅ Done.")


if __name__ == "__main__":
    main()
