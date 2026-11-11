"""Run check_stocks.py --notify every hour on the hour, 10:00-18:00,
Monday to Friday, in São Paulo time.

Usage:
    python scheduler.py          # run forever on the schedule
    python scheduler.py --now    # also run once immediately at startup
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
HOURS = range(10, 19)  # 10:00 to 18:00 (inclusive)
WEEKDAYS = range(0, 5)  # Monday=0 ... Friday=4
SCRIPT = Path(__file__).parent / "check_stocks.py"


def next_run(now: datetime) -> datetime:
    """Next datetime on the hour that falls in HOURS and WEEKDAYS."""
    candidate = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while candidate.weekday() not in WEEKDAYS or candidate.hour not in HOURS:
        candidate += timedelta(hours=1)
    return candidate


def run_check() -> None:
    started = datetime.now(TZ)
    print(f"\n===== {started:%d/%m/%Y %H:%M} — executando check_stocks =====", flush=True)
    # A separate process, so an error in one run never stops the scheduler
    result = subprocess.run([sys.executable, str(SCRIPT), "--notify"])
    if result.returncode != 0:
        print(f"⚠️  check_stocks terminou com código {result.returncode}", flush=True)


def main() -> None:
    if "--now" in sys.argv:
        run_check()

    while True:
        target = next_run(datetime.now(TZ))
        print(f"Próxima execução: {target:%a %d/%m/%Y %H:%M}", flush=True)
        # Sleep in short steps so clock changes (or container pauses) don't drift
        while (remaining := (target - datetime.now(TZ)).total_seconds()) > 0:
            time.sleep(min(remaining, 60))
        run_check()


if __name__ == "__main__":
    main()
