"""Start Ticket Drop on this computer only.

    .venv\\Scripts\\python.exe serve.py [--port 8000] [--db .local\\ticket-drop.db] [--sale-opens-in 60]
"""

import argparse
import os
from pathlib import Path

import uvicorn

from app import db
from app.main import create_app

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ticket Drop locally.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(HERE / ".local" / "ticket-drop.db"),
                        help="SQLite file. Created and seeded if it does not exist.")
    parser.add_argument("--sale-opens-in", type=float, default=None,
                        help="Seconds until the sale opens. By default the sale is already open.")
    parser.add_argument("--sample-sales", type=float, default=0.0, metavar="FRACTION",
                        help="Mark about this share of seats as sold to sample accounts, e.g. 0.55. "
                             "Only applied to a database with no tickets yet.")
    args = parser.parse_args()
    os.environ.setdefault("TICKET_DROP_DB", args.db)
    if args.sale_opens_in is not None:
        os.environ["TICKET_DROP_SALE_OPENS_IN"] = str(args.sale_opens_in)
    app = create_app()
    if args.sample_sales:
        sold = db.add_sample_sales(app.state.settings.db_path, args.sample_sales)
        if sold:
            print(f"Sample data: marked {sold} seats as sold to sample accounts.")
    print(f"Ticket Drop is running at http://127.0.0.1:{args.port} (press Ctrl+C to stop)")
    # server_header=False: do not advertise the server software and version.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", server_header=False)


if __name__ == "__main__":
    main()
