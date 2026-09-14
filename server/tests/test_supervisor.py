"""Супервизор: backoff-последовательность, реконнект, деградация опроса.

Сон инжектируется — тесты не ждут реального времени (кроме коротких
response_timeout в сценариях деградации).
"""

from __future__ import annotations

import asyncio

from easy_breezy.ble.fake import FakeS4Device, FakeTransport
from easy_breezy.ble.protocol.s4 import OPCODE_REQUEST_PARAMS
from easy_breezy.ble.supervisor import ConnectionState, DeviceSupervisor

POLL_INTERVAL = 1000.0
"""Опрос в тестах не наступает сам — задержка отличима от backoff-пауз."""


class SleepRecorder:
    """Инжектируемый сон: пишет задержки, возвращается мгновенно."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


class GatedSleeper(SleepRecorder):
    """Тот же сон, но паузу опроса держит вечно — сессия не успевает опросить."""

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if delay == POLL_INTERVAL:
            await asyncio.Event().wait()
        await asyncio.sleep(0)


def backoffs(sleeper: SleepRecorder) -> list[float]:
    """Только паузы переподключения: сон опроса идёт через тот же инжект."""
    return [delay for delay in sleeper.delays if delay != POLL_INTERVAL]


async def wait_for_polls(device: FakeS4Device, count: int) -> None:
    """Ждёт ``count`` запросов состояния — первый из них делает сама сессия."""
    async with asyncio.timeout(2.0):
        while (
            sum(
                frame.opcode == OPCODE_REQUEST_PARAMS
                for frame in device.received_frames
            )
            < count
        ):
            await asyncio.sleep(0)


async def _wait_for_state(
    supervisor: DeviceSupervisor, state: ConnectionState, timeout: float = 2.0
) -> None:
    async with asyncio.timeout(timeout):
        while supervisor.connection_state is not state:
            await asyncio.sleep(0)


def make_supervisor(
    transport: FakeTransport, **kwargs: object
) -> tuple[DeviceSupervisor, SleepRecorder, list[ConnectionState]]:
    sleeper = SleepRecorder()
    transitions: list[ConnectionState] = []
    supervisor = DeviceSupervisor(
        lambda: transport,
        sleep=sleeper,
        jitter=lambda: 0.0,
        backoff_initial=1.0,
        backoff_max=60.0,
        poll_interval=POLL_INTERVAL,
        response_timeout=0.2,
        on_connection=transitions.append,
        **kwargs,  # type: ignore[arg-type]
    )
    return supervisor, sleeper, transitions


async def test_backoff_sequence_until_connected() -> None:
    transport = FakeTransport(FakeS4Device())
    transport.connect_failures = 3
    supervisor, sleeper, _ = make_supervisor(transport)

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
    finally:
        await supervisor.stop()

    # экспоненциальный backoff: 1 → 2 → 4 (джиттер отключён)
    assert sleeper.delays[:3] == [1.0, 2.0, 4.0]
    assert transport.connect_count == 4


async def test_reconnects_after_connection_loss() -> None:
    transport = FakeTransport(FakeS4Device())
    supervisor, _, transitions = make_supervisor(transport)

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        transport.simulate_connection_loss()
        await _wait_for_state(supervisor, ConnectionState.DISCONNECTED)
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
    finally:
        await supervisor.stop()

    assert transitions[:5] == [
        ConnectionState.CONNECTING,
        ConnectionState.ONLINE,
        ConnectionState.DISCONNECTED,
        ConnectionState.CONNECTING,
        ConnectionState.ONLINE,
    ]
    assert transport.connect_count == 2


async def test_state_updates_reach_callback() -> None:
    device = FakeS4Device()
    transport = FakeTransport(device)
    received = []
    sleeper = SleepRecorder()
    supervisor = DeviceSupervisor(
        lambda: transport,
        sleep=sleeper,
        jitter=lambda: 0.0,
        poll_interval=1000.0,
        response_timeout=0.2,
        on_state=received.append,
    )

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        transport.push_state()  # незапрошенный push устройства
        async with asyncio.timeout(2):
            while len(received) < 2:
                await asyncio.sleep(0)
    finally:
        await supervisor.stop()

    assert received[0] == device.state  # начальное состояние сессии
    assert supervisor.last_state == device.state


async def test_poll_degradation_triggers_reconnect() -> None:
    """3 подряд неудачных опроса → пересоздание соединения (план §7)."""
    device = FakeS4Device()
    transport = FakeTransport(device)
    supervisor, _, transitions = make_supervisor(transport)

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        device.drop_responses = 10**6  # устройство перестало отвечать
        await _wait_for_state(supervisor, ConnectionState.DISCONNECTED, timeout=5.0)
    finally:
        await supervisor.stop()

    assert (
        ConnectionState.DISCONNECTED
        in transitions[transitions.index(ConnectionState.ONLINE) :]
    )


async def test_survives_driver_error_in_session() -> None:
    """DriverError в сессии не убивает супервизор (полевой факт стенда MVP).

    Обрыв во время первого чтения даёт DriverError («соединение разорвано»
    поверх сбоя записи) — раньше он выпадал из except-списка run() и задача
    умирала молча, устройство навсегда зависало в connecting.
    """
    transport = FakeTransport(FakeS4Device())
    transport.fail_writes = True  # connect проходит, первый REQUEST падает
    supervisor, sleeper, _ = make_supervisor(transport)

    supervisor.start()
    try:
        # несколько честных ретраев с backoff — задача жива и логирует
        async with asyncio.timeout(2):
            while transport.connect_count < 3:
                await asyncio.sleep(0)
        assert sleeper.delays[:2] == [1.0, 2.0]

        transport.fail_writes = False  # устройство «починилось»
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
    finally:
        await supervisor.stop()


async def test_scan_gate_blocks_connection_attempts() -> None:
    gate = asyncio.Lock()
    transport = FakeTransport(FakeS4Device())
    supervisor, _, _ = make_supervisor(transport, scan_gate=gate)

    await gate.acquire()
    supervisor.start()
    try:
        await asyncio.sleep(0.05)
        assert transport.connect_count == 0  # гейт держит подключение

        gate.release()
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        assert not gate.locked()  # после подключения гейт свободен
    finally:
        await supervisor.stop()


async def test_backoff_resets_after_healthy_session() -> None:
    """Прожившая сессия обнуляет паузу — разрыв стоит секунду, а не потолок.

    Полевой факт NUC: ``_session()`` не возвращается нормально (опрос всегда
    заканчивается исключением), поэтому прежний сброс «по отсутствию
    исключения» был мёртвым кодом. За 17 дней все 2780 пауз переподключения
    легли в 60–75 с: каждый разрыв стоил минуту простоя даже после суток
    непрерывного онлайна.
    """
    device = FakeS4Device()
    transport = FakeTransport(device)
    transport.connect_failures = 3
    supervisor, sleeper, _ = make_supervisor(transport)

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        assert backoffs(sleeper) == [1.0, 2.0, 4.0]  # пауза успела вырасти
        await wait_for_polls(device, 2)  # сессия пережила опрос — здорова
        transport.simulate_connection_loss()
        await _wait_for_state(supervisor, ConnectionState.DISCONNECTED)
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
    finally:
        await supervisor.stop()

    assert backoffs(sleeper) == [1.0, 2.0, 4.0, 1.0]


async def test_backoff_keeps_growing_on_flapping_session() -> None:
    """Сессия, рассыпавшаяся до первого опроса, счётчик не обнуляет.

    Иначе флапающий бризер (подключился — и сразу отвалился) заставил бы
    супервизор долбить адаптер без пауз.
    """
    device = FakeS4Device()
    transport = FakeTransport(device)
    transport.connect_failures = 3
    sleeper = GatedSleeper()
    supervisor = DeviceSupervisor(
        lambda: transport,
        sleep=sleeper,
        jitter=lambda: 0.0,
        backoff_initial=1.0,
        backoff_max=60.0,
        poll_interval=POLL_INTERVAL,
        response_timeout=0.2,
    )

    supervisor.start()
    try:
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        assert backoffs(sleeper) == [1.0, 2.0, 4.0]
        transport.simulate_connection_loss()  # опросить не успели
        await _wait_for_state(supervisor, ConnectionState.DISCONNECTED)
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
    finally:
        await supervisor.stop()

    assert backoffs(sleeper) == [1.0, 2.0, 4.0, 8.0]


async def test_online_event_tracks_driver_availability() -> None:
    """``online`` взведено ровно тогда, когда драйвер годен для команд (шина)."""
    transport = FakeTransport(FakeS4Device())
    supervisor, _, _ = make_supervisor(transport)

    supervisor.start()
    try:
        assert not supervisor.online.is_set()
        await _wait_for_state(supervisor, ConnectionState.ONLINE)
        assert supervisor.online.is_set()
        assert supervisor.driver is not None

        transport.simulate_connection_loss()
        await _wait_for_state(supervisor, ConnectionState.DISCONNECTED)
        assert not supervisor.online.is_set()
    finally:
        await supervisor.stop()
    assert not supervisor.online.is_set()
