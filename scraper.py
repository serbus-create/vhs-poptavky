"""
VHS. Mezinárodní poptávkový hlídač
====================================
Kreativní agentura vhs. (v-h-s.cz) – design, video, foto, branding
Sleduje poptávky zakázek na 6 trzích: CZ · SK · PL · AT · DE · US · HU

Spouštění:   python scraper.py
Automaticky: GitHub Actions každé 2h (Po–Pá)
"""

import json
import os
import smtplib
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# KONFIGURACE
# ──────────────────────────────────────────────
EMAIL_FROM     = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO       = os.getenv("EMAIL_TO", "info@v-h-s.cz")
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "587"))

SEEN_FILE = Path("seen_ids.json")

# ──────────────────────────────────────────────
# KLÍČOVÁ SLOVA podle jazyka
# Pro filtrování relevantních poptávek
# ──────────────────────────────────────────────
KEYWORDS_BY_LANG = {
    "cs": [
        "grafika", "grafický", "logo", "vizuál", "branding", "brand",
        "video", "reklama", "reklamní", "fotograf", "focení", "foto",
        "web", "webové", "tisk", "polep", "kampaň", "marketing",
        "ilustrace", "animace", "design", "leták", "banner", "sociální sítě",
    ],
    "sk": [
        "grafika", "grafický", "logo", "vizuál", "branding",
        "video", "reklama", "reklamný", "fotograf", "fotenie", "foto",
        "web", "webové", "tlač", "polep", "kampaň", "marketing",
        "ilustrácia", "animácia", "dizajn", "leták", "banner",
    ],
    "pl": [
        "grafika", "graficzny", "logo", "identyfikacja", "branding",
        "wideo", "video", "reklama", "reklamowy", "fotograf", "zdjęcia", "foto",
        "strona", "strona www", "druk", "kampania", "marketing",
        "ilustracja", "animacja", "design", "ulotka", "baner",
    ],
    "de": [
        "grafik", "logo", "branding", "corporate", "design",
        "video", "werbung", "fotograf", "fotografie", "foto",
        "webseite", "website", "druck", "kampagne", "marketing",
        "illustration", "animation", "flyer", "banner", "social media",
        "werbeagentur", "kreativ", "bildbearbeitung",
    ],
    "en": [
        "graphic design", "logo", "branding", "brand identity",
        "video production", "advertising", "photographer", "photography",
        "website", "web design", "print", "campaign", "marketing",
        "illustration", "animation", "flyer", "banner", "social media",
        "creative agency", "visual", "motion graphics", "content creation",
    ],
    "hu": [
        "grafika", "logó", "branding", "arculat", "design",
        "videó", "reklám", "fotós", "fotózás", "foto",
        "weboldal", "web", "nyomtatás", "kampány", "marketing",
        "illusztráció", "animáció", "szórólap", "banner",
    ],
}

# ──────────────────────────────────────────────
# ZDROJE POPTÁVEK – všechny trhy
# ──────────────────────────────────────────────
#
# Struktura každého zdroje:
# {
#   "name": str,          # název platformy
#   "market": str,        # zkratka trhu (CZ, SK, DE…)
#   "flag": str,          # emoji vlajka
#   "lang": str,          # kód jazyka pro filtrování klíčových slov
#   "type": str,          # "html" nebo "rss"
#   "urls": list[tuple],  # (kategorie, url)
#   "price_note": str,    # poznámka o cenové výhodě (volitelné)
# }
#
SOURCES = [

    # ── ČESKO ──────────────────────────────────────────────────────────────
    {
        "name": "ePoptávka.cz",
        "market": "CZ", "flag": "🇨🇿", "lang": "cs", "type": "html",
        "urls": [
            ("Grafika a reklama",      "https://poptavky.epoptavka.cz/grafika-reklamni-sluzby"),
            ("Foto a video",           "https://poptavky.epoptavka.cz/fotografie-a-video"),
            ("Web a e-shopy",          "https://poptavky.epoptavka.cz/tvorba-webu-a-e-shopu"),
            ("Tisk a polygrafie",      "https://poptavky.epoptavka.cz/tisk-a-polygrafie"),
            ("Marketing a reklama",    "https://poptavky.epoptavka.cz/marketing-a-reklama"),
        ],
    },
    {
        "name": "Navolnenoze.cz",
        "market": "CZ", "flag": "🇨🇿", "lang": "cs", "type": "html",
        "urls": [
            ("Grafika / Reklama",      "https://navolnenoze.cz/hledam/?obor=grafika-reklama"),
            ("Foto / Video",           "https://navolnenoze.cz/hledam/?obor=foto-video"),
        ],
    },
    # Google Alerts RSS – CZ (nastavte si vlastní URL z google.com/alerts)
    # {
    #   "name": "Google Alerts CZ",
    #   "market": "CZ", "flag": "🇨🇿", "lang": "cs", "type": "rss",
    #   "urls": [("Poptávky", "https://www.google.com/alerts/feeds/TVOJE_ID/TOKEN")],
    # },

    # ── SLOVENSKO ──────────────────────────────────────────────────────────
    {
        "name": "Freelancer.sk",
        "market": "SK", "flag": "🇸🇰", "lang": "sk", "type": "html",
        "urls": [
            ("Grafika a dizajn",       "https://www.freelancer.sk/projekty/grafika-dizajn/"),
            ("Video a animácie",       "https://www.freelancer.sk/projekty/video-animacie/"),
            ("Fotografia",             "https://www.freelancer.sk/projekty/fotografia/"),
            ("Web design",             "https://www.freelancer.sk/projekty/web-dizajn/"),
            ("Marketing",              "https://www.freelancer.sk/projekty/marketing/"),
        ],
    },
    {
        "name": "Profesia.sk (brigády/grafika)",
        "market": "SK", "flag": "🇸🇰", "lang": "sk", "type": "html",
        "urls": [
            ("Grafik/Designer",        "https://www.profesia.sk/praca/grafik/"),
            ("Marketingový špecialista","https://www.profesia.sk/praca/marketingovy-specialista/"),
        ],
    },

    # ── POLSKO ─────────────────────────────────────────────────────────────
    {
        "name": "Useme.com (PL)",
        "market": "PL", "flag": "🇵🇱", "lang": "pl", "type": "html",
        "urls": [
            ("Grafika i design",       "https://useme.com/pl/roles/graphic-designer/"),
            ("Video i animacje",       "https://useme.com/pl/roles/video-maker/"),
            ("Fotografia",             "https://useme.com/pl/roles/photographer/"),
            ("Strony www",             "https://useme.com/pl/roles/web-designer/"),
        ],
    },
    {
        "name": "Freelancermap.pl",
        "market": "PL", "flag": "🇵🇱", "lang": "pl", "type": "html",
        "urls": [
            ("Design/Grafika",         "https://www.freelancermap.pl/oferty-pracy/grafik"),
            ("Marketing",              "https://www.freelancermap.pl/oferty-pracy/marketing"),
        ],
    },

    # ── RAKOUSKO ───────────────────────────────────────────────────────────
    # Cenová výhoda: CZ ceny vs. AT platový standard = silná konkurenční pozice
    {
        "name": "Freelancer.at",
        "market": "AT", "flag": "🇦🇹", "lang": "de", "type": "html",
        "price_note": "💰 Cenová výhoda AT/DE",
        "urls": [
            ("Grafik & Design",        "https://www.freelancer.at/projekte/grafik-design/"),
            ("Video & Animation",      "https://www.freelancer.at/projekte/video-animation/"),
            ("Fotografie",             "https://www.freelancer.at/projekte/fotografie/"),
            ("Marketing",              "https://www.freelancer.at/projekte/marketing/"),
        ],
    },
    {
        "name": "Gulp.at",
        "market": "AT", "flag": "🇦🇹", "lang": "de", "type": "html",
        "price_note": "💰 Cenová výhoda AT/DE",
        "urls": [
            ("Grafik/Design AT",       "https://www.gulp.at/stellenmarkt/freiberufler/?keyword=grafik"),
            ("Marketing AT",           "https://www.gulp.at/stellenmarkt/freiberufler/?keyword=marketing"),
        ],
    },

    # ── NĚMECKO ────────────────────────────────────────────────────────────
    {
        "name": "Freelancermap.de",
        "market": "DE", "flag": "🇩🇪", "lang": "de", "type": "html",
        "price_note": "💰 Cenová výhoda AT/DE",
        "urls": [
            ("Grafik & Design",        "https://www.freelancermap.de/projektboerse/grafik-design"),
            ("Video & Animation",      "https://www.freelancermap.de/projektboerse/video-animation"),
            ("Marketing",              "https://www.freelancermap.de/projektboerse/marketing"),
            ("Fotografie",             "https://www.freelancermap.de/projektboerse/fotografie"),
        ],
    },
    {
        "name": "Twago.de",
        "market": "DE", "flag": "🇩🇪", "lang": "de", "type": "html",
        "price_note": "💰 Cenová výhoda AT/DE",
        "urls": [
            ("Design DE",              "https://www.twago.de/search/?q=grafik+design&type=project"),
            ("Video DE",               "https://www.twago.de/search/?q=video+produktion&type=project"),
        ],
    },

    # ── USA ────────────────────────────────────────────────────────────────
    # Cenová výhoda: USD sazby vs. CZ náklady = velmi silná pozice pro remote projekty
    {
        "name": "Upwork (EN)",
        "market": "US", "flag": "🇺🇸", "lang": "en", "type": "rss",
        "price_note": "💰💰 Nejsilnější cenová výhoda",
        "urls": [
            # Upwork má veřejné RSS pro hledání projektů
            ("Graphic Design",
             "https://www.upwork.com/ab/feed/jobs/rss?q=graphic+design&sort=recency&paging=0%3B10"),
            ("Video Production",
             "https://www.upwork.com/ab/feed/jobs/rss?q=video+production&sort=recency&paging=0%3B10"),
            ("Logo & Branding",
             "https://www.upwork.com/ab/feed/jobs/rss?q=logo+branding&sort=recency&paging=0%3B10"),
            ("Photography",
             "https://www.upwork.com/ab/feed/jobs/rss?q=photography+product&sort=recency&paging=0%3B10"),
            ("Social Media Content",
             "https://www.upwork.com/ab/feed/jobs/rss?q=social+media+content+design&sort=recency&paging=0%3B10"),
            ("Marketing Creative",
             "https://www.upwork.com/ab/feed/jobs/rss?q=marketing+creative+agency&sort=recency&paging=0%3B10"),
        ],
    },
    {
        "name": "PeoplePerHour (EN)",
        "market": "US", "flag": "🇺🇸", "lang": "en", "type": "rss",
        "price_note": "💰💰 Nejsilnější cenová výhoda",
        "urls": [
            ("Design & Art",
             "https://www.peopleperhour.com/freelance-jobs/design-art.rss"),
            ("Photography",
             "https://www.peopleperhour.com/freelance-jobs/photography.rss"),
            ("Video & Animation",
             "https://www.peopleperhour.com/freelance-jobs/video-animation.rss"),
        ],
    },

    # ── MAĎARSKO ───────────────────────────────────────────────────────────
    {
        "name": "Freelancer.hu",
        "market": "HU", "flag": "🇭🇺", "lang": "hu", "type": "html",
        "urls": [
            ("Grafika és dizájn",      "https://www.freelancer.hu/projektek/grafika-dizajn/"),
            ("Videó és animáció",      "https://www.freelancer.hu/projektek/video-animacio/"),
            ("Marketing",              "https://www.freelancer.hu/projektek/marketing/"),
        ],
    },
    {
        "name": "Logout.hu (pályázatok)",
        "market": "HU", "flag": "🇭🇺", "lang": "hu", "type": "html",
        "urls": [
            ("Kreatív munkák HU",      "https://logout.hu/allasok/?kategoria=grafikus"),
        ],
    },
]

# ──────────────────────────────────────────────
# HTTP Session
# ──────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,cs;q=0.8,de;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def get_page(session, url, label):
    try:
        base = "/".join(url.split("/")[:3])
        try:
            session.get(base, timeout=8)
        except Exception:
            pass
        time.sleep(1.0)
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log(f"  ⚠️  {label}: {e}")
        return None


# ──────────────────────────────────────────────
# RSS Parser
# ──────────────────────────────────────────────
def parse_rss(session, feed_url, source_name, category, market, flag, price_note="") -> list[dict]:
    leads = []
    try:
        r = session.get(feed_url, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log(f"  ⚠️  RSS {source_name} / {category}: {e}")
        return leads

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//entry") or root.findall(".//atom:entry", ns)

    for item in items:
        def txt(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        title = txt("title") or ""
        link  = txt("link") or txt("guid") or ""
        desc  = txt("description") or txt("summary") or ""
        date  = txt("pubDate") or txt("published") or ""

        if not link or not title:
            continue

        uid = f"{market.lower()}-rss-" + link.strip("/").split("/")[-1][-30:]
        leads.append({
            "id": uid, "source": source_name, "market": market, "flag": flag,
            "category": category, "title": title,
            "date": date[:16], "region": "", "price_note": price_note,
            "desc": BeautifulSoup(desc, "html.parser").get_text()[:400],
            "url": link,
        })

    log(f"  ✓ {flag} {source_name} / {category}: {len(leads)}")
    return leads


# ──────────────────────────────────────────────
# HTML Scraper (generický)
# ──────────────────────────────────────────────
def scrape_html(session, source_name, category, url, market, flag, price_note="") -> list[dict]:
    leads = []
    soup = get_page(session, url, f"{flag} {source_name}/{category}")
    if not soup:
        return leads

    selectors = [
        "ul.demands-list > li", ".demand-item", "article.demand",
        ".project-item", ".job-item", ".listing-item", ".offer-item",
        "article", ".item", "li.item", ".row-item",
    ]
    items = []
    for sel in selectors:
        candidates = soup.select(sel)
        if candidates and len(candidates) > 1:
            items = candidates
            break

    for item in items:
        link_tag = item.select_one("a[href]")
        if not link_tag:
            continue
        href = link_tag["href"]
        if not href.startswith("http"):
            base = "/".join(url.split("/")[:3])
            href = base + ("" if href.startswith("/") else "/") + href

        uid = f"{market.lower()}-" + href.strip("/").split("/")[-1][-30:]
        title_tag = item.select_one("h1,h2,h3,h4,.title,.name,strong")
        title = (title_tag or link_tag).get_text(strip=True)
        if len(title) < 4:
            continue

        date_tag = item.select_one(".date,time,.created,.posted,.when")
        date_str = date_tag.get_text(strip=True)[:20] if date_tag else ""

        region_tag = item.select_one(".region,.location,.kraj,.miasto,.ort")
        region = region_tag.get_text(strip=True) if region_tag else ""

        desc_tag = item.select_one("p,.description,.perex,.desc,.summary,.excerpt")
        desc = desc_tag.get_text(strip=True)[:400] if desc_tag else ""

        leads.append({
            "id": uid, "source": source_name, "market": market, "flag": flag,
            "category": category, "title": title,
            "date": date_str, "region": region, "price_note": price_note,
            "desc": desc, "url": href,
        })

    log(f"  ✓ {flag} {source_name} / {category}: {len(leads)}")
    return leads


# ──────────────────────────────────────────────
# Filtrování podle klíčových slov
# ──────────────────────────────────────────────
def is_relevant(lead: dict) -> bool:
    lang = "en"  # default
    market_lang_map = {
        "CZ": "cs", "SK": "sk", "PL": "pl",
        "AT": "de", "DE": "de", "HU": "hu",
        "US": "en",
    }
    lang = market_lang_map.get(lead.get("market", ""), "en")
    keywords = KEYWORDS_BY_LANG.get(lang, KEYWORDS_BY_LANG["en"])
    text = (lead.get("title", "") + " " + lead.get("desc", "")).lower()
    return any(kw in text for kw in keywords)


# ──────────────────────────────────────────────
# Paměť
# ──────────────────────────────────────────────
def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()

def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────
MARKET_COLORS = {
    "CZ": "#E8390E", "SK": "#0a3161", "PL": "#dc143c",
    "AT": "#ed2939", "DE": "#000000", "US": "#3c3b6e", "HU": "#ce2939",
}
SOURCE_BADGE_COLORS = {
    "ePoptávka.cz": "#e74c3c", "Navolnenoze.cz": "#2980b9",
    "Upwork (EN)": "#6fda44", "PeoplePerHour (EN)": "#ee6c2d",
    "Freelancermap.de": "#1a1a2e", "Freelancer.at": "#cc0000",
}

def build_email_html(new_leads: list[dict]) -> str:
    # Seskupit podle trhu
    by_market = {}
    for lead in new_leads:
        by_market.setdefault(lead["market"], []).append(lead)

    market_order = ["CZ", "SK", "PL", "AT", "DE", "US", "HU"]
    market_names = {
        "CZ": "Česká republika", "SK": "Slovensko", "PL": "Polsko",
        "AT": "Rakousko", "DE": "Německo", "US": "USA", "HU": "Maďarsko",
    }

    sections = ""
    for mkt in market_order:
        if mkt not in by_market:
            continue
        leads = by_market[mkt]
        color = MARKET_COLORS.get(mkt, "#555")
        flag = leads[0]["flag"]
        name = market_names.get(mkt, mkt)

        rows = ""
        for lead in leads:
            badge_color = SOURCE_BADGE_COLORS.get(lead["source"], "#7f8c8d")
            price_tag = (
                f'<span style="background:#f39c12;color:#fff;font-size:10px;'
                f'padding:2px 6px;border-radius:3px;margin-left:4px;">'
                f'{lead["price_note"]}</span>'
                if lead.get("price_note") else ""
            )
            rows += f"""
            <tr>
              <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top;">
                <div style="margin-bottom:5px;">
                  <span style="background:{badge_color};color:#fff;font-size:10px;
                               padding:2px 7px;border-radius:3px;">{lead['source']}</span>
                  <span style="background:#ecf0f1;color:#666;font-size:10px;
                               padding:2px 7px;border-radius:3px;margin-left:4px;">{lead['category']}</span>
                  {price_tag}
                  {('<span style="background:#f0f0f0;color:#888;font-size:10px;padding:2px 6px;border-radius:3px;margin-left:4px;">📍 ' + lead['region'] + '</span>') if lead.get('region') else ''}
                  {('<span style="color:#aaa;font-size:10px;margin-left:6px;">' + lead['date'] + '</span>') if lead.get('date') else ''}
                </div>
                <strong><a href="{lead['url']}"
                   style="color:#1a1a2e;text-decoration:none;font-size:14px;line-height:1.4;">
                  {lead['title']}
                </a></strong>
                {('<br><span style="color:#555;font-size:12px;line-height:1.5;">' + lead['desc'][:250] + '</span>') if lead.get('desc') else ''}
              </td>
              <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;
                         white-space:nowrap;vertical-align:middle;">
                <a href="{lead['url']}"
                   style="background:{color};color:#fff;padding:7px 13px;
                          border-radius:5px;text-decoration:none;font-size:12px;">
                  Zobrazit →
                </a>
              </td>
            </tr>
            """

        sections += f"""
        <div style="margin:20px 0;">
          <div style="background:{color};color:#fff;padding:10px 16px;
                      border-radius:6px 6px 0 0;display:flex;align-items:center;">
            <span style="font-size:20px;margin-right:8px;">{flag}</span>
            <span style="font-size:14px;font-weight:bold;">{name}</span>
            <span style="margin-left:auto;background:rgba(255,255,255,.25);
                         padding:2px 9px;border-radius:10px;font-size:12px;">
              {len(leads)} poptávek
            </span>
          </div>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #e0e0e0;border-top:none;border-radius:0 0 6px 6px;">
            {rows}
          </table>
        </div>
        """

    return f"""<!DOCTYPE html><html lang="cs">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;
             color:#222;background:#f9f9f9;padding:0;">

  <div style="background:#E8390E;padding:22px 28px;">
    <h1 style="color:#fff;margin:0;font-size:18px;letter-spacing:1px;">
      vhs. · Mezinárodní hlídač poptávek 🌍
    </h1>
    <p style="color:#aaa;margin:5px 0 0;font-size:12px;">
      {datetime.now().strftime('%d. %m. %Y · %H:%M')} &nbsp;·&nbsp;
      celkem {len(new_leads)} nových poptávek z {len(by_market)} trhů
    </p>
  </div>

  <div style="padding:8px 24px 24px;">
    {sections}
  </div>

  <div style="background:#fff5f3;padding:12px 28px;font-size:11px;color:#999;border-top:3px solid #E8390E;
              border-top:1px solid #e0e0e0;">
    Automatický hlídač zakázek pro <strong>vhs. – výtvarně hybridní sdružení</strong>
    · <a href="https://www.v-h-s.cz" style="color:#999;">v-h-s.cz</a><br>
    Trhy: CZ · SK · PL · AT · DE · US · HU
  </div>

</body></html>"""


def send_email(new_leads: list[dict]) -> None:
    markets_found = sorted(set(l["market"] for l in new_leads))
    subject = (
        f"🌍 VHS. – {len(new_leads)} poptávek "
        f"[{' · '.join(markets_found)}] "
        f"· {datetime.now().strftime('%d.%m.')}"
    )

    if not EMAIL_FROM or not EMAIL_PASSWORD:
        log("⚠️  EMAIL_FROM nebo EMAIL_PASSWORD není nastaven.")
        log("   Spusť: EMAIL_FROM=... EMAIL_PASSWORD=... python scraper.py")
        log(f"\n   Předmět emailu by byl: {subject}")
        log("   Poptávky:")
        for lead in new_leads:
            log(f"   {lead['flag']} [{lead['market']}] {lead['title']} ({lead['source']})")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(build_email_html(new_leads), "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
            srv.starttls()
            srv.login(EMAIL_FROM, EMAIL_PASSWORD)
            srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log(f"✅ Email odeslán → {EMAIL_TO}")
    except Exception as e:
        log(f"❌ Chyba emailu: {e}")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    log("🌍 VHS. Mezinárodní poptávkový hlídač startuje...")
    seen = load_seen()
    log(f"   Pamatuji si {len(seen)} dříve viděných poptávek.")

    session = make_session()
    all_leads: list[dict] = []

    for source in SOURCES:
        name       = source["name"]
        market     = source["market"]
        flag       = source["flag"]
        price_note = source.get("price_note", "")
        src_type   = source["type"]

        for category, url in source["urls"]:
            if src_type == "rss":
                leads = parse_rss(session, url, name, category, market, flag, price_note)
            else:
                leads = scrape_html(session, name, category, url, market, flag, price_note)
            all_leads += leads
            time.sleep(1.5)   # slušné chování vůči serverům

    # Filtr relevance
    relevant = [l for l in all_leads if is_relevant(l)]
    log(f"\n📋 Relevantních poptávek: {len(relevant)} / {len(all_leads)} celkem")

    # Filtr nových
    new_leads = [l for l in relevant if l["id"] not in seen]
    log(f"📬 Nových (ještě neviděných): {len(new_leads)}")

    # Statistika podle trhu
    if new_leads:
        by_mkt = {}
        for l in new_leads:
            by_mkt[l["market"]] = by_mkt.get(l["market"], 0) + 1
        for mkt, cnt in sorted(by_mkt.items()):
            log(f"   {cnt:3d}× {mkt}")

        send_email(new_leads)
        seen.update(l["id"] for l in new_leads)
        save_seen(seen)
        log(f"💾 Uloženo. Celkem v paměti: {len(seen)} poptávek.")
    else:
        log("😴 Žádné novinky – email se neposílá.")

    log("✔️  Hotovo.")


if __name__ == "__main__":
    main()
