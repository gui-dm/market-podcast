from __future__ import annotations

import json


REQUIRED_EPISODE_FIELDS = {
    "title",
    "description",
    "guid",
    "pub_date",
    "audio",
    "bytes",
    "duration",
}


def load_episode_metadata(directory, limit):
    """Carrega somente metadados publicáveis; auditorias nunca viram itens do RSS."""
    episodes = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        if path.name.endswith("-auditoria.json"):
            continue
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        if not REQUIRED_EPISODE_FIELDS <= metadata.keys():
            continue
        episodes.append((path, metadata))
        if len(episodes) >= limit:
            break
    return episodes
