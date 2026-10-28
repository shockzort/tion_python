"""Кодек miIO: кадры локального протокола Xiaomi (UDP 54321) без I/O.

Спецификация — ``docs/protocol/xiaomi-miio.md``. Кадр — 32-байтный
заголовок (magic ``0x2131``, длина, 4 нуля, did, stamp, md5-контрольная
сумма) плюс тело JSON, зашифрованное AES-128-CBC/PKCS#7: ключ —
``md5(token)``, IV — ``md5(key + token)``. Контрольная сумма — md5 от
заголовка, в котором на её месте стоит токен, и шифротекста.

Hello — кадр из одного заголовка со всеми ``0xff`` после длины; ответ на
него несёт did и текущий stamp устройства (секунды с его старта). Время и
номер сообщения кодек не выдумывает — их передаёт вызывающий.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = 0x2131
HEADER_SIZE = 32
TOKEN_SIZE = 16
HELLO = struct.pack(">HH", MAGIC, HEADER_SIZE) + b"\xff" * 28
_HEADER = struct.Struct(">HHIII")


class MiioProtocolError(ValueError):
    """Кадр не разбирается: чужой magic, длина, контрольная сумма или JSON."""


@dataclass(frozen=True, slots=True)
class HelloReply:
    """Ответ на hello: идентификатор и часы устройства."""

    did: int
    stamp: int


@dataclass(frozen=True, slots=True)
class Packet:
    """Расшифрованный кадр с телом."""

    did: int
    stamp: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MiioKey:
    """Токен устройства и выведенные из него ключ/IV."""

    token: bytes
    key: bytes
    iv: bytes

    @classmethod
    def from_hex(cls, token_hex: str) -> MiioKey:
        token = bytes.fromhex(token_hex)
        if len(token) != TOKEN_SIZE:
            raise ValueError("токен miIO — 32 hex-символа")
        key = hashlib.md5(token).digest()  # md5 задан протоколом
        iv = hashlib.md5(key + token).digest()
        return cls(token=token, key=key, iv=iv)

    def _cipher(self) -> Cipher[modes.CBC]:
        return Cipher(algorithms.AES(self.key), modes.CBC(self.iv))

    def encrypt(self, plain: bytes) -> bytes:
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = self._cipher().encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    def decrypt(self, data: bytes) -> bytes:
        if not data or len(data) % 16:
            raise MiioProtocolError("длина шифротекста не кратна блоку AES")
        decryptor = self._cipher().decryptor()
        padded = decryptor.update(data) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        try:
            return unpadder.update(padded) + unpadder.finalize()
        except ValueError as exc:
            raise MiioProtocolError("битый PKCS#7 — неверный токен?") from exc


def _checksum(key: MiioKey, header: bytes, encrypted: bytes) -> bytes:
    return hashlib.md5(header[:16] + key.token + encrypted).digest()


def _parse_header(data: bytes) -> tuple[int, int]:
    if len(data) < HEADER_SIZE:
        raise MiioProtocolError(f"кадр короче заголовка: {len(data)} байт")
    magic, length, _unknown, did, stamp = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise MiioProtocolError(f"чужой magic: {magic:#06x}")
    if length != len(data):
        raise MiioProtocolError(f"длина в заголовке {length} != {len(data)}")
    return did, stamp


def parse_hello(data: bytes) -> HelloReply:
    """Ответ на hello → did и stamp устройства."""
    did, stamp = _parse_header(data)
    if len(data) != HEADER_SIZE:
        raise MiioProtocolError("ответ на hello не должен нести тело")
    return HelloReply(did=did, stamp=stamp)


def encode_payload(
    message_id: int, method: str, params: list[Any] | dict[str, Any]
) -> bytes:
    """Тело запроса: компактный JSON (устройства режут длинные кадры)."""
    body = {"id": message_id, "method": method, "params": params}
    return json.dumps(body, separators=(",", ":")).encode()


def encode_request(key: MiioKey, *, did: int, stamp: int, plain: bytes) -> bytes:
    """Кадр запроса с телом ``plain`` (готовый JSON)."""
    encrypted = key.encrypt(plain)
    header = _HEADER.pack(MAGIC, HEADER_SIZE + len(encrypted), 0, did, stamp)
    return header + _checksum(key, header, encrypted) + encrypted


def decode_packet(key: MiioKey, data: bytes) -> Packet:
    """Кадр устройства → тело JSON; контрольная сумма проверяется."""
    did, stamp = _parse_header(data)
    encrypted = data[HEADER_SIZE:]
    if not encrypted:
        raise MiioProtocolError("кадр без тела")
    if _checksum(key, data, encrypted) != data[16:HEADER_SIZE]:
        raise MiioProtocolError("контрольная сумма не сходится — неверный токен?")
    plain = key.decrypt(encrypted).rstrip(b"\x00")
    try:
        payload = json.loads(plain)
    except ValueError as exc:
        raise MiioProtocolError("тело кадра — не JSON") from exc
    if not isinstance(payload, dict):
        raise MiioProtocolError("тело кадра — не объект")
    return Packet(did=did, stamp=stamp, payload=payload)
