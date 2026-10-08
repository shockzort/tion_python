# Исследование Bluetooth: цепочка кода, восстановление и ретраи

Дата: 2026-10-08. Проверен HEAD `bc04c3cae494acaab1c78cf6ddc1a5fd06623b03` (0.3.0).
Исследование read-only: исходники и окружение не менялись. Локальные проверки
использовали mock/FakeTransport, без обращений к радио. Этот отчёт не устанавливает
причину отключения детской: для причинной связи нужны журналы и HCI-события эпизода.

## Устройство цепочки

```text
lifespan / AppContainer.startup
  → DeviceRegistry.start → DeviceSupervisor на каждый paired MAC
    → общий ScanCoordinator → S4Driver.start
      → BleakTransport.find_device_by_address
      → BleakClient(BLEDevice).connect → start_notify
    → начальный GET → ONLINE → периодический GET
    → ошибка/разрыв → close → новый transport/driver → backoff → повтор

REST / automation → CommandBus: очередь на устройство
  → ждать ONLINE → merge delta → S4Driver.set_state
    → лок устройства → SET → ожидание STATE → контрольный GET

notifications → очередь транспорта → сборка/CRC/decode
  → waiter текущего запроса + callback реестра → cache/events/telemetry
```

Точки сборки: `server/src/easy_breezy/container.py:118–139,209–226`;
реестр: `core/registry.py:73–85,157–183`; жизненный цикл: `ble/supervisor.py:95–179`.
Транспорт реального сервера создаётся заново на каждую сессию, сам повторов SET не
делает. MagicAir здесь — облачный источник показаний, а не второй BLE-клиент.
Отвязка бризеров от MagicAir устраняет один из возможных внешних центральных
контроллеров, но не исправляет ошибки локального lifecycle.

Внутри процесса уже есть полезные ограничения: `scan_gate` сериализует поиск и
подключение Tion, pairing и фоновый Qingping уступают друг другу; опрос и команды
сериализованы локом S4Driver. При подключении фоновой Qingping-сессии без
зарегистрированного датчика сканер вообще не запускается
(`integrations/qingping/client.py:202–215`).

## Таймауты и ретраи в текущем коде

| Слой | Реальная политика | Ограничение |
|---|---|---|
| Поиск Tion | 14 с в Bleak, внешний `asyncio.timeout(15)` | Каждый reconnect снова требует рекламу; нет проверки уже существующего connected-объекта BlueZ (`ble/transport.py:99–115`). |
| LE connect + GATT discovery | Bleak timeout 10 с; внешний 20 с | Эти значения заданы фабрикой по умолчанию, не настройками окружения (`transport.py:69–70,119–131`; `container.py:223–224`). |
| Подписка / disconnect | По 10 с | Ошибку disconnect только логируют (`transport.py:134–154`). |
| GATT write | 5 с на пакет, `response=False` | Это не подтверждение исполнения команды устройством (`transport.py:156–163`). SET состоит из двух пакетов. |
| Ответ драйвера | 3 с после записи | SET всегда дополняется контрольным GET (`driver.py:119–164`). |
| Опрос | Через 30 с после предыдущего цикла | 3 последовательных `DriverTimeoutError` пересоздают сессию; остальные DriverError ведут к reconnect сразу (`supervisor.py:154–179`). При молчании без callback разрыва обнаружение занимает около 99 с плюс время записи/ожидания лока. |
| Reconnect | 1 → 2 → 4 → 8 → 16 → 20 с; jitter +0…25% | Устойчивая сессия сбрасывает backoff после первого успешного периодического GET. Номинальный максимум ожидания — 25 с, плюс поиск/подключение и очередь gate (`supervisor.py:120–126,173`). |
| Обычная команда | 4 с на попытку, всего две попытки | Повтор сразу; если сессия всё ещё ONLINE, может использовать тот же проблемный драйвер. Бюджет включает ожидание driver-lock (`core/bus.py:449–482,518–524`). |
| Ожидание связи командой | Ручная до 30 с; автоматическая 180 с | Очередь устройства на время этого ожидания занята. Это ожидание отдельно от двух бюджетов по 4 с (`bus.py:446,526–571`). |
| Сброс фильтра | Одна попытка, до 15 с исполнения | Автоматического повтора SET нет; очередь обслуживания истекает через 15 с (`bus.py:349,486–516`). |
| Watchdog | Все бризеры offline 10 мин → Powered off/on; ещё 10 мин → SIGTERM | Один живой бризер полностью сбрасывает эпизод. При offline одной детской эскалации не будет (`core/watchdog.py:114–148`). |
| Qingping | Start/stop по 10 с; сессия до 60 с; ошибка → 1…20 с | Foreground Tion прерывает фон. При остановке сканера lock освобождается после `stop` (`integrations/qingping/client.py:205–253`). |

Таймауты — несколько независимых бюджетов. Особенно заметен разрыв между 4 с
командной шины и разрешёнными 3 с ожидания после SET + 3 с после GET + записью
пакетов. Например, при потерянном ответе на SET более секунды суммарного ожидания
лока/записи/GET уже исчерпывают 4 с. Команда могла примениться, но закончиться
TIMEOUT и повторным SET. Это не доказывает частоту такого поведения на живых
бризерах; нужны длительности фаз и счётчик повторов по причине.

## Подтверждённые дефекты кода

### C1. Частично успешное подключение не закрывается при ошибке start_notify

Приоритет: высокий для доступности. `ble/supervisor.py:138–144` вызывает
`driver.start()` **до** `try/finally`, который закрывает драйвер на строках 149–152.
В `ble/transport.py:125–140` успешный `connect` и неуспешный `start_notify` не
сопровождаются локальным disconnect.

Условие: LE-соединение и GATT discovery завершились, затем `start_notify`
выбросил BleakError/OSError/TimeoutError либо был отменён. Супервизор теряет ссылку
на транспорт, оставляя возможное соединение BlueZ. Следующая попытка требует
свежую рекламу того же S4; подключённый S4 может не рекламироваться. Получается
самоподдерживающееся состояние «не найден в эфире» вместо восстановления.
Это также объясняет, почему исправление должно закрывать все пути частичного
старта, а не просто сокращать backoff.

Локальный repro с mock BleakClient: `connect` выставляет connected, `start_notify`
выбрасывает BleakError; вызов `_session()` завершён TransportError:

```text
disconnect_calls=0, still_connected=True, supervisor_driver=None
```

В Bleak 3.0.2 connect имеет собственный cleanup при ошибках *внутри connect*
(`.venv/.../bleak/backends/bluezdbus/client.py:157–330`). Он уже завершён к моменту
вызова нашего `start_notify`, поэтому данный путь не закрывает. Обычный timeout
LE-connect сам по себе ещё не доказывает утечку этого типа.

Узкая правка: включить `driver.start` в область гарантированного `close` и проверить
идемпотентный cleanup транспорта; cleanup не должен перекрывать исходную ошибку.
Не удалять бонды. Тесты: connect success + notify error/timeout/cancel; попытка
после частичного старта должна находить устройство; mock проверяет ровно один
disconnect, освобождение gate и отсутствие живого listener.

### C2. Ответ с чужим request_id завершает текущий запрос

Приоритет: высокий для достоверности команд; не объяснение потери радио.
`ble/driver.py:237–245` генерирует идентификатор, но waiter его не хранит.
`driver.py:293–296` завершает waiter любым декодированным STATE_RESPONSE.
Разобранный `frame.request_id` доступен, но не проверяется.

Условие: ответ на истёкший запрос приходит после старта следующего GET; также
возможен поздний ответ на SET в момент контрольного GET. Per-device lock не
помогает, потому что старый ответ уже в пути. Старое состояние может быть
объявлено результатом нового запроса, попасть в кэш как свежее и стать основой
следующей записи.

Локальный repro: первый GET истёк; второй имеет другой id; вместо его ответа
доставлен кадр первого GET:

```text
request_ids_differ=True, device_fan=5, returned_old_fan=2
```

Граница доказательства: локальный repro проверяет принятие неверного id.
Дополнительно [пассивный полевой capture](1_timeline.md) разобран через
Reassembler/parse_frame: у **17 из 17** пар GET `3232` → STATE `3132` request_id
совпал (детская 6/6, спальня 6/6, гостиная 5/5); CRC всех 34 кадров корректен.
Для GET это подтверждает echo на трёх наших S4. SET в этом capture отсутствует,
для него остаётся отдельная проверка. `docs/protocol/tion-s4-ble.md:70–71`
ранее подтверждал echo фикстурой Lite; строки 90–92 требуют корреляцию и
одновременно приём unsolicited STATE. Нельзя просто отбрасывать любые STATE
с неизвестным id.

Узкая правка после проверки протокола: хранить expected id в waiter и завершать
его только подходящим ответом; валидные unsolicited STATE продолжать отдавать
callback/cache. Тесты: late GET → next GET, late SET → readback, unsolicited,
отмена и новый запрос с другим id.

### C3. Read-modify-write вычисляет дельту до захвата driver-lock

Приоритет: средний для целостности управления; не причина disconnect.
`core/bus.py:518–524` читает `driver.last_state` и вычисляет полное желаемое
состояние до вызова `set_state`; лок берётся внутри `ble/driver.py:128`.
Параллельный периодический GET может уже держать лок и обновить `last_state`,
пока команда ждёт. Полный SET затем вернёт неуказанные поля к старому состоянию.

Локальный repro: первоначально sound=True; устройство изменено на sound=False;
периодический GET начат с задержкой записи; одновременно отправлена дельта
только `fan_speed=4`:

```text
new_sound_seen_by_poll=False,
unrequested_sound_after_command=True,
requested_fan_after_command=4
```

Условие не требует другого BLE-клиента: изменение может прийти с панели бризера
или как корректировка прошивки. Узкая правка: атомарная операция «выбрать базу →
merge → SET/readback» под одним локом драйвера, по образцу reset_filter, без
зависимости низкого BLE-слоя от core. Тест должен синхронизировать выполняющийся
poll и команду, а не проверять только параллельные SET через одного worker.

### C4. Ошибка/отмена записи обычного SET оставляет незавершённый waiter

Приоритет: низкий; cleanup и диагностика. `driver.py:129–138` создаёт waiter и
пишет кадр до `try/finally` на строках 139–144. Ошибка write оставляет
`_state_waiter` pending. В отличие от `_request_state` и `reset_filter`, здесь нет
отмены незавершённого waiter на всех путях выхода.

Локальный repro с `FakeTransport.fail_writes=True`:

```text
waiter_retained=True, waiter_pending=True
```

Последующий disconnect может выставить исключение в future, которое уже никто
не ждёт; поздний пакет может его завершить. Следующая операция заменяет ссылку,
поэтому отдельно этот дефект не устанавливает бесконечный offline.
Узкая правка: запись и ожидание в одном try/finally, cancel pending waiter и
очистка ссылки. Тесты: ошибка и отмена на каждом пакете SET, затем новая команда
и disconnect; отсутствие unhandled Future exception.

### C5. Бюджет 4 с обрывает штатный fallback, если ответ на SET потерян

Приоритет: средний; подтверждён конфликт бюджетов, а не частота сбоев в проде.
`core/bus.py:164,449–482,518–524` допускает 4 с на SET/readback и сразу повторяет
всю операцию. `ble/driver.py:139–145` после потери SET-ответа расходует 3 с только
на ожидание, затем начинает контрольный GET. На этот GET вместе с записью и
ожиданием лока остаётся меньше секунды.

[Пассивные замеры](1_timeline.md) обычного GET гостиной дают median 1.18 с,
max 1.36 с. В модели с такой задержкой ответа GET и потерянным SET-ответом
применение команды успешно, но `_apply` завершается по внешнему timeout:

```text
elapsed_seconds=4.0, physical_fan=4,
operation_result=TimeoutError, opcodes=['3032', '3232']
```

Затем bus повторно вызывает SET на том же ONLINE driver, если supervisor ещё
не снял сессию. Дельта абсолютная, поэтому обычно повтор идемпотентен, но это
лишняя запись и возможный ложный статус TIMEOUT уже применённой команды. Этот
вывод не относится к сбросу фильтров: у него отдельные 15 с и запрет retry.
По собранному журналу за 7 дней 218 обычных команд DONE и 0 failed/timeout —
реального эпизода C5 в этом окне не установлено.

Узкое решение: сделать бюджет последовательности согласованным с подтверждённым
временем GET, явно учитывать ожидание лока; при неопределённом результате SET
сначала завершать readback, а не немедленно повторять запись. Простое увеличение
всех таймаутов не исправляет correlation и cleanup. Тест — silent SET ACK с GET
1.18 с при production timeout 3 с; verify итог без повторного SET.

## Пробелы recovery и границы гарантий

1. **Нет восстановления отдельного залипшего устройства.** Это подтверждённая
   политика watchdog, не скрытая неисправность: один ONLINE запрещает общую
   эскалацию. После C1 нужен ограниченный targeted recovery конкретного MAC:
   сначала сопоставить наш lifecycle с Device1 Connected/ServicesResolved,
   закрыть принадлежащее нам старое соединение и повторить. Не следует сбрасывать
   весь адаптер из-за одной недоступной комнаты.

2. **Gate ограничен одним процессом.** `cli.py:89–91,107,183–190,228–234` использует
   BLE напрямую; отдельный `breezy monitor`, GUI настройки Bluetooth, другой
   контейнер или ручной scan не участвуют в ScanCoordinator. В нынешнем сервере
   нет межпроцессного владельца радио. Сначала запретить конфликтующий способ
   диагностики в runbook/навыках эксплуатации или направить CLI через API;
   постоянный распределённый lock сейчас избыточен.

3. **Не все участки под общим gate имеют прикладной предел времени.**
   `ble/scanner.py:64–70` передаёт discover duration, но не ограничивает отдельно
   start/stop. В Bleak discover длительность относится к фазе ожидания между
   start/stop. `core/pairing.py:96–99` держит gate на весь pair; D-Bus connect,
   `_enable_pairable`, `_register_agent`, `_restore_adapter` не ограничены нашим
   timeout (`transport.py:193–200,221–246`). 45 с ограничивают только Device1.Pair.
   При зависшем D-Bus запросе reconnect других устройств и Qingping могут ждать
   дольше ожидаемого. Факт такого зависания в проде не установлен. Узкая мера:
   общий deadline операции и отдельный bounded cleanup; тестировать зависание
   вспомогательного D-Bus вызова, не только отсутствие ответа устройства.

4. **Watchdog reset не координируется с gate и не имеет своего общего timeout.**
   `core/watchdog.py:37–66,139` одновременно с живыми задачами reconnect меняет
   Powered всех адаптеров. Нет паузы supervisors/Qingping и проверки fresh GET
   как явного критерия завершения восстановления. Прерывание на участке между
   Powered False и True также не защищено отдельным finally. Это путь только
   общего отказа; для детской при двух ONLINE он не запускался бы по коду.

5. **Мало данных для различения radio/BlueZ/API/ownership.** Ошибки логируются
   строками; `device_found` всегда `rssi=None` (`transport.py:114`), нет времени
   ожидания gate и метрик длительности connect/notify/readback, номера поколения
   сессии, последнего успешного GET и структурированного BlueZ/HCI reason.
   Нужны минимальные фазовые поля и bounded btmon capture на повторном эпизоде,
   а не постоянный дамп BLE-пакетов.

## Что покрыто тестами и что не покрыто

Повторно выполнены существующие driver/supervisor и coordinator-тесты:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider \
  tests/test_driver.py tests/test_supervisor.py \
  tests/test_qingping.py::test_background_yields_and_cancelled_foreground_does_not_stall
18 passed, 1 warning in 1.14s
```

Они покрывают GET/SET, soft CRC, fallback, disconnect при запросе, сериализацию,
backoff, поломку опроса, gate, сброс backoff после здоровой сессии, отмену
ожидающего foreground. Выполнены пять отдельных локальных repro выше; код
тестов в репозиторий не добавлялся.

В `server/tests` нет тестов с mock `BleakClient`, `start_notify` или реальным
`BleakTransport`: частично успешный connect отсутствует в модели FakeTransport.
`test_supervisor.make_supervisor` к тому же возвращает один reusable transport,
тогда как production создаёт новый. CommandBus fixtures используют
`response_timeout=0.15` и `execute_budget=2` (`tests/conftest.py:135–154`), поэтому
не квалифицируют production-сочетание 3 с / 4 с.

Дополнительный запуск Qingping listener-тестов с DB fixture был остановлен при
зависании SQLite в sandbox; они не учитываются как PASS этого исследования.
Аппаратная квалификация: BlueZ restart, пропажа USB/HCI, partial connect/notify,
долгое отсутствие одного S4, recovery без перезапуска питания и сосуществование
трёх S4 с реальным Qingping остаётся отдельным этапом.

## Предлагаемый узкий порядок действий

1. Исправить C1 и C4 с mock-тестами частичного start/cancel/cleanup.
2. На основании подтверждённого GET echo исправить C2, отдельно проверить
   SET capture; добавить фазовую диагностику без изменения политики радио.
3. Атомарный merge C3 рассматривать отдельной небольшой правкой управления.
4. По реальным длительностям согласовать бюджет команды с SET/readback и
   обеспечить bounded pairing/scan cleanup. Не увеличивать все timeout вслепую.
5. Только если воспроизведён залипший Device1 при живом адаптере, вводить
   ограниченную per-device recovery; общий reset оставить последней ступенью.

## Приложение: воспроизводимые проверки без Bluetooth

Команда запускается из корня репозитория. Использует только mock/FakeTransport,
не создаёт БД, не подключается к D-Bus, не управляет реальными устройствами и
не изменяет файлы проекта. Ожидаемые результаты приведены выше. На исправленном
коде соответствующие проверки перестанут воспроизводить дефект.

```bash
PYTHONDONTWRITEBYTECODE=1 server/.venv/bin/python - <<'PY'
import asyncio
import dataclasses
import time
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from easy_breezy.ble.driver import DriverError, DriverTimeoutError, S4Driver
from easy_breezy.ble.fake import FakeS4Device, FakeTransport
from easy_breezy.ble.supervisor import DeviceSupervisor
from easy_breezy.ble.transport import BleakTransport, TransportError
from easy_breezy.core.bus import CommandBus
from easy_breezy.core.model import StateDelta


def isolated_bus():
    # _apply не использует БД/реестр, нужен только production budget.
    bus = CommandBus.__new__(CommandBus)
    bus._budget = 4.0
    return bus


async def partial_start():
    clients = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.is_connected = False
            self.disconnect_calls = 0
            clients.append(self)

        async def connect(self):
            self.is_connected = True

        async def start_notify(self, *args):
            raise BleakError('injected start_notify failure')

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    transport = BleakTransport(
        'AA:BB:CC:DD:EE:FF', notify_uuid='n', write_uuid='w'
    )
    found = BLEDevice('AA:BB:CC:DD:EE:FF', 'test', {})
    with patch('easy_breezy.ble.transport.BleakClient', Client), patch.object(
        transport, '_find_device', AsyncMock(return_value=found)
    ):
        supervisor = DeviceSupervisor(lambda: transport)
        try:
            await supervisor._session()
        except TransportError:
            pass
        print('C1', clients[0].disconnect_calls,
              clients[0].is_connected, supervisor.driver)
        await transport.disconnect()  # cleanup самого mock


async def late_response():
    device = FakeS4Device()
    device.drop_responses = 100
    transport = FakeTransport(device)
    driver = S4Driver(transport, response_timeout=0.02)
    async with driver:
        try:
            await driver.get_state()
        except DriverTimeoutError:
            pass
        old_id = device.received_frames[-1].request_id
        old_packets = device.state_packets(request_id=old_id)
        device.state = dataclasses.replace(device.state, fan_speed=5)
        request = asyncio.create_task(driver.get_state())
        while len(device.received_frames) < 2:
            await asyncio.sleep(0)
        for packet in old_packets:
            transport._queue.put_nowait(packet)
        result = await request
        print('C2', old_id != device.received_frames[-1].request_id,
              device.state.fan_speed, result.fan_speed)


async def poll_vs_delta():
    device = FakeS4Device()
    transport = FakeTransport(device)
    driver = S4Driver(transport)
    async with driver:
        await driver.get_state()
        device.state = dataclasses.replace(device.state, sound=False)
        transport.write_delay = 0.05
        poll = asyncio.create_task(driver.get_state())
        await asyncio.sleep(0)
        command = asyncio.create_task(
            isolated_bus()._apply(driver, StateDelta(fan_speed=4))
        )
        polled, actual = await poll, await command
        print('C3', polled.sound, actual.sound, actual.fan_speed)


async def set_write_failure():
    device = FakeS4Device()
    transport = FakeTransport(device)
    driver = S4Driver(transport)
    await driver.start()
    transport.fail_writes = True
    try:
        await driver.set_state(device.state)
    except DriverError:
        pass
    waiter = driver._state_waiter
    print('C4', waiter is not None, waiter is not None and not waiter.done())
    await driver.close()
    if waiter is not None and waiter.done() and not waiter.cancelled():
        waiter.exception()  # воспроизводитель сам потребляет orphan exception


async def timeout_budget():
    deliveries = []

    class DelayedResponse(FakeTransport):
        async def write(self, packet):
            replies = self.device.handle_packet(packet)
            if replies:
                async def deliver():
                    await asyncio.sleep(1.18)
                    for reply in replies:
                        self._queue.put_nowait(reply)
                deliveries.append(asyncio.create_task(deliver()))

    device = FakeS4Device()
    device.push_state_after_set = False
    driver = S4Driver(DelayedResponse(device), response_timeout=3)
    async with driver:
        driver.last_state = device.state
        started = time.monotonic()
        try:
            await isolated_bus()._apply(driver, StateDelta(fan_speed=4))
        except TimeoutError:
            print('C5', round(time.monotonic() - started, 2),
                  device.state.fan_speed, 'TimeoutError',
                  [f.opcode.hex() for f in device.received_frames])
    for task in deliveries:
        task.cancel()
    await asyncio.gather(*deliveries, return_exceptions=True)


async def main():
    await partial_start()
    await late_response()
    await poll_vs_delta()
    await set_write_failure()
    await timeout_budget()

asyncio.run(main())
PY
```
