"""Фейковое miIO-устройство для тестов транспорта и сервиса приборов (без сети)."""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass, field
from typing import Any

from easy_breezy.integrations.xiaomi import ha2
from easy_breezy.integrations.xiaomi.miio import (
    HEADER_SIZE,
    HELLO,
    MAGIC,
    MiioKey,
    decode_packet,
    encode_request,
)
from easy_breezy.integrations.xiaomi.transport import MiioTransport

TEST_TOKEN = "00112233445566778899aabbccddeeff"
TEST_DID = 2232120756

HA2_VALUES: dict[tuple[int, int], Any] = {
    (2, 1): True,
    (2, 2): 0,
    (2, 3): 3,
    (2, 6): 55,
    (2, 7): 75,
    (2, 14): 0,
    (3, 1): 55,
    (3, 3): 0,
    (3, 4): 3,
    (3, 6): 1,
    (3, 7): 24.0,
    (4, 1): 100,
    (15, 1): 100,
    (5, 1): True,
    (6, 1): False,
    (7, 1): False,
    (9, 5): 1,
    (9, 11): 0,
    (11, 3): 0,
    (11, 4): 3,
}
"""Значения с устройства владельца (2026-10-27) по карте ``ha2.PROPS``."""
assert set(HA2_VALUES) == set(ha2.PROPS.values())


@dataclass
class FakeMiioDevice:
    key: MiioKey = field(default_factory=lambda: MiioKey.from_hex(TEST_TOKEN))
    did: int = TEST_DID
    stamp: int = 1536
    values: dict[tuple[int, int], Any] = field(default_factory=lambda: dict(HA2_VALUES))
    drop: int = 0
    """Сколько следующих запросов (не hello) проглотить без ответа."""
    max_props: int = 16
    """Больше свойств в запросе — молчание (как у ha2 на 20)."""
    reject: set[tuple[int, int]] = field(default_factory=set)
    """Свойства, запись которых отвечает code=-4004."""
    requests: list[dict[str, Any]] = field(default_factory=list)
    hellos: int = 0

    def handle(self, data: bytes) -> bytes | None:
        if data == HELLO:
            self.hellos += 1
            return struct.pack(
                ">HHIII", MAGIC, HEADER_SIZE, 0, self.did, self.stamp
            ) + (b"\xff" * 16)
        payload = decode_packet(self.key, data).payload
        self.requests.append(payload)
        if self.drop > 0:
            self.drop -= 1
            return None
        result = self._dispatch(payload["method"], payload["params"])
        if result is None:
            return None
        body = json.dumps({"id": payload["id"], **result}).encode()
        return encode_request(self.key, did=self.did, stamp=self.stamp, plain=body)

    def _dispatch(self, method: str, params: list[Any]) -> dict[str, Any] | None:
        if method == "get_properties":
            if len(params) > self.max_props:
                return None
            return {"result": [self._get(item) for item in params]}
        if method == "set_properties":
            return {"result": [self._set(item) for item in params]}
        return {"error": {"code": -9999, "message": "user ack timeout"}}

    def _get(self, item: dict[str, Any]) -> dict[str, Any]:
        pair = (item["siid"], item["piid"])
        if pair not in self.values:
            return {**item, "code": -4003}
        return {**item, "code": 0, "value": self.values[pair]}

    def _set(self, item: dict[str, Any]) -> dict[str, Any]:
        pair = (item["siid"], item["piid"])
        if pair in self.reject:
            return {"did": item["did"], "siid": pair[0], "piid": pair[1], "code": -4004}
        self.values[pair] = item["value"]
        return {"did": item["did"], "siid": pair[0], "piid": pair[1], "code": 0}


class FakeEndpoint(asyncio.DatagramTransport):
    """UDP-«сокет», который отвечает голосом ``FakeMiioDevice``."""

    def __init__(
        self, device: FakeMiioDevice, protocol: asyncio.DatagramProtocol
    ) -> None:
        super().__init__()
        self._device = device
        self._protocol = protocol
        self.closed = False

    def sendto(self, data: bytes, addr: Any = None) -> None:  # type: ignore[override]
        reply = self._device.handle(bytes(data))
        if reply is not None:
            asyncio.get_running_loop().call_soon(
                self._protocol.datagram_received, reply, ("fake", 54321)
            )

    def close(self) -> None:
        self.closed = True


def fake_transport(device: FakeMiioDevice, *, timeout: float = 0.05) -> MiioTransport:
    async def factory(protocol: asyncio.DatagramProtocol) -> asyncio.BaseTransport:
        return FakeEndpoint(device, protocol)

    return MiioTransport(
        "fake",
        device.key,
        timeout=timeout,
        endpoint_factory=factory,
        message_id_seed=100,
    )
