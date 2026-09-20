"""Печатает пару ключей VAPID для веб-пушей.

Запуск: uv run python scripts/gen_vapid.py
Значения вставляются в переменные Railway, в репозиторий не попадают.
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()

    raw_public = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    public_key = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")

    private_value = vapid.private_key.private_numbers().private_value
    private_key = base64.urlsafe_b64encode(
        private_value.to_bytes(32, "big")
    ).decode().rstrip("=")

    print("VAPID_PUBLIC_KEY =", public_key)
    print("VAPID_PRIVATE_KEY =", private_key)
    print("VAPID_SUBJECT = mailto:укажите@свою.почту")


if __name__ == "__main__":
    main()
