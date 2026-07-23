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

COMMON_ASSETS = {
    "Ibovespa": "^BVSP",
    "Dólar": "BRL=X",
    "Treasury de 10 anos": "^TNX",
    "Petróleo Brent": "BZ=F",
    "Ouro": "GC=F",
    "Minério de ferro": "TIO=F",
    "Vale": "VALE3.SA",
    "Petrobras": "PETR4.SA"
}

OPENING_ASSETS = {
    "Futuro do S&P 500": "ES=F",
    "Futuro do Nasdaq": "NQ=F"
}

CLOSING_ASSETS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC"
}

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=Ibovespa+dólar+juros+mercado+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=global+markets+Federal+Reserve+Treasury+oil+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419"
]

NEWS_TERMS = {
    "ibovespa", "dólar", "juros", "selic", "inflação", "mercado", "bolsa",
    "fed", "federal reserve", "treasury", "petróleo", "brent", "ouro",
    "vale", "petrobras", "china", "tarifa", "nasdaq", "s&p"
}

SPOKEN_LABELS = {
    "S&P 500": "Ésse e Pê quinhentos",
    "Futuro do S&P 500": "Futuro do Ésse e Pê quinhentos",
    "Nasdaq": "Náz-dac",
    "Futuro do Nasdaq": "Futuro do Náz-dac",
    "Treasury de 10 anos": "Juro do título americano de dez anos",
    "Petróleo Brent": "Petróleo Brênt"
}


def safe_number(value):
    try:
        n = float(value)
        return None if math.isnan(n) else n
    except (TypeError, ValueError):
        return None


def market_snapshot(edition):
    result = {}
    assets = COMMON_ASSETS | (OPENING_ASSETS if edition == "abertura" else CLOSING_ASSETS)
    for label, ticker in assets.items():
        try:
            hist = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
            closes = [safe_number(v) for v in hist["Close"].tolist()]
            closes = [v for v in closes if v is not None]
            if not closes:
                raise ValueError("sem cotação")
            last = closes[-1]
            previous = closes[-2] if len(closes) > 1 else last
            change = ((last / previous) - 1) * 100 if previous else 0
            timestamp = hist.index[-1]
            reference_date = timestamp.strftime("%d/%m") if hasattr(timestamp, "strftime") else ""
            result[label] = {"value": last, "change": change, "previous": previous, "ticker": ticker, "reference_date": reference_date}
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


def headline_too_similar(title, existing):
    stopwords = {"a", "o", "e", "de", "da", "do", "em", "com", "para", "por", "um", "uma"}
    words = {w for w in re.findall(r"[a-zá-ú0-9]+", title.casefold()) if w not in stopwords and len(w) > 2}
    for previous in existing:
        previous_words = {w for w in re.findall(r"[a-zá-ú0-9]+", previous.casefold()) if w not in stopwords and len(w) > 2}
        union = words | previous_words
        if union and len(words & previous_words) / len(union) >= 0.38:
            return True
    return False


def headline_has_bad_fx_reference(title, usd_value):
    if not usd_value:
        return False
    matches = re.findall(r"R\$\s*(\d+[,.]\d+)", title, flags=re.IGNORECASE)
    for match in matches:
        quoted = float(match.replace(",", "."))
        if abs(quoted / usd_value - 1) > 0.025:
            return True
    return False


def headlines(limit=4, usd_value=None):
    items = []
    for url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:limit]:
                title = re.sub(r"\s+-\s+[^-]+$", "", entry.title).strip(" .")
                normalized = title.casefold()
                relevant = sum(term in normalized for term in NEWS_TERMS)
                noisy = any(term in normalized for term in ("como funciona", "saiba como", "guia", "portal nacional"))
                if (title and relevant >= 1 and not noisy and title not in items
                        and not headline_has_bad_fx_reference(title, usd_value)
                        and not headline_too_similar(title, items)):
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


def spoken_asset(label, item, edition):
    spoken_label = SPOKEN_LABELS.get(label, label)
    if item["value"] is None:
        return f"A cotação de {spoken_label} não estava disponível na coleta."
    reference = "com base na cotação mais recente" if edition == "abertura" and ("Futuro" in label or label in {"Dólar", "Petróleo Brent", "Ouro"}) else "com base no último fechamento disponível"
    if label == "Dólar":
        value = br_number(item["value"], 4)
        return f"Dólar contra o real: {value}; {direction(item['change'])}, {reference}."
    if label == "Treasury de 10 anos":
        bps = (item["value"] - item["previous"]) * 100
        move = f"alta de {br_number(abs(bps), 1)} pontos-base" if bps > 0.05 else f"queda de {br_number(abs(bps), 1)} pontos-base" if bps < -0.05 else "estabilidade"
        return f"{spoken_label}: yield de {br_number(item['value'], 3)} por cento ao ano, com {move} sobre o fechamento anterior."
    value = br_number(item["value"])
    return f"{spoken_label}: {value}; {direction(item['change'])}, {reference}."


def build_script(edition, snapshot, selic_value, news, now):
    opening = edition == "abertura"
    intro = (
        f"Bom dia. Este é o Market Brief Brasil, edição de abertura de {now:%d/%m/%Y}."
        if opening else
        f"Boa noite. Este é o Market Brief Brasil, edição de fechamento de {now:%d/%m/%Y}."
    )
    parts = [intro, f"Horário de referência: {now:%H:%M}, em São Paulo. Vamos aos principais números disponíveis."]
    equity_labels = ["Futuro do S&P 500", "Futuro do Nasdaq"] if opening else ["S&P 500", "Nasdaq"]
    order = ["Ibovespa", "Dólar", *equity_labels, "Treasury de 10 anos", "Petróleo Brent", "Ouro", "Minério de ferro"]
    parts.extend(spoken_asset(label, snapshot[label], edition) for label in order)
    if selic_value is not None:
        parts.append(f"A taxa de referência consultada no Banco Central está em {br_number(selic_value)} por cento ao ano.")
    winners = [(k, v["change"]) for k, v in snapshot.items() if v["change"] is not None and k != "Treasury de 10 anos"]
    winners.sort(key=lambda x: x[1], reverse=True)
    if winners:
        top, change = winners[0]
        bottom, bottom_change = winners[-1]
        parts.append(f"Entre os ativos acompanhados, o maior avanço foi de {top}, com {br_number(change)} por cento.")
        if bottom_change < 0:
            parts.append(f"Na ponta negativa, {bottom} recuou {br_number(abs(bottom_change))} por cento.")
    if news:
        parts.append("No noticiário das últimas vinte e quatro horas, estes são os temas que merecem acompanhamento. As manchetes são uma triagem inicial e devem ser confirmadas nas fontes originais.")
        parts.extend(f"{idx}. {headline}." for idx, headline in enumerate(news, 1))
    if opening:
        global_risk = snapshot.get("Treasury de 10 anos", {}).get("value")
        brent_change = snapshot.get("Petróleo Brent", {}).get("change")
        if global_risk and brent_change is not None:
            parts.append(f"A leitura cruzada mostra o juro americano em {br_number(global_risk, 3)} por cento e o Brent {direction(brent_change)}. Essa combinação pode influenciar inflação, câmbio e ações ligadas a commodities durante o pregão.")
        parts.append("Ao longo do dia, observe a reação do câmbio, da curva de juros e das ações ligadas a commodities. Os índices brasileiros citados antes da abertura representam o último fechamento, enquanto futuros e ativos globais podem estar em negociação.")
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
    snapshot = market_snapshot(args.edition)
    script = build_script(args.edition, snapshot, selic(), headlines(usd_value=snapshot.get("Dólar", {}).get("value")), now)
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
