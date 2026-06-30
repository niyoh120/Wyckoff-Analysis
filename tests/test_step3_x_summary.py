from __future__ import annotations

import pandas as pd

from workflows.step3_models import Step3RunOptions
from workflows.step3_reporting import send_empty_step3_report
from workflows.step3_runtime_config import Step3RuntimeConfig


def _options() -> Step3RunOptions:
    return Step3RunOptions(
        webhook_url="https://example.invalid/webhook",
        api_key="",
        model="",
        notify=True,
        provider="gemini",
        llm_base_url="",
        wecom_webhook="",
        dingtalk_webhook="",
        runtime_config=Step3RuntimeConfig(send_compliance_brief=False, send_x_summary=True),
    )


def test_empty_step3_report_sends_x_summary_after_main_report(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        reporting, "notify_step3_channels", lambda _options, title, content: sent.append((title, content)) or True
    )
    monkeypatch.setattr(reporting, "compliance_llm_config_from_env", lambda: None)

    ok, reason, _report = send_empty_step3_report(
        options=_options(),
        items=[{"code": "300024", "name": "机器人"}],
        benchmark_context={"regime": "PANIC_REPAIR", "close": 4094.4},
        selected_df=pd.DataFrame([{"code": "300024", "name": "机器人", "priority_score": 88}]),
        rag_veto_preview="",
        rag_veto_lines=[],
    )

    assert (ok, reason) == (True, "ok")
    assert [title.split()[0] for title, _ in sent] == ["📄", "🧵"]
    assert "X直白版总结" in sent[-1][1]
    assert "300024 机器人" in sent[-1][1]


def test_x_summary_can_be_disabled(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[str] = []
    options = Step3RunOptions(
        **{
            **_options().__dict__,
            "runtime_config": Step3RuntimeConfig(send_compliance_brief=False, send_x_summary=False),
        }
    )
    monkeypatch.setattr(
        reporting, "notify_step3_channels", lambda _options, title, _content: sent.append(title) or True
    )

    ok, reason, _report = send_empty_step3_report(
        options=options,
        items=[],
        benchmark_context={},
        selected_df=pd.DataFrame(),
        rag_veto_preview="",
        rag_veto_lines=[],
    )

    assert (ok, reason) == (True, "ok")
    assert len(sent) == 1
