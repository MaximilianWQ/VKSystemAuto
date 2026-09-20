from app import setup_tokens


async def test_issued_token_is_accepted_once(pool):
    token = await setup_tokens.issue(pool)
    assert await setup_tokens.consume(pool, token) is True
    assert await setup_tokens.consume(pool, token) is False


async def test_raw_token_is_not_stored(pool):
    """В базе лежит только хеш: дамп БД не должен давать доступ к дашборду."""
    token = await setup_tokens.issue(pool)
    stored = await pool.fetchval("SELECT token_hash FROM setup_tokens")
    assert stored != token
    assert token not in stored


async def test_unknown_token_rejected(pool):
    assert await setup_tokens.consume(pool, "выдуманный") is False


async def test_expired_token_rejected(pool):
    token = await setup_tokens.issue(pool, ttl_seconds=-1)
    assert await setup_tokens.consume(pool, token) is False


async def test_tokens_are_unique(pool):
    tokens = {await setup_tokens.issue(pool) for _ in range(20)}
    assert len(tokens) == 20


async def test_token_is_long_enough_to_resist_guessing(pool):
    assert len(await setup_tokens.issue(pool)) >= 32


async def test_purge_removes_expired_only(pool):
    fresh = await setup_tokens.issue(pool)
    await setup_tokens.issue(pool, ttl_seconds=-1)
    assert await setup_tokens.purge_expired(pool) == 1
    assert await setup_tokens.consume(pool, fresh) is True
