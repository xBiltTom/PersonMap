"""Private GHunt 2.3.4 worker, launched with its own Python via -I.

Uses upstream APIs/parsers (AGPL-3.0, https://github.com/mxrch/GHunt).
Only HTTP transport, bounded collection and normalized output are adapted.
No imports from PersonMap: GHunt never enters the API's interpreter.
"""
import asyncio
import base64
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import traceback


class Bridge:
    def __init__(self, reader, output):
        self.reader, self.output = reader, output
        self.pending, self.sequence, self.statuses = {}, 0, []

    def emit(self, data):
        self.output.write(json.dumps(data, ensure_ascii=True) + "\n")
        self.output.flush()

    async def receive(self):
        while line := await self.reader.readline():
            message = json.loads(line)
            future = self.pending.get(message.get("id"))
            if future is not None and not future.done():
                future.set_result(message)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Parent disconnected"))

    def transport(self):
        import httpx
        bridge = self

        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                bridge.sequence += 1
                key = bridge.sequence
                future = asyncio.get_running_loop().create_future()
                bridge.pending[key] = future
                bridge.emit({"event": "request", "id": key, "method": request.method,
                    "url": str(request.url), "headers": request.headers.multi_items(),
                    "body": base64.b64encode(await request.aread()).decode()})
                try:
                    response = await future
                finally:
                    bridge.pending.pop(key, None)
                if response.get("error"):
                    raise httpx.TransportError("Parent request failed")
                bridge.statuses.append(response["status"])
                return httpx.Response(response["status"], headers=response["headers"],
                    content=base64.b64decode(response["body"]), request=request)

        return Transport()


def text(value, limit=500):
    return value[:limit] if isinstance(value, str) else ""


def date(value):
    return value.isoformat() if hasattr(value, "isoformat") else None


def profile_record(target):
    """PROFILE only: never export the operator's CONTACT/AFFINITY containers."""
    if "PROFILE" not in target.sourceIds or not re.fullmatch(r"[0-9]{10,30}", str(target.personId)):
        return None
    photo = target.profilePhotos.get("PROFILE")
    cover = target.coverPhotos.get("PROFILE")
    return {"gaia_id": str(target.personId),
        "name": text(getattr(target.names.get("PROFILE"), "fullname", "")),
        "email": text(getattr(target.emails.get("PROFILE"), "value", ""), 320),
        "avatar_url": text(photo.url, 2048) if photo and not photo.isDefault else "",
        "cover_url": text(cover.url, 2048) if cover and not cover.isDefault else "",
        "last_updated": date(target.sourceIds["PROFILE"].lastUpdated),
        "user_types": [text(item) for item in getattr(target.profileInfos.get("PROFILE"), "userTypes", [])][:20],
        "services": [text(item) for item in getattr(target.inAppReachability.get("PROFILE"), "apps", [])][:20]}


def compatible_people_parser():
    """Keep the native parser, tolerating optional covers without provenance.

    Google can return coverPhoto entries without metadata.container. GHunt
    2.3.4 indexes that field unconditionally and loses the entire profile.
    Ignore only incomplete covers; never assign them to PROFILE ourselves.
    This replacement is scoped to this isolated, single-job worker.
    """
    import ghunt.apis.peoplepa as peoplepa
    from ghunt.parsers.people import Person

    class CompatiblePerson(Person):
        async def _scrape(self, client, data):
            self.adapter_warnings = []
            covers = data.get("coverPhoto")
            if covers:
                valid = [item for item in covers if isinstance(item, dict)
                         and isinstance(item.get("imageUrl"), str)
                         and item["imageUrl"]
                         and isinstance(item.get("metadata"), dict)
                         and isinstance(item["metadata"].get("container"), str)
                         and item["metadata"]["container"]] if isinstance(covers, list) else []
                if not isinstance(covers, list) or len(valid) != len(covers):
                    self.adapter_warnings.append("incomplete_cover_ignored")
                data = {**data, "coverPhoto": valid}
            await super()._scrape(client, data)

    peoplepa.Person = CompatiblePerson


def error_status(bridge, start):
    statuses = bridge.statuses[start:]
    if 429 in statuses:
        return "rate_limited"
    if 401 in statuses:
        return "session_expired"
    if 403 in statuses:
        return "access_denied"
    return "upstream_error"


async def authenticate(client, creds):
    """Validate native Google cookies; our APIs do not consume service OSIDs.

GHunt 2.3.4's default also bootstraps Cloud Console/Calendar OSIDs. PeoplePa,
Maps, anonymous Calendar, Play Games and Drive use cookies/SAPISID/OAuth instead.
Keep native cookie generation and checks without making unused OSIDs mandatory.
"""
    from ghunt.helpers import auth
    from ghunt.errors import GHuntLoginError
    if not creds.cookies.get("SAPISID") or not await auth.check_cookies(client, creds.cookies):
        await auth.gen_cookies_and_osids(client, creds, osids=[])
        if not creds.cookies.get("SAPISID") or not await auth.check_cookies(client, creds.cookies):
            raise GHuntLoginError("Google session validation failed")
    creds.save_creds(silent=True)


async def calendar_data(client, bridge, email, creds, max_events):
    # Authenticated access may include calendars shared with the operator.
    # Query the original parsers with authentication explicitly disabled so
    # only anonymously accessible calendar data enters the dossier.
    from ghunt.apis.calendar import CalendarHttp

    class PublicCalendar(CalendarHttp):
        def _load_endpoint(self, endpoint):
            endpoint.authentication_mode = None
            return super()._load_endpoint(endpoint)

    api = PublicCalendar(creds)
    async with __import__("httpx").AsyncClient(transport=bridge.transport(), follow_redirects=False) as anonymous:
        found, calendar = await api.get_calendar(anonymous, email)
        if not found:
            return {"status": "not_public"}
        result = {"status": "observed", "summary": text(calendar.summary),
                  "time_zone": text(calendar.time_zone), "events": [], "truncated": False}
        if max_events:
            found_events, events = await api.get_events(anonymous, email, max_results=max_events)
            if found_events:
                result["truncated"] = bool(events.next_page_token)
                result["events"] = [{"summary": text(event.summary),
                    "start": date(event.start.date_time), "end": date(event.end.date_time)}
                    for event in events.items[:max_events]]
        return result


async def drive_data(client, creds, query):
    from ghunt.apis.drive import DriveHttp
    from ghunt.helpers.drive import get_users_from_file
    api = DriveHttp(creds)
    if query.get("resource_key"):
        api.headers["X-Goog-Drive-Resource-Keys"] = query["value"] + "/" + query["resource_key"]
    found, file = await api.get_file(client, query["value"])
    if not found:
        return {"status": "not_found_or_inaccessible"}
    # Do not export a file merely because it is in the operator's private Drive.
    if not any(permission.id == "anyoneWithLink" or getattr(permission, "type", "") == "anyone"
               for permission in file.permissions):
        return {"status": "not_public"}
    users = get_users_from_file(file)
    if not isinstance(users, list):
        users = list(users.values())  # Upstream returns a dict on one early-return path.
    return {"status": "observed", "id": text(file.id), "title": text(file.title),
        "mime_type": text(file.mime_type), "created": date(file.created_date), "modified": date(file.modified_date),
        "users": [{"name": text(user.name), "email": text(user.email_address, 320),
                   "gaia_id": text(user.gaia_id), "role": text(user.role),
                   "last_modifier": bool(user.is_last_modifying_user)} for user in users[:30]]}


async def collect(job, bridge):
    from ghunt import globals as gb
    gb.init_globals()
    from ghunt.helpers import auth, gmaps, playgames
    from ghunt.objects.base import GHuntCreds
    from ghunt.apis.peoplepa import PeoplePaHttp
    from ghunt.lib.httpx import AsyncClient

    compatible_people_parser()

    class Credentials(GHuntCreds):
        def are_creds_loaded(self):
            return bool(self.cookies and self.android.master_token)

        def save_creds(self, silent=False):
            # Upstream refresh writes on every authentication. Replace atomically
            # with private permissions, under the parent's session lock.
            destination = Path(self.creds_path)
            descriptor, temporary = tempfile.mkstemp(prefix=".ghunt-", dir=destination.parent)
            os.close(descriptor)
            original = self.creds_path
            try:
                self.creds_path = temporary
                super().save_creds(silent=True)
                os.replace(temporary, destination)
            finally:
                self.creds_path = original
                if os.path.exists(temporary):
                    os.unlink(temporary)

    creds = Credentials(job["credentials"])
    async with AsyncClient(transport=bridge.transport(), timeout=job["timeout"], follow_redirects=False) as client:
        try:
            creds.load_creds(silent=True)
        except Exception:
            return {"status": "session_invalid", "services": {}}
        start = len(bridge.statuses)
        try:
            await authenticate(client, creds)
        except Exception:
            status = error_status(bridge, start)
            return {"status": "session_expired" if status in {"session_expired", "access_denied"} else "authentication_failed", "services": {}}
        query = job["query"]
        if query["kind"] == "status":
            return {"status": "authenticated", "services": {}}
        start = len(bridge.statuses)
        if query["kind"] == "drive":
            try:
                result = await drive_data(client, creds, query)
                return {"status": result["status"], "drive": result, "services": {}}
            except Exception:
                return {"status": error_status(bridge, start), "services": {}}
        api = PeoplePaHttp(creds)
        try:
            found, target = (await api.people_lookup(client, query["value"], params_template="max_details")
                             if query["kind"] == "email" else
                             await api.people(client, query["value"], params_template="max_details"))
            if not found:
                return {"status": "not_found", "services": {}}
            profile = profile_record(target)
            if not profile:
                return {"status": "no_public_profile", "services": {}}
        except Exception as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            return {"status": error_status(bridge, start), "error_type": type(exc).__name__,
                    "error_frame": {"module": Path(frame.filename).stem, "function": frame.name, "line": frame.lineno},
                    "services": {}}
        result = {"status": "observed", "profile": profile, "services": {},
                  "warnings": getattr(target, "adapter_warnings", [])}
        for service in job["services"]:
            start = len(bridge.statuses)
            try:
                if service == "maps":
                    status, stats = await gmaps.get_reviews(client, profile["gaia_id"])
                    result["services"][service] = {"status": {"empty": "empty", "failed": "blocked"}.get(status, "observed"),
                        "statistics": {text(key, 100): value for key, value in stats.items()
                                       if isinstance(value, int) and not isinstance(value, bool)}}
                elif service == "calendar" and query["kind"] == "email":
                    result["services"][service] = await calendar_data(client, bridge, query["value"], creds, job["max_events"])
                elif service == "play_games" and query["kind"] == "email":
                    candidates = await playgames.search_player(creds, client, query["value"])
                    # Search rank never confirms a player belongs to the email.
                    result["services"][service] = {"status": "candidates" if candidates else "empty",
                        "players": [{"id": text(item.id), "name": text(item.name),
                                     "avatar_url": text(item.avatar_url, 2048)} for item in candidates[:3]]}
                else:
                    result["services"][service] = {"status": "requires_email"}
            except Exception:
                result["services"][service] = {"status": error_status(bridge, start)}
        return result


async def main(job, output):
    reader = asyncio.StreamReader(limit=8 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    bridge = Bridge(reader, output)
    receiver = asyncio.create_task(bridge.receive())
    try:
        try:
            from importlib.metadata import version
            result = (await collect(job, bridge) if version("ghunt") == "2.3.4" else
                      {"status": "runtime_version_mismatch", "services": {}})
        except Exception:
            result = {"status": "worker_error", "services": {}}
        bridge.emit({"event": "result", "result": result})
    finally:
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiver


def private_session_payload(creds, stage=None):
    data = {"cookies": creds.cookies, "osids": creds.osids,
            "android": {"master_token": creds.android.master_token,
                        "authorization_tokens": creds.android.authorization_tokens}}
    if stage:
        data["_person_map"] = {"state": "pending", "stage": stage}
    return data


def write_private_session(path, payload, *, exclusive=False):
    descriptor, temporary = tempfile.mkstemp(prefix=".ghunt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(base64.b64encode(json.dumps(payload).encode()))
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def companion_cookies(raw):
    if not isinstance(raw, dict) or len(raw) > 100:
        raise ValueError("Invalid cookie container")
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key)
           or not isinstance(value, str) or len(value) > 16384 or any(ord(ch) < 32 for ch in value)
           for key, value in raw.items()):
        raise ValueError("Invalid cookie value")
    return dict(raw)


async def login(destination, *, resume=False):
    """Local operator bootstrap. Secrets are read without echo or argv tokens."""
    from getpass import getpass
    from ghunt.helpers import auth
    from ghunt.objects.base import GHuntCreds
    from ghunt.lib.httpx import AsyncClient
    path = Path(destination).expanduser().absolute()
    if path.exists():
        print("La sesión ya existe. Usa otra ruta para iniciar una sesión nueva.")
        return 2
    checkpoint = path.with_name(path.name + ".ghunt-pending")
    if not resume and checkpoint.exists():
        print("Hay un inicio de sesión pendiente. Ejecuta ghunt_session.py resume con la misma ruta --credentials.")
        return 2
    stage = "lectura_de_autenticacion"
    try:
        cookies, tokens, master, oauth = {}, {}, "", ""
        if resume:
            with checkpoint.open("rb") as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Pending session too large")
            data = json.loads(base64.b64decode(raw, validate=True))
            master = data["android"]["master_token"]
            tokens = data["android"].get("authorization_tokens", {})
            cookies = companion_cookies(data.get("cookies", {}))
        else:
            value = getpass("Autenticación de GHunt Companion, OAuth token o master token (entrada oculta): ").strip()
            if len(value) > 1024 * 1024:
                raise ValueError("Authentication too large")
            if value.startswith("aas_et/"):
                master = value
            elif value.startswith("oauth2_4/"):
                oauth = value
            else:
                data = json.loads(base64.b64decode(value, validate=True))
                oauth = data["oauth_token"]
                cookies = companion_cookies(data.get("cookies", {}))
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        class LoginCredentials(GHuntCreds):
            def are_creds_loaded(self):
                return bool(self.cookies and self.android.master_token)

            def save_creds(self, silent=False):
                write_private_session(checkpoint, private_session_payload(self, stage))
        creds = LoginCredentials(str(path))
        async with AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            if oauth:
                stage = "intercambio_oauth"
                master, _, _, _ = await auth.android_master_auth(client, oauth)
            if not isinstance(master, str) or not master or len(master) > 16384 or not isinstance(tokens, dict):
                raise ValueError("Invalid master credentials")
            creds.android.master_token = master
            creds.android.authorization_tokens = tokens
            # Native OAuth bootstrap checks for a nonempty cookie container;
            # only authenticate() can promote this checkpoint to a ready session.
            creds.cookies, creds.osids = cookies or {"a": "a"}, {}
            stage = "validacion_google"
            write_private_session(checkpoint, private_session_payload(creds, stage), exclusive=not resume)
            await authenticate(client, creds)
        stage = "guardado_de_sesion"
        write_private_session(checkpoint, private_session_payload(creds))
        # Atomic exclusive promotion; never publish a partially authenticated file.
        os.link(checkpoint, path)
        checkpoint.unlink()
        print("Sesión de GHunt guardada con permisos 0600.")
        return 0
    except Exception as exc:
        print("No se pudo iniciar sesión: " + type(exc).__name__ + ". Etapa: " + stage + ".")
        if checkpoint.is_file():
            print("Avance guardado de forma privada; usa ghunt_session.py resume con la misma ruta --credentials.")
        elif stage == "intercambio_oauth":
            print("Google rechazó el intercambio. Genera una autenticación nueva en Companion; no reutilices la anterior.")
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in {"--login", "--resume"}:
        logging.disable(logging.CRITICAL)
        sys.exit(asyncio.run(login(sys.argv[2], resume=sys.argv[1] == "--resume")))
    job = json.loads(sys.stdin.readline())
    output = sys.stdout
    sys.stdout = sys.stderr
    logging.disable(logging.CRITICAL)
    asyncio.run(main(job, output))
