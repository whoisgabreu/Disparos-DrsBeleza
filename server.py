import os
from urllib.parse import quote_plus

from flask import Flask, redirect

import db
from generate_code import gerar_codigo

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


def build_whatsapp_url(lead: dict | None) -> str:
    if lead:
        code = gerar_codigo(lead["number"], CODE_KEYWORD)
        message = WHATSAPP_MESSAGE.format(code=code)
    else:
        message = WHATSAPP_MESSAGE_NO_CODE
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote_plus(message)}"


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


if __name__ == "__main__":
    db.init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        debug=True,
    )
