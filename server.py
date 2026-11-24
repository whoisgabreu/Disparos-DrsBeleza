import hashlib
import hmac
import json
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


def _find_code(raw: str, payload) -> str | None:
    candidates = [raw]
    if isinstance(payload, (dict, list)):
        candidates.append(json.dumps(payload, ensure_ascii=False))
    candidates.extend(request.form.values())

    for candidate in candidates:
        code = extrair_codigo(candidate)
        if code:
            return code
    return None


def _find_account_id(payload) -> str | None:
    if isinstance(payload, dict) and payload.get("account_id"):
        return str(payload["account_id"])

    for key, value in request.form.items():
        if key.endswith("account_id") and value:
            return value
    return None


def _message_id(raw: str, payload) -> str:
    if isinstance(payload, dict):
        containers = [payload]
        message = payload.get("message")
        if isinstance(message, dict):
            containers.append(message)

        for container in containers:
            add = container.get("add")
            if isinstance(add, list) and add and isinstance(add[0], dict):
                message_id = add[0].get("id")
                if message_id:
                    return str(message_id)

    for key, value in request.form.items():
        if key.endswith("[id]") and value:
            return value

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

    if KOMMO_ACCOUNT_ID:
        account_id = _find_account_id(payload)
        if account_id and not hmac.compare_digest(
            account_id, KOMMO_ACCOUNT_ID
        ):
            _log("bloqueado: account_id divergente")
            return {"error": "account mismatch"}, 403

    code = _find_code(raw, payload)
    if not code:
        _log("sem codigo no payload (ignorado)")
        return {"status": "ignored"}, 200

    message_id = _message_id(raw, payload)
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
        f"OK lead={lead['number']} code={code} message_id={message_id}"
    )
    return {"status": "ok"}, 200


if __name__ == "__main__":
    db.init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8085")),
        debug=True,
    )
