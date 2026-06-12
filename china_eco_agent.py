"""
Agent de veille économique Chine — CFO étranger APAC
=====================================================
Sources : IMF, World Bank, OECD, Caixin, BBC Business, SCMP
Fréquence : lundi à vendredi 8h Shanghai (00:00 UTC)
"""

import os, json, logging, hashlib
from datetime import datetime
from pathlib import Path

import requests
import anthropic
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

LOG_FILE  = Path("logs/agent_eco.log")
SEEN_FILE = Path("seen_eco_articles.json")

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)


SOURCES = [
    {
        "nom": "IMF — Fonds monétaire international",
        "url": "https://www.imf.org/en/News/rss?language=eng",
        "tags": ["China", "Asia", "GDP", "growth", "inflation", "monetary", "fiscal"],
    },
    {
        "nom": "World Bank — Banque mondiale",
        "url": "https://blogs.worldbank.org/rss.xml",
        "tags": ["China", "Asia", "economy", "growth", "trade", "development"],
    },
    {
        "nom": "OECD — Organisation de coopération économique",
        "url": "https://www.oecd.org/newsroom/news.rss",
        "tags": ["China", "Asia", "GDP", "PMI", "inflation", "trade", "APAC"],
    },
    {
        "nom": "Caixin — Presse économique chinoise",
        "url": "https://www.caixinglobal.com/rss/all.xml",
        "tags": ["China", "economy", "PMI", "GDP", "trade", "yuan", "PBOC", "property"],
    },
    {
        "nom": "BBC Business — Actualités mondiales",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "tags": ["China", "Asia", "economy", "trade", "yuan", "growth", "inflation"],
    },
    {
        "nom": "South China Morning Post — Économie",
        "url": "https://www.scmp.com/rss/5/feed",
        "tags": ["China", "economy", "GDP", "PMI", "trade", "property", "consumption"],
    },
]

KEYWORDS_ECO = [
    "China", "GDP", "growth", "PMI", "CPI", "PPI", "inflation", "deflation",
    "export", "import", "trade", "consumption", "retail", "industrial",
    "stimulus", "fiscal", "monetary", "interest rate", "reserve",
    "yuan", "RMB", "PBOC", "property", "real estate", "unemployment",
    "Caixin", "NBS", "APAC", "Asia", "supply chain", "manufacturing",
    "credit", "liquidity", "foreign investment", "FDI",
]


def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(vus), f)


def fetch_rss(source):
    articles = []
    try:
        resp = requests.get(
            source["url"], timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CFO-EcoAgent/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml",
            }
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = (root.findall(".//item") or
                 root.findall(".//{http://www.w3.org/2005/Atom}entry"))

        for item in items[:20]:
            titre = (
                getattr(item.find("title"), "text", "") or
                getattr(item.find("{http://www.w3.org/2005/Atom}title"), "text", "") or ""
            ).strip()
            lien = (
                getattr(item.find("link"), "text", "") or
                getattr(item.find("{http://www.w3.org/2005/Atom}link"), "attrib", {}).get("href", "") or ""
            ).strip()
            desc = (
                getattr(item.find("description"), "text", "") or
                getattr(item.find("{http://www.w3.org/2005/Atom}summary"), "text", "") or ""
            ).strip()
            date_str = (
                getattr(item.find("pubDate"), "text", "") or
                getattr(item.find("{http://www.w3.org/2005/Atom}updated"), "text", "") or ""
            ).strip()

            if titre:
                articles.append({
                    "source": source["nom"],
                    "titre":  titre,
                    "lien":   lien,
                    "desc":   desc[:600],
                    "date":   date_str,
                    "id":     hashlib.md5((titre + lien).encode()).hexdigest(),
                })
    except Exception as e:
        log.warning(f"Erreur fetch {source['nom']} : {e}")
    return articles


def filtrer_pertinents(articles, vus):
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a["desc"]).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_ECO):
            nouveaux.append(a)
    return nouveaux


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

def analyser_avec_claude(articles):
    if not articles:
        return "Aucun signal économique significatif détecté aujourd'hui."

    client   = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    date_str = datetime.now().strftime("%d %B %Y")

    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += (
            f"\n[{i}] Source : {a['source']}\n"
            f"    Titre : {a['titre']}\n"
            f"    Date  : {a['date']}\n"
            f"    Lien  : {a['lien']}\n"
            f"    Résumé: {a['desc']}\n"
        )

    prompt = (
        "Veille économique Chine — " + date_str + "\n"
        "Nombre d'articles : " + str(len(articles)) + "\n\n"
        + articles_txt +
        "\nPour chaque signal important :\n"
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

    log.info(f"Envoi de {len(articles)} articles à Claude...")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = [
        "=" * 62,
        "  VEILLE ECONOMIQUE CHINE — " + now,
        "  Pour : CFO étranger / Couverture APAC",
        "=" * 62,
        "",
        "  " + str(len(articles)) + " signal(s) économique(s) détecté(s)",
        "",
        "  SOURCES SURVEILLÉES :",
    ]
    for s in SOURCES:
        lignes.append("    - " + s["nom"])

    if articles:
        lignes += ["", "-" * 62, "  ARTICLES DU JOUR", "-" * 62]
        for i, a in enumerate(articles, 1):
            lignes.append("\n  [" + str(i) + "] " + a["source"])
            lignes.append("      " + a["titre"])
            if a["lien"]:
                lignes.append("      " + a["lien"])

    lignes += [
        "", "-" * 62,
        "  ANALYSE ÉCONOMIQUE & POINTS D'ATTENTION CFO",
        "-" * 62,
        analyse,
        "", "=" * 62,
    ]
    return "\n".join(lignes)

def sauvegarder_rapport(rapport):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / ("eco_chine_" + datetime.now().strftime("%Y%m%d_%H%M") + ".txt")
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info("Rapport : " + str(fichier))


def executer_agent():
    log.info("Démarrage agent veille économique Chine...")
    try:
        vus = charger_vus()
        tous_articles = []

        for source in SOURCES:
            articles = fetch_rss(source)
            log.info(source["nom"] + " : " + str(len(articles)) + " articles récupérés")
            tous_articles.extend(articles)

        pertinents = filtrer_pertinents(tous_articles, vus)
        log.info("Signaux pertinents : " + str(len(pertinents)))

        analyse = analyser_avec_claude(pertinents)
        rapport = generer_rapport(pertinents, analyse)

        print(rapport)
        sauvegarder_rapport(rapport)

        for a in pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)

        log.info("Terminé.")

    except anthropic.APIError as e:
        log.error("Claude : " + str(e))
    except Exception as e:
        log.exception("Erreur : " + str(e))


if __name__ == "__main__":
    executer_agent()
