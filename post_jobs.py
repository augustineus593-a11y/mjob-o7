"""
Kara Job Updates — Job Bot v13
Fixes from v12:

FIX 1 — Requirements displayed as raw clean text (not parsed bullets)
  The bullet-parsing approach kept producing garbage (field labels, section
  headers, prose sentences). Now extract_requirements_block() grabs the
  requirements section as a raw text block, does minimal cleaning (strip
  obvious junk lines, deduplicate, cap at 10 lines), and the post displays
  it verbatim under "Minimum Requirements:" — exactly as the advert has it.
  extract_bullets() is removed entirely.

FIX 2 — Celebrity/article filter hardened
  is_real_job() now requires a GOOD_KEYWORD to appear in the TITLE itself
  (not just the RSS summary). Summary is only used to confirm action words.
  This stops articles like '"I Am Incredibly Grateful..." Karabelo Ramabodu'
  from slipping through because "youth" appeared somewhere in the summary.
  BAD_KEYWORDS are checked against title-only first; one bad keyword in the
  title kills the listing immediately regardless of summary.
"""

import os, re, time, requests, random
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

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
    # Qualification level
    "honours", "masters", "phd", "postgraduate",
    "5 years experience", "10 years", "executive", "head of", "director",
    # Scam / warning
    "scam", "fake", "fraud", "warning", "not offering", "beware",
    "hoax", "misleading", "suspended", "arrested",
    # Crime / politics / news
    "court", "murder", "killed", "died", "protest", "strike",
    "looting", "crime", "convicted", "tender", "parliament",
    # Listicles / guides
    "survey", "guide to", "what is", "celebrating",
    "top 10", "list of", "here are", "everything you need",
    # Entertainment — people
    "pens heartfelt", "last episode", "airs last", "smoke and mirrors",
    "celebrity", "actress", "actor", "musician", "singer", "rapper",
    # Entertainment — content types
    "album", "movie", "telenovela", "soap opera", "reality show",
    "dating", "relationship", "wedding", "divorce", "baby shower",
    # Entertainment — social / lifestyle
    "instagram", "twitter beef", "throwback", "hairstyle", "fashion",
    # ── NEW v12 — TV / show specific ─────────────────────────────
    "presenter", "presenters", "lineup", "line-up",
    "top billing", "billing", "star-studded", "studded",
    "episode", "season", "episodes", "seasons",
    "contestant", "contestants", "host", "hosts",
    "audition", "casting", "cast",
    "nominated", "nomination", "award", "awards",
    "highlight", "highlights", "preview", "teaser",
    "recap", "review", "reviews",
    "watch ", "stream", "streaming",
    "airs ", "premiere", "premieres", "finale",
    "reality tv", "talk show", "game show",
]

RSS_SOURCES = [
    {"url": "https://www.salearnership.co.za/feed/",                          "source": "SA Learnership"},
    {"url": "https://learnerships24.co.za/feed/",                             "source": "Learnerships24"},
    {"url": "https://youthvillage.co.za/feed/",                               "source": "Youth Village SA"},
    {"url": "https://learnerships.net/feed/",                                  "source": "Learnerships.net"},
    {"url": "https://southafricain.com/feed/",                                 "source": "South Africa In"},
    {"url": "https://www.salearnershipjobs.co.za/feed/",                       "source": "SA Learnership Jobs"},
    {"url": "https://zaboutjobs.com/feed/",                                    "source": "ZA Jobs"},
    {"url": "https://www.kazi-jobs.co.za/feed/",                               "source": "Kazi Jobs"},
    {"url": "https://www.kazi-jobs.co.za/category/job-opportunies/feed/",      "source": "Kazi Jobs"},
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
    r'Learnerships\.net|South Africa In|SA Learnership Jobs|Kazi Jobs)[^\n]*$',
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
# URL UTILITIES
# ─────────────────────────────────────────────

def strip_utm(url):
    """Remove UTM tracking parameters from a URL, return clean URL."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if not k.startswith("utm_")}
        new_query = urlencode(clean_qs, doseq=True)
        clean = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, ""
        ))
        return clean.rstrip("/")
    except Exception:
        return re.sub(r'\?.*$', '', url).rstrip('/')


# ─────────────────────────────────────────────
# TITLE CASING — preserve ALL-CAPS abbreviations
# ─────────────────────────────────────────────

_LOWER_WORDS = {"a", "an", "the", "and", "but", "or", "for", "nor",
                "at", "by", "in", "of", "on", "to", "up", "as"}

def smart_title(text):
    words = text.split()
    result = []
    for i, word in enumerate(words):
        leading  = re.match(r'^([^A-Za-z0-9]*)', word).group(1)
        trailing = re.search(r'([^A-Za-z0-9]*)$', word).group(1)
        core     = word[len(leading): len(word) - len(trailing) if trailing else len(word)]

        if not core:
            result.append(word)
            continue

        alpha_chars = re.sub(r'[^A-Za-z]', '', core)

        if len(alpha_chars) >= 2 and alpha_chars == alpha_chars.upper():
            result.append(word)
            continue

        if i > 0 and core.lower() in _LOWER_WORDS:
            result.append(leading + core.lower() + trailing)
            continue

        result.append(leading + core.capitalize() + trailing)

    return ' '.join(result)


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
# YEAR VALIDATION  (v12: pub_year fallback)
# ─────────────────────────────────────────────

def confirm_current_year(title, article_plain_text, pub_year=None):
    """
    Return True if the listing appears to be current-year.
    Checks (in order):
      1. CURRENT_YEAR in title
      2. CURRENT_YEAR in first 5000 chars of article
      3. pub_year (from RSS <pubDate>) matches CURRENT_YEAR  ← NEW v12
    """
    if CURRENT_YEAR in title:
        return True
    if CURRENT_YEAR in article_plain_text[:5000]:
        return True
    if pub_year and str(pub_year) == CURRENT_YEAR:
        print(f"   ℹ️  Year confirmed via RSS pubDate ({pub_year})")
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


# ─────────────────────────────────────────────
# REQUIREMENTS BLOCK — raw clean text (v13)
# ─────────────────────────────────────────────

# Lines that are pure section-navigation noise (not actual requirements)
_REQ_JUNK_LINE = re.compile(
    r'^(view (latest|all|more)|apply (now|here|online)|contact us|'
    r'for more (info|information|details)|click (here|below)|'
    r'share this|follow us|subscribe|read more|learn more|'
    r'what (the|this)|how to apply|about (us|the company)|overview|'
    r'introduction|note:|nb:|please note)',
    re.I
)

def extract_requirements_block(plain_text):
    """
    v13: Instead of trying to parse bullets, extract the requirements section
    as a clean raw text block — exactly as the advert presents it.

    Steps:
    1. Find the requirements heading in the plain text
    2. Grab the chunk until the next section heading
    3. Split into lines, drop obvious junk/navigation lines and blank lines
    4. Deduplicate adjacent identical lines
    5. Return max 10 clean lines joined with newlines
    """
    # Try to find the requirements section
    section = find_section(
        plain_text,
        r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
        r'[Rr]equirements?\s*[:\-]',
        r'[Ee]ligibility\s+[Cc]riteria\s*[:\-]',
        r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
        r'[Qq]ualifications?\s+[Rr]equired\s*[:\-]',
        r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
    )
    if not section:
        return ""

    clean_lines = []
    seen = set()

    for raw_line in section.split('\n'):
        # Basic cleanup
        line = raw_line.strip()
        line = re.sub(r'^[•·▪➤✔✓\-–*]\s*', '', line).strip()   # strip bullet chars
        line = re.sub(r'^\d+[\.\)]\s*', '', line).strip()         # strip numbering

        # Skip empty or very short lines
        if len(line) < 4:
            continue

        # Skip lines that are pure site junk or navigation
        if is_junk(line):
            break   # junk usually means we've left the content area

        if _REQ_JUNK_LINE.match(line):
            continue

        # Stop if we hit a copyright/footer signal
        if re.search(r'(copyright|©|\bpowered\b|\bprivacy\b)', line, re.I):
            break

        # Skip pure section-label lines with nothing after the colon
        # e.g. "Educational Requirements" alone, "Experience Requirements" alone
        if re.match(r'^(Educational|Experience|Academic|Other|Additional|'
                    r'General|Basic|Further|Key)\s+(Requirements?|Qualifications?'
                    r'|Criteria|Skills?)\s*:?\s*$', line, re.I):
            continue

        # Deduplicate
        line_lower = line.lower()
        if line_lower in seen:
            continue
        seen.add(line_lower)

        clean_lines.append(line)

        if len(clean_lines) >= 10:
            break

    return "\n".join(clean_lines)


# ─────────────────────────────────────────────
# QUALIFICATION EXTRACTION
# ─────────────────────────────────────────────

def extract_qualification(text):
    QUAL_NOUNS = [
        'grade 12', 'grade12', 'matric', 'national senior certificate',
        'national certificate', 'national diploma', 'higher certificate',
        'advanced diploma', 'bachelor', 'b.tech', 'btech', 'b tech',
        'degree', 'diploma', 'nqf level', 'nqf', 'abet', 'fet',
        'trade test', 'artisan', 'certificate',
    ]

    labelled = [
        r'[Qq]ualification(?:s)?\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Ee]ducation(?:al\s+[Rr]equirement)?\s*[:\-]\s*([^\n\r]{10,100})',
        r'[Mm]inimum\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Rr]equired\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Aa]cademic\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
    ]
    for pat in labelled:
        m = re.search(pat, text, re.I)
        if m:
            val = _clean_qual(m.group(1))
            if val and _qual_is_valid(val, QUAL_NOUNS):
                return val

    standalone = [
        r'(Grade\s+12[^.\n\r]{0,100})',
        r'(Matric(?:ulation)?(?:\s+Certificate)?[^.\n\r]{0,80})',
        r'(National\s+Senior\s+Certificate[^.\n\r]{0,80})',
        r'((?:National\s+)?Diploma\s+in\s+[^.\n\r]{5,100})',
        r'((?:National\s+)?Diploma\s+(?:or|and)\s+[^.\n\r]{5,80})',
        r'(Higher\s+Certificate\s+in\s+[^.\n\r]{5,80})',
        r'(Advanced\s+Diploma\s+in\s+[^.\n\r]{5,80})',
        r'(Bachelor(?:\'s)?\s+(?:Degree\s+)?in\s+[^.\n\r]{5,80})',
        r'(B\.?Tech\s+in\s+[^.\n\r]{5,80})',
        r'(NQF\s+Level\s+\d[^.\n\r]{0,60})',
        r'(Trade\s+Test[^.\n\r]{0,60})',
        r'[•·\-–*]\s+((?:Diploma|Degree|Certificate|Matric|Grade\s+12)[^.\n\r]{5,100})',
    ]
    for pat in standalone:
        m = re.search(pat, text, re.I)
        if m:
            val = _clean_qual(m.group(1))
            if val and _qual_is_valid(val, QUAL_NOUNS) and len(val) >= 12:
                return val

    return None


def _clean_qual(val):
    val = val.strip()
    val = re.split(r'[|;]', val)[0].strip()
    val = val.rstrip('.,;:-()')
    for jp in JUNK_PHRASES:
        idx = val.lower().find(jp)
        if idx > 0:
            val = val[:idx].strip()
    val = val[:120]
    val = re.sub(r'[{}\[\]<>@#=]', '', val).strip()
    return val


def _qual_is_valid(val, qual_nouns):
    if not val or len(val) < 4:
        return False
    if is_junk(val):
        return False
    vl = val.lower()
    return any(n in vl for n in qual_nouns)


# ─────────────────────────────────────────────
# ARTICLE DETAIL EXTRACTOR  (v12: pub_year kwarg)
# ─────────────────────────────────────────────

def extract_article_details(url, title="", pub_year=None):
    details = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"   ⚠️  HTTP {r.status_code} fetching article")
            return None

        main_html = get_main_content(r.text)
        plain = strip_html(main_html)

        # v12: pass pub_year into year check
        if not confirm_current_year(title, plain, pub_year=pub_year):
            print(f"   ❌ No '{CURRENT_YEAR}' found in title, article, or pubDate — skipping stale listing")
            return None

        # ── Closing date ──────────────────────────────────────────
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

        # ── Location ──────────────────────────────────────────────
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

        # ── Requirements ─────────────────────────────────────────
        # Try to extract qualification from a found section first, fallback to full text
        req_section = find_section(
            plain,
            r'[Rr]equirements?\s*[:\-]',
            r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s+[Cc]riteria\s*[:\-]',
            r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Qq]ualifications?\s+[Rr]equired\s*[:\-]',
            r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
        )

        qual = extract_qualification(req_section) if req_section else None
        if not qual:
            qual = extract_qualification(plain[:3000])
        if qual:
            details["qualification"] = qual

        # v13: Raw requirements block — displayed as-is in the post
        req_block = extract_requirements_block(plain)
        if req_block:
            details["requirements_block"] = req_block

        # ── Experience ───────────────────────────────────────────
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

        # ── Age ───────────────────────────────────────────────────
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

        # ── Positions ────────────────────────────────────────────
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

        # ── Stipend ──────────────────────────────────────────────
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

        # ── Opportunity type ─────────────────────────────────────
        title_lower = plain[:200].lower() + " " + details.get("qualification", "").lower()
        if "learnership" in title_lower:
            details["opp_type"] = "learnership"
        elif "internship" in title_lower:
            details["opp_type"] = "internship"
        elif "apprentice" in title_lower:
            details["opp_type"] = "apprenticeship"
        elif "bursary" in title_lower:
            details["opp_type"] = "bursary"
        else:
            details["opp_type"] = "opportunity"

        print(f"   Fields found: {[k for k in details if k != 'closing_date_obj']}")

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return details


# ─────────────────────────────────────────────
# COMPANY NAME EXTRACTION  (v12: sentence-opener blocklist)
# ─────────────────────────────────────────────

_NOISE_OPENERS = {
    "learnership", "internship", "apprenticeship", "bursary",
    "vacancy", "vacancies", "opportunity", "opportunities",
    "programme", "program", "graduate", "trainee", "yes",
    "general", "worker", "workers", "officer", "officers",
}

_JOB_NOISE_SUFFIX = {
    "general", "worker", "workers", "officer", "officers", "clerk",
    "assistant", "manager", "supervisor", "technician", "specialist",
    "practitioner", "analyst", "advisor", "consultant", "coordinator",
    "engineer", "supply", "chain", "wealth",
    "financial", "corporate", "investment", "senior", "junior",
    "artisan", "intern", "learner", "millwright", "boilermaker",
    "electrician", "plumber", "welder", "fitter",
}

# v12: Sentence-opener verbs / words that can NEVER start a company name
_SENTENCE_OPENERS = {
    "preparing", "check", "checking", "applications", "application",
    "looking", "how", "find", "finding", "get", "getting",
    "here", "this", "these", "now", "new", "top", "best",
    "why", "what", "where", "when", "all", "join", "joining",
    "learn", "learning", "meet", "meeting", "see", "register",
    "registering", "open", "opening", "read", "reading",
    "download", "view", "viewing", "about", "important",
    "introducing", "announcing", "attention", "alert",
    "exciting", "great", "big", "latest", "upcoming",
    "congratulations", "welcome", "calling", "wanted",
    "notice", "update", "reminder", "deadline",
}

_OPP_TRIGGER = re.compile(
    r'\b(Learnership|Internship|Apprenticeship|Bursary|Graduate|'
    r'Vacancy|Vacancies|Programme|Program|Opportunity|Opportunities|'
    r'Trainee|Artisan|YES)\b',
    re.I
)


def extract_company(title):
    """
    Return the company/organisation name from a job title, or '' if not found.
    v12: Also rejects titles where the first word is a sentence-opener verb/word.
    """
    m = _OPP_TRIGGER.search(title)
    if not m:
        return ""

    candidate = title[:m.start()].strip()
    if not candidate:
        return ""

    words = candidate.split()
    if not words:
        return ""

    # Reject if the very first word is a noise word OR a sentence opener
    first = words[0].lower()
    if first in _NOISE_OPENERS or first in _SENTENCE_OPENERS:
        return ""

    # Trim trailing job-description noise words and bare year numbers
    while words and (words[-1].lower() in _JOB_NOISE_SUFFIX
                     or re.match(r'^20\d{2}$', words[-1])):
        words.pop()

    if not words:
        return ""

    company = " ".join(words[:4])

    # Final sanity: must be at least 2 characters and not pure digits
    if len(company) < 2 or company.isdigit():
        return ""

    return company


# ─────────────────────────────────────────────
# POST BUILDER
# ─────────────────────────────────────────────

def build_post(title, details, direct_url, source):
    title = SITE_SUFFIXES.sub('', title).strip()
    title = smart_title(title)
    direct_url = strip_utm(direct_url)

    opp_type      = details.get("opp_type", "opportunity")
    qual          = details.get("qualification", "")
    exp           = details.get("experience", "")
    location      = details.get("location", "")
    closing       = details.get("closing_date", "")
    stipend       = details.get("stipend", "")
    age           = details.get("age", "")
    req_block     = details.get("requirements_block", "")
    positions     = details.get("positions", "")

    is_entry = False
    if qual or exp:
        ql = qual.lower()
        el = exp.lower()
        is_entry = (
            "grade 12" in ql or "matric" in ql
            or "entry" in el or "no experience" in el
        )

    company = extract_company(title)
    article = "an" if opp_type[0].lower() in "aeiou" else "a"

    if is_entry and company:
        opener = (
            f"🚨 {company} is offering {article} {opp_type} and all you need is "
            f"Grade 12 — no experience required! "
            f"Don't sleep on this one 🔥"
        )
    elif is_entry:
        opener = (
            f"🚨 I found {article} {opp_type} that only requires Grade 12, "
            f"no experience needed at all! This one is for you 🔥"
        )
    elif company:
        opener = (
            f"🚨 {company} is hiring! They have {article} {opp_type} open "
            f"right now — check if you qualify 👇"
        )
    else:
        opener = (
            f"🚨 There is {article} {opp_type} open right now and applications "
            f"are still running — check the requirements below 👇"
        )

    lines = [opener, "", f"📌 {title}", ""]

    # ── Minimum Requirements — displayed as raw block ─────────────
    lines.append("📋 Minimum Requirements:")
    lines.append("")
    if req_block:
        lines.append(req_block)
    else:
        lines.append("See full advert for requirements")
    lines.append("")

    # ── Stipend ───────────────────────────────────────────────────
    if stipend:
        lines.append(f"💰 Stipend / Salary: {stipend}")
        lines.append("")

    if positions:
        lines.append(f"🔢 Posts Available: {positions}")
        lines.append("")

    # ── Location & closing date ───────────────────────────────────
    if location:
        lines.append(f"📍 Location: {location}")
    else:
        lines.append("📍 Location: See advert")

    if closing:
        lines.append(f"📅 Closing Date: {closing}")
    else:
        lines.append("📅 Closing Date: See advert")

    lines.append("")
    lines.append("👇 Apply here:")
    lines.append(direct_url)
    lines.append("")
    lines.append("Share this with someone who needs it 🙏 Let's help each other!")
    lines.append("")
    lines.append(
        "#Learnership #EntryLevel #Grade12Jobs #YouthEmployment "
        "#SouthAfrica #Matric #NoExperience #KaraJobUpdates "
        "#Internship #GovernmentJobs #SETA #JobAlert"
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
    title_lower = title.lower()
    combined = title_lower + " " + summary.lower()

    # One bad keyword in the TITLE → reject immediately
    if any(k in title_lower for k in BAD_KEYWORDS):
        return False

    # Good keyword MUST appear in the TITLE — not just buried in the summary
    if not any(k in title_lower for k in GOOD_KEYWORDS):
        return False

    # Action word can be anywhere (title or summary)
    return any(k in combined for k in [
        "apply", "application", "opportunity", "hiring",
        "available", "2026", "invited", "register", "programme",
    ])


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


def get_item_pub_year(item):
    """Extract the publication year from an RSS item's <pubDate>. Returns int or None."""
    pub_date_el = item.find("pubDate")
    if pub_date_el is None:
        return None
    raw = get_text(pub_date_el)
    # RSS pubDate format: "Mon, 21 Apr 2026 10:00:00 +0000"
    m = re.search(r'\b(20\d{2})\b', raw)
    if m:
        return int(m.group(1))
    return None


def post_to_facebook(message):
    if not PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set.")
        return None
    try:
        r = requests.post(GRAPH_URL, data={
            "message": message,
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
                listings.append({
                    "title": title[:120],
                    "link": link,
                    "source": "Edupstairs",
                    "pub_year": datetime.now().year,  # Edupstairs has no RSS pubDate
                })
                print(f"    Edupstairs ✔ {title[:65]}")
        print(f"  Edupstairs: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Edupstairs error: {e}")
    return listings


# ─────────────────────────────────────────────
# KAZI JOBS HTML SCRAPER
# ─────────────────────────────────────────────

def scrape_kazijobs():
    listings = []
    url = "https://www.kazi-jobs.co.za/category/job-opportunies/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  Kazi Jobs HTML: HTTP {r.status_code}")
            return listings

        links = re.findall(
            r'href=["\']((https?://(?:www\.)?kazi-jobs\.co\.za/[^"\'#?]+))["\']',
            r.text
        )
        seen = set()
        for _, link in links:
            link = link.rstrip("/")
            if any(x in link for x in [
                "/category/", "/tag/", "/page/", "/author/", "/feed",
                ".jpg", ".png", "/about", "/contact", "/home",
            ]):
                continue
            if link in seen or len(link) < 38:
                continue
            seen.add(link)

            pat = rf'href=["\']{re.escape(link)}["\'][^>]*>\s*([^<]{{5,150}})\s*<'
            m = re.search(pat, r.text)
            title = (m.group(1).strip() if m
                     else link.split("/")[-1].replace("-", " ").title())
            title = re.sub(r'<[^>]+>', '', title).strip()

            if is_real_job(title, ""):
                listings.append({
                    "title": title[:120],
                    "link": link,
                    "source": "Kazi Jobs",
                    "pub_year": datetime.now().year,  # HTML scrape has no pubDate
                })
                print(f"    Kazi Jobs ✔ {title[:65]}")

        print(f"  Kazi Jobs HTML: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Kazi Jobs HTML error: {e}")
    return listings


# ─────────────────────────────────────────────
# FETCH ALL LISTINGS  (v12: pub_year passed through)
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
                    pub_year = get_item_pub_year(item)  # v12
                    all_listings.append({
                        "title": title[:120],
                        "link": link,
                        "source": src["source"],
                        "pub_year": pub_year,           # v12
                    })
                    accepted += 1
            print(f"    → {accepted} relevant")
            time.sleep(1.5)
        except requests.exceptions.ConnectionError:
            print(f"  {src['source']} — connection failed")
        except Exception as e:
            print(f"  {src['source']} error: {e}")

    all_listings.extend(scrape_edupstairs())
    all_listings.extend(scrape_kazijobs())

    seen_titles, seen_urls, unique = set(), set(), []
    for j in all_listings:
        tkey = make_key(j["title"])
        ukey = strip_utm(j["link"])
        if tkey in seen_titles or ukey in seen_urls:
            continue
        seen_titles.add(tkey)
        seen_urls.add(ukey)
        unique.append(j)
    random.shuffle(unique)
    return unique


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print(f"\n🤖 Kara Job Updates — Job Bot v12 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("✅ lxml available\n" if LXML_AVAILABLE else "⚠️  lxml not available\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs\n")
    print("Fetching listings...\n")

    listings = fetch_all_listings()
    new_jobs = [j for j in listings if make_key(j["title"]) not in already_posted]

    print(f"\n✅ Total unique: {len(listings)}  |  🆕 New: {len(new_jobs)}\n")

    posted_count = 0

    if not new_jobs:
        print("⏸  No new job listings this run — nothing to post.")
        print(f"\n🏁 Run complete — {posted_count} post(s) published this run.")
        return

    for listing in new_jobs:
        if posted_count >= MAX_PER_RUN:
            break

        key = make_key(listing["title"])
        print(f"\n📤 [{posted_count + 1}/{MAX_PER_RUN}] {listing['title'][:65]}")
        print(f"   URL: {listing['link'][:80]}")
        print("   Extracting details...")

        details = extract_article_details(
            listing["link"],
            title=listing["title"],
            pub_year=listing.get("pub_year"),   # v12
        )

        if details is None:
            save_posted(key)
            continue

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

        result = post_to_facebook(post)
        if result:
            save_posted(key)
            posted_count += 1
            print(f"✅ Posted {posted_count}/{MAX_PER_RUN}")
            if posted_count < MAX_PER_RUN:
                time.sleep(5)

    print(f"\n🏁 Run complete — {posted_count} post(s) published this run.")


if __name__ == "__main__":
    main()
