import configparser

from .paths import find_config


def _get_bool(cp, section, option, default=False):
    if not cp.has_option(section, option):
        return default
    return cp.getboolean(section, option)


def _get_int(cp, section, option, default=0):
    if not cp.has_option(section, option):
        return default
    return cp.getint(section, option)


def _get_float(cp, section, option, default=0.0):
    if not cp.has_option(section, option):
        return default
    return cp.getfloat(section, option)


class Config:
    def __init__(self):
        self.path = find_config()
        cp = configparser.ConfigParser()
        cp.optionxform = str
        with open(self.path, "r", encoding="utf-8") as fh:
            cp.read_file(fh)

        if not cp.has_section("plc"):
            raise ValueError("Bagian [plc] wajib ada di config.ini")
        if not cp.has_section("database"):
            raise ValueError("Bagian [database] wajib ada di config.ini")

        self.protocol = cp.get("plc", "protocol", fallback="hostlink").strip().lower()
        self.port = cp.get("plc", "port", fallback="COM3").strip()
        self.baudrate = _get_int(cp, "plc", "baudrate", 9600)
        self.bytesize = _get_int(cp, "plc", "bytesize", 7)
        self.parity = cp.get("plc", "parity", fallback="E").strip().upper()
        self.stopbits = _get_float(cp, "plc", "stopbits", 2)
        self.timeout = _get_float(cp, "plc", "timeout", 1.0)
        self.unit_no = _get_int(cp, "plc", "unit_no", 0)
        self.retries = _get_int(cp, "plc", "retries", 3)
        self.retry_delay = _get_float(cp, "plc", "retry_delay", 0.3)
        self.simulate = _get_bool(cp, "plc", "simulate", False)
        self.auto_monitor = _get_bool(cp, "plc", "auto_monitor", True)

        self.slave_id = _get_int(cp, "plc", "slave_id", 1)
        self.tcp_host = cp.get("plc", "tcp_host", fallback="127.0.0.1").strip()
        self.tcp_port = _get_int(cp, "plc", "tcp_port", 502)
        self.address_base = _get_int(cp, "plc", "address_base", 0)
        self.word_order = cp.get("plc", "word_order", fallback="little").strip().lower()

        self.fins_host = cp.get("plc", "fins_host", fallback="127.0.0.1").strip()
        self.fins_port = _get_int(cp, "plc", "fins_port", 9600)
        self.fins_dest_node = _get_int(cp, "plc", "fins_dest_node", 0)
        self.fins_src_node = _get_int(cp, "plc", "fins_src_node", 0)
        self.fins_dna = _get_int(cp, "plc", "fins_dna", 0)
        self.fins_da2 = _get_int(cp, "plc", "fins_da2", 0)
        self.fins_sna = _get_int(cp, "plc", "fins_sna", 0)
        self.fins_sa2 = _get_int(cp, "plc", "fins_sa2", 0)

        self.interval = _get_float(cp, "polling", "interval", 5.0)
        self.reconnect_delay = _get_float(cp, "polling", "reconnect_delay", 5.0)

        self.db_enabled = _get_bool(cp, "database", "enabled", True)
        self.db_host = cp.get("database", "host", fallback="127.0.0.1").strip()
        self.db_port = _get_int(cp, "database", "port", 3306)
        self.db_user = cp.get("database", "user", fallback="root").strip()
        self.db_password = cp.get("database", "password", fallback="")
        self.db_name = cp.get("database", "database", fallback="plc_data").strip()
        self.db_charset = cp.get("database", "charset", fallback="utf8mb4").strip()
        self.table_reg = cp.get("database", "table_reg", fallback="t_reg_status").strip()
        self.table_transmit = cp.get("database", "table_transmit", fallback="t_transmit").strip()
        self.dev_name = cp.get("database", "dev_name", fallback="OMRON").strip()
        self.group_name = cp.get("database", "group_name", fallback="default").strip()
        self.autocreate = _get_bool(cp, "database", "autocreate", True)

        self.log_level = cp.get("logging", "level", fallback="INFO").strip().upper()
        self.log_file = cp.get("logging", "file", fallback="logs/tagvix.log").strip()
        self.log_max_bytes = _get_int(cp, "logging", "max_bytes", 1048576)
        self.log_backup_count = _get_int(cp, "logging", "backup_count", 5)
        self.log_console = _get_bool(cp, "logging", "console", True)

        self.tags = []
        if cp.has_section("tags"):
            for name, spec in cp.items("tags"):
                spec = (spec or "").strip()
                if not spec or spec.startswith(";"):
                    continue
                self.tags.append((name.strip(), spec))

        self._validate()

    def _validate(self):
        if self.protocol not in ("hostlink", "modbus_rtu", "modbus_tcp", "fins_tcp"):
            raise ValueError("protocol tidak didukung: " + self.protocol)
        if self.protocol in ("hostlink", "modbus_rtu"):
            if self.bytesize not in (7, 8):
                raise ValueError("bytesize harus 7 atau 8")
            if self.parity not in ("N", "E", "O"):
                raise ValueError("parity harus N / E / O")
            if int(self.stopbits) not in (1, 2):
                raise ValueError("stopbits harus 1 atau 2")
        if self.protocol == "hostlink" and not (0 <= self.unit_no <= 31):
            raise ValueError("unit_no harus 0-31")
        if self.protocol in ("modbus_rtu", "modbus_tcp") and not (1 <= self.slave_id <= 247):
            raise ValueError("slave_id harus 1-247")
        if self.protocol == "modbus_tcp" and not self.tcp_host:
            raise ValueError("tcp_host wajib diisi untuk modbus_tcp")
        if self.protocol == "fins_tcp":
            if not self.fins_host:
                raise ValueError("fins_host wajib diisi untuk fins_tcp")
            for name in ("fins_dest_node", "fins_src_node", "fins_dna", "fins_da2",
                         "fins_sna", "fins_sa2"):
                if not (0 <= getattr(self, name) <= 255):
                    raise ValueError("{} harus 0-255".format(name))
        if self.address_base not in (0, 1):
            raise ValueError("address_base harus 0 atau 1")
        if self.word_order not in ("little", "big"):
            raise ValueError("word_order harus little atau big")
        if self.interval <= 0:
            raise ValueError("polling.interval harus > 0")
        if not self.tags:
            raise ValueError("Tidak ada tag terdefinisi di bagian [tags]")
