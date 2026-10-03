"""Message times read off LinkedIn's thread view.

The thread shows only a clock time under each day divider. When the divider
is missed the day defaults to today, which put last night's 11 PM messages
after this morning's reply in the inbox. These keep the thread in order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.linkedin.browser_driver import _settle_times
from app.linkedin.driver import MessageEvent
from app.services.inbox_service import _heal_future_times

NOW = datetime(2026, 9, 29, 6, 17, tzinfo=UTC)  # 11:47 AM in India


def test_times_misdated_to_today_move_back_to_the_day_they_were_sent() -> None:
    # Sent last night at 11:02 PM IST (17:32 UTC), but dated today.
    events = [
        MessageEvent(event_urn="a", text="Hi Vinhaar", sent_at=datetime(2026, 9, 29, 17, 32, tzinfo=UTC)),
        MessageEvent(event_urn="b", text="Any openings?", sent_at=datetime(2026, 9, 29, 17, 32, tzinfo=UTC)),
        MessageEvent(event_urn="c", text="Sure", sent_at=datetime(2026, 9, 29, 6, 10, tzinfo=UTC)),
    ]
    _settle_times(events, NOW)
    assert [e.sent_at for e in events] == [
        datetime(2026, 9, 28, 17, 32, tzinfo=UTC),
        datetime(2026, 9, 28, 17, 32, tzinfo=UTC),
        datetime(2026, 9, 29, 6, 10, tzinfo=UTC),
    ]


def test_correct_times_are_left_alone() -> None:
    times = [NOW - timedelta(days=2), NOW - timedelta(hours=3), NOW - timedelta(minutes=1), None]
    events = [MessageEvent(event_urn=str(i), sent_at=t) for i, t in enumerate(times)]
    _settle_times(events, NOW)
    assert [e.sent_at for e in events] == times


class _Row:
    def __init__(self, sent_at: datetime, created: int) -> None:
        self.sent_at = sent_at
        self.created_at = NOW + timedelta(seconds=created)


def test_stored_future_messages_are_healed_when_the_thread_is_read() -> None:
    convo: Any = type("C", (), {"last_message_at": None})()
    rows: list[Any] = [
        _Row(datetime(2026, 9, 29, 17, 32, tzinfo=UTC), 0),  # campaign message, misdated
        _Row(datetime(2026, 9, 29, 17, 32, tzinfo=UTC), 1),  # their reply, misdated
        _Row(datetime(2026, 9, 29, 6, 16, tzinfo=UTC), 2),  # our reply just now
    ]
    assert _heal_future_times(convo, rows, NOW) is True
    assert rows[0].sent_at == datetime(2026, 9, 28, 17, 32, tzinfo=UTC)
    assert rows[1].sent_at == datetime(2026, 9, 28, 17, 32, tzinfo=UTC)
    assert convo.last_message_at == rows[2].sent_at
    assert _heal_future_times(convo, rows, NOW) is False  # nothing left to fix
