import struct
from dataclasses import dataclass, field
from typing import Optional

WORD_TYPES = {"BIT", "BOOL", "INT", "UINT", "WORD", "BCD"}
DWORD_TYPES = {"DINT", "UDINT", "REAL"}
VALID_TYPES = WORD_TYPES | DWORD_TYPES

HOSTLINK_AREAS = {"DM", "CIO", "IR", "LR"}
MODBUS_AREAS = {"HR", "IR", "CO", "DI"}
FINS_AREAS = {"DM", "CIO", "WR", "HR", "AR"}
VALID_AREAS = HOSTLINK_AREAS | MODBUS_AREAS | FINS_AREAS

AREA_PREFIX = {
    "DM": "D",
    "CIO": "CIO",
    "IR": "IR",
    "LR": "LR",
    "WR": "W",
    "HR": "H",
    "AR": "A",
}

PREFIX_TO_AREA = {
    "D": "DM",
    "CIO": "CIO",
    "IR": "IR",
    "LR": "LR",
    "W": "WR",
    "H": "HR",
    "A": "AR",
    "HR": "HR",
}


def parse_address_label(text):
    """Ubah alamat gaya Omron (mis. 'D200', 'CIO0.03') -> (area, address, bit)."""
    s = (text or "").strip().upper()
    if not s:
        raise ValueError("Alamat kosong")
    idx = 0
    while idx < len(s) and s[idx].isalpha():
        idx += 1
    prefix = s[:idx]
    number = s[idx:]
    if not prefix or not number:
        raise ValueError("Alamat tidak valid: " + text)
    area = PREFIX_TO_AREA.get(prefix)
    if area is None:
        raise ValueError("Prefix area tidak dikenal: " + prefix)
    bit = None
    if "." in number:
        number, bit_text = number.split(".", 1)
        bit = int(bit_text)
    return area, int(number), bit


def areas_for_protocol(protocol):
    if protocol == "hostlink":
        return HOSTLINK_AREAS
    if protocol in ("modbus_rtu", "modbus_tcp"):
        return MODBUS_AREAS
    if protocol == "fins_tcp":
        return FINS_AREAS
    return VALID_AREAS


@dataclass
class Tag:
    name: str
    area: str
    address: int
    datatype: str = "UINT"
    scale: float = 1.0
    unit: str = ""
    bit: Optional[int] = None

    @property
    def word_count(self) -> int:
        return 2 if self.datatype in DWORD_TYPES else 1

    @property
    def address_label(self) -> str:
        prefix = AREA_PREFIX.get(self.area, self.area)
        if self.bit is not None:
            return "{}{}.{:02d}".format(prefix, self.address, self.bit)
        return "{}{}".format(prefix, self.address)


def parse_tag(name: str, spec: str, valid_areas=None) -> Tag:
    parts = [p.strip() for p in spec.split(":")]
    if len(parts) < 2:
        raise ValueError("Tag '{}' tidak valid: '{}'. Minimal AREA:ALAMAT".format(name, spec))

    allowed = valid_areas if valid_areas is not None else VALID_AREAS
    area = parts[0].upper()
    if area not in allowed:
        raise ValueError(
            "Tag '{}': area '{}' tidak dikenal (pilihan: {})".format(
                name, area, ", ".join(sorted(allowed))
            )
        )

    address_field = parts[1]
    bit = None
    if "." in address_field:
        addr_text, bit_text = address_field.split(".", 1)
        bit = int(bit_text)
        if not (0 <= bit <= 15):
            raise ValueError("Tag '{}': nomor bit harus 0-15".format(name))
    else:
        addr_text = address_field
    address = int(addr_text)

    datatype = (parts[2] if len(parts) > 2 and parts[2] else "UINT").upper()
    if datatype not in VALID_TYPES:
        raise ValueError("Tag '{}': tipe '{}' tidak dikenal".format(name, datatype))

    if bit is not None:
        datatype = "BIT"

    scale = float(parts[3]) if len(parts) > 3 and parts[3] else 1.0
    unit = parts[4] if len(parts) > 4 else ""

    return Tag(name=name, area=area, address=address, datatype=datatype,
               scale=scale, unit=unit, bit=bit)


def parse_tags(tag_pairs, valid_areas=None):
    tags = []
    seen = set()
    for name, spec in tag_pairs:
        if name in seen:
            raise ValueError("Nama tag duplikat: " + name)
        seen.add(name)
        tags.append(parse_tag(name, spec, valid_areas=valid_areas))
    return tags


def _to_signed16(value):
    return value - 0x10000 if value & 0x8000 else value


def _to_signed32(value):
    return value - 0x100000000 if value & 0x80000000 else value


def _bcd_to_int(value):
    result = 0
    for shift in (12, 8, 4, 0):
        result = result * 10 + ((value >> shift) & 0xF)
    return result


def _combine32(words, word_order):
    w0 = words[0] & 0xFFFF
    w1 = words[1] & 0xFFFF
    if word_order == "big":
        return w1 | (w0 << 16)
    return w0 | (w1 << 16)


def decode_tag(tag: Tag, words, word_order="little"):
    if tag.datatype in ("BIT", "BOOL"):
        value = (words[0] >> (tag.bit or 0)) & 1
    elif tag.datatype == "INT":
        value = _to_signed16(words[0])
    elif tag.datatype == "UINT":
        value = words[0] & 0xFFFF
    elif tag.datatype == "WORD":
        value = words[0] & 0xFFFF
    elif tag.datatype == "BCD":
        value = _bcd_to_int(words[0] & 0xFFFF)
    elif tag.datatype == "UDINT":
        value = _combine32(words, word_order)
    elif tag.datatype == "DINT":
        value = _to_signed32(_combine32(words, word_order))
    elif tag.datatype == "REAL":
        combined = _combine32(words, word_order)
        value = struct.unpack("<f", struct.pack("<I", combined))[0]
    else:
        raise ValueError("Tipe tidak didukung: " + tag.datatype)

    if tag.datatype not in ("BIT", "BOOL") and tag.scale != 1.0:
        value = value * tag.scale

    return value


def encode_word(value):
    return int(value) & 0xFFFF
