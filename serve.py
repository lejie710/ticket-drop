"""Start Ticket Drop on this computer only.

    .venv\\Scripts\\python.exe serve.py [--port 8000]
"""

import argparse

import uvicorn

from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ticket Drop locally.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
