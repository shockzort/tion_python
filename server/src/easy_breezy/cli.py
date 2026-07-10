"""CLI ``breezy`` — диагностика и управление бризерами без UI.

Работает напрямую по MAC-адресу (реестр устройств появится в Фазе 2).
Используется в hardware-смоуках фаз 1/4/6.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Annotated

import typer

from easy_breezy import __version__
from easy_breezy.ble.driver import S4Driver
from easy_breezy.ble.protocol.s4 import GATT_NOTIFY, GATT_WRITE, Mode, S4State
from easy_breezy.ble.scanner import scan as ble_scan
from easy_breezy.ble.supervisor import ConnectionState, DeviceSupervisor
from easy_breezy.ble.transport import BleakTransport, TransportError
from easy_breezy.logging import setup_logging

app = typer.Typer(help="Easy Breezy — управление бризерами Tion", no_args_is_help=True)

MacArg = Annotated[
    str, typer.Argument(help="MAC-адрес бризера, например AA:BB:CC:DD:EE:FF")
]


def _make_transport(mac: str) -> BleakTransport:
    return BleakTransport(mac, notify_uuid=GATT_NOTIFY, write_uuid=GATT_WRITE)


def _fmt_bool(value: bool) -> str:
    return "вкл" if value else "выкл"


def _print_state(state: S4State) -> None:
    mode = "приток" if state.mode is Mode.OUTSIDE else "рециркуляция"
    typer.echo(
        f"Питание: {_fmt_bool(state.power)} | Скорость: {state.fan_speed}/6 | "
        f"Нагрев: {_fmt_bool(state.heater)} (цель {state.heater_temp}°C) | "
        f"Режим: {mode}"
    )
    typer.echo(
        f"Воздух: вход {state.in_temp}°C → после бризера {state.out_temp}°C | "
        f"Фильтр: {state.filter_remain_days:.0f} дн | "
        f"Звук: {_fmt_bool(state.sound)} | Подсветка: {_fmt_bool(state.light)}"
    )


@app.callback()
def _init(
    version: Annotated[bool, typer.Option("--version", help="Показать версию")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="DEBUG-логи BLE")
    ] = False,
) -> None:
    setup_logging("DEBUG" if verbose else "WARNING")
    if version:
        typer.echo(f"breezy {__version__}")
        raise typer.Exit()


@app.command()
def scan(
    duration: Annotated[float, typer.Option(help="Длительность скана, сек")] = 15.0,
) -> None:
    """Найти бризеры Tion в эфире."""

    async def run() -> None:
        typer.echo(f"Сканирую эфир {duration:.0f} с…")
        found = await ble_scan(duration)
        if not found:
            typer.echo("Бризеры не найдены. Устройство включено и рядом?")
            raise typer.Exit(1)
        for item in found:
            hint = f" [{item.model_hint}]" if item.model_hint else ""
            typer.echo(f"{item.address}  RSSI {item.rssi:>4}  {item.name}{hint}")

    asyncio.run(run())


@app.command()
def state(mac: MacArg) -> None:
    """Показать текущее состояние бризера."""

    async def run() -> None:
        async with S4Driver(_make_transport(mac)) as driver:
            _print_state(await driver.get_state())

    asyncio.run(run())


@app.command(name="set")
def set_params(
    mac: MacArg,
    power: Annotated[
        bool | None, typer.Option("--power/--no-power", help="Питание")
    ] = None,
    fan: Annotated[int | None, typer.Option(min=1, max=6, help="Скорость 1–6")] = None,
    heater: Annotated[
        bool | None, typer.Option("--heater/--no-heater", help="Нагрев")
    ] = None,
    temp: Annotated[
        int | None, typer.Option(min=0, max=30, help="Целевая температура °C")
    ] = None,
    mode: Annotated[
        Mode | None, typer.Option(help="Режим: outside | recirculation")
    ] = None,
    sound: Annotated[
        bool | None, typer.Option("--sound/--no-sound", help="Звук")
    ] = None,
    light: Annotated[
        bool | None, typer.Option("--light/--no-light", help="Подсветка")
    ] = None,
) -> None:
    """Изменить параметры (read-modify-write: неуказанные — как на устройстве)."""
    changes = {
        key: value
        for key, value in {
            "power": power,
            "fan_speed": fan,
            "heater": heater,
            "heater_temp": temp,
            "mode": mode,
            "sound": sound,
            "light": light,
        }.items()
        if value is not None
    }
    if not changes:
        typer.echo("Нечего менять: укажите хотя бы один параметр (--help).")
        raise typer.Exit(1)

    async def run() -> None:
        async with S4Driver(_make_transport(mac)) as driver:
            current = await driver.get_state()
            desired = dataclasses.replace(current, **changes)  # type: ignore[arg-type]
            confirmed = await driver.set_state(desired)
            typer.echo("Применено. Состояние устройства:")
            _print_state(confirmed)

    asyncio.run(run())


@app.command()
def pair(
    mac: MacArg,
    wait: Annotated[
        int, typer.Option(help="Секунд на перевод бризера в режим сопряжения")
    ] = 0,
) -> None:
    """Сопрячь бризер (устройство должно быть в режиме сопряжения)."""

    async def run() -> None:
        if wait > 0:
            typer.echo(f"Переведите бризер в режим сопряжения — жду {wait} с…")
            for remaining in range(wait, 0, -5):
                typer.echo(f"  подключение через {remaining} с")
                await asyncio.sleep(min(5, remaining))

        typer.echo("Подключаюсь… (бризер должен быть в режиме сопряжения)")
        transport: BleakTransport | None = None
        for attempt in range(1, 4):
            candidate = _make_transport(mac)
            try:
                await candidate.connect()
                transport = candidate
                break
            except TransportError as exc:
                typer.echo(f"  попытка {attempt}/3 не удалась: {exc}")
        if transport is None:
            typer.echo(
                "Соединение не установлено. Бризер точно вошёл в режим "
                "сопряжения (мигание/сигнал)?"
            )
            raise typer.Exit(1)

        try:
            await transport.pair()
        except TransportError:
            await transport.disconnect()
            raise
        typer.echo("Сопряжение выполнено. Проверяю связь…")
        async with S4Driver(transport) as driver:  # транспорт уже подключён
            _print_state(await driver.get_state())

    asyncio.run(run())


@app.command()
def unpair(mac: MacArg) -> None:
    """Удалить сопряжение (bond) с бризером."""

    async def run() -> None:
        await _make_transport(mac).unpair()
        typer.echo("Сопряжение удалено.")

    asyncio.run(run())


@app.command()
def monitor(
    mac: MacArg,
    interval: Annotated[float, typer.Option(help="Период опроса, сек")] = 30.0,
) -> None:
    """Следить за устройством: состояния, разрывы, переподключения (Ctrl+C — выход)."""

    def on_state(state: S4State) -> None:
        _print_state(state)
        typer.echo("—")

    def on_connection(state: ConnectionState) -> None:
        labels = {
            ConnectionState.CONNECTING: "подключение…",
            ConnectionState.ONLINE: "на связи",
            ConnectionState.DISCONNECTED: "нет связи",
        }
        typer.echo(f"[{labels[state]}]")

    async def run() -> None:
        supervisor = DeviceSupervisor(
            lambda: _make_transport(mac),
            poll_interval=interval,
            on_state=on_state,
            on_connection=on_connection,
        )
        supervisor.start()
        try:
            await asyncio.Event().wait()  # до Ctrl+C
        finally:
            await supervisor.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("Остановлено.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
