from __future__ import annotations

import argparse
import logging
import signal
from threading import Event

from booruradar.core.config import get_settings
from booruradar.core.logging import configure_logging


logger = logging.getLogger(__name__)


class Worker:
    """Minimal worker shell; collection scheduling arrives after Milestone 0."""

    def __init__(self, poll_interval_seconds: float) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.stop_event = Event()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()

    def run_once(self) -> None:
        logger.info("worker_cycle_complete", extra={"registered_collectors": 0})

    def run_forever(self) -> None:
        logger.info("worker_started")
        while not self.stop_event.is_set():
            self.run_once()
            self.stop_event.wait(self.poll_interval_seconds)
        logger.info("worker_stopped")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BooruRadar metadata worker.")
    parser.add_argument("--once", action="store_true", help="Run one empty scheduling cycle and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = Worker(settings.worker_poll_interval_seconds)
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    worker.run_once() if args.once else worker.run_forever()


if __name__ == "__main__":
    main()
