from workflows.backtest_cli import build_backtest_parser
from workflows.backtest_defaults import DEFAULT_USE_CURRENT_META


def test_formal_backtest_disables_current_metadata_by_default() -> None:
    assert DEFAULT_USE_CURRENT_META is False
    assert build_backtest_parser().parse_args([]).use_current_meta is False
