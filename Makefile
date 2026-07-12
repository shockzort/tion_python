# Easy Breezy — команды разработки и развёртывания
.PHONY: dev dev-ui test lint fmt build-ui apk run clean

# Запуск сервера разработки (http://localhost:8000)
dev:
	cd server && uv run python -m easy_breezy

# Запуск dev-сервера UI с прокси на сервер (http://localhost:5173)
dev-ui:
	cd ui && npm run dev

# Все тесты: сервер (pytest, гейт покрытия ≥80 %) + UI (vitest)
test:
	cd server && uv run pytest --cov --cov-report=term-missing:skip-covered --cov-fail-under=80
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

# Android APK (TWA поверх PWA); ключи и SDK — mobile/README.md
apk:
	cd mobile && \
		export BUBBLEWRAP_KEYSTORE_PASSWORD=$$(grep KEYSTORE_PASSWORD keystore.properties | cut -d= -f2) && \
		export BUBBLEWRAP_KEY_PASSWORD=$$(grep KEY_PASSWORD keystore.properties | cut -d= -f2) && \
		npx @bubblewrap/cli build --skipPwaValidation

# Продоподобный запуск: сервер отдаёт собранный UI (после build-ui)
run:
	cd server && uv run python -m easy_breezy

clean:
	rm -rf server/.venv server/.mypy_cache server/.ruff_cache server/.pytest_cache \
		ui/node_modules ui/dist
