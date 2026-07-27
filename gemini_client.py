from __future__ import annotations

import os
import time


DEFAULT_GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
)

RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def configured_models(environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get("GEMINI_MODELS") or environ.get("GEMINI_MODEL") or ""
    candidates = raw.split(",") if raw.strip() else DEFAULT_GEMINI_MODELS
    result = []
    for candidate in candidates:
        model = str(candidate).strip()
        if model and model not in result:
            result.append(model)
    if not result:
        raise ValueError("nenhum modelo Gemini configurado")
    return result


def _response_detail(response, api_key):
    text = str(getattr(response, "text", "") or "").strip()
    if api_key:
        text = text.replace(api_key, "***")
    return " ".join(text.split())[:600]


def _retry_delay(response, attempt):
    raw = str(getattr(response, "headers", {}).get("Retry-After", "") or "").strip()
    try:
        retry_after = float(raw)
    except ValueError:
        retry_after = attempt * 2
    return max(1, min(retry_after, 30))


def request_with_fallback(
    api_key,
    payload,
    request_func,
    models=None,
    attempts_per_model=2,
    sleep_func=time.sleep,
    timeout=90,
):
    """Executa a chamada com retry curto e troca de modelo em falhas transitórias."""
    models = list(models or configured_models())
    failures = []
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    for model in models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        for attempt in range(1, attempts_per_model + 1):
            response = None
            try:
                response = request_func(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json(), model
            except Exception as exc:
                status = getattr(response, "status_code", None)
                detail = _response_detail(response, api_key) if response is not None else ""
                description = f"{model}: HTTP {status}" if status else f"{model}: {exc}"
                if detail:
                    description += f" — {detail}"
                failures.append(description)

                retryable = status is None or status in RETRYABLE_STATUS_CODES
                if not retryable:
                    break
                if attempt < attempts_per_model:
                    delay = _retry_delay(response, attempt)
                    print(
                        f"Gemini {model} indisponível na tentativa "
                        f"{attempt}/{attempts_per_model}; nova tentativa em "
                        f"{delay:g}s: {description}"
                    )
                    sleep_func(delay)
                else:
                    print(
                        f"Gemini {model} indisponível; tentando o próximo "
                        f"modelo configurado: {description}"
                    )

    summary = " | ".join(failures[-len(models) * attempts_per_model:])
    raise RuntimeError(
        f"Gemini falhou em {len(models)} modelo(s) configurado(s): {summary}"
    )
