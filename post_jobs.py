"""
Kara Job Updates — Job Bot v18
================================
CHANGES from v17:

FIX 1 — Post structure matches manual posts exactly
  • Opener always starts with 🚨🎯
  • Requirements use ✅ emoji (not •)
  • Location uses 📍, closing date uses 📅 (no broken calendar emoji)
  • "Apply here 👇" on its own line, URL on the next line
  • Optional role description sentence from the actual advert

FIX 2 — Blog/article filter — hard block on editorial titles
  • Blocks titles like "Why Thousands Apply...", "What Happens After...",
    "Here Is What...", "Top 10...", "Guide To...", etc.
  • These are articles, not opportunities

FIX 3 — Requirements extraction completely rewritten
  • No more FAQ questions ("Is NARYSEC a paid programme?")
  • No more section headings ("What This Internship Is Really About")
  • No more mid-sentence conjunction cuts ("and are eager to enter...")
  • Each bullet must look like a real requirement
  • Fallback: use qual + citizenship/age sentences only

FIX 4 — Location cleaned
  • Rejects noise values: "specific", "a busy retail...", "various"
  • Only accepts named places: cities, provinces, municipalities

FIX 5 — Abbreviation fixer applied to ALL extracted text
  • NCV, WIL, ICT, NQF, TVET, HR, IT, AI, etc. always uppercase
  • "Ncv l4" → "NCV L4", "Wil" → "WIL", "Ict" → "ICT"

FIX 6 — Company name extraction improved
  • "Casual Frontshop" no longer extracted as company
  • Handles "Dis-Chem", hyphenated names correctly

FIX 7 — Qual tier display no longer garbled
  • "Ncv l4 intake)" type strings cleaned before display

FIX 8 — Article-style Edupstairs posts blocked
  • Only posts that describe a real opportunity pass the filter
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

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

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

# ─────────────────────────────────────────────
# ABBREVIATION FIXER
# ─────────────────────────────────────────────
# Applied to all extracted text: titles, req items, qual, location

_ABBREV_MAP = {
    r'\bNcv\b': 'NCV',
    r'\bncv\b': 'NCV',
    r'\bWil\b': 'WIL',
    r'\bwil\b': 'WIL',
    r'\bIct\b': 'ICT',
    r'\bict\b': 'ICT',
    r'\bNqf\b': 'NQF',
    r'\bnqf\b': 'NQF',
    r'\bTvet\b': 'TVET',
    r'\btvet\b': 'TVET',
    r'\bSeta\b': 'SETA',
    r'\bseta\b': 'SETA',
    r'\bHr\b': 'HR',
    r'\bIt\b(?=\s+(learnership|internship|support|technician|programme|skills|sector))'  : 'IT',
    r'\bAi\b': 'AI',
    r'\bCt\b': 'CT',
    r'\bSa\b(?=\s)': 'SA',
    r'\bNsc\b': 'NSC',
    r'\bNc\b(?=\s+\d)': 'NC',
    r'\bN(\d)\b': lambda m: f'N{m.group(1)}',   # N3, N4, N5 stay as-is
    r'\bNqf\s+[Ll]evel\b': 'NQF Level',
    r'\bncv\s+l(\d)\b': lambda m: f'NCV L{m.group(1)}',
    r'\bNcv\s+[Ll](\d)\b': lambda m: f'NCV L{m.group(1)}',
}

def fix_abbreviations(text):
    if not text:
        return text
    for pattern, replacement in _ABBREV_MAP.items():
        if callable(replacement):
            text = re.sub(pattern, replacement, text, flags=re.I)
        else:
            text = re.sub(pattern, replacement, text)
    # Generic: NQF Level N — ensure spacing
    text = re.sub(r'\bNQF\s*[Ll]evel\s*(\d)', r'NQF Level \1', text)
    # NCV LN — ensure spacing
    text = re.sub(r'\bNCV\s*[Ll](\d)', r'NCV L\1', text)
    return text


# ─────────────────────────────────────────────
# ARTICLE/BLOG POST FILTER — block non-opportunities
# ─────────────────────────────────────────────

# These title patterns indicate editorial articles, not job/learnership listings
_ARTICLE_TITLE_PATTERNS = re.compile(
    r'^(why\s+|what\s+happens?\s+|how\s+to\s+|top\s+\d|here\s+(are|is)\s+|'
    r'guide\s+to|everything\s+you\s+need|the\s+truth\s+about|'
    r'reasons?\s+why|tips?\s+(for|to)|steps?\s+to|things?\s+you\s+|'
    r'do\s+you\s+know|find\s+out|did\s+you\s+know|'
    r'mistakes?\s+(to\s+avoid|that)|secrets?\s+of|'
    r'inside\s+look|behind\s+the\s+scenes|'
    r'celebrating|congratulations|welcome\s+to)',
    re.I
)

# If a title CONTAINS these phrases it's editorial
_ARTICLE_PHRASE_PATTERNS = re.compile(
    r'(thousands\s+apply|only\s+a\s+few\s+get\s+selected|'
    r'your\s+next\s+move\s+matters|after\s+you\s+complete\s+a\s+learnership|'
    r'what\s+happens\s+after|success\s+stories|'
    r'tips\s+(for|to)\s+|how\s+to\s+write|how\s+to\s+prepare|'
    r'interview\s+tips|cv\s+tips|job\s+search\s+tips)',
    re.I
)

def is_article_not_job(title):
    """Return True if the title looks like an editorial article, not a real opportunity."""
    t = title.strip()
    if _ARTICLE_TITLE_PATTERNS.search(t):
        return True
    if _ARTICLE_PHRASE_PATTERNS.search(t):
        return True
    return False


# ─────────────────────────────────────────────
# KEYWORDS
# ─────────────────────────────────────────────

GOOD_KEYWORDS = [
    "learnership", "internship", "apprentice", "trainee",
    "vacancy", "vacancies", "entry level", "entry-level",
    "graduate", "youth", "matric", "grade 12", "grade 11", "grade 10",
    "bursary", "yes programme", "nyda", "seta", "nqf",
    "general worker", "general workers", "cleaner", "cleaners",
    "packer", "packers", "driver", "drivers", "security guard",
    "warehouse", "domestic", "handyman", "labourer", "labourers",
    "sweeper", "groundskeeper", "helper", "helpers",
    "porter", "gardener", "gardeners", "tea lady",
    "kitchen assistant", "store assistant", "cashier", "till operator",
    "casual", "contract", "part-time", "no experience", "unskilled",
    "hiring", "we are hiring", "now hiring", "apply now",
]

BAD_KEYWORDS = [
    "honours", "masters", "phd", "postgraduate",
    "5 years experience", "10 years", "executive", "head of", "director",
    "scam", "fake", "fraud", "warning", "not offering", "beware",
    "hoax", "misleading", "suspended", "arrested",
    "court", "murder", "killed", "died", "protest", "strike",
    "looting", "crime", "convicted", "tender", "parliament",
    "survey", "celebrating",
    "celebrity", "actress", "actor", "musician", "singer", "rapper",
    "album", "movie", "telenovela", "soap opera", "reality show",
    "dating", "relationship", "wedding", "divorce", "baby shower",
    "instagram", "twitter beef", "throwback", "hairstyle", "fashion",
    "presenter", "presenters", "lineup", "line-up",
    "top billing", "billing", "star-studded", "episode", "season",
    "contestant", "host", "audition", "casting", "cast",
    "nominated", "nomination", "award", "awards",
    "highlight", "preview", "teaser", "recap", "review",
    "stream", "streaming", "airs ", "premiere", "finale",
    "reality tv", "talk show", "game show",
]

RSS_SOURCES = [
    {"url": "https://www.salearnership.co.za/feed/",                     "source": "SA Learnership"},
    {"url": "https://learnerships24.co.za/feed/",                        "source": "Learnerships24"},
    {"url": "https://youthvillage.co.za/feed/",                          "source": "Youth Village SA"},
    {"url": "https://www.kazi-jobs.co.za/feed/",                          "source": "Kazi Jobs"},
    {"url": "https://www.kazi-jobs.co.za/category/job-opportunies/feed/", "source": "Kazi Jobs"},
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
    r'Learnerships\.net|South Africa In|SA Learnership Jobs|Kazi Jobs|'
    r'Jobs South Africa|Jobs Live|Job Vine)[^\n]*$',
    re.I
)

MAX_PER_RUN = 6

JUNK_PHRASES = [
    'copyright', 'powered by', 'privacy policy', 'all rights reserved',
    'cookie', 'subscribe', 'newsletter', 'follow us', 'share this',
    'click here', 'read more', 'learn more', 'mcnitols', 'edupstairs',
    'youth village', 'salearnership', 'learnerships24',
]

CURRENT_YEAR = str(datetime.now().year)

ALL_HASHTAGS = [
    "#Learnership", "#Internship", "#Apprenticeship",
    "#Grade12Jobs", "#Grade10Jobs", "#MatricJobs",
    "#YouthEmployment", "#SouthAfrica", "#Matric",
    "#KaraJobUpdates", "#JobAlert", "#GeneralWorker",
    "#JobsInSouthAfrica", "#NowHiring", "#EntryLevelJobs",
    "#NoExperienceNeeded", "#GautengJobs", "#JobOpportunity",
    "#SAJobs", "#WorkInSA",
]


# ─────────────────────────────────────────────
# QUALIFICATION TIER DETECTION
# ─────────────────────────────────────────────

def detect_qual_tier(qual_text, plain_text=""):
    primary = fix_abbreviations(qual_text.strip())
    if not primary:
        m = re.search(
            r'(?:minimum\s+requirements?|requirements?|qualification)[:\-]\s*(.{20,400})',
            plain_text, re.I | re.S)
        primary = m.group(1) if m else plain_text[:400]

    t = primary.lower()

    if re.search(r'\b(bachelor|b\.?tech|btech|b\s+tech|honours|degree)\b', t):
        m = re.search(
            r'(bachelor[\'s]*\s+(?:degree\s+)?in\s+[^\n\r.,;]{5,80}|'
            r'b\.?tech\s+in\s+[^\n\r.,;]{5,80}|'
            r'degree\s+in\s+[^\n\r.,;]{5,80}|'
            r'undergraduate\s+degree[^\n\r.,;]{0,60})',
            primary, re.I)
        display = m.group(0).strip().rstrip('.,;') if m else "Bachelor's degree or equivalent"
        return {"tier": "degree", "display": fix_abbreviations(display.capitalize())}

    if re.search(r'\b(national diploma|advanced diploma|higher certificate|'
                 r'nqf\s+level\s+[5-9]|nd\s+in)\b', t):
        m = re.search(
            r'((?:national\s+|advanced\s+)?diploma\s+in\s+[^\n\r.,;]{5,80}|'
            r'higher\s+certificate\s+in\s+[^\n\r.,;]{5,80}|'
            r'nqf\s+level\s+[5-9][^\n\r.,;]{0,40})',
            primary, re.I)
        display = m.group(0).strip().rstrip('.,;') if m else "National Diploma or equivalent"
        return {"tier": "diploma", "display": fix_abbreviations(display.capitalize())}

    if re.search(r'\b(nqf\s+level\s+4|n[3-6]\s+certificate|n[3-6]\b|ncv|tvet|trade\s+test|artisan)\b', t):
        m = re.search(
            r'(n[3-6]\s+[^\n\r.,;]{0,60}|ncv[^\n\r.,;]{0,60}|'
            r'trade\s+test[^\n\r.,;]{0,40}|nqf\s+level\s+4[^\n\r.,;]{0,40})',
            primary, re.I)
        raw = m.group(0).strip().rstrip('.,;') if m else "N-Certificate / Trade Test"
        display = fix_abbreviations(raw.capitalize())
        # Clean garbled suffix like "intake)" or stray brackets
        display = re.sub(r'\s*[\(\)]+\s*$', '', display).strip()
        return {"tier": "certificate", "display": display}

    if re.search(r'\b(grade\s*12|matric|national\s+senior\s+certificate|nsc)\b', t):
        return {"tier": "grade12", "display": "Grade 12 (Matric)"}

    if re.search(r'\b(grade\s*1[01])\b', t):
        return {"tier": "grade1011", "display": "Grade 10 or 11"}

    if re.search(r'\b(no\s+(formal\s+)?qualif|unskilled|abet|no\s+experience\s+needed|grade\s*[89])\b', t):
        return {"tier": "any", "display": "No formal qualification required"}

    return {"tier": "grade12", "display": "Grade 12 (Matric)"}


# ─────────────────────────────────────────────
# URL UTILITIES
# ─────────────────────────────────────────────

def strip_utm(url):
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if not k.startswith("utm_")}
        new_query = urlencode(clean_qs, doseq=True)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                            parsed.params, new_query, ""))
        return clean.rstrip("/")
    except Exception:
        return re.sub(r'\?.*$', '', url).rstrip('/')


# ─────────────────────────────────────────────
# TITLE CASING + ABBREVIATION FIXING
# ─────────────────────────────────────────────

_LOWER_WORDS = {"a","an","the","and","but","or","for","nor","at","by","in","of","on","to","up","as"}

# Known acronyms/abbreviations that must stay ALL-CAPS in titles
_FORCE_UPPER = {
    "ncv","wil","ict","nqf","tvet","seta","nyda","sa","hr","it","ai","hiv","tb",
    "nsc","fet","nsfas","dhet","uif","sars","saps","sandf","narysec","bocma",
    "eastc","apx","var",
}

def smart_title(text):
    words = text.split()
    result = []
    for i, word in enumerate(words):
        leading  = re.match(r'^([^A-Za-z0-9]*)', word).group(1)
        trailing = re.search(r'([^A-Za-z0-9]*)$', word).group(1)
        core = word[len(leading): len(word) - len(trailing) if trailing else len(word)]
        if not core:
            result.append(word); continue
        alpha = re.sub(r'[^A-Za-z]', '', core)
        # Already all-caps acronym — keep it
        if len(alpha) >= 2 and alpha == alpha.upper():
            result.append(word); continue
        # Known acronym that should be forced upper
        if alpha.lower() in _FORCE_UPPER:
            result.append(leading + alpha.upper() + trailing); continue
        if i > 0 and core.lower() in _LOWER_WORDS:
            result.append(leading + core.lower() + trailing); continue
        result.append(leading + core.capitalize() + trailing)
    return fix_abbreviations(' '.join(result))


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
            try: return datetime(int(yr), month, int(day))
            except ValueError: pass
    return None


def is_junk(val):
    return any(j in val.lower() for j in JUNK_PHRASES)


# ─────────────────────────────────────────────
# YEAR VALIDATION
# ─────────────────────────────────────────────

def confirm_current_year(title, plain, pub_year=None):
    if CURRENT_YEAR in title: return True
    if CURRENT_YEAR in plain[:5000]: return True
    if pub_year and str(pub_year) == CURRENT_YEAR:
        print(f"   ℹ️  Year confirmed via pubDate ({pub_year})")
        return True
    return False


# ─────────────────────────────────────────────
# HTML → PLAIN TEXT
# ─────────────────────────────────────────────

def strip_html(html):
    html = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', html, flags=re.DOTALL|re.I)
    html = re.sub(r'<(br|p|div|h[1-6]|section|article|header|footer|nav)[^>]*>', '\n', html, flags=re.I)
    html = re.sub(r'</(p|div|h[1-6]|section|article|header|footer|nav)>', '\n', html, flags=re.I)
    html = re.sub(r'<li[^>]*>', '\n• ', html, flags=re.I)
    html = re.sub(r'<[^>]+>', '', html)
    html = unescape(html)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n[ \t]+', '\n', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


def get_main_content(html):
    for pat in [
        r'<article[^>]*>(.*?)</article>',
        r'<main[^>]*>(.*?)</main>',
        r'<div[^>]*class="[^"]*(?:entry|post|content|article)-(?:content|body)[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
    ]:
        m = re.search(pat, html, re.DOTALL|re.I)
        if m: return m.group(1)
    for t in ["footer","nav","header"]:
        html = re.sub(rf'<{t}[^>]*>.*?</{t}>', '', html, flags=re.DOTALL|re.I)
    return html


def find_section(text, *patterns):
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            chunk = text[m.end():m.end()+800]
            stop = re.search(
                r'\n(?:Requirements?|Qualification|Experience|How to Apply|'
                r'Application|Benefits?|Responsibilities|Duties|About)\s*[:\-\n]',
                chunk, re.I)
            return chunk[:stop.start()] if stop else chunk
    return ""


# ─────────────────────────────────────────────
# REQUIREMENTS — completely rewritten
# Items must look like actual requirements, not FAQ/headings
# ─────────────────────────────────────────────

# These patterns indicate a line is NOT a real requirement
_NOT_REQ = re.compile(
    r'^(is\s+|are\s+|can\s+i\s+|do\s+i\s+|will\s+i\s+|does\s+|'      # FAQ questions
    r'what\s+(is|are|this|happens|does)|why\s+|how\s+(do|does|to|can)|'  # FAQ/article
    r'when\s+|where\s+can|who\s+(can|is|are)\s+(?!eligible|qualif)|'
    r'note:|nb:|disclaimer|for\s+more\s+info|contact\s+us|'
    r'for\s+(this|the)\s+(?:opportunity|programme|position|role|internship|learnership)[^.]{0,40}(must|criteria|following|apply)\b|'
    r'apply\s+(now|here|online|via|at|to|through)|'
    r'click\s+|visit\s+|email\s+|send\s+|submit\s+|'
    r'about\s+(the\s+)?(company|programme|us|this)|'
    r'overview|introduction|background|description|'
    r'training\s+provider|reference\s*:|'
    r'responsibilities|duties|what\s+you\s+will\s+(do|learn|gain))',
    re.I
)

# A real requirement contains one of these signals
_REQ_SIGNAL = re.compile(
    r'(grade|matric|diploma|degree|certificate|nqf|ncv|n3|n4|n5|'
    r'years?\s+of\s+experience|years?\s+experience|experience|'
    r'unemployed|age\s*\d|\d+\s*[-–]\s*\d+\s*years?|'
    r'south\s+african\s+citizen|citizen|valid\s+id|id\s+document|'
    r'driver[\'s]?\s+licen[sc]e|licence|computer\s+(literate|skills?)|'
    r'reside|resident|living\s+in|based\s+in|municipality|'
    r'must\s+(be|have|hold)|you\s+(must|need\s+to|should\s+have)|'
    r'minimum|required|essential|advantageous|'
    r'not\s+(currently\s+)?employed|no\s+(criminal|previous)|'
    r'physically\s+fit|own\s+transport|bilingual|fluent|proficient)',
    re.I
)

_REQ_HEADINGS = re.compile(
    r'(minimum\s+requirements?|requirements?|eligibility|who\s+can\s+apply|'
    r'qualifications?\s+required|to\s+qualify|what\s+you\s+need|'
    r'essential\s+requirements?|advantageous)',
    re.I
)


def _clean_req_item(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[•·▪➤✔✓\-–*]\s*', '', text).strip()
    text = re.sub(r'^\d+[\.\)]\s*', '', text).strip()
    return fix_abbreviations(text)


def _is_valid_req(item):
    """Return True if item looks like a real requirement."""
    if len(item) < 5:
        return False
    if is_junk(item):
        return False
    if item.endswith('?'):  # FAQ question
        return False
    if _NOT_REQ.match(item):
        return False
    if not _REQ_SIGNAL.search(item):
        # Allow short items that start with "Must" or similar even without signal
        if not re.match(r'^(must\s+|you\s+must\s+|applicants?\s+must\s+)', item, re.I):
            return False
    return True


def _truncate_at_word(text, max_chars=90):
    """Truncate at a word boundary, never mid-word."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(' ', 1)[0].rstrip('.,;:')
    return cut + "…"


def extract_top_requirements(html_content, plain_text, max_items=3):
    items = []

    if BS4_AVAILABLE:
        soup = BeautifulSoup(html_content, "lxml" if LXML_AVAILABLE else "html.parser")
        for t in soup(["nav","footer","header","script","style"]):
            t.decompose()

        # Find requirements heading, then grab the next UL/OL
        for heading in soup.find_all(re.compile(r'^h[1-6]$|^(strong|b|p)$')):
            if _REQ_HEADINGS.search(heading.get_text(strip=True)):
                sib = heading.find_next_sibling()
                while sib:
                    if sib.name in ("ul","ol"):
                        for li in sib.find_all("li"):
                            raw = _clean_req_item(li.get_text(separator=" ", strip=True))
                            if _is_valid_req(raw):
                                items.append(raw)
                        if items: break
                    if sib.name and re.match(r'^h[1-6]$', sib.name):
                        break
                    sib = sib.find_next_sibling()
            if items: break

        # Fallback: scan all lists
        if not items:
            for lst in soup.find_all(["ul","ol"]):
                if _REQ_SIGNAL.search(lst.get_text()):
                    for li in lst.find_all("li"):
                        raw = _clean_req_item(li.get_text(separator=" ", strip=True))
                        if _is_valid_req(raw):
                            items.append(raw)
                    if len(items) >= 2:
                        break

    # Plain text fallback
    if not items:
        section = find_section(
            plain_text,
            r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s*[:\-]',
            r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
        )
        seen = set()
        for raw in section.split('\n'):
            raw = _clean_req_item(raw)
            if not _is_valid_req(raw):
                continue
            rl = raw.lower()
            if rl in seen:
                continue
            seen.add(rl)
            items.append(raw)

    # Sort: qualification first
    def qual_priority(s):
        sl = s.lower()
        if any(w in sl for w in ['grade','matric','diploma','degree','certificate','nqf','ncv','n3','n4','n5']):
            return 0
        if any(w in sl for w in ['unemployed','age','citizen','south african','id']):
            return 1
        return 2

    items.sort(key=qual_priority)
    return [_truncate_at_word(item, 90) for item in items[:max_items]]


# ─────────────────────────────────────────────
# ROLE DESCRIPTION — extract 1-2 sentences from the advert body
# Used in posts like Dis-Chem where there is a real job description
# ─────────────────────────────────────────────

def extract_role_description(plain_text, title=""):
    """
    Try to extract a natural 1-2 sentence description of what the role/programme is.
    Returns empty string if nothing clean found.
    """
    # Look for a paragraph that describes the role (not requirements section)
    # Avoid: FAQ, headings, navigation, contact info
    desc_patterns = [
        r'(?:is\s+(?:looking|seeking|inviting|offering|providing|accepting|open(?:ing)?)\s+applications?\s+for\s+)([^.\n]{30,200}\.)',
        r'(?:programme?\s+(?:is|aims?|provides?|offers?|seeks?)\s+)([^.\n]{30,200}\.)',
        r'(?:opportunity\s+(?:is|for|to)\s+)([^.\n]{30,200}\.)',
        r'(?:requires?\s+a\s+)([^.\n]{20,150}\s+to\s+[^.\n]{10,100}\.)',
    ]
    for pat in desc_patterns:
        m = re.search(pat, plain_text[:3000], re.I)
        if m:
            sentence = m.group(0).strip()
            sentence = re.sub(r'\s+', ' ', sentence)
            if 30 <= len(sentence) <= 250 and not is_junk(sentence):
                return fix_abbreviations(sentence)

    # Fallback: find the first substantive paragraph (not a heading, not a list)
    paragraphs = [p.strip() for p in plain_text[:3000].split('\n\n') if p.strip()]
    for para in paragraphs[1:4]:  # skip the very first (often a title echo)
        para = re.sub(r'\s+', ' ', para).strip()
        if len(para) < 40 or len(para) > 300:
            continue
        if re.match(r'^(requirements?|qualification|how to apply|about|overview)', para, re.I):
            continue
        if is_junk(para):
            continue
        if not re.search(r'[a-z]{4}', para):  # no real words
            continue
        # Must contain a verb
        if re.search(r'\b(requires?|offers?|provides?|seeks?|invit|looking|accepting|open|must|will|can)\b', para, re.I):
            return fix_abbreviations(para[:250])

    return ""


# ─────────────────────────────────────────────
# QUALIFICATION EXTRACTION
# ─────────────────────────────────────────────

def extract_qualification(text):
    QUAL_NOUNS = [
        'grade 12','grade12','grade 11','grade 10','matric','national senior certificate',
        'national certificate','national diploma','higher certificate',
        'advanced diploma','bachelor','b.tech','btech','b tech',
        'degree','diploma','nqf level','nqf','abet','fet',
        'trade test','artisan','certificate','n3','n4','n5',
        'undergraduate',
    ]
    for pat in [
        r'[Qq]ualification(?:s)?\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Mm]inimum\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Rr]equired\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,100})',
        r'[Ee]ducation(?:al\s+[Rr]equirement)?\s*[:\-]\s*([^\n\r]{10,100})',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            val = _cq(m.group(1))
            if val and _qv(val, QUAL_NOUNS): return val
    for pat in [
        r'(Grade\s+1[012][^.\n\r]{0,80})',
        r'(Matric(?:ulation)?(?:\s+Certificate)?[^.\n\r]{0,60})',
        r'((?:National\s+)?Diploma\s+in\s+[^.\n\r]{5,80})',
        r'(Higher\s+Certificate\s+in\s+[^.\n\r]{5,60})',
        r'(Advanced\s+Diploma\s+in\s+[^.\n\r]{5,60})',
        r'(Bachelor(?:\'s)?\s+(?:Degree\s+)?in\s+[^.\n\r]{5,60})',
        r'(Undergraduate\s+Degree[^.\n\r]{0,60})',
        r'(B\.?Tech\s+in\s+[^.\n\r]{5,60})',
        r'(NQF\s+Level\s+\d[^.\n\r]{0,40})',
        r'(N[3-6]\s+[^\n\r]{0,40})',
        r'(Trade\s+Test[^.\n\r]{0,40})',
        r'(NCV\s+Level\s+\d[^.\n\r]{0,40})',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            val = _cq(m.group(1))
            if val and _qv(val, QUAL_NOUNS) and len(val) >= 12: return val
    return None


def _cq(val):
    val = val.strip()
    val = re.split(r'[|;]', val)[0].strip().rstrip('.,;:-()')
    for jp in JUNK_PHRASES:
        idx = val.lower().find(jp)
        if idx > 0: val = val[:idx].strip()
    val = re.sub(r'[{}\[\]<>@#=]', '', val[:120]).strip()
    return fix_abbreviations(val)


def _qv(val, nouns):
    if not val or len(val) < 4 or is_junk(val): return False
    return any(n in val.lower() for n in nouns)


# ─────────────────────────────────────────────
# COMPANY NAME EXTRACTION — improved
# ─────────────────────────────────────────────

_NOISE_FIRST = {
    "learnership","internship","apprenticeship","bursary","vacancy","vacancies",
    "opportunity","opportunities","programme","program","graduate","trainee",
    "yes","general","worker","workers","officer","officers","cleaner","cleaners",
    "packer","packers","driver","drivers","security","preparing","check","looking","how",
    "find","here","this","now","new","top","best","why","what","where","all","join",
    "learn","meet","see","register","open","about","exciting","great","latest",
    "congratulations","welcome","calling","wanted","notice","update","deadline",
    # These are roles/adjectives, not company names:
    "casual","frontshop","front","shop","retail","store","part","full","time",
    "contract","temporary","permanent","junior","senior","entry","level",
}

_NOISE_SUFFIX = {
    "general","worker","workers","officer","officers","clerk","assistant",
    "manager","supervisor","technician","specialist","practitioner","analyst",
    "advisor","consultant","coordinator","engineer","supply","chain",
    "financial","corporate","senior","junior","artisan","intern","learner",
    "millwright","boilermaker","electrician","plumber","welder","fitter",
    "frontshop","cashier","packer","driver","cleaner","security",
}

_OPP_TRIGGER = re.compile(
    r'\b(Learnership|Internship|Apprenticeship|Bursary|Graduate|'
    r'Vacancy|Vacancies|Programme|Program|Opportunity|Opportunities|'
    r'Trainee|Artisan|YES|Cleaner|Cleaners|General\s+Worker|General\s+Workers|'
    r'Packer|Packers|Driver|Drivers|Security\s+Guard|Labourer|Labourers|'
    r'Helper|Helpers|Porter|Porters|Gardener|Gardeners|Cashier|'
    r'Hiring|Wanted|Needed|Assistant)\b',
    re.I
)

# Known multi-word company names — match these first before tokenising
_KNOWN_COMPANIES = re.compile(
    r'\b(Dis[- ]?Chem(?:\s+Pharmacies)?|Pick\s+n\s+Pay|Shoprite\s+Checkers?|'
    r'Old\s+Mutual|Rand\s+Water|Kimberly\s+Clark|Northlink\s+College|'
    r'West\s+Coast\s+TVET\s+College|Sasol|Takealot|Paracon|Vodacom|'
    r'Feltex\s+Shipping|APX\s+Security|National\s+Rural\s+Youth\s+Service\s+Corps|'
    r'NARYSEC|BOCMA|EASTC|Department\s+of\s+[A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)?|'
    r'SASSA|NECSA|Samancor|Motus|Adidas|Cashbuild|Kia\s+(?:SA|South\s+Africa))\b',
    re.I
)


def extract_company(title):
    # First try known multi-word company names
    m = _KNOWN_COMPANIES.search(title)
    if m:
        return fix_abbreviations(m.group(0).strip())

    # Then fall back to position-based extraction
    m = _OPP_TRIGGER.search(title)
    if not m: return ""
    candidate = title[:m.start()].strip()
    words = candidate.split()
    if not words or words[0].lower() in _NOISE_FIRST: return ""
    while words and (words[-1].lower() in _NOISE_SUFFIX or re.match(r'^20\d{2}$', words[-1])):
        words.pop()
    if not words: return ""
    # Extra check: if any remaining word is in NOISE_FIRST, the company name is invalid
    if words[0].lower() in _NOISE_FIRST: return ""
    company = " ".join(words[:6])
    return fix_abbreviations(company) if len(company) >= 2 and not company.isdigit() else ""


# ─────────────────────────────────────────────
# LOCATION — stricter validation
# ─────────────────────────────────────────────

# Accept only if it matches a real place-name pattern
_VALID_LOCATION = re.compile(
    r'\b(Johannesburg|Cape\s+Town|Durban|Pretoria|Soweto|Sandton|'
    r'Ekurhuleni|Tshwane|Polokwane|Bloemfontein|Port\s+Elizabeth|Gqeberha|'
    r'East\s+London|Rustenburg|Kimberley|Nelspruit|Midrand|Centurion|'
    r'Sasolburg|Secunda|Welkom|Vanderbijlpark|Vereeniging|Alberton|Benoni|'
    r'Boksburg|Soweto|Roodepoort|Krugersdorp|Mpumalanga|Limpopo|Gauteng|'
    r'Western\s+Cape|KwaZulu[- ]Natal|North\s+West|Northern\s+Cape|'
    r'Eastern\s+Cape|Free\s+State|Mpumalanga|South\s+Africa)\b',
    re.I
)

# Reject location values that are clearly noise
_JUNK_LOCATION = re.compile(
    r'^(specific|various|see\s+advert|multiple|nationwide|country[- ]?wide|'
    r'tbd|to\s+be\s+confirmed|n/?a|not\s+specified|'
    r'a\s+busy|retail|pharmacy|environment|office|workplace)',
    re.I
)


def clean_location(val):
    """Validate and clean a location string. Returns None if not trustworthy."""
    if not val:
        return None
    val = val.strip().rstrip('.,;')
    val = fix_abbreviations(val)
    if len(val) < 3 or len(val) > 80:
        return None
    if _JUNK_LOCATION.match(val):
        return None
    if re.search(r'(http|www|\.co|click|apply|salary)', val, re.I):
        return None
    # Must either match a known place or be short and capitalised
    if _VALID_LOCATION.search(val):
        return val
    # Short capitalised string that doesn't look like junk
    if len(val) <= 40 and val[0].isupper() and not re.search(r'[{}\[\]<>@#=;]', val):
        if not _JUNK_LOCATION.search(val):
            return val
    return None


# ─────────────────────────────────────────────
# ARTICLE DETAIL EXTRACTOR
# ─────────────────────────────────────────────

def extract_article_details(url, title="", pub_year=None):
    details = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"   ⚠️  HTTP {r.status_code}"); return None

        main_html = get_main_content(r.text)
        plain = strip_html(main_html)

        if not confirm_current_year(title, plain, pub_year):
            print(f"   ❌ Stale — no {CURRENT_YEAR}"); return None

        # Closing date
        for pat in [
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Cc]losing\s+[Dd]ate\s*[:\-]\s*(\w+\s+\d{1,2},?\s+\d{4})',
            r'[Dd]eadline\s*[:\-]\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'[Aa]pply\s+[Bb]efore\s*[:\-]?\s*(\d{1,2}[\s/\-]\w+[\s/\-]\d{4})',
            r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+202[5678])',
            r'(\d{1,2}[\/\-]\d{1,2}[\/\-]202[5678])',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                parsed = parse_date_str(m.group(1).strip())
                if parsed:
                    details["closing_date"] = parsed.strftime("%d %B %Y")
                    details["closing_date_obj"] = parsed
                    break

        # Location
        raw_loc = None
        for pat in [
            r'[Ll]ocation\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,60})',
            r'[Cc]ity\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Pp]rovince\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Bb]ased\s+[Ii]n\s*[:\-]?\s*([A-Za-z][^\n\r|,\.]{3,40})',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                candidate = clean_location(m.group(1))
                if candidate:
                    raw_loc = candidate
                    break

        # Fallback: scan for known city/province names
        if not raw_loc:
            m = _VALID_LOCATION.search(plain[:3000])
            if m:
                raw_loc = m.group(0).strip()

        if raw_loc:
            details["location"] = raw_loc

        # Qualification
        req_section = find_section(plain,
            r'[Rr]equirements?\s*[:\-]', r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s*[:\-]', r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Qq]ualifications?\s+[Rr]equired\s*[:\-]', r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
        )
        qual = extract_qualification(req_section or "") or extract_qualification(plain[:3000])
        if qual: details["qualification"] = qual

        details["qual_tier"] = detect_qual_tier(qual or "", req_section or "")

        # Requirements
        tier = details["qual_tier"]["tier"]
        req_items = extract_top_requirements(main_html, plain, max_items=4)

        # Pin qualification as first item if not already present
        if qual:
            qual_short = _truncate_at_word(qual, 90)
            if not any(qual_short[:20].lower() in r.lower() for r in req_items):
                req_items = [qual_short] + [r for r in req_items if r != qual_short]

        # Drop items that contradict detected tier
        req_items = _filter_req_by_tier(req_items, tier)[:3]
        details["req_items"] = req_items

        # Positions
        for pat in [
            r'\(X?\s*(\d+)\s*[Pp]osts?\)', r'\(X?\s*(\d+)\s*[Pp]ositions?\)',
            r'[Pp]ositions?\s+[Aa]vailable\s*[:\-]\s*(\d+)',
            r'(\d+)\s+[Pp]osts?\s+[Aa]vailable',
            r'(\d+)\s+[Vv]acancies', r'[Xx]\s*(\d+)\s+[Pp]osts?',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()
                if val.isdigit() and 0 < int(val) < 1000:
                    details["positions"] = val; break

        # Role description (for non-learnership posts)
        role_desc = extract_role_description(plain, title)
        if role_desc:
            details["role_description"] = role_desc

        # Opportunity type
        tl = (title + " " + plain[:200]).lower()
        if "learnership" in tl:       details["opp_type"] = "learnership"
        elif "internship" in tl:      details["opp_type"] = "internship"
        elif "apprentice" in tl:      details["opp_type"] = "apprenticeship"
        elif "bursary" in tl:         details["opp_type"] = "bursary"
        elif any(w in tl for w in ["general worker","cleaner","packer","driver",
                                    "security","warehouse","labourer","porter","gardener",
                                    "cashier","kitchen","domestic","assistant","frontshop"]):
            details["opp_type"] = "job"
        else:
            details["opp_type"] = "opportunity"

        print(f"   Fields: {[k for k in details if k not in ('closing_date_obj','qual_tier','req_items','role_description')]}")
        print(f"   Qual tier: {details['qual_tier']['tier']} → {details['qual_tier']['display']}")
        print(f"   Req items: {details.get('req_items', [])}")

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return details


def _filter_req_by_tier(req_items, tier):
    if not req_items:
        return req_items
    lower_qual_words = {
        "degree":      ["grade 12", "grade12", "matric", "grade 10", "grade 11", "national senior"],
        "diploma":     ["grade 12", "grade12", "matric", "grade 10", "grade 11", "national senior"],
        "certificate": ["grade 12", "grade12", "matric", "grade 10", "national senior"],
    }
    blocklist = lower_qual_words.get(tier, [])
    filtered = []
    for item in req_items:
        il = item.lower().strip()
        if blocklist and any(
            il == w or il.startswith(w + " ") or il.startswith(w + "(") or il.startswith(w + ",")
            for w in blocklist
        ):
            continue
        # Remove items ending mid-sentence on a conjunction
        if re.search(r'\b(and|or|with|who|that|where|when|as|but)\s*[…]?\s*$', il):
            continue
        filtered.append(item)
    return filtered if filtered else req_items


# ─────────────────────────────────────────────
# POST BUILDER — matches your manual post structure exactly
# ─────────────────────────────────────────────
#
# Manual structure (from your screenshots):
#   🚨🎯 [One sentence opener]
#
#   [Optional: 1-2 sentence role description]
#
#   Requirements:
#   ✅ Requirement 1
#   ✅ Requirement 2
#   ✅ Requirement 3
#
#   📍 Location
#   📅 Closing date: DD Month YYYY
#
#   Apply here 👇
#   [URL]
#
#   [Closing line]
#
#   #Hashtags

_OPENERS_GRADE12_WITH_COMPANY = [
    "{company} has opened a {opp} — no experience required, just {qual}.",
    "{company} is hiring. Your Matric is all you need to apply.",
    "Great opportunity at {company}. Grade 12 is the only qualification they are asking for.",
    "If you have been sitting at home with your Matric, {company} wants to hear from you.",
    "{company} is offering a {opp} and they are not asking for a degree. {qual} is enough.",
    "Doors are open at {company}. All you need to walk through them is {qual}.",
    "This one goes to all Matric holders — {company} is accepting applications right now.",
    "{company} does not care about work experience here. They just want people with {qual}.",
]

_OPENERS_GRADE12_NO_COMPANY = [
    "A {opp} is open right now. Minimum: {qual}.",
    "If you have your Matric, this {opp} is for you.",
    "Here is one for Grade 12 holders. A {opp} is accepting applications now.",
    "No degree needed. This {opp} only requires {qual}.",
]

_OPENERS_GRADE12_WITH_POSITIONS = [
    "{company} has {positions} spots open right now. Your Matric is all you need to apply.",
    "{company} is filling {positions} positions. Grade 12 holders, this is for you.",
    "{company} needs {positions} people. Minimum qualification: {qual}.",
]

_OPENERS_INTERNSHIP = [
    "{company} has an internship for their former students — below are the requirements.",
    "{company} is offering an internship. Get your foot in the door — {qual} required.",
    "Internship available at {company}. They are looking for people with {qual}.",
    "{company} has opened internship applications. Minimum qualification: {qual}.",
    "Want real work experience? {company} has an internship and they need {qual}.",
]

_OPENERS_INTERNSHIP_NO_COMPANY = [
    "An internship is open. Minimum qualification: {qual}.",
    "Internship opportunity available. You will need {qual} to apply.",
    "Here is an internship for people with {qual}. Check the requirements below.",
]

_OPENERS_APPRENTICESHIP = [
    "{company} is offering an apprenticeship. You will earn while you learn a trade — {qual} required.",
    "Apprenticeship alert! {company} is taking on new learners. Minimum: {qual}.",
    "{company} wants to train you in a trade. If you have {qual}, get your application in.",
    "Build a career with your hands. {company} has an apprenticeship open — {qual} is enough.",
]

_OPENERS_DEGREE_WITH_COMPANY = [
    "{company} Learnership Programme is opened for unemployed graduates who want to gain industrial exposure in this field.",
    "{company} is looking for graduates. You need a {qual} to apply.",
    "Graduates — {company} has a {opp} open for you. Minimum: {qual}.",
    "{company} wants degree holders for their {opp}. If that is you, apply now.",
]

_OPENERS_DEGREE_NO_COMPANY = [
    "A graduate {opp} is open. You will need {qual} to be considered.",
    "Graduates, this one is for you. A {opp} is available — {qual} required.",
    "Applications are open for a graduate {opp}. Minimum qualification: {qual}.",
]

_OPENERS_DIPLOMA = [
    "{company} is looking for candidates with a {qual}. Applications are open.",
    "Got a {qual}? {company} wants to hear from you — they have a {opp} available.",
    "{company} is recruiting for a {opp}. Minimum qualification: {qual}.",
    "This {opp} at {company} is for people who hold a {qual}.",
]

_OPENERS_JOB_WITH_COMPANY = [
    "{company} requires a {role}, to uphold their standards and procedures.",
    "{company} is looking for a {role} right now. Apply before the closing date.",
    "{role} wanted at {company} — vacancies are open and applications are being accepted.",
    "{company} needs a {role}. If that is you, your application is welcome.",
]

_OPENERS_JOB_NO_COMPANY = [
    "{role} are needed. Check the details and apply if you qualify.",
    "Job alert — {role} vacancies are open. See the requirements below.",
    "There is work available for {role}. Applications are open now.",
]

_OPENERS_LEARNERSHIP_NO_COMPANY = [
    "A learnership has opened — for the unskilled and unemployed youth. Check the requirements below.",
    "A learnership is open right now. Minimum: {qual}.",
    "Here is a learnership for people with {qual}. Applications are open.",
    "Learnership alert! Minimum requirement: {qual}. Apply before the deadline.",
]

_CLOSING_LINES = [
    "Know someone without a job? Send this to them. 🙌",
    "Share with someone who needs this. 🙏",
    "Tag a friend who is looking for work. 👇",
    "If this is not for you, share it with someone it is for. 🙏",
    "Pass this on — someone out there is waiting for this opportunity.",
    "Do not keep this to yourself. Tag someone who needs it. 👇",
    "Someone in your circle needs to see this. Share it.",
]


def _pick(options):
    return random.choice(options)


def _pick_hashtags(opp_type, tier):
    base = ["#KaraJobUpdates", "#JobsInSouthAfrica", "#SouthAfrica"]
    if opp_type == "learnership":
        pool = ["#Learnership","#YouthEmployment","#MatricJobs","#Grade12Jobs",
                "#EntryLevelJobs","#SAJobs","#NowHiring","#JobOpportunity"]
    elif opp_type == "internship":
        pool = ["#YouthEmployment","#NowHiring","#JobAlert","#EntryLevelJobs",
                "#Internship","#JobOpportunity","#SAJobs","#NowHiring"]
    elif opp_type == "apprenticeship":
        pool = ["#Apprenticeship","#YouthEmployment","#SAJobs",
                "#NowHiring","#JobOpportunity","#MatricJobs","#JobAlert","#EntryLevelJobs"]
    elif opp_type == "job":
        pool = ["#JobAlert","#Grade10Jobs","#Learnership",
                "#GeneralWorker","#MatricJobs","#NowHiring","#EntryLevelJobs","#SAJobs"]
    elif tier == "degree":
        pool = ["#YouthEmployment","#Learnership","#NowHiring","#MatricJobs",
                "#JobOpportunity","#NowHiring","#GraduateJobs","#SAJobs"]
    else:
        pool = ["#YouthEmployment","#NowHiring","#JobAlert","#EntryLevelJobs",
                "#Learnership","#MatricJobs","#SAJobs","#JobOpportunity"]
    selected = random.sample(pool, min(5, len(pool)))
    return " ".join(base + selected)


def build_post(title, details, direct_url, source):
    title = SITE_SUFFIXES.sub('', title).strip()
    title = smart_title(title)
    direct_url = strip_utm(direct_url)

    opp_type     = details.get("opp_type", "opportunity")
    location     = details.get("location", "")
    closing      = details.get("closing_date", "")
    positions    = details.get("positions", "")
    req_items    = details.get("req_items", [])
    qual_tier    = details.get("qual_tier", {"tier": "grade12", "display": "Grade 12 (Matric)"})
    role_desc    = details.get("role_description", "")

    qual_display = qual_tier["display"]
    tier         = qual_tier["tier"]
    company      = extract_company(title)

    # Detect role type for job posts
    role_match = re.search(
        r'\b(cleaners?|general\s+workers?|packers?|drivers?|security\s+guards?|'
        r'labourers?|porters?|gardeners?|warehouse\s+workers?|helpers?|cashiers?|'
        r'kitchen\s+assistants?|domestic\s+workers?|frontshop\s+assistants?|'
        r'store\s+assistants?|till\s+operators?)\b',
        title, re.I
    )
    is_job_role = bool(role_match)
    role_raw = role_match.group(0).strip() if role_match else ""
    # Keep singular for "requires a Cashier" style
    role = role_raw.title()

    # ── Pick opener ─────────────────────────────────────────────────────
    def fmt(t):
        try:
            return t.format(
                company=company or "This company",
                opp=opp_type,
                qual=qual_display,
                positions=positions,
                role=role,
                location=location or "South Africa"
            )
        except KeyError:
            return t

    if opp_type == "internship" and company:
        opener = fmt(_pick(_OPENERS_INTERNSHIP))
    elif opp_type == "internship":
        opener = fmt(_pick(_OPENERS_INTERNSHIP_NO_COMPANY))
    elif opp_type == "apprenticeship" and company:
        opener = fmt(_pick(_OPENERS_APPRENTICESHIP))
    elif tier == "degree" and company:
        opener = fmt(_pick(_OPENERS_DEGREE_WITH_COMPANY))
    elif tier == "degree":
        opener = fmt(_pick(_OPENERS_DEGREE_NO_COMPANY))
    elif tier in ("diploma", "certificate") and company:
        opener = fmt(_pick(_OPENERS_DIPLOMA))
    elif is_job_role and company:
        opener = fmt(_pick(_OPENERS_JOB_WITH_COMPANY))
    elif is_job_role:
        opener = fmt(_pick(_OPENERS_JOB_NO_COMPANY))
    elif positions and company:
        opener = fmt(_pick(_OPENERS_GRADE12_WITH_POSITIONS))
    elif company:
        opener = fmt(_pick(_OPENERS_GRADE12_WITH_COMPANY))
    elif opp_type == "learnership":
        opener = fmt(_pick(_OPENERS_LEARNERSHIP_NO_COMPANY))
    else:
        opener = f"A {opp_type} is open right now. Minimum: {qual_display}."

    # ── Build post ────────────────────────────────────────────────────
    lines = [f"🚨🎯 {opener}"]

    # Optional role description (from advert body) — only for job posts and internships
    # where there IS a real description scraped
    if role_desc and opp_type in ("job", "internship") and len(role_desc) >= 40:
        lines.append("")
        lines.append(role_desc)

    # Requirements section
    lines.append("")
    lines.append("Requirements:")
    if req_items:
        for item in req_items:
            lines.append(f"✅ {item}")
    else:
        lines.append(f"✅ {qual_display}")
        lines.append("✅ Check the advert for full details")

    lines.append("")

    # Location and closing date
    if location:
        lines.append(f"📍 {location}")
    lines.append(f"📅 Closing date: {closing if closing else 'See advert'}")
    lines.append("")

    # Apply line
    lines.append("Apply here 👇")
    lines.append(direct_url)
    lines.append("")

    # Closing line
    lines.append(_pick(_CLOSING_LINES))
    lines.append("")

    # Hashtags
    lines.append(_pick_hashtags(opp_type, tier))

    return "\n".join(lines)


# ─────────────────────────────────────────────
# XML PARSING
# ─────────────────────────────────────────────

def clean_xml(text):
    text = text.lstrip('\ufeff')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    for bad, good in {'\x91':"'",'\x92':"'",'\x93':'"','\x94':'"',
                      '\x96':'-','\x97':'-','\x95':'*','\x85':'...'}.items():
        text = text.replace(bad, good)
    return text


def parse_feed(raw_bytes):
    try:
        text = clean_xml(raw_bytes.decode("utf-8", errors="replace"))
        root = ET.fromstring(text.encode("utf-8"))
        items = root.findall(".//item")
        if items: return items
    except ET.ParseError:
        pass
    if LXML_AVAILABLE:
        try:
            parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
            root = lxml_etree.fromstring(raw_bytes, parser=parser)
            items = root.findall(".//item")
            if items: return items
        except Exception: pass
    return []


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def load_posted():
    if not os.path.exists(POSTED_FILE): return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted(key):
    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(key + "\n")


def make_key(title):
    t = title.lower()
    t = re.sub(r'\b20\d{2}\b', '', t)
    t = re.sub(r'[^a-z0-9 ]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:80]


def make_url_key(url):
    u = strip_utm(url).lower()
    u = re.sub(r'https?://(www\.)?', '', u)
    return u.rstrip('/')


def is_real_job(title, summary=""):
    tl = title.lower()
    # Block editorial/article titles first
    if is_article_not_job(title):
        return False
    combined = tl + " " + summary.lower()
    if any(k in tl for k in BAD_KEYWORDS): return False
    if not any(k in tl for k in GOOD_KEYWORDS): return False
    return any(k in combined for k in [
        "apply","application","opportunity","hiring","available",
        "2026","invited","register","programme","required","wanted","needed",
    ])


def is_real_url(url):
    if not url or not url.startswith("http"): return False
    try:
        p = urlparse(url)
        return len(p.path.rstrip("/")) >= 4 and len(url) >= 35
    except Exception: return False


def get_text(el):
    return (el.text or "").strip() if el is not None else ""


def get_item_link(item):
    link = get_text(item.find("link"))
    if is_real_url(link): return link
    d = item.find("description")
    if d is not None and d.text:
        for h in re.findall(r'href=["\']([^"\']+)["\']', unescape(d.text)):
            if is_real_url(h) and "google.com" not in h: return h
    return None


def get_item_pub_year(item):
    el = item.find("pubDate")
    if el is None: return None
    m = re.search(r'\b(20\d{2})\b', get_text(el))
    return int(m.group(1)) if m else None


def post_to_facebook(message):
    if not PAGE_TOKEN:
        print("❌ FB_PAGE_TOKEN not set."); return None
    try:
        r = requests.post(GRAPH_URL, data={
            "message": message, "access_token": PAGE_TOKEN, "published": "true",
        }, timeout=20)
        result = r.json()
        if "id" in result:
            print(f"  ✅ Posted! ID: {result['id']}"); return result["id"]
        else:
            print(f"  ❌ Failed: {result}"); return None
    except Exception as e:
        print(f"  ❌ Error: {e}"); return None


# ─────────────────────────────────────────────
# SCRAPERS
# ─────────────────────────────────────────────

def scrape_edupstairs():
    listings = []
    try:
        r = requests.get("https://www.edupstairs.org/", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  Edupstairs: HTTP {r.status_code}"); return listings
        seen = set()
        for _, link in re.findall(r'href=["\']((https?://www\.edupstairs\.org/[^"\'#?]+))["\']', r.text):
            link = link.rstrip("/")
            if any(x in link for x in ["/category/","/tag/","/page/","/author/","/feed",".jpg",".png"]): continue
            if link in seen or len(link) < 40: continue
            seen.add(link)
            m = re.search(rf'href=["\']{re.escape(link)}["\'][^>]*>\s*([^<]{{5,120}})\s*<', r.text)
            title = m.group(1).strip() if m else link.split("/")[-1].replace("-"," ").title()
            # Block articles before adding
            if is_article_not_job(title):
                print(f"    Edupstairs ✗ [ARTICLE] {title[:65]}")
                continue
            if is_real_job(title, ""):
                listings.append({"title":title[:120],"link":link,"source":"Edupstairs","pub_year":datetime.now().year})
                print(f"    Edupstairs ✔ {title[:65]}")
        print(f"  Edupstairs: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Edupstairs error: {e}")
    return listings


def scrape_kazijobs():
    listings = []
    try:
        r = requests.get("https://www.kazi-jobs.co.za/category/job-opportunies/", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  Kazi Jobs HTML: HTTP {r.status_code}"); return listings
        seen = set()
        for _, link in re.findall(r'href=["\']((https?://(?:www\.)?kazi-jobs\.co\.za/[^"\'#?]+))["\']', r.text):
            link = link.rstrip("/")
            if any(x in link for x in ["/category/","/tag/","/page/","/author/","/feed",".jpg",".png","/about","/contact"]): continue
            if link in seen or len(link) < 38: continue
            seen.add(link)
            m = re.search(rf'href=["\']{re.escape(link)}["\'][^>]*>\s*([^<]{{5,150}})\s*<', r.text)
            title = m.group(1).strip() if m else link.split("/")[-1].replace("-"," ").title()
            title = re.sub(r'<[^>]+>','',title).strip()
            if is_article_not_job(title):
                continue
            if is_real_job(title, ""):
                listings.append({"title":title[:120],"link":link,"source":"Kazi Jobs","pub_year":datetime.now().year})
                print(f"    Kazi Jobs ✔ {title[:65]}")
        print(f"  Kazi Jobs HTML: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Kazi Jobs HTML error: {e}")
    return listings


def scrape_firstjobly():
    """
    Scrape FirstJobly.co.za/jobs listing page.
    Job cards render as anchor tags in the HTML — no JS or login needed.
    Detail URLs follow: https://firstjobly.co.za/jobs/{slug-at-company}
    Detail pages have clean ## Requirements and ## About This Role sections.
    """
    listings = []
    try:
        r = requests.get("https://firstjobly.co.za/jobs", headers=HEADERS, timeout=20)
        print(f"  FirstJobly: HTTP {r.status_code}")
        if r.status_code != 200:
            return listings

        seen = set()
        # Each job card: <a href="/jobs/some-slug">...</a>
        for slug in re.findall(
            r'href=["\'](/jobs/[a-z0-9][a-z0-9\-]{5,120})["\']',
            r.text
        ):
            if slug in ("/jobs", "/jobs/"):
                continue
            link = f"https://firstjobly.co.za{slug}"
            if link in seen:
                continue
            seen.add(link)

            # Extract title from the anchor text surrounding this href
            pat = rf'href=["\']{re.escape(slug)}["\'][^>]*>([\s\S]{{5,400}}?)</a>'
            m = re.search(pat, r.text)
            if m:
                # Anchor contains: Title \n Company \n "Posted X ago..."
                # Take the first non-empty line as the title
                lines = [l.strip() for l in re.sub(r'<[^>]+>', '', m.group(1)).split('\n') if l.strip()]
                title = lines[0] if lines else ""
                # Drop "Posted X ago" noise if it bled into the first line
                title = re.sub(r'\s*Posted\s+\d+.*$', '', title, flags=re.I).strip()
            else:
                # Fallback: derive title from slug, strip "-at-company" suffix
                title = re.sub(r'-at-[a-z0-9\-]+$', '', slug.replace('/jobs/', '')).replace('-', ' ').title()

            title = smart_title(fix_abbreviations(title.strip()))
            if not title or len(title) < 5:
                continue

            if is_article_not_job(title):
                print(f"    FirstJobly ✗ [ARTICLE] {title[:65]}")
                continue
            if is_real_job(title, ""):
                listings.append({
                    "title": title[:120],
                    "link": link,
                    "source": "FirstJobly",
                    "pub_year": datetime.now().year,
                })
                print(f"    FirstJobly ✔ {title[:65]}")

        print(f"  FirstJobly: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  FirstJobly error: {e}")
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
                time.sleep(1); continue
            items = parse_feed(r.content)
            if not items:
                print(f"    ⚠️  Could not parse feed"); time.sleep(1); continue
            accepted = 0
            for item in items[:20]:
                title = unescape(get_text(item.find("title")))
                d = item.find("description")
                summary = re.sub(r"<[^>]+>","",unescape(d.text or "")) if d is not None else ""
                title = re.sub(r'\s*[|\-–]\s*[^|\-–]+$','',title).strip()
                link = get_item_link(item)
                if not link: continue
                # Block articles at RSS level too
                if is_article_not_job(title):
                    continue
                if is_real_job(title, summary):
                    all_listings.append({
                        "title":title[:120], "link":link,
                        "source":src["source"], "pub_year":get_item_pub_year(item)
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
    all_listings.extend(scrape_firstjobly())

    seen_titles, seen_urls, unique = set(), set(), []
    for j in all_listings:
        tk = make_key(j["title"])
        uk = make_url_key(j["link"])
        if tk in seen_titles or uk in seen_urls: continue
        seen_titles.add(tk); seen_urls.add(uk); unique.append(j)
    random.shuffle(unique)
    return unique


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

LAST_POSTED_FILE = "last_posted_time.txt"


def save_last_posted_time():
    with open(LAST_POSTED_FILE, "w") as f:
        f.write(datetime.now().isoformat())


def check_dry_spell():
    if not os.path.exists(LAST_POSTED_FILE):
        print("ℹ️  No last-posted record yet.\n")
        return
    try:
        with open(LAST_POSTED_FILE) as f:
            last = datetime.fromisoformat(f.read().strip())
        hours_ago = (datetime.now() - last).total_seconds() / 3600
        if hours_ago >= 24:
            print(f"⚠️  DRY SPELL WARNING: No post in {hours_ago:.0f} hours.")
            print(f"   Last posted: {last.strftime('%Y-%m-%d %H:%M')}")
            print(f"   Sources may be blocked or have no new content.\n")
        else:
            print(f"🕐 Last posted: {last.strftime('%Y-%m-%d %H:%M')} ({hours_ago:.0f}h ago)\n")
    except Exception:
        pass


def main():
    print(f"\n🤖 Kara Job Updates — Job Bot v18 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("✅ lxml" if LXML_AVAILABLE else "⚠️  no lxml")
    print("✅ BeautifulSoup\n" if BS4_AVAILABLE else "⚠️  no BeautifulSoup — plain-text fallback\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs")
    check_dry_spell()
    print("Fetching listings...\n")

    listings = fetch_all_listings()
    new_jobs = [j for j in listings if make_key(j["title"]) not in already_posted]

    print(f"\n✅ Total unique: {len(listings)}  |  🆕 New: {len(new_jobs)}\n")

    posted_count = 0

    if not new_jobs:
        print("⏸  Nothing new to post.")
        print(f"\n🏁 Run complete — 0 post(s) published.")
        return

    for listing in new_jobs:
        if posted_count >= MAX_PER_RUN: break

        key = make_key(listing["title"])
        print(f"\n📤 [{posted_count+1}/{MAX_PER_RUN}] {listing['title'][:65]}")
        print(f"   URL: {listing['link'][:80]}")
        print("   Extracting details...")

        details = extract_article_details(
            listing["link"], title=listing["title"], pub_year=listing.get("pub_year")
        )

        if details is None:
            save_posted(key); continue

        closing_obj = details.get("closing_date_obj")
        if closing_obj and closing_obj < datetime.now():
            print(f"   ❌ EXPIRED ({details.get('closing_date')}) — skipping")
            save_posted(key); continue

        post = build_post(
            title=listing["title"], details=details,
            direct_url=listing["link"], source=listing["source"]
        )

        print("\n--- POST PREVIEW ---")
        print(post)
        print("--------------------\n")

        result = post_to_facebook(post)
        if result:
            save_posted(key)
            save_last_posted_time()
            posted_count += 1
            print(f"✅ Posted {posted_count}/{MAX_PER_RUN}")
            if posted_count < MAX_PER_RUN:
                time.sleep(5)

    print(f"\n🏁 Run complete — {posted_count} post(s) published this run.")


if __name__ == "__main__":
    main()
