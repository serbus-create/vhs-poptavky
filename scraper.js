/**
 * VHS. Poptávkový hlídač — Poptavky.cz edice (Node.js + Playwright)
 * =====================================================================
 * Kreativní agentura vhs. (v-h-s.cz) – design, video, foto, branding
 *
 * Poptavky.cz vykresluje obsah přes JavaScript (SPA), takže obyčejný
 * HTTP request vidí jen prázdnou kostru. Tenhle scraper proto používá
 * headless prohlížeč (Playwright), který stránku skutečně otevře
 * a počká, až se obsah dokreslí – přesně jako člověk v Chrome.
 *
 * Výstup: leads.json — čte ho index.html (dashboard na GitHub Pages).
 * Žádný email se neposílá.
 *
 * Spouštění:   node scraper.js
 * Automaticky: GitHub Actions každé 2h (Po–Pá)
 */

import { chromium } from "playwright";
import fs from "fs";

const SEEN_FILE  = "seen_ids.json";   // id -> firstSeen ISO timestamp
const LEADS_FILE = "leads.json";      // aktuální data pro dashboard
const BASE_URL   = "https://www.poptavky.cz";
const DEBUG      = true;

const CATEGORIES = [
  ["Grafika",                      "/poptavky/reklama-tisk/grafika"],
  ["Reklamní agentury",            "/poptavky/reklama-tisk/reklamni-agentury"],
  ["Marketing – online",           "/poptavky/reklama-tisk/marketing-online"],
  ["Marketing – komunikace",       "/poptavky/reklama-tisk/marketing-marketingova-komunikace"],
  ["Venkovní reklama",             "/poptavky/reklama-tisk/venkovni-reklama"],
  ["Digitální tisk",               "/poptavky/reklama-tisk/digitalni-tisk"],
  ["Velkoformátový tisk, plakáty", "/poptavky/reklama-tisk/velkoformatovy-tisk-plakaty"],
  ["Katalogy, brožury, knihy",     "/poptavky/reklama-tisk/katalogy-casopisy-brozury-knihy"],
  ["Film, video",                  "/poptavky/sluzby/film-video"],
  ["Foto, video, kamera",          "/poptavky/sluzby/foto-video-kamera"],
  ["Tvorba www stránek",           "/poptavky/sluzby/tvorba-www-stranek"],
  ["Grafické služby (SW)",         "/poptavky/pocitace-software/software/graficke-sluzby"],
];

const EXCLUDE_KEYWORDS = [
  "krejčovství", "krejčí", "švadlena", "opravu oděvů",
  "zednické práce", "instalatérské práce", "elektrikářské práce",
];

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0.6367.82 Safari/537.36";

function log(msg) {
  const t = new Date().toTimeString().slice(0, 8);
  console.log(`[${t}] ${msg}`);
}

// ──────────────────────────────────────────────
// Paměť: id -> kdy poprvé zaznamenáno (pro označení "Nové")
// ──────────────────────────────────────────────
function loadSeen() {
  if (fs.existsSync(SEEN_FILE)) {
    const raw = JSON.parse(fs.readFileSync(SEEN_FILE, "utf-8"));
    // zpětná kompatibilita: pokud je to pole (stará verze), převeď na objekt
    if (Array.isArray(raw)) {
      const obj = {};
      raw.forEach((id) => (obj[id] = new Date().toISOString()));
      return obj;
    }
    return raw;
  }
  return {};
}

function saveSeen(seenMap) {
  fs.writeFileSync(SEEN_FILE, JSON.stringify(seenMap, null, 2), "utf-8");
}

// ──────────────────────────────────────────────
// Scraper — jedna kategorie
// ──────────────────────────────────────────────
async function scrapeCategory(page, label, path, debugSamples) {
  const leads = [];
  const url = BASE_URL + path;

  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 25000 });
    try {
      await page.waitForSelector('a[href^="/poptavka/"]', { timeout: 8000 });
    } catch {
      // možná prázdná kategorie
    }
    await page.waitForTimeout(500);
  } catch (e) {
    log(`  ⚠️  ${label}: chyba při načítání – ${e.message}`);
    return leads;
  }

  if (DEBUG) {
    const html = await page.content();
    const count = (html.match(/\/poptavka\//g) || []).length;
    log(`  🔍 DEBUG ${label}: délka=${html.length} znaků, výskytů '/poptavka/'=${count}`);
  }

  const items = await page.$$eval('a[href^="/poptavka/"]', (anchors) => {
    const seen = new Set();
    const results = [];

    for (const a of anchors) {
      const href = a.getAttribute("href") || "";
      const m = href.match(/^\/poptavka\/(\d+)-/);
      if (!m) continue;

      const id = m[1];
      if (seen.has(id)) continue;
      seen.add(id);

      const title = (a.textContent || "").trim();
      if (!title || title.length < 5) continue;

      const container = a.closest("article, div, li");
      let metaText = "";
      let descText = "";

      if (container) {
        const ul = container.querySelector("ul");
        metaText = ul ? ul.textContent.replace(/\s+/g, " ").trim() : "";

        const ps = container.querySelectorAll("p");
        if (ps.length) {
          descText = Array.from(ps).map((p) => p.textContent.trim()).join(" ");
        } else {
          descText = container.textContent.replace(metaText, "").replace(title, "").trim();
        }
      }

      results.push({ id, href, title, metaText, descText });
    }
    return results;
  });

  if (debugSamples && items.length) {
    items.slice(0, 5).forEach((it) => {
      log(`     vzorek: id=${it.id} text='${it.title.slice(0, 60)}'`);
    });
  }

  for (const item of items) {
    const fullUrl = BASE_URL + item.href;

    const regionMatch = item.metaText.match(/okres\s+([A-Za-zÀ-ž\-\s]+?)(?=\s+\d|\s{2,}|$)/);
    const region = regionMatch ? regionMatch[1].trim() : "";

    const dateMatch = item.metaText.match(/\d{1,2}\.\s*\d{1,2}\.\s*\d{4}/);
    const dateStr = dateMatch ? dateMatch[0] : "";

    const metaNoDate = dateStr ? item.metaText.replace(dateStr, "") : item.metaText;
    const priceMatch = metaNoDate.match(/(\d[\d\s]{0,12})\s*korun/);
    const price = priceMatch ? priceMatch[1].trim() + " Kč" : "";

    let desc = item.descText.replace(/\s+/g, " ").trim().slice(0, 350);
    const isPublicTender = /veřejné zakázky|veřejná zakázka/i.test(desc);

    leads.push({
      id: item.id,
      title: item.title,
      category: label + (isPublicTender ? " · VZ" : ""),
      region,
      price,
      date: dateStr,
      desc,
      url: fullUrl,
    });
  }

  log(`  ✓ ${label}: ${leads.length} položek`);
  return leads;
}

function isRelevant(lead) {
  const text = (lead.title + " " + lead.desc).toLowerCase();
  return !EXCLUDE_KEYWORDS.some((kw) => text.includes(kw));
}

// ──────────────────────────────────────────────
// MAIN
// ──────────────────────────────────────────────
async function main() {
  log("🎯 VHS. Poptávkový hlídač (Poptavky.cz, Playwright/Node) startuje...");
  const seenMap = loadSeen();
  log(`   Pamatuji si ${Object.keys(seenMap).length} dříve viděných poptávek.`);
  log(`   Sleduji ${CATEGORIES.length} kategorií.\n`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ userAgent: USER_AGENT });

  let allLeads = [];
  let debugShown = false;

  for (const [label, path] of CATEGORIES) {
    const leads = await scrapeCategory(page, label, path, DEBUG && !debugShown);
    if (DEBUG && !debugShown) debugShown = true;
    allLeads = allLeads.concat(leads);
  }

  await browser.close();

  // Dedup napříč kategoriemi
  const dedupMap = new Map();
  for (const lead of allLeads) {
    if (!dedupMap.has(lead.id)) dedupMap.set(lead.id, lead);
  }
  allLeads = [...dedupMap.values()];

  const relevant = allLeads.filter(isRelevant);
  log(`\n📋 Relevantních poptávek: ${relevant.length} / ${allLeads.length} celkem`);

  const now = new Date().toISOString();
  let newCount = 0;

  // Přidej firstSeen (nové poptávky dostanou aktuální čas, staré si podrží původní)
  for (const lead of relevant) {
    if (!seenMap[lead.id]) {
      seenMap[lead.id] = now;
      newCount++;
    }
    lead.firstSeen = seenMap[lead.id];
  }

  log(`📬 Nových (ještě neviděných): ${newCount}`);

  // Seřaď od nejnovějších (podle firstSeen)
  relevant.sort((a, b) => new Date(b.firstSeen) - new Date(a.firstSeen));

  // Ulož data pro dashboard
  const output = {
    generatedAt: now,
    count: relevant.length,
    newCount,
    leads: relevant,
  };
  fs.writeFileSync(LEADS_FILE, JSON.stringify(output, null, 2), "utf-8");
  log(`💾 Uloženo do ${LEADS_FILE}: ${relevant.length} poptávek (${newCount} nových)`);

  saveSeen(seenMap);
  log(`💾 Paměť aktualizována: ${Object.keys(seenMap).length} poptávek celkem.`);

  log("✔️  Hotovo.");
}

main().catch((e) => {
  console.error("❌ Fatální chyba:", e);
  process.exit(1);
});
