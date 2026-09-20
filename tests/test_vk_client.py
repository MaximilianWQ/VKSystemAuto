import pytest
from vkbottle import VKAPIError

from app.vk.client import VKCallError, VKClient
from app.vk.ratelimit import RateLimiter


class FakeAPI:
    def __init__(self, responses=None, raises=None):
        self.calls = []
        self._responses = responses or []
        self._raises = raises

    async def request(self, method, data, version=None):
        self.calls.append((method, data, version))
        if self._raises:
            raise self._raises
        return self._responses.pop(0) if self._responses else {"response": 1}


def make_client(api):
    return VKClient(api, api_version="5.199", limiter=RateLimiter(rate=1000, capacity=1000))


async def test_passes_method_params_and_version():
    api = FakeAPI()
    client = make_client(api)
    await client.call("messages.send", peer_id=1, message="привет")
    method, data, version = api.calls[0]
    assert method == "messages.send"
    assert data == {"peer_id": 1, "message": "привет"}
    assert version == "5.199"


async def test_unwraps_response_key():
    api = FakeAPI(responses=[{"response": {"id": 7}}])
    client = make_client(api)
    assert await client.call("messages.send") == {"id": 7}


async def test_drops_none_params():
    api = FakeAPI()
    client = make_client(api)
    await client.call("messages.send", peer_id=1, attachment=None)
    assert api.calls[0][1] == {"peer_id": 1}


async def test_wraps_vk_error_with_code_and_method():
    api = FakeAPI(raises=VKAPIError[6](error_msg="too many requests"))
    client = make_client(api)
    with pytest.raises(VKCallError) as exc:
        await client.call("messages.send", peer_id=1)
    assert exc.value.code == 6
    assert exc.value.method == "messages.send"


async def test_error_text_carries_no_message_body():
    api = FakeAPI(raises=VKAPIError[901](error_msg="нельзя писать"))
    client = make_client(api)
    with pytest.raises(VKCallError) as exc:
        await client.call("messages.send", peer_id=1, message="секретный текст клиента")
    assert "секретный текст клиента" not in str(exc.value)
