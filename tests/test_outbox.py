from app.db import queries as q
from app.vk import outbox
from app.vk.client import VKCallError


class FakeClient:
    """Считает вызовы и умеет падать заданными кодами по очереди."""

    def __init__(self, errors=None):
        self.calls = []
        self._errors = list(errors or [])

    async def call(self, method, **params):
        self.calls.append((method, params))
        if self._errors:
            code = self._errors.pop(0)
            if code is not None:
                raise VKCallError(code=code, method=method)
        return {"message_id": len(self.calls)}


async def test_enqueue_stores_pending_row_with_random_id(pool):
    row_id = await outbox.enqueue(pool, peer_id=1, text="привет")
    row = await pool.fetchrow("SELECT * FROM outbox WHERE id = $1", row_id)
    assert row["status"] == "pending"
    assert row["peer_id"] == 1
    assert row["payload"]["message"] == "привет"
    assert 0 < row["random_id"] <= 2**31 - 1


async def test_random_id_differs_between_messages(pool):
    a = await outbox.enqueue(pool, peer_id=1, text="раз")
    b = await outbox.enqueue(pool, peer_id=1, text="два")
    ids = await pool.fetch("SELECT random_id FROM outbox WHERE id = ANY($1::bigint[])", [a, b])
    assert ids[0]["random_id"] != ids[1]["random_id"]


async def test_process_batch_sends_and_marks_sent(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    client = FakeClient()
    assert await outbox.process_batch(pool, client) == 1

    method, params = client.calls[0]
    assert method == "messages.send"
    assert params["peer_id"] == 1
    assert params["message"] == "привет"
    assert "random_id" in params

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "sent"
    assert row["sent_at"] is not None


async def test_retry_reuses_the_same_random_id(pool):
    """Это то, что не даёт клиенту получить дубль после ретрая."""
    await outbox.enqueue(pool, peer_id=1, text="привет")
    original = await pool.fetchval("SELECT random_id FROM outbox")

    failing = FakeClient(errors=[6])
    await outbox.process_batch(pool, failing)
    assert await pool.fetchval("SELECT random_id FROM outbox") == original

    await pool.execute("UPDATE outbox SET next_attempt_at = now()")
    ok = FakeClient()
    await outbox.process_batch(pool, ok)
    assert ok.calls[0][1]["random_id"] == original


async def test_error_6_backs_off_and_stays_pending(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[6]))
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] > row["created_at"]


async def test_error_9_delays_long(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[9]))
    delay = await pool.fetchval(
        "SELECT extract(epoch FROM next_attempt_at - now()) FROM outbox"
    )
    assert delay > outbox.FLOOD_DELAY_SECONDS - 10


async def test_error_901_fails_permanently_and_blocks_user(pool):
    await q.upsert_user(pool, 1)
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[901]))

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "failed"
    assert (await q.get_user(pool, 1))["can_write"] is False


async def test_gives_up_after_max_attempts(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    for _ in range(outbox.MAX_ATTEMPTS):
        await pool.execute("UPDATE outbox SET next_attempt_at = now()")
        await outbox.process_batch(pool, FakeClient(errors=[10]))
    assert await pool.fetchval("SELECT status FROM outbox") == "failed"


async def test_skips_rows_scheduled_for_later(pool):
    await outbox.enqueue(pool, peer_id=1, text="потом")
    await pool.execute("UPDATE outbox SET next_attempt_at = now() + interval '1 hour'")
    client = FakeClient()
    assert await outbox.process_batch(pool, client) == 0
    assert client.calls == []


async def test_recover_stuck_returns_sending_rows_to_pending(pool):
    """Процесс убили посреди отправки — строка не должна зависнуть навсегда."""
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await pool.execute("UPDATE outbox SET status = 'sending'")
    assert await outbox.recover_stuck(pool) == 1
    assert await pool.fetchval("SELECT status FROM outbox") == "pending"


async def test_preserves_order_within_one_peer(pool):
    for i in range(5):
        await outbox.enqueue(pool, peer_id=1, text=str(i))
    client = FakeClient()
    await outbox.process_batch(pool, client)
    assert [c[1]["message"] for c in client.calls] == ["0", "1", "2", "3", "4"]


async def test_attachment_and_keyboard_are_passed_through(pool):
    await outbox.enqueue(
        pool, peer_id=1, text="вот", attachment="photo1_2", keyboard='{"buttons":[]}'
    )
    client = FakeClient()
    await outbox.process_batch(pool, client)
    params = client.calls[0][1]
    assert params["attachment"] == "photo1_2"
    assert params["keyboard"] == '{"buttons":[]}'
