import argparse
import csv
import json
import re
import time
from pathlib import Path

import requests

PHONE_COLUMNS = [
    "Telefone comercial",
    "Tel. direto com.",
    "Celular",
    "Telefone residencial",
    "Outro telefone",
]


def normalize(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    if digits.startswith("55") and len(digits) == 12 and digits[4] in ("8", "9"):
        digits = digits[:4] + "9" + digits[4:]
    return digits


def pick_phone(row: dict) -> str:
    for column in PHONE_COLUMNS:
        value = (row.get(column) or "").strip()
        if value:
            return value
    return ""


def load_token(token_file: Path) -> str:
    if not token_file.exists():
        raise SystemExit(f"Arquivo de token nao encontrado: {token_file}")
    match = re.search(
        r"eyJ[\w-]+\.[\w-]+\.[\w-]+",
        token_file.read_text(encoding="utf-8"),
    )
    if not match:
        raise SystemExit(f"Token nao encontrado em: {token_file}")
    return match.group(0)


def fetch_contacts(
    lead_ids: list[str],
    base_url: str,
    token: str,
    chunk_size: int,
) -> tuple[dict[str, str], int]:
    headers = {"Authorization": f"Bearer {token}"}
    unique_ids = list(dict.fromkeys(i for i in lead_ids if i))
    mapping: dict[str, str] = {}
    requests_made = 0

    for start in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[start : start + chunk_size]
        params = [("with", "contacts"), ("limit", "250")]
        params.extend(("filter[id][]", lead_id) for lead_id in chunk)

        response = requests.get(
            f"{base_url.rstrip('/')}/api/v4/leads",
            headers=headers,
            params=params,
            timeout=30,
        )
        requests_made += 1

        if response.status_code != 200:
            print(
                f"[aviso] lote {start}-{start + len(chunk)} retornou "
                f"{response.status_code}: {response.text[:150]}"
            )
            continue

        leads = response.json().get("_embedded", {}).get("leads", [])
        for lead in leads:
            contacts = lead.get("_embedded", {}).get("contacts", [])
            if contacts:
                mapping[str(lead.get("id"))] = str(contacts[0].get("id"))

        time.sleep(0.3)

    return mapping, requests_made


def build(
    input_path: Path,
    output_path: Path,
    with_contacts: bool,
    token_file: Path,
    base_url: str,
    chunk_size: int,
) -> dict:
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    stats = {
        "read": len(rows),
        "kept": 0,
        "converted": 0,
        "intl": 0,
        "invalid": 0,
        "duplicate": 0,
        "contacts_found": 0,
        "contacts_missing": 0,
        "requests": 0,
    }

    leads: list[tuple[str, str]] = []
    seen: set[str] = set()

    for row in rows:
        raw = pick_phone(row)
        if not raw:
            stats["invalid"] += 1
            continue

        raw_digits = re.sub(r"\D", "", raw)
        number = normalize(raw)

        if (
            raw_digits.startswith("55")
            and len(raw_digits) == 12
            and raw_digits[4] in ("8", "9")
        ):
            stats["converted"] += 1

        if not number.startswith("55") or len(number) != 13:
            stats["intl"] += 1
            continue

        if number in seen:
            stats["duplicate"] += 1
            continue

        seen.add(number)
        leads.append((str(row.get("ID") or "").strip(), number))
        stats["kept"] += 1

    contacts: dict[str, str] = {}
    if with_contacts:
        token = load_token(token_file)
        contacts, stats["requests"] = fetch_contacts(
            [lead_id for lead_id, _ in leads],
            base_url,
            token,
            chunk_size,
        )

    data = {}
    for index, (lead_id, number) in enumerate(leads, start=1):
        entry = {"number": number}
        contact_id = contacts.get(lead_id) if with_contacts else None
        if contact_id:
            entry["contact_id"] = contact_id
            stats["contacts_found"] += 1
        elif with_contacts:
            stats["contacts_missing"] += 1
        data[str(index)] = entry

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera reativar.json a partir do export de leads do Kommo"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--output", default=str(Path(__file__).with_name("reativar.json"))
    )
    parser.add_argument(
        "--with-contacts",
        action="store_true",
        help="Busca o contact_id real via API do Kommo",
    )
    parser.add_argument(
        "--kommo-token-file",
        default=str(Path(__file__).with_name("dados kommo.txt")),
    )
    parser.add_argument(
        "--kommo-base", default="https://drsdabeleza.amocrm.com"
    )
    parser.add_argument("--chunk-size", type=int, default=200)
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_path = Path(args.output).expanduser()

    if not input_path.exists():
        raise SystemExit(f"Arquivo nao encontrado: {input_path}")

    stats = build(
        input_path,
        output_path,
        args.with_contacts,
        Path(args.kommo_token_file).expanduser(),
        args.kommo_base,
        args.chunk_size,
    )

    print(f"Lidos: {stats['read']}")
    print(f"Mantidos BR (13 digitos): {stats['kept']}")
    print(f"Convertidos 12->13: {stats['converted']}")
    print(f"Descartados (internacional/fora do padrao): {stats['intl']}")
    print(f"Sem telefone: {stats['invalid']}")
    print(f"Duplicados ignorados: {stats['duplicate']}")
    if args.with_contacts:
        print(f"Requisicoes a API: {stats['requests']}")
        print(f"Com contact_id: {stats['contacts_found']}")
        print(f"Sem contact_id: {stats['contacts_missing']}")
    print(f"Gravado: {output_path}")


if __name__ == "__main__":
    main()
