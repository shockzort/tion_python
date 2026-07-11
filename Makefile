# Easy Breezy — команды разработки и развёртывания
.PHONY: dev dev-ui test lint fmt build-ui run clean

# Запуск сервера разработки (http://localhost:8000)
dev:
	cd server && uv run python -m easy_breezy

# Запуск dev-сервера UI с прокси на сервер (http://localhost:5173)
dev-ui:
	cd ui && npm run dev

# Все тесты: сервер (pytest) + UI (vitest)
test:
	cd server && uv run pytest
	cd ui && npm run test

# Линтеры и типы: сервер + UI
lint:
	cd server && uv run ruff check src tests && uv run black --check src tests \
		&& uv run isort --check-only src tests && uv run mypy
	cd ui && npm run lint && npx tsc -b

# Автоформатирование сервера
fmt:
	cd server && uv run black src tests && uv run isort src tests \
		&& uv run ruff check --fix src tests

# Сборка фронтенда (выполнять на dev-машине/CI, не на Pi)
build-ui:
	cd ui && npm run build

# Продоподобный запуск: сервер отдаёт собранный UI (после build-ui)
run:
	cd server && uv run python -m easy_breezy

clean:
	rm -rf server/.venv server/.mypy_cache server/.ruff_cache server/.pytest_cache \
		ui/node_modules ui/dist
