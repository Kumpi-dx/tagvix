import time

READ_COMMANDS = {
    "DM": "RD",
    "CIO": "RR",
    "IR": "RR",
    "LR": "RR",
}

WRITE_COMMANDS = {
    "DM": "WD",
    "CIO": "WR",
    "IR": "WR",
    "LR": "WR",
}

LR_BASE = 1000

PARITY_NAMES = {
    "N": "PARITY_NONE",
    "E": "PARITY_EVEN",
    "O": "PARITY_ODD",
}

FINS_HOSTLINK_HEADER = "800002" + "00" * 7
FINS_CMD_OPERATING_MODE = "0401"
FINS_MODE_MONITOR = "02"


class HostLinkError(Exception):
    pass


class HostLinkTimeout(HostLinkError):
    pass


class HostLinkResponseError(HostLinkError):
    pass


def calc_fcs(text):
    value = 0
    for ch in text.encode("ascii"):
        value ^= ch
    return "{:02X}".format(value)


def to_bcd4(value):
    """Format angka desimal jadi 4 digit BCD (yang dipakai Host Link C-mode)."""
    value = int(value)
    if not (0 <= value <= 9999):
        raise HostLinkError("Nilai di luar jangkauan BCD: {}".format(value))
    return "{:04d}".format(value)


class HostLinkClient:
    def __init__(self, port, baudrate=9600, bytesize=7, parity="E", stopbits=2,
                 timeout=1.0, unit_no=0, retries=3, retry_delay=0.3, simulate=False):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.unit_no = unit_no
        self.retries = retries
        self.retry_delay = retry_delay
        self.simulate = simulate
        self.stop_event = None
        self._ser = None
        self._sim_phase = 0.0

    def _stopping(self):
        return self.stop_event is not None and self.stop_event.is_set()

    @property
    def is_open(self):
        if self.simulate:
            return True
        return self._ser is not None and self._ser.is_open

    def open(self):
        if self.simulate:
            return
        import serial

        parity_value = getattr(serial, PARITY_NAMES.get(self.parity, "PARITY_EVEN"))
        stopbits_value = serial.STOPBITS_ONE if self.stopbits == 1 else serial.STOPBITS_TWO
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=parity_value,
            stopbits=stopbits_value,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _effective_address(self, area, address):
        if area == "LR":
            return address + LR_BASE
        return address

    def _build_frame(self, command, payload):
        body = "@{:02d}{}{}".format(self.unit_no, command, payload)
        return (body + calc_fcs(body) + "*\r").encode("ascii")

    def _read_until_cr(self):
        import serial  # noqa: F401

        buffer = bytearray()
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._stopping():
                raise HostLinkError("Dihentikan oleh pengguna")
            chunk = self._ser.read(1)
            if not chunk:
                continue
            if chunk == b"\r":
                return bytes(buffer)
            buffer += chunk
        if not buffer:
            raise HostLinkTimeout("Tidak ada respons dari PLC (timeout)")
        return bytes(buffer)

    def _parse_response(self, raw):
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise HostLinkResponseError("Respons bukan ASCII: {!r}".format(raw)) from exc

        if len(text) < 8 or text[0] != "@" or text[-1] != "*":
            raise HostLinkResponseError("Format respons tidak valid: {!r}".format(text))

        body = text[:-3]
        fcs_received = text[-3:-1].upper()
        fcs_expected = calc_fcs(body)
        if fcs_received != fcs_expected:
            raise HostLinkResponseError(
                "FCS salah (diterima {}, dihitung {})".format(fcs_received, fcs_expected)
            )

        end_code = text[5:7]
        if end_code != "00":
            raise HostLinkResponseError("PLC error code: {}".format(end_code))

        return text[7:-3]

    def _exchange(self, command, payload):
        if self.simulate:
            return None
        self._ser.reset_input_buffer()
        self._ser.write(self._build_frame(command, payload))
        return self._parse_response(self._read_until_cr())

    def _fins_exchange(self, fins_frame):
        if self.simulate:
            return ""
        if not self.is_open:
            self.open()
        body = "@{:02d}FA0{}".format(self.unit_no, fins_frame)
        frame = (body + calc_fcs(body) + "*\r").encode("ascii")
        self._ser.reset_input_buffer()
        self._ser.write(frame)
        raw = self._read_until_cr()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise HostLinkResponseError(
                "Respons FINS bukan ASCII: {!r}".format(raw)
            ) from exc

        if len(text) < 29 or text[0] != "@" or text[-1] != "*" or text[3:5] != "FA":
            raise HostLinkResponseError("Format respons FINS tidak valid: {!r}".format(text))

        fcs_received = text[-3:-1].upper()
        if fcs_received != calc_fcs(text[:-3]):
            raise HostLinkResponseError(
                "FCS FINS salah (diterima {}, dihitung {})".format(
                    fcs_received, calc_fcs(text[:-3])
                )
            )

        pos = text.find(FINS_CMD_OPERATING_MODE)
        if pos < 0:
            raise HostLinkResponseError(
                "Respons FINS tidak memuat command code: {!r}".format(text)
            )
        end_code = text[pos + 4:pos + 8]
        if end_code != "0000":
            raise HostLinkResponseError("PLC error code (FINS): {}".format(end_code))

        return text[pos + 8:-3]

    def set_monitor_mode(self):
        """Pindahkan CPU PLC ke mode MONITOR lewat perintah FINS 0401.

        MONITOR tetap menjalankan ladder (seperti RUN) tetapi mengizinkan
        penulisan word dari Host Link, sama seperti perilaku HMI/SCADA.
        """
        fins_frame = "{}{}{}".format(
            FINS_HOSTLINK_HEADER, FINS_CMD_OPERATING_MODE, FINS_MODE_MONITOR
        )
        return self._fins_exchange(fins_frame)

    def read_words(self, area, address, count):
        area = area.upper()
        if self.simulate:
            return self._simulate_words(area, address, count)

        command = READ_COMMANDS.get(area)
        if command is None:
            raise HostLinkError("Area tidak didukung: " + area)
        address = self._effective_address(area, address)
        payload = "{}{}".format(to_bcd4(address), to_bcd4(count))

        if not self.is_open:
            self.open()

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise HostLinkError("Dihentikan oleh pengguna")
            try:
                data = self._exchange(command, payload)
                words = []
                for i in range(0, len(data), 4):
                    words.append(int(data[i:i + 4], 16))
                if len(words) != count:
                    raise HostLinkResponseError(
                        "Jumlah word tidak sesuai: minta {}, dapat {}".format(count, len(words))
                    )
                return words
            except HostLinkError as exc:
                last_error = exc
                if self._stopping():
                    raise HostLinkError("Dihentikan oleh pengguna")
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise last_error

    def write_words(self, area, address, values):
        area = area.upper()
        if self.simulate:
            return
        command = WRITE_COMMANDS.get(area)
        if command is None:
            raise HostLinkError("Area tidak didukung: " + area)
        address = self._effective_address(area, address)
        data = "".join("{:04X}".format(int(v) & 0xFFFF) for v in values)
        payload = "{}{}".format(to_bcd4(address), data)

        if not self.is_open:
            self.open()

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise HostLinkError("Dihentikan oleh pengguna")
            try:
                self._exchange(command, payload)
                return
            except HostLinkError as exc:
                last_error = exc
                if self._stopping():
                    raise HostLinkError("Dihentikan oleh pengguna")
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise last_error

    def _simulate_words(self, area, address, count):
        import math

        self._sim_phase += 0.3
        words = []
        for i in range(count):
            idx = self._effective_address(area, address) + i
            value = int(100 + 50 * math.sin(self._sim_phase + idx * 0.5))
            words.append(value & 0xFFFF)
        return words
