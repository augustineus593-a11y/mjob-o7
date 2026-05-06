#!/usr/bin/env python3
"""
Kara Job Updates — post_jobs.py  v19
Facebook auto-poster for Vuka Sizame Hub.

What changed in v19:
  - Post intro is now a faithful 2–3 sentence SUMMARY of the actual advert
    (no more random template openers — matches the manually-edited screenshot style)
  - Requirements list is extracted more aggressively (up to 6 items)
  - plain_text is stored on details dict and passed to build_post()
  - All _OPENERS_* lists and extract_role_description() removed (no longer needed)
  - Everything else (RSS fetch, dedup, Facebook posting, GitHub Actions) unchanged
"""

import os, re, time, random, requests
from datetime import datetime
from html import unescape
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import xml.etree.ElementTree as ET

try:
    from lxml import etree as lxml_etree
    LXML_AVAILABLE = True
    print("✅ lxml")
except ImportError:
    LXML_AVAILABLE = False
    print("⚠️  no lxml")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
    print("✅ BeautifulSoup\n")
except ImportError:
    BS4_AVAILABLE = False
    print("⚠️  no BeautifulSoup — plain-text fallback\n")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PAGE_ID    = os.environ.get("FB_PAGE_ID", "")
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
GRAPH_URL  = f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed"
POSTED_FILE = "posted.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-ZA,en;q=0.9",
}

GOOD_KEYWORDS = [
    "learnership", "internship", "apprenticeship", "bursary",
    "graduate", "trainee", "vacancy", "vacancies", "hiring",
    "programme", "program", "opportunity", "opportunities",
    "general worker", "cleaners", "packers", "drivers",
    "yes programme", "yes program", "work experience",
    "apply now", "applications open", "applications are open",
]

BAD_KEYWORDS = [
    "how to write", "tips for", "cv tips", "interview tips",
    "top 10", "top 5", "best ways", "everything you need to know",
    "what is a learnership", "difference between",
    "why you should", "benefits of", "guide to",
]


def is_article_not_job(title):
    tl = title.lower()
    article_patterns = [
        r'^(how|why|what|when|where|who|top\s+\d|best\s+\d|\d+\s+ways)',
        r'(tips?|guide|advice|explained|everything\s+you|difference\s+between)',
        r'(hidden\s+opportunities|most\s+youth\s+are\s+missing)',
        r'^is\s+',
    ]
    return any(re.search(p, tl) for p in article_patterns)


RSS_SOURCES = [
    {"url": "https://www.salearnership.co.za/feed/",                      "source": "SA Learnership"},
    {"url": "https://learnerships24.co.za/feed/",                         "source": "Learnerships24"},
    {"url": "https://youthvillage.co.za/feed/",                           "source": "Youth Village SA"},
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

_FORCE_UPPER = {
    "ncv","wil","ict","nqf","tvet","seta","nyda","sa","hr","it","ai","hiv","tb",
    "nsc","fet","nsfas","dhet","uif","sars","saps","sandf","narysec","bocma",
    "eastc","apx","var",
}

def fix_abbreviations(text):
    """Fix common abbreviations to proper casing."""
    fixes = {
        r'\bSa\b': 'SA', r'\bNqf\b': 'NQF', r'\bTvet\b': 'TVET',
        r'\bSeta\b': 'SETA', r'\bNcv\b': 'NCV', r'\bWil\b': 'WIL',
        r'\bIct\b': 'ICT', r'\bHr\b': 'HR', r'\bIt\b': 'IT',
        r'\bAi\b': 'AI', r'\bHiv\b': 'HIV', r'\bTb\b': 'TB',
        r'\bNsc\b': 'NSC', r'\bFet\b': 'FET', r'\bNsfas\b': 'NSFAS',
        r'\bDhet\b': 'DHET', r'\bUif\b': 'UIF', r'\bSars\b': 'SARS',
        r'\bSaps\b': 'SAPS', r'\bNarysec\b': 'NARYSEC',
        r'\bSwgc\b': 'SWGC', r'\bMict\b': 'MICT',
        r'\bWr\b': 'WR', r'\bFoodbev\b': 'FoodBev',
    }
    for pat, rep in fixes.items():
        text = re.sub(pat, rep, text)
    return text


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
        if len(alpha) >= 2 and alpha == alpha.upper():
            result.append(word); continue
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
# REQUIREMENTS EXTRACTION
# ─────────────────────────────────────────────

_NOT_REQ = re.compile(
    r'^(is\s+|are\s+|can\s+i\s+|do\s+i\s+|will\s+i\s+|does\s+|'
    r'what\s+(is|are|this|happens|does)|why\s+|how\s+(do|does|to|can)|'
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

_REQ_SIGNAL = re.compile(
    r'(grade|matric|diploma|degree|certificate|nqf|ncv|n3|n4|n5|n6|'
    r'years?\s+of\s+experience|years?\s+experience|experience|'
    r'unemployed|age\s*\d|\d+\s*[-–]\s*\d+\s*years?|'
    r'south\s+african\s+citizen|citizen|valid\s+id|id\s+document|'
    r'driver[\'s]?\s+licen[sc]e|licence|computer\s+(literate|skills?)|'
    r'reside|resident|living\s+in|based\s+in|municipality|'
    r'must\s+(be|have|hold)|you\s+(must|need\s+to|should\s+have)|'
    r'minimum|required|essential|advantageous|stipend|affidavit|'
    r'bank\s+(account|confirmation)|proof\s+of|certified\s+copy|'
    r'not\s+(currently\s+)?employed|no\s+(criminal|previous)|'
    r'physically\s+fit|own\s+transport|bilingual|fluent|proficient)',
    re.I
)

_REQ_HEADINGS = re.compile(
    r'(minimum\s+requirements?|requirements?|eligibility|who\s+can\s+apply|'
    r'qualifications?\s+required|to\s+qualify|what\s+you\s+need|'
    r'essential\s+requirements?|advantageous|documents?\s+required|'
    r'documents?\s+needed)',
    re.I
)


def _clean_req_item(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[•·▪➤✔✓\-–*]\s*', '', text).strip()
    text = re.sub(r'^\d+[\.\)]\s*', '', text).strip()
    return fix_abbreviations(text)


def _is_valid_req(item):
    if len(item) < 5:
        return False
    if is_junk(item):
        return False
    if item.endswith('?'):
        return False
    if _NOT_REQ.match(item):
        return False
    if not _REQ_SIGNAL.search(item):
        if not re.match(r'^(must\s+|you\s+must\s+|applicants?\s+must\s+)', item, re.I):
            return False
    return True


def _truncate_at_word(text, max_chars=90):
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(' ', 1)[0].rstrip('.,;:')
    return cut + "…"


def extract_top_requirements(html_content, plain_text, max_items=6):
    """
    Extract up to max_items real requirement lines from the advert.
    Increased to 6 to capture full requirement lists like in the screenshots.
    """
    items = []

    if BS4_AVAILABLE:
        soup = BeautifulSoup(html_content, "lxml" if LXML_AVAILABLE else "html.parser")
        for t in soup(["nav","footer","header","script","style"]):
            t.decompose()

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

        if not items:
            for lst in soup.find_all(["ul","ol"]):
                if _REQ_SIGNAL.search(lst.get_text()):
                    for li in lst.find_all("li"):
                        raw = _clean_req_item(li.get_text(separator=" ", strip=True))
                        if _is_valid_req(raw):
                            items.append(raw)
                    if len(items) >= 2:
                        break

    if not items:
        section = find_section(
            plain_text,
            r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s*[:\-]',
            r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
            r'[Dd]ocuments?\s+[Rr]equired\s*[:\-]',
            r'[Dd]ocuments?\s+[Nn]eeded\s*[:\-]',
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

    def qual_priority(s):
        sl = s.lower()
        if any(w in sl for w in ['grade','matric','diploma','degree','certificate','nqf','ncv','n3','n4','n5','n6']):
            return 0
        if any(w in sl for w in ['unemployed','age','citizen','south african','id','status']):
            return 1
        if any(w in sl for w in ['document','cv','certified','affidavit','bank','proof']):
            return 2
        return 3

    items.sort(key=qual_priority)
    return [_truncate_at_word(item, 90) for item in items[:max_items]]


# ─────────────────────────────────────────────
# QUALIFICATION EXTRACTION
# ─────────────────────────────────────────────

def extract_qualification(text):
    QUAL_NOUNS = [
        'grade 12','grade12','grade 11','grade 10','matric','national senior certificate',
        'national certificate','national diploma','higher certificate',
        'advanced diploma','bachelor','b.tech','btech','b tech',
        'degree','diploma','nqf level','nqf','abet','fet',
        'trade test','artisan','certificate','n3','n4','n5','n6',
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
# COMPANY NAME EXTRACTION
# ─────────────────────────────────────────────

_NOISE_FIRST = {
    "learnership","internship","apprenticeship","bursary","vacancy","vacancies",
    "opportunity","opportunities","programme","program","graduate","trainee",
    "yes","general","worker","workers","officer","officers","cleaner","cleaners",
    "packer","packers","driver","drivers","security","preparing","check","looking","how",
    "find","here","this","now","new","top","best","why","what","where","all","join",
    "learn","meet","see","register","open","about","exciting","great","latest",
    "congratulations","welcome","calling","wanted","notice","update","deadline",
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

_KNOWN_COMPANIES = re.compile(
    r'\b(Dis[- ]?Chem(?:\s+Pharmacies)?|Pick\s+n\s+Pay|Shoprite\s+Checkers?|'
    r'Old\s+Mutual|Rand\s+Water|Kimberly\s+Clark|Northlink\s+College|'
    r'West\s+Coast\s+TVET\s+College|Sasol|Takealot|Paracon|Vodacom|'
    r'Feltex\s+Shipping|APX\s+Security|National\s+Rural\s+Youth\s+Service\s+Corps|'
    r'NARYSEC|BOCMA|EASTC|Department\s+of\s+[A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)?|'
    r'SASSA|NECSA|Samancor|Motus|Adidas|Cashbuild|Kia\s+(?:SA|South\s+Africa)|'
    r'South\s+West\s+Gauteng\s+TVET\s+College|SWGC|Transnet|Eskom|Telkom|'
    r'Foschini|TFG|BCE\s+Food\s+Service|Umuzi|Kimberly\s+Clark|'
    r'Department\s+of\s+Water\s+and\s+Sanitation|SAPS|SANDF)\b',
    re.I
)


def extract_company(title):
    m = _KNOWN_COMPANIES.search(title)
    if m:
        return fix_abbreviations(m.group(0).strip())
    m = _OPP_TRIGGER.search(title)
    if not m: return ""
    candidate = title[:m.start()].strip()
    words = candidate.split()
    if not words or words[0].lower() in _NOISE_FIRST: return ""
    while words and (words[-1].lower() in _NOISE_SUFFIX or re.match(r'^20\d{2}$', words[-1])):
        words.pop()
    if not words: return ""
    if words[0].lower() in _NOISE_FIRST: return ""
    company = " ".join(words[:6])
    return fix_abbreviations(company) if len(company) >= 2 and not company.isdigit() else ""


# ─────────────────────────────────────────────
# LOCATION VALIDATION
# ─────────────────────────────────────────────

_VALID_LOCATION = re.compile(
    r'\b(Johannesburg|Cape\s+Town|Durban|Pretoria|Soweto|Sandton|'
    r'Ekurhuleni|Tshwane|Polokwane|Bloemfontein|Port\s+Elizabeth|Gqeberha|'
    r'East\s+London|Rustenburg|Kimberley|Nelspruit|Midrand|Centurion|'
    r'Sasolburg|Secunda|Welkom|Vanderbijlpark|Vereeniging|Alberton|Benoni|'
    r'Boksburg|Roodepoort|Krugersdorp|Mpumalanga|Limpopo|Gauteng|Florida|'
    r'Western\s+Cape|KwaZulu[- ]Natal|North\s+West|Northern\s+Cape|'
    r'Eastern\s+Cape|Free\s+State|South\s+Africa|Molapo|George\s+Tabor)\b',
    re.I
)

_JUNK_LOCATION = re.compile(
    r'^(specific|various|see\s+advert|multiple|nationwide|country[- ]?wide|'
    r'tbd|to\s+be\s+confirmed|n/?a|not\s+specified|'
    r'a\s+busy|retail|pharmacy|environment|office|workplace)',
    re.I
)


def clean_location(val):
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
    if _VALID_LOCATION.search(val):
        return val
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
            r'[Cc]ampus(?:es)?\s*[:\-]?\s*([A-Za-z][^\n\r|,\.]{3,80})',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                candidate = clean_location(m.group(1))
                if candidate:
                    raw_loc = candidate
                    break

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

        # Requirements — up to 6 items to match full advert lists
        tier = details["qual_tier"]["tier"]
        req_items = extract_top_requirements(main_html, plain, max_items=6)

        if qual:
            qual_short = _truncate_at_word(qual, 90)
            if not any(qual_short[:20].lower() in r.lower() for r in req_items):
                req_items = [qual_short] + [r for r in req_items if r != qual_short]

        req_items = _filter_req_by_tier(req_items, tier)[:6]
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

        # Store plain_text for use in build_post intro summary
        details["plain_text"] = plain

        print(f"   Fields: {[k for k in details if k not in ('closing_date_obj','qual_tier','req_items','plain_text')]}")
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
        if re.search(r'\b(and|or|with|who|that|where|when|as|but)\s*[…]?\s*$', il):
            continue
        filtered.append(item)
    return filtered if filtered else req_items


# ─────────────────────────────────────────────
# INTRO SUMMARISER
# Produces a faithful 2–3 sentence summary from the actual advert body.
# This matches the screenshot style: what the programme is, who runs it,
# what it offers — NOT a randomly picked template.
# ─────────────────────────────────────────────

def build_intro_summary(plain_text, title, opp_type, company, qual_display, location=""):
    """
    Extract a clean 2–3 sentence intro directly from the advert body.
    Falls back to a factual constructed sentence if nothing usable found.
    """
    # Try to find a genuine descriptive paragraph near the top of the article
    paragraphs = re.split(r'\n{2,}', plain_text[:5000])
    candidates = []
    for para in paragraphs[:15]:
        para = re.sub(r'\s+', ' ', para).strip()
        if len(para) < 50 or len(para) > 700:
            continue
        # Skip headings, requirement sections, bullet lines, navigation
        if re.match(
            r'^(requirements?|qualification|how to apply|about|overview|'
            r'documents?|closing|apply|location|note:|nb:|duties|'
            r'responsibilities|contact|benefits?|stipend)',
            para, re.I
        ):
            continue
        if para.lstrip().startswith(('•', '✅', '✔', '-', '*', '–')):
            continue
        if is_junk(para):
            continue
        # Must contain a descriptive verb — signs of a real programme description
        if re.search(
            r'\b(is|are|offers?|provides?|invit|open|accept|design|aim|equip|'
            r'allow|enable|give|gain|earn|require|seek|looking|currently|'
            r'partnership|initiative|programme|intended|targeted|eligible|'
            r'opportunity|experience|practical|workplace|stipend|training)\b',
            para, re.I
        ):
            candidates.append(para)

    if candidates:
        # Pick the most informative candidate (longest under 500 chars)
        best = max(
            (c for c in candidates if len(c) <= 500),
            key=len,
            default=candidates[0]
        )
        # Limit to 3 sentences
        sentences = re.split(r'(?<=[.!?])\s+', best.strip())
        intro = ' '.join(sentences[:3]).strip()
        if len(intro) >= 60:
            return fix_abbreviations(intro)

    # Fallback: construct a factual sentence from known fields
    opp_label = {
        "learnership":    "Learnership",
        "internship":     "Internship Programme",
        "apprenticeship": "Apprenticeship",
        "bursary":        "Bursary",
        "job":            "Vacancy",
    }.get(opp_type, "Opportunity")

    if company and company.lower() not in ("this company",):
        intro = f"Applications are open for the {company} {opp_label} for {CURRENT_YEAR}."
    else:
        intro = f"A {opp_label} is currently open for applications for {CURRENT_YEAR}."

    if qual_display and "matric" not in qual_display.lower():
        intro += f" Minimum qualification: {qual_display}."
    else:
        intro += " No prior experience required — Matric is enough to apply."

    return intro


# ─────────────────────────────────────────────
# HASHTAG PICKER
# ─────────────────────────────────────────────

def _pick_hashtags(opp_type, tier):
    base = ["#KaraJobUpdates", "#JobsInSouthAfrica", "#SouthAfrica"]
    if opp_type == "learnership":
        pool = ["#Learnership", "#YouthEmployment", "#MatricJobs", "#Grade12Jobs",
                "#EntryLevelJobs", "#SAJobs", "#NowHiring", "#JobOpportunity"]
    elif opp_type == "internship":
        pool = ["#YouthEmployment", "#NowHiring", "#JobAlert", "#EntryLevelJobs",
                "#Internship", "#JobOpportunity", "#SAJobs", "#NowHiring"]
    elif opp_type == "apprenticeship":
        pool = ["#Apprenticeship", "#YouthEmployment", "#SAJobs",
                "#NowHiring", "#JobOpportunity", "#MatricJobs", "#JobAlert", "#EntryLevelJobs"]
    elif opp_type == "job":
        pool = ["#JobAlert", "#Grade10Jobs", "#GeneralWorker",
                "#MatricJobs", "#NowHiring", "#EntryLevelJobs", "#SAJobs", "#NowHiring"]
    elif tier == "degree":
        pool = ["#YouthEmployment", "#GraduateJobs", "#NowHiring",
                "#JobOpportunity", "#SAJobs", "#Internship", "#EntryLevelJobs"]
    else:
        pool = ["#YouthEmployment", "#NowHiring", "#JobAlert", "#EntryLevelJobs",
                "#Learnership", "#MatricJobs", "#SAJobs", "#JobOpportunity"]
    selected = random.sample(pool, min(5, len(pool)))
    return " ".join(base + selected)


_CLOSING_LINES = [
    "Know someone without a job? Send this to them. 🙌",
    "Share with someone who needs this. 🙏",
    "Tag a friend who is looking for work. 👇",
    "If this is not for you, share it with someone it is for. 🙏",
    "Pass this on — someone out there is waiting for this opportunity.",
    "Do not keep this to yourself. Tag someone who needs it. 👇",
    "Someone in your circle needs to see this. Share it.",
]


# ─────────────────────────────────────────────
# POST BUILDER — faithful advert summary style
#
# Matches your screenshot structure exactly:
#
#   🚨🎯 [2–3 sentence summary from the actual advert body]
#
#   Requirements:
#   ✅ Requirement 1
#   ✅ Requirement 2
#   ✅ Requirement 3  (up to 6 items)
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
# ─────────────────────────────────────────────

def build_post(title, details, direct_url, source, plain_text=""):
    title = SITE_SUFFIXES.sub('', title).strip()
    title = smart_title(title)
    direct_url = strip_utm(direct_url)

    opp_type     = details.get("opp_type", "opportunity")
    location     = details.get("location", "")
    closing      = details.get("closing_date", "")
    req_items    = details.get("req_items", [])
    qual_tier    = details.get("qual_tier", {"tier": "grade12", "display": "Grade 12 (Matric)"})

    qual_display = qual_tier["display"]
    tier         = qual_tier["tier"]
    company      = extract_company(title)

    # ── Intro: 2–3 sentences sourced from the actual advert body ─────────
    intro = build_intro_summary(
        plain_text=plain_text,
        title=title,
        opp_type=opp_type,
        company=company,
        qual_display=qual_display,
        location=location,
    )

    # ── Assemble post ────────────────────────────────────────────────────
    lines = [f"🚨🎯 {intro}"]
    lines.append("")

    lines.append("Requirements:")
    if req_items:
        for item in req_items:
            lines.append(f"✅ {item}")
    else:
        lines.append(f"✅ {qual_display}")
        lines.append("✅ Check the advert for full details")

    lines.append("")

    if location:
        lines.append(f"📍 {location}")
    lines.append(f"📅 Closing date: {closing if closing else 'See advert'}")
    lines.append("")

    lines.append("Apply here 👇")
    lines.append(direct_url)
    lines.append("")

    lines.append(random.choice(_CLOSING_LINES))
    lines.append("")

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
    listings = []
    try:
        r = requests.get("https://firstjobly.co.za/jobs", headers=HEADERS, timeout=20)
        print(f"  FirstJobly: HTTP {r.status_code}")
        if r.status_code != 200:
            return listings

        seen = set()
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

            pat = rf'href=["\']{re.escape(slug)}["\'][^>]*>([\s\S]{{5,400}}?)</a>'
            m = re.search(pat, r.text)
            if m:
                lines = [l.strip() for l in re.sub(r'<[^>]+>', '', m.group(1)).split('\n') if l.strip()]
                title = lines[0] if lines else ""
                title = re.sub(r'\s*Posted\s+\d+.*$', '', title, flags=re.I).strip()
            else:
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
    print(f"\n🤖 Kara Job Updates — Job Bot v19 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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
            title=listing["title"],
            details=details,
            direct_url=listing["link"],
            source=listing["source"],
            plain_text=details.get("plain_text", ""),
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
