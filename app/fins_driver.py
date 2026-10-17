import socket
import struct
import time

FINS_TCP_PORT = 9600
FINS_MAGIC = b"FINS"
FINS_TCP_CMD_FRAME = 0x00000000
FINS_TCP_CMD_NODE = 0x00000001

CMD_MEMORY_READ = 0x0101
CMD_MEMORY_WRITE = 0x0102

WORD_AREAS = {
    "DM": 0x82,
    "CIO": 0xB0,
    "WR": 0xB1,
    "HR": 0xB2,
    "AR": 0xB3,
}
READ_AREAS = set(WORD_AREAS)
WRITE_AREAS = set(WORD_AREAS)


class FinsError(Exception):
    pass


class FinsTcpClient:
    def __init__(self, host="127.0.0.1", port=FINS_TCP_PORT, dest_node=0,
                 src_node=0, dna=0, da2=0, sna=0, sa2=0, timeout=1.0,
                 retries=3, retry_delay=0.3, address_base=0, simulate=False):
        self.host = host
        self.port = port
        self.dest_node = dest_node & 0xFF
        self.src_node = src_node & 0xFF
        self.dna = dna & 0xFF
        self.da2 = da2 & 0xFF
        self.sna = sna & 0xFF
        self.sa2 = sa2 & 0xFF
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.address_base = address_base
        self.simulate = simulate
        self.stop_event = None
        self._sock = None
        self._sid = 0
        self._sim_phase = 0.0

    def _stopping(self):
        return self.stop_event is not None and self.stop_event.is_set()

    @property
    def is_open(self):
        if self.simulate:
            return True
        return self._sock is not None

    def _label(self):
        return "{}:{}".format(self.host, self.port)

    def open(self):
        if self.simulate:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            try:
                sock.close()
            except Exception:
                pass
            raise FinsError("Gagal terhubung ke PLC FINS/TCP " + self._label())
        self._sock = sock

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def _reconnect(self):
        self.close()
        if self._stopping():
            return
        try:
            self.open()
        except Exception:
            pass

    def _offset(self, address):
        if self.address_base == 1:
            return address - 1
        return address

    def _next_sid(self):
        self._sid = (self._sid + 1) & 0xFF
        return self._sid

    def _build_fins_frame(self, command, body):
        sid = self._next_sid()
        header = struct.pack(
            ">BBBBBBBBBB",
            0x80,
            0x00,
            0x02,
            self.dna,
            self.dest_node,
            self.da2,
            self.sna,
            self.src_node,
            self.sa2,
            sid,
        )
        return header + struct.pack(">H", command) + body

    def _recv_exact(self, count):
        chunks = b""
        while len(chunks) < count:
            part = self._sock.recv(count - len(chunks))
            if not part:
                raise FinsError("Koneksi FINS/TCP terputus")
            chunks += part
        return chunks

    def _send_command(self, command, body=b""):
        frame = self._build_fins_frame(command, body)
        packet = (
            FINS_MAGIC
            + struct.pack(">I", FINS_TCP_CMD_FRAME)
            + struct.pack(">I", 0x00000000)
            + struct.pack(">I", len(frame))
            + frame
        )
        self._sock.sendall(packet)

        head = self._recv_exact(16)
        if head[:4] != FINS_MAGIC:
            raise FinsError("Balasan FINS/TCP tidak valid")
        tcp_error = struct.unpack(">I", head[8:12])[0]
        length = struct.unpack(">I", head[12:16])[0]
        if tcp_error not in (0,):
            raise FinsError("FINS/TCP error: 0x{:08X}".format(tcp_error))
        if length < 12:
            raise FinsError("Panjang balasan FINS tidak valid")
        data = self._recv_exact(length)

        mres = data[12]
        sres = data[13]
        if mres != 0x00 or sres != 0x00:
            raise FinsError("FINS error: MRES=0x{:02X}, SRES=0x{:02X}".format(mres, sres))
        return data[14:]

    def _read_once(self, area, address, count):
        area_code = WORD_AREAS[area]
        body = bytes([
            area_code,
            (address >> 8) & 0xFF,
            address & 0xFF,
            0x00,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        resp = self._send_command(CMD_MEMORY_READ, body)
        words = []
        for i in range(0, min(len(resp), count * 2), 2):
            words.append(struct.unpack(">H", resp[i:i + 2])[0])
        if len(words) < count:
            raise FinsError("Data balasan FINS kurang dari yang diminta")
        return words

    def read_words(self, area, address, count):
        area = area.upper()
        if self.simulate:
            return self._simulate_words(area, address, count)
        if area not in READ_AREAS:
            raise FinsError("Area tidak didukung: " + area)

        addr = self._offset(address)
        if not self.is_open:
            self.open()

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise FinsError("Dihentikan oleh pengguna")
            try:
                return self._read_once(area, addr, count)
            except Exception as exc:
                last_error = exc
                if self._stopping():
                    raise FinsError("Dihentikan oleh pengguna")
                self._reconnect()
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise FinsError("Gagal baca {}:{} -> {}".format(area, address, last_error))

    def write_words(self, area, address, values):
        area = area.upper()
        if self.simulate:
            return
        if area not in WRITE_AREAS:
            raise FinsError("Area tidak bisa ditulis: " + area)

        addr = self._offset(address)
        if not self.is_open:
            self.open()

        count = len(values)
        area_code = WORD_AREAS[area]
        body = bytes([
            area_code,
            (addr >> 8) & 0xFF,
            addr & 0xFF,
            0x00,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        for value in values:
            body += struct.pack(">H", int(value) & 0xFFFF)

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise FinsError("Dihentikan oleh pengguna")
            try:
                self._send_command(CMD_MEMORY_WRITE, body)
                return
            except Exception as exc:
                last_error = exc
                if self._stopping():
                    raise FinsError("Dihentikan oleh pengguna")
                self._reconnect()
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise FinsError("Gagal tulis {}:{} -> {}".format(area, address, last_error))

    def _simulate_words(self, area, address, count):
        import math

        self._sim_phase += 0.3
        words = []
        for i in range(count):
            value = int(100 + 50 * math.sin(self._sim_phase + (address + i) * 0.5))
            words.append(value & 0xFFFF)
        return words
