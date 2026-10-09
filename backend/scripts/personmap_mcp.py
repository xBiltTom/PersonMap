"""Set up the local MCP credential or launch Codex with an isolated MCP config.

Run using backend/.venv/bin/python backend/scripts/personmap_mcp.py setup|codex
Credentials stay in the ignored .env file and the child environment, never CLI args.
"""
import argparse
import os
import re
import secrets
import shutil
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


def setup():
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    key = dotenv_values(ENV_FILE).get("MCP_API_KEY") if ENV_FILE.exists() else None
    if not key:
        line = "MCP_API_KEY=" + secrets.token_urlsafe(32)
        if re.search(r"(?m)^MCP_API_KEY\s*=.*$", content):
            content = re.sub(r"(?m)^MCP_API_KEY\s*=.*$", line, content)
        else:
            content += ("\n" if content and not content.endswith("\n") else "") + line + "\n"
        ENV_FILE.write_text(content)
        ENV_FILE.chmod(0o600)
        print("Credencial MCP creada en .env; su valor no se muestra.")
    else:
        print("Se conserva la credencial MCP existente en .env.")
    print("Inicia o reinicia el backend y abre la plataforma web.")


def launch_codex(url, extra_args):
    if not shutil.which("codex"):
        raise SystemExit("Codex CLI no está instalado en PATH.")
    key = os.getenv("PERSONMAP_MCP_TOKEN") or dotenv_values(ENV_FILE).get("MCP_API_KEY")
    if not key:
        raise SystemExit("Ejecuta primero este script con el argumento setup.")
    import json
    env = {**os.environ, "PERSONMAP_MCP_TOKEN": key}
    args = ["codex", "-c", "mcp_servers.personmap.url=" + json.dumps(url),
            "-c", 'mcp_servers.personmap.bearer_token_env_var="PERSONMAP_MCP_TOKEN"', *extra_args]
    os.execvpe("codex", args, env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "codex"])
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    args, remaining = parser.parse_known_args()
    if args.action == "setup":
        if remaining:
            parser.error("setup no admite argumentos adicionales")
        setup()
    else:
        launch_codex(args.url, remaining)
