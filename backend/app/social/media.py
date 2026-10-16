"""Explicit public CDN image references, separate from canonical publication URLs."""
import hashlib
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from app.core.config import settings

CDNS = {
    'instagram': ('cdninstagram.com', 'fbcdn.net'),
    'threads': ('cdninstagram.com', 'fbcdn.net'),
    'tiktok': ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'tiktokcdn-eu.net',
               'tiktokv.com', 'byteoversea.com', 'ibytedtos.com', 'muscdn.com'),
    'youtube': ('ytimg.com',),
}
MAX_POST_MEDIA = 20


def public_media_url(value, platform):
    if not isinstance(value, str) or len(value) > 8192 or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in {None, 443}
                or not any(host == domain or host.endswith('.' + domain) for domain in CDNS.get(platform, ()))):
            return None
        if any(key.casefold() in {'api_key', 'access_token', 'authorization', 'password', 'token'}
               for key, _ in parse_qsl(parsed.query)):
            return None
        if settings.apify_token and settings.apify_token.get_secret_value() in value:
            return None
        # CDN signatures are needed to read public media. Keep them only in the
        # stored reference; MCP citations use the post URL, never this query string.
        return urlunsplit(('https', parsed.netloc, parsed.path, parsed.query, ''))
    except ValueError:
        return None


def media_reference(value, platform, role='image'):
    url = public_media_url(value, platform)
    if not url:
        return None
    parsed = urlsplit(url)
    identity = f'{platform}:{parsed.hostname}:{parsed.path}'
    return {'id': hashlib.sha256(identity.encode()).hexdigest(), 'type': 'image',
            'role': 'video_thumbnail' if role == 'video_thumbnail' else 'image', 'url': url}


def sanitize_media(items, platform):
    result, seen = [], set()
    for item in items[:MAX_POST_MEDIA] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ref = media_reference(item.get('url'), platform, item.get('role'))
        if ref and ref['id'] not in seen:
            seen.add(ref['id'])
            result.append({**ref, 'position': len(result) + 1})
    return result


def actor_media(platform, row):
    candidates = []
    def add(url, role='image'):
        if ref := media_reference(url, platform, role):
            candidates.append(ref)
    if platform in {'instagram', 'threads'}:
        add(row.get('displayUrl'), 'video_thumbnail' if row.get('type') == 'Video' or row.get('isVideo') else 'image')
        for url in row.get('images', [])[:MAX_POST_MEDIA] if isinstance(row.get('images'), list) else []:
            add(url)
        for child in row.get('childPosts', [])[:MAX_POST_MEDIA] if isinstance(row.get('childPosts'), list) else []:
            if isinstance(child, dict):
                add(child.get('displayUrl'), 'video_thumbnail' if child.get('type') == 'Video' or child.get('isVideo') else 'image')
        # Threads' documented image candidate structure; choose one resolution.
        candidates_raw = (row.get('image_versions2') or {}).get('candidates', []) if isinstance(row.get('image_versions2'), dict) else []
        if candidates_raw and isinstance(candidates_raw[0], dict):
            add(candidates_raw[0].get('url'))
    elif platform == 'tiktok':
        video = row.get('videoMeta') if isinstance(row.get('videoMeta'), dict) else {}
        add(video.get('coverUrl') or video.get('originalCoverUrl'), 'video_thumbnail')
        slides = row.get('slideshowImageLinks')
        for slide in slides[:MAX_POST_MEDIA] if isinstance(slides, list) else []:
            add(slide if isinstance(slide, str) else slide.get('downloadLink') if isinstance(slide, dict) else None)
    elif platform == 'youtube':
        add(row.get('thumbnailUrl') or row.get('thumbnail'), 'video_thumbnail')
    return sanitize_media(candidates, platform)
