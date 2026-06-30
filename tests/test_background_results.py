from __future__ import annotations


def _reset_local_db(local_db) -> None:
    if local_db._conn is not None:
        local_db._conn.close()
    local_db._conn = None


def _screen_result() -> dict:
    return {
        "ok": True,
        "selection_brief": {
            "status": "ready_for_ai_review",
            "headline": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
            "best_codes": ["300750"],
        },
        "trigger_groups": {"huge": [{"code": f"{idx:06d}", "blob": "x" * 200} for idx in range(80)]},
    }


def test_local_db_background_history_uses_tool_result_preview(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "background.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    try:
        local_db.init_db()

        local_db.save_background_task_result(
            "bg_screen",
            "screen_stocks",
            _screen_result(),
            session_id="s1",
        )
        row = local_db.load_background_task_results(limit=1)[0]

        assert row["task_id"] == "bg_screen"
        assert "本轮首选可进入 AI 研报复核: 300750 宁德时代" in row["summary"]
        assert "完整 trigger_groups 已保留在完整结果中" in row["summary"]
        assert '"trigger_groups"' not in row["summary"]
    finally:
        _reset_local_db(local_db)


def test_local_db_chat_background_history_uses_shared_preview(tmp_path, monkeypatch):
    from integrations import local_db, local_db_chat

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "background-chat.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    try:
        local_db.init_db()

        local_db_chat.save_background_task_result(
            "bg_screen_chat",
            "screen_stocks",
            _screen_result(),
            session_id="s1",
        )
        row = local_db.load_background_task_result("bg_screen_chat")

        assert row is not None
        assert "本轮首选可进入 AI 研报复核: 300750 宁德时代" in row["summary"]
        assert "完整 trigger_groups 已保留在完整结果中" in row["summary"]
        assert '"trigger_groups"' not in row["summary"]
    finally:
        _reset_local_db(local_db)
