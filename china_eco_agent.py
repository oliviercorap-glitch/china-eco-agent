#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
China Economic Intelligence Agent — for APAC CFO
================================================
Sources:
- International (EN): IMF, World Bank, OECD, Caixin (EN), BBC, SCMP
- Chinese institutions (EN): NBS, PBOC, MOFCOM, SCIO
- Chinese media (EN): Xinhua, Caixin (CN), Yicai, People's Daily, China News Service
- Chinese media (CN native): People's Daily CN, Xinhua CN, Sina Finance, Sohu Finance, CE.cn, East Money

Frequency: Mon-Fri 8am Shanghai (00:00 UTC)
Env: DEEPSEEK_API_KEY
Output: HTML report in English (styled, filtered articles)
"""

import os
import json
import logging
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_FILE = Path("logs/agent_eco.log")
SEEN_FILE = Path("seen_eco_articles.json")
DEBUG_MODE = False

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mots‑clés bilingues (anglais + chinois)
# ---------------------------------------------------------------------------
KEYWORDS_ECO = [
    # English
    "China", "Chinese", "GDP", "growth", "PMI", "CPI", "PPI",
    "inflation", "deflation", "export", "import", "trade",
    "consumption", "retail", "industrial", "stimulus", "fiscal",
    "monetary", "interest rate", "reserve", "yuan", "RMB",
    "PBOC", "property", "real estate", "unemployment", "Caixin",
    "NBS", "APAC", "Asia", "supply chain", "manufacturing",
    "credit", "liquidity", "foreign investment", "FDI",
    "renminbi", "economy", "policy", "rate", "market",
    "Beijing", "Shanghai", "tariff", "trade war", "debt", "bond",
    "stock", "yield", "infrastructure", "consumer", "spending",
    # Chinese (simplified)
    "经济", "中国", "增长", "通胀", "通货", "出口", "进口",
    "贸易", "消费", "零售", "工业", "财政", "货币", "利率",
    "准备金", "人民币", "央行", "房地产", "失业", "制造业",
    "供应链", "信贷", "流动性", "外商投资", "政策", "市场",
    "北京", "上海", "关税", "债务", "债券", "股票", "基础设施",
    "消费支出", "GDP", "PMI", "CPI", "PPI"
]

def article_relevant(article):
    """Retourne True si l'article a au moins 2 mots-clés (anglais ou chinois)."""
    texte = (article["titre"] + " " + article["desc"]).lower()
    # Compter les occurrences (chaque mot-clé compte une fois)
    count = 0
    for kw in KEYWORDS_ECO:
        if kw.lower() in texte:
            count += 1
    return count >= 2


# ---------------------------------------------------------------------------
# Sources (RSS + scraping) – version enrichie avec sources CN natives
# ---------------------------------------------------------------------------
RSS_SOURCES = [
    {"nom": "IMF", "url": "https://www.imf.org/en/News/rss?language=eng", "type": "rss"},
    {"nom": "World Bank", "url": "https://blogs.worldbank.org/rss.xml", "type": "rss"},
    {"nom": "OECD", "url": "https://www.oecd.org/newsroom/news.rss", "type": "rss"},
    {"nom": "Caixin English", "url": "https://www.caixinglobal.com/rss/all.xml", "type": "rss"},
    {"nom": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "type": "rss"},
    {"nom": "South China Morning Post", "url": "https://www.scmp.com/rss/5/feed", "type": "rss"},
]

SCRAPE_SOURCES = [
    # English sources (existing)
    {
        "nom": "NBS (EN)",
        "url": "https://www.stats.gov.cn/english/LatestReleases",
        "type": "scrape",
        "selector": "ul.list li a",
        "href_attr": "href",
        "base_url": "https://www.stats.gov.cn"
    },
    {
        "nom": "PBOC (EN)",
        "url": "http://www.pbc.gov.cn/en/3688110/index.html",
        "type": "scrape",
        "selector": "div.newsList ul li a",
        "href_attr": "href",
        "base_url": "http://www.pbc.gov.cn"
    },
    {
        "nom": "MOFCOM (EN)",
        "url": "http://english.mofcom.gov.cn/newsrelease/commonnews.shtml",
        "type": "scrape",
        "selector": "div.newsList ul li a",
        "href_attr": "href",
        "base_url": "http://english.mofcom.gov.cn"
    },
    {
        "nom": "SCIO (EN)",
        "url": "http://www.scio.gov.cn/xwfbh/index.htm",
        "type": "scrape",
        "selector": "div.list li a",
        "href_attr": "href",
        "base_url": "http://www.scio.gov.cn"
    },
    {
        "nom": "Xinhuanet Finance (EN)",
        "url": "http://www.xinhuanet.com/english/business/index.htm",
        "type": "scrape",
        "selector": "div.item-title a",
        "href_attr": "href",
        "base_url": "http://www.xinhuanet.com"
    },
    {
        "nom": "Caixin (CN)",
        "url": "https://economy.caixin.com/",
        "type": "scrape",
        "selector": "div.news-list li a",
        "href_attr": "href",
        "base_url": "https://economy.caixin.com"
    },
    {
        "nom": "Yicai (CN)",
        "url": "https://www.yicai.com/news/",
        "type": "scrape",
        "selector": "div.news-list-item a",
        "href_attr": "href",
        "base_url": "https://www.yicai.com"
    },
    {
        "nom": "People's Daily Economy (EN)",
        "url": "http://en.people.cn/economy/index.html",
        "type": "scrape",
        "selector": "div.cp p a",
        "href_attr": "href",
        "base_url": "http://en.people.cn"
    },
    {
        "nom": "China News Service (CN)",
        "url": "https://www.chinanews.com.cn/finance/",
        "type": "scrape",
        "selector": "div.news-list a",
        "href_attr": "href",
        "base_url": "https://www.chinanews.com.cn"
    },
    # NEW: Chinese native sources
    {
        "nom": "人民网 经济 (People's Daily CN)",
        "url": "http://finance.people.com.cn/",
        "type": "scrape",
        "selector": "div.cj_list a",
        "href_attr": "href",
        "base_url": "http://finance.people.com.cn/"
    },
    {
        "nom": "新华网 财经 (Xinhua CN)",
        "url": "http://www.xinhuanet.com/fortune/index.htm",
        "type": "scrape",
        "selector": "div.item-title a",
        "href_attr": "href",
        "base_url": "http://www.xinhuanet.com"
    },
    {
        "nom": "新浪财经 (Sina Finance)",
        "url": "https://finance.sina.com.cn/",
        "type": "scrape",
        "selector": "div.news-item a",
        "href_attr": "href",
        "base_url": "https://finance.sina.com.cn"
    },
    {
        "nom": "搜狐财经 (Sohu Finance)",
        "url": "https://business.sohu.com/",
        "type": "scrape",
        "selector": "div.news-list a",
        "href_attr": "href",
        "base_url": "https://business.sohu.com"
    },
    {
        "nom": "中国经济网 (CE.cn)",
        "url": "http://www.ce.cn/",
        "type": "scrape",
        "selector": "div.news_list a",
        "href_attr": "href",
        "base_url": "http://www.ce.cn"
    },
    {
        "nom": "东方财富 (East Money)",
        "url": "https://www.eastmoney.com/",
        "type": "scrape",
        "selector": "div.news-item a",
        "href_attr": "href",
        "base_url": "https://www.eastmoney.com"
    }
]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, indent=2)


# ---------------------------------------------------------------------------
# Récupération RSS
# ---------------------------------------------------------------------------
def fetch_rss(source):
    articles = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(source["url"], timeout=15, headers=headers)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)

        for item in items[:20]:
            titre = item.findtext("title") or item.findtext("atom:title", namespaces=ns) or ""
            titre = titre.strip()
            if not titre:
                continue
            lien = ""
            link_el = item.find("link")
            if link_el is not None:
                lien = link_el.text or link_el.get("href") or ""
            if not lien:
                link_el = item.find("atom:link", ns)
                if link_el is not None:
                    lien = link_el.get("href") or ""
            lien = lien.strip()
            desc = item.findtext("description") or item.findtext("atom:summary", namespaces=ns) or ""
            desc = desc.strip()
            date_str = item.findtext("pubDate") or item.findtext("atom:updated", namespaces=ns) or ""
            date_str = date_str.strip()
            articles.append({
                "source": source["nom"],
                "titre": titre,
                "lien": lien,
                "desc": desc[:600],
                "date": date_str,
                "id": hashlib.md5((titre + lien).encode()).hexdigest(),
            })
    except Exception as e:
        log.warning(f"Error fetching RSS {source['nom']}: {e}")
    return articles


# ---------------------------------------------------------------------------
# Scraping HTML (supporte UTF-8)
# ---------------------------------------------------------------------------
def scrape_source(source):
    articles = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(source["url"], timeout=15, headers=headers)
        resp.raise_for_status()
        # Forcer l'encodage sur UTF-8 si le serveur ne le précise pas
        if resp.encoding is None:
            resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.content, "html.parser")
        links = soup.select(source["selector"])
        for link in links[:20]:
            titre = link.get_text(strip=True)
            if not titre:
                continue
            href = link.get(source["href_attr"])
            if not href:
                continue
            lien = href if href.startswith("http") else urljoin(source["base_url"], href)
            articles.append({
                "source": source["nom"],
                "titre": titre,
                "lien": lien,
                "desc": "",
                "date": "",
                "id": hashlib.md5((titre + lien).encode()).hexdigest(),
            })
    except Exception as e:
        log.warning(f"Error scraping {source['nom']}: {e}")
    return articles


def collecter_tous_articles():
    tous = []
    for src in RSS_SOURCES:
        articles = fetch_rss(src)
        log.info(f"{src['nom']}: {len(articles)} RSS articles")
        tous.extend(articles)
    for src in SCRAPE_SOURCES:
        articles = scrape_source(src)
        log.info(f"{src['nom']}: {len(articles)} scraped articles")
        tous.extend(articles)

    if DEBUG_MODE and tous:
        log.debug("===== Sample articles =====")
        for i, a in enumerate(tous[:10], 1):
            log.debug(f"{i}. {a['source']} - {a['titre'][:50]}")
        log.debug("===========================")
    return tous


def filtrer_pertinents(articles, vus):
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        if article_relevant(a):
            nouveaux.append(a)
            log.debug(f"Relevant: {a['titre'][:50]}...")
    return nouveaux


# ---------------------------------------------------------------------------
# Analyse DeepSeek (REST API) – en anglais
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_EN = """You are a senior economist specialized in China and the APAC region,
advising a CFO of a multinational corporation based in Shanghai.

Analyze the following news and economic indicators, and evaluate their concrete impact
on CFO decisions:
- Impact on revenues and local demand
- Impact on costs (inflation, raw materials, logistics)
- Impact on exchange rates and financial flows
- Monetary or fiscal policy signals to anticipate
- Comparison with APAC trends

Your analysis must be in **English**, professional, and decision‑oriented.
Signal strength: STRONG / MODERATE / WEAK.
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "No significant economic signals detected today."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        log.error("DEEPSEEK_API_KEY not set")
        return "Error: DeepSeek API key missing. Analysis unavailable."

    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += (
            f"\n[{i}] Source: {a['source']}\n"
            f"    Title: {a['titre']}\n"
            f"    Link: {a['lien']}\n"
        )
        if a['desc']:
            articles_txt += f"    Summary: {a['desc']}\n"

    prompt = (
        f"China Economic Watch — {date_str}\n"
        f"Number of articles: {len(articles)}\n\n"
        f"{articles_txt}\n\n"
        "For each important signal, provide:\n"
        "1. SIGNAL: STRONG / MODERATE / WEAK\n"
        "2. INDICATOR: which macro indicator?\n"
        "3. READING: what does this signal say about the Chinese economy?\n"
        "4. CFO IMPACT: effect on revenues, costs, FX, or liquidity\n"
        "5. TO WATCH: which next indicator would confirm this signal?\n\n"
        "Finish with:\n"
        "- MACRO SUMMARY (5 lines): state of the economy this week\n"
        "- APAC COMPARISON: how does China position vs. the region?\n"
        "- 3 KEY POINTS for the CFO this week"
    )

    log.info(f"Sending {len(articles)} articles to DeepSeek via REST API...")
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_EN},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 4096
        }
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        log.exception(f"Error calling DeepSeek: {e}")
        return f"DeepSeek analysis error: {e}"


# ---------------------------------------------------------------------------
# HTML Report Generator – avec mise en forme
# ---------------------------------------------------------------------------
def format_analysis(analysis_text):
    if not analysis_text:
        return "<p>No analysis available.</p>"

    lines = analysis_text.split('\n')
    html_lines = []
    in_list = False
    in_section = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
            continue

        # Section titles (Signal, Macro Summary, etc.)
        if re.match(r'^###?\s+Signal\s+\d+:', line, re.I) or re.match(r'^##?\s*Signal\s+\d+:', line, re.I):
            if in_section:
                html_lines.append("</div>")
            html_lines.append(f'<div class="signal-section"><h3 class="signal-title">{line}</h3>')
            in_section = True
            continue

        if re.match(r'^##?\s*(MACRO SUMMARY|APAC COMPARISON|3 KEY POINTS)', line, re.I):
            if in_section:
                html_lines.append("</div>")
            html_lines.append(f'<div class="section-block"><h3 class="block-title">{line}</h3>')
            in_section = True
            continue

        # Labels (INDICATOR, READING, CFO IMPACT, TO WATCH)
        if re.match(r'^\*\*?([A-Z\s]+):\*\*?', line):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            line = re.sub(r'\*\*(.*?):\*\*', r'<strong>\1:</strong>', line)
            html_lines.append(f'<p class="label">{line}</p>')
            continue

        # List items (- or *)
        if line.startswith('- ') or line.startswith('* '):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = line[2:] if line.startswith('- ') else line[1:]
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
            html_lines.append(f'<li>{content}</li>')
            continue

        if in_list:
            html_lines.append("</ul>")
            in_list = False

        line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
        html_lines.append(f'<p class="normal">{line}</p>')

    if in_section:
        html_lines.append("</div>")
    if in_list:
        html_lines.append("</ul>")

    return '\n'.join(html_lines)


def generer_rapport_html(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%d %B %Y")
    sources_list = [s['nom'] for s in RSS_SOURCES + SCRAPE_SOURCES]

    formatted_analysis = format_analysis(analyse)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>China Economic Intelligence – {date_str}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Roboto, Arial, sans-serif;
            max-width: 1100px;
            margin: 40px auto;
            padding: 20px;
            background: #f8fafc;
            color: #1e293b;
            line-height: 1.6;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            padding: 40px;
        }}
        h1 {{
            font-size: 2.2rem;
            font-weight: 600;
            border-bottom: 4px solid #2563eb;
            padding-bottom: 10px;
            color: #0f172a;
            margin-top: 0;
        }}
        .meta {{
            color: #475569;
            margin-bottom: 30px;
            font-size: 1rem;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
        }}
        .badge {{
            background: #dbeafe;
            color: #1e40af;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 500;
        }}
        .section {{
            margin-top: 35px;
        }}
        .section-title {{
            font-size: 1.6rem;
            font-weight: 500;
            margin-bottom: 15px;
            color: #0f172a;
            border-left: 6px solid #2563eb;
            padding-left: 15px;
        }}
        .article-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .article-item {{
            background: #f1f5f9;
            padding: 15px 20px;
            border-radius: 10px;
            transition: background 0.2s;
        }}
        .article-item:hover {{
            background: #e2e8f0;
        }}
        .article-title {{
            font-weight: 600;
            font-size: 1.05rem;
        }}
        .article-title a {{
            color: #1e293b;
            text-decoration: none;
        }}
        .article-title a:hover {{
            color: #2563eb;
            text-decoration: underline;
        }}
        .article-source {{
            font-size: 0.85rem;
            color: #475569;
            margin-top: 4px;
        }}
        .article-desc {{
            margin-top: 6px;
            font-size: 0.95rem;
            color: #334155;
        }}
        .analysis-box {{
            background: #f8fafc;
            padding: 25px 30px;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            margin-top: 10px;
        }}
        .analysis-box .signal-section,
        .analysis-box .section-block {{
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .analysis-box .signal-title,
        .analysis-box .block-title {{
            font-size: 1.2rem;
            font-weight: 600;
            color: #0f172a;
            margin-bottom: 10px;
        }}
        .analysis-box .label {{
            font-weight: 600;
            color: #1e40af;
            margin: 8px 0 4px 0;
        }}
        .analysis-box ul {{
            margin: 8px 0 12px 20px;
            padding-left: 0;
            list-style-type: disc;
        }}
        .analysis-box ul li {{
            margin-bottom: 4px;
        }}
        .analysis-box p {{
            margin: 6px 0;
        }}
        .analysis-box .normal {{
            margin: 4px 0;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 0.9rem;
            color: #94a3b8;
            border-top: 1px solid #e2e8f0;
            padding-top: 20px;
        }}
        .no-articles {{
            background: #fef3c7;
            padding: 20px;
            border-radius: 12px;
            color: #92400e;
            font-weight: 500;
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>🇨🇳 China Economic Intelligence</h1>
    <div class="meta">
        <span><strong>Date:</strong> {date_str}</span>
        <span><strong>Generated:</strong> {now}</span>
        <span class="badge">{len(articles)} signal(s) detected</span>
    </div>

    <div class="section">
        <div class="section-title">📰 Articles of the Day</div>
        <div class="article-list">
"""

    if articles:
        for a in articles:
            html += f"""
            <div class="article-item">
                <div class="article-title"><a href="{a['lien']}" target="_blank">{a['titre']}</a></div>
                <div class="article-source">Source: {a['source']}</div>
                {f'<div class="article-desc">{a["desc"]}</div>' if a['desc'] else ''}
            </div>
            """
    else:
        html += '<div class="no-articles">No relevant articles found today.</div>'

    html += f"""
        </div>
    </div>

    <div class="section">
        <div class="section-title">📊 Economic Analysis & CFO Brief</div>
        <div class="analysis-box">
            {formatted_analysis}
        </div>
    </div>

    <div class="section" style="margin-top: 20px;">
        <div class="section-title" style="font-size:1.2rem;">🔍 Monitored Sources</div>
        <ul style="columns:2; list-style: none; padding-left: 0; margin-top: 10px;">
    """

    for src in sources_list:
        html += f"<li style='padding: 4px 0;'>• {src}</li>"

    html += f"""
        </ul>
    </div>

    <div class="footer">
        Powered by DeepSeek AI &bull; China Eco Agent
    </div>
</div>
</body>
</html>
    """
    return html


def sauvegarder_rapport_html(html):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"eco_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"HTML report saved: {fichier}")
    return fichier


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def executer_agent():
    log.info("Starting China economic intelligence agent (English report, Chinese sources)")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        pertinents = filtrer_pertinents(tous_articles, vus)
        log.info(f"New relevant signals: {len(pertinents)}")

        analyse = analyser_avec_deepseek(pertinents)
        html = generer_rapport_html(pertinents, analyse)
        fichier = sauvegarder_rapport_html(html)

        print(f"Report generated: {fichier}")

        for a in pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)

        log.info("Done.")
    except Exception as e:
        log.exception(f"General error: {e}")
        raise


if __name__ == "__main__":
    executer_agent()
