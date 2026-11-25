"""Run fit_obd.py against a simulated car, no cable or car needed.

Starts the ELM327-emulator project's "car" scenario on a local TCP port inside this process,
runs one fit_obd command against it, then stops the emulator. Files are saved in
logs/simulated/ so they are never mixed up with readings from a real car.

Usage:
    uv run --with ELM327-emulator==4.0.0 simulate.py check
    uv run --with ELM327-emulator==4.0.0 simulate.py explore
    uv run --with ELM327-emulator==4.0.0 simulate.py log --seconds 3
"""

from __future__ import annotations

import logging
import socket
import sys
import time

import fit_obd

SIM_PORT = 35000
STARTUP_TIMEOUT_S = 15.0


def _wait_for_port(port: int, timeout_s: float) -> bool:
    """Return True once something accepts connections on 127.0.0.1:port."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> None:
    """Start the emulator, run the fit_obd command given on the command line, stop it."""
    try:
        from elm import Elm
    except ImportError:
        print(
            "ERROR: the emulator is missing. Run this with:\n"
            "  uv run --with ELM327-emulator==4.0.0 simulate.py check",
            file=sys.stderr,
        )
        sys.exit(1)
    if _wait_for_port(SIM_PORT, 0.1):
        print(f"ERROR: port {SIM_PORT} is already in use; stop whatever uses it.", file=sys.stderr)
        sys.exit(1)
    logging.disable(logging.WARNING)  # the emulator and pint are chatty; errors still show
    fit_obd.LOG_DIR = fit_obd.LOG_DIR / "simulated"
    with Elm(batch_mode=True, net_port=SIM_PORT) as emulator:
        emulator.set_sorted_obd_msg(scenario="car")
        if not _wait_for_port(SIM_PORT, STARTUP_TIMEOUT_S):
            print("ERROR: the simulated car did not start.", file=sys.stderr)
            sys.exit(1)
        print("Simulated car (ELM327-emulator, scenario 'car'): no real car involved.\n")
        port = f"socket://127.0.0.1:{SIM_PORT}"
        sys.argv = [sys.argv[0], "--port", port, "--baud", "38400", *sys.argv[1:]]
        fit_obd.main()


if __name__ == "__main__":
    main()
