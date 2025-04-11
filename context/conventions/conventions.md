# Конвенции разработки системы управления бризерами Tion

## 1. Стиль кода и линтинг

### 1.1. Python

- **Форматирование**:
  - Использование `black` и `isort` для автоматического форматирования.
  - Пример настройки pre-commit:

    ```yaml
    repos:
      - repo: https://github.com/psf/black
        rev: 23.3.0
      - repo: https://github.com/PyCQA/isort
        rev: 5.12.0
    ```

- **Линтинг**:
  - `flake8` с плагинами
    - `flake8-bugbear` (потенциальные ошибки)
    - `flake8-docstrings` (проверка документации)
  - Статическая типизация через `mypy`.

    ```python
    # Пример аннотаций типов
    def set_speed(device: TionDevice, speed: int) -> None: ...
    ```

### 1.2. Именование

- `snake_case` для переменных/функций.
- `CamelCase` для классов.
- `UPPER_SNAKE_CASE` для констант.
- Исключения: Суффикс Error (например, `BluetoothConnectionError`).

## 2. Тестирование

- **Unit-тесты**:

  - Покрытие > 80% (`pytest-cov`).
  - Мокирование внешних вызовов (Bluetooth, API) с помощью `pytest-mock`.

    ```python
    def test_ble_connection(mocker):
        mock_ble = mocker.patch("tion.BleakClient.connect")
        assert connect_to_device() == Status.OK
    ```

- **Интеграционные тесты**:
  - Тестирование сценариев «от команды Алисы до изменения состояния бризера».
  - Использование Docker-контейнеров с эмуляторами BLE-устройств.

## 3. Документация

- Google-style docstrings для всех публичных методов.

```python
def get_co2_level() -> int:
    """Возвращает текущий уровень CO₂ из кеша.

    Returns:
        int: Значение в ppm (0-5000).
    """
```

- Описание в формате OpenAPI 3.0 (Swagger).
- Генерация документации через `FastAPI` или `flasgger`.

## 4. Git-конвенции

**Структура коммитов**:

[тип](<ID задачи или область>): <описание>
Пример: [feat](ble): Добавлено автоматическое переподключение

- Типы коммитов:
  - feat: Новая функциональность
  - fix: Исправление ошибок
  - improvement: Улучшения в проекте не касающиеся нового функционала
  - docs: Изменения в документации
  - refactor: Рефакторинг без изменения функционала
  - test: Тесты

- Ветвление:
  - master — стабильная версия.
  - Функциональные ветки: feature/ble-retry-logic, fix/web-auth.

## 5. Контейнеризация и CI/CD

- Docker: Мультистейд-сборка для уменьшения образа.

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

- CI/CD (GitHub Actions):

    ```yaml
    jobs:
      test:
        steps:
          - name: Run linters
            run: |
              black --check .
              flake8
          - name: Run tests
            run: pytest --cov=.
    ```

## 6. Безопасность

- Секреты:
  - Хранить в .env (в .gitignore).
  - Использовать python-dotenv для загрузки.

  ```python
    from dotenv import load_dotenv
    load_dotenv()
  ```

- Зависимости:
  - Регулярное обновление (pip-audit, dependabot).
  - Фиксация версий в requirements.txt с hash-суммами.

## 7. Работа с Bluetooth

- Асинхронность:
  - Использовать asyncio и Bleak для неблокирующих операций.

    ```python
    async def connect(device: BLEDevice) -> None:
        async with BleakClient(device) as client:
            await client.write_gatt_char(uuid, data)
    ```

- Обработка ошибок:
  - Экспоненциальная задержка при повторных подключениях.
  - Логирование всех BLE-событий в отдельный файл.

## 8. Веб-интерфейс

- Доступность:
  - Соответствие WCAG 2.1 (контраст, ARIA-роли).
  - Тестирование через axe-core.

- Шаблоны:
  - Использование Jinja2 с компонентным подходом.
  - Изоляция CSS через BEM-нотацию.

    ```html
    <div class="device-card">
    <button class="device-card__btn--primary">Включить</button>
    </div>
    ```

## 9. Логирование

- Формат:
  - JSON-логи для интеграции с ELK/Graylog.
  - Логирование через structlog.

    ```python
    import structlog
    logger = structlog.get_logger()
    logger.info("device_connected", device_id="Tion-123")
    ```

- Уровни:
    DEBUG — детализация BLE-операций.
    INFO — информационные сообщения.
    WARNING — предупреждения.
    ERROR — критические сбои (отправка в Sentry).

## 10. Автоматизация

- Все конвенции внедрены через pre-commit hooks и CI.
- Регулярный аудит зависимостей через Dependabot.
