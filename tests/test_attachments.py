from app.vk.attachments import describe, parse_attachments, parse_geo


def test_photo_picks_largest_size():
    raw = [{
        "type": "photo",
        "photo": {
            "id": 1, "owner_id": 2,
            "sizes": [
                {"type": "m", "url": "small.jpg", "width": 130, "height": 100},
                {"type": "w", "url": "big.jpg", "width": 2560, "height": 1920},
                {"type": "x", "url": "mid.jpg", "width": 604, "height": 453},
            ],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "photo"
    assert item["url"] == "big.jpg"
    assert item["width"] == 2560


def test_photo_without_sizes_is_tolerated():
    [item] = parse_attachments([{"type": "photo", "photo": {"id": 1, "owner_id": 2}}])
    assert item["type"] == "photo"
    assert item["url"] == ""


def test_video_yields_page_url_not_file():
    """VK API не отдаёт прямой файл видео — только страницу с плеером."""
    raw = [{
        "type": "video",
        "video": {
            "id": 456, "owner_id": -789, "title": "Экран", "duration": 42,
            "access_key": "abc",
            "image": [{"url": "prev.jpg", "width": 320, "height": 240}],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "video"
    assert item["url"] == "https://vk.com/video-789_456?access_key=abc"
    assert item["preview"] == "prev.jpg"
    assert item["duration"] == 42


def test_video_without_access_key():
    raw = [{"type": "video", "video": {"id": 1, "owner_id": 2, "title": "", "image": []}}]
    [item] = parse_attachments(raw)
    assert item["url"] == "https://vk.com/video2_1"


def test_doc_keeps_metadata():
    raw = [{
        "type": "doc",
        "doc": {"id": 5, "owner_id": 6, "title": "счёт.pdf", "ext": "pdf",
                "size": 10240, "url": "https://vk.com/doc.pdf"},
    }]
    [item] = parse_attachments(raw)
    assert item == {
        "type": "doc", "id": 5, "owner_id": 6, "title": "счёт.pdf",
        "ext": "pdf", "size": 10240, "url": "https://vk.com/doc.pdf",
    }


def test_audio_message_keeps_both_links_and_waveform():
    raw = [{
        "type": "audio_message",
        "audio_message": {
            "id": 9, "owner_id": 10, "duration": 7,
            "link_ogg": "voice.ogg", "link_mp3": "voice.mp3",
            "waveform": [1, 5, 3],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "audio_message"
    assert item["duration"] == 7
    assert item["link_ogg"] == "voice.ogg"
    assert item["link_mp3"] == "voice.mp3"
    assert item["waveform"] == [1, 5, 3]


def test_sticker_picks_largest_image():
    raw = [{
        "type": "sticker",
        "sticker": {"sticker_id": 3, "images": [
            {"url": "s64.png", "width": 64},
            {"url": "s512.png", "width": 512},
        ]},
    }]
    [item] = parse_attachments(raw)
    assert item == {"type": "sticker", "id": 3, "url": "s512.png"}


def test_unknown_type_is_marked_not_dropped():
    """Терять вложение молча нельзя — оператор должен видеть, что оно было."""
    [item] = parse_attachments([{"type": "market", "market": {"id": 1}}])
    assert item == {"type": "unsupported", "raw_type": "market"}


def test_malformed_attachment_does_not_crash():
    assert parse_attachments([{"type": "photo"}]) == [{"type": "photo", "url": "",
                                                       "id": 0, "owner_id": 0,
                                                       "width": 0, "height": 0}]


def test_empty_list():
    assert parse_attachments([]) == []


def test_parse_geo():
    geo = {"coordinates": {"latitude": 55.75, "longitude": 37.61},
           "place": {"title": "Москва"}}
    assert parse_geo(geo) == {"type": "geo", "lat": 55.75, "lon": 37.61, "title": "Москва"}


def test_parse_geo_none():
    assert parse_geo(None) is None


def test_describe_summarises_for_notification():
    items = [{"type": "photo"}, {"type": "photo"}, {"type": "audio_message"}]
    assert describe(items) == "2 фото, голосовое"


def test_describe_empty():
    assert describe([]) == ""
