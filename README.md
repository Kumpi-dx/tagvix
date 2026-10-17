# TagVix — Omron and Other PLC / Modbus → MySQL

Aplikasi TagVix untuk membaca data dari **PLC Omron CP1E** (via
**Host Link serial**) **atau perangkat Modbus** (**Modbus RTU** serial /
**Modbus TCP**), lalu menyimpannya ke **database MySQL**. Dilengkapi
**GUI modern-industrial** yang ringkas & mudah dipakai, dan dapat dibuild menjadi
**`.exe`** dengan konfigurasi terpisah.

## Fitur

- **GUI modern-industrial** (dark theme): tombol Start/Stop, indikator PLC & DB,
  tabel nilai live, kartu statistik, editor konfigurasi, dan console log.
- **Multi-protokol**: `hostlink` (Omron), `modbus_rtu`, `modbus_tcp` — pilih
  lewat dropdown di tab **Settings**.
- Setting protokol mudah: field yang tidak relevan otomatis dinonaktifkan.
- Komunikasi serial Omron **Host Link (C-mode)** native, tanpa software OPC tambahan.
- Baca area **DM** dan **CIO/IR** (word & bit); Modbus area **HR/IR/CO/DI**.
- Mendukung tipe data: `BIT`, `INT`, `UINT`, `WORD`, `BCD`, `DINT`, `UDINT`, `REAL`.
- Simpan ke 2 tabel MySQL: **histori** (per siklus) dan **nilai terakhir** (upsert).
- Auto-create database & tabel.
- Konfigurasi terpisah (`config.ini`), tidak perlu build ulang saat ganti setting.
- Logging rotasi ke file + console, auto-reconnect saat perangkat/DB terputus.
- Mode **simulasi** untuk uji coba tanpa perangkat.

## Struktur Proyek

```
opc_py/
├─ config/
│  └─ config.ini            # SEMUA konfigurasi (edit di sini)
├─ app/
│  ├─ config_loader.py      # baca & validasi config
│  ├─ plc_driver.py         # driver Host Link Omron
│  ├─ modbus_driver.py      # driver Modbus RTU/TCP
│  ├─ tags.py               # parsing & decode tag
│  ├─ db_store.py           # koneksi & simpan MySQL
│  ├─ middleware.py         # loop polling utama
│  ├─ gui.py                # GUI modern-industrial (CustomTkinter)
│  ├─ logger_setup.py       # logging
│  └─ paths.py              # resolve path (dev & .exe)
├─ main.py                  # entry point
├─ requirements.txt
├─ tagvix.spec              # spec PyInstaller
├─ build.bat                # script build .exe
├─ docs/                    # dokumentasi tambahan
│  ├─ contoh_ringan_1_tag.md # contoh cepat 1 tag (counter) -> MySQL
│  └─ contoh_ladder_cp1e.md  # contoh ladder CP1E lengkap -> MySQL
└─ README.md
```

> Mulai cepat: [`docs/contoh_ringan_1_tag.md`](docs/contoh_ringan_1_tag.md)
> (1 alamat/counter saja). Contoh lengkap:
> [`docs/contoh_ladder_cp1e.md`](docs/contoh_ladder_cp1e.md).

## 1. Instalasi (mode Python)

```bat
python -m pip install -r requirements.txt
python main.py
```

## 2. Konfigurasi (`config/config.ini`)

### Bagian `[plc]`

| Key        | Contoh   | Keterangan |
|------------|----------|------------|
| `protocol` | `hostlink` | `hostlink` \| `modbus_rtu` \| `modbus_tcp` |
| `port`     | `COM3`   | Port serial PC (hostlink & modbus_rtu) |
| `baudrate` | `9600`   | Harus sama dengan setting perangkat |
| `bytesize` | `7`      | 7 atau 8 |
| `parity`   | `E`      | N / E / O |
| `stopbits` | `2`      | 1 atau 2 |
| `unit_no`  | `0`      | Station number PLC Host Link (0–31) |
| `slave_id` | `1`      | Slave/device ID Modbus (1–247) |
| `tcp_host` | `127.0.0.1` | Host/IP perangkat Modbus TCP |
| `tcp_port` | `502`    | Port TCP Modbus |
| `address_base` | `0`  | `0` = alamat langsung (`40001`→`0`), `1` = gaya referensi (`40001`→`40000`) |
| `word_order` | `little` | Urutan word 32-bit: `little` (low dulu) \| `big` (high dulu) |
| `simulate` | `false`  | `true` = uji tanpa perangkat |

> Setting default Omron CP1E: **9600, 7 data bit, Even, 2 stop bit**.
> Default Modbus RTU: **9600, 8 data bit, None, 1 stop bit** (sesuaikan perangkat).

#### Contoh Modbus TCP

```ini
[plc]
protocol = modbus_tcp
tcp_host = 192.168.1.10
tcp_port = 502
slave_id = 1
address_base = 0
word_order = big
timeout = 1.0
retries = 3
```

#### Contoh Modbus RTU (RS-485)

```ini
[plc]
protocol = modbus_rtu
port = COM5
baudrate = 9600
bytesize = 8
parity = N
stopbits = 1
slave_id = 1
```

## Cara Pakai GUI

1. Klik tab **Settings** → pilih **Protocol** (Host Link / Modbus RTU / Modbus TCP),
   isi setting koneksi yang sesuai, dan kredensial MySQL.
2. Edit daftar **TAGS** (satu baris per tag), lalu klik **Simpan & Terapkan**.
3. Buka tab **Monitor** → klik **Start**.
4. Pantau nilai live di tabel, status **PLC ●** / **DB ●** di kanan atas,
   dan pesan di tab **Log**.
5. Klik **Stop** untuk berhenti. Konfigurasi tetap tersimpan di `config.ini`.

Menjalankan mode console (tanpa GUI):

```bat
python main.py --console
```

### Bagian `[database]`

```ini
host = 127.0.0.1
port = 3306
user = root
password = rahasia
database = plc_data
table_readings = plc_readings
table_latest = plc_latest
autocreate = true
```

### Bagian `[tags]` — definisi tag

Format:

```
nama = AREA:ALAMAT:TIPE:SCALE:UNIT
```

- **AREA**   : Host Link → `DM` | `CIO` | `IR` | `LR`
  Modbus → `HR` (holding) | `IR` (input) | `CO` (coil) | `DI` (discrete input)
- **ALAMAT** : nomor word/register (desimal). Untuk bit Host Link pakai `word.bit` → `CIO:0.00`
- **TIPE**   : `BIT` | `INT` | `UINT` | `WORD` | `BCD` | `DINT` | `UDINT` | `REAL`
- **SCALE**  : faktor pengali (opsional, default 1)
- **UNIT**   : satuan (opsional)

Contoh Host Link:

```ini
temperature = DM:100:INT:0.1:C      ; DM100, signed, dikali 0.1, satuan C
total_count = DM:200:DINT:1:pcs     ; DM200-DM201, 32-bit
setpoint    = DM:110:REAL:1:        ; DM110-DM111, float IEEE754
motor_run   = CIO:0.00:BIT:1:       ; bit 00 dari word CIO0
```

Contoh Modbus:

```ini
flow_rate = HR:40001:UINT:0.1:Lpm  ; holding register 40001 (basis 0 -> 0)
pressure  = HR:40002:INT:0.01:bar  ; holding register 40002
temp      = HR:40010:REAL:1:C      ; 2 register, float (lihat word_order)
pump_on   = CO:1:BIT:1:            ; coil ke-1
alarm     = DI:0:BIT:1:            ; discrete input ke-0
```

## 3. Build menjadi `.exe`

Jalankan:

```bat
build.bat
```

Hasil:

```
dist\tagvix\
├─ tagvix.exe              <-- jalankan ini
├─ config\config.ini       <-- edit konfigurasi di sini
└─ (library pendukung)
```

Cukup edit `config\config.ini`, lalu jalankan `tagvix.exe`.
Folder `logs\` dibuat otomatis saat aplikasi berjalan.

> `.exe` dibuat sebagai **aplikasi GUI** (tanpa jendela console hitam).
> Konfigurasi tetap bisa diubah lewat tab **Settings** di dalam aplikasi.

> Ingin satu file `.exe`? Ubah `build.bat` tambahkan `--onefile` pada perintah
> PyInstaller, atau modifikasi `tagvix.spec` (`EXE` tanpa `COLLECT`).

## 4. Wiring RS-232C (PC ↔ CP1E)

Gunakan port **RS-232C** pada CP1E (konektor **DB9 female**). Kabel resmi
yang disarankan: **XW2Z-200S-V** (2 m) / **XW2Z-500S-V** (5 m) atau
**XW2Z-200S-CV / XW2Z-500S-CV**. Konektor: **DB9 female** (ke PC) ↔
**DB9 male** (ke CP1E).

> PENTING: kabel ini **bukan null-modem / cross-over**. Port RS-232C Omron
> menaruh SD di pin 2 dan RD di pin 3 (kebalikan port PC), sehingga jalur
> data **lurus** (2↔2, 3↔3). Jangan pakai kabel serial PC biasa.

### Pinout CP1E (DB9 female di CPU Unit)

| Pin | Sinyal | Arah | Keterangan |
|-----|--------|------|------------|
| 1 | FG | - | Frame ground / shield |
| 2 | SD | Output PLC | Send Data (TX PLC) |
| 3 | RD | Input PLC | Receive Data (RX PLC) |
| 4 | RS | Output | RTS |
| 5 | CS | Input | CTS |
| 6 | +5V | - | **JANGAN dihubungkan ke perangkat lain** |
| 7 | - | - | (tidak dipakai) |
| 8 | - | - | (tidak dipakai) |
| 9 | SG | - | Signal Ground |

### Pinout PC / laptop (DB9 male, COM port)

| Pin | Sinyal |
|-----|--------|
| 2 | RXD (input) |
| 3 | TXD (output) |
| 5 | GND |
| 7 | RTS |
| 8 | CTS |

### Diagram sambungan PC ↔ CP1E

| PC (DB9) | Arah | CP1E (DB9) |
|----------|------|------------|
| 2 RXD | ←— | 2 SD |
| 3 TXD | —→ | 3 RD |
| 5 GND | ↔ | 9 SG |
| 7 RTS | —→ | 5 CS *(opsional)* |
| 8 CTS | ←— | 4 RS *(opsional)* |
| 1 shield | ↔ | 1 FG *(opsional)* |

- Data pin **lurus**: 2↔2 dan 3↔3. Ground: PC pin5 → CP1E **pin9**.
- Handshake opsional; untuk Host Link biasanya cukup 3 kabel (2, 3, 9).
  Bila diperlukan, alternatifnya short lokal: PC 7-8, dan CP1E 4-5.
- **Jangan sambungkan pin 6 (+5V).**

- Set **CPU serial port** CP1E ke mode **Host Link** dengan setting komunikasi
  yang sama (9600, 7, Even, 2) melalui CX-Programmer → PLC Settings.
- Pastikan Unit/Station No. di config sama dengan setting PLC.

## 5. Skema Database

Dibuat otomatis bila `autocreate = true`.

**Histori** (`plc_readings`) — 1 baris per tag per siklus:

| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | BIGINT PK | auto increment |
| ts | DATETIME(3) | waktu baca |
| tag | VARCHAR(64) | nama tag |
| area | VARCHAR(8) | DM/CIO/... |
| address | VARCHAR(32) | alamat |
| value | DOUBLE | nilai hasil decode |
| raw_value | VARCHAR(32) | nilai mentah (hex) |
| unit | VARCHAR(16) | satuan |
| quality | VARCHAR(16) | GOOD / BAD |

**Nilai terakhir** (`plc_latest`) — 1 baris per tag, di-update terus:

```sql
SELECT tag, value, unit, ts FROM plc_latest;
SELECT * FROM plc_readings
WHERE tag = 'temperature' AND ts >= NOW() - INTERVAL 1 HOUR;
```

## 6. Uji Coba Tanpa PLC

Set di `config.ini`:

```ini
[plc]
simulate = true
```

Aplikasi akan menghasilkan nilai sinusoidal dan tetap menyimpan ke MySQL.

## 7. Troubleshooting

| Gejala | Solusi |
|--------|--------|
| `PermissionError: COM3` | Tutup aplikasi lain (CX-Programmer, terminal serial) yang memakai port |
| `Gagal membuka port serial` | Cek nomor COM di Device Manager, cek kabel |
| `timeout` / `FCS salah` | Cek baud/parity/stopbit & Unit No. harus sama, cek kabel |
| `PLC error code: xx` | Alamat tidak valid / area tidak ada di PLC, cek `[tags]` |
| `(2003) Can't connect to MySQL` | Pastikan service MySQL jalan, host/user/password benar |
| Data tidak masuk | Cek `enabled = true`, cek log di `logs/tagvix.log` |

## Catatan

- **Host Link**: area baca `DM` (`RD`) dan `CIO/IR/LR` (`RR`). Nilai 32-bit & float
  Omron menyimpan **low word di alamat bawah** (ditangani otomatis).
- **Modbus**: area `HR`/`IR` (register) dan `CO`/`DI` (bit). 32-bit & float
  mengikuti `word_order` (default `little`; beberapa perangkat butuh `big`).
  `address_base` membantu bila perangkat memakai penomoran referensi (mis. 40001).
- Menambah protokol/driver lain: buat class dengan method `open`, `close`,
  `read_words`, `write_words` (lihat `app/modbus_driver.py`), lalu daftarkan
  pemilihannya di `app/middleware.py` dan validasi di `app/config_loader.py`.
# tagvix
