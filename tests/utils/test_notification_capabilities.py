from utils.notification_capabilities import notification_capabilities, split_utf8_text


def test_notification_capabilities_describe_existing_webhook_channels():
    assert notification_capabilities("feishu").supports_cards
    assert notification_capabilities("wecom").max_bytes == 4000
    assert notification_capabilities("dingtalk").markdown


def test_split_utf8_text_preserves_multibyte_content_and_limit():
    chunks = split_utf8_text("第一段\n第二段\n第三段", max_bytes=10)

    assert "".join(chunks).replace("\n", "") == "第一段第二段第三段"
    assert all(len(chunk.encode("utf-8")) <= 10 for chunk in chunks)
