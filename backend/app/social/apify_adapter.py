"""Per-Actor allowlist parsers into the existing ToolFinding contract.

No free-text identifier mining, audience expansion, AI enrichment or raw-row storage.
"""
from urllib.parse import parse_qs, urlsplit
import re

from app.core.config import settings
from app.social.capabilities import INSTAGRAM_POSTS
from app.schemas.footprint import discovered_provenance
from app.social.safety import public_url, text
from app.social.media import actor_media
from app.tools.base import ToolFinding
from app.tools.social_profiles import parse_social_profile, social_host

TEMPLATES = {"instagram": "https://instagram.com/{}", "tiktok": "https://tiktok.com/@{}",
             "threads": "https://threads.net/@{}", "youtube": "https://youtube.com/@{}"}


def actor_input(spec, request, item_limit):
    requests = request if isinstance(request, list) else [request]
    request = requests[0]
    if spec.actor == INSTAGRAM_POSTS.actor:
        return {"directUrls": [item.url for item in requests], "resultsType": "posts",
                "resultsLimit": item_limit, "addParentData": False}
    if spec.platform == "instagram":
        return {"usernames": [item.username for item in requests], "includeAboutSection": False}
    if spec.platform == "threads":
        return {"usernames": [item.username for item in requests]}
    if spec.platform == "tiktok":
        return {"profiles": [item.username for item in requests], "resultsPerPage": item_limit,
            "profileScrapeSections": ["videos"], "profileSorting": "latest", "maxFollowersPerProfile": 0,
            "maxFollowingPerProfile": 0, "commentsPerPost": 0, "topLevelCommentsPerPost": 0, "maxRepliesPerComment": 0,
            "shouldDownloadVideos": False, "shouldDownloadCovers": False, "shouldDownloadSlideshowImages": False,
            "shouldDownloadAvatars": False, "downloadSubtitlesOptions": "NEVER_DOWNLOAD_SUBTITLES"}
    if spec.platform == "youtube":
        return {"startUrls": [{"url": item.url} for item in requests], "maxResults": item_limit,
                "maxResultsShorts": 0, "maxResultStreams": 0, "sortVideosBy": "NEWEST"}
    raise ValueError("unsupported_actor_contract")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value[:100] if isinstance(value, list) else []


def _handle(value):
    return value.strip().lstrip("@") if isinstance(value, str) and re.fullmatch(r"@?[\w.-]{1,100}", value.strip()) else ""


def _profile(platform, raw_url, handle):
    # Derive only from an OBSERVED structured handle, never from the input query.
    raw = raw_url if isinstance(raw_url, str) and raw_url else TEMPLATES[platform].format(handle) if handle else None
    profile = parse_social_profile(url) if (url := public_url(raw)) else None
    if not profile or profile.platform != platform:
        return None
    if handle and profile.resource_kind == "username" and profile.username.casefold() != handle.casefold():
        return None
    return profile


def _matches(profile, handle, request):
    expected = parse_social_profile(request.url)
    if not expected:
        return False
    if expected.resource_kind == "channel_id":
        return profile.resource_kind == "channel_id" and profile.username == expected.username
    if profile.resource_kind == "channel_id":
        return bool(handle and handle.casefold() == expected.username.casefold())
    return profile.username.casefold() == expected.username.casefold()


def _public_links(raw_links):
    links, emails = [], []
    for raw in raw_links:
        if not isinstance(raw, str):
            continue
        # An explicit public contact link is a rule, not regex mining of a bio.
        if raw.startswith("mailto:") and text(raw, 2048) == raw and re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw[7:]):
            emails.append(raw[7:].lower())
        elif url := public_url(raw):
            links.append(url)
    return list(dict.fromkeys(links))[:10], list(dict.fromkeys(emails))[:5]


def _instagram_authorship(row, handle):
    if _handle(row.get("ownerUsername")).casefold() == handle.casefold():
        return "owner", {"id": row.get("ownerId"), "full_name": row.get("ownerFullName")}
    for author in _list(row.get("coauthorProducers")):
        if (isinstance(author, dict) and not author.get("is_unpublished")
                and _handle(author.get("username")).casefold() == handle.casefold()):
            return "coauthor", author
    return None, {}


def _content(platform, row, handle):
    if platform == "instagram":
        role, author = _instagram_authorship(row, handle)
        if row.get("ownerUsername") and role is None:
            return None
        raw_url, caption, published = row.get("url"), row.get("caption"), row.get("timestamp")
    elif platform == "threads":
        owner = _dict(row.get("user"))
        if owner.get("is_private") or owner.get("text_post_app_is_private") or not _handle(owner.get("username")):
            return None
        if owner["username"].casefold() != handle.casefold():
            return None
        code = row.get("code")
        raw_url = row.get("url") or (f"https://threads.net/@{handle}/post/{code}"
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", code) else None)
        caption, published = _dict(row.get("caption")).get("text"), row.get("taken_at")
    elif platform == "tiktok":
        raw_url, caption, published = row.get("webVideoUrl"), row.get("text"), row.get("createTimeISO")
    else:
        raw_url, caption, published = row.get("url"), row.get("description"), row.get("date")
    url = public_url(raw_url)
    hosts = {"instagram": {"instagram.com"}, "tiktok": {"tiktok.com"},
             "threads": {"threads.net", "threads.com"}, "youtube": {"youtube.com"}}
    if not url or social_host(url) not in hosts[platform] or parse_social_profile(url):
        return None
    path = urlsplit(url).path
    if platform == "instagram" and not re.fullmatch(r"/(?:p|reel)/[\w-]+/?", path):
        return None
    if platform == "tiktok" and not re.fullmatch(r"/@" + re.escape(handle) + r"/video/[0-9]+/?", path, re.I):
        return None
    if platform == "threads" and not re.fullmatch(r"/@" + re.escape(handle) + r"/post/[\w-]+/?", path, re.I):
        return None
    if platform == "youtube":
        video_ids = parse_qs(urlsplit(url).query).get("v", [])
        if path != "/watch" or len(video_ids) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_ids[0]):
            return None
    tags = [tag.get("name") if isinstance(tag, dict) else tag for tag in _list(row.get("hashtags"))]
    return {"id": text(row.get("id"), 100),
        **({"authorship_role": role} if platform == "instagram" and role else {}), "url": url,
        "kind": "video" if platform in {"youtube", "tiktok"} else "post",
        "text": text(caption), "title": text(row.get("title"), 255),
        "media": actor_media(platform, row),
        "published_at": text(published, 100) if isinstance(published, str) else published if isinstance(published, int) else None,
        **{field: row[key] for field, key in (("likes", "likesCount"), ("comments", "commentsCount"), ("views", "videoViewCount"))
           if type(row.get(key)) is int and row[key] >= 0},
        "hashtags": [text(tag, 100) for tag in tags if isinstance(tag, str)][:30],
        "mentions": [text(mention, 100) for mention in _list(row.get("mentions")) if isinstance(mention, str)][:30]}


class ApifyAdapter:
    def normalize(self, spec, request, result, submitted_input):
        finding = None
        seen_content = set()
        for row in result.items:
            if not isinstance(row, dict) or row.get("error") or row.get("errorCode") or row.get("isProfileNotExist"):
                continue
            if spec.actor == INSTAGRAM_POSTS.actor:
                # Exact observed author is mandatory; never attribute by query URL alone.
                role, author = _instagram_authorship(row, request.username)
                if role is None:
                    continue
                handle = request.username
                account = {"id": str(author.get("id") or ""), "username": handle}
                raw_url = TEMPLATES["instagram"].format(handle)
                name, bio, avatar = author.get("full_name"), None, None
                links, posts = [], [row]
            elif spec.platform == "tiktok":
                account = _dict(row.get("authorMeta"))
                if account.get("privateAccount"):
                    continue
                handle, raw_url = _handle(account.get("name")), account.get("profileUrl")
                name, bio, avatar = account.get("nickName"), account.get("signature"), account.get("avatar")
                links = [account.get("bioLink")]
                posts = [row]
            elif spec.platform == "youtube":
                account = _dict(row.get("aboutChannelInfo")) or row
                if row.get("isAgeRestricted") or account.get("isAgeRestricted"):
                    continue
                handle, raw_url = _handle(account.get("channelUsername")), account.get("channelUrl")
                name, bio, avatar = account.get("channelName"), account.get("channelDescription"), account.get("channelAvatarUrl")
                links = [_dict(link).get("url") for link in _list(account.get("channelDescriptionLinks"))]
                posts = [row]
            else:
                account = row
                if any(account.get(key) for key in ("private", "is_private", "text_post_app_is_private")):
                    continue
                handle, raw_url = _handle(account.get("username")), account.get("url")
                name, bio = account.get("fullName") or account.get("full_name"), account.get("biography")
                avatar = account.get("profilePicUrl") or account.get("profile_pic_url")
                links = [account.get("externalUrl"), *[_dict(link).get("url") for link in
                    _list(account.get("externalUrls")) + _list(account.get("bio_links"))]]
                posts = _list(row.get("latestPosts"))
            # A URL (or URL + echoed query handle) is not a profile observation.
            observed_fields = (name, bio, account.get("id"), account.get("pk"), account.get("channelId"))
            if not handle or not any(isinstance(value, str) and value.strip() for value in observed_fields):
                continue
            profile = _profile(spec.platform, raw_url, handle)
            if not profile or not _matches(profile, handle, request):
                continue
            if finding is None:
                public_links, emails = _public_links(links)
                evidence = [request.url]
                source = {"provider": "apify", "actor": spec.actor, "actor_id": result.actor_id,
                    "run_id": result.run_id, "dataset_id": result.dataset_id, "build_id": result.build_id,
                    "build_number": result.build_number, "source_platform": spec.platform,
                    "source_url": request.url, "retrieved_at": result.retrieved_at,
                    "query": {"platform": spec.platform, "username": request.username, "profile_url": request.url},
                    "input": submitted_input, "usage": result.usage}
                metadata = {"provider": "apify", "source_tool": "apify_social", "source_kind": "public_social_profile",
                    "verification_status": "verified", "ownership_status": "unverified", "access_context": "public_only",
                    "provenance": discovered_provenance(evidence), "collection_sources": [source],
                    "url": request.url, "profile_url": request.url, "observed_profile_url": profile.url,
                    "ownership": request.declared_seed or {"status": "unverified", "needs_review": True},
                    "ownership_review_required": not bool(request.declared_seed),
                    "resource_kind": profile.resource_kind, "name": text(name, 255), "bio": text(bio),
                    "linked_profiles": public_links, "website": next(iter(public_links), None),
                    "extracted_emails": emails, "extracted_usernames": [handle] if handle else [],
                    "public_content": [], "content_scope": "observed_account_not_confirmed_subject"}
                metadata["ownership_status"] = metadata["ownership"]["status"]
                if profile.resource_kind == "username":
                    metadata["username"] = profile.username
                if avatar_url := public_url(avatar):
                    metadata["avatar_url"] = avatar_url
                finding = ToolFinding(entity_type="social_account", platform=spec.platform, value=request.url,
                    display_name=text(name, 255) or profile.username, metadata_info=metadata,
                    confidence=0.6, evidence_urls=evidence)
            for post in posts:
                if len(finding.metadata_info["public_content"]) >= settings.apify_max_content_items_per_profile:
                    break
                if isinstance(post, dict) and (content := _content(spec.platform, post, handle)) and content["url"] not in seen_content:
                    content["origin"] = "automatic"
                    content["collection_source"] = finding.metadata_info["collection_sources"][0]
                    finding.metadata_info["public_content"].append(content)
                    seen_content.add(content["url"])
        return [finding] if finding else []
