import asyncio
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
import httpx
import imagehash
from PIL import Image


class AvatarHasher:
    """
    Perceptual Image Hashing Engine for Avatar Correlation.
    Uses Difference Hashing (dHash) and Hamming Distance to identify
    when an individual reuses the same profile photo across disparate platforms
    (e.g., Gravatar, GitHub, Twitter, Keybase), boosting correlation confidence to 99%.
    """

    HAMMING_MATCH_THRESHOLD = 6  # <= 6 indicates near-identical or resized image
    HASH_SIZE = 8

    async def compute_dhash_from_url(self, client: httpx.AsyncClient, url: str) -> Optional[imagehash.ImageHash]:
        """Downloads an image from a URL and computes its perceptual dHash."""
        if not url or not url.startswith("http"):
            return None
        try:
            resp = await client.get(url, timeout=6.0)
            if resp.status_code != 200:
                return None
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            return imagehash.dhash(img, hash_size=self.HASH_SIZE)
        except Exception:
            return None

    def compare_hashes(self, hash_a: imagehash.ImageHash, hash_b: imagehash.ImageHash) -> Tuple[bool, int]:
        """Calculates Hamming distance between two perceptual hashes."""
        dist = int(hash_a - hash_b)
        is_match = bool(dist <= self.HAMMING_MATCH_THRESHOLD)
        return is_match, dist

    async def correlate_entity_avatars(
        self, entities: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        Extracts avatar URLs from entities, calculates perceptual hashes,
        and performs all-pairs Hamming distance comparison.
        """
        targets_with_avatars: List[Dict[str, Any]] = []

        for ent in entities:
            metadata = getattr(ent, "metadata_info", {}) or {}
            avatar_url = metadata.get("avatar_url") or metadata.get("photo_url")
            if avatar_url and isinstance(avatar_url, str) and avatar_url.startswith("http"):
                targets_with_avatars.append({
                    "entity_id": str(getattr(ent, "id", "")),
                    "platform": getattr(ent, "platform", "unknown"),
                    "display_name": getattr(ent, "display_name", "") or getattr(ent, "value", ""),
                    "avatar_url": avatar_url,
                })

        if len(targets_with_avatars) < 2:
            return []

        # Download and hash concurrently
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, headers=headers, verify=False) as client:
            tasks = [self.compute_dhash_from_url(client, item["avatar_url"]) for item in targets_with_avatars]
            hashes = await asyncio.gather(*tasks, return_exceptions=True)

        hashed_entries = []
        for item, h in zip(targets_with_avatars, hashes):
            if isinstance(h, imagehash.ImageHash):
                hashed_entries.append({**item, "hash": h})

        correlations: List[Dict[str, Any]] = []
        for i, a in enumerate(hashed_entries):
            for b in hashed_entries[i + 1 :]:
                if a["entity_id"] == b["entity_id"]:
                    continue

                is_match, dist = self.compare_hashes(a["hash"], b["hash"])
                if is_match:
                    # Confidence scales inversely with Hamming distance: distance 0 => 0.99, distance 6 => 0.85
                    confidence = round(max(0.85, 0.99 - (dist * 0.02)), 2)
                    correlations.append({
                        "entity_a_id": a["entity_id"],
                        "entity_b_id": b["entity_id"],
                        "platform_a": a["platform"],
                        "platform_b": b["platform"],
                        "hamming_distance": dist,
                        "confidence": confidence,
                        "match_type": "exact_avatar" if dist == 0 else "visually_similar_avatar",
                        "avatar_a": a["avatar_url"],
                        "avatar_b": b["avatar_url"],
                    })

        return correlations


avatar_hasher = AvatarHasher()
