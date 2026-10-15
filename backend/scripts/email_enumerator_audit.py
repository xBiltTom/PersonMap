#!/usr/bin/env python3
"""Audit reviewed email probes, using a random control unless explicitly asked."""
import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.email_catalog import capabilities
from app.tools.email_enumerator import EmailEnumeratorTool, execution_summary, valid_email


async def audit(args):
    if args.sites:
        settings.email_enum_sites = args.sites.split(",")
    if args.expected_registered and not (args.operator_email or args.investigation):
        raise SystemExit("Los positivos esperados requieren un correo propio o un análisis local explícito")
    if args.investigation:
        from sqlalchemy import select
        from app.core.database import async_session_maker, engine
        from app.models.investigation import Investigation
        from app.models.target import Target
        try:
            async with asyncio.timeout(10):
                async with async_session_maker() as db:
                    email = (await db.execute(select(Target.email).join(Investigation, Investigation.target_id == Target.id)
                        .where(Investigation.id == args.investigation))).scalar_one_or_none()
        finally:
            await engine.dispose()
    else:
        email = (getpass.getpass("Correo propio para comprobar (entrada oculta): ").strip().lower()
                 if args.operator_email else EmailEnumeratorTool._invented_email("control@gmail.com"))
    if not valid_email(email):
        raise SystemExit("Correo inválido")
    context = TargetContext(email=email)
    findings = await EmailEnumeratorTool().execute(context)
    result = {"audited_at": datetime.now(timezone.utc).isoformat(),
              "input_kind": "operator_supplied" if args.operator_email or args.investigation else "random_control",
              "capabilities": capabilities(), "summary": execution_summary(context),
              "findings_count": len(findings),
              "services": context.extra.get("email_enum_diagnostics", {}).get(email, {})}
    if args.expected_registered:
        services = result["services"]
        expected = sorted(set(args.expected_registered.split(",")))
        result["positive_validation"] = {
            "ground_truth": "operator_reported_registration",
            "detected": [key for key in expected if services.get(key, {}).get("status") == "registered"],
            "reported_negative": [key for key in expected if services.get(key, {}).get("status") == "not_registered"],
            "inconclusive": {key: services.get(key, {}).get("status", "not_checked") for key in expected
                             if services.get(key, {}).get("status") not in {"registered", "not_registered"}}}
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n")
    print(serialized)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", help="IDs separados por comas; por defecto usa el catálogo configurado")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--operator-email", action="store_true", help="Solicita un correo propio con entrada oculta")
    inputs.add_argument("--investigation", type=UUID, help="Lee solo el correo del análisis local indicado, sin imprimirlo")
    parser.add_argument("--expected-registered", help="IDs de servicios donde el operador confirma su registro, separados por comas")
    parser.add_argument("--output", help="Guarda el informe sin correo, respuestas crudas ni tokens")
    asyncio.run(audit(parser.parse_args()))
