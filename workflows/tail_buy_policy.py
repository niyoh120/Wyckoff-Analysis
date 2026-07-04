"""Read-only strategy policy inputs for Tail Buy jobs."""

from __future__ import annotations

from workflows.strategy_attribution_policy import load_attribution_signal_weights
from workflows.tail_buy_utils import log_line


def load_tail_buy_policy_adjustments(
    logs_path: str | None = None,
    *,
    market: str = "cn",
) -> dict[str, float]:
    return load_attribution_signal_weights(
        market=market,
        log_fn=lambda message: log_line(message, logs_path),
    )
