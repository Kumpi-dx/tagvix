import time

WRITE_AREAS = {"HR", "CO"}
READ_AREAS = {"HR", "IR", "CO", "DI"}


class ModbusError(Exception):
    pass


class ModbusClient:
    def __init__(self, mode, port="COM3", baudrate=9600, bytesize=8, parity="N",
                 stopbits=1, tcp_host="127.0.0.1", tcp_port=502, slave_id=1,
                 timeout=1.0, retries=3, retry_delay=0.3, address_base=0,
                 simulate=False):
        self.mode = mode
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.slave_id = slave_id
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.address_base = address_base
        self.simulate = simulate
        self.stop_event = None
        self._client = None
        self._sim_phase = 0.0

    def _stopping(self):
        return self.stop_event is not None and self.stop_event.is_set()

    @property
    def is_open(self):
        if self.simulate:
            return True
        return self._client is not None and getattr(self._client, "connected", False)

    def _label(self):
        if self.mode == "modbus_tcp":
            return "{}:{}".format(self.tcp_host, self.tcp_port)
        return "{} @ {} bps, {}{}{}".format(
            self.port, self.baudrate, self.bytesize, self.parity, int(self.stopbits)
        )

    def open(self):
        if self.simulate:
            return
        from pymodbus.client import ModbusSerialClient, ModbusTcpClient

        if self.mode == "modbus_tcp":
            client = ModbusTcpClient(
                host=self.tcp_host, port=self.tcp_port,
                timeout=self.timeout, retries=0,
            )
        else:
            client = ModbusSerialClient(
                port=self.port, baudrate=self.baudrate, bytesize=self.bytesize,
                parity=self.parity, stopbits=int(self.stopbits),
                timeout=self.timeout, retries=0,
            )
        if not client.connect():
            try:
                client.close()
            except Exception:
                pass
            raise ModbusError("Gagal terhubung ke perangkat Modbus " + self._label())
        self._client = client

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

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

    def _read_once(self, area, address, count):
        device_id = self.slave_id
        if area == "HR":
            rr = self._client.read_holding_registers(address, count=count, device_id=device_id)
        elif area == "IR":
            rr = self._client.read_input_registers(address, count=count, device_id=device_id)
        elif area == "CO":
            rr = self._client.read_coils(address, count=count, device_id=device_id)
        elif area == "DI":
            rr = self._client.read_discrete_inputs(address, count=count, device_id=device_id)
        else:
            raise ModbusError("Area tidak didukung: " + area)

        if rr is None:
            raise ModbusError("Tidak ada respons dari perangkat Modbus")
        if rr.isError():
            raise ModbusError("Modbus exception: " + str(rr))
        if area in ("CO", "DI"):
            return [1 if b else 0 for b in rr.bits[:count]]
        return [w & 0xFFFF for w in rr.registers[:count]]

    def read_words(self, area, address, count):
        area = area.upper()
        if self.simulate:
            return self._simulate_words(area, address, count)
        if area not in READ_AREAS:
            raise ModbusError("Area tidak didukung: " + area)

        addr = self._offset(address)
        if not self.is_open:
            self.open()

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise ModbusError("Dihentikan oleh pengguna")
            try:
                return self._read_once(area, addr, count)
            except Exception as exc:
                last_error = exc
                if self._stopping():
                    raise ModbusError("Dihentikan oleh pengguna")
                self._reconnect()
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise ModbusError("Gagal baca {}:{} -> {}".format(area, address, last_error))

    def write_words(self, area, address, values):
        area = area.upper()
        if self.simulate:
            return
        if area not in WRITE_AREAS:
            raise ModbusError("Area tidak bisa ditulis: " + area)

        addr = self._offset(address)
        if not self.is_open:
            self.open()

        last_error = None
        for attempt in range(1, self.retries + 1):
            if self._stopping():
                raise ModbusError("Dihentikan oleh pengguna")
            try:
                if area == "HR":
                    rr = self._client.write_registers(
                        addr, [int(v) & 0xFFFF for v in values], device_id=self.slave_id
                    )
                else:
                    if len(values) == 1:
                        rr = self._client.write_coil(
                            addr, bool(values[0]), device_id=self.slave_id
                        )
                    else:
                        rr = self._client.write_coils(
                            addr, [bool(v) for v in values], device_id=self.slave_id
                        )
                if rr is None or rr.isError():
                    raise ModbusError("Modbus exception: " + str(rr))
                return
            except Exception as exc:
                last_error = exc
                if self._stopping():
                    raise ModbusError("Dihentikan oleh pengguna")
                self._reconnect()
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise ModbusError("Gagal tulis {}:{} -> {}".format(area, address, last_error))

    def _simulate_words(self, area, address, count):
        import math

        self._sim_phase += 0.3
        words = []
        for i in range(count):
            value = int(100 + 50 * math.sin(self._sim_phase + (address + i) * 0.5))
            words.append(value & 0xFFFF)
        return words
