"""Inspect, audit or explicitly update a separate Maigret catalogue snapshot."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tools import http_client
from app.tools.maigret_catalog import capabilities, native_recipes
from app.tools.maigret_runner import run_maigret


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["info", "list", "check", "update"])
    parser.add_argument("--sites", nargs="+", default=[])
    parser.add_argument("--id-type", default="username")
    parser.add_argument("--ref", help="Explicit upstream tag or commit for a separate catalogue snapshot")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "info":
        print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
    elif args.mode == "list":
        print(json.dumps([{"name": site.name, "url": site.url, "id_type": site.id_type,
                           "protocol": site.protocol, "tags": site.tags}
                          for site in native_recipes(args.id_type, ("", "tor", "i2p", "dns")).values()], indent=2))
    elif args.mode == "check":
        if not args.sites or len(args.sites) > 30:
            parser.error("Selecciona entre uno y 30 sitios con --sites; no se ejecuta un barrido implícito")
        recipes = native_recipes(id_type=None, protocols=("", "tor", "i2p", "dns"))
        if any(name not in recipes for name in args.sites):
            parser.error("Algún nombre no está en el catálogo activo")
        results = []
        async def collected(value):
            results.append(value)
        await run_maigret("", [recipes[name] for name in args.sites], {}, collected, operation="self_check")
        rendered = json.dumps(results[0], ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n")
        print(rendered)
    else:
        if not args.output or not args.ref or not re.fullmatch(r"(?:v?\d+(?:\.\d+){1,3}|[a-fA-F0-9]{40})", args.ref):
            parser.error("Usa --ref con un tag de versión o commit completo y --output para un snapshot nuevo")
        if args.output.exists():
            parser.error("El snapshot de salida ya existe; usa otro nombre para conservarlo")
        source = f"https://raw.githubusercontent.com/soxoj/maigret/{args.ref}/maigret/resources/data.json"
        async with http_client.build_client(timeout=30, public_only=True) as client:
            response = await client.get(source)
            response.raise_for_status()
        document = response.json()
        if len(response.content) > 20 * 1024 * 1024 or not all(isinstance(document.get(key), dict) for key in ("sites", "engines")):
            raise ValueError("Invalid upstream catalogue")
        content = response.content
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental replacement of an earlier snapshot.
        with args.output.open("xb") as target:
            target.write(content)
        provenance = {"source": source, "ref": args.ref, "sha256": hashlib.sha256(content).hexdigest(),
                      "sites": len(document["sites"])}
        args.output.with_suffix(args.output.suffix + ".meta.json").write_text(json.dumps(provenance, indent=2) + "\n")
        print(json.dumps({"snapshot": str(args.output), **provenance}, indent=2))
        print("Configura MAIGRET_DATABASE_FILE con este archivo y reinicia el servicio para utilizarlo.")


if __name__ == "__main__":
    asyncio.run(main())
