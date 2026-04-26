"""
Kara Job Updates — Job Bot v16
================================
CHANGES from v15:

FIX 1 — Post openers completely rewritten with 8+ varieties
  • Rotates between styles so no two posts feel the same
  • "ShopRite is hiring", "Cleaners are wanted at...",
    "They are looking for workers at...", "Good news — X has opened applications",
    "Attention job seekers — X wants you", "No experience needed at X",
    "Here is one for Grade 12 holders", etc.
  • Opener chosen based on opp_type, company, qual tier, role type
  • Never starts with "I found a learnership" every time

FIX 2 — Grammar fixed
  • Requirements truncation fixed — no more mid-sentence cuts like
    "Grade 12 and are eager to enter..."
  • Req items now cut at sentence boundaries, not mid-word

FIX 3 — No-qualification and Grade 10/11 jobs included
  • BAD_KEYWORDS no longer blocks unskilled / general roles
  • GOOD_KEYWORDS expanded for domestic, casual, contract, part-time
  • qual tier "any" now shows "No matric needed" not Grade 12

FIX 4 — Requirements: qualification always first, then others
  • If qual detected, it's pinned to position 1 in the list
  • Location pulled more aggressively (city, province, "based in")

FIX 5 — Post style variety
  • 3 closing line variations (not always "Share with someone")
  • Hashtags rotated from a pool of 15 tags, 8 picked per post
  • Emoji usage varied per post style
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
    "survey", "guide to", "what is", "celebrating",
    "top 10", "list of", "here are", "everything you need",
    "pens heartfelt", "last episode", "airs last", "smoke and mirrors",
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
    {"url": "https://learnerships.net/feed/",                             "source": "Learnerships.net"},
    {"url": "https://southafricain.com/feed/",                            "source": "South Africa In"},
    {"url": "https://www.salearnershipjobs.co.za/feed/",                  "source": "SA Learnership Jobs"},
    {"url": "https://zaboutjobs.com/feed/",                               "source": "ZA Jobs"},
    {"url": "https://www.kazi-jobs.co.za/feed/",                          "source": "Kazi Jobs"},
    {"url": "https://www.kazi-jobs.co.za/category/job-opportunies/feed/", "source": "Kazi Jobs"},
    {"url": "https://www.jobssouthafrica.co.za/feed/",                    "source": "Jobs South Africa"},
    {"url": "https://www.jobslive.co.za/feed/",                           "source": "Jobs Live"},
    {"url": "https://www.jobvine.co.za/rss/",                             "source": "Job Vine"},
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
    combined = (qual_text + " " + plain_text[:2000]).lower()

    if re.search(r'\b(bachelor|b\.?tech|btech|b tech|degree)\b', combined):
        m = re.search(
            r'(bachelor[\'s]*\s+(?:degree\s+)?in\s+[^\n\r]{5,60}|'
            r'b\.?tech\s+in\s+[^\n\r]{5,60}|degree\s+in\s+[^\n\r]{5,60})',
            combined, re.I)
        display = m.group(0).strip().rstrip('.,;') if m else "Bachelor's degree or equivalent"
        return {"tier": "degree", "display": display.capitalize()}

    if re.search(r'\b(national diploma|advanced diploma|higher certificate|'
                 r'nd in|nqf level [5-9])\b', combined):
        m = re.search(
            r'((?:national |advanced )?diploma\s+in\s+[^\n\r]{5,60}|'
            r'higher certificate\s+in\s+[^\n\r]{5,60}|nqf level [5-9][^\n\r]{0,40})',
            combined, re.I)
        display = m.group(0).strip().rstrip('.,;') if m else "National Diploma or equivalent"
        return {"tier": "diploma", "display": display.capitalize()}

    if re.search(r'\b(n[23456]|ncv|tvet|trade test|artisan)\b', combined):
        m = re.search(
            r'(n[23456]\s+[^\n\r]{0,50}|ncv[^\n\r]{0,50}|'
            r'trade test[^\n\r]{0,40}|artisan[^\n\r]{0,40})',
            combined, re.I)
        display = m.group(0).strip().rstrip('.,;') if m else "N-Certificate / NCV or equivalent"
        return {"tier": "certificate", "display": display.capitalize()}

    if re.search(r'\b(grade\s*1[02]|matric|national senior certificate|nsc)\b', combined):
        if re.search(r'\b(grade\s*1[01]|grade\s*[789]|abet)\b', combined):
            return {"tier": "grade12", "display": "Grade 10, 11, or 12"}
        return {"tier": "grade12", "display": "Grade 12 (Matric)"}

    if re.search(r'\b(no\s+(formal\s+)?qualif|unskilled|abet\s+level|no\s+experience\s+needed|'
                 r'grade\s*[89]|grade\s*1[01])\b', combined):
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
# TITLE CASING
# ─────────────────────────────────────────────

_LOWER_WORDS = {"a","an","the","and","but","or","for","nor","at","by","in","of","on","to","up","as"}

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
        if i > 0 and core.lower() in _LOWER_WORDS:
            result.append(leading + core.lower() + trailing); continue
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
# REQUIREMENTS — clean truncation at word boundary
# ─────────────────────────────────────────────

_REQ_JUNK = re.compile(
    r'^(view|apply (now|here)|contact us|for more|click|share|follow|subscribe|'
    r'read more|learn more|how to apply|about us|overview|introduction|note:|nb:)',
    re.I
)

_REQ_HEADINGS = re.compile(
    r'(minimum\s+requirements?|requirements?|eligibility|who\s+can\s+apply|'
    r'qualifications?\s+required|to\s+qualify|what\s+you\s+need)',
    re.I
)

_QUAL_SIGNALS = re.compile(
    r'(grade|matric|diploma|degree|certificate|qualification|nqf|'
    r'experience|years?|unemployed|age\s*\d|citizen|driver|licence|skills?)',
    re.I
)


def _clean_item(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[•·▪➤✔✓\-–*]\s*', '', text).strip()
    text = re.sub(r'^\d+[\.\)]\s*', '', text).strip()
    return text


def _truncate_clean(text, max_chars=80):
    """Truncate at a word boundary and add ellipsis — never mid-word."""
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

        for heading in soup.find_all(re.compile(r'^h[1-6]$|^(strong|b|p)$')):
            if _REQ_HEADINGS.search(heading.get_text(strip=True)):
                sib = heading.find_next_sibling()
                while sib:
                    if sib.name in ("ul","ol"):
                        for li in sib.find_all("li"):
                            item = _clean_item(li.get_text(separator=" ", strip=True))
                            if len(item) >= 4 and not is_junk(item) and not _REQ_JUNK.match(item):
                                items.append(item)
                        if items: break
                    if sib.name and re.match(r'^h[1-6]$', sib.name): break
                    sib = sib.find_next_sibling()
            if items: break

        if not items:
            for lst in soup.find_all(["ul","ol"]):
                if _QUAL_SIGNALS.search(lst.get_text()):
                    for li in lst.find_all("li"):
                        item = _clean_item(li.get_text(separator=" ", strip=True))
                        if len(item) >= 4 and not is_junk(item) and not _REQ_JUNK.match(item):
                            items.append(item)
                    if len(items) >= 2: break

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
            item = _clean_item(raw)
            if len(item) < 4 or is_junk(item) or _REQ_JUNK.match(item): continue
            if re.search(r'(copyright|©|\bpowered\b)', item, re.I): break
            il = item.lower()
            if il in seen: continue
            seen.add(il)
            items.append(item)

    # Sort: qualification first, then citizenship/age, then other
    def qual_priority(s):
        sl = s.lower()
        if any(w in sl for w in ['grade','matric','diploma','degree','certificate','nqf','n3','n4','n5']): return 0
        if any(w in sl for w in ['unemployed','age','citizen','south african','id']): return 1
        return 2

    items.sort(key=qual_priority)

    # Clean truncation — word boundary only
    return [_truncate_clean(item, 80) for item in items[:max_items]]


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
    ]
    for pat in [
        r'[Qq]ualification(?:s)?\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Mm]inimum\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
        r'[Rr]equired\s+[Qq]ualification\s*[:\-]\s*([^\n\r]{10,120})',
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
        r'(B\.?Tech\s+in\s+[^.\n\r]{5,60})',
        r'(NQF\s+Level\s+\d[^.\n\r]{0,40})',
        r'(N[3-6]\s+[^\n\r]{0,40})',
        r'(Trade\s+Test[^.\n\r]{0,40})',
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
    return re.sub(r'[{}\[\]<>@#=]', '', val[:120]).strip()


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
    "packer","driver","security","preparing","check","looking","how","find",
    "here","this","now","new","top","best","why","what","where","all","join",
    "learn","meet","see","register","open","about","exciting","great","latest",
    "congratulations","welcome","calling","wanted","notice","update","deadline",
}

_NOISE_SUFFIX = {
    "general","worker","workers","officer","officers","clerk","assistant",
    "manager","supervisor","technician","specialist","practitioner","analyst",
    "advisor","consultant","coordinator","engineer","supply","chain",
    "financial","corporate","senior","junior","artisan","intern","learner",
    "millwright","boilermaker","electrician","plumber","welder","fitter",
}

_OPP_TRIGGER = re.compile(
    r'\b(Learnership|Internship|Apprenticeship|Bursary|Graduate|'
    r'Vacancy|Vacancies|Programme|Program|Opportunity|Opportunities|'
    r'Trainee|Artisan|YES|Cleaner|Cleaners|General\s+Worker|General\s+Workers|'
    r'Packer|Packers|Driver|Drivers|Security\s+Guard|Labourer|Labourers|'
    r'Helper|Helpers|Porter|Porters|Gardener|Gardeners|Cashier|'
    r'Hiring|Wanted|Needed)\b',
    re.I
)


def extract_company(title):
    m = _OPP_TRIGGER.search(title)
    if not m: return ""
    candidate = title[:m.start()].strip()
    words = candidate.split()
    if not words or words[0].lower() in _NOISE_FIRST: return ""
    while words and (words[-1].lower() in _NOISE_SUFFIX or re.match(r'^20\d{2}$', words[-1])):
        words.pop()
    if not words: return ""
    company = " ".join(words[:6])
    return company if len(company) >= 2 and not company.isdigit() else ""


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

        # Location — multiple patterns, pick first clean result
        for pat in [
            r'[Ll]ocation\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,50})',
            r'[Cc]ity\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Pp]rovince\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Bb]ased\s+[Ii]n\s*[:\-]?\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'[Ww]here\s*[:\-]\s*([A-Za-z][^\n\r|,\.]{3,40})',
            r'\b(Johannesburg|Cape Town|Durban|Pretoria|Soweto|Sandton|'
            r'Ekurhuleni|Tshwane|Polokwane|Bloemfontein|Port Elizabeth|'
            r'East London|Rustenburg|Kimberley|Nelspruit|Midrand|Centurion|'
            r'Gauteng|Western Cape|KwaZulu.Natal|Limpopo|Mpumalanga|'
            r'North West|Northern Cape|Eastern Cape|Free State)\b',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip().rstrip('.,;') if m.lastindex and m.lastindex >= 1 else m.group(0).strip()
                if (2 <= len(val) <= 60
                        and not re.search(r'http|www|\.co|click|apply|salary', val, re.I)
                        and not re.search(r'[{}\[\]<>@#=;]', val)
                        and not is_junk(val)):
                    details["location"] = val
                    break

        # Qualification
        req_section = find_section(plain,
            r'[Rr]equirements?\s*[:\-]', r'[Mm]inimum\s+[Rr]equirements?\s*[:\-]',
            r'[Ee]ligibility\s*[:\-]', r'[Ww]ho\s+[Cc]an\s+[Aa]pply\s*[:\-]?',
            r'[Qq]ualifications?\s+[Rr]equired\s*[:\-]', r'[Tt]o\s+[Qq]ualify\s*[:\-]?',
        )
        qual = extract_qualification(req_section or "") or extract_qualification(plain[:3000])
        if qual: details["qualification"] = qual

        details["qual_tier"] = detect_qual_tier(qual or "", plain)

        # Top requirements — qual always pinned first
        req_items = extract_top_requirements(main_html, plain, max_items=3)
        if qual:
            qual_short = _truncate_clean(qual, 80)
            if not any(qual_short[:20].lower() in r.lower() for r in req_items):
                req_items = [qual_short] + [r for r in req_items if r != qual_short]
            req_items = req_items[:3]
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

        # Stipend
        for pat in [
            r'[Ss]tipend\s*[:\-]\s*(R\s*[\d\s,]+(?:\s*per\s+month)?)',
            r'[Ss]alary\s*[:\-]\s*(R\s*[\d\s,]+(?:\s*per\s+(?:month|annum))?)',
            r'(R\s*\d[\d\s,]*\s*(?:per\s+month|p\.?m\.?))',
        ]:
            m = re.search(pat, plain, re.I)
            if m:
                val = m.group(1).strip()[:40]
                if re.search(r'\d', val):
                    details["stipend"] = val; break

        # Opportunity type
        tl = (title + " " + plain[:200]).lower()
        if "learnership" in tl:       details["opp_type"] = "learnership"
        elif "internship" in tl:      details["opp_type"] = "internship"
        elif "apprentice" in tl:      details["opp_type"] = "apprenticeship"
        elif "bursary" in tl:         details["opp_type"] = "bursary"
        elif any(w in tl for w in ["general worker","cleaner","packer","driver",
                                    "security","warehouse","labourer","porter","gardener",
                                    "cashier","kitchen","domestic"]):
            details["opp_type"] = "job"
        else:
            details["opp_type"] = "opportunity"

        print(f"   Fields: {[k for k in details if k not in ('closing_date_obj','qual_tier','req_items')]}")
        print(f"   Qual tier: {details['qual_tier']['tier']} → {details['qual_tier']['display']}")
        print(f"   Req items: {details.get('req_items', [])}")

    except Exception as e:
        print(f"   ⚠️  Extraction error: {e}")

    return details


# ─────────────────────────────────────────────
# POST BUILDER — varied openers, human feel
# ─────────────────────────────────────────────

# Opener templates by situation
# Placeholders: {company}, {opp}, {qual}, {positions}, {role}, {location}

_OPENERS_WITH_COMPANY_GRADE12 = [
    "{company} is hiring! All you need is {qual}.",
    "Good news — {company} has opened applications for a {opp}. Matric is enough to apply.",
    "{company} wants you. {qual} is all the qualification you need.",
    "Attention job seekers — {company} is looking for people. Minimum requirement: {qual}.",
    "Here is one for Grade 12 holders. {company} is offering a {opp}.",
    "{company} has a {opp} open right now. If you have {qual}, send your application.",
    "Applications are open at {company}. You do not need experience — just {qual}.",
    "This one is for you if you have {qual}. {company} is offering a {opp}.",
]

_OPENERS_WITH_COMPANY_GRADE12_POSITIONS = [
    "{company} is looking for {positions} people. {qual} is the only requirement.",
    "{company} needs {positions} candidates for their {opp}. Apply if you have {qual}.",
    "They need {positions} people at {company}. Minimum: {qual}.",
    "{positions} spots are open at {company}. Do not sleep on this — {qual} is enough.",
]

_OPENERS_PEOPLE_ROLE_WITH_COMPANY = [
    "{role} are wanted at {company}. Apply today.",
    "{company} is looking for {role}. Check if you qualify.",
    "{role} needed at {company} — applications are open now.",
    "Calling all {role}! {company} has vacancies available.",
    "{company} has an opening for {role}. See the requirements below.",
]

_OPENERS_PEOPLE_ROLE_NO_COMPANY = [
    "{role} are needed — check the details below.",
    "There is an opening for {role}. See if you qualify.",
    "Vacancies are open for {role}. Applications welcome.",
    "{role} wanted — apply before the closing date.",
]

_OPENERS_DIPLOMA_DEGREE = [
    "If you have a {qual}, this {opp} is for you.",
    "This {opp} requires {qual}. Check the details below.",
    "Applications are open for a {opp}. Minimum requirement: {qual}.",
    "{company} is offering a {opp} for candidates with {qual}." if "{company}" else "A {opp} is available — {qual} required.",
]

_OPENERS_NO_QUAL = [
    "No matric? No problem. This one is open to everyone.",
    "You do not need any qualifications for this one. See below.",
    "This opportunity does not require a formal qualification. Anyone can apply.",
    "Open to all — no qualification needed. Check the details.",
]

_CLOSING_LINES = [
    "Share with someone who needs this 🙏",
    "Tag a friend who is looking for work 👇",
    "Pass this on — someone out there needs this opportunity.",
    "Know someone who needs a job? Share this with them. 🙌",
    "Don't keep this to yourself — tag someone who would benefit. 👇",
]


def _pick(options):
    return random.choice(options)


def _pick_hashtags(opp_type, tier):
    base = ["#KaraJobUpdates", "#JobsInSouthAfrica", "#SouthAfrica"]
    pool = [t for t in ALL_HASHTAGS if t not in base]

    if opp_type == "learnership":
        pool = ["#Learnership","#YouthEmployment","#MatricJobs","#Grade12Jobs",
                "#EntryLevelJobs","#SAJobs","#NowHiring","#JobOpportunity"]
    elif opp_type == "internship":
        pool = ["#Internship","#GraduateJobs","#YouthEmployment","#SAJobs",
                "#NowHiring","#JobOpportunity","#EntryLevelJobs","#JobAlert"]
    elif opp_type == "apprenticeship":
        pool = ["#Apprenticeship","#TradesJobs","#YouthEmployment","#SAJobs",
                "#NowHiring","#JobOpportunity","#MatricJobs","#JobAlert"]
    elif opp_type == "job":
        pool = ["#GeneralWorker","#NowHiring","#EntryLevelJobs","#NoExperienceNeeded",
                "#Grade12Jobs","#JobAlert","#SAJobs","#GautengJobs"]
    elif tier == "any":
        pool = ["#NoExperienceNeeded","#GeneralWorker","#NowHiring","#JobAlert",
                "#EntryLevelJobs","#SAJobs","#Grade10Jobs","#JobOpportunity"]

    selected = random.sample(pool, min(5, len(pool)))
    return " ".join(base + selected)


def build_post(title, details, direct_url, source):
    title = SITE_SUFFIXES.sub('', title).strip()
    title = smart_title(title)
    direct_url = strip_utm(direct_url)

    opp_type  = details.get("opp_type", "opportunity")
    location  = details.get("location", "")
    closing   = details.get("closing_date", "")
    stipend   = details.get("stipend", "")
    positions = details.get("positions", "")
    req_items = details.get("req_items", [])
    qual_tier = details.get("qual_tier", {"tier": "grade12", "display": "Grade 12 (Matric)"})

    qual_display = qual_tier["display"]
    tier         = qual_tier["tier"]
    company      = extract_company(title)

    # Detect people role
    role_match = re.search(
        r'\b(cleaners?|general\s+workers?|packers?|drivers?|security\s+guards?|'
        r'labourers?|porters?|gardeners?|warehouse\s+workers?|helpers?|cashiers?|'
        r'kitchen\s+assistants?|domestic\s+workers?)\b',
        title, re.I
    )
    is_people_role = bool(role_match)
    role_raw = role_match.group(0).strip() if role_match else ""
    role = (role_raw.title() + "s") if role_raw and not role_raw.lower().endswith('s') else role_raw.title()

    # ── Pick opener ─────────────────────────────────────────────────────
    if tier == "any":
        opener = _pick(_OPENERS_NO_QUAL)

    elif is_people_role and company:
        t = _pick(_OPENERS_PEOPLE_ROLE_WITH_COMPANY)
        opener = t.format(role=role, company=company, opp=opp_type, qual=qual_display)

    elif is_people_role:
        t = _pick(_OPENERS_PEOPLE_ROLE_NO_COMPANY)
        opener = t.format(role=role, opp=opp_type, qual=qual_display)

    elif tier in ("degree", "diploma"):
        pool = _OPENERS_DIPLOMA_DEGREE
        t = _pick(pool)
        opener = t.format(company=company, opp=opp_type, qual=qual_display,
                          positions=positions, role=role, location=location)

    elif positions and company:
        t = _pick(_OPENERS_WITH_COMPANY_GRADE12_POSITIONS)
        opener = t.format(company=company, opp=opp_type, qual=qual_display, positions=positions)

    elif company:
        t = _pick(_OPENERS_WITH_COMPANY_GRADE12)
        opener = t.format(company=company, opp=opp_type, qual=qual_display,
                          positions=positions, role=role)

    else:
        opener = f"There is a {opp_type} open right now. Minimum requirement: {qual_display}."

    lines = [opener, ""]

    # ── Requirements ─────────────────────────────────────────────────
    lines.append("Requirements:")
    if req_items:
        for item in req_items:
            lines.append(f"• {item}")
    else:
        lines.append(f"• {qual_display}")
        lines.append("• Check the advert for full details")
    lines.append("")

    # ── Details ───────────────────────────────────────────────────────
    if stipend:
        lines.append(f"💰 {stipend}")
    if location:
        lines.append(f"📍 {location}")
    else:
        lines.append("📍 Various locations across South Africa")
    lines.append(f"📅 Closing date: {closing if closing else 'See advert'}")
    lines.append("")

    # ── Apply ─────────────────────────────────────────────────────────
    lines.append("Apply here 👇")
    lines.append(direct_url)
    lines.append("")

    # ── Closing line (varied) ─────────────────────────────────────────
    lines.append(_pick(_CLOSING_LINES))
    lines.append("")

    # ── Hashtags (rotated) ────────────────────────────────────────────
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
            if is_real_job(title, ""):
                listings.append({"title":title[:120],"link":link,"source":"Kazi Jobs","pub_year":datetime.now().year})
                print(f"    Kazi Jobs ✔ {title[:65]}")
        print(f"  Kazi Jobs HTML: {len(listings)} relevant listings")
    except Exception as e:
        print(f"  Kazi Jobs HTML error: {e}")
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

def main():
    print(f"\n🤖 Kara Job Updates — Job Bot v16 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("✅ lxml" if LXML_AVAILABLE else "⚠️  no lxml")
    print("✅ BeautifulSoup\n" if BS4_AVAILABLE else "⚠️  no BeautifulSoup — plain-text fallback\n")

    already_posted = load_posted()
    print(f"📋 Already posted: {len(already_posted)} jobs\n")
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
            posted_count += 1
            print(f"✅ Posted {posted_count}/{MAX_PER_RUN}")
            if posted_count < MAX_PER_RUN:
                time.sleep(5)

    print(f"\n🏁 Run complete — {posted_count} post(s) published this run.")


if __name__ == "__main__":
    main()
