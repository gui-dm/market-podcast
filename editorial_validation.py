import re


def validate_episode(edition, script, audit, now):
    """Travas determinísticas executadas antes do TTS e da publicação."""
    errors = []
    words = re.findall(r"\b[\wÀ-ÿ]+\b", script)
    greeting = "Bom dia." if edition == "abertura" else "Boa noite."
    disclaimer = (
        "Este conteúdo tem caráter exclusivamente informativo e não constitui "
        "recomendação de investimento."
    )
    if not script.startswith(greeting):
        errors.append(f"saudação inválida: esperado {greeting}")
    if disclaimer not in script:
        errors.append("aviso informativo final ausente")
    if len(words) < 360:
        errors.append(f"roteiro curto: {len(words)} palavras; mínimo 360")
    if not isinstance(audit, list) or not audit:
        errors.append("ficha de auditoria ausente")
    else:
        required = {"item", "data", "horario", "fonte", "url"}
        for index, row in enumerate(audit, 1):
            if not isinstance(row, dict):
                errors.append(f"auditoria {index} inválida")
                continue
            missing = sorted(key for key in required if not str(row.get(key, "")).strip())
            if missing:
                errors.append(f"auditoria {index} sem {', '.join(missing)}")
            if row.get("tipo") == "cotacao" and not str(row.get("instrumento", "")).strip():
                errors.append(f"cotação {index} sem instrumento")
            if str(now.year) not in str(row.get("data", "")):
                errors.append(f"auditoria {index} com data não confirmada para {now.year}")
    if errors:
        raise ValueError("; ".join(errors))
