# AGENTS.md — TagVix (Omron CP1E → MySQL)

## Quickstart

```powershell
python -m pip install -r requirements.txt
python main.py           # GUI mode
python main.py --console # console mode
build.bat                # build .exe
```

## Architecture

- **Monorepo**: Single package `app/` with drivers (`plc_driver.py`, `modbus_driver.py`, `fins_driver.py`)
- **Entry point**: `main.py` — routes to `run_gui()` or `run_console()` based on `--console` arg
- **Config**: `config/config.ini` — all settings INI format, edited via GUI **Settings** tab or directly
- **Drivers**: Host Link (serial), Modbus RTU/TCP, FINS/TCP — each implements `open()`, `close()`, `read_words()`, `write_words()`
- **Polling loop**: `middleware.py:run()` — runs in a thread, interval configurable via `config.ini` `[polling] interval`
- **Database**: MySQL via PyMySQL — auto-creates DB/tables if `autocreate=true`; two tables: `plc_readings` (histori) and `plc_latest` (upsert)

## Driver quirks

- **Host Link (Omron)**: parity must be `E`; bytesize 7; stopbits 2; unit_no 0-31; C-mode wiring: PC pin2↔SD, pin3↔RD (not cross-over); lurus kabel (2↔2, 3↔3)
- **Modbus RTU**: parity `N`/`E`/`O`; bytesize 7/8; stopbits 1/2; slave_id 1-247; `word_order` affects 32-bit types (DINT/REAL)
- **Modbus TCP**: `tcp_host` and `tcp_port` required; omitted for hostlink/rtu
- **FINS/TCP**: `fins_host`, `fins_port` (default 9600); `fins_dest_node`, `fins_src_node`, `fins_dna`, `fins_da2`, `fins_sna`, `fins_sa2` all 0-255
- **Simulate mode**: set `simulate=true` in `[plc]` to generate sinusoidal values without hardware

## Tag format

```
nama = AREA:ALAMAT:TIPE:SCALE:UNIT
```

- Host Link areas: `DM`, `CIO`, `IR`, `LR`; bits via `CIO:0.00`
- Modbus areas: `HR`, `IR`, `CO`, `DI`
- Types: `BIT`, `INT`, `UINT`, `WORD`, `BCD`, `DINT`, `UDINT`, `REAL`
- 32-bit types (DINT, UDINT, REAL) use `_combine32()` with `word_order` from config

## Database

- Auto-connect with `autocreate=true` creates DB and tables if missing
- `plc_readings`: 1 row per tag per cycle; indexed `(tag, ts)`
- `plc_latest`: 1 row per tag, upsert on each cycle
- `_safe_identifier()` validates table names — agent must not inject raw SQL

## GUI specifics

- **Theming**: `ctk.set_appearance_mode("light")`, `ctk.set_default_color_theme("blue")`
- **Protocol tab state**: `_apply_protocol_state()` shows/hides serial/hostlink/modbus/tcp/fins fields based on selected protocol
- **Tag editor**: multiline `CTkTextbox` with hint text; parse lines on `[tags]` section on save
- **Save & Apply**: `on_save()` writes `ini_values` + `tag_lines` to config; offers to restart TagVix immediately
- **Logs**: rotation via `RotatingFileHandler` max 1MB x 5 backups; also console if `log_console=true`

## Common gotchas

- `PermissionError: COM3` — close CX-Programmer or other serial consumers first
- `timeout` / `FCS salah` — verify baud/parity/stopbit match PLC; check lurus kabel (2↔2, 3↔3)
- `Gagal membuka port serial` — check Device Manager COM number
- `PLC error code: xx` — verify tag area/address valid for selected protocol
- `(2003) Can't connect to MySQL` — verify MySQL service, host/user/password
- `Data tidak masuk` — check `enabled = true` in config; check `logs/tagvix.log`
- **On stop**: `on_stop()` must be called before app exit to cleanly close PLC/DB connections
- `build.bat` copies `config\config.ini` to `dist\tagvix\config\` — agent must not edit config inside `dist/` only