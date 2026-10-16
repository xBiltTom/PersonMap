"""Paid benchmark safety and reproducible build reporting, with mocked transport."""
import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import settings
from scripts import apify_live_benchmark as benchmark


def args(tmp_path, **overrides):
    values = dict(account=["instagram:apify"], output=tmp_path / "report.json",
                  content_limit=1, charge_per_run=.03, charge_total=.12, reddit_mode="users")
    return SimpleNamespace(**(values | overrides))


@pytest.mark.asyncio
async def test_missing_token_produces_explicit_unvalidated_report_without_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "apify_token", None)
    def forbidden():
        pytest.fail("No client without token")
    monkeypatch.setattr(benchmark, "ApifyClient", forbidden)
    options = args(tmp_path)
    await benchmark.main(options)
    report = json.loads(options.output.read_text())
    assert report["reason"] == "token_missing" and report["runs"] == []
    assert report["reserved_charge_usd"] == 0 and report["validated_builds"] == {}
    assert all(row["status"] == "not_live_validated" for row in report["platforms"].values())
    with pytest.raises(FileExistsError):
        await benchmark.main(options)


@pytest.mark.parametrize("overrides", [
    {"charge_per_run": float("nan")}, {"charge_total": float("inf")},
    {"charge_per_run": .06}, {"charge_total": .01},
    {"account": ["instagram:a", "instagram:b", "instagram:c"]},
])
@pytest.mark.asyncio
async def test_invalid_budget_rejected_before_report_or_paid_start(tmp_path, overrides):
    options = args(tmp_path, **overrides)
    with pytest.raises(SystemExit):
        await benchmark.main(options)
    assert not options.output.exists()


@pytest.mark.asyncio
async def test_report_reservation_precedes_post_and_success_records_build(tmp_path, monkeypatch):
    from app.social.apify_client import ApifyRunResult
    monkeypatch.setattr(settings, "apify_token", SecretStr("test-token"))
    monkeypatch.setattr(settings, "apify_actor_builds", {"instagram": "0.9.1"})
    options = args(tmp_path)
    class Client:
        async def run(self, spec, submitted, limit, charge, *, on_update):
            saved = json.loads(options.output.read_text())
            assert saved["runs"][0]["status"] == "reserved"
            assert saved["reserved_charge_usd"] == .03
            assert limit == 1 and charge == .03
            return ApifyRunResult(actor=spec.actor, status="SUCCEEDED", build_number="0.9.1",
                items=[{"username": "apify", "fullName": "Apify", "url": "https://instagram.com/apify"}],
                usage={"usageTotalUsd": .001})
    monkeypatch.setattr(benchmark, "ApifyClient", Client)
    await benchmark.main(options)
    saved = json.loads(options.output.read_text())
    assert saved["validated_builds"] == {"instagram": "0.9.1"}
    assert saved["runs"][0]["profiles_obtained"] == 1
    assert saved["runs"][0]["useful_content_items"] == 0
    assert saved["runs"][0]["content_validation"] == "not_observed"
    assert saved["runs"][0]["usage"]["usageTotalUsd"] == .001
    assert saved["runs"][0]["elapsed_seconds"] >= 0
    assert "test-token" not in options.output.read_text()


@pytest.mark.parametrize("mode", ["users", "posts", "comments"])
def test_official_reddit_probe_bounds_user_activity(mode):
    spec, submitted = benchmark.probe("reddit", ["apify"], 1, mode)
    assert spec.actor == "apify/reddit-scraper"
    assert submitted["scrapeMode"] == mode and submitted["usernames"] == ["apify"]
    assert submitted["maxPostsPerUser"] == submitted["maxCommentsPerUser"] == 1
    assert not submitted["includeCommentReplies"]


def test_twitter_probe_disables_extra_queries():
    spec, submitted = benchmark.probe("twitter", ["apify"], 1)
    assert spec.actor == "apidojo/twitter-profile-scraper" and submitted["maxItems"] == 1
    assert not submitted["getReplies"] and not submitted["getAboutData"]
