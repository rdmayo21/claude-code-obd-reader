"""Tests that need no car and no adapter. All values here are synthetic."""

from __future__ import annotations

from typing import Any

import obd
import pytest
from obd.OBDResponse import Status, StatusTest

import fit_obd
from fit_obd import (
    Reading,
    Snapshot,
    decode_vin,
    format_snapshot,
    health_flags,
    is_read_only,
    mask_vin,
    readiness_lines,
    summarize_rows,
    to_reading,
)

# Synthetic VIN for tests. Deliberately not a valid VIN (it contains I and O).
FAKE_VIN = "FAKEVIN0TEST01234"


class _FakeQuantity:
    def __init__(self, magnitude: float, units: str) -> None:
        self.magnitude = magnitude
        self.units = units


class _FakeResponse:
    def __init__(self, value: Any) -> None:
        self.value = value

    def is_null(self) -> bool:
        return self.value is None


class _FakeCar:
    """Stands in for obd.OBD: answers from a dict and records every command queried."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.sent: list[bytes] = []
        self.supported_commands = {getattr(obd.commands, n) for n in answers}

    def supports(self, cmd: Any) -> bool:
        return cmd in self.supported_commands

    def query(self, cmd: Any) -> _FakeResponse:
        self.sent.append(cmd.command)
        return _FakeResponse(self.answers.get(cmd.name))

    def protocol_name(self) -> str:
        return "ISO 15765-4 (CAN 11/500)"


def _status(mil: bool = False, incomplete: tuple[str, ...] = ()) -> Status:
    status = Status()
    status.MIL = mil
    for name in ("MISFIRE_MONITORING", "CATALYST_MONITORING", "EGR_VVT_SYSTEM_MONITORING"):
        setattr(status, name, StatusTest(name, True, name not in incomplete))
    return status


def test_to_reading_handles_quantity_number_and_none() -> None:
    assert to_reading("RPM", _FakeQuantity(812.456, "rpm")) == Reading("RPM", 812.46, "rpm")
    assert to_reading("X", 3) == Reading("X", 3.0, "")
    assert to_reading("X", None) == Reading("X", None, "")
    assert to_reading("X", "junk").value is None


def test_decode_vin_strips_padding() -> None:
    assert decode_vin(bytearray(b"\x00\x00" + FAKE_VIN.encode())) == FAKE_VIN
    assert decode_vin(None) is None
    assert decode_vin(b"") is None


def test_health_flags_quiet_when_healthy() -> None:
    readings = {
        "RPM": 750.0,
        "CONTROL_MODULE_VOLTAGE": 14.2,
        "COOLANT_TEMP": 90.0,
        "LONG_FUEL_TRIM_1": 2.3,
        "SHORT_FUEL_TRIM_1": -1.0,
        "FUEL_LEVEL": 60.0,
    }
    assert health_flags(readings, False, 0) == ()


def test_health_flags_battery_low_only_when_engine_off() -> None:
    off = health_flags({"RPM": 0.0, "CONTROL_MODULE_VOLTAGE": 11.9}, False, 0)
    assert len(off) == 1 and "Battery low" in off[0]
    running = health_flags({"RPM": 800.0, "CONTROL_MODULE_VOLTAGE": 12.6}, False, 0)
    assert len(running) == 1 and "Charging voltage low" in running[0]


def test_health_flags_falls_back_to_adapter_voltage() -> None:
    flags = health_flags({"ELM_VOLTAGE": 11.5, "CONTROL_MODULE_VOLTAGE": None}, None, 0)
    assert any("Battery low" in f for f in flags)


def test_health_flags_codes_light_trim_coolant_fuel() -> None:
    readings = {"RPM": 2000.0, "COOLANT_TEMP": 110.0, "LONG_FUEL_TRIM_1": 14.0, "FUEL_LEVEL": 8.0}
    flags = health_flags(readings, True, 2)
    text = " ".join(flags)
    assert "light" in text and "2 stored" in text
    assert "Coolant hot" in text and "adding" in text and "Fuel low" in text


def test_fuel_trim_ignored_with_engine_off() -> None:
    assert health_flags({"RPM": 0.0, "LONG_FUEL_TRIM_1": 20.0}, False, 0) == ()


def test_summarize_rows_skips_blanks_and_time() -> None:
    rows = [
        {"time": "t1", "RPM": "800", "SPEED": ""},
        {"time": "t2", "RPM": "1200", "SPEED": "30"},
    ]
    stats = summarize_rows(rows)
    assert "time" not in stats
    assert stats["RPM"] == {"min": 800.0, "max": 1200.0, "mean": 1000.0, "n": 2}
    assert stats["SPEED"]["n"] == 1


def test_format_snapshot_reports_no_answer_and_flags() -> None:
    snap = Snapshot(
        taken_at="2026-01-01T12:00:00",
        vin=None,
        check_engine_light=None,
        stored_codes=(),
        readings=(Reading("RPM", None, ""), Reading("FUEL_LEVEL", 42.0, "percent")),
        flags=(),
    )
    text = format_snapshot(snap)
    assert "VIN: not reported" in text and "unknown" in text
    assert "not supported / no answer" in text and "42.0 percent" in text
    assert "No flags." in text


def test_mask_vin_keeps_only_last_four() -> None:
    assert mask_vin(FAKE_VIN) == "*************1234"
    assert mask_vin(None) == "not reported"


def test_is_read_only_allows_read_modes_and_refuses_clear() -> None:
    for req in (b"010C", b"0102", b"03", b"07", b"0902", b"ATRV"):
        assert is_read_only(req)
    for req in (b"04", b"08", b"2E", b"31", b"ATZ"):
        assert not is_read_only(req)


def test_every_command_the_tool_queries_passes_the_read_only_guard() -> None:
    names = (
        *fit_obd.SNAPSHOT_COMMANDS,
        *fit_obd.LOG_COMMANDS,
        *fit_obd.OTHER_COMMANDS,
    )
    for name in names:
        assert is_read_only(getattr(obd.commands, name).command), name
    assert not is_read_only(obd.commands.CLEAR_DTC.command)


def test_query_refuses_clear_codes_and_sends_nothing() -> None:
    car = _FakeCar({"CLEAR_DTC": None})
    with pytest.raises(fit_obd.ReadOnlyViolation):
        fit_obd._query(car, "CLEAR_DTC")
    assert car.sent == []


def test_readiness_lines_counts_complete_monitors() -> None:
    lines = readiness_lines(_status())
    assert lines[0].startswith("Readiness monitors: 3 of 3 complete (all complete)")
    lines = readiness_lines(_status(incomplete=("CATALYST_MONITORING",)))
    assert "2 of 3 complete (1 not complete)" in lines[0]
    assert any("catalyst" in line and "NOT complete" in line for line in lines)
    assert readiness_lines(None) == ["Readiness: not reported."]


def test_snapshot_from_a_simulated_car() -> None:
    car = _FakeCar(
        {
            "STATUS": _status(),
            "GET_DTC": [],
            "VIN": bytearray(FAKE_VIN.encode()),
            "CONTROL_MODULE_VOLTAGE": _FakeQuantity(11.9, "volt"),
            "RPM": _FakeQuantity(0, "revolutions_per_minute"),
            "FUEL_LEVEL": _FakeQuantity(64.3, "percent"),
        }
    )
    snap = fit_obd.take_snapshot(car)
    assert snap.check_engine_light is False and snap.stored_codes == ()
    assert snap.vin == FAKE_VIN
    assert any("Battery low" in f for f in snap.flags)
    text = format_snapshot(snap)
    assert FAKE_VIN not in text and "*************1234" in text
    assert all(is_read_only(req) for req in car.sent)


def test_explore_from_a_simulated_car_never_asks_for_the_vin() -> None:
    car = _FakeCar(
        {
            "STATUS": _status(),
            "GET_CURRENT_DTC": [],
            "FREEZE_DTC": None,
            "RPM": _FakeQuantity(0, "revolutions_per_minute"),
            "COOLANT_TEMP": _FakeQuantity(20, "degC"),
            "VIN": bytearray(FAKE_VIN.encode()),
        }
    )
    text = "\n".join(fit_obd.explore_lines(car))
    assert "Protocol: ISO 15765-4" in text
    assert "Live sensors this car supports (4):" in text
    assert "Pending codes: none" in text and "Freeze frame: none stored" in text
    assert obd.commands.VIN.command not in car.sent
    assert all(is_read_only(req) for req in car.sent)
