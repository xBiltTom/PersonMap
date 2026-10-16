"""Small, explicit paid benchmark; no token means no network or paid start.

Run from backend: .venv/bin/python scripts/apify_live_benchmark.py --help
Reports contain schema keys and metrics, never raw profile text or credentials.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.schemas.footprint import UsernameSeed
from app.social.apify_adapter import ApifyAdapter, TEMPLATES, actor_input
from app.social.apify_client import ApifyClient
from app.social.capabilities import ACTORS, ApifyActorSpec, actor_build
from app.social.router import RoutingDecision


def probe(platform, usernames, content_limit, reddit_mode="users"):
    """Deferred Actors stay outside production ACTORS/router until validated."""
    if platform == "reddit":
        spec = ApifyActorSpec("reddit", "apify/reddit-scraper", ("username",), ("profile",), profile_row=True)
        return spec, {"scrapeMode": reddit_mode, "usernames": usernames, "includeNsfw": False,
            "maxPostsPerUser": content_limit, "maxCommentsPerUser": content_limit,
            "maxPostsPerCommunity": 1, "maxCommentsPerPost": 1, "maxCommentDepth": 1,
            "maxSearchResultsPerQuery": 1, "includeCommentReplies": False}
    spec = ApifyActorSpec("twitter", "apidojo/twitter-profile-scraper", ("username",), ("tweets",))
    return spec, {"twitterHandles": usernames, "maxItems": len(usernames) * content_limit,
                  "getReplies": False, "getAboutData": False, "includeNativeRetweets": False}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", action="append", default=[], metavar="PLATFORM:USERNAME",
        help="Public validation account, explicit only; at most 2 per platform, 6 runs overall")
    parser.add_argument("--output", type=Path, required=True, help="New report path (exclusive; refuses reuse)")
    parser.add_argument("--reddit-mode", choices=["users", "posts", "comments"], default="users")
    parser.add_argument("--content-limit", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--charge-per-run", type=float, default=.03)
    parser.add_argument("--charge-total", type=float, default=.12)
    return parser.parse_args()


async def main(args):
    if not (0 < args.charge_per_run <= .05 and 0 < args.charge_total <= .2):
        raise SystemExit("Limits must be finite, positive, <= $0.05/run and <= $0.20 overall")
    groups = {}
    for raw in args.account:
        platform, sep, value = raw.partition(":")
        if not sep or platform not in {*ACTORS, "reddit", "twitter"}:
            raise SystemExit("Expected a supported platform:username")
        username = UsernameSeed(username=value).username
        names = groups.setdefault(platform, [])
        if username not in names:
            names.append(username)
        if len(names) > min(2, settings.apify_max_profiles_per_actor):
            raise SystemExit("Too many profiles for minimal benchmark")
    if len(groups) > 6 or len(groups) * args.charge_per_run > args.charge_total + 1e-9:
        raise SystemExit("Run reservations exceed total benchmark budget")
    report = {"date": datetime.now(timezone.utc).isoformat(), "live_validation": "not_live_validated",
              "reserved_charge_usd": 0, "runs": [], "validated_builds": {},
              "platforms": {name: {"status": "not_live_validated", "build": None,
                  "usageTotalUsd": None, "elapsed_seconds": None} for name in [*ACTORS, "reddit", "twitter"]}}
    # Exclusive creation is deliberate: rerunning a command cannot silently repeat paid work.
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    def save():
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2))
        temporary.replace(args.output)
    if not settings.apify_token or not settings.apify_token.get_secret_value().strip():
        report["reason"] = "token_missing"
        save()
        print("not_live_validated: token_missing; paid starts=0")
        return
    if not groups:
        raise SystemExit("Supply explicit public validation accounts with --account")
    for platform, names in groups.items():
        requests = [RoutingDecision(platform, name, TEMPLATES[platform].format(name), "hybrid", (),
            ACTORS[platform].actor, "benchmark") for name in names] if platform in ACTORS else []
        if platform in ACTORS:
            spec = ACTORS[platform]
            submitted = actor_input(spec, requests, args.content_limit)
        else:
            spec, submitted = probe(platform, names, args.content_limit, args.reddit_mode)
            if platform == "reddit" and args.reddit_mode != "users":
                spec = ApifyActorSpec("reddit", spec.actor, ("username",), (args.reddit_mode,))
        row_limit = len(names) if spec.profile_row else len(names) * args.content_limit
        build = actor_build(spec)
        record = {"platform": platform, "actor": spec.actor, "requested_build": build,
            "profiles_requested": len(names), "input": submitted, "status": "reserved",
            "reserved_charge_usd": args.charge_per_run}
        report["runs"].append(record)
        report["reserved_charge_usd"] = len(report["runs"]) * args.charge_per_run
        save()  # Durable reservation before POST; no automatic retry of this report.
        started = monotonic()
        def update(summary):
            record.update(summary)
            save()
        result = await ApifyClient().run(spec, submitted, row_limit, args.charge_per_run, on_update=update)
        record.update(result.summary())
        record["elapsed_seconds"] = monotonic() - started
        record["observed_schema"] = sorted({key for row in result.items if isinstance(row, dict) for key in row})
        record["nested_schema"] = {key: sorted({nested for row in result.items if isinstance(row, dict)
            for nested in (row.get(key) if isinstance(row.get(key), dict) else {})})
            for key in ("authorMeta", "aboutChannelInfo")}
        normalized = [finding for request in requests
            for finding in ApifyAdapter().normalize(spec, request, result, submitted)]
        record["profiles_obtained"] = len(normalized) if requests else None
        record["useful_content_items"] = sum(len(f.metadata_info["public_content"]) for f in normalized) if requests else None
        record["row_errors"] = sum(bool(row.get("error") or row.get("errorCode") or row.get("reasonCode"))
            for row in result.items if isinstance(row, dict))
        if not requests:
            record["assessment"] = "probe_only_requires_output_review; not integrated or build-validated"
        elif result.status == "SUCCEEDED" and not result.error and len(normalized) == len(requests):
            # Build numbers are supported by the runs build selector; build IDs remain in run summary.
            if result.build_number:
                report["validated_builds"][platform] = result.build_number
            record["validation"] = "live_profile_validated"
            record["content_validation"] = "observed" if record["useful_content_items"] else "not_observed"
        else:
            record["validation"] = "failed_or_incomplete"
        report["platforms"][platform] = {"status": record.get("validation", "probe_only"),
            "build": result.build_number, "usageTotalUsd": result.usage.get("usageTotalUsd"),
            "elapsed_seconds": record["elapsed_seconds"]}
        save()
        if result.error in {"authentication_failed", "access_denied", "quota_exhausted", "rate_limited"}:
            break
    report["live_validation"] = "executed_see_per_actor_results"
    save()
    print("Report:", args.output)
    print("APIFY_ACTOR_BUILDS=" + json.dumps(report["validated_builds"]))


if __name__ == "__main__":
    asyncio.run(main(arguments()))
