from __future__ import annotations

import pandas as pd

from workflows.step3_models import Step3LlmResult, Step3RunOptions, Step3TrackInputs
from workflows.step3_runtime_config import Step3RuntimeConfig


def _options(*, send_x_summary: bool = True) -> Step3RunOptions:
    return Step3RunOptions(
        webhook_url="https://example.test/hook",
        api_key="key",
        model="model",
        notify=True,
        provider="gemini",
        llm_base_url="",
        wecom_webhook="",
        dingtalk_webhook="",
        runtime_config=Step3RuntimeConfig(
            send_compliance_brief=False,
            send_x_summary=send_x_summary,
            require_confirmed_operation=False,
        ),
    )


def _track_inputs() -> Step3TrackInputs:
    return Step3TrackInputs(
        payloads_by_track={"launchpad": ["payload"]},
        df_by_track={"launchpad": pd.DataFrame()},
        selected_codes_by_track={"launchpad": ["000001"]},
        items_by_track={"launchpad": [{"code": "000001", "name": "高分股"}]},
    )


def test_step3_final_report_sends_x_summary_after_main_report(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        reporting, "notify_step3_channels", lambda _opts, title, content: sent.append((title, content)) or True
    )
    monkeypatch.setattr(reporting, "_build_x_summary", lambda *_args: "## 🧵 X直白版总结\n短评")

    ok, reason, report = reporting.send_step3_final_report(
        options=_options(send_x_summary=True),
        active_tracks=["launchpad"],
        track_inputs=_track_inputs(),
        selected_df=pd.DataFrame([{"code": "000001", "name": "高分股"}]),
        selected_codes=["000001"],
        benchmark_context={"regime": "RISK_ON"},
        rag_veto_preview="",
        rag_veto_lines=[],
        failed=[],
        llm_result=Step3LlmResult(
            ok=True,
            status="ok",
            report="## 🏹 处于起跳板\n- 000001 高分股",
            used_models={"launchpad": "model"},
        ),
        report_progress=lambda *_args: None,
    )

    assert (ok, reason) == (True, "ok")
    assert "处于起跳板" in report
    assert len(sent) == 2
    assert "批量研报" in sent[0][0]
    assert "X直白版总结" in sent[1][0]
    assert sent[1][1].startswith("## 🧵 X直白版总结")


def test_step3_final_report_respects_x_summary_switch(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        reporting, "notify_step3_channels", lambda _opts, title, content: sent.append((title, content)) or True
    )
    monkeypatch.setattr(reporting, "_build_x_summary", lambda *_args: (_ for _ in ()).throw(AssertionError))

    ok, reason, _report = reporting.send_step3_final_report(
        options=_options(send_x_summary=False),
        active_tracks=["launchpad"],
        track_inputs=_track_inputs(),
        selected_df=pd.DataFrame([{"code": "000001", "name": "高分股"}]),
        selected_codes=["000001"],
        benchmark_context={"regime": "RISK_ON"},
        rag_veto_preview="",
        rag_veto_lines=[],
        failed=[],
        llm_result=Step3LlmResult(
            ok=True,
            status="ok",
            report="## 🏹 处于起跳板\n- 000001 高分股",
            used_models={"launchpad": "model"},
        ),
        report_progress=lambda *_args: None,
    )

    assert (ok, reason) == (True, "ok")
    assert len(sent) == 1
    assert "批量研报" in sent[0][0]


def test_step3_final_report_ignores_x_summary_delivery_failure(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[str] = []

    def fake_notify(_opts, title, _content):
        sent.append(title)
        return "X直白版总结" not in title

    monkeypatch.setattr(reporting, "notify_step3_channels", fake_notify)
    monkeypatch.setattr(reporting, "_build_x_summary", lambda *_args: "## 🧵 X直白版总结\n短评")

    ok, reason, _report = reporting.send_step3_final_report(
        options=_options(send_x_summary=True),
        active_tracks=["launchpad"],
        track_inputs=_track_inputs(),
        selected_df=pd.DataFrame([{"code": "000001", "name": "高分股"}]),
        selected_codes=["000001"],
        benchmark_context={"regime": "RISK_ON"},
        rag_veto_preview="",
        rag_veto_lines=[],
        failed=[],
        llm_result=Step3LlmResult(
            ok=True,
            status="ok",
            report="## 🏹 处于起跳板\n- 000001 高分股",
            used_models={"launchpad": "model"},
        ),
        report_progress=lambda *_args: None,
    )

    assert (ok, reason) == (True, "ok")
    assert any("X直白版总结" in title for title in sent)


def test_step3_final_report_ignores_x_summary_generation_failure(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[str] = []
    monkeypatch.setattr(reporting, "notify_step3_channels", lambda _opts, title, _content: sent.append(title) or True)
    monkeypatch.setattr(reporting, "_build_x_summary", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    ok, reason, _report = reporting.send_step3_final_report(
        options=_options(send_x_summary=True),
        active_tracks=["launchpad"],
        track_inputs=_track_inputs(),
        selected_df=pd.DataFrame([{"code": "000001", "name": "高分股"}]),
        selected_codes=["000001"],
        benchmark_context={"regime": "RISK_ON"},
        rag_veto_preview="",
        rag_veto_lines=[],
        failed=[],
        llm_result=Step3LlmResult(
            ok=True,
            status="ok",
            report="## 🏹 处于起跳板\n- 000001 高分股",
            used_models={"launchpad": "model"},
        ),
        report_progress=lambda *_args: None,
    )

    assert (ok, reason) == (True, "ok")
    assert len(sent) == 1
    assert "批量研报" in sent[0]


def test_step3_final_report_ignores_x_summary_build_failure(monkeypatch) -> None:
    import workflows.step3_reporting as reporting

    sent: list[str] = []
    monkeypatch.setattr(reporting, "notify_step3_channels", lambda _opts, title, _content: sent.append(title) or True)
    monkeypatch.setattr(reporting, "_build_x_summary", lambda *_args: (_ for _ in ()).throw(RuntimeError("down")))

    ok, reason, _report = reporting.send_step3_final_report(
        options=_options(send_x_summary=True),
        active_tracks=["launchpad"],
        track_inputs=_track_inputs(),
        selected_df=pd.DataFrame([{"code": "000001", "name": "高分股"}]),
        selected_codes=["000001"],
        benchmark_context={"regime": "RISK_ON"},
        rag_veto_preview="",
        rag_veto_lines=[],
        failed=[],
        llm_result=Step3LlmResult(
            ok=True,
            status="ok",
            report="## 🏹 处于起跳板\n- 000001 高分股",
            used_models={"launchpad": "model"},
        ),
        report_progress=lambda *_args: None,
    )

    assert (ok, reason) == (True, "ok")
    assert len(sent) == 1
    assert "批量研报" in sent[0]
