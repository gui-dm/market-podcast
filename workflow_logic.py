from __future__ import annotations

import argparse
import os
from pathlib import Path


OPENING_SCHEDULES = {
    "47 7 * * 1-5",
    "7,27,47 8-9 * * 1-5",
}
CLOSING_SCHEDULES = {
    "17 18 * * 1-5",
    "37,57 18 * * 1-5",
    "17,37,57 19-20 * * 1-5",
}
ISSUE_EDITIONS = {
    "[scheduler] abertura": "abertura",
    "[scheduler] teste abertura": "abertura",
    "[scheduler] fechamento": "fechamento",
    "[scheduler] teste fechamento": "fechamento",
}


def select_edition(event_name, dispatch_edition="", issue_title="", schedule=""):
    if event_name == "workflow_dispatch":
        if dispatch_edition not in {"abertura", "fechamento"}:
            raise ValueError("edição manual inválida")
        return dispatch_edition
    if event_name == "issues":
        try:
            return ISSUE_EDITIONS[issue_title]
        except KeyError as exc:
            raise ValueError("sinal de agendamento inválido") from exc
    if event_name == "schedule":
        if schedule in OPENING_SCHEDULES:
            return "abertura"
        if schedule in CLOSING_SCHEDULES:
            return "fechamento"
        raise ValueError("expressão de agendamento desconhecida")
    raise ValueError(f"evento não suportado: {event_name}")


def force_regeneration(event_name, issue_title=""):
    return event_name == "workflow_dispatch" or issue_title.startswith("[scheduler] teste ")


def episode_complete(root, episode_date, edition):
    root = Path(root)
    slug = f"{episode_date}-{edition}"
    episodes = root / "docs" / "episodes"
    required = [
        episodes / f"{slug}.mp3",
        episodes / f"{slug}.json",
        episodes / f"{slug}.txt",
        episodes / f"{slug}-auditoria.json",
    ]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        return False
    feed = root / "docs" / "feed.xml"
    if not feed.is_file():
        return False
    return f"episodes/{slug}.mp3" in feed.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["select", "force", "complete"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--date")
    parser.add_argument("--edition")
    args = parser.parse_args()

    event_name = os.getenv("EVENT_NAME", "")
    issue_title = os.getenv("ISSUE_TITLE", "")
    if args.command == "select":
        print(
            select_edition(
                event_name,
                os.getenv("DISPATCH_EDITION", ""),
                issue_title,
                os.getenv("SCHEDULE_EXPRESSION", ""),
            )
        )
    elif args.command == "force":
        print("true" if force_regeneration(event_name, issue_title) else "false")
    else:
        if not args.date or not args.edition:
            parser.error("complete exige --date e --edition")
        print("true" if episode_complete(args.root, args.date, args.edition) else "false")


if __name__ == "__main__":
    main()
