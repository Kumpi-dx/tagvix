# Contoh Ringan — 1 Tag (Counter) → MySQL

Panduan cepat: **satu alamat saja** (counter) yang otomatis tersimpan ke
database. Cocok untuk memastikan jalur **PLC → TagVix → MySQL** sudah benar
sebelum menambah tag lain.

Alamat yang dipakai: **`DM200`**, nama tag **`counter`**.

---

## Ringkasan jalur data

```
DM200 (counter, naik tiap 1 detik)
        │
        │ Host Link serial (COM)
        ▼
     TagVix  ──►  MySQL
                 ├─ plc_readings  (histori, 1 baris/siklus)
                 └─ plc_latest    (nilai terakhir, 1 baris/tag)
```

---

## 1. Isi `config/config.ini`

Cukup **satu baris** di bagian `[tags]`:

```ini
[tags]
counter = DM:200:BCD:1:pcs
```

> Format: `nama = AREA:ALAMAT:TIPE:SCALE:UNIT`.
> Tipe `BCD` dipakai karena contoh ladder menambah nilai dalam BCD.

Pastikan bagian `[database]` aktif:

```ini
[database]
enabled = true
database = plc_data
autocreate = true
```

---

## 2. Uji dulu TANPA PLC (mode simulasi)

Paling cepat. TagVix akan membuat nilai naik-turun sinusoidal untuk tiap tag,
lalu menyimpannya ke MySQL.

```ini
[plc]
simulate = true
```

Lalu jalankan:

```powershell
python main.py
```

Klik **Start** di GUI. Buka MySQL:

```sql
SELECT * FROM plc_latest;
SELECT ts, tag, value, unit FROM plc_readings ORDER BY id DESC LIMIT 10;
```

Kalau baris `counter` muncul dan `value` berubah tiap siklus → **jalur DB sudah
beres**. Lanjut ke langkah 3.

---

## 3. Uji dengan PLC asli (ladder minimal, 2 rung)

Buat program baru di **CX-Programmer**, tulis 2 rung berikut:

```
; ---------- RUNG 1 : bersihkan DM200 saat PLC baru ON ----------
        LD     A200.11               ; First Cycle Flag (P_First_Cycle)
        MOV(021) #0  DM200

; ---------- RUNG 2 : DM200 naik 1 tiap 1 detik (BCD) ----------
        LD     P_1s
        +(400) DM200  #1  DM200      ; DM200 = DM200 + 1
```

Penjelasan:
- `A200.11` = **First Cycle Flag** — ON hanya pada scan pertama. Di CX-Programmer
  simbolnya bernama `P_First_Cycle` (CP1E **tidak** memakai nama `P_First_Run`).
  Kalau simbol tidak muncul, ketik alamatnya langsung: `A200.11`.
- `P_1s` = pulsa clock internal **1 detik** (ada di CP1E).
- `+(400)` = penjumlahan BCD; tiap detik DM200 naik 1 (0,1,2,…). Nilai sama
  dengan `counter` yang dibaca TagVix.

Download ke CP1E. Set di `config.ini`:

```ini
[plc]
simulate = false
port = COM3          ; sesuaikan
```

Jalankan TagVix → **Start**. Cek lagi:

```sql
SELECT ts, tag, value, unit FROM plc_readings
WHERE tag = 'counter' ORDER BY id DESC LIMIT 10;
```

`value` harus naik mendekati 1 per detik.

---

## 4. Isi tabel yang dipakai

**`plc_latest`** (1 baris per tag):

| kolom | contoh |
|-------|--------|
| tag | `counter` |
| value | 42 |
| unit | `pcs` |
| ts | 2026-10-12 16:00:00 |

**`plc_readings`** (histori):

| ts | tag | area | address | value | raw_value | unit | quality |
|----|-----|------|---------|-------|-----------|------|---------|
| … | counter | DM | 200 | 42 | `0042` | pcs | GOOD |

---

## 5. Langkah berikutnya

- Tambah tag lain di `[tags]` (satu baris per tag) → otomatis ikut tersimpan.
- Untuk beberapa tag + sensor analog nyata, lihat
  [`contoh_ladder_cp1e.md`](contoh_ladder_cp1e.md).
- Ganti nilai setiap tag dengan sensor asli, atau pakai `simulate = true`
  untuk uji tanpa perangkat.

---

## 6. Bila bermasalah

| Gejala | Solusi |
|--------|--------|
| `PermissionError: COM3` | Tutup CX-Programmer / aplikasi yang memakai port |
| `timeout` / `FCS salah` | Samakan serial (9600, 7, E, 2) & Unit No. |
| Tag jalan tapi value tetap | Cek rung 2 (`P_1s`, `+`), cek tipe `BCD` di `[tags]` |
| Data tidak masuk DB | `enabled = true`, `autocreate = true`; cek `logs/tagvix.log` |
| `(2003) Can't connect to MySQL` | Service MySQL / user / password |
