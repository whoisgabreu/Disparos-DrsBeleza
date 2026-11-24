import os
import threading
import time

from waitress import serve

import db
import import_leads
from server import app
from wpp import run_tick

TICK_INTERVAL_MINUTES = float(
    os.environ.get("TICK_INTERVAL_MINUTES", "15")
)
_tick_lock = threading.Lock()


@app.get("/health")
def health():
    return {"status": "ok"}


def _scheduler_loop() -> None:
    while True:
        with _tick_lock:
            try:
                run_tick()
            except Exception as exc:
                print(f"[scheduler] erro no tick: {exc}")
        time.sleep(TICK_INTERVAL_MINUTES * 60)


def main() -> None:
    db.init_db()
    if import_leads.SOURCE.exists():
        import_leads.main()
    else:
        print("[startup] reativar.json nao encontrado; pulando import.")
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
