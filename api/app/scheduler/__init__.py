"""The safety engine.

Four concerns, deliberately separated so each is testable on its own:

* `pacing`      — when an account may next act (log-normal gaps, working hours)
* `quota`       — how much it may do (daily caps, trailing 7-day invite ceiling)
* `locks`       — the single execution slot per account
* `engine`      — what should happen to a lead next (the sequence state machine)
* `dispatcher`  — the gate that combines all of the above
* `templating`  — message rendering, which refuses to send a half-filled message
"""

from app.scheduler import dispatcher, engine, locks, pacing, quota, templating

__all__ = ["dispatcher", "engine", "locks", "pacing", "quota", "templating"]
