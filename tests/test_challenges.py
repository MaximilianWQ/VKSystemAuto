from app.web import challenges


async def test_issued_challenge_is_returned_once(pool):
    challenge_id = await challenges.issue(pool, b"\x01\x02\x03", "register")
    assert await challenges.consume(pool, challenge_id, "register") == b"\x01\x02\x03"
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_purpose_must_match(pool):
    """Challenge для входа нельзя подсунуть в регистрацию."""
    challenge_id = await challenges.issue(pool, b"\x01", "login")
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_expired_challenge_rejected(pool):
    challenge_id = await challenges.issue(pool, b"\x01", "register", ttl_seconds=-1)
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_unknown_id_rejected(pool):
    assert await challenges.consume(pool, "выдуманный", "register") is None


async def test_purge_removes_expired_only(pool):
    fresh = await challenges.issue(pool, b"\x01", "register")
    await challenges.issue(pool, b"\x02", "register", ttl_seconds=-1)
    assert await challenges.purge_expired(pool) == 1
    assert await challenges.consume(pool, fresh, "register") == b"\x01"
