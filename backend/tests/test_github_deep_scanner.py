"""
Tests del escáner de GitHub.

Forma de las respuestas tomada de peticiones reales a la API del 2026-09-10. La
que importa: los eventos públicos ya no traen `payload.commits`, así que el
correo de autoría solo aparece al leer los commits de los repositorios.
"""

import httpx
import pytest
import respx

from app.tools.base import TargetContext
from app.tools.github_deep_scanner import GitHubDeepScannerTool

API = "https://api.github.com"


def _mock_profile(router: respx.MockRouter, *, name, commits: httpx.Response) -> None:
    router.get(f"{API}/users/JorgeWueder").mock(
        return_value=httpx.Response(
            200,
            json={
                "login": "JorgeWueder",
                "name": name,
                "bio": None,
                "public_repos": 2,
                "avatar_url": "https://avatars.githubusercontent.com/u/177425552?v=4",
                "html_url": "https://github.com/JorgeWueder",
                "blog": "",
                "company": None,
                "location": None,
                "email": None,
            },
        )
    )
    router.get(f"{API}/users/JorgeWueder/events/public").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "type": "PushEvent",
                    "created_at": "2026-09-01T16:00:00Z",
                    "repo": {"name": "JorgeWueder/proyecto-software-agil"},
                    "payload": {"push_id": 1, "ref": "refs/heads/main"},
                }
            ],
        )
    )
    # El fork no tiene ruta: si el escáner lo pidiera, respx lanzaría y el
    # perfil entero se perdería, así que el test también prueba que no lo lee.
    router.get(f"{API}/users/JorgeWueder/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"full_name": "JorgeWueder/proyecto-software-agil", "fork": False},
                {"full_name": "JorgeWueder/fork-ajeno", "fork": True},
            ],
        )
    )
    router.get(f"{API}/repos/JorgeWueder/proyecto-software-agil/commits").mock(
        return_value=commits
    )


@pytest.mark.asyncio
async def test_author_email_comes_from_repository_commits():
    commits = httpx.Response(
        200,
        json=[
            {
                "html_url": "https://github.com/JorgeWueder/proyecto-software-agil/commit/abc123",
                "commit": {"author": {"name": "Jorge de la Cruz", "email": "JorgeWueder@outlook.es"}},
            },
            {"commit": {"author": {"name": "JorgeWueder", "email": "1+JorgeWueder@users.noreply.github.com"}}},
        ],
    )
    with respx.mock() as router:
        _mock_profile(router, name=None, commits=commits)
        findings = await GitHubDeepScannerTool().execute(TargetContext(username="JorgeWueder"))

    assert len(findings) == 1
    # Normalizado y sin la dirección anónima de GitHub.
    assert findings[0].metadata_info["emails"] == ["jorgewueder@outlook.es"]
    # Y con el commit concreto que lo prueba, para poder enseñarlo.
    assert findings[0].metadata_info["email_evidence"] == [
        {
            "email": "jorgewueder@outlook.es",
            "repo": "JorgeWueder/proyecto-software-agil",
            "commit_url": "https://github.com/JorgeWueder/proyecto-software-agil/commit/abc123",
        }
    ]


@pytest.mark.asyncio
async def test_profile_without_name_does_not_invent_one():
    """
    Sin nombre en el perfil, `name` queda vacío. Rellenarlo con el login hacía
    que el modelo lo tratara como un nombre distinto del de la persona. Un
    repositorio vacío (409) tampoco debe tumbar el perfil.
    """
    with respx.mock() as router:
        _mock_profile(router, name=None, commits=httpx.Response(409, json={}))
        findings = await GitHubDeepScannerTool().execute(TargetContext(username="JorgeWueder"))

    assert len(findings) == 1
    assert findings[0].metadata_info["name"] == ""
    assert findings[0].metadata_info["emails"] == []
    assert findings[0].display_name == "@JorgeWueder"


@pytest.mark.asyncio
async def test_alias_coverage_is_durable_and_token_stays_only_in_requests(monkeypatch):
    import json
    from pydantic import SecretStr
    from app.core.config import settings
    from app.core.runtime import durable_runtime
    from app.tools.base import ToolFinding
    monkeypatch.setattr(settings, 'github_api_token', SecretStr('fixture-public-token'))
    monkeypatch.setattr(settings, 'username_scan_max_aliases', 2)
    tool = GitHubDeepScannerTool()
    scanned = []
    async def scan(client, username):
        assert client.headers['Authorization'] == 'Bearer fixture-public-token'
        scanned.append(username)
        return ToolFinding(entity_type='social_account', platform='github', value=f'https://github.com/{username}')
    monkeypatch.setattr(tool, '_scan_github_profile', scan)
    context = TargetContext(username='fixture')
    assert len(await tool.execute(context)) == 1
    context.discovered_usernames.extend(['FIXTURE', 'second-fixture', '../invalid'])
    assert len(await tool.execute(context)) == 1
    assert scanned == ['fixture', 'second-fixture']
    context.discovered_usernames.append('third-fixture')
    assert not tool.can_run(context) and await tool.execute(context) == []
    runtime = durable_runtime(context.extra)
    assert runtime['github_checked_usernames'] == ['fixture', 'second-fixture']
    assert 'fixture-public-token' not in json.dumps(runtime)
