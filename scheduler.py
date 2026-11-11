"""Run check_stocks.py --notify every hour on the hour, 10:00-18:00,
Monday to Friday, in São Paulo time.

Also serves a small status page on PORT (default 8080), used as a health
check by Fly.io.

Usage:
    python scheduler.py          # run forever on the schedule
    python scheduler.py --now    # also run once immediately at startup
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
HOURS = range(10, 19)  # 10:00 to 18:00 (inclusive)
WEEKDAYS = range(0, 5)  # Monday=0 ... Friday=4
SCRIPT = Path(__file__).parent / "check_stocks.py"
PORT = int(os.getenv("PORT", "8080"))

status = {"started": None, "last_run": None, "last_exit_code": None, "next_run": None}


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"status": "ok", **status}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # keep health checks out of the logs


def start_status_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Status em http://0.0.0.0:{PORT}/", flush=True)


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
    status["last_run"] = started.isoformat(timespec="minutes")
    status["last_exit_code"] = result.returncode
    if result.returncode != 0:
        print(f"⚠️  check_stocks terminou com código {result.returncode}", flush=True)


def main() -> None:
    status["started"] = datetime.now(TZ).isoformat(timespec="minutes")
    start_status_server()

    if "--now" in sys.argv:
        run_check()

    while True:
        target = next_run(datetime.now(TZ))
        status["next_run"] = target.isoformat(timespec="minutes")
        print(f"Próxima execução: {target:%a %d/%m/%Y %H:%M}", flush=True)
        # Sleep in short steps so clock changes (or container pauses) don't drift
        while (remaining := (target - datetime.now(TZ)).total_seconds()) > 0:
            time.sleep(min(remaining, 60))
        run_check()


if __name__ == "__main__":
    main()
