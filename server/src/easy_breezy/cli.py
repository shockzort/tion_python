"""CLI ``breezy`` — диагностика и управление бризерами без UI.

BLE-команды работают напрямую по MAC-адресу (используются в
hardware-смоуках фаз 1/4/6). Подкоманды ``user`` управляют
пользователями веб-интерфейса напрямую через БД (``EB_DATA_DIR`` /
``EB_DATABASE_URL``) — сервер останавливать не нужно: сессии
проверяются по БД на каждом запросе.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import time
from typing import Annotated

import typer
from sqlalchemy.exc import IntegrityError

from easy_breezy import __version__
from easy_breezy.auth import hash_password
from easy_breezy.ble.driver import S4Driver
from easy_breezy.ble.protocol.s4 import GATT_NOTIFY, GATT_WRITE, Mode, S4State
from easy_breezy.ble.scanner import scan as ble_scan
from easy_breezy.ble.supervisor import ConnectionState, DeviceSupervisor
from easy_breezy.ble.transport import BleakTransport, TransportError
from easy_breezy.config import Settings
from easy_breezy.logging import setup_logging
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SessionRepo, UserRepo

app = typer.Typer(help="Easy Breezy — управление бризерами Tion", no_args_is_help=True)

user_app = typer.Typer(
    help="Пользователи веб-интерфейса (напрямую через БД)", no_args_is_help=True
)
app.add_typer(user_app, name="user")

PASSWORD_MIN_LENGTH = 8
"""Минимальная длина пароля — как в POST /api/auth/setup."""

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

        typer.echo("Сопрягаюсь… (бризер должен быть в режиме сопряжения)")
        transport: BleakTransport | None = None
        for attempt in range(1, 4):
            candidate = _make_transport(mac)
            try:
                await candidate.pair()  # SMP до GATT — спека §1.7
                transport = candidate
                break
            except TransportError as exc:
                typer.echo(f"  попытка {attempt}/3 не удалась: {exc}")
        if transport is None:
            typer.echo(
                "Сопряжение не выполнено. Бризер точно вошёл в режим "
                "сопряжения (кнопка ~5 с)? Если индикация выключена — "
                "просто подержи и отпусти."
            )
            raise typer.Exit(1)

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


# --- пользователи ----------------------------------------------------------


UsernameArg = Annotated[str, typer.Argument(help="Имя пользователя")]


def _prompt_password() -> str:
    password: str = typer.prompt("Пароль", hide_input=True, confirmation_prompt=True)
    if len(password) < PASSWORD_MIN_LENGTH:
        typer.echo(f"Пароль короче {PASSWORD_MIN_LENGTH} символов.")
        raise typer.Exit(1)
    return password


@user_app.command(name="add")
def user_add(username: UsernameArg) -> None:
    """Создать пользователя (пароль спрашивается интерактивно)."""
    password_hash = hash_password(_prompt_password())

    async def run() -> None:
        db = _open_db()
        try:
            await db.migrate()
            async with db.session() as session:
                await UserRepo(session).create(
                    username=username,
                    password_hash=password_hash,
                    created_at=int(time.time()),
                )
        except IntegrityError:
            typer.echo(f"Пользователь «{username}» уже существует.")
            raise typer.Exit(1) from None
        finally:
            await db.dispose()
        typer.echo(f"Пользователь «{username}» создан.")

    asyncio.run(run())


@user_app.command(name="list")
def user_list() -> None:
    """Показать пользователей."""

    async def run() -> None:
        db = _open_db()
        try:
            await db.migrate()
            async with db.session() as session:
                users = await UserRepo(session).list_all()
        finally:
            await db.dispose()
        if not users:
            typer.echo("Пользователей нет (сервер напечатает setup-токен).")
            return
        for user in users:
            created = datetime.datetime.fromtimestamp(
                user.created_at, tz=datetime.UTC
            ).strftime("%Y-%m-%d")
            typer.echo(f"{user.id:>3}  {user.username}  (создан {created})")

    asyncio.run(run())


@user_app.command(name="passwd")
def user_passwd(username: UsernameArg) -> None:
    """Сменить пароль (все сессии пользователя сбрасываются)."""
    password_hash = hash_password(_prompt_password())

    async def run() -> None:
        db = _open_db()
        try:
            await db.migrate()
            async with db.session() as session:
                user = await UserRepo(session).get_by_username(username)
                if user is None:
                    typer.echo(f"Пользователь «{username}» не найден.")
                    raise typer.Exit(1)
                user.password_hash = password_hash
                dropped = await SessionRepo(session).delete_for_user(user.id)
        finally:
            await db.dispose()
        typer.echo(f"Пароль обновлён, сессий сброшено: {dropped}.")

    asyncio.run(run())


@user_app.command(name="remove")
def user_remove(username: UsernameArg) -> None:
    """Удалить пользователя (сессии и api-токены уходят каскадом)."""

    async def run() -> None:
        db = _open_db()
        try:
            await db.migrate()
            async with db.session() as session:
                repo = UserRepo(session)
                user = await repo.get_by_username(username)
                if user is None:
                    typer.echo(f"Пользователь «{username}» не найден.")
                    raise typer.Exit(1)
                if await repo.count() == 1:
                    typer.echo(
                        "Это последний пользователь: после удаления сервер "
                        "напечатает setup-токен при следующем старте."
                    )
                if not typer.confirm(f"Удалить «{username}»?"):
                    raise typer.Exit(0)
                await repo.delete(user)
        finally:
            await db.dispose()
        typer.echo(f"Пользователь «{username}» удалён.")

    asyncio.run(run())


def _open_db() -> Database:
    return Database(Settings().resolved_database_url())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
