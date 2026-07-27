from __future__ import annotations

import os
import time


DEFAULT_GITHUB_MODELS = (
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
)

RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def configured_github_models(environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get("GITHUB_MODELS_MODELS", "")
    candidates = raw.split(",") if raw.strip() else DEFAULT_GITHUB_MODELS
    result = []
    for candidate in candidates:
        model = str(candidate).strip()
        if model and model not in result:
            result.append(model)
    if not result:
        raise ValueError("nenhum GitHub Model configurado")
    return result


def _detail(response, token):
    text = str(getattr(response, "text", "") or "").strip()
    if token:
        text = text.replace(token, "***")
    return " ".join(text.split())[:600]


def request_text(
    token,
    prompt,
    request_func,
    models=None,
    attempts_per_model=2,
    sleep_func=time.sleep,
    timeout=90,
):
    models = list(models or configured_github_models())
    failures = []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "Content-Type": "application/json",
    }

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é um editor financeiro rigoroso. Obedeça às fontes "
                        "autorizadas e nunca acrescente fatos ou números."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 3200,
        }
        for attempt in range(1, attempts_per_model + 1):
            response = None
            try:
                response = request_func(
                    "https://models.github.ai/inference/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not str(content).strip():
                    raise ValueError("GitHub Models retornou resposta vazia")
                return str(content).strip(), model
            except Exception as exc:
                status = getattr(response, "status_code", None)
                description = f"{model}: HTTP {status}" if status else f"{model}: {exc}"
                detail = _detail(response, token) if response is not None else ""
                if detail:
                    description += f" — {detail}"
                failures.append(description)
                retryable = status is None or status in RETRYABLE_STATUS_CODES
                if not retryable:
                    break
                if attempt < attempts_per_model:
                    delay = min(attempt * 3, 15)
                    print(
                        f"GitHub Models {model} indisponível; nova tentativa "
                        f"em {delay}s: {description}"
                    )
                    sleep_func(delay)
                else:
                    print(
                        f"GitHub Models {model} indisponível; tentando o "
                        f"próximo modelo: {description}"
                    )

    raise RuntimeError(
        "GitHub Models falhou em todos os modelos configurados: "
        + " | ".join(failures[-len(models) * attempts_per_model:])
    )
