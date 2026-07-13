from utils import markdown_webhooks


class _Response:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {"errcode": 0}


def test_dingtalk_webhook_splits_oversized_utf8_message(monkeypatch):
    payloads = []
    monkeypatch.setattr(markdown_webhooks, "append_tickflow_limit_hint", lambda value: value)
    monkeypatch.setattr(
        markdown_webhooks.requests,
        "post",
        lambda *_args, **kwargs: payloads.append(kwargs["json"]) or _Response(),
    )

    assert markdown_webhooks.send_dingtalk_notification("https://example.com/hook", "日报", "中" * 1_500)
    assert len(payloads) >= 2
    assert all(len(item["markdown"]["text"].encode("utf-8")) <= 4_000 for item in payloads)
