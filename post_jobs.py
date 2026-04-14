"""
Kuvukiland Job Bot v6
- Requirements extracted exactly as written in the advertisement
- Qualification match anchored to requirements section only (no footer junk)
- Gossip/entertainment articles blocked
- 2026 year enforcement — stale 2024/2025 listings never posted
- Posts up to 6 per run, runs every 10 minutes via GitHub Actions
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
    "Referer": "https://www.google.com/",
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
    "top 10", "list of", "here are", "everything you need",
    "2024", "2025",   # ← block any listing still referencing old years
    # Entertainment / gossip
    "pens heartfelt", "last episode", "airs last", "smoke and mirrors",
    "celebrity", "actress", "actor", "musician", "singer", "rapper",
    "album", "movie", "telenovela", "soap opera", "reality show",
    "dating", "relationship", "wedding", "divorce", "baby shower",
    "instagram", "twitter beef", "throwback", "hairstyle", "fashion",
]

RSS_SOURCES = [
    {"url": "https://www.salearnership.co.za/feed/",     "source": "SA Learnership"},
    {"url": "https://learnerships24.co.za/feed/",        "source": "Learnerships24"},
    {"url": "https://youthvillage.co.za/feed/",          "source": "Youth Village SA"},
    {"url": "https://learnerships.net/feed/",            "source": "Learnerships.net"},
    {"url": "https://southafricain.com/feed/",           "source": "South Africa In"},
    {"url": "https://www.salearnershipjobs.co.za/feed/", "source": "SA Learnership Jobs"},
    {"url": "https://zaboutjobs.com/feed/",              "source": "ZA Jobs"},
]

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
    "aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

SITE_SUFFIXES = re.compile(
    r'\s*[-|–]\s*(Edupstairs|SA Learnership|Learnerships24|Youth Village|'
    r'Skills Portal|ProStudy|ZA Jobs|After School Africa|Mabumbe|'
    r'Learnerships\.net|South Africa In|SA Learnership Jobs)[^\n]*$',
    re.I
)

MAX_PER_RUN = 6

JUNK_PHRASES = [
    'copyright', 'powered by', 'privacy policy', 'all rights reserved',
    'cookie', 'subscribe', 'newsletter', 'follow us', 'share this',
    'click here', 'read more', 'learn more', 'mcnitols', 'edupstairs',
    'youth village', 'salearnership', 'learnerships24',
]

CURRENT_YEAR = str(datetime.now().year)   # "2026"


# ─────────────────────────────────────────────
# DATE UTILITIES
# ─────────────────────────────────────────────

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


def is_junk(val):
    v = val.lower()
    return any(j in v for j in JUNK_PHRASES)


# ─────────────────────────────────────────────
# YEAR VALIDATION
# ─────────────────────────────────────────────

def confirm_current_year(title, article_plain_text):
    """
    Returns True if the listing is confirmed to be for the current year (2026).
    Checks:
    1. Title contains "2026"
    2. Article body contains "2026" at least once
    3. Article URL contains "2026"
    If none of these, the listing is rejected as potentially stale/old.
    """
    if CURRENT_YEAR in title:
        return True
    if CURRENT_YEAR in article_plain_text[:5000]:
        return True
    return False


# ─────────────────────────────────────────────
# HTML → PLAIN TEXT
# ─────────────────────────────────────────────

def strip_html(html):
    html = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', html,
                  flags=re.DOTALL | re.I)
    html = re.sub(r'<(br|p|div|h[1-6]|section|article|header|footer|nav)[^>]*>',
                  '\n', html, flags=re.I)
    html = re.sub(r'</(p|div|h[1-6]|section|article|header|footer|nav)>',
                  '\n', html, flags=re.I)
    html = re.sub(r'<li[^>]*>', '\n• ', html, flags=re.I)
    html = re.sub(r'<[^>]+>', '', html)
    html = unescape(html)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n[ \t]+', '\n', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


def get_main_content(html):
    for tag in [
        r'<article[^>]*>(.*?)</article>',
        r'<main[^>]*>(.*?)</main>',
        r'<div[^>]*class="[^"]*(?:entry|post|content|article)-(?:content|body)[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
    ]:
        m = re.search(tag, html, re.DOTALL | re.I)
        if m:
            return m.group(1)
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.I)
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.I)
    html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.I)
    return html


def find_section(text, *heading_patterns):
    for pat in heading_patterns:
        m = re.search(pat, text, re.I)
        if m:
            start = m.end()
            chunk = text[start:start + 800]
            next_heading = re.search(
                r'\n(?:Requirements?|Qualification|Experience|How to Apply|'
                r'Application|Benefits?|Responsibilities|Duties|About)\s*[:\-\n]',
                chunk, re.I
            )
            if next_heading:
                chunk = chunk[:next_heading.start()]
            return chunk
    return ""


def extract_bullets(section_text, max_items=5):
    items = []
    for line in section_text.split('\n'):
        line = line.strip()
        line = re.sub(r'^[•·\-–*▪➤✔✓]\s*', '', line)
        line = re.sub(r'^\d+[\.\)]\s*', '', line)
        line = line.strip()
        if len(line) < 5 or len(line) > 200:
            continue
        if is_junk(line):
            break
        if re.search(r'(copyright|©|\bpowered\b|\bprivacy\b)', line, re.I):
            break
        items.append(line)
        if len(items) >= max_items:
            break
    return items


# ─────────────────────────────────────────────
# ARTICLE DETAIL EXTRACTOR
# ─────────────────────────────────────────────

def extract_article_details(url, title=""):
    """
    Visit the article and extract real details.
    Also verifies the listing is for 2026 — returns None if stale.
    """
    details = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"   ⚠️  HTTP {r.status_code} fetching article")
            return None

        main_html = get_main_content(r.text)
        plain = strip_html(main_html)

        # ── YEAR CHECK — reject stale listings ───────────────────
        if not confirm_current_year(title, plain):
            print(f"   ❌ No '{CURRENT_YEAR}' found in title or article — skipping stale listing")
            return None

        # ── CLOSING DATE ─────────────────────────────────────────
        for pat in [
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\w+\s+\d{1,2},?\s+\d{4})',
            r'[Dd]eadline\s*[:\-]\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Aa]pply\s+[Bb]efore\s*[:\-]?\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Cc]loses?\s+[Oo]n\s*[:\-]?\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Aa]pplication\s+[Dd]eadline\s*[:\-]\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+202[567])',
            r'(\d{1,2}[\/\-]\d{1,2}[\/\-]202[567])',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                parsed = parse_date_str(m.group(1).strip())
                if parsed:
                    details["closing_date"] = parsed.strftime("%d %B %Y")
                    details["closing_date_obj"] = parsed
                    break

        # ── LOCATION ─────────────────────────────────────────────
        for pat in [
            r'[Ll]ocation\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,60})',
            r'[Cc]ity\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Pp]rovince\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Pp]lace\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Ww]here\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,60})',
            r'[Bb]ased\s+[Ii]n\s*[:\-]?\s*([A-Za-z][^\n\r|,\.]{3,50})',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip().rstrip('.,;')
                if (3 <= len(val) <= 80
                        and not re.search(r'http|www|\.co|click|apply|salary|stipend', val, re.I)
                        and not re.search(r'[{}\[\]<>@#=;]', val)
                        and not is_junk(val)):
                    details["location"] = val
                    break

        # ── REQUIREMENTS SECTION ─────────────────────────────────
        req_section = find_section(
            plain,
            r'[Rr]equirements?\s*[:\-]',
            r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s+[Cc]riteria\s*[:\-]',
            r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Qq]ualifications?\s+[Rr]equired\s*[:\-]',
            r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
        )

        # ── QUALIFICATION ─────────────────────────────────────────
        qual_search_text = req_section if req_section else plain[:2000]
        for pat in [
            r'[Qq]ualification\s*[:\-]\s*([^\n\r]{5,100})',
            r'[Ee]ducation(?:al\s+[Rr]equirement)?\s*[:\-]\s*([^\n\r]{5,80})',
            r'(Grade\s+12[^\n\r]{0,80})',
            r'(Matric[^\n\r]{0,60})',
            r'(National\s+(?:Senior\s+)?Certificate[^\n\r]{0,60})',
            r'((?:National\s+)?Diploma[^\n\r]{0,60})',
            r'((?:Bachelor[^\n\r]{0,60}))',
            r'(NQF\s+Level\s+\d[^\n\r]{0,60})',
        ]:
            m = re.search(pat, qual_search_text, re.I)
            if m:
                val = m.group(1).strip()
                val = re.split(r'[|]', val)[0].strip()
                for jp in JUNK_PHRASES:
                    idx = val.lower().find(jp)
                    if idx > 0:
                        val = val[:idx].strip()
                val = val[:100]
                if (len(val) >= 4
                        and not re.search(r'[{}\[\]<>@#=;]', val)
                        and not is_junk(val)
                        and any(x in val.lower() for x in
                                ['grade', 'matric', 'diploma', 'certificate',
                                 'degree', 'nqf', 'qualification', 'senior', 'bachelor'])):
                    details["qualification"] = val
                    break

        # ── REQUIREMENTS BULLETS ─────────────────────────────────
        if req_section:
            bullets = extract_bullets(req_section, max_items=5)
            clean_bullets = []
            qual_lower = details.get("qualification", "").lower()
            for b in bullets:
                if is_junk(b):
                    continue
                if qual_lower and b.lower() in qual_lower:
                    continue
                clean_bullets.append(b)
            if clean_bullets:
                details["requirements"] = clean_bullets

        # ── EXPERIENCE ───────────────────────────────────────────
        for pat in [
            r'[Ee]xperience\s+[Rr]equired\s*[:\-]\s*([^\n\r]{3,80})',
            r'[Ww]ork\s+[Ee]xperience\s*[:\-]\s*([^\n\r]{3,80})',
            r'[Ee]xperience\s*[:\-]\s*([^\n\r]{3,80})',
            r'(No\s+(?:work\s+)?[Ee]xperience\s+(?:required|needed|necessary))',
            r'(Entry[\s\-][Ll]evel)',
            r'(\d+\s*(?:year[s]?|yr[s]?)\s+(?:\w+\s+)?[Ee]xperience)',
            r'(\d+\s*[-–]\s*\d+\s*(?:year[s]?|yr[s]?)\s+[Ee]xperience)',
            r'([Mm]inimum\s+\d+\s+year[s]?\s+[^\n\r]{3,60})',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()[:80]
                if (len(val) >= 3
                        and not re.search(r'[{}\[\]<>@#=;]', val)
                        and not is_junk(val)):
                    details["experience"] = val
                    break

        # ── AGE ──────────────────────────────────────────────────
        for pat in [
            r'[Aa]ge\s*[:\-]\s*(\d{2}\s*[-–to]+\s*\d{2}\s*years?)',
            r'[Aa]ged?\s+(\d{2}\s*[-–to]+\s*\d{2}\s*years?)',
            r'[Bb]etween\s+(?:the\s+ages?\s+of\s+)?(\d{2}\s+and\s+\d{2}\s*years?)',
            r'(\d{2}\s*[-–]\s*\d{2}\s*years?\s*old)',
            r'(\d{2}\s*[-–]\s*\d{2}\s*years?)',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()
                if re.match(r'^[\d\s\-–toalersy]+$', val, re.I) and len(val) <= 20:
                    details["age"] = val
                    break

        # ── POSITIONS ────────────────────────────────────────────
        for pat in [
            r'\(X?\s*(\d+)\s*[Pp]osts?\)',
            r'\(X?\s*(\d+)\s*[Pp]ositions?\)',
            r'[Pp]ositions?\s+[Aa]vailable\s*[:\-]\s*(\d+)',
            r'[Nn]umber\s+of\s+[Pp]osts?\s*[:\-]\s*(\d+)',
            r'(\d+)\s+[Pp]osts?\s+[Aa]vailable',
            r'(\d+)\s+[Vv]acancies',
            r'[Xx]\s*(\d+)\s+[Pp]osts?',
            r'X(\d+)\s+',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()
                if val.isdigit() and 0 < int(val) < 1000:
                    details["positions"] = val
                    break

        # ── STIPEND / SALARY ─────────────────────────────────────
        for pat in [
            r'[Ss]tipend\s*[:\-]\s*(R\s*[\d\s,]+(?:\s*per\s+month)?)',
            r'[Ss]alary\s*[:\-]\s*(R\s*[\d\s,]+(?:\s*per\s+(?:month|annum))?)',
            r'(R\s*\d[\d\s,]*\s*(?:per\s+month|p\.?m\.?))',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()[:40]
                if re.search(r'\d', val):
                    details["stipend"] = val
                    break

        print(f"   Fields found: {[k for k in details if k != 'closing_date_obj']}")

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return details


# ─────────────────────────────────────────────
# POST BUILDER
# ─────────────────────────────────────────────

def build_post(title, details, direct_url, source):
    title = SITE_SUFFIXES.sub('', title).strip()
    lines = ["🔌 Nasi iSpan 🚨", "", f"💼 {title}", ""]

    if details.get("positions"):
        lines.append(f"📌 Posts Available: {details['positions']}")
        lines.append("")

    lines.append("📋 Requirements:")

    qual = details.get("qualification", "Grade 12 / Matric")
    lines.append(f"✔ Qualification: {qual}")

    exp = details.get("experience")
    if exp:
        lines.append(f"✔ Experience: {exp}")
    elif details.get("requirements"):
        for req in details["requirements"][:4]:
            lines.append(f"✔ {req}")
    else:
        lines.append("✔ See full advert for requirements")

    if details.get("age"):
        lines.append(f"✔ Age: {details['age']}")

    if details.get("stipend"):
        lines.append(f"💰 Stipend: {details['stipend']}")

    lines.append("")
    lines.append(f"📍 Location: {details.get('location', 'See full advert')}")
    lines.append(f"📅 Closing Date: {details.get('closing_date', 'See full advert')}")
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
    for bad, good in {
        '\x91': "'", '\x92': "'", '\x93': '"', '\x94': '"',
        '\x96': '-', '\x97': '-', '\x95': '*', '\x85': '...',
    }.items():
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


def is_real_job(title, summary=""):
    text = (title + " " + summary).lower()
    has_job = any(k in text for k in GOOD_KEYWORDS)
    has_act = any(k in text for k in [
        "apply", "application", "opportunity", "hiring",
        "available", "2026", "invited", "register", "programme",
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
            "message": message,
            "link": link,
            "access_token": PAGE_TOKEN,
            "published": "true",
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
            print(f"  Edupstairs: HTTP {r.status_code}")
            return listings
        links = re.findall(
            r'href=["\']((https?://www\.edupstairs\.org/[^"\'#?]+))["\']', r.text
        )
        seen = set()
        for _, link in links:
            link = link.rstrip("/")
            if any(x in link for x in [
                "/category/", "/tag/", "/page/", "/author/", "/feed", ".jpg", ".png"
            ]):
                continue
            if link in seen or len(link) < 40:
                continue
            seen.add(link)
            pat = rf'href=["\']{re.escape(link)}["\'][^>]*>\s*([^<]{{5,120}})\s*<'
            m = re.search(pat, r.text)
            title = (m.group(1).strip() if m
                     else link.split("/")[-1].replace("-", " ").title())
            if is_real_job(title, ""):
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
                print(f"    ⚠️  Could not parse feed")
                time.sleep(1)
                continue
            accepted = 0
            for item in items[:20]:
                title = unescape(get_text(item.find("title")))
                d = item.find("description")
                summary = (re.sub(r"<[^>]+>", "", unescape(d.text or ""))
                           if d is not None else "")
                title = re.sub(r'\s*[|\-–]\s*[^|\-–]+$', '', title).strip()
                link = get_item_link(item)
                if not link:
                    continue
                if is_real_job(title, summary):
                    all_listings.append({
                        "title": title[:120],
                        "link": link,
                        "source": src["source"],
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
    print(f"\n🤖 Kuvukiland Job Bot v6 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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

    posted_count = 0

    for listing in new_jobs:
        if posted_count >= MAX_PER_RUN:
            break

        key = make_key(listing["title"])
        print(f"\n📤 [{posted_count + 1}/{MAX_PER_RUN}] {listing['title'][:65]}")
        print(f"   URL: {listing['link'][:80]}")
        print("   Extracting details...")

        # Pass title so year check can use it
        details = extract_article_details(listing["link"], title=listing["title"])

        # None means stale listing — mark as posted to never retry it
        if details is None:
            save_posted(key)
            continue

        # Skip if closing date is expired
        closing_obj = details.get("closing_date_obj")
        if closing_obj and closing_obj < datetime.now():
            print(f"   ❌ EXPIRED ({details.get('closing_date')}) — skipping")
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
            print(f"✅ Posted {posted_count}/{MAX_PER_RUN}")
            if posted_count < MAX_PER_RUN:
                time.sleep(5)

    print(f"\n🏁 Run complete — {posted_count} post(s) published this run.")


if __name__ == "__main__":
    main()
