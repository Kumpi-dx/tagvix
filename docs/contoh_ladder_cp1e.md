# Contoh Ladder CP1E untuk TagVix → MySQL

Dokumen ini menjelaskan **contoh program ladder Omron CP1E** yang menyiapkan
data di memori PLC (DM/CIO) agar bisa dibaca **TagVix** lalu disimpan ke
database MySQL (`plc_readings` dan `plc_latest`).

> **Penting:** Ladder PLC **tidak** bisa konek langsung ke MySQL. PLC CP1E
> tidak punya driver/socket database. Yang menghubungkan ke database adalah
> **TagVix** (middleware Python). Ladder hanya mengisi area memori PLC.

---

## 1. Gambaran alur data

```
 Sensor / I-O ─► Program Ladder (CP1E) ─► DM / CIO (memori PLC)
                                              │
                                              │  Host Link serial (COM)
                                              ▼
                                        TagVix (Python)
                                              │
                                              ▼
                                   MySQL: plc_readings, plc_latest
```

Pembagian tugas:

| Bagian | Tugas |
|--------|-------|
| Ladder CP1E | Mengerjakan logika proses dan **mengisi nilai ke DM/CIO** |
| TagVix | Membaca DM/CIO via **Host Link** lalu **menulis ke MySQL** |
| MySQL | Menyimpan histori (`plc_readings`) & nilai terakhir (`plc_latest`) |

---

## 2. Prasyarat

- PLC **Omron CP1E** (port RS-232C), kabel **XW2Z-…S-V** (kabel lurus 2↔2, 3↔3).
- PLC diset **Host Link** dengan komunikasi yang sama dengan `config.ini`
  (default: **9600, 7 data bit, Even, 2 stop bit**, Unit No. 0).
- Software **CX-Programmer** untuk menulis & mengunduh ladder.
- TagVix sudah jalan dan bisa baca PLC (mode `hostlink`).

---

## 3. Peta alamat yang dipakai

Alamat di bawah ini dipilih agar cocok dengan blok `[tags]` di
`config/config.ini`.

| Memori PLC | tag (`config.ini`) | Tipe | Keterangan |
|-----------|--------------------|------|------------|
| `DM100` | `temperature` | INT (×0.1) | suhu, nilai = 253 → 25.3 °C |
| `DM101` | `pressure` | INT (×0.01) | tekanan |
| `DM102` | `speed` | UINT | kecepatan (rpm) |
| `DM200` + `DM201` | `total_count` | DINT | counter 32-bit (low di DM200) |
| `DM110` + `DM111` | `setpoint` | REAL | float IEEE754 (low di DM110) |
| `CIO0.00` | `motor_run` | BIT | tombol START (input fisik) |
| `DM300` | `alarm_word` | WORD | word alarm |

> Catatan: `alarm_word` di file contoh memakai `CIO10`. Pada CP1E, `CIO10`
> bisa saja bukan word output. Di dokumen ini disarankan pakai **`DM300`**
> agar aman. Sesuaikan baris `alarm_word` di `[tags]` bila perlu.

---

## 4. Program Ladder

Tulis di CX-Programmer (**Program → Ladder**), atau tempel mnemonic-nya di
**Program list view**. Opcode ditulis dalam tanda kurung.

### Rung 1 — Motor Start/Stop (latch)

`0.00` = tombol START (NO), `0.01` = tombol STOP (NC), `100.00` = output MOTOR.

```
       0.00        0.01      100.00
        | |---+----|/|--------( )---
              |
     100.00   |
        | |---+

        LD     0.00
        OR     100.00
        ANDNOT 0.01
        OUT    100.00
```

### Rung 2 — Inisialisasi (hanya 1 scan pertama)

`A200.11` = **First Cycle Flag** — ON hanya pada scan pertama. Di CX-Programmer
simbolnya `P_First_Cycle`; CP1E **tidak** memakai nama `P_First_Run`. Bila simbol
tidak muncul, ketik alamat `A200.11`.

```
        LD     A200.11
        MOV(021)  #0000     DM200    ; counter low  word = 0
        MOV(021)  #0000     DM201    ; counter high word = 0
        MOV(021)  #0001     DM10     ; konstanta +1 (32-bit)
        MOV(021)  #0000     DM11
        MOVL(498) #42F60000 DM110    ; setpoint = 123.0 (float) -> DM110/DM111
```

> `#42F60000` adalah representasi IEEE754 dari `123.0`. Omron menyimpan
> **low word di alamat lebih rendah**, dan TagVix sudah menanganinya
> (`_combine32`), jadi `MOVL #42F60000 DM110` sudah benar.

### Rung 3 — Counter naik tiap 1 detik (32-bit / DINT)

`P_1s` = pulsa internal 1 detik. `+L(400)` = penjumlahan 32-bit.

```
        LD     P_1s
        +L(400) DM200   DM10   DM200   ; DM200+DM201 = DM200+DM201 + 1
```

> `+L` menjumlahkan S1 (DM200, 2 word) + S2 (DM10/DM11 = 1) → D (DM200).
> Hasilnya counter 32-bit yang terus naik, cocok untuk tag `total_count` (DINT).

### Rung 4 — Nilai proses (contoh, tanpa modul analog)

Agar tabel DB langsung terisi nilai yang berubah, nilai dibuat dari counter.

```
        LD     P_1s
        AND(034) DM200  #03E7  DM100   ; temperature 0..999 -> 0.0..99.9 C
        AND(034) DM200  #00FF  DM101   ; pressure    0..255 -> 0.00..2.55 bar
        MOV(021) #1500         DM102   ; speed = 1500 rpm (tetap)
```

> `AND #03E7` (0x03E7 = 999) memotong nilai menjadi 0–999 → dikali scale 0.1
> di TagVix = 0.0–99.9 °C. Ini hanya **simulasi** agar ada data berubah.

### Rung 5 — Alarm sederhana

```
        LD     <(410) DM100  #0800     ; temperature > 800 (80.0 C) ?
        OUT    100.01                  ; bit alarm (opsional)
        LD     100.01
        MOV(021) #0001  DM300          ; alarm_word = 1 -> dibaca TagVix
```

---

## 5. Alamat & tipe: versi dengan modul analog (data nyata)

CP1E base unit **tidak** punya input analog. Untuk sensor nyata (4–20 mA /
0–10 V) perlu modul ekspansi, mis. **CP1W-AD041** (4 kanal). Kanal dimapping
ke `CIO1` (word 1), lalu discale ke DM dengan `SCL(194)`.

```
; Contoh skala kanal 1 (CIO1) rentang 0..6000  ->  0..1000 (x0.1 C) di DM100
        LD     P_On
        SCL(194) CIO1  DM400  DM100     ; parameter skala ada di DM400..DM403
```

Parameter `SCL(194)` di 4 word berturut-turut (`DM400`–`DM403`) biasanya:

| Word | Isi |
|------|-----|
| DM400 | Ay (min output) |
| DM401 | Ax (min input) |
| DM402 | By (max output) |
| DM403 | Bx (max input) |

Contoh nilai: `Ay=0, Ax=0, By=1000, Bx=6000`.

> Verifikasi blok parameter `SCL` dengan manual CP1E Anda (kadang urutannya
> dibalik). Bila tidak yakin, pakai `APR(069)` atau hitung manual dengan
> `*` dan `/`. Rung 4 di atas bisa dihapus bila sudah pakai analog asli.

---

## 6. Blok `[tags]` yang cocok

Tempel di `config/config.ini` bagian `[tags]`:

```ini
temperature = DM:100:INT:0.1:C
pressure    = DM:101:INT:0.01:bar
speed       = DM:102:UINT:1:rpm
total_count = DM:200:DINT:1:pcs
setpoint    = DM:110:REAL:1:C
motor_run   = CIO:0.00:BIT:1:
alarm_word  = DM:300:WORD:1:
```

Arti: `nama = AREA:ALAMAT:TIPE:SCALE:UNIT`.

---

## 7. Pemetaan ke tabel database

TagVix mengisi kedua tabel secara otomatis:

**`plc_readings`** — 1 baris per tag per siklus:

| Kolom | Isi contoh (`temperature`) |
|-------|----------------------------|
| ts | waktu baca |
| tag | `temperature` |
| area | `DM` |
| address | `100` |
| value | 25.3 |
| raw_value | `00FD` (hex) |
| unit | `C` |
| quality | `GOOD` / `BAD` |

**`plc_latest`** — 1 baris per tag (upsert), berisi nilai terakhir.

Contoh query hasil:

```sql
SELECT ts, tag, value, unit FROM plc_readings
WHERE tag = 'temperature'
ORDER BY ts DESC LIMIT 10;

SELECT * FROM plc_latest ORDER BY tag;
```

---

## 8. Cara menguji

### A. Uji logika tanpa PLC (simulasi TagVix)
Set di `config.ini`:

```ini
[plc]
simulate = true
```

Jalankan TagVix (`python main.py` atau `tagvix.exe`), klik **Start**. Nilai
sinusoidal akan muncul dan tersimpan ke MySQL — memastikan sisi DB sudah benar
tanpa perlu PLC.

### B. Uji dengan PLC asli
1. Tulis ladder di CX-Programmer, **Download** ke CP1E.
2. Pastikan PLC di mode **Host Link**, setting serial sama (9600, 7, E, 2).
3. Di `config.ini`: `simulate = false`, `port` = COM yang benar.
4. Jalankan TagVix → **Start**. Cek tabel `plc_readings`/`plc_latest`.
5. Tonton nilai `temperature`/`total_count` berubah tiap siklus.

### C. Cek cepat komunikasi PLC
Bila ragu, tes dulu dengan CX-Programmer atau `py` sederhana untuk memastikan
COM tidak dipakai aplikasi lain (tutup CX-Programmer saat TagVix jalan).

---

## 9. Troubleshooting

| Gejala | Kemungkinan & solusi |
|--------|----------------------|
| `PermissionError: COM3` | Port dipakai CX-Programmer → tutup dulu |
| `timeout` / `FCS salah` | Setting serial beda / kabel bukan lurus (2↔2, 3↔3) |
| `Gagal membuka port serial` | Nomor COM salah (cek Device Manager) |
| `PLC error code: xx` | Alamat area di `[tags]` tidak valid untuk CP1E |
| Nilai DINT/REAL salah | Pastikan urutan word (low dulu); cek `MOVL`/`+L` |
| Data tidak masuk | `enabled = true` di `[database]`; cek `logs/tagvix.log` |
| `(2003) Can't connect to MySQL` | Service MySQL mati / user-password salah |

---

## 10. Catatan tipe data Omron

- **DM**: area data word. `DM:100:INT` membaca 1 word; `DINT`/`UDINT`/`REAL`
  membaca 2 word (alamat+1), **low word di alamat lebih rendah**.
- **CIO**: bit & word I/O. Bit ditulis `CIO:0.00` (word 0, bit 00).
- **REAL** harus ditulis sebagai pola bit IEEE754 (mis. lewat `MOVL`).
- Untuk menulis nilai dari HMI/komputer ke DM, gunakan fungsi Host Link write
  TagVix (`write_words`) bila diperlukan.
```
