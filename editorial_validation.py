import re
from urllib.parse import urlparse


MIN_WORDS = 360
DISCLAIMER = (
    "Este conteúdo tem caráter exclusivamente informativo e não constitui "
    "recomendação de investimento."
)


def word_count(script):
    return len(re.findall(r"\b[\wÀ-ÿ]+\b", script))


def normalize_audit(audit, now):
    """Normaliza formatos inequívocos sem inventar o dia ou o mês da fonte."""
    if not isinstance(audit, list):
        return audit

    normalized = []
    for original in audit:
        if not isinstance(original, dict):
            normalized.append(original)
            continue
        row = dict(original)
        date = str(row.get("data", "")).strip()
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", date)
        if match:
            row["data"] = f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{now.year}"
        normalized.append(row)
    return normalized


def audit_errors(audit, now):
    errors = []
    if not isinstance(audit, list) or not audit:
        return ["ficha de auditoria ausente"]

    required = {"item", "data", "horario", "fonte", "url"}
    allowed_years = {now.year - 1, now.year, now.year + 1}
    for index, row in enumerate(audit, 1):
        if not isinstance(row, dict):
            errors.append(f"auditoria {index} inválida")
            continue
        missing = sorted(key for key in required if not str(row.get(key, "")).strip())
        if missing:
            errors.append(f"auditoria {index} sem {', '.join(missing)}")
        if row.get("tipo") == "cotacao" and not str(row.get("instrumento", "")).strip():
            errors.append(f"cotação {index} sem instrumento")

        date = str(row.get("data", ""))
        years = {int(year) for year in re.findall(r"\b(20\d{2})\b", date)}
        if not years:
            errors.append(f"auditoria {index} sem ano explícito")
        elif not years <= allowed_years:
            errors.append(f"auditoria {index} com ano incompatível com a edição")

        url = str(row.get("url", "")).strip()
        parsed_url = urlparse(url)
        if url and (parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc):
            errors.append(f"auditoria {index} com URL inválida")
    return errors


def script_errors(edition, script, minimum_words=MIN_WORDS):
    errors = []
    greeting = "Bom dia." if edition == "abertura" else "Boa noite."
    if not script.startswith(greeting):
        errors.append(f"saudação inválida: esperado {greeting}")
    if DISCLAIMER not in script:
        errors.append("aviso informativo final ausente")
    words = word_count(script)
    if minimum_words and words < minimum_words:
        errors.append(f"roteiro curto: {words} palavras; mínimo {minimum_words}")
    return errors


def validate_audit(audit, now):
    errors = audit_errors(audit, now)
    if errors:
        raise ValueError("; ".join(errors))


def validate_episode(edition, script, audit, now, minimum_words=MIN_WORDS):
    """Travas determinísticas executadas antes do TTS e da publicação."""
    errors = script_errors(edition, script, minimum_words)
    errors.extend(audit_errors(audit, now))
    if errors:
        raise ValueError("; ".join(errors))
