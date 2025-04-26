# Конвенции разработки системы управления бризерами Tion

## 0. Общие сведения

В проекте должны быть реализованы идеи из слоистой архитектуры и DDD.

### Domain

Каждый домен представлен в отдельных пакетах в корне проекта. Например, `device_manager`, `operator`, `scenarist`.

Домен содержит в себе:

1. Доменные сущности (например, `Device`, `Scenario` и т.д.).
2. Доменные ошибки / исключения.
3. Интерфейсы хранилищ (репозитории) представленные как абстрактные классы. Например, `IDeviceStorageDBI`.
4. Функции / методы реализующие доменную логику.

### Usecase

1. На этом слое находится бизнес-логика. Она определяет функциональность приложения.
2. Usecase используют один и более домен для реализации бизнес-логики.
3. Usecase не может вызывать другой usecase.
4. Usecase находятся в поддиректориях директории usecase.
5. Usecase группируются по логическому смыслу.
6. Внутри каждой директории могут находиться один и более файлов с имплементацией usecase. Один файл -- один usecase.
7. Каждый файл должен отражать семантику usecase.
8. Usecase внутри одной директории объединяются в модуль. В `__init__.py` должен быть представлен конструктор usecases.

### Adapters

Различные имплементации доменных интерфейсов (например, хранилищ) также находятся в корне проекте и имеют соответствующие названия.

### API

Сервис реализует HTTP API представленные в директории api:

* api.yaml -- публичный API для интеграции с приложениями и сторонними сервисами
* private_api.yam -- приватный API для выполнения сервисных задач

### API implementation

Имплементации API находятся в директории api_impl.

### Postgres

1. Мы не используем ORM для работы с Postgres.
2. Имплементации должны соответствовать доменным интерфейсам хранилищ.
3. В частности мы не прокидываем соединение в интерфейс БД, т.к. это противоречит идеям слоистой архитектуры.

## 1. Стиль кода и линтинг

### 1.1. Python

* **Форматирование**:
  * Использование `black` и `isort` для автоматического форматирования.
  * Пример настройки pre-commit:

    ```yaml
    repos:
      - repo: https://github.com/psf/black
        rev: 23.3.0
      - repo: https://github.com/PyCQA/isort
        rev: 5.12.0
    ```

* **Линтинг**:
  * `flake8` с плагинами
    * `flake8-bugbear` (потенциальные ошибки)
    * `flake8-docstrings` (проверка документации)
  * Статическая типизация через `mypy`.

    ```python
    # Пример аннотаций типов
    def set_speed(device: TionDevice, speed: int) -> None: ...
    ```

### 1.2. Именование

* `snake_case` для переменных/функций.
* `CamelCase` для классов.
* `UPPER_SNAKE_CASE` для констант.
* Исключения: Суффикс Error (например, `BluetoothConnectionError`).

## 2. Тестирование

* **Unit-тесты**:

  * Покрытие > 80% (`pytest-cov`).
  * Мокирование внешних вызовов (Bluetooth, API) с помощью `pytest-mock`.

    ```python
    def test_ble_connection(mocker):
        mock_ble = mocker.patch("tion.BleakClient.connect")
        assert connect_to_device() == Status.OK
    ```

* **Интеграционные тесты**:
  * Тестирование сценариев «от команды Алисы до изменения состояния бризера».
  * Использование Docker-контейнеров с эмуляторами BLE-устройств.

## 3. Документация

* Google-style docstrings для всех публичных методов.

```python
def get_co2_level() -> int:
    """Возвращает текущий уровень CO₂ из кеша.

    Returns:
        int: Значение в ppm (0-5000).
    """
```

* Описание в формате OpenAPI 3.0 (Swagger).
* Генерация документации через `FastAPI` или `flasgger`.

## 4. Git-конвенции

**Структура коммитов**:

[тип](<ID задачи или область>): <описание>
Пример: [feat](ble): Добавлено автоматическое переподключение

* Типы коммитов:
  * feat: Новая функциональность
  * fix: Исправление ошибок
  * improvement: Улучшения в проекте не касающиеся нового функционала
  * docs: Изменения в документации
  * refactor: Рефакторинг без изменения функционала
  * test: Тесты

* Ветвление:
  * master — стабильная версия.
  * Функциональные ветки: feature/ble-retry-logic, fix/web-auth.

## 5. Контейнеризация и CI/CD

* Docker: Мультистейд-сборка для уменьшения образа.

    ```dockerfile
    FROM python:3.10-slim as builder
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install --user -r requirements.txt

    FROM python:3.10-slim
    COPY --from=builder /root/.local /root/.local
    COPY . .
    CMD ["python", "main.py"]
    ```

## 6. Безопасность

* Секреты:
  * Хранить в .env (в .gitignore).
  * Использовать python-dotenv для загрузки.

  ```python
    from dotenv import load_dotenv
    load_dotenv()
  ```

* Зависимости:
  * Регулярное обновление (pip-audit, dependabot).
  * Фиксация версий в requirements.txt с hash-суммами.

## 7. Работа с Bluetooth

* Асинхронность:
  * Использовать asyncio и Bleak для неблокирующих операций.

    ```python
    async def connect(device: BLEDevice) -> None:
        async with BleakClient(device) as client:
            await client.write_gatt_char(uuid, data)
    ```

* Обработка ошибок:
  * Экспоненциальная задержка при повторных подключениях.
  * Логирование всех BLE-событий в отдельный файл.

## 8. Веб-интерфейс

* Доступность:
  * Соответствие WCAG 2.1 (контраст, ARIA-роли).
  * Тестирование через axe-core.

* Шаблоны:
  * Использование Jinja2 с компонентным подходом.
  * Изоляция CSS через BEM-нотацию.

    ```html
    <div class="device-card">
    <button class="device-card__btn--primary">Включить</button>
    </div>
    ```

## 9. Логирование

* Формат:
  * JSON-логи для интеграции с ELK/Graylog.
  * Логирование через structlog.

    ```python
    import structlog
    logger = structlog.get_logger()
    logger.info("device_connected", device_id="Tion-123")
    ```

* Уровни:
    DEBUG — детализация BLE-операций.
    INFO — информационные сообщения.
    WARNING — предупреждения.
    ERROR — критические сбои (отправка в Sentry).
