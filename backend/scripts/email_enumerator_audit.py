#!/usr/bin/env python3
"""Audit reviewed email probes, using a random control unless explicitly asked."""
import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.email_catalog import capabilities
from app.tools.email_enumerator import EmailEnumeratorTool, execution_summary, valid_email


async def audit(args):
    if args.sites:
        settings.email_enum_sites = args.sites.split(",")
    email = (getpass.getpass("Correo propio para comprobar (entrada oculta): ").strip().lower()
             if args.operator_email else EmailEnumeratorTool._invented_email("control@gmail.com"))
    if not valid_email(email):
        raise SystemExit("Correo inválido")
    context = TargetContext(email=email)
    findings = await EmailEnumeratorTool().execute(context)
    result = {"audited_at": datetime.now(timezone.utc).isoformat(),
              "input_kind": "operator_supplied" if args.operator_email else "random_control",
              "capabilities": capabilities(), "summary": execution_summary(context),
              "findings_count": len(findings),
              "services": context.extra.get("email_enum_diagnostics", {}).get(email, {})}
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n")
    print(serialized)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", help="IDs separados por comas; por defecto usa el catálogo configurado")
    parser.add_argument("--operator-email", action="store_true", help="Solicita un correo propio con entrada oculta")
    parser.add_argument("--output", help="Guarda el informe sin correo, respuestas crudas ni tokens")
    asyncio.run(audit(parser.parse_args()))
