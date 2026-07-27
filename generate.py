from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import edge_tts
import feedparser
import requests
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo

from editorial_validation import normalize_audit, validate_audit, validate_episode

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
            quote = yf.Ticker(ticker)
            hist = quote.history(period="7d", interval="1d", auto_adjust=False)
            closes = [safe_number(v) for v in hist["Close"].tolist()]
            closes = [v for v in closes if v is not None]
            if not closes:
                raise ValueError("sem cotação")
            last = closes[-1]
            previous = closes[-2] if len(closes) > 1 else last
            quote_kind = "último fechamento"

            # Na abertura, ativos globais e câmbio já estão negociando. O candle
            # diário de futuros pode misturar contratos e produzir falsos gaps.
            if edition == "abertura" and label in {
                "Dólar", "Treasury de 10 anos", "Petróleo Brent", "Ouro",
                "Futuro do S&P 500", "Futuro do Nasdaq",
            }:
                intraday = quote.history(period="2d", interval="5m", auto_adjust=False)
                intraday_closes = [safe_number(v) for v in intraday["Close"].tolist()]
                intraday_closes = [v for v in intraday_closes if v is not None]
                if intraday_closes:
                    last = intraday_closes[-1]
                    quote_kind = "intradiária"
                fast_previous = safe_number(getattr(quote.fast_info, "previous_close", None))
                if fast_previous:
                    previous = fast_previous
            change = ((last / previous) - 1) * 100 if previous else 0
            # Movimentos desse tamanho em poucas horas normalmente indicam rolagem
            # de contrato ou dado inconsistente. Melhor omitir do que narrar errado.
            max_opening_move = 5.0 if label in {"Petróleo Brent", "Ouro"} else 3.0
            if edition == "abertura" and quote_kind == "intradiária" and abs(change) > max_opening_move:
                change = None
            timestamp = hist.index[-1]
            reference_date = timestamp.strftime("%d/%m/%Y") if hasattr(timestamp, "strftime") else ""
            collected_at = datetime.now(TZ).isoformat()
            result[label] = {
                "value": last, "change": change, "previous": previous,
                "ticker": ticker, "reference_date": reference_date,
                "quote_kind": quote_kind,
                "instrument": ticker,
                "collected_at": collected_at,
                "source": "Yahoo Finance",
                "source_url": f"https://finance.yahoo.com/quote/{ticker}",
            }
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


def entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(TZ)


def headlines(limit=8, usd_value=None, now=None, edition="abertura"):
    now = now or datetime.now(TZ)
    # A abertura deve explicar o que está acontecendo hoje. Aceita madrugada e
    # primeiras horas da manhã; fatos de ontem entram somente se publicados após
    # o fechamento e ainda forem relevantes para a sessão atual.
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if edition == "abertura":
        cutoff -= timedelta(hours=6)
    else:
        cutoff = now.replace(hour=6, minute=0, second=0, microsecond=0)
    items = []
    for url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:limit]:
                published_at = entry_datetime(entry)
                if published_at is None or published_at < cutoff or published_at > now + timedelta(minutes=10):
                    continue
                title = re.sub(r"\s+-\s+[^-]+$", "", entry.title).strip(" .")
                normalized = title.casefold()
                relevant = sum(term in normalized for term in NEWS_TERMS)
                noisy = any(term in normalized for term in ("como funciona", "saiba como", "guia", "portal nacional"))
                if (title and relevant >= 1 and not noisy and title not in items
                        and not headline_has_bad_fx_reference(title, usd_value)
                        and not headline_too_similar(
                            title, [item["titulo"] for item in items]
                        )):
                    items.append({
                        "titulo": title,
                        "publicado_em": published_at.isoformat(),
                        "fonte": entry.get("source", {}).get("title", "Google News"),
                        "url": entry.get("link", ""),
                    })
        except Exception:
            continue
    return items[:limit]


EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "roteiro": {"type": "string"},
        "auditoria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["cotacao", "noticia", "agenda"]},
                    "item": {"type": "string"},
                    "valor_ou_fato": {"type": "string"},
                    "data": {"type": "string"},
                    "horario": {"type": "string"},
                    "instrumento": {"type": "string"},
                    "fonte": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": [
                    "tipo",
                    "item",
                    "valor_ou_fato",
                    "data",
                    "horario",
                    "instrumento",
                    "fonte",
                    "url",
                ],
            },
        },
        "aprovado": {"type": "boolean"},
        "erros": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["roteiro", "auditoria", "aprovado", "erros"],
}


def gemini_request(url, headers, payload, attempts=3):
    """Repete falhas transitórias; erros editoriais continuam bloqueantes."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            wait_seconds = attempt * 2
            print(
                f"Gemini indisponível na tentativa {attempt}/{attempts}; "
                f"nova tentativa em {wait_seconds}s: {exc}"
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"Gemini falhou após {attempts} tentativas: {last_error}")


def response_text(response_data):
    candidates = response_data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini não retornou candidato")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise ValueError("Gemini retornou resposta vazia")
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)


def grounded_search_queries(response_data):
    candidates = response_data.get("candidates", [])
    if not candidates:
        return []
    metadata = candidates[0].get("groundingMetadata", {})
    return metadata.get("webSearchQueries", [])


def canonicalize_script(edition, text):
    reviewed = re.sub(
        r"^(?:\s*(?:Bom dia|Boa noite)\.?\s*)+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    reviewed = re.sub(
        r"(?:\s*(?:Bom dia|Boa noite)\.?\s*)+$",
        "",
        reviewed,
        flags=re.IGNORECASE,
    ).strip()
    disclaimer = (
        "Este conteúdo tem caráter exclusivamente informativo e não constitui "
        "recomendação de investimento."
    )
    reviewed = re.sub(
        r"\s*(?:As informações têm finalidade informativa e não representam "
        r"recomendação de investimento|Este conteúdo tem caráter exclusivamente "
        r"informativo e não constitui recomendação de investimento)\.?\s*$",
        "",
        reviewed,
        flags=re.IGNORECASE,
    ).strip()
    greeting = "Bom dia" if edition == "abertura" else "Boa noite"
    return f"{greeting}. {reviewed}\n\n{disclaimer}"


def review_script(url, headers, edition, facts, script, audit, now):
    candidate = script
    validation_feedback = ""
    for attempt in range(1, 3):
        review_prompt = f"""
Atue como revisor factual do Market Brief Brasil. Reescreva o roteiro abaixo
mantendo apenas afirmações sustentadas pelos DADOS AUTORIZADOS e pela FICHA DE
AUDITORIA. Esta é a tentativa {attempt} de 2.

REGRAS:
- Não acrescente nenhum fato, agente, fluxo, expectativa, número ou causa.
- Uma causalidade só pode permanecer quando estiver sustentada pela auditoria.
- Caso a relação seja apenas simultânea, use "em meio a" ou "ao mesmo tempo".
- Preserve números, datas, horários, instrumentos e a diferença entre cotação
  atual, ajuste, último negócio e fechamento.
- Se uma direção não estiver confirmada, omita a direção; não tente conciliá-la.
- Produza de 450 a 650 palavras, em texto corrido natural para áudio.
- Comece exatamente com {"Bom dia." if edition == "abertura" else "Boa noite."}.
- Termine exatamente com o aviso informativo presente no roteiro.
- Não use Markdown, links, listas ou comentários.
{validation_feedback}

EDIÇÃO: {edition}
DADOS AUTORIZADOS:
{json.dumps(facts, ensure_ascii=False, default=str)}

FICHA DE AUDITORIA:
{json.dumps(audit, ensure_ascii=False, default=str)}

ROTEIRO A REVISAR:
{candidate}
""".strip()
        review_payload = {
            "contents": [{"parts": [{"text": review_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 3200,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }
        reviewed = canonicalize_script(
            edition,
            response_text(gemini_request(url, headers, review_payload)),
        )
        try:
            validate_episode(edition, reviewed, audit, now)
            return reviewed
        except ValueError as exc:
            if attempt == 2:
                raise
            validation_feedback = (
                "\nA versão anterior foi reprovada pelo validador local: "
                f"{exc}. Corrija somente esses pontos sem introduzir fatos."
            )
            candidate = reviewed
    raise RuntimeError("revisor não produziu roteiro válido")


def editorial_script(edition, snapshot, selic_value, news, now):
    """Pesquisa, gera roteiro auditado e bloqueia a publicação em caso de falha."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY ausente; episódio bloqueado antes do áudio")

    opening = edition == "abertura"
    objective = (
        "Priorize de três a cinco destaques capazes de influenciar o pregão: exterior, "
        "agenda econômica, juros, câmbio, commodities e empresas. Use cotações apenas "
        "quando derem contexto; não faça uma leitura sequencial de todos os números."
        if opening else
        "Apresente as principais cotações de forma condensada e depois explique de três "
        "a cinco destaques do dia, maiores movimentos e o que acompanhar no próximo pregão."
    )
    facts = {
        "edicao": edition,
        "data_hora_sao_paulo": now.isoformat(),
        "cotacoes": snapshot,
        "selic": selic_value,
        "manchetes_selecionadas": news,
    }
    prompt = f"""
Você é o editor-chefe e roteirista do Market Brief Brasil. Produza a edição de
{edition} de {now:%d/%m/%Y}, executada às {now:%H:%M} no fuso America/Sao_Paulo.

Antes de escrever, use obrigatoriamente a ferramenta Google Search para verificar
as cotações, notícias e a agenda. Os DADOS INICIAIS abaixo são pistas de pesquisa,
não autorização para repetir um número sem confirmação na web.

OBJETIVO DA EDIÇÃO:
{objective}

REGRAS OBRIGATÓRIAS:
- Não use memória para dados atuais. Abra e confronte fontes antes de escrever.
- Priorize fontes oficiais, Reuters, bolsas e provedores financeiros reconhecidos.
- Confirme cada cotação essencial em duas fontes independentes quando possível.
- Cada número narrado deve possuir na auditoria data no formato DD/MM/AAAA,
  horário aproximado, instrumento exato, fonte e URL.
- Se um dado não puder ser confirmado, diga que não encontrou confirmação ou omita-o.
- Não trate o fechamento anterior como movimento de hoje.
- Na abertura, não chame PTAX, dólar futuro ou futuro de Ibovespa de cotação atual
  antes da abertura da respectiva sessão. Identifique explicitamente o ajuste anterior.
- Nunca misture spot, PTAX, futuro, DXY, vencimentos de futuros, último negócio e ajuste.
- Um tema recorrente só pode voltar quando houver fato novo, nova reação ou novo impacto.
- Priorize acontecimentos publicados na data da edição. Não diga "hoje" sobre
  movimento cuja referência seja o fechamento anterior.
- A direção de preço vem exclusivamente de "cotacoes". Manchetes dão contexto,
  mas nunca substituem, corrigem ou contradizem a variação numérica.
- Se "change" for nulo, informe apenas o preço e diga que a direção não foi
  confirmada; não infira alta ou queda pelo texto das manchetes.
- Se uma manchete divergir da cotação, omita a direção presente na manchete.
- Não invente relações de causa e efeito. Só diga que um fato explica um movimento se
  essa relação estiver explícita numa manchete; caso contrário, use "em meio a" ou
  "é um ponto de atenção".
- Reescreva as manchetes; não as leia como uma lista e não mencione numeração.
- Explique brevemente por que cada destaque importa para o investidor brasileiro.
- Corrija concordância, pontuação e fluidez. Evite siglas sem explicação e frases longas.
- Preserve a diferença entre cotação em tempo real e último fechamento disponível.
- O roteiro não deve conter Markdown, links, ficha de auditoria nem instruções de locução.
- Comece com Bom dia na abertura e Boa noite no fechamento.
- Produza de 450 a 650 palavras. A revisão local reprova menos de 360 palavras.
- Termine exatamente com: "Este conteúdo tem caráter exclusivamente informativo e
  não constitui recomendação de investimento."

ESTRUTURA DA ABERTURA:
gancho; pré-abertura global e transmissão para o Brasil; até três fatos relevantes
do Brasil; até três vetores internacionais; agenda e riscos de hoje com horário de
Brasília; síntese sem repetir cotações.

ESTRUTURA DO FECHAMENTO:
gancho; placar do pregão; empresas e catalisadores confirmados; macro do dia;
exterior no horário da consulta sem chamar mercado aberto de fechamento; agenda
confirmada de amanhã; pergunta central para o próximo pregão.

CRITÉRIOS DE REPROVAÇÃO AUTOMÁTICA:
data incorreta; cotação essencial sem fonte ou horário; mistura de instrumentos;
direção contraditória; contratos diferentes usados numa variação; notícia antiga
tratada como fato novo; agenda na data errada; causalidade sem sustentação; menos
de 360 palavras; ausência do aviso final. Se ocorrer qualquer um deles, marque
"aprovado": false e liste os erros. É preferível bloquear a publicação.

DADOS INICIAIS PARA CONFERÊNCIA:
{json.dumps(facts, ensure_ascii=False, default=str)}
""".strip()

    model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "maxOutputTokens": 5000,
            "thinkingConfig": {"thinkingLevel": "minimal"},
            "responseMimeType": "application/json",
            "responseSchema": EDITORIAL_SCHEMA,
        },
    }
    try:
        research_response = gemini_request(url, headers, payload)
        queries = grounded_search_queries(research_response)
        if not queries:
            raise ValueError("Google Search não foi executado; pesquisa obrigatória ausente")
        result = json.loads(response_text(research_response))
        script = str(result.get("roteiro", "")).strip()
        audit = normalize_audit(result.get("auditoria", []), now)
        if not result.get("aprovado", False):
            model_errors = [str(error) for error in result.get("erros", [])]
            non_recoverable = [
                error for error in model_errors
                if not re.search(r"palavr|curt|extens|dura", error, flags=re.IGNORECASE)
            ]
            if non_recoverable:
                raise ValueError(
                    "auditoria editorial reprovou: " + "; ".join(non_recoverable)
                )
        if not script:
            raise ValueError("roteiro editorial vazio")
        validate_audit(audit, now)
        print(
            f"Pesquisa executada com {len(queries)} consulta(s); "
            f"auditoria recebida com {len(audit)} item(ns)."
        )
        reviewed = review_script(url, headers, edition, facts, script, audit, now)
        print(f"Roteiro editorial revisado com {len(reviewed)} caracteres.")
        print(f"Roteiro editorial gerado com {model}.")
        return reviewed, audit
    except Exception as exc:
        raise RuntimeError(f"episódio bloqueado pela camada editorial: {exc}") from exc


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
        parts.extend(
            f"{idx}. {headline['titulo']} (publicada às "
            f"{datetime.fromisoformat(headline['publicado_em']):%H:%M})."
            for idx, headline in enumerate(news, 1)
        )
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
    selic_value = selic()
    news = headlines(
        usd_value=snapshot.get("Dólar", {}).get("value"),
        now=now,
        edition=args.edition,
    )
    script, audit = editorial_script(args.edition, snapshot, selic_value, news, now)
    slug = f"{now:%Y-%m-%d}-{args.edition}"
    audit_path = EPISODES / f"{slug}-auditoria.json"
    audit_path.write_text(
        json.dumps(
            {
                "edition": args.edition,
                "generated_at": now.isoformat(),
                "approved": True,
                "items": audit,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
