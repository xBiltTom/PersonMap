#!/usr/bin/env python3
"""Read-only academic audit of explicit public DOIs; no dossier/session writes."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.academic_finder import AcademicFinderTool, capabilities, execution_summary
from app.tools.academic_metadata import doi_url
from app.tools.base import TargetContext


async def audit(args):
    urls = [doi_url(value) for value in args.doi]
    if not all(urls) or len(urls) > capabilities()["max_dois"]:
        raise SystemExit("Indica DOI válidos dentro del límite configurado de publicaciones.")
    context = TargetContext(extra={"candidate_urls": urls})
    findings = await AcademicFinderTool().execute(context)
    report = {"audited_at": datetime.now(timezone.utc).isoformat(),
        "input_kind": "explicit_public_doi", "requested_dois": urls,
        "target_association_tested": False, "capabilities": capabilities(),
        "summary": execution_summary(context), "diagnostics": context.extra.get("academic_diagnostics", []),
        "publications": [{"doi": finding.metadata_info.get("doi"), "title": finding.display_name,
            "sources": finding.metadata_info.get("academic_sources", []),
            "citation_counts": finding.metadata_info.get("citation_counts", {}),
            "target_association_status": finding.metadata_info.get("target_association_status")}
            for finding in findings if finding.platform == "research_paper"]}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n")
    print(serialized)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doi", required=True, action="append", help="DOI o URL DOI de una publicación pública; repetible")
    parser.add_argument("--output", help="Informe sin cookies, claves ni contacto del operador")
    asyncio.run(audit(parser.parse_args()))
