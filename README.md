```
Clone https://github.com/rdmayo21/claude-code-obd-reader and follow its AGENTS.md to set up a read-only OBD-II car reader for me.
```

# A read-only car reader, built with Claude Code

Companion to the video **[I Plugged Claude Code Into My Honda Fit's OBD Port](https://youtu.be/Eg4q1WUa-zI)**.

A USB OBD-II cable from a laptop to the port under the dashboard, and one Python file that asks
the car's engine computer for data: trouble codes, the check-engine light, battery and charging
voltage, temperatures, fuel, the sensors the car supports, emissions readiness, and a drive log.
**It only reads.** It never clears codes and never writes anything to the car.

In the video it ran on an old Windows laptop with Claude Code driving it. It found no trouble
codes, all eight emissions monitors complete, 39 live sensors, and a battery reading of 9.75 V
with the key on and the engine off; with the engine running the charging voltage was 14.2 V.

```
laptop ── USB ──> OBD-II cable (ELM327-compatible, FTDI USB chip) ──> OBD-II port under the dash
fit_obd.py: ports · check · explore · log · summary          (read-only modes 01, 02, 03, 07, 09)
```

## Set it up: hand it to your agent

Paste the line at the top of this page into your AI coding agent (Claude Code, Codex, Gemini CLI,
Cursor, any of them). It installs what is needed, runs the tests and a simulated car, and stops
only for what needs you: plugging the cable in, turning the key, and on Windows possibly a driver
update in Device Manager. [AGENTS.md](AGENTS.md) is the full runbook, with a check after every
step and a table of failures and fixes.

<details><summary>By hand instead</summary>

1. Install [uv](https://docs.astral.sh/uv/). Clone this repo and `cd` into it.
2. Tests (no car needed): `uv run --with pytest pytest -q`. A simulated car:
   `uv run --with ELM327-emulator==4.0.0 simulate.py check` (also `explore`, `log --seconds 3`).
3. Plug the cable into the car's OBD-II port and into the laptop. Key to ON; the engine can be off.
4. `uv run fit_obd.py ports` lists the serial ports (the cable is a new `COM` port on Windows,
   `/dev/ttyUSB0` on Linux, `/dev/tty.usbserial-*` on macOS).
5. `uv run fit_obd.py check`, then `uv run fit_obd.py explore`.
6. With the engine running, outdoors: `uv run fit_obd.py log --seconds 30`, then
   `uv run fit_obd.py summary logs/drive_<time>.csv`.

If the adapter is not found automatically, pass it: `--port COM3` (or `--port /dev/ttyUSB0`)
and, if needed, `--baud 115200`. These options go before the command:
`uv run fit_obd.py --port COM3 check`.

</details>

In the video, Claude Code started in the car with one prompt and the reader already in its folder;
[docs/car_prompt.txt](docs/car_prompt.txt) is that prompt, lightly generalized. The script keeps
the name it had in the video, `fit_obd.py`, but asks only for standard OBD-II data, nothing
specific to Honda.

## What you need

| Part | Notes |
|---|---|
| A **USB OBD-II cable** that speaks the ELM327 command set, with an **FTDI USB-serial chip** | The video used a [Vgate vLinker FS USB](https://vgatemall.com/products-detail/i-19). Other ELM327-compatible USB cables should work but were not tested |
| A laptop with Python 3.11+ via [uv](https://docs.astral.sh/uv/) | The video: an old Windows 10 laptop. macOS and Linux run the same code |
| A car with an OBD-II port | US cars from 1996 on, EU petrol cars from 2001 on. The video: a 2016 Honda Fit |
| Optional: an AI coding agent | Claude Code in the video |

The one Python dependency, [python-obd](https://github.com/brendan-w/python-obd), is installed
by `uv` on the first run.

## What it does

| Command | What it reads |
|---|---|
| `ports` | The serial ports that answer when opened (it briefly opens each candidate port) |
| `check` | One snapshot: VIN (masked to its last four), check-engine light, stored codes, adapter and computer voltage, temperatures, fuel, RPM, speed, load, fuel trims, pressure, distances, then plain-English flags (low battery with the engine off, charging voltage out of range with it running, hot coolant, large fuel trims, low fuel). Saves the full snapshot as JSON in `logs/` |
| `explore` | The protocol, every mode 01 value the car says it supports (listed as "live sensors"; the count includes status items such as `0101 STATUS`), the emissions readiness monitors the car has, pending codes and the freeze frame. Never asks for the VIN |
| `log` | 15 values once a second to `logs/drive_<time>.csv`, until Ctrl-C or `--seconds N` |
| `summary FILE` | Min, mean and max of each column of a drive log |

### What the output looks like

From the simulated car (`simulate.py`, which runs the
[ELM327-emulator](https://github.com/Ircama/ELM327-emulator) project's `car` scenario; every value
below is the emulator's, none is from a real car, and the VIN is the emulator's made-up one):

```
$ uv run --with ELM327-emulator==4.0.0 simulate.py check
Simulated car (ELM327-emulator, scenario 'car'): no real car involved.

Car snapshot  2026-11-24T21:55:04
VIN: *********TS39
Check-engine light: off
Trouble codes: none

  ELM_VOLTAGE                13.2 volt
  CONTROL_MODULE_VOLTAGE     14.67 volt
  COOLANT_TEMP               55.0 degree_Celsius
  INTAKE_TEMP                17.0 degree_Celsius
  AMBIANT_AIR_TEMP           not supported / no answer
  FUEL_LEVEL                 66.67 percent
  RPM                        1303.75 revolutions_per_minute
  SPEED                      10.0 kilometer_per_hour
  ENGINE_LOAD                100.0 percent
  SHORT_FUEL_TRIM_1          0.0 percent
  LONG_FUEL_TRIM_1           -5.47 percent
  BAROMETRIC_PRESSURE        97.0 kilopascal
  RUN_TIME                   117.0 second
  DISTANCE_W_MIL             0.0 kilometer
  DISTANCE_SINCE_DTC_CLEAR   50.0 kilometer

No flags.

Saved logs/simulated/check_20261124_215505.json (it holds the full VIN: keep it private)
```

```
$ uv run --with ELM327-emulator==4.0.0 simulate.py explore
Simulated car (ELM327-emulator, scenario 'car'): no real car involved.

Protocol: ISO 15765-4 (CAN 11/500)
Live sensors this car supports (40):
  0101  STATUS                       Status since DTCs cleared
  0103  FUEL_STATUS                  Fuel System Status
  ...
  014D  RUN_TIME_MIL                 Time run with MIL on
  014E  TIME_SINCE_DTC_CLEARED       Time since trouble codes cleared
  0151  FUEL_TYPE                    Fuel Type
  015B  HYBRID_BATTERY_REMAINING     Hybrid battery pack remaining life

Readiness monitors: 6 of 6 complete (all complete)
  misfire                  complete
  fuel system              complete
  component                complete
  catalyst                 complete
  oxygen sensor            complete
  egr vvt system           complete

Pending codes: none
Freeze frame: none stored
```

```
$ uv run --with ELM327-emulator==4.0.0 simulate.py log --seconds 3
Simulated car (ELM327-emulator, scenario 'car'): no real car involved.

Logging 15 values every 1.0s to logs/simulated/drive_20261124_215517.csv
Stopping after 3 s.

Stopped. 3 rows in logs/simulated/drive_20261124_215517.csv
$ uv run fit_obd.py summary logs/simulated/drive_20261124_215517.csv
value                            min      mean       max      n
RPM                              0.0   1837.42    4208.5      3
SPEED                           10.0     34.67      55.0      3
ENGINE_LOAD                    34.12     64.31     100.0      3
...
CONTROL_MODULE_VOLTAGE         14.67     14.72     14.79      3
```

A real car prints its own numbers. Reading them: a 12 V battery at rest is about 12.4 to 12.7 V;
with the engine running, 13.5 to 14.5 V means the alternator is charging. A reading taken with
the key on and the laptop plugged in is not a resting battery test, so a low number is a reason to
test the battery and check its terminals, not a diagnosis.

## Read-only: what it sends and what it never sends

- Every request goes through one function, `_query`, which refuses anything that is not an OBD
  read mode (01 live data, 02 freeze frame, 03 stored codes, 07 pending codes, 09 vehicle info)
  or the adapter's own voltage read (`ATRV`, which never reaches the car). Mode 04 (clear codes),
  mode 08 (on-board tests) and every other mode are refused before anything is sent. The tests
  check every command in the tool's fixed lists against the guard; the freeze-frame values that
  `explore` picks at run time are mode 02 and go through the same guard.
- The python-obd library itself sends the adapter's setup commands (`AT...`, they configure the
  cable, not the car) and the standard "which sensors do you support" reads when it connects.
- There is no command in this tool to clear codes, reset anything, or reprogram the car, and
  [AGENTS.md](AGENTS.md) tells agents never to add one unless the car's owner asks.
- In the video the guard caught Claude Code's own mistake: its first version of the guard also
  blocked the adapter's voltage read, so the check failed with nothing sent. It was fixed by
  allowing `ATRV` by name.

## Privacy

`check` prints the VIN masked to its last four characters. The saved JSON in `logs/` holds the
**full VIN**: `logs/` is gitignored, and neither it nor a screenshot of `--show-vin` should be
shared or committed.

## Windows: "error code 28" (the driver fix from the video)

In the video the cable showed up in Device Manager with a warning and no COM port: **error code
28, no driver installed for this device**, although an FTDI driver was on the laptop. The
installed FTDI driver package had been made for a different FTDI product, so it did not match
this cable's USB ID (`VID_0403&PID_6015`). Claude Code's terminal had no admin rights, so the fix
was done by hand in Device Manager, in two rounds:

1. Device Manager, find the cable (it showed as **vLinker FS**, with a warning icon), right-click,
   **Update driver**, **Search automatically for drivers**. Windows Update installed the first
   half, **USB Serial Converter**.
2. Error 28 came back on the second half, **USB Serial Port**. Same again on that entry:
   **Update driver**, **Search automatically**. Windows Update offered the matching FTDI ports
   driver, and the cable appeared as **USB Serial Port (COM3)**.

After that the first read of the car worked. If Windows Update finds nothing, FTDI's own VCP
driver for Windows (from ftdichip.com) is the other route; it was not needed in the video.
macOS and Linux include an FTDI driver.

## What was tested, and what was not

- **On a real car (November 2026):** `check`, `explore` and a 30-second engine-running `log` on
  one 2016 Honda Fit, from Windows 10 with a Vgate vLinker FS USB, with Claude Code running the
  commands. `explore` and the read-only guard were written by Claude Code during that session.
- **Tidied for this repo, and not yet run on a car:** messages and help made generic (no
  machine-specific paths or ports), `log --seconds N` (in the video the 30-second log was stopped
  by a timer from the command line), `simulate.py`, and `explore` and the guard rewritten from
  the session's screen recording (same modes, same allowed adapter read, same tests) rather than
  copied from the laptop. These pass the tests and the simulated run.
- **Simulated:** `check`, `explore`, `log` and `summary` against the ELM327-emulator through
  `simulate.py` (local TCP), on macOS with Python 3.14 (the laptop in the video had Python 3.12).
  `simulate.py` has not been run on Windows or Linux.
- **Not tested:** other cars, other cables, macOS or Linux with a real cable, Bluetooth or Wi-Fi
  adapters, diesel engines (the readiness list is the petrol one). If something is off, open an issue.

```bash
uv run --with pytest pytest -q                          # 16 tests, no car needed
uv run --with ELM327-emulator==4.0.0 simulate.py check  # a simulated car
```

## Credits and license

- [python-obd](https://github.com/brendan-w/python-obd) (GPL-2.0) talks to the adapter; it is
  installed by `uv`, not included here.
- [ELM327-emulator](https://github.com/Ircama/ELM327-emulator) for the simulated car.
- Everything in this repo: MIT, see [LICENSE](LICENSE).
- Not affiliated with Vgate, FTDI, Honda or Anthropic.
