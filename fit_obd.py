"""Read a car's engine computer over a USB OBD-II adapter, read-only.

Read-only: this tool only asks the car for data. It never clears codes or writes to the car, and
a guard in the query function refuses any request outside the read-only OBD modes.

Usage:
    uv run fit_obd.py ports            # list serial ports this computer can see
    uv run fit_obd.py check            # one-shot health snapshot (key on, engine on or off)
    uv run fit_obd.py explore          # supported sensors, readiness, pending codes, freeze frame
    uv run fit_obd.py log --seconds 30 # log once a second to logs/drive_<time>.csv
    uv run fit_obd.py summary FILE     # min, mean and max of a logged drive
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parent
LOG_DIR = REPO_DIR / "logs"

# Read once for the health snapshot.
SNAPSHOT_COMMANDS = (
    "ELM_VOLTAGE",
    "CONTROL_MODULE_VOLTAGE",
    "COOLANT_TEMP",
    "INTAKE_TEMP",
    "AMBIANT_AIR_TEMP",
    "FUEL_LEVEL",
    "RPM",
    "SPEED",
    "ENGINE_LOAD",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "BAROMETRIC_PRESSURE",
    "RUN_TIME",
    "DISTANCE_W_MIL",
    "DISTANCE_SINCE_DTC_CLEAR",
)

# Read every cycle while logging a drive.
LOG_COMMANDS = (
    "RPM",
    "SPEED",
    "ENGINE_LOAD",
    "THROTTLE_POS",
    "COOLANT_TEMP",
    "INTAKE_TEMP",
    "INTAKE_PRESSURE",
    "MAF",
    "TIMING_ADVANCE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "O2_B1S2",
    "CATALYST_TEMP_B1S1",
    "FUEL_LEVEL",
    "CONTROL_MODULE_VOLTAGE",
)

# Other commands the tool sends by name (trouble codes, VIN, readiness, freeze frame).
OTHER_COMMANDS = ("STATUS", "GET_DTC", "GET_CURRENT_DTC", "FREEZE_DTC", "VIN")

# OBD service modes that only read: 01 live data, 02 freeze frame, 03 stored codes,
# 07 pending codes, 09 vehicle info. Mode 04 (clear codes) and all others are refused.
READ_ONLY_MODES = (b"01", b"02", b"03", b"07", b"09")
# Adapter-only reads that never reach the car: ATRV asks the adapter for socket voltage.
READ_ONLY_ADAPTER_COMMANDS = (b"ATRV",)

# Readiness monitors that apply to a petrol (spark-ignition) engine.
SPARK_MONITORS = (
    "MISFIRE_MONITORING",
    "FUEL_SYSTEM_MONITORING",
    "COMPONENT_MONITORING",
    "CATALYST_MONITORING",
    "HEATED_CATALYST_MONITORING",
    "EVAPORATIVE_SYSTEM_MONITORING",
    "SECONDARY_AIR_SYSTEM_MONITORING",
    "OXYGEN_SENSOR_MONITORING",
    "OXYGEN_SENSOR_HEATER_MONITORING",
    "EGR_VVT_SYSTEM_MONITORING",
)

# Thresholds for plain-English flags. Voltage rules assume a 12 V lead-acid battery.
BATTERY_LOW_ENGINE_OFF = 12.2
CHARGING_LOW = 13.2
CHARGING_HIGH = 15.0
COOLANT_HOT_C = 105.0
FUEL_TRIM_LIMIT_PCT = 10.0
FUEL_LOW_PCT = 15.0
FALLBACK_BAUDS = (115200, 38400)


class ReadOnlyViolation(RuntimeError):
    """Raised when something tries to send a request outside the read-only modes."""


@dataclass(frozen=True)
class Reading:
    """One value read from the car."""

    name: str
    value: float | None
    unit: str


@dataclass(frozen=True)
class TroubleCode:
    """One diagnostic trouble code."""

    code: str
    description: str


@dataclass(frozen=True)
class Snapshot:
    """A one-shot health snapshot."""

    taken_at: str
    vin: str | None
    check_engine_light: bool | None
    stored_codes: tuple[TroubleCode, ...]
    readings: tuple[Reading, ...]
    flags: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def is_read_only(request: bytes) -> bool:
    """True when an OBD request belongs to a read-only service mode or adapter read.

    Args:
        request: The raw request bytes, for example b"010C" or b"ATRV".

    Returns:
        True for modes 01, 02, 03, 07 and 09 and for the adapter's voltage read; False for
        everything else, including mode 04 (clear codes).
    """
    return request in READ_ONLY_ADAPTER_COMMANDS or request[:2] in READ_ONLY_MODES


def to_reading(name: str, raw: Any) -> Reading:
    """Convert a python-obd response value into a Reading.

    Args:
        name: The command name.
        raw: A pint Quantity, a plain number, or None.

    Returns:
        A Reading with a float value (or None when the car gave no answer).
    """
    if raw is None:
        return Reading(name, None, "")
    magnitude = getattr(raw, "magnitude", raw)
    unit = str(getattr(raw, "units", ""))
    try:
        return Reading(name, round(float(magnitude), 2), unit)
    except (TypeError, ValueError):
        return Reading(name, None, unit)


def decode_vin(raw: Any) -> str | None:
    """Turn the VIN response (bytes or str) into a clean string."""
    if raw is None:
        return None
    text = raw.decode("ascii", errors="ignore") if isinstance(raw, bytes | bytearray) else str(raw)
    text = "".join(ch for ch in text if ch.isalnum())
    return text or None


def health_flags(
    readings: Mapping[str, float | None],
    check_engine_light: bool | None,
    code_count: int,
) -> tuple[str, ...]:
    """Produce plain-English warnings from a set of readings.

    Args:
        readings: Command name to value (None when unsupported or unanswered).
        check_engine_light: Whether the car reports the light as on.
        code_count: Number of stored trouble codes.

    Returns:
        Warnings, empty when nothing looks off.
    """
    flags: list[str] = []
    if check_engine_light:
        flags.append("Check-engine light is commanded ON.")
    if code_count:
        flags.append(f"{code_count} stored trouble code(s).")

    rpm = readings.get("RPM")
    engine_running = rpm is not None and rpm > 300
    volts = readings.get("CONTROL_MODULE_VOLTAGE") or readings.get("ELM_VOLTAGE")
    if volts is not None:
        if engine_running and volts < CHARGING_LOW:
            flags.append(f"Charging voltage low ({volts} V with engine running): alternator?")
        elif engine_running and volts > CHARGING_HIGH:
            flags.append(f"Charging voltage high ({volts} V): voltage regulator?")
        elif not engine_running and volts < BATTERY_LOW_ENGINE_OFF:
            flags.append(f"Battery low at rest ({volts} V): weak or discharged battery.")

    coolant = readings.get("COOLANT_TEMP")
    if coolant is not None and coolant > COOLANT_HOT_C:
        flags.append(f"Coolant hot ({coolant} °C).")

    for trim_name, label in (
        ("LONG_FUEL_TRIM_1", "Long-term"),
        ("SHORT_FUEL_TRIM_1", "Short-term"),
    ):
        trim = readings.get(trim_name)
        if trim is not None and abs(trim) > FUEL_TRIM_LIMIT_PCT and engine_running:
            direction = "adding" if trim > 0 else "removing"
            flags.append(f"{label} fuel trim {trim:+.1f}%: computer is {direction} a lot of fuel.")

    fuel = readings.get("FUEL_LEVEL")
    if fuel is not None and fuel < FUEL_LOW_PCT:
        flags.append(f"Fuel low ({fuel:.0f}%).")
    return tuple(flags)


def readiness_lines(status: Any) -> list[str]:
    """Describe the emissions readiness monitors in a python-obd Status object.

    Args:
        status: The decoded STATUS response (mode 01 PID 01), or None.

    Returns:
        One line per monitor the car has, then a one-line verdict.
    """
    if status is None:
        return ["Readiness: not reported."]
    lines: list[str] = []
    available = 0
    complete = 0
    for name in SPARK_MONITORS:
        test = getattr(status, name, None)
        if test is None or not test.available:
            continue
        available += 1
        complete += bool(test.complete)
        state = "complete" if test.complete else "NOT complete"
        lines.append(f"  {name.removesuffix('_MONITORING').replace('_', ' ').lower():<24} {state}")
    if not available:
        return ["Readiness: the car reports no monitors."]
    verdict = "all complete" if complete == available else f"{available - complete} not complete"
    return [
        f"Readiness monitors: {complete} of {available} complete ({verdict})",
        *lines,
    ]


def summarize_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    """Compute min / max / mean per column of a logged drive.

    Args:
        rows: CSV rows as dicts (strings); blank cells are skipped.

    Returns:
        Column name to {"min", "max", "mean", "n"}; the time column is excluded.
    """
    columns: dict[str, list[float]] = {}
    for row in rows:
        for key, cell in row.items():
            if key == "time" or cell in ("", None):
                continue
            try:
                columns.setdefault(key, []).append(float(cell))
            except ValueError:
                continue
    return {
        key: {
            "min": min(vals),
            "max": max(vals),
            "mean": round(statistics.fmean(vals), 2),
            "n": len(vals),
        }
        for key, vals in columns.items()
    }


def mask_vin(vin: str | None) -> str:
    """Hide all but the last four characters of a VIN, for on-camera output."""
    if not vin:
        return "not reported"
    return "*" * max(len(vin) - 4, 0) + vin[-4:]


def format_snapshot(snap: Snapshot, show_vin: bool = False) -> str:
    """Render a snapshot as text for the terminal.

    Args:
        snap: The snapshot to render.
        show_vin: Print the full VIN. Off by default because the output may be filmed or shared.
    """
    vin = (snap.vin or "not reported") if show_vin else mask_vin(snap.vin)
    lines = [f"Car snapshot  {snap.taken_at}", f"VIN: {vin}"]
    light = {True: "ON", False: "off", None: "unknown"}[snap.check_engine_light]
    lines.append(f"Check-engine light: {light}")
    if snap.stored_codes:
        lines.append("Trouble codes:")
        lines += [f"  {c.code}  {c.description or '(no description)'}" for c in snap.stored_codes]
    else:
        lines.append("Trouble codes: none")
    lines.append("")
    for r in snap.readings:
        value = "not supported / no answer" if r.value is None else f"{r.value} {r.unit}".strip()
        lines.append(f"  {r.name:<26} {value}")
    lines.append("")
    lines += [f"FLAG: {f}" for f in snap.flags] or ["No flags."]
    return "\n".join(lines)


def format_codes(title: str, codes: Iterable[tuple[str, str]] | None) -> list[str]:
    """Render a list of (code, description) pairs under a title."""
    codes = list(codes or [])
    if not codes:
        return [f"{title}: none"]
    return [
        f"{title}:",
        *(f"  {code}  {desc or '(no description)'}" for code, desc in codes),
    ]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _shown(path: Path) -> str:
    """A saved file's path relative to the repo, so no home folder is printed."""
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return path.name


def _connect(port: str | None, baud: int | None = None) -> Any:
    """Open the adapter and confirm the car is answering, or exit with a clear message.

    Tries the library's automatic speed detection first, then common fixed speeds,
    because auto-detection fails on some adapters.
    """
    import obd

    obd.logger.setLevel("CRITICAL")
    conn = None
    for candidate in (baud,) if baud else (None, *FALLBACK_BAUDS):
        conn = obd.OBD(portstr=port, baudrate=candidate, fast=False, timeout=1.0)
        if conn.status() != obd.OBDStatus.NOT_CONNECTED:
            break
        conn.close()
    status = conn.status()
    if status == obd.OBDStatus.NOT_CONNECTED:
        ports = obd.scan_serial()
        print(
            "ERROR: no OBD adapter found. Is the cable plugged into this computer?\n"
            f"Serial ports seen: {ports or 'none'}\n"
            "If the cable is plugged in and no port shows, this computer lacks a driver for it\n"
            "(on Windows: Device Manager, error code 28; see the README).",
            file=sys.stderr,
        )
        sys.exit(1)
    if status != obd.OBDStatus.CAR_CONNECTED:
        print(
            f"ERROR: adapter found on {conn.port_name()} but the car is not answering "
            f"(status: {status}). Turn the key to ON (II) and try again.",
            file=sys.stderr,
        )
        conn.close()
        sys.exit(1)
    return conn


def _query(conn: Any, name: str) -> Any:
    """Query one command by name; None when unsupported or unanswered.

    Raises:
        ReadOnlyViolation: the command is outside the read-only modes. Nothing is sent.
    """
    import obd

    cmd = getattr(obd.commands, name)
    if not is_read_only(cmd.command):
        raise ReadOnlyViolation(f"refused {name} ({cmd.command!r}): not a read-only request")
    if not conn.supports(cmd):
        return None
    response = conn.query(cmd)
    return None if response.is_null() else response.value


def take_snapshot(conn: Any) -> Snapshot:
    """Read the health snapshot from the car."""
    status = _query(conn, "STATUS")
    codes = tuple(TroubleCode(code, desc) for code, desc in (_query(conn, "GET_DTC") or []))
    readings = tuple(to_reading(name, _query(conn, name)) for name in SNAPSHOT_COMMANDS)
    light = None if status is None else bool(status.MIL)
    flags = health_flags({r.name: r.value for r in readings}, light, len(codes))
    return Snapshot(
        taken_at=datetime.now().isoformat(timespec="seconds"),
        vin=decode_vin(_query(conn, "VIN")),
        check_engine_light=light,
        stored_codes=codes,
        readings=readings,
        flags=flags,
    )


def explore_lines(conn: Any) -> list[str]:
    """Read what the car offers: protocol, live sensors, readiness, pending codes, freeze frame.

    Never asks for the VIN.
    """
    protocol = conn.protocol_name()
    live = sorted(
        (c for c in conn.supported_commands if c.mode == 1 and not c.name.startswith("PIDS_")),
        key=lambda c: c.command,
    )
    lines = [f"Protocol: {protocol}", f"Live sensors this car supports ({len(live)}):"]
    lines += [f"  {c.command.decode()}  {c.name:<28} {c.desc}" for c in live]
    lines.append("")
    lines += readiness_lines(_query(conn, "STATUS"))
    lines.append("")
    lines += format_codes("Pending codes", _query(conn, "GET_CURRENT_DTC"))
    freeze = _query(conn, "FREEZE_DTC")
    if not freeze or not freeze[0] or freeze[0] == "P0000":
        lines.append("Freeze frame: none stored")
    else:
        lines.append(f"Freeze frame: set by {freeze[0]} {freeze[1] or ''}".rstrip())
        frame = sorted(
            (c for c in conn.supported_commands if c.mode == 2 and not c.name.startswith("PIDS_")),
            key=lambda c: c.command,
        )
        for c in frame:
            if c.name == "FREEZE_DTC":
                continue
            r = to_reading(c.name, _query(conn, c.name))
            value = "no answer" if r.value is None else f"{r.value} {r.unit}".strip()
            lines.append(f"  {c.name:<28} {value}")
    return lines


def cmd_ports(_: argparse.Namespace) -> None:
    """List serial ports."""
    import obd

    ports = obd.scan_serial()
    print("\n".join(ports) if ports else "No serial ports found.")


def cmd_check(args: argparse.Namespace) -> None:
    """Print a snapshot and save it as JSON (the JSON holds the full VIN)."""
    conn = _connect(args.port, args.baud)
    try:
        snap = take_snapshot(conn)
    finally:
        conn.close()
    print(format_snapshot(snap, show_vin=args.show_vin))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"check_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(asdict(snap), indent=2))
    print(f"\nSaved {_shown(out)} (it holds the full VIN: keep it private)")


def cmd_explore(args: argparse.Namespace) -> None:
    """Print what the car supports, readiness, pending codes and the freeze frame."""
    conn = _connect(args.port, args.baud)
    try:
        lines = explore_lines(conn)
    finally:
        conn.close()
    print("\n".join(lines))


def cmd_log(args: argparse.Namespace) -> None:
    """Log supported commands to CSV until Ctrl-C (or for --seconds)."""
    import obd

    conn = _connect(args.port, args.baud)
    names = [n for n in LOG_COMMANDS if conn.supports(getattr(obd.commands, n))]
    if not names:
        print(
            "ERROR: the car reports none of the logging commands as supported.",
            file=sys.stderr,
        )
        conn.close()
        sys.exit(1)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"drive_{datetime.now():%Y%m%d_%H%M%S}.csv"
    until = "Ctrl-C to stop." if not args.seconds else f"Stopping after {args.seconds:g} s."
    print(f"Logging {len(names)} values every {args.interval}s to {_shown(out)}\n{until}")
    rows = 0
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        with out.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["time", *names])
            while deadline is None or time.monotonic() < deadline:
                started = time.monotonic()
                values = [to_reading(n, _query(conn, n)).value for n in names]
                writer.writerow(
                    [datetime.now().isoformat(timespec="seconds")]
                    + ["" if v is None else v for v in values]
                )
                fh.flush()
                rows += 1
                time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
    print(f"\nStopped. {rows} rows in {_shown(out)}")


def cmd_summary(args: argparse.Namespace) -> None:
    """Print min / max / mean for a logged drive."""
    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: no such log file: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(newline="") as fh:
        stats = summarize_rows(list(csv.DictReader(fh)))
    if not stats:
        print("ERROR: log has no numeric data.", file=sys.stderr)
        sys.exit(1)
    print(f"{'value':<26}{'min':>10}{'mean':>10}{'max':>10}{'n':>7}")
    for name, s in stats.items():
        print(f"{name:<26}{s['min']:>10}{s['mean']:>10}{s['max']:>10}{s['n']:>7}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--port", help="serial port, e.g. COM3 or /dev/ttyUSB0 (default: auto)")
    parser.add_argument("--baud", type=int, help="serial speed (default: auto-detect)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)
    check = sub.add_parser("check", help="one-shot health snapshot")
    check.add_argument(
        "--show-vin", action="store_true", help="print the full VIN (masked by default)"
    )
    check.set_defaults(func=cmd_check)
    sub.add_parser(
        "explore", help="supported sensors, readiness, pending codes, freeze frame"
    ).set_defaults(func=cmd_explore)
    log = sub.add_parser("log", help="log a drive to CSV")
    log.add_argument("--interval", type=float, default=1.0, help="seconds between rows")
    log.add_argument("--seconds", type=float, help="stop after this many seconds")
    log.set_defaults(func=cmd_log)
    summary = sub.add_parser("summary", help="summarize a logged drive")
    summary.add_argument("file")
    summary.set_defaults(func=cmd_summary)
    args = parser.parse_args()
    try:
        args.func(args)
    except ReadOnlyViolation as exc:
        print(f"ERROR: {exc}. Nothing was sent to the car.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
