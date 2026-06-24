"""Local SQLite portfolio persistence helpers."""

from __future__ import annotations

from integrations.local_db import get_db

# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


def save_portfolio(portfolio_id: str, free_cash: float, positions: list[dict]) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO portfolio
               (portfolio_id, free_cash, synced_at) VALUES (?, ?, datetime('now'))""",
            (portfolio_id, free_cash),
        )
        conn.execute(
            "DELETE FROM portfolio_position WHERE portfolio_id=?",
            (portfolio_id,),
        )
        if positions:
            conn.executemany(
                """INSERT INTO portfolio_position
                   (portfolio_id, code, name, shares, cost_price, buy_dt, stop_loss, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                [
                    (
                        portfolio_id,
                        str(p.get("code", "")).strip(),
                        str(p.get("name", "")).strip(),
                        int(p.get("shares", 0) or 0),
                        float(p.get("cost_price", 0) or 0),
                        str(p.get("buy_dt", "") or ""),
                        float(p["stop_loss"]) if p.get("stop_loss") is not None else None,
                    )
                    for p in positions
                ],
            )


def load_portfolio(portfolio_id: str) -> dict | None:
    conn = get_db()
    cur = conn.execute("SELECT * FROM portfolio WHERE portfolio_id=?", (portfolio_id,))
    row = cur.fetchone()
    if not row:
        return None
    pos_cur = conn.execute("SELECT * FROM portfolio_position WHERE portfolio_id=?", (portfolio_id,))
    return {
        "portfolio_id": row["portfolio_id"],
        "free_cash": row["free_cash"],
        "positions": [dict(p) for p in pos_cur.fetchall()],
    }


def _ensure_local_portfolio(portfolio_id: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO portfolio (portfolio_id, free_cash) VALUES (?, 0)",
        (portfolio_id,),
    )
    conn.commit()


def upsert_local_position(
    portfolio_id: str,
    code: str,
    name: str,
    shares: int,
    cost_price: float,
    buy_dt: str = "",
) -> None:
    _ensure_local_portfolio(portfolio_id)
    conn = get_db()
    with conn:
        if buy_dt:
            conn.execute(
                """INSERT INTO portfolio_position
                   (portfolio_id, code, name, shares, cost_price, buy_dt, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(portfolio_id, code) DO UPDATE SET
                   name=excluded.name, shares=excluded.shares,
                   cost_price=excluded.cost_price, buy_dt=excluded.buy_dt,
                   synced_at=excluded.synced_at""",
                (portfolio_id, code, name, shares, cost_price, buy_dt),
            )
        else:
            conn.execute(
                """INSERT INTO portfolio_position
                   (portfolio_id, code, name, shares, cost_price, synced_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(portfolio_id, code) DO UPDATE SET
                   name=excluded.name, shares=excluded.shares,
                   cost_price=excluded.cost_price,
                   synced_at=excluded.synced_at""",
                (portfolio_id, code, name, shares, cost_price),
            )


def delete_local_position(portfolio_id: str, code: str) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            "DELETE FROM portfolio_position WHERE portfolio_id=? AND code=?",
            (portfolio_id, code),
        )


def update_local_free_cash(portfolio_id: str, free_cash: float) -> None:
    _ensure_local_portfolio(portfolio_id)
    conn = get_db()
    with conn:
        conn.execute(
            "UPDATE portfolio SET free_cash=?, synced_at=datetime('now') WHERE portfolio_id=?",
            (free_cash, portfolio_id),
        )
