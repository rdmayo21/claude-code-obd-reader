# AGENTS.md: set this read-only car reader up for your human

You are an AI coding agent (Claude Code, Codex, Gemini CLI, Cursor, or any other) and your human
wants to read their car's engine computer the way the video did. This file is the whole job.
Work through it top to bottom from the repo root and run every check. Do everything yourself
except the parts marked **HUMAN**; for those, ask, wait for the answer, and go on.

**Done means:**
1. The tests pass and the simulated car answers all four commands in step 3 (`check`,
   `explore`, `log`, `summary`). This part needs no car.
2. With the cable in the car and the key at ON: `uv run fit_obd.py check` printed a snapshot
   from the real car (a masked VIN, the check-engine light, codes, voltages) and
   `uv run fit_obd.py explore` printed the car's supported sensors and readiness (steps 4 to 7).
3. You told the human what the readings mean in plain words, including what they do not prove
   (step 9), and the key is off.

Step 4 asks whether the human has the cable and is at the car. If not, stop there with done 1
and tell them what the rest needs (step 4 says what to say).

## What this is

`fit_obd.py` is one Python file. It talks to an ELM327-compatible USB OBD-II cable through the
python-obd library and only **reads**: modes 01 (live data), 02 (freeze frame), 03 (stored
codes), 07 (pending codes), 09 (vehicle info) and the adapter's own voltage read (`ATRV`). A
guard in `_query` refuses everything else before it is sent, including mode 04 (clear codes).
Commands: `ports`, `check`, `explore`, `log`, `summary`. `simulate.py` runs any of them
against a simulated car.

## Rules

- **Read only.** Never send anything to the car that is not in the read-only modes above. Never
  weaken, bypass or remove the guard (`READ_ONLY_MODES`, `READ_ONLY_ADAPTER_COMMANDS`,
  `is_read_only`, the check in `_query`), and never send raw requests to the adapter yourself
  (no serial terminal, no `conn.query(..., force=True)`, no new commands outside those modes).
- **Never clear codes, reset monitors, run on-board tests (mode 08), or reprogram anything**
  unless the car's owner asks for that exact thing in their own words. Even then, first tell
  them what it does: clearing codes also erases the freeze frame and resets the emissions
  readiness monitors, so the car can fail an inspection until it has been driven enough, and the
  problem behind a code is not fixed by clearing it. This repo has no command for it; say so and
  suggest a scan tool or a mechanic rather than writing one.
- **The VIN stays private.** Never pass `--show-vin`. Never open, print, `cat` or paste any
  `check_*.json` under `logs/` (a real one holds the full VIN; treat the simulated ones in
  `logs/simulated/` the same way), and never commit anything in `logs/` (it is gitignored;
  keep it that way). The masked VIN in `check` output is fine to show.
- **Safety in and around the car.** The engine runs only outdoors, never in a closed garage. The
  driver never reads the laptop while driving; a log during a drive runs on its own
  (`--seconds`) or a passenger watches it. A key at ON with the engine off drains the battery:
  keep those sessions short and ask the human to turn the key off at the end.
- **Commands that never return:** `uv run fit_obd.py log` without `--seconds` runs until Ctrl-C.
  Always pass `--seconds N`. Every other command returns on its own within about a minute.
- If a check fails, read the output and use the table at the end before changing anything. If
  something fails on the car, tell the human what it means before you fix it.
- You will download Python packages (python-obd, pytest, the emulator). If your sandbox blocks
  that, ask the human to allow it.
- **Where the repo lives.** Clone it into the human's home folder (`~/claude-code-obd-reader`;
  on Windows `$HOME\claude-code-obd-reader` in PowerShell), not a temporary folder: they will run
  commands from it at the car. Whenever you hand the human a command, start it with
  `cd <the absolute path of this folder>` and then the command.

## Steps

Commands below work in a macOS or Linux shell and in Windows PowerShell unless marked.

1. **Tools.** `git --version` and `uv --version` must both print a version. Install uv if
   missing: macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh` (then open a new
   shell or run `export PATH="$HOME/.local/bin:$PATH"`); Windows PowerShell
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (then a
   new PowerShell window). uv brings its own Python (3.11 or newer is used).
2. **Tests.** `uv run --with pytest pytest -q` must end with `16 passed`. The first run
   downloads python-obd. No car or cable is involved.
3. **Simulated car.** Each of these starts the ELM327-emulator's `car` scenario on local TCP
   port 35000 inside one process, runs one command, and stops it:
   - `uv run --with ELM327-emulator==4.0.0 simulate.py check`: first line
     `Simulated car (ELM327-emulator, scenario 'car'): no real car involved.`, then a snapshot
     with `VIN: *********TS39`, `Check-engine light: off`, `Trouble codes: none`,
     `CONTROL_MODULE_VOLTAGE     14.67 volt`, `No flags.` and a line
     `Saved logs/simulated/check_<time>.json`.
   - `uv run --with ELM327-emulator==4.0.0 simulate.py explore`: `Protocol: ISO 15765-4 (CAN 11/500)`,
     `Live sensors this car supports (40):` and a list,
     `Readiness monitors: 6 of 6 complete (all complete)`, `Pending codes: none`,
     `Freeze frame: none stored`.
   - `uv run --with ELM327-emulator==4.0.0 simulate.py log --seconds 3`: ends
     `Stopped. 3 rows in logs/simulated/drive_<time>.csv`. Then
     `uv run fit_obd.py summary logs/simulated/drive_<time>.csv` (the name it printed) prints a
     table with `value min mean max n`.
   Each takes about 5 to 10 seconds. These numbers and the VIN are the emulator's, not a car's
   (its made-up VIN is 13 characters, so the mask shows 9 stars; a real 17-character VIN shows 13).
   The emulator also leaves an empty `elm.log` in the repo root, and uv makes `.venv/` and
   `uv.lock`; all are gitignored and harmless.
4. **HUMAN: at the car.** Ask the human, one question at a time if needed:
   - Do they have a USB OBD-II cable and are they at the car with this laptop now? If not, stop
     here and tell them: the tests and the simulated car work; the rest needs the cable plugged
     into the car's OBD-II port and this laptop, the key at ON, about 10 minutes, and on Windows
     possibly a driver update in Device Manager (step 5a). They can come back to you at the car.
   - Which cable is it? The tested one is an ELM327-compatible cable
     with an FTDI USB chip (Vgate vLinker FS USB). Bluetooth and Wi-Fi adapters are not covered
     by this runbook.
   - Is this laptop the one that will be in the car, and is the car parked outdoors or in an open
     space?
   Then ask them to: plug the cable into the car's OBD-II port (under the dashboard on the
   driver's side; the car's manual shows where), plug the USB end into this laptop, and turn the
   key (or press the start button without the brake) to **ON** with the engine **off**. Wait
   for them to say it is done.
5. **Find the adapter.** `uv run fit_obd.py ports` lists the serial ports that answer. Expect a
   new one: Windows `\\.\COM3` (any number), Linux `/dev/ttyUSB0`, macOS
   `/dev/tty.usbserial-<letters>`. If it is there, go to step 6. If not:
   - **Windows:** run
     `Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like '*VID_0403*' } | Format-Table Status, Class, FriendlyName -AutoSize`.
     A row with `Status` `Error` (or `Unknown`) means the cable is seen but has no working
     driver; in Device Manager it shows a warning icon and **error code 28**. That is what
     happened in the video. Fix it in step 5a. No row at all: the cable is not seen (unplug and
     replug it, try another USB port). A row with `OK` and class `Ports`: the COM port exists;
     run `ports` again and use `--port COMn` from the name.
   - **Linux:** `ls /dev/ttyUSB*`. If the port exists but opening it is denied, the user needs
     the `dialout` group: **HUMAN** runs `sudo usermod -aG dialout $USER`, then logs out and in.
   - **macOS:** `ls /dev/tty.usbserial*`. Nothing: unplug and replug, try another port or adapter.

   **5a. HUMAN (Windows only): install the driver through Device Manager.** An agent's terminal
   usually lacks the admin rights a driver install needs, so the human clicks through it. Ask
   them to: open Device Manager (right-click Start, Device Manager), find the cable (it has a
   warning icon; in the video it was listed as **vLinker FS**), right-click it, **Update
   driver**, **Search automatically for drivers**, and wait for Windows Update to install it.
   Then run the `Get-PnpDevice` command again. In the video this took **two rounds**: the first
   installed **USB Serial Converter**, then a second entry, **USB Serial Port**, showed error 28;
   the same steps on that entry (Update driver, Search automatically) installed the ports driver,
   and the cable became **USB Serial Port (COM3)**. Done when a `Ports` row shows `OK` with a
   `COM` number. If Windows Update finds nothing, the human can install FTDI's VCP driver from
   ftdichip.com instead (not needed in the video).
6. **The read-only check.** `uv run fit_obd.py check` (add `--port COM3` or the port from
   step 5 before `check` if auto-detection fails: `uv run fit_obd.py --port COM3 check`). The
   first connection takes a few seconds per speed it tries. You want a `Car snapshot` with
   `VIN: *************` and four characters, the check-engine light, trouble codes, and
   readings; `not supported / no answer` on some lines is normal (cars differ). It ends
   `Saved logs/check_<time>.json (it holds the full VIN: keep it private)`. Do not open that file.
7. **Explore.** `uv run fit_obd.py explore`: the protocol, the live sensors the car supports,
   readiness monitors, pending codes and the freeze frame. It never asks for the VIN.
8. **HUMAN, optional: engine running.** This is how the video checked the alternator. Ask the
   human whether they want to start the engine. Only outdoors. With a yes, wait for them to say
   it is running, then `uv run fit_obd.py check` again (with the engine running, the battery rule
   becomes a charging check), then `uv run fit_obd.py log --seconds 30` and
   `uv run fit_obd.py summary logs/drive_<time>.csv` with the name it printed. A row can take
   longer than the 1 s interval on some cars (about 1.5 s in the video), so 30 s may give about
   20 rows. Leave `log` running only with `--seconds`.
9. **Tell the human what you found, then finish.** In plain words, with the conditions of each
   reading: the check-engine light, any stored or pending codes (with their descriptions),
   battery voltage with the key on and engine off (about 12.4 to 12.7 V is a healthy rested
   12 V battery; a reading taken with the key on and a laptop plugged in is not a rested battery
   test), charging voltage with the engine running (13.5 to 14.5 V is normal), readiness
   monitors, and anything flagged. Say what a reading does not prove: a low number is a reason to
   test the battery and check the terminals, not a diagnosis. Then ask them to turn the key off
   (or the engine off) and unplug the cable when they are done. Their files are in `logs/` and
   stay private.

## When it does not work

| What you see | Cause and fix |
|---|---|
| `16 passed` not reached, import errors | Run from the repo root. `uv run` must be able to download python-obd; allow network access |
| `simulate.py`: `port 35000 is already in use` | An earlier emulator is still running. macOS/Linux: `lsof -nP -iTCP:35000 -sTCP:LISTEN` shows it; Windows: `Get-NetTCPConnection -LocalPort 35000`. Stop it if it is yours, otherwise ask the human |
| `simulate.py`: `the emulator is missing` | You ran it with `uv run simulate.py`; use `uv run --with ELM327-emulator==4.0.0 simulate.py ...` |
| `ERROR: no OBD adapter found` | No serial port for the cable: step 5 (Windows: error code 28, step 5a). If `ports` does list the cable, pass it with `--port`. Also caused by another program holding the port open (a scan tool app, a serial terminal, an earlier run): close it. Linux: the `dialout` group (step 5) |
| Windows Device Manager: warning icon, error code 28 | No matching driver: step 5a. In the video an FTDI driver was already installed but was a package made for a different FTDI product, so Windows did not use it for this cable |
| Driver installed, but a second device (**USB Serial Port**) now shows error 28 | Normal for FTDI cables: two halves. Repeat Update driver on that entry (step 5a) |
| `adapter found on ... but the car is not answering` | Key not at ON, cable not fully seated in the car's port, or a car without OBD-II. Re-seat, key to ON, wait 5 s, run again. Try `--baud 38400` or `--baud 115200` |
| `ERROR: refused ... not a read-only request. Nothing was sent to the car.` | The guard did its job: something tried a request outside the read-only modes. Do not loosen the guard to get past it. If a read was wrongly refused (in the video the adapter's `ATRV` voltage read was, before it was allowed by name), allow only that exact read-only request and add a test |
| Many lines `not supported / no answer` | That car does not report those values; normal. `explore` shows what it does report |
| `Battery low at rest` flag | Reported, not diagnosed: see step 9. Keep key-on time short |
| `log` rows slower than one a second | Each value is a separate request; some cars answer slowly. Use the rows you got |
| `ERROR: the car reports none of the logging commands as supported` | The engine computer did not answer the standard live-data list. Run `explore` to see what it does support |

## Changing things

- What `check` reads: `SNAPSHOT_COMMANDS`; what `log` reads: `LOG_COMMANDS` (names from
  python-obd's command table; `explore` prints the ones the car supports). Any new command must
  be in a read-only mode; the test `test_every_command_the_tool_queries_passes_the_read_only_guard`
  checks the lists. Run the tests afterwards.
- Flag thresholds: the constants after `SPARK_MONITORS` in `fit_obd.py`.
- Where files go: `LOG_DIR`.

## Map

- `fit_obd.py`: the reader. Pure logic first (`is_read_only`, `health_flags`,
  `readiness_lines`, `summarize_rows`, formatting), then the adapter I/O and the commands.
- `simulate.py`: runs a command against the ELM327-emulator's simulated car.
- `tests/test_fit_obd.py`: 16 tests with a fake car; no adapter needed.
- `docs/car_prompt.txt`: the prompt the video gave Claude Code in the car, lightly generalized.
- `README.md`: the human-facing overview, parts, safety and the Windows driver note.
