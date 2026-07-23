from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import edge_tts
import feedparser
import requests
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
EPISODES = DOCS / "episodes"
TZ = ZoneInfo("America/Sao_Paulo")

ASSETS = {
    "Ibovespa": "^BVSP",
    "Dólar": "BRL=X",
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Treasury de 10 anos": "^TNX",
    "Petróleo Brent": "BZ=F",
    "Ouro": "GC=F",
    "Minério de ferro": "TIO=F",
    "Vale": "VALE3.SA",
    "Petrobras": "PETR4.SA"
}

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=mercados+financeiros+Brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=global+markets+Federal+Reserve+oil&hl=pt-BR&gl=BR&ceid=BR:pt-419"
]


def safe_number(value):
    try:
        n = float(value)
        return None if math.isnan(n) else n
    except (TypeError, ValueError):
        return None


def market_snapshot():
    result = {}
    for label, ticker in ASSETS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
            closes = [safe_number(v) for v in hist["Close"].tolist()]
            closes = [v for v in closes if v is not None]
            if not closes:
                raise ValueError("sem cotação")
            last = closes[-1]
            previous = closes[-2] if len(closes) > 1 else last
            change = ((last / previous) - 1) * 100 if previous else 0
            result[label] = {"value": last, "change": change, "ticker": ticker}
        except Exception as exc:
            result[label] = {"value": None, "change": None, "ticker": ticker, "error": str(exc)}
    return result


def selic():
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1178/dados/ultimos/1?formato=json"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return float(response.json()[0]["valor"].replace(",", "."))
    except Exception:
        return None


def headlines(limit=5):
    items = []
    for url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:limit]:
                title = re.sub(r"\s+-\s+[^-]+$", "", entry.title).strip()
                if title and title not in items:
                    items.append(title)
        except Exception:
            continue
    return items[:limit]


def br_number(value, decimals=2):
    if value is None:
        return "indisponível"
    raw = f"{value:,.{decimals}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def direction(change):
    if change is None:
        return "sem variação confirmada"
    if change > 0.04:
        return f"em alta de {br_number(abs(change))} por cento"
    if change < -0.04:
        return f"em queda de {br_number(abs(change))} por cento"
    return "praticamente estável"


def spoken_asset(label, item):
    if item["value"] is None:
        return f"A cotação de {label} não estava disponível na coleta."
    value = br_number(item["value"])
    return f"{label}: {value}; {direction(item['change'])}."


def build_script(edition, snapshot, selic_value, news, now):
    opening = edition == "abertura"
    intro = (
        f"Bom dia. Este é o Market Brief Brasil, edição de abertura de {now:%d/%m/%Y}."
        if opening else
        f"Boa noite. Este é o Market Brief Brasil, edição de fechamento de {now:%d/%m/%Y}."
    )
    parts = [intro, "Vamos aos principais números disponíveis no horário desta gravação."]
    order = ["Ibovespa", "Dólar", "S&P 500", "Nasdaq", "Treasury de 10 anos", "Petróleo Brent", "Ouro", "Minério de ferro"]
    parts.extend(spoken_asset(label, snapshot[label]) for label in order)
    if selic_value is not None:
        parts.append(f"A taxa de referência consultada no Banco Central está em {br_number(selic_value)} por cento ao ano.")
    winners = [(k, v["change"]) for k, v in snapshot.items() if v["change"] is not None]
    winners.sort(key=lambda x: x[1], reverse=True)
    if winners:
        top, change = winners[0]
        bottom, bottom_change = winners[-1]
        parts.append(f"Entre os ativos acompanhados, o maior avanço foi de {top}, com {br_number(change)} por cento.")
        if bottom_change < 0:
            parts.append(f"Na ponta negativa, {bottom} recuou {br_number(abs(bottom_change))} por cento.")
    if news:
        parts.append("No noticiário, estes são os temas que merecem acompanhamento.")
        parts.extend(f"{idx}. {headline}." for idx, headline in enumerate(news, 1))
    if opening:
        parts.append("Ao longo do dia, observe a reação do câmbio, da curva de juros e das ações ligadas a commodities. Compare sempre dados intradiários com referências do mesmo horário.")
    else:
        parts.append("Para o próximo pregão, acompanhe a continuidade dos movimentos em juros, câmbio e commodities, além de novos dados econômicos e resultados corporativos.")
    parts.append("As informações têm finalidade informativa e não representam recomendação de investimento.")
    return "\n\n".join(parts)


def ensure_cover():
    path = DOCS / "cover.png"
    if path.exists():
        return
    DOCS.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1400, 1400), "#07182c")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 104)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        title_font = small_font = ImageFont.load_default()
    draw.rectangle((90, 90, 1310, 1310), outline="#45d4e8", width=8)
    draw.text((145, 420), "MARKET", fill="white", font=title_font)
    draw.text((145, 545), "BRIEF BRASIL", fill="#45d4e8", font=title_font)
    draw.text((150, 735), "Abertura e fechamento", fill="#c8d7e7", font=small_font)
    draw.text((150, 800), "dos mercados", fill="#c8d7e7", font=small_font)
    image.save(path, "PNG")


def duration_seconds(mp3_path):
    # O feed aceita duração aproximada; evita dependência de ffprobe no runner.
    return max(60, int(mp3_path.stat().st_size * 8 / 48000))


def rebuild_feed(config):
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    base = config["feed_base_url"].rstrip("/")
    for tag, text in [("title", config["title"]), ("link", base), ("language", config["language"]), ("description", config["description"]), ("lastBuildDate", format_datetime(datetime.now(timezone.utc)))]:
        ET.SubElement(channel, tag).text = text
    ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}author").text = config["author"]
    ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"
    ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image", {"href": f"{base}/cover.png"})
    meta_files = sorted(EPISODES.glob("*.json"), reverse=True)[: config["max_episodes"]]
    for meta_path in meta_files:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        item = ET.SubElement(channel, "item")
        for tag, text in [("title", meta["title"]), ("description", meta["description"]), ("guid", meta["guid"]), ("pubDate", meta["pub_date"])]:
            ET.SubElement(item, tag).text = text
        ET.SubElement(item, "enclosure", {"url": f"{base}/episodes/{meta['audio']}", "length": str(meta["bytes"]), "type": "audio/mpeg"})
        ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration").text = str(meta["duration"])
        ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(DOCS / "feed.xml", encoding="utf-8", xml_declaration=True)


async def synthesize(text, path, voice, rate):
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=["abertura", "fechamento"], required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(TZ)
    EPISODES.mkdir(parents=True, exist_ok=True)
    ensure_cover()
    snapshot = market_snapshot()
    script = build_script(args.edition, snapshot, selic(), headlines(), now)
    slug = f"{now:%Y-%m-%d}-{args.edition}"
    audio_path = EPISODES / f"{slug}.mp3"
    asyncio.run(synthesize(script, audio_path, config["voice"], config["rate"]))
    title = f"{args.edition.capitalize()} — {now:%d/%m/%Y}"
    metadata = {
        "title": title,
        "description": f"Market Brief Brasil: edição de {args.edition}.",
        "guid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"market-brief-brasil/{slug}")),
        "pub_date": format_datetime(now.astimezone(timezone.utc)),
        "audio": audio_path.name,
        "bytes": audio_path.stat().st_size,
        "duration": duration_seconds(audio_path)
    }
    (EPISODES / f"{slug}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (EPISODES / f"{slug}.txt").write_text(script, encoding="utf-8")
    rebuild_feed(config)
    print(json.dumps({"edition": args.edition, "audio": str(audio_path), "assets": snapshot}, ensure_ascii=False))


if __name__ == "__main__":
    main()

