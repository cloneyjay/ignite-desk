"""Agent worker process. Runs autonomously on schedule."""

from __future__ import annotations

import logging
import signal
import sys
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.ignite.agent.config import AgentConfig
from backend.ignite.agent.engine import AgentEngine
from backend.ignite.agent.position_manager import PositionManager
from backend.ignite.config import load_settings
from backend.ignite.services.runtime import Runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("agent.worker")


class AgentWorker:
    """Agent worker process with scheduled cycles."""

    def __init__(self, runtime: Runtime, config: AgentConfig) -> None:
        self.runtime = runtime
        self.config = config
        self.engine = AgentEngine(runtime, config)
        self.position_manager = PositionManager(runtime, config)
        self.scheduler = BackgroundScheduler(timezone=timezone.utc)
        self._shutdown = threading.Event()
        self._cycle_lock = threading.Lock()
        self._cycle_running = False

    def start(self) -> None:
        """Start the worker and scheduler."""
        log.info("Starting agent worker")
        log.info(
            "Config: enabled=%s, symbols=%s, timeframe=%s, interval=%dmin, session_open=%d:00",
            self.config.enabled,
            self.config.symbols or "all",
            self.config.timeframe,
            self.config.cycle_interval_min,
            self.config.session_open_hour,
        )

        # Schedule jobs
        self.scheduler.add_job(
            self._run_cycle_job,
            CronTrigger(hour=self.config.session_open_hour, minute=0, timezone="UTC"),
            id="session_open",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        self.scheduler.add_job(
            self._run_cycle_job,
            IntervalTrigger(minutes=self.config.cycle_interval_min, timezone="UTC"),
            id="interval",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        self.scheduler.add_job(
            self._manage_positions_job,
            IntervalTrigger(seconds=self.config.position_check_interval_sec, timezone="UTC"),
            id="position_manager",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

        # Signal handling
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self.scheduler.start()
        log.info("Agent worker started successfully")

    def shutdown(self) -> None:
        """Graceful shutdown."""
        log.info("Shutting down agent worker")
        self._shutdown.set()
        self.scheduler.shutdown(wait=True)
        log.info("Agent worker stopped")

    def _signal_handler(self, signum: int, frame: object) -> None:
        log.info("Received signal %s, initiating shutdown", signum)
        self.shutdown()
        sys.exit(0)

    def _run_cycle_job(self) -> None:
        """Wrapper for cycle execution with single-flight lock."""
        if not self._cycle_lock.acquire(blocking=False):
            log.warning("Cycle already running, skipping this trigger")
            return
        try:
            self._cycle_running = True
            if not self._shutdown.is_set():
                self.engine.run_cycle()
        except Exception as exc:  # noqa: BLE001
            log.exception("Cycle failed: %s", exc)
        finally:
            self._cycle_running = False
            self._cycle_lock.release()

    def _manage_positions_job(self) -> None:
        """Wrapper for position management with lock."""
        if not self._cycle_lock.acquire(blocking=False):
            return
        try:
            if not self._shutdown.is_set():
                self.position_manager.manage_all()
        except Exception as exc:  # noqa: BLE001
            log.exception("Position management failed: %s", exc)
        finally:
            self._cycle_lock.release()

    def _trigger_cycle(self) -> None:
        """Manually trigger a cycle (for testing)."""
        self._run_cycle_job()


def main() -> None:
    """Main entry point for the agent worker process."""
    settings = load_settings()
    config = AgentConfig.from_env()

    runtime = Runtime(settings)
    worker = AgentWorker(runtime, config)

    try:
        worker.start()
        # Keep process alive
        while not worker._shutdown.is_set():
            pass
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
    except Exception as exc:  # noqa: BLE001
        log.exception("Worker failed: %s", exc)
        sys.exit(1)
    finally:
        worker.shutdown()


if __name__ == "__main__":
    main()