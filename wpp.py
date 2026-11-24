import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests as rq

import db

BASE_URL = os.environ.get("EVOLUTION_URL", "evolution.v4lisboatech.com.br")
INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "Gabriel Lucas - DEV")
API_KEY = os.environ.get(
    "EVOLUTION_API_KEY", "6E30DF765BBA-43B5-8986-696F99E3AD6A"
)

REDIRECT_BASE_URL = os.environ.get(
    "REDIRECT_BASE_URL", "http://192.168.3.33:8080"
).rstrip("/")

DELAY_MS = int(os.environ.get("DELAY_MS", "5000"))
SEND_INTERVAL = float(os.environ.get("SEND_INTERVAL", "30"))

MESSAGES_FILE = Path(
    os.environ.get("MESSAGES_FILE", Path(__file__).with_name("mensagens.json"))
)

FOLLOWUP_SCHEDULE = [
    int(item)
    for item in os.environ.get(
        "FOLLOWUP_SCHEDULE", "4,3,2,1,1,1,1"
    ).split(",")
    if item.strip()
]
SLOTS_PER_DAY = int(os.environ.get("SLOTS_PER_DAY", "4"))
BUSINESS_TZ = ZoneInfo(os.environ.get("BUSINESS_TZ", "America/Sao_Paulo"))
BUSINESS_START = os.environ.get("BUSINESS_START", "08:00")
BUSINESS_END = os.environ.get("BUSINESS_END", "18:00")
WORKDAYS = {
    int(item)
    for item in os.environ.get("WORKDAYS", "0,1,2,3,4").split(",")
    if item.strip()
}


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


START_MIN = _to_minutes(BUSINESS_START)
END_MIN = _to_minutes(BUSINESS_END)
SLOT_MINUTES = (END_MIN - START_MIN) / SLOTS_PER_DAY


def slot_window(index: int) -> tuple[float, float]:
    start = START_MIN + index * SLOT_MINUTES
    return start, start + SLOT_MINUTES


def load_messages() -> list[str]:
    try:
        messages = json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Arquivo de mensagens nao encontrado: {MESSAGES_FILE}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON invalido em {MESSAGES_FILE}: {exc}")

    if not isinstance(messages, list) or not messages:
        raise SystemExit("mensagens.json deve conter uma lista nao vazia.")

    for index, message in enumerate(messages, start=1):
        if not isinstance(message, str) or "{link}" not in message:
            raise SystemExit(
                f"Mensagem #{index} invalida: deve ser texto contendo {{link}}."
            )

    return messages


def lead_link(lead: dict) -> str:
    return f"{REDIRECT_BASE_URL}/reativar/{lead['token']}"


def send_text(lead: dict, text: str) -> rq.Response:
    payload = {
        "number": lead["number"],
        "text": text,
        "delay": DELAY_MS,
        "linkPreview": True,
    }
    url = (
        f"https://{BASE_URL}/message/sendText/"
        f"{quote(INSTANCE_NAME, safe='')}"
    )
    return rq.post(
        url,
        headers={"Content-Type": "application/json", "apikey": API_KEY},
        json=payload,
        timeout=30,
    )


def _process_lead(
    lead: dict, messages: list[str], today: str, now_min: float, now: datetime
) -> int:
    followup_day = lead["followup_day"]

    if lead["day_anchor"] is None:
        db.initialize_lead_day(lead["token"], today)
        sends_in_day = 0
        slot_cursor = 0
    elif lead["day_anchor"] != today:
        followup_day += 1
        if followup_day >= len(FOLLOWUP_SCHEDULE):
            db.advance_day(lead["token"], followup_day, today, "DESISTIDO")
            print(f"{lead['number']}: follow-ups concluidos (DESISTIDO)")
            return 0
        status = "ENVIADO" if lead["status"] == "ENVIADO" else lead["status"]
        db.advance_day(lead["token"], followup_day, today, status)
        sends_in_day = 0
        slot_cursor = 0
    else:
        sends_in_day = lead["sends_in_day"]
        slot_cursor = lead["slot_cursor"]

    quota = FOLLOWUP_SCHEDULE[followup_day]

    base_cursor = slot_cursor
    while slot_cursor < SLOTS_PER_DAY and now_min >= slot_window(slot_cursor)[1]:
        slot_cursor += 1
    if slot_cursor != base_cursor:
        db.set_slot_cursor(lead["token"], slot_cursor)

    if slot_cursor >= SLOTS_PER_DAY:
        return 0
    if sends_in_day >= quota:
        return 0

    slot_start, slot_end = slot_window(slot_cursor)
    if not (slot_start <= now_min < slot_end):
        return 0

    fresh = db.get_by_token(lead["token"])
    if not fresh or fresh["status"] not in ("PENDENTE", "ENVIADO"):
        return 0

    message_index = random.randrange(len(messages))
    text = messages[message_index].format(link=lead_link(fresh))
    response = send_text(fresh, text)

    if response.ok:
        db.register_send(
            fresh["token"], message_index, now.isoformat(timespec="seconds")
        )
        print(
            f"{fresh['number']}: enviado (dia {followup_day + 1}, "
            f"envio {sends_in_day + 1}/{quota}, msg #{message_index + 1})"
        )
        return 1

    print(
        f"{fresh['number']}: falha {response.status_code} "
        f"{response.text[:200]}"
    )
    return 0


def run_tick(now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)

    local = now.astimezone(BUSINESS_TZ)
    today = local.date().isoformat()
    db.init_db(today)
    messages = load_messages()

    if local.weekday() not in WORKDAYS:
        print(f"{today} {local.strftime('%H:%M')}: fora de dia util.")
        return

    now_min = local.hour * 60 + local.minute + local.second / 60
    if not (START_MIN <= now_min < END_MIN):
        print(
            f"{today} {local.strftime('%H:%M')}: fora do horario comercial."
        )
        return

    running = db.list_running()
    if not running:
        print("Nenhum lead em campanha.")
        return

    sent = 0
    for position, lead in enumerate(running):
        sent += _process_lead(lead, messages, today, now_min, now)
        if position < len(running) - 1:
            time.sleep(SEND_INTERVAL)

    print(
        f"Tick {today} {local.strftime('%H:%M')}: {sent} envio(s). "
        f"Resumo: {db.count_by_status()}"
    )


def main() -> None:
    run_tick()


if __name__ == "__main__":
    main()
