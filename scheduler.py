from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "schedules.sqlite"

_scheduler: BackgroundScheduler | None = None
_loop: asyncio.AbstractEventLoop | None = None
_fire_callback: Callable[[int, str], Awaitable[None]] | None = None


def start(loop: asyncio.AbstractEventLoop, fire_callback: Callable[[int, str], Awaitable[None]]) -> None:
    """Start the background scheduler.

    `fire_callback(user_id, job_id)` is invoked on the bot event loop when any
    scheduled job fires.
    """
    global _scheduler, _loop, _fire_callback
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")}
    _scheduler = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
    _scheduler.start()
    _loop = loop
    _fire_callback = fire_callback
    log.info("scheduler started; %d jobs loaded", len(_scheduler.get_jobs()))


def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


def _trampoline(user_id: int, job_id: str) -> None:
    if _loop is None or _fire_callback is None:
        log.warning("scheduler fire with no loop/callback registered")
        return
    asyncio.run_coroutine_threadsafe(_fire_callback(user_id, job_id), _loop)


def _trigger_for(cadence: str, hh: int, mm: int) -> CronTrigger:
    if cadence == "daily":
        return CronTrigger(hour=hh, minute=mm)
    if cadence == "weekly":
        return CronTrigger(day_of_week="mon", hour=hh, minute=mm)
    if cadence == "every-other-day":
        return CronTrigger(day="*/2", hour=hh, minute=mm)
    if cadence.startswith("cron:"):
        return CronTrigger.from_crontab(cadence[len("cron:"):])
    raise ValueError(f"unknown cadence {cadence!r}")


def add(user_id: int, cadence: str, time_hhmm: str) -> str:
    if _scheduler is None:
        raise RuntimeError("scheduler not started")
    try:
        hh_str, mm_str = time_hhmm.split(":")
        hh, mm = int(hh_str), int(mm_str)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except ValueError as e:
        raise ValueError(f"invalid time {time_hhmm!r}; expected HH:MM in 24h") from e
    trigger = _trigger_for(cadence, hh, mm)
    job = _scheduler.add_job(
        _trampoline,
        trigger=trigger,
        args=[user_id],
        kwargs={},
        replace_existing=False,
    )
    job.modify(args=[user_id, job.id])
    return job.id


def list_for_user(user_id: int) -> list[dict[str, Any]]:
    if _scheduler is None:
        return []
    out: list[dict[str, Any]] = []
    for job in _scheduler.get_jobs():
        args = job.args or []
        if not args or args[0] != user_id:
            continue
        out.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return out


def remove(user_id: int, job_id: str) -> bool:
    if _scheduler is None:
        return False
    job = _scheduler.get_job(job_id)
    if job is None:
        return False
    args = job.args or []
    if not args or args[0] != user_id:
        return False
    _scheduler.remove_job(job_id)
    return True
