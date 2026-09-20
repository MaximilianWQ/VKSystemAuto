"""Обстрел вебхука по HTTP против запущенного сервиса.

Запуск против локального сервера:
    uv run locust -f loadtests/locustfile.py --host http://localhost:8000

Критерий приёмки: p95 ниже 100 мс, ноль ответов кроме 'ok'.
"""

import itertools
import os

from locust import HttpUser, constant_pacing, task

GROUP_ID = int(os.environ.get("VK_GROUP_ID", "111"))
SECRET = os.environ.get("VK_SECRET_KEY", "секрет")

counter = itertools.count()


class CallbackUser(HttpUser):
    wait_time = constant_pacing(0.05)

    @task
    def send_event(self):
        index = next(counter)
        with self.client.post(
            "/vk/callback",
            json={
                "type": "message_new",
                "group_id": GROUP_ID,
                "secret": SECRET,
                "event_id": f"locust-{index}",
                "object": {"message": {"id": index, "from_id": 1000 + index % 50,
                                       "peer_id": 1000 + index % 50,
                                       "text": "нагрузочный тест"}},
            },
            catch_response=True,
        ) as response:
            if response.text != "ok":
                response.failure(f"ожидали 'ok', получили {response.text[:50]!r}")
