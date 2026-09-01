from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from goldsignal.models.candle import Timeframe
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.notifications.telegram import TelegramError, send_signal_alert

TS = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)


def _buy_signal():
    return StrategySignal(
        signal_id="abc",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.BUY,
        signal_timestamp=TS,
        entry_price=2450.20,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=2440.00,
        targets=[ProfitTarget(label="TP1", price=2470.60, r_multiple=2.0)],
        setup_expiration=TS + timedelta(minutes=15),
        invalidation_conditions=["x"],
        estimated_spread=0.3,
        estimated_slippage=0.2,
    )


def _no_trade_signal():
    return StrategySignal(
        signal_id="abc",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.NO_TRADE,
        signal_timestamp=TS,
        entry_price=None,
        entry_order_type=None,
        stop_loss=None,
        targets=[],
        setup_expiration=None,
        invalidation_conditions=[],
        estimated_spread=None,
        estimated_slippage=None,
        reason="insufficient_candle_history",
    )


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True}
    return resp


def test_send_buy_signal_posts_to_telegram():
    with patch(
        "goldsignal.notifications.telegram.requests.post", return_value=_ok_response()
    ) as mock_post:
        sent = send_signal_alert(_buy_signal(), bot_token="TOKEN123", chat_id="999")
    assert sent is True
    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert url == "https://api.telegram.org/botTOKEN123/sendMessage"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "999"
    assert "BUY" in payload["text"]


def test_no_trade_not_sent_without_debug_mode():
    with patch("goldsignal.notifications.telegram.requests.post") as mock_post:
        sent = send_signal_alert(_no_trade_signal(), bot_token="TOKEN123", chat_id="999")
    assert sent is False
    mock_post.assert_not_called()


def test_no_trade_sent_with_debug_mode():
    with patch(
        "goldsignal.notifications.telegram.requests.post", return_value=_ok_response()
    ) as mock_post:
        sent = send_signal_alert(
            _no_trade_signal(), bot_token="TOKEN123", chat_id="999", debug_mode=True
        )
    assert sent is True
    mock_post.assert_called_once()


def test_raises_on_http_error():
    resp = MagicMock()
    resp.status_code = 401
    with patch("goldsignal.notifications.telegram.requests.post", return_value=resp):
        with pytest.raises(TelegramError):
            send_signal_alert(_buy_signal(), bot_token="TOKEN123", chat_id="999")


def test_raises_when_telegram_rejects_message():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": False, "description": "chat not found"}
    with patch("goldsignal.notifications.telegram.requests.post", return_value=resp):
        with pytest.raises(TelegramError):
            send_signal_alert(_buy_signal(), bot_token="TOKEN123", chat_id="999")


def test_requires_token_and_chat_id():
    with pytest.raises(ValueError):
        send_signal_alert(_buy_signal(), bot_token="", chat_id="999")
    with pytest.raises(ValueError):
        send_signal_alert(_buy_signal(), bot_token="TOKEN123", chat_id="")
