"""
Agent de veille économique Chine — CFO étranger APAC
=====================================================
Sources surveillées :
  - NBS    (National Bureau of Statistics) — PIB, IPI, PMI, CPI, PPI
  - PBOC   (Banque centrale) — politique monétaire, crédit, M2
  - MOFCOM (Commerce extérieur) — exports, imports, balance commerciale
  - World Bank China — indicateurs macro
  - Caixin PMI — PMI indépendant manufacturier & services

Fréquence : lundi à vendredi 8h Shanghai (00:00 UTC)
Livraison  : rapport .txt dans GitHub Artifacts

Variables d'environnement (GitHub Secrets) :
  ANTHROPIC_API_KEY
"""

import os, json, logging, hashlib
from datetime import datetime, timedelta
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


# ---------------------------------------------------------------------------
# Sources RSS / flux publics
# ---------------------------------------------------------------------------

SOURCES = [
    {
        "nom": "NBS China — Statistiques nationales",
        "url": "http://www.stats.gov.cn/english/rss/p1.xml",
        "tags": ["GDP", "CPI", "PPI", "PMI", "industrial", "retail", "employment"],
    },
    {
        "nom": "PBOC — Politique monétaire",
        "url": "http://www.pbc.gov.cn/en/3688110/index.rss",
        "tags": ["monetary", "credit", "M2", "loan", "interest rate", "RRR", "liquidity"],
    },
    {
        "nom": "MOFCOM — Commerce extérieur",
        "url": "http://english.mofcom.gov.cn/rss/article.xml",
        "tags": ["export", "import", "trade", "surplus", "deficit", "foreign trade"],
    },
    {
        "nom": "Xinhua Finance — Actualités économiques",
        "url": "http://www.xinhuanet.com/english/rss/economyAll.xml",
        "tags": ["economy", "growth", "GDP", "stimulus", "fiscal", "consumption"],
    },
    {
        "nom": "South China Morning Post — Économie",
        "url": "https://www.scmp.com/rss/5/feed",
        "tags": ["China economy", "growth", "PMI", "trade", "property", "consumption"],
    },
    {
        "nom": "Reuters — Chine & APAC",
        "url": "https://feeds.reuters.com/reuters/CNtopNews",
        "tags": ["China", "economy", "GDP", "PBOC", "stimulus", "trade", "yuan"],
    },
]

# Mots-clés économiques pertinents pour un CFO
KEYWORDS_ECO = [
    "GDP", "growth", "PMI", "CPI", "PPI", "inflation", "deflation",
    "export", "import", "trade surplus", "trade deficit",
    "consumption", "retail sales", "industrial output",
    "stimulus", "fiscal policy", "monetary policy",
    "interest rate", "RRR", "reserve ratio", "credit",
    "property", "real estate", "unemployment", "jobs",
    "yuan", "RMB", "exchange rate", "capital flow",
    "foreign investment", "FDI", "supply chain",
    "manufacturing", "services sector", "Caixin", "NBS",
]

# Indicateurs macro à surveiller — publiés mensuellement par NBS
INDICATEURS_NBS = {
    "GDP":              "Croissance du PIB",
    "CPI":              "Inflation consommateurs",
    "PPI":              "Inflation producteurs",
    "PMI Manufacturing":"PMI Manufacturier NBS",
    "PMI Services":     "PMI Services NBS",
    "Industrial Output":"Production industrielle",
    "Retail Sales":     "Ventes au détail",
    "Fixed Investment": "Investissement fixe",
    "Unemployment":     "Taux de chômage",
}


# ---------------------------------------------------------------------------
# Gestion des articles déjà vus
# ---------------------------------------------------------------------------

def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(vus), f)


# ---------------------------------------------------------------------------
# Récupération des flux RSS
# ---------------------------------------------------------------------------

def fetch_rss(source):
    articles = []
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent": "CFO-EcoAgent/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

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


# ---------------------------------------------------------------------------
# Analyse Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Tu es un économiste senior spécialisé en Chine et en zone APAC,
conseiller d'un CFO de multinationale étrangère basé à Shanghai.

Tu analyses les actualités et indicateurs économiques chinois et évalues leur impact
concret sur les décisions financières d'un CFO :
- Impact sur les revenus et la demande locale (consommation, secteur immobilier)
- Impact sur les coûts (inflation PPI, matières premières, logistique)
- Impact sur la politique de change et les flux financiers
- Signaux de politique monétaire ou fiscale à anticiper
- Comparaison avec les tendances APAC (Japon, Corée, ASEAN, Inde)

Ton analyse est :
- En français, ton professionnel et synthétique
- Structurée avec un niveau de signal : FORT / MODÉRÉ / FAIBLE
- Orientée décision CFO : que surveiller, que réviser, qu'anticiper ?
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
        f"Veille économique Chine — {date_str}\n"
        f"Nombre d'articles à analyser : {len(articles)}\n\n"
        f"{articles_txt}\n\n"
        "Pour chaque signal économique important, fournis :\n"
        "1. SIGNAL : FORT / MODÉRÉ / FAIBLE\n"
        "2. INDICATEUR : quel indicateur macro est concerné ?\n"
        "3. LECTURE : que nous dit ce chiffre sur l'économie chinoise ?\n"
        "4. IMPACT CFO : conséquence concrète sur les revenus, coûts, change ou liquidité\n"
        "5. À SURVEILLER : quel prochain indicateur ou événement confirmerait ou infirmerait ce signal ?\n\n"
        "Termine par :\n"
        "- SYNTHÈSE MACRO (5 lignes) : état de l'économie chinoise cette semaine\n"
        "- COMPARAISON APAC : comment la Chine se positionne-t-elle par rapport au reste de la région ?\n"
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


# ---------------------------------------------------------------------------
# Génération du rapport
# ---------------------------------------------------------------------------

def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = [
        "=" * 62,
        f"  VEILLE ECONOMIQUE CHINE — {now}",
        f"  Pour : CFO étranger / Couverture APAC",
        "=" * 62,
        f"\n  {len(articles)} signal(s) économique(s) détecté(s)",
        "\n  SOURCES SURVEILLÉES :",
    ]
    for s in SOURCES:
        lignes.append(f"    - {s['nom']}")

    if articles:
        lignes += ["\n" + "-" * 62, "  ARTICLES DU JOUR", "-" * 62]
        for i, a in enumerate(articles, 1):
            lignes.append(f"\n  [{i}] {a['source']}")
            lignes.append(f"      {a['titre']}")
            if a["lien"]:
                lignes.append(f"      {a['lien']}")

    lignes += [
        "\n" + "-" * 62,
        "  ANALYSE ÉCONOMIQUE & POINTS D'ATTENTION CFO",
        "-" * 62,
        analyse,
        "\n" + "=" * 62,
    ]
    return "\n".join(lignes)

def sauvegarder_rapport(rapport):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"eco_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport : {fichier}")


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------

def executer_agent():
    log.info("Démarrage agent veille économique Chine...")
    try:
        vus = charger_vus()
        tous_articles = []

        for source in SOURCES:
            articles = fetch_rss(source)
            log.info(f"{source['nom']} : {len(articles)} articles récupérés")
            tous_articles.extend(articles)

        pertinents = filtrer_pertinents(tous_articles, vus)
        log.info(f"Signaux pertinents et nouveaux : {len(pertinents)}")

        analyse = analyser_avec_claude(pertinents)
        rapport = generer_rapport(pertinents, analyse)

        print(rapport)
        sauvegarder_rapport(rapport)

        for a in pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)

        log.info("Terminé.")

    except anthropic.APIError as e:
        log.error(f"Claude : {e}")
    except Exception as e:
        log.exception(f"Erreur : {e}")


if __name__ == "__main__":
    executer_agent()
