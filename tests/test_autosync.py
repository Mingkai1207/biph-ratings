"""
Tests for the daily base44 auto-sync loop. We monkey-patch sync_from_base44
so the loop body runs against a fake instead of hitting real base44 + the
real DB write path. Tests use asyncio.run() to avoid the pytest-asyncio
plugin dependency — small price for one less requirement.

Verifies:
- The loop runs sync once after the initial delay
- Exceptions in the sync don't kill the loop (it sleeps + retries)
- The startup hook is a no-op when interval=0
"""
import asyncio

from backend import main, seed


def test_loop_calls_sync_after_initial_delay(monkeypatch):
    """With short delay + interval, the loop fires sync_from_base44 once
    almost immediately, proving the wiring works."""
    calls = []

    def fake_sync():
        calls.append(1)
        return {
            "reviews_added": 7, "teachers_added": 1,
            "reviews_after": 100, "teachers_after": 50,
        }

    monkeypatch.setattr(seed, "sync_from_base44", fake_sync)
    monkeypatch.setattr(main, "BASE44_SYNC_INITIAL_DELAY_SEC", 0)
    monkeypatch.setattr(main, "BASE44_SYNC_INTERVAL_SEC", 3600)

    async def runner():
        task = asyncio.create_task(main._base44_sync_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())
    assert calls == [1], "sync should run exactly once before next interval"


def test_loop_survives_sync_failure(monkeypatch):
    """A raising sync_from_base44 should be caught — the loop continues
    rather than crashing the FastAPI worker."""
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("base44 unreachable")

    monkeypatch.setattr(seed, "sync_from_base44", boom)
    monkeypatch.setattr(main, "BASE44_SYNC_INITIAL_DELAY_SEC", 0)
    monkeypatch.setattr(main, "BASE44_SYNC_INTERVAL_SEC", 3600)

    async def runner():
        task = asyncio.create_task(main._base44_sync_loop())
        await asyncio.sleep(0.05)
        # Task is still running — the failure didn't kill it.
        still_running = not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return still_running

    assert asyncio.run(runner()), "loop must not crash on sync failure"
    assert calls == [1], "sync was attempted even though it failed"


def test_startup_skips_loop_when_interval_zero(monkeypatch):
    """conftest sets BASE44_SYNC_INTERVAL_SEC=0; the startup hook should
    not schedule the loop in that case (so tests don't hit the network)."""
    scheduled = []
    monkeypatch.setattr(asyncio, "create_task", lambda coro: scheduled.append(coro) or coro)
    monkeypatch.setattr(main, "BASE44_SYNC_INTERVAL_SEC", 0)

    asyncio.run(main._start_base44_sync_loop())
    assert scheduled == [], "loop should not be scheduled when interval=0"
