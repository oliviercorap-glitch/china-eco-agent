#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Agent de veille économique Chine — CFO étranger APAC
Version enrichie avec sources institutionnelles et médias chinois
=======================================================
Sources :
- Internationales : IMF, World Bank, OECD, Caixin (EN), BBC, SCMP
- Institutions chinoises : NBS, PBOC, MOFCOM, SCIO
- Médias chinois : Xinhua, Caixin (CN), Yicai, People's Daily, China News Service

Fréquence : lundi à vendredi 8h Shanghai (00:00 UTC)
Variables d'environnement : DEEPSEEK_API_KEY
"""

import os
import json
import logging
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env (si présent)
load_dotenv()

# --- Configuration des logs ---
LOG_FILE = Path("logs/agent_eco.log")
SEEN_FILE = Path("seen_eco_articles.json")

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mots-clés élargis (anglais + translittérations)
# ---------------------------------------------------------------------------
KEYWORDS_ECO = [
    "China", "GDP", "growth", "PMI", "CPI", "PPI", "inflation", "deflation",
    "export", "import", "trade", "consumption", "retail", "industrial",
    "stimulus", "fiscal", "monetary", "interest rate", "reserve",
    "yuan", "RMB", "PBOC", "property", "real estate", "unemployment",
    "Caixin", "NBS", "APAC", "Asia", "supply chain", "manufacturing",
    "credit", "liquidity", "foreign investment", "FDI",
    "renminbi", "zhongguo", "jingji", "fangdi chan", "dichan",
]


# ---------------------------------------------------------------------------
# Sources : définition avec URL de scraping ou RSS
# ---------------------------------------------------------------------------

# Sources RSS internationales
RSS_SOURCES = [
    {
        "nom": "IMF — Fonds monétaire international",
        "url": "https://www.imf.org/en/News/rss?language=eng",
        "type": "rss"
    },
    {
        "nom": "World Bank — Banque mondiale",
        "url": "https://blogs.worldbank.org/rss.xml",
        "type": "rss"
    },
    {
        "nom": "OECD — Organisation de coopération économique",
        "url": "https://www.oecd.org/newsroom/news.rss",
        "type": "rss"
    },
    {
        "nom": "Caixin English",
        "url": "https://www.caixinglobal.com/rss/all.xml",
        "type": "rss"
    },
    {
        "nom": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "type": "rss"
    },
    {
        "nom": "South China Morning Post",
        "url": "https://www.scmp.com/rss/5/feed",
        "type": "rss"
    },
]

# Sources à scraper (HTML)
SCRAPE_SOURCES = [
    {
        "nom": "NBS — Bureau national des statistiques (EN)",
        "url": "https://www.stats.gov.cn/english/LatestReleases",
        "type": "scrape",
        "selector": "ul.list li a",
        "href_attr": "href",
        "base_url": "https://www.stats.gov.cn"
    },
    {
        "nom": "PBOC — Banque populaire de Chine (EN)",
        "url": "http://www.pbc.gov.cn/en/3688110/index.html",
        "type": "scrape",
        "selector": "div.newsList ul li a",
        "href_attr": "href",
        "base_url": "http://www.pbc.gov.cn"
    },
    {
        "nom": "MOFCOM — Ministère du commerce (EN)",
        "url": "http://english.mofcom.gov.cn/newsrelease/commonnews.shtml",
        "type": "scrape",
        "selector": "div.newsList ul li a",
        "href_attr": "href",
        "base_url": "http://english.mofcom.gov.cn"
    },
    {
        "nom": "SCIO — Bureau d'info du Conseil des affaires de l'État (EN)",
        "url": "http://www.scio.gov.cn/xwfbh/index.htm",
        "type": "scrape",
        "selector": "div.list li a",
        "href_attr": "href",
        "base_url": "http://www.scio.gov.cn"
    },
    {
        "nom": "Xinhuanet — Finance (EN)",
        "url": "http://www.xinhuanet.com/english/business/index.htm",
        "type": "scrape",
        "selector": "div.item-title a",
        "href_attr": "href",
        "base_url": "http://www.xinhuanet.com"
    },
    {
        "nom": "Caixin — 财新网 (CN)",
        "url": "https://economy.caixin.com/",
        "type": "scrape",
        "selector": "div.news-list li a",
        "href_attr": "href",
        "base_url": "https://economy.caixin.com"
    },
    {
        "nom": "Yicai — 第一财经 (CN)",
        "url": "https://www.yicai.com/news/",
        "type": "scrape",
        "selector": "div.news-list-item a",
        "href_attr": "href",
        "base_url": "https://www.yicai.com"
    },
    {
        "nom": "People's Daily Online — Économie (EN)",
        "url": "http://en.people.cn/economy/index.html",
        "type": "scrape",
        "selector": "div.cp p a",
        "href_attr": "href",
        "base_url": "http://en.people.cn"
    },
    {
        "nom": "China News Service — Économie (CN)",
        "url": "https://www.chinanews.com.cn/finance/",
        "type": "scrape",
        "selector": "div.news-list a",
        "href_attr": "href",
        "base_url": "https://www.chinanews.com.cn"
    },
]


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def charger_vus():
    """Charge l'ensemble des IDs d'articles déjà traités."""
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    """Sauvegarde les IDs d'articles traités."""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, indent=2)


def fetch_rss(source):
    """Récupère et parse un flux RSS (supporte RSS 2.0 et Atom)."""
    articles = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(source["url"], timeout=15, headers=headers)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        # Gestion des namespaces Atom
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//atom:entry", ns)

        for item in items[:20]:
            # Titre
            titre = item.findtext("title")
            if titre is None:
                titre = item.findtext("atom:title", namespaces=ns)
            if not titre:
                continue
            titre = titre.strip()

            # Lien
            lien = ""
            link_el = item.find("link")
            if link_el is not None:
                lien = link_el.text or link_el.get("href") or ""
            if not lien:
                link_el = item.find("atom:link", ns)
                if link_el is not None:
                    lien = link_el.get("href") or ""
            lien = lien.strip()

            # Description
            desc = item.findtext("description")
            if desc is None:
                desc = item.findtext("atom:summary", namespaces=ns)
            desc = (desc or "").strip()

            # Date
            date_str = item.findtext("pubDate")
            if date_str is None:
                date_str = item.findtext("atom:updated", namespaces=ns)
            date_str = (date_str or "").strip()

            articles.append({
                "source": source["nom"],
                "titre": titre,
                "lien": lien,
                "desc": desc[:600],
                "date": date_str,
                "id": hashlib.md5((titre + lien).encode()).hexdigest(),
            })
    except Exception as e:
        log.warning(f"Erreur fetch RSS {source['nom']} : {e}")
    return articles


def scrape_source(source):
    """Récupère les articles en scraping une page HTML."""
    articles = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(source["url"], timeout=15, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        links = soup.select(source["selector"])
        for link in links[:20]:
            titre = link.get_text(strip=True)
            if not titre:
                continue
            href = link.get(source["href_attr"])
            if not href:
                continue
            if href.startswith("http"):
                lien = href
            else:
                lien = urljoin(source["base_url"], href)
            articles.append({
                "source": source["nom"],
                "titre": titre,
                "lien": lien,
                "desc": "",
                "date": "",
                "id": hashlib.md5((titre + lien).encode()).hexdigest(),
            })
    except Exception as e:
        log.warning(f"Erreur scrape {source['nom']} : {e}")
    return articles


def collecter_tous_articles():
    """Rassemble tous les articles (RSS + scraping)."""
    tous = []
    for src in RSS_SOURCES:
        articles = fetch_rss(src)
        log.info(f"{src['nom']} : {len(articles)} articles RSS")
        tous.extend(articles)
    for src in SCRAPE_SOURCES:
        articles = scrape_source(src)
        log.info(f"{src['nom']} : {len(articles)} articles scrapés")
        tous.extend(articles)
    return tous


def filtrer_pertinents(articles, vus):
    """Filtre les articles : nouveaux et contenant au moins un mot-clé."""
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a["desc"]).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_ECO):
            nouveaux.append(a)
    return nouveaux


# ---------------------------------------------------------------------------
# Analyse par DeepSeek via appel HTTP direct (API compatible OpenAI)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Tu es un économiste senior spécialisé en Chine et en zone APAC,
conseiller d'un CFO de multinationale étrangère basé à Shanghai.

Tu analyses les actualités et indicateurs économiques chinois et évalues leur impact
concret sur les décisions financières d'un CFO :
- Impact sur les revenus et la demande locale
- Impact sur les coûts (inflation, matières premières, logistique)
- Impact sur la politique de change et les flux financiers
- Signaux de politique monétaire ou fiscale à anticiper
- Comparaison avec les tendances APAC

Ton analyse est en français, professionnelle, orientée décision CFO.
Niveau de signal : FORT / MODÉRÉ / FAIBLE
"""

def analyser_avec_deepseek(articles):
    """Envoie les articles à DeepSeek via l'API REST et retourne l'analyse."""
    if not articles:
        return "Aucun signal économique significatif détecté aujourd'hui."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        log.error("Variable DEEPSEEK_API_KEY non définie")
        return "Erreur : clé API DeepSeek manquante. Analyse non disponible."

    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += (
            f"\n[{i}] Source : {a['source']}\n"
            f"    Titre : {a['titre']}\n"
            f"    Lien  : {a['lien']}\n"
        )
        if a['desc']:
            articles_txt += f"    Résumé: {a['desc']}\n"

    prompt = (
        f"Veille économique Chine — {date_str}\n"
        f"Nombre d'articles : {len(articles)}\n\n"
        f"{articles_txt}\n\n"
        "Pour chaque signal important :\n"
        "1. SIGNAL : FORT / MODÉRÉ / FAIBLE\n"
        "2. INDICATEUR : quel indicateur macro ?\n"
        "3. LECTURE : que dit ce signal sur l'économie chinoise ?\n"
        "4. IMPACT CFO : conséquence sur revenus, coûts, change ou liquidité\n"
        "5. À SURVEILLER : quel prochain indicateur confirmerait ce signal ?\n\n"
        "Termine par :\n"
        "- SYNTHÈSE MACRO (5 lignes) : état de l'économie cette semaine\n"
        "- COMPARAISON APAC : comment la Chine se positionne vs la région ?\n"
        "- 3 POINTS D'ATTENTION pour le CFO cette semaine"
    )

    log.info(f"Envoi de {len(articles)} articles à DeepSeek via API REST...")
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",  # ou "deepseek-reasoner"
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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
        log.exception(f"Erreur lors de l'appel à DeepSeek : {e}")
        return f"Erreur d'analyse DeepSeek : {e}"


def generer_rapport(articles, analyse):
    """Génère le rapport final."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = [
        "=" * 62,
        f"  VEILLE ECONOMIQUE CHINE — {now}",
        "  Pour : CFO étranger / Couverture APAC",
        "  Modèle IA : DeepSeek",
        "=" * 62,
        "",
        f"  {len(articles)} signal(s) économique(s) détecté(s)",
        "",
        "  SOURCES SURVEILLÉES :",
    ]
    for s in RSS_SOURCES + SCRAPE_SOURCES:
        lignes.append(f"    - {s['nom']}")

    if articles:
        lignes += ["", "-" * 62, "  ARTICLES DU JOUR", "-" * 62]
        for i, a in enumerate(articles, 1):
            lignes.append(f"\n  [{i}] {a['source']}")
            lignes.append(f"      {a['titre']}")
            if a["lien"]:
                lignes.append(f"      {a['lien']}")

    lignes += [
        "", "-" * 62,
        "  ANALYSE ÉCONOMIQUE & POINTS D'ATTENTION CFO",
        "-" * 62,
        analyse,
        "", "=" * 62,
    ]
    return "\n".join(lignes)


def sauvegarder_rapport(rapport):
    """Sauvegarde le rapport dans le dossier rapports/."""
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"eco_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport : {fichier}")


def executer_agent():
    """Point d'entrée principal."""
    log.info("Démarrage agent veille économique Chine (enrichi sources chinoises)")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        pertinents = filtrer_pertinents(tous_articles, vus)
        log.info(f"Signaux pertinents et nouveaux : {len(pertinents)}")

        analyse = analyser_avec_deepseek(pertinents)
        rapport = generer_rapport(pertinents, analyse)
        print(rapport)
        sauvegarder_rapport(rapport)

        # Mise à jour du cache des articles vus
        for a in pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)

        log.info("Terminé.")
    except Exception as e:
        log.exception(f"Erreur générale : {e}")
        raise


if __name__ == "__main__":
    executer_agent()
