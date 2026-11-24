import hashlib
import hmac
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

from flask import Flask, redirect, request

import db
from generate_code import extrair_codigo, gerar_codigo_nucleo

app = Flask(__name__)

CODE_KEYWORD = os.environ.get("CODE_KEYWORD", "reativacao")
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "5531991519947")
WHATSAPP_MESSAGE = os.environ.get(
    "WHATSAPP_MESSAGE",
    "Olá, vim do Google e quero agendar meu momento de SPA "
    "na Drs da Beleza. ({code})",
)
WHATSAPP_MESSAGE_NO_CODE = os.environ.get(
    "WHATSAPP_MESSAGE_NO_CODE",
    "Olá, vim do Google e quero agendar meu momento de SPA "
    "na Drs da Beleza.",
)
KOMMO_WEBHOOK_SECRET = os.environ.get("KOMMO_WEBHOOK_SECRET")
KOMMO_ACCOUNT_ID = os.environ.get("KOMMO_ACCOUNT_ID")


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"


def _log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[webhook] {ts} {message}", flush=True)


def _lead_code(lead: dict) -> str:
    core = lead.get("code")
    if not core:
        core = gerar_codigo_nucleo(lead["number"], CODE_KEYWORD)
        if lead.get("token"):
            db.set_lead_code(lead["token"], core)
    return core


def build_whatsapp_url(lead: dict | None) -> str:
    if lead:
        message = WHATSAPP_MESSAGE.format(code=f"cód.+{_lead_code(lead)}")
    else:
        message = WHATSAPP_MESSAGE_NO_CODE
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote_plus(message)}"


def _parse_message(raw: str, payload) -> dict:
    fields = {
        "account_id": None,
        "message_id": None,
        "text": None,
        "contact_id": None,
        "type": None,
        "message_type": None,
        "origin": None,
    }

    if isinstance(payload, dict):
        account = payload.get("account")
        if isinstance(account, dict) and account.get("id"):
            fields["account_id"] = account["id"]
        elif payload.get("account_id"):
            fields["account_id"] = payload["account_id"]

        container = payload.get("message")
        if not isinstance(container, dict):
            container = payload
        add = container.get("add")
        if isinstance(add, list) and add and isinstance(add[0], dict):
            item = add[0]
            fields["message_id"] = item.get("id")
            fields["text"] = item.get("text")
            fields["contact_id"] = item.get("contact_id")
            fields["type"] = item.get("type")
            fields["message_type"] = item.get("message_type")
            fields["origin"] = item.get("origin")

    prefix = "message[add][0]"
    form = request.form
    for key, field in (
        ("message_id", "id"),
        ("text", "text"),
        ("contact_id", "contact_id"),
        ("type", "type"),
        ("message_type", "message_type"),
        ("origin", "origin"),
    ):
        if not fields[key]:
            fields[key] = form.get(f"{prefix}[{field}]")
    if not fields["account_id"]:
        fields["account_id"] = form.get("account[id]")

    return {
        key: (str(value) if value is not None else None)
        for key, value in fields.items()
    }


def _find_code(raw: str, fields: dict) -> str | None:
    candidates = [fields.get("text"), raw, *request.form.values()]
    for candidate in candidates:
        code = extrair_codigo(candidate)
        if code:
            return code
    return None


def _message_id(raw: str, fields: dict) -> str:
    if fields.get("message_id"):
        return str(fields["message_id"])

    request_id = request.headers.get("X-Amocrm-Requestid")
    if request_id:
        return request_id

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.route("/reativar/<string:token>")
def reativar(token: str):
    db.init_db()
    lead = db.get_by_token(token)

    if lead and lead["status"] != "ATIVO":
        db.mark_active(token)
        print(
            f"Lead {lead['number']} (contact_id={lead['contact_id']}) "
            "marcado como ATIVO"
        )

    return redirect(build_whatsapp_url(lead))


@app.post("/webhooks/kommo/<secret>")
def kommo_webhook(secret: str):
    _log(
        f"recebido ip={_client_ip()} "
        f"ct={request.content_type} bytes={request.content_length}"
    )

    if not KOMMO_WEBHOOK_SECRET:
        _log("ignorado: KOMMO_WEBHOOK_SECRET nao configurado")
        return {"error": "webhook nao configurado"}, 503
    if not hmac.compare_digest(secret, KOMMO_WEBHOOK_SECRET):
        _log(f"bloqueado: secret invalido ip={_client_ip()}")
        return {"error": "forbidden"}, 403

    db.init_db()
    raw = request.get_data(as_text=True) or ""
    payload = request.get_json(silent=True)
    fields = _parse_message(raw, payload)

    if KOMMO_ACCOUNT_ID:
        account_id = fields.get("account_id")
        if account_id and not hmac.compare_digest(
            account_id, KOMMO_ACCOUNT_ID
        ):
            _log("bloqueado: account_id divergente")
            return {"error": "account mismatch"}, 403

    if fields.get("type") and fields["type"] != "incoming":
        _log(f"ignorado: type={fields['type']}")
        return {"status": "ignored"}, 200

    code = _find_code(raw, fields)
    if not code:
        _log("sem codigo no payload (ignorado)")
        return {"status": "ignored"}, 200

    message_id = _message_id(raw, fields)
    if db.webhook_seen(message_id):
        _log(f"duplicado message_id={message_id} code={code}")
        return {"status": "duplicate"}, 200

    lead = db.get_by_code(code)
    if not lead:
        db.record_webhook(message_id, code)
        _log(f"codigo invalido code={code} message_id={message_id}")
        return {"error": "codigo invalido"}, 422

    db.mark_replied(lead["token"], message_id)
    db.record_webhook(message_id, code)
    _log(
        f"OK lead={lead['number']} code={code} message_id={message_id} "
        f"contact_id={fields.get('contact_id')} origin={fields.get('origin')}"
    )
    return {"status": "ok"}, 200


if __name__ == "__main__":
    db.init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8085")),
        debug=True,
    )
