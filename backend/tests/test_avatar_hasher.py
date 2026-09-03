import pytest
from PIL import Image
import imagehash
from io import BytesIO
from app.identity.avatar_hasher import AvatarHasher
from app.models.entity import Entity


def test_avatar_hasher_hamming_distance():
    hasher = AvatarHasher()

    # Create two identical test images
    img_a = Image.new("RGB", (100, 100), color=(73, 109, 137))
    img_b = Image.new("RGB", (100, 100), color=(73, 109, 137))

    hash_a = imagehash.dhash(img_a, hash_size=hasher.HASH_SIZE)
    hash_b = imagehash.dhash(img_b, hash_size=hasher.HASH_SIZE)

    is_match, dist = hasher.compare_hashes(hash_a, hash_b)
    assert is_match is True
    assert dist == 0

    # Create a completely different noise image
    img_c = Image.new("RGB", (100, 100), color=(255, 255, 255))
    for x in range(0, 100, 2):
        for y in range(0, 100, 2):
            img_c.putpixel((x, y), (0, 0, 0))

    hash_c = imagehash.dhash(img_c, hash_size=hasher.HASH_SIZE)
    is_match_c, dist_c = hasher.compare_hashes(hash_a, hash_c)
    assert dist_c > hasher.HAMMING_MATCH_THRESHOLD


@pytest.mark.asyncio
async def test_correlate_entity_avatars_empty_or_single():
    hasher = AvatarHasher()
    # Empty list
    corrs = await hasher.correlate_entity_avatars([])
    assert corrs == []

    # Single entity
    e = Entity(
        investigation_id="test-inv",
        entity_type="social_account",
        platform="github",
        value="https://github.com/test",
        display_name="Test",
        metadata_info={"avatar_url": "https://example.com/avatar.jpg"},
    )
    corrs = await hasher.correlate_entity_avatars([e])
    assert corrs == []
