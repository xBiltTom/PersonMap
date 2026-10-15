import pytest
import asyncio
import json
import httpx
from urllib.parse import parse_qs
from app.core.config import settings
from app.tools.username_finder import UsernameFinderTool
from app.tools.base import TargetContext
from app.tools.dataset_adapter import SiteCheck, load_whatsmyname, WMN_FILE
from app.tools.maigret_catalog import build_scan_catalog, whatsmyname_info
from app.tools import http_client, dataset_adapter


def test_username_finder_loads_the_unified_catalog():
    """
    Desde la Fase 4.1 el catálogo lo construye `dataset_adapter` normalizando
    WhatsMyName y Maigret en memoria, y devuelve objetos `SiteCheck` en lugar de
    los diccionarios crudos del fichero.
    """
    tool = UsernameFinderTool()
    sites = tool._load_sites()

    assert len(sites) >= 50
    assert len(sites) <= settings.username_scan_max_sites

    site_names = [s.name.lower() for s in sites]
    assert any("github" in name for name in site_names)
    assert any("reddit" in name for name in site_names)

    # La priorización es por ranking real, no por una lista escrita a mano: los
    # primeros del catálogo tienen que ser plataformas masivas.
    primeros = " ".join(site_names[:25])
    assert any(p in primeros for p in ("facebook", "youtube", "twitter", "linkedin"))


def test_username_finder_filters_generic_roles():
    tool = UsernameFinderTool()
    assert "admin" in tool._generic_users
    assert "root" in tool._generic_users
    assert "support" in tool._generic_users


@pytest.mark.asyncio
async def test_username_finder_empty_context():
    tool = UsernameFinderTool()
    context = TargetContext()
    findings = await tool.execute(context)
    assert findings == []


def test_every_usable_wmn_recipe_survives_the_normal_deep_budget(monkeypatch):
    monkeypatch.setattr(settings, "username_scan_max_sites", 3400)
    monkeypatch.setattr(settings, "maigret_tags", [])
    monkeypatch.setattr(settings, "maigret_site_names", [])
    monkeypatch.setattr(settings, "maigret_excluded_tags", [])
    usable = load_whatsmyname()
    scanned = [s for s in UsernameFinderTool()._load_sites() if s.source == "whatsmyname"]
    assert sorted(s.name for s in scanned) == sorted(s.name for s in usable)
    for family in (("YouTube Channel", "YouTube User", "YouTube User2"),
                   ("Docker Hub (Organization)", "Docker Hub (User)")):
        assert set(family) <= {s.name for s in scanned}
    assert any(s.native_name == "GitHub" for s in build_scan_catalog(include_variants=True))
    assert len(whatsmyname_info()["whatsmyname_catalog_sha256"]) == 64


def test_wmn_loader_preserves_request_fields_from_the_snapshot():
    raw = {s["name"]: s for s in json.loads(WMN_FILE.read_text())["sites"]}
    for site in load_whatsmyname():
        recipe = raw[site.name]
        assert site.headers == recipe.get("headers", {})
        assert site.post_body == recipe.get("post_body")
        assert site.strip_bad_char == recipe.get("strip_bad_char", "")
        assert site.missing_code == recipe["m_code"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Anime-Planet", "COLOURlovers"])
async def test_real_wmn_post_recipe_and_control_use_the_same_protocol(name):
    """These probes have no alias in their URL; a GET can never check them."""
    site = next(s for s in load_whatsmyname() if s.name == name)
    requested = []
    def reply(request):
        requested.append(request)
        assert request.method == "POST"
        assert request.headers["content-type"] == site.headers["Content-Type"]
        if "json" in request.headers["content-type"]:
            alias = json.loads(request.content)["username"]
        else:
            alias = parse_qs(request.content.decode())["userName"][0]
        exists = alias == "audituser"
        return httpx.Response(site.expected_code if exists else site.missing_code,
                              text=site.presence[0] if exists else site.absence[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        finding = await UsernameFinderTool()._check_site(client, "audituser", site, asyncio.Semaphore(1),
                                                        None, {"checked": 0, "control_rejected": 0}, 1)
    assert finding is not None
    assert finding.value == site.build_pretty_url("audituser")
    assert finding.metadata_info["negative_control"] == "passed"
    assert finding.metadata_info["catalog_source"] == "whatsmyname"
    assert len(requested) == 2
    assert requested[0].content != requested[1].content


@pytest.mark.asyncio
async def test_wmn_post_catchall_is_rejected():
    site = next(s for s in load_whatsmyname() if s.name == "Anime-Planet")
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(site.expected_code, text=site.presence[0]))) as client:
        counter = {"checked": 0, "control_rejected": 0}
        finding = await UsernameFinderTool()._check_site(client, "audituser", site, asyncio.Semaphore(1),
                                                        None, counter, 1)
    assert finding is None
    assert counter["control_rejected"] == 1


@pytest.mark.asyncio
async def test_wmn_normalization_is_used_for_urls_and_reported_alias():
    site = next(s for s in load_whatsmyname() if s.name == "Blogspot")
    requested = []
    def reply(request):
        requested.append(request)
        exists = request.url.host == "audituser.blogspot.com"
        return httpx.Response(site.expected_code if exists else site.missing_code,
                              text=site.presence[0] if exists else (site.absence[0] if site.absence else ""))
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), follow_redirects=True) as client:
        finding = await UsernameFinderTool()._check_site(client, "audit.user", site, asyncio.Semaphore(1),
                                                        None, {"checked": 0, "control_rejected": 0}, 1)
    assert finding is not None
    assert finding.metadata_info["username"] == "audituser"
    assert finding.metadata_info["requested_username"] == "audit.user"
    assert finding.value == "https://audituser.blogspot.com/?hl=en-US"
    assert all("." not in req.url.host.removesuffix(".blogspot.com") for req in requested)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,body", [
    ("application/json", '{"username":"{account}"}'),
    ("application/x-www-form-urlencoded", 'username={account}'),
])
async def test_wmn_post_encodes_alias_as_data(content_type, body):
    alias = 'a"&x=ñ'
    site = SiteCheck(name="Encoding", url="https://example.org/check", post_body=body,
                     headers={"Content-Type": content_type})
    def reply(request):
        parsed = json.loads(request.content) if "json" in content_type else parse_qs(request.content.decode())
        assert parsed == {"username": alias if "json" in content_type else [alias]}
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        await UsernameFinderTool()._request_site(client, site, alias)


@pytest.mark.asyncio
async def test_wmn_redirect_status_is_checked_before_following():
    site = SiteCheck(name="Redirect", url="https://example.org/{account}", expected_code=301,
                     presence=("exists",))
    requested = []
    def reply(request):
        requested.append(request)
        return httpx.Response(301, text="exists", headers={"Location": "https://example.org/home"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), follow_redirects=True) as client:
        response = await UsernameFinderTool()._request_site(client, site, "audituser")
    assert response.status_code == 301
    assert len(requested) == 1


@pytest.mark.asyncio
async def test_wmn_unexpected_control_response_is_inconclusive():
    site = SiteCheck(name="Control", url="https://example.org/{account}", expected_code=200,
                     presence=("exists",), absence=("missing",), missing_code=404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="maintenance"))) as client:
        assert await UsernameFinderTool()._control_matches(client, site, "audituser", asyncio.Semaphore(1)) is None


@pytest.mark.asyncio
async def test_wmn_post_findings_reach_the_investigation_once(monkeypatch):
    site = next(s for s in load_whatsmyname() if s.name == "Anime-Planet")
    requested = []
    def reply(request):
        requested.append(request)
        alias = json.loads(request.content)["username"]
        return httpx.Response(site.expected_code if alias == "audituser" else site.missing_code,
                              text=site.presence[0] if alias == "audituser" else site.absence[0])
    def client(**kwargs):
        assert kwargs["rotate_ua"] is False  # Explicit recipe UAs must survive transport.
        return httpx.AsyncClient(transport=httpx.MockTransport(reply))
    monkeypatch.setattr(http_client, "build_client", client)
    tool = UsernameFinderTool()
    monkeypatch.setattr(tool, "_load_sites", lambda: [site])
    context = TargetContext(username="audituser")
    findings = await tool.execute(context)
    assert len(findings) == 1
    assert findings[0].metadata_info["catalog_source"] == "whatsmyname"
    assert findings[0].metadata_info["scan_mode"] == "deep"
    assert context.extra["username_finder_coverage"]["audituser"] == 1
    assert await tool.execute(context) == []
    assert len(requested) == 2


def test_updated_wmn_signatures_invalidate_the_catalog_cache(monkeypatch, tmp_path):
    snapshot = tmp_path / "wmn.json"
    recipe = {"name": "Cache check", "uri_check": "https://wmn.example.org/{account}",
              "e_code": 200, "e_string": "old signature", "m_code": 404, "m_string": "missing"}
    snapshot.write_text(json.dumps({"sites": [recipe]}))
    monkeypatch.setattr(dataset_adapter, "WMN_FILE", snapshot)
    monkeypatch.setattr(settings, "maigret_tags", [])
    monkeypatch.setattr(settings, "maigret_site_names", [])
    monkeypatch.setattr(settings, "maigret_excluded_tags", [])
    tool = UsernameFinderTool()
    assert next(s for s in tool._load_sites() if s.name == recipe["name"]).presence == ("old signature",)
    before = whatsmyname_info()["whatsmyname_catalog_sha256"]
    recipe["e_string"] = "new signature"
    snapshot.write_text(json.dumps({"sites": [recipe]}))
    assert whatsmyname_info()["whatsmyname_catalog_sha256"] != before
    assert next(s for s in tool._load_sites() if s.name == recipe["name"]).presence == ("new signature",)
