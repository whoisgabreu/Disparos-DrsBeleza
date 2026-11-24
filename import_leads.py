import json
import secrets
from pathlib import Path

import db

SOURCE = Path(__file__).with_name("reativar.json")


def main() -> None:
    db.init_db()

    if not SOURCE.exists():
        raise SystemExit(f"Arquivo nao encontrado: {SOURCE}")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    total = 0

    for key, item in data.items():
        number = str(item["number"]).strip()
        contact_id = str(item.get("contact_id") or key)
        db.upsert_lead(number, contact_id, secrets.token_urlsafe(16))
        total += 1

    print(f"{total} lead(s) importado(s) de {SOURCE.name}.")
    print(f"Resumo por status: {db.count_by_status()}")


if __name__ == "__main__":
    main()
