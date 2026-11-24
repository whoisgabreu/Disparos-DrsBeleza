import argparse
import os
import sys
import time
import uuid

import requests

from generate_code import gerar_codigo_nucleo

DEFAULT_BASE_URL = os.environ.get(
    "WEBHOOK_BASE_URL", "https://wpp.drsdabeleza.com.br"
)
ACCOUNT_ID = os.environ.get("KOMMO_ACCOUNT_ID", "34578671")
SUBDOMAIN = os.environ.get("KOMMO_SUBDOMAIN", "drsdabeleza")
CODE_KEYWORD = os.environ.get("CODE_KEYWORD", "reativacao")


def build_form(text: str, message_id: str, contact_id: str) -> dict:
    return {
        "account[subdomain]": SUBDOMAIN,
        "account[id]": ACCOUNT_ID,
        "account[_links][self]": f"https://{SUBDOMAIN}.amocrm.com",
        "message[add][0][id]": message_id,
        "message[add][0][chat_id]": "test-chat",
        "message[add][0][talk_id]": "1",
        "message[add][0][contact_id]": contact_id,
        "message[add][0][text]": text,
        "message[add][0][created_at]": str(int(time.time())),
        "message[add][0][message_type]": "text",
        "message[add][0][element_type]": "2",
        "message[add][0][entity_type]": "lead",
        "message[add][0][element_id]": "1",
        "message[add][0][entity_id]": "1",
        "message[add][0][type]": "incoming",
        "message[add][0][author][id]": "test-author",
        "message[add][0][author][type]": "external",
        "message[add][0][author][name]": "Teste",
        "message[add][0][origin]": "waba",
    }


def post(base_url: str, secret: str, text: str, message_id: str, contact_id: str):
    url = f"{base_url.rstrip('/')}/webhooks/kommo/{secret}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "amoCRM-Webhooks/3.0",
    }
    started = time.perf_counter()
    response = requests.post(
        url,
        data=build_form(text, message_id, contact_id),
        headers=headers,
        timeout=20,
    )
    return response, time.perf_counter() - started


def check(name: str, response, elapsed: float, expected: set[int]) -> bool:
    ok = response.status_code in expected
    slow = " (lento >2s)" if elapsed > 2 else ""
    print(
        f"[{'OK' if ok else 'FALHOU'}] {name}: {response.status_code} "
        f"em {elapsed:.2f}s{slow} | {response.text[:200]}"
    )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste do webhook Kommo")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--secret", default=os.environ.get("KOMMO_WEBHOOK_SECRET")
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=[
            "health",
            "valid",
            "invalid",
            "nocode",
            "wrong-secret",
            "all",
        ],
    )
    parser.add_argument("--phone")
    parser.add_argument("--code")
    parser.add_argument("--contact-id", default="test-contact")
    parser.add_argument("--message-id")
    args = parser.parse_args()

    if not args.secret:
        raise SystemExit("Defina KOMMO_WEBHOOK_SECRET ou use --secret.")

    base = args.base_url.rstrip("/")
    message_id = args.message_id

    def run_health() -> bool:
        started = time.perf_counter()
        response = requests.get(f"{base}/health", timeout=15)
        elapsed = time.perf_counter() - started
        try:
            ok = (
                response.status_code == 200
                and response.json().get("status") == "ok"
            )
        except ValueError:
            ok = False
        print(
            f"[{'OK' if ok else 'FALHOU'}] health: {response.status_code} "
            f"em {elapsed:.2f}s | {response.text[:120]}"
        )
        return ok

    def send(text: str, secret: str | None = None, mid: str | None = None):
        return post(
            base,
            secret or args.secret,
            text,
            mid or message_id or f"test-{uuid.uuid4()}",
            args.contact_id,
        )

    def run_nocode() -> bool:
        response, elapsed = send("Oi, tudo bem?")
        return check("nocode", response, elapsed, {200})

    def run_invalid() -> bool:
        response, elapsed = send("Oi (cód.+ABCDEFGH)")
        return check("invalid", response, elapsed, {422})

    def run_wrong_secret() -> bool:
        response, elapsed = send("Oi", secret="segredo-errado")
        return check("wrong-secret", response, elapsed, {403})

    def run_valid() -> bool:
        code = args.code
        if not code:
            if not args.phone:
                print("[SKIP] valid: informe --phone ou --code")
                return True
            code = gerar_codigo_nucleo(args.phone, CODE_KEYWORD)
        text = f"Olá, vim do Google e quero agendar. (cód.+{code})"
        response, elapsed = send(text)
        return check("valid", response, elapsed, {200})

    results = []

    if args.mode in ("health", "all"):
        results.append(run_health())
    if args.mode == "nocode":
        results.append(run_nocode())
    if args.mode == "invalid":
        results.append(run_invalid())
    if args.mode == "wrong-secret":
        results.append(run_wrong_secret())
    if args.mode == "valid":
        results.append(run_valid())
    if args.mode == "all":
        results.append(run_nocode())
        results.append(run_invalid())
        results.append(run_wrong_secret())
        if args.phone or args.code:
            results.append(run_valid())

    print()
    if all(results):
        print("TODOS OS TESTES PASSARAM")
        return 0
    print("ALGUNS TESTES FALHARAM")
    return 1


if __name__ == "__main__":
    sys.exit(main())
