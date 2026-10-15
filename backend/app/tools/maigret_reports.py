"""Export persisted Maigret evidence using upstream writers in the private worker."""
import base64
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
from typing import Literal

ReportFormat = Literal["json", "ndjson", "csv", "txt", "markdown", "html", "pdf", "xmind", "graph", "neo4j"]
REPORT_TYPES = {"json": ("json", "application/json"), "ndjson": ("jsonl", "application/x-ndjson"),
                "csv": ("csv", "text/csv"), "txt": ("txt", "text/plain"),
                "markdown": ("md", "text/markdown"), "html": ("html", "text/html"),
                "pdf": ("pdf", "application/pdf"), "xmind": ("xmind", "application/vnd.xmind.workbook"),
                "graph": ("html", "text/html"), "neo4j": ("cypher", "text/plain")}
SCOPE = ("Person Map: estos registros son detecciones y datos públicos, no atribuciones de identidad. "
         "El grafo nativo muestra enlaces e identificadores, no grupos de identidad confirmados.")


def report_record(entity):
    meta = entity.metadata_info or {}
    if meta.get("search_engine") != "maigret" or meta.get("maigret_status") != "Claimed":
        return None
    queries = meta.get("maigret_queries") or []
    query = queries[0] if queries else meta.get("queried_identifier") or {"value": meta.get("username", ""), "id_type": "username"}
    return {"site": meta.get("maigret_site") or (entity.display_name or "").split(": ", 1)[0],
            "value": query["value"], "id_type": query["id_type"], "url": entity.value,
            "data": meta.get("maigret_data", {}), "ids": meta.get("discovered_identifiers", {}),
            "identifiers": meta.get("extracted_identifiers", []),
            "links": meta.get("linked_profiles", []), "http_status": meta.get("checked_status"),
            "verification_status": meta.get("verification_status"), "negative_control": meta.get("negative_control"),
            "sources": meta.get("source_tools", [entity.source_tool])}


def check_records(runtime):
    for field in ("username_finder_checks", "maigret_enricher_checks"):
        for key, checks in runtime.get(field, {}).items():
            kind, value = key.split(":", 1) if field == "maigret_enricher_checks" else ("username", key)
            for name, checked in checks.items():
                if checked.get("url"):
                    yield {"site": name, "value": value, "id_type": kind, "url": checked["url"],
                           "data": {}, "ids": {}, "links": [], "http_status": checked.get("http_status"),
                           "verification_status": "candidate" if checked["status"] == "Claimed" else "inconclusive" if checked["status"] == "Unknown" else "not_detected",
                           "negative_control": None, "sources": ["username_finder" if field == "username_finder_checks" else "maigret_enricher"],
                           "status": checked["status"], "error": checked.get("error")}


def render_native_report(job, db):
    # This is called only inside the worker. Never import native report/CLI
    # objects into the API server or invoke a separate network-enabled renderer.
    from maigret import report
    from maigret.result import MaigretCheckResult, MaigretCheckStatus
    from maigret.errors import CheckError
    fmt = job["report_format"]
    extension, mime = REPORT_TYPES[fmt]
    grouped = {}
    for record in job["records"]:
        if record["site"] not in db.sites_dict:
            continue
        key = (record["value"], record["id_type"])
        site = copy.deepcopy(db.sites_dict[record["site"]])
        status = MaigretCheckResult(record["value"], site.name, record["url"], MaigretCheckStatus(record.get("status", "Claimed")),
                                   ids_data=record["data"], tags=site.tags,
                                   error=CheckError(record["error"]) if record.get("error") else None)
        grouped.setdefault(key, {})[site.name] = {
            "site": site, "status": status, "url_user": record["url"], "url_main": site.url_main,
            "http_status": record["http_status"], "ids_usernames": record["ids"], "ids_links": record["links"],
            "person_map": {"verification_status": record["verification_status"],
                           "identifiers": record.get("identifiers", []),
                           "negative_control": record["negative_control"], "sources": record["sources"],
                           "ownership_status": "unverified"}}
    if fmt in {"graph", "markdown"}:
        def plain_markup(value):
            if isinstance(value, str):
                return value.replace("<", "&lt;").replace(">", "&gt;")
            if isinstance(value, dict):
                return {key: plain_markup(item) for key, item in value.items()}
            if isinstance(value, list):
                return [plain_markup(item) for item in value]
            return value
        for results in grouped.values():
            for result in results.values():
                result["status"].ids_data = plain_markup(result["status"].ids_data)
    groups = [(value, kind, results) for (value, kind), results in grouped.items()]
    output = io.StringIO()
    if fmt in {"json", "ndjson"}:
        queries = []
        for value, kind, results in groups:
            raw = io.StringIO()
            report.generate_json_report(value, results, raw, "simple")
            queries.append({"value": value, "id_type": kind, "results": json.loads(raw.getvalue())})
        text = (json.dumps({"scope": SCOPE, "queries": queries}, ensure_ascii=False)
                if fmt == "json" else "\n".join(json.dumps({"scope": SCOPE, **query}, ensure_ascii=False) for query in queries))
        content = text.encode()
    elif fmt == "csv":
        writer = csv.writer(output)
        writer.writerow(["id_type", "username", "name", "url_main", "url_user", "exists", "http_status", "error_reason"])
        for value, kind, results in groups:
            raw = io.StringIO()
            report.generate_csv_report(value, results, raw)
            for row in list(csv.reader(io.StringIO(raw.getvalue())))[1:]:
                writer.writerow([kind, *[("'" + field) if field.startswith(("=", "+", "-", "@")) else field for field in row]])
        content = output.getvalue().encode()
    elif fmt == "txt":
        output.write(SCOPE + "\n\n")
        for value, kind, results in groups:
            output.write(f"\n{kind}: {value}\n")
            report.generate_txt_report(value, results, output)
            output.write("\n")
        content = output.getvalue().encode()
    else:
        if not groups:
            raise ValueError("No persisted Maigret detections to render")
        context = report.generate_report_context(groups)
        context["brief"] = SCOPE
        if fmt == "markdown":
            content = report.generate_markdown_report(context).encode()
        elif fmt == "html":
            template, _ = report.generate_report_template(False)
            content = template.render(**context).encode()
        else:
            with tempfile.TemporaryDirectory(prefix="person-map-maigret-report-") as directory:
                target = Path(directory) / ("report." + extension)
                if fmt == "pdf":
                    # Offline render: no image URL from a profile may create
                    # a network request or read an arbitrary local file.
                    report._pdf_report_link_callback = lambda uri, rel: report._BLANK_IMAGE_PATH
                    report.save_pdf_report(str(target), context)
                elif fmt == "graph":
                    report.save_graph_report(str(target), groups, db)
                elif fmt == "neo4j":
                    report.save_neo4j_report(str(target), groups, db)
                elif fmt == "xmind":
                    combined = {}
                    for value, kind, results in groups:
                        for name, result in results.items():
                            combined[f"{name} ({kind}:{value})"] = result
                    report.save_xmind_report(str(target), "Candidatos de Person Map", combined)
                content = target.read_bytes()
                if fmt == "neo4j":
                    content = ("// " + SCOPE + "\n").encode() + content
                elif fmt == "graph":
                    import html
                    content = content.replace(b"<body>", ("<body><p>" + html.escape(SCOPE) + "</p>").encode(), 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Report exceeds export size limit")
    if fmt in {"html", "graph"}:
        policy = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'"
        import html
        content = content.replace(b"<head>", ("<head><meta http-equiv=\"Content-Security-Policy\" content=\"" + html.escape(policy, quote=True) + "\">").encode(), 1)
    return {"mime_type": mime, "extension": extension, "body": base64.b64encode(content).decode(),
            "records": sum(len(results) for _, _, results in groups), "scope": "candidate_evidence"}
