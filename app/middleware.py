import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .db_store import MySQLStore
from .plc_driver import HostLinkClient, HostLinkError
from .modbus_driver import ModbusClient, ModbusError
from .fins_driver import FinsTcpClient, FinsError
from .tags import areas_for_protocol, decode_tag, parse_address_label, parse_tags


def _parse_number(text):
    text = str(text).strip()
    if text == "":
        raise ValueError("kosong")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(text, 0)
    except ValueError:
        return int(float(text))


@dataclass
class Reading:
    tag: str
    area: str
    address: str
    value: Optional[float]
    raw: Optional[str]
    unit: str
    quality: str


class Middleware:
    def __init__(self, config, logger, on_reading=None, on_status=None):
        self.config = config
        self.log = logger
        self.on_reading = on_reading
        self.on_status = on_status
        self.tags = parse_tags(
            config.tags, valid_areas=areas_for_protocol(config.protocol)
        )
        if config.protocol == "hostlink":
            self.plc = HostLinkClient(
                port=config.port,
                baudrate=config.baudrate,
                bytesize=config.bytesize,
                parity=config.parity,
                stopbits=config.stopbits,
                timeout=config.timeout,
                unit_no=config.unit_no,
                retries=config.retries,
                retry_delay=config.retry_delay,
                simulate=config.simulate,
            )
            self.word_order = "little"
        elif config.protocol == "fins_tcp":
            self.plc = FinsTcpClient(
                host=config.fins_host,
                port=config.fins_port,
                dest_node=config.fins_dest_node,
                src_node=config.fins_src_node,
                dna=config.fins_dna,
                da2=config.fins_da2,
                sna=config.fins_sna,
                sa2=config.fins_sa2,
                timeout=config.timeout,
                retries=config.retries,
                retry_delay=config.retry_delay,
                address_base=config.address_base,
                simulate=config.simulate,
            )
            self.word_order = config.word_order
        else:
            self.plc = ModbusClient(
                mode=config.protocol,
                port=config.port,
                baudrate=config.baudrate,
                bytesize=config.bytesize,
                parity=config.parity,
                stopbits=config.stopbits,
                tcp_host=config.tcp_host,
                tcp_port=config.tcp_port,
                slave_id=config.slave_id,
                timeout=config.timeout,
                retries=config.retries,
                retry_delay=config.retry_delay,
                address_base=config.address_base,
                simulate=config.simulate,
            )
            self.word_order = config.word_order
        self.db = None
        self._running = False
        self._stop_event = threading.Event()
        self.cycle_count = 0
        self.plc.stop_event = self._stop_event

    def _emit_status(self, component, ok, message=""):
        if self.on_status:
            try:
                self.on_status(component, ok, message)
            except Exception:
                pass

    def _init_db(self):
        if not self.config.db_enabled:
            self.log.warning("Database dinonaktifkan (database.enabled=false).")
            self._emit_status("db", False, "disabled")
            return
        self.db = MySQLStore(
            host=self.config.db_host,
            port=self.config.db_port,
            user=self.config.db_user,
            password=self.config.db_password,
            database=self.config.db_name,
            charset=self.config.db_charset,
            table_reg=self.config.table_reg,
            table_transmit=self.config.table_transmit,
            dev_name=self.config.dev_name,
            group_name=self.config.group_name,
            autocreate=self.config.autocreate,
            logger=self.log,
        )
        self.db.connect()
        self.log.info(
            "Terhubung ke MySQL %s:%s/%s",
            self.config.db_host, self.config.db_port, self.config.db_name,
        )
        self._emit_status("db", True, "connected")

    def _connect_plc(self):
        while self._running and not self._stop_event.is_set():
            try:
                self.plc.open()
                if self.config.simulate:
                    self.log.info("Mode SIMULASI aktif (tidak mengakses perangkat).")
                elif self.config.protocol == "hostlink":
                    self.log.info(
                        "Terhubung ke PLC %s @ %d bps, %d%s%d, unit %d",
                        self.config.port, self.config.baudrate, self.config.bytesize,
                        self.config.parity, int(self.config.stopbits), self.config.unit_no,
                    )
                elif self.config.protocol == "fins_tcp":
                    self.log.info(
                        "Terhubung ke PLC Omron FINS/TCP %s:%d, dest node %d",
                        self.config.fins_host, self.config.fins_port,
                        self.config.fins_dest_node,
                    )
                elif self.config.protocol == "modbus_tcp":
                    self.log.info(
                        "Terhubung ke Modbus TCP %s:%d, slave %d",
                        self.config.tcp_host, self.config.tcp_port, self.config.slave_id,
                    )
                else:
                    self.log.info(
                        "Terhubung ke Modbus RTU %s @ %d bps, %d%s%d, slave %d",
                        self.config.port, self.config.baudrate, self.config.bytesize,
                        self.config.parity, int(self.config.stopbits), self.config.slave_id,
                    )
                if (self.config.protocol == "hostlink" and self.config.auto_monitor
                        and not self.config.simulate):
                    try:
                        self.plc.set_monitor_mode()
                        self.log.info(
                            "PLC dipindah ke mode MONITOR (write diizinkan, ladder tetap jalan)."
                        )
                    except Exception as exc:
                        self.log.warning(
                            "Tidak bisa auto-switch ke MONITOR: %s. "
                            "Penulisan ke PLC hanya jalan bila PLC di mode MONITOR.", exc
                        )
                self._emit_status("plc", True, "connected")
                return True
            except Exception as exc:
                self.log.error("Gagal membuka koneksi perangkat: %s", exc)
                self._emit_status("plc", False, str(exc))
                self._stop_event.wait(self.config.reconnect_delay)
        return False

    def poll_once(self):
        cache = {}
        readings = []
        for tag in self.tags:
            if self._stop_event.is_set():
                break
            key = (tag.area, tag.address, tag.word_count)
            try:
                if key not in cache:
                    cache[key] = self.plc.read_words(tag.area, tag.address, tag.word_count)
                words = cache[key]
                value = decode_tag(tag, words, self.word_order)
                raw = "".join("{:04X}".format(w & 0xFFFF) for w in words)
                readings.append(
                    Reading(tag.name, tag.area, tag.address_label, float(value),
                            raw, tag.unit, "GOOD")
                )
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self.log.warning("Gagal baca tag %s (%s): %s",
                                 tag.name, tag.address_label, exc)
                readings.append(
                    Reading(tag.name, tag.area, tag.address_label, None,
                            None, tag.unit, "BAD")
                )
        return readings

    def _save(self, readings, ts):
        if self.db is None:
            return
        try:
            self.db.save_readings(readings, ts)
            self._emit_status("db", True, "connected")
        except Exception as exc:
            self.log.error("Gagal menyimpan ke MySQL: %s", exc)
            self._emit_status("db", False, str(exc))
            try:
                self.db.close()
                self.db.connect()
                self._emit_status("db", True, "connected")
            except Exception:
                pass

    def _process_transmit(self):
        if self.db is None:
            return
        try:
            rows = self.db.fetch_transmit()
        except Exception as exc:
            self.log.error("Gagal membaca tabel transmit: %s", exc)
            return

        for row in rows:
            dev_name, reg_name, reg_value, ttl, tr_time = row
            if reg_name is None or reg_value is None:
                continue
            try:
                area, address, bit = parse_address_label(str(reg_name))
                number = _parse_number(reg_value)
            except Exception as exc:
                self.log.warning("Perintah tulis tidak valid (%s=%s): %s",
                                 reg_name, reg_value, exc)
                continue
            try:
                self.plc.write_words(area, address, [number & 0xFFFF])
                self.log.info("Tulis ke PLC %s = %s", reg_name, number)
            except Exception as exc:
                self.log.error("Gagal tulis %s ke PLC: %s", reg_name, exc)
                continue
            try:
                self.db.delete_transmit(row)
            except Exception as exc:
                self.log.error("Gagal menghapus baris transmit %s: %s", reg_name, exc)

    def _log_readings(self, readings):
        summary = ", ".join("{}={}{}".format(r.tag, r.value, r.unit) for r in readings)
        self.log.info("Siklus baca OK: " + summary)

    def run(self):
        self._running = True
        self._stop_event.clear()
        try:
            self._init_db()
        except Exception as exc:
            self.log.error("Inisialisasi database gagal: %s", exc)
            self._emit_status("db", False, str(exc))

        if not self._connect_plc():
            self.log.error("Berhenti: tidak bisa terhubung ke PLC.")
            self._shutdown()
            return 1

        self.log.info("TagVix berjalan. Interval %.1f detik, %d tag.",
                      self.config.interval, len(self.tags))

        try:
            while self._running and not self._stop_event.is_set():
                start = time.time()
                try:
                    readings = self.poll_once()
                    if self._stop_event.is_set():
                        break
                    ts = datetime.now()
                    self._save(readings, ts)
                    self._process_transmit()
                    self.cycle_count += 1
                    if self.on_reading:
                        try:
                            self.on_reading(readings, ts, time.time() - start)
                        except Exception:
                            pass
                    self._log_readings(readings)
                except (HostLinkError, ModbusError, FinsError) as exc:
                    if self._stop_event.is_set():
                        break
                    self.log.error("Komunikasi perangkat bermasalah: %s", exc)
                    self._emit_status("plc", False, str(exc))
                    self.plc.close()
                    if not self._connect_plc():
                        break

                elapsed = time.time() - start
                remaining = self.config.interval - elapsed
                if remaining > 0:
                    self._stop_event.wait(remaining)
        except Exception as exc:
            self.log.exception("Error fatal pada loop: %s", exc)
        finally:
            self._shutdown()
        return 0

    def stop(self):
        self._running = False
        self._stop_event.set()

    def _shutdown(self):
        self.log.info("Menutup koneksi...")
        self.plc.close()
        if self.db is not None:
            self.db.close()
        self._emit_status("plc", False, "stopped")
        self._emit_status("db", False, "stopped")
