import os

import db
from server import app

if __name__ == "__main__":
    db.init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8085")),
        debug=True,
    )
