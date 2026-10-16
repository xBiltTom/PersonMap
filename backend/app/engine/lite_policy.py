"""Automatic local Lite acquisition; independent of interactive Maigret plans."""
# Ordered by demo relevance, then communities, portfolios and technical forums.
PLATFORM_TIERS = (
    ('Instagram', 'TikTok', 'YouTube', 'Twitter', 'Facebook', 'Reddit', 'GitHub', 'LinkedIn', 'Telegram', 'Threads'),
    ('Bluesky', 'Twitch', 'Snapchat', 'Pinterest', 'Tumblr', 'Medium', 'Quora', 'StackOverflow', 'GitLab', 'BitBucket',
     'CodePen', 'Replit', 'Kaggle', 'HuggingFace', 'HackerNews'),
    ('Behance', 'Dribbble', 'Artstation', 'SoundCloud', 'Spotify', 'Bandcamp', 'Steam', 'Roblox', 'Chess',
     'Academia.edu', 'SlideShare', 'About.me', 'beacons.ai', 'carrd.co'),
)
COMMON_PLATFORMS = tuple(platform for tier in PLATFORM_TIERS for platform in tier)
LITE_DEADLINE_SECONDS = 225
LITE_USERNAME_RECIPES = 100


def creation_policy(payload):
    from app.core.config import settings
    if settings.personmap_env == 'lite' and payload.execution_mode == 'internal':
        return payload.model_copy(update={
            'acquisition_mode': 'fair', 'strategy': 'rule_based',
            'pivot_mode': 'standard', 'maigret_plan': None,
        })
    return payload
