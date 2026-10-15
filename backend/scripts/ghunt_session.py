#!/usr/bin/env python3
"""Operator-only GHunt session setup/status; never accepts a token on argv."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app.core.config import settings
    from app.tools.ghunt_runtime import capabilities, credentials_path, python_path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["status", "check", "login", "resume"])
    parser.add_argument("--credentials", help="Ruta de creds.m del operador; nunca un token")
    args = parser.parse_args()
    if args.credentials:
        settings.ghunt_credentials_file = args.credentials
    info = capabilities()
    if args.operation == "status":
        print(json.dumps(info, indent=2))
        return 0
    if args.operation in {"login", "resume"}:
        if not info["runtime_available"]:
            print("Instala el runtime: uv sync --project integrations/ghunt --python 3.12 --frozen")
            return 2
        if credentials_path() is None:
            print("Indica --credentials o configura GHUNT_CREDENTIALS_FILE.")
            return 2
        return subprocess.call([str(python_path()), "-I", str(ROOT / "app/tools/ghunt_worker.py"),
                                "--" + args.operation, str(credentials_path())])
    if info["status"] != "configured":
        print(json.dumps({"status": info["status"]}))
        return 2
    from app.tools.ghunt_runner import run_ghunt
    try:
        result = asyncio.run(run_ghunt({"kind": "status", "value": ""}, []))
        print(json.dumps({"status": result["status"], "requests": result["requests"]}))
        return 0 if result["status"] == "authenticated" else 1
    except Exception as exc:
        print(json.dumps({"status": "check_failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
