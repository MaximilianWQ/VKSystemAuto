"""Приведение вложений ВК к единому виду для хранения и показа в дашборде.

Неизвестные типы не выбрасываем: оператор должен видеть, что вложение было,
даже если мы не умеем его отрисовать.
"""

from typing import Any

RUSSIAN_NAMES = {
    "photo": ("фото", "фото", "фото"),
    "video": ("видео", "видео", "видео"),
    "doc": ("файл", "файла", "файлов"),
    "audio_message": ("голосовое", "голосовых", "голосовых"),
    "sticker": ("стикер", "стикера", "стикеров"),
    "geo": ("геопозиция", "геопозиции", "геопозиций"),
    "unsupported": ("вложение", "вложения", "вложений"),
}


def _largest(items: list[dict], key: str = "width") -> dict:
    return max(items, key=lambda i: i.get(key, 0)) if items else {}


def _photo(body: dict) -> dict:
    biggest = _largest(body.get("sizes") or [])
    return {
        "type": "photo",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "url": biggest.get("url", ""),
        "width": biggest.get("width", 0),
        "height": biggest.get("height", 0),
    }


def _video(body: dict) -> dict:
    owner_id = body.get("owner_id", 0)
    video_id = body.get("id", 0)
    url = f"https://vk.com/video{owner_id}_{video_id}"
    if body.get("access_key"):
        url += f"?access_key={body['access_key']}"
    return {
        "type": "video",
        "id": video_id,
        "owner_id": owner_id,
        "title": body.get("title", ""),
        "duration": body.get("duration", 0),
        "preview": _largest(body.get("image") or []).get("url", ""),
        "url": url,
    }


def _doc(body: dict) -> dict:
    return {
        "type": "doc",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "title": body.get("title", ""),
        "ext": body.get("ext", ""),
        "size": body.get("size", 0),
        "url": body.get("url", ""),
    }


def _audio_message(body: dict) -> dict:
    return {
        "type": "audio_message",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "duration": body.get("duration", 0),
        "link_ogg": body.get("link_ogg", ""),
        "link_mp3": body.get("link_mp3", ""),
        "waveform": body.get("waveform", []),
    }


def _sticker(body: dict) -> dict:
    return {
        "type": "sticker",
        "id": body.get("sticker_id", 0),
        "url": _largest(body.get("images") or []).get("url", ""),
    }


PARSERS = {
    "photo": _photo,
    "video": _video,
    "doc": _doc,
    "audio_message": _audio_message,
    "sticker": _sticker,
}


def parse_attachments(raw: list[dict]) -> list[dict]:
    result: list[dict] = []
    for attachment in raw or []:
        kind = attachment.get("type", "")
        parser = PARSERS.get(kind)
        if parser is None:
            result.append({"type": "unsupported", "raw_type": kind})
            continue
        result.append(parser(attachment.get(kind) or {}))
    return result


def parse_geo(geo: dict[str, Any] | None) -> dict | None:
    if not geo:
        return None
    coordinates = geo.get("coordinates") or {}
    return {
        "type": "geo",
        "lat": coordinates.get("latitude", 0.0),
        "lon": coordinates.get("longitude", 0.0),
        "title": (geo.get("place") or {}).get("title", ""),
    }


def _plural(count: int, forms: tuple[str, str, str]) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def describe(items: list[dict]) -> str:
    """Короткая сводка для текста уведомления: «2 фото, голосовое»."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1

    parts: list[str] = []
    for kind, count in counts.items():
        forms = RUSSIAN_NAMES.get(kind, RUSSIAN_NAMES["unsupported"])
        parts.append(forms[0] if count == 1 else f"{count} {_plural(count, forms)}")
    return ", ".join(parts)


MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Гифку ВК показывает документом, а не фото, поэтому она сюда не входит.
PHOTO_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")
PHOTO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def pick_uploader(content_type: str, filename: str) -> str:
    """Фото или документ. Ошибка в выборе даёт нечитаемое вложение у клиента."""
    if (content_type or "").lower() in PHOTO_TYPES:
        return "photo"
    if filename.lower().endswith(PHOTO_EXTENSIONS):
        return "photo"
    return "doc"


def _photo_uploader(api):
    from vkbottle import PhotoMessageUploader

    return PhotoMessageUploader(api)


def _doc_uploader(api):
    from vkbottle import DocMessagesUploader

    return DocMessagesUploader(api)


async def upload_photo(api, peer_id: int, data: bytes, filename: str) -> str:
    return await _photo_uploader(api).upload(file_source=data, peer_id=peer_id)


async def upload_doc(api, peer_id: int, data: bytes, filename: str) -> str:
    return await _doc_uploader(api).upload(
        file_source=data, peer_id=peer_id, title=filename
    )
