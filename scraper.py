"""
VHS. Poptávkový hlídač — Poptavky.cz edice
=============================================
Kreativní agentura vhs. (v-h-s.cz) – design, video, foto, branding

Sleduje nové poptávky na Poptavky.cz — najvětší český agregátor poptávek
(916 000+ poptávek, 70 % trhu). Jeden spolehlivý zdroj místo mnoha
nefunkčních scraperů.

Spouštění:   python scraper.py
Automaticky: GitHub Actions každé 2h (Po–Pá)
"""

import json
import os
import re
import smtplib
import time
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
EMAIL_TO       = os.getenv("EMAIL_TO", "serbus@v-h-s.cz")
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "587"))

SEEN_FILE = Path("seen_ids.json")
BASE_URL  = "https://www.poptavky.cz"
DEBUG     = True  # dočasně zapnuto pro diagnostiku prázdných výsledků

# ──────────────────────────────────────────────
# KATEGORIE relevantní pro vhs. (design, video, foto, tisk, web, branding)
# ──────────────────────────────────────────────
CATEGORIES = [
    ("Grafika",                          "/poptavky/reklama-tisk/grafika"),
    ("Reklamní agentury",                "/poptavky/reklama-tisk/reklamni-agentury"),
    ("Marketing – online",               "/poptavky/reklama-tisk/marketing-online"),
    ("Marketing – komunikace",           "/poptavky/reklama-tisk/marketing-marketingova-komunikace"),
    ("Venkovní reklama",                 "/poptavky/reklama-tisk/venkovni-reklama"),
    ("Digitální tisk",                   "/poptavky/reklama-tisk/digitalni-tisk"),
    ("Velkoformátový tisk, plakáty",     "/poptavky/reklama-tisk/velkoformatovy-tisk-plakaty"),
    ("Katalogy, brožury, knihy",         "/poptavky/reklama-tisk/katalogy-casopisy-brozury-knihy"),
    ("Film, video",                      "/poptavky/sluzby/film-video"),
    ("Foto, video, kamera",              "/poptavky/sluzby/foto-video-kamera"),
    ("Tvorba www stránek",               "/poptavky/sluzby/tvorba-www-stranek"),
    ("Grafické služby (SW)",             "/poptavky/pocitace-software/software/graficke-sluzby"),
]

# Doplňková filtrace – vyřadí zjevně nerelevantní zásahy (kategorie je široká)
EXCLUDE_KEYWORDS = [
    "krejčovství", "krejčí", "švadlena", "opravu oděvů",
    "zednické práce", "instalatérské práce", "elektrikářské práce",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.82 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9",
}

# ──────────────────────────────────────────────
# Scraper — Poptavky.cz
# ──────────────────────────────────────────────
POPTAVKA_LINK_RE = re.compile(r'^/poptavka/(\d+)-')


def scrape_category(session: requests.Session, label: str, path: str) -> list[dict]:
    """Stáhne a naparsuje jednu kategorii z poptavky.cz."""
    leads = []
    url = BASE_URL + path

    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log(f"  ⚠️  {label}: chyba při stahování – {e}")
        return leads

    # DIAGNOSTIKA – zjistíme, jestli stránka vůbec obsahuje odkazy na poptávky
    if DEBUG:
        poptavka_count_raw = r.text.count("/poptavka/")
        log(f"  🔍 DEBUG {label}: status={r.status_code}, délka={len(r.text)} znaků, "
            f"výskytů '/poptavka/'={poptavka_count_raw}")
        if poptavka_count_raw == 0:
            snippet = re.sub(r"\s+", " ", r.text)[:300]
            log(f"     Prvních 300 znaků HTML: {snippet}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Najdi všechny odkazy na jednotlivé poptávky (vzor /poptavka/12345-nazev)
    poptavka_links = []
    for a in soup.find_all("a", href=True):
        m = POPTAVKA_LINK_RE.match(a["href"])
        if m:
            poptavka_links.append((m.group(1), a["href"], a))

    # Dedup podle ID (odkaz se může objevit vícekrát na stránce)
    seen_ids_on_page = set()
    unique_links = []
    for pid, href, a_tag in poptavka_links:
        if pid not in seen_ids_on_page:
            seen_ids_on_page.add(pid)
            unique_links.append((pid, href, a_tag))

    for pid, href, a_tag in unique_links:
        title = a_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        full_url = BASE_URL + href if href.startswith("/") else href

        # Najdi rodičovský blok (article/div) obsahující tento odkaz,
        # abychom z něj vytáhli lokalitu, datum, cenu a popis.
        container = a_tag.find_parent(["article", "div", "li"])

        region, price, date_str, desc, is_public_tender = "", "", "", "", False

        if container:
            # Metadata (lokalita/datum/cena) bývají v <ul>, popis v <p>
            meta_ul = container.find("ul")
            meta_text = meta_ul.get_text(" ", strip=True) if meta_ul else ""

            region_match = re.search(r"okres\s+([A-Za-zÀ-ž\-\s]+?)(?=\s+\d|\s{2,}|$)", meta_text)
            region = region_match.group(1).strip() if region_match else ""

            date_match = re.search(r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}", meta_text)
            date_str = date_match.group(0) if date_match else ""

            # Cena = číslo těsně před slovem "korun", odstraníme datum ať se nesplete s rokem
            meta_no_date = meta_text.replace(date_str, "") if date_str else meta_text
            price_match = re.search(r"(\d[\d\s]{0,12})\s*korun", meta_no_date)
            price = (price_match.group(1).strip() + " Kč") if price_match else ""

            # Popis: vezmi text z <p> tagů uvnitř bloku
            desc_paragraphs = container.find_all("p")
            if desc_paragraphs:
                desc = " ".join(p.get_text(" ", strip=True) for p in desc_paragraphs)
            else:
                # Záložní varianta: celý text bloku bez metadat
                full_text = container.get_text(" ", strip=True)
                desc = full_text.replace(meta_text, "").replace(title, "")

            desc = re.sub(r"\s+", " ", desc).strip()[:350]
            is_public_tender = "veřejné zakázky" in desc.lower() or "veřejná zakázka" in desc.lower()

        leads.append({
            "id": pid,
            "title": title,
            "category": label + (" · VZ" if is_public_tender else ""),
            "region": region,
            "price": price,
            "date": date_str,
            "desc": desc,
            "url": full_url,
        })

    log(f"  ✓ {label}: {len(leads)} položek")
    return leads


def is_relevant(lead: dict) -> bool:
    text = (lead["title"] + " " + lead["desc"]).lower()
    return not any(kw in text for kw in EXCLUDE_KEYWORDS)


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
# Email (VHS. brand: #E8390E)
# ──────────────────────────────────────────────
def build_email_html(new_leads: list[dict]) -> str:
    rows = ""
    for lead in new_leads:
        price_tag = (
            f'<span style="background:#f39c12;color:#fff;font-size:10px;'
            f'padding:2px 6px;border-radius:3px;margin-left:4px;">{lead["price"]}</span>'
            if lead.get("price") else ""
        )
        region_tag = (
            f'<span style="background:#f0f0f0;color:#888;font-size:10px;'
            f'padding:2px 6px;border-radius:3px;margin-left:4px;">📍 {lead["region"]}</span>'
            if lead.get("region") else ""
        )
        rows += f"""
        <tr>
          <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top;">
            <div style="margin-bottom:5px;">
              <span style="background:#7f8c8d;color:#fff;font-size:10px;
                           padding:2px 7px;border-radius:3px;">{lead['category']}</span>
              {price_tag}{region_tag}
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
               style="background:#E8390E;color:#fff;padding:7px 13px;
                      border-radius:5px;text-decoration:none;font-size:12px;">
              Zobrazit →
            </a>
          </td>
        </tr>
        """

    return f"""<!DOCTYPE html><html lang="cs">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;
             color:#222;background:#f9f9f9;padding:0;">
  <div style="background:#E8390E;padding:22px 28px;">
    <h1 style="color:#fff;margin:0;font-size:18px;letter-spacing:1px;">
      vhs. · Nové poptávky
    </h1>
    <p style="color:#ffe0d8;margin:5px 0 0;font-size:12px;">
      {datetime.now().strftime('%d. %m. %Y · %H:%M')} &nbsp;·&nbsp;
      {len(new_leads)} nových z poptavky.cz
    </p>
  </div>
  <div style="padding:8px 24px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #e0e0e0;border-radius:6px;margin-top:16px;">
      {rows}
    </table>
  </div>
  <div style="background:#fff5f3;padding:12px 28px;font-size:11px;color:#999;
              border-top:3px solid #E8390E;">
    Automatický hlídač zakázek pro <strong>vhs. – výtvarně hybridní sdružení</strong>
    · <a href="https://www.v-h-s.cz" style="color:#999;">v-h-s.cz</a>
    · zdroj: <a href="https://www.poptavky.cz" style="color:#999;">poptavky.cz</a>
  </div>
</body></html>"""


def send_email(new_leads: list[dict]) -> None:
    subject = f"🎯 VHS. – {len(new_leads)} nových poptávek · {datetime.now().strftime('%d.%m.')}"

    if not EMAIL_FROM or not EMAIL_PASSWORD:
        log("⚠️  EMAIL_FROM nebo EMAIL_PASSWORD není nastaven.")
        log(f"   Předmět emailu by byl: {subject}")
        for lead in new_leads:
            log(f"   • {lead['title']} [{lead['category']}]")
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
    log("🎯 VHS. Poptávkový hlídač (Poptavky.cz) startuje...")
    seen = load_seen()
    log(f"   Pamatuji si {len(seen)} dříve viděných poptávek.")
    log(f"   Sleduji {len(CATEGORIES)} kategorií.\n")

    session = requests.Session()
    all_leads: list[dict] = []

    for label, path in CATEGORIES:
        all_leads += scrape_category(session, label, path)
        time.sleep(1.5)  # slušné chování vůči serveru

    # Dedup napříč kategoriemi (stejná poptávka může spadat do více kategorií)
    dedup: dict[str, dict] = {}
    for lead in all_leads:
        dedup.setdefault(lead["id"], lead)
    all_leads = list(dedup.values())

    relevant = [l for l in all_leads if is_relevant(l)]
    log(f"\n📋 Relevantních poptávek: {len(relevant)} / {len(all_leads)} celkem")

    new_leads = [l for l in relevant if l["id"] not in seen]
    log(f"📬 Nových (ještě neviděných): {len(new_leads)}")

    if new_leads:
        send_email(new_leads)
        seen.update(l["id"] for l in new_leads)
        save_seen(seen)
        log(f"💾 Uloženo. Celkem v paměti: {len(seen)} poptávek.")
    else:
        log("😴 Žádné novinky – email se neposílá.")

    log("✔️  Hotovo.")


if __name__ == "__main__":
    main()
