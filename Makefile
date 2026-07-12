# Easy Breezy — команды разработки и развёртывания
.PHONY: dev dev-ui test lint fmt build-ui apk run clean release deploy provision

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

# Android APK (TWA поверх PWA); ключи и SDK — mobile/README.md.
# Итог: mobile/easy-breezy-<версия>.apk (версия — appVersion из twa-manifest.json).
apk:
	cd mobile && \
		export BUBBLEWRAP_KEYSTORE_PASSWORD=$$(grep KEYSTORE_PASSWORD keystore.properties | cut -d= -f2) && \
		export BUBBLEWRAP_KEY_PASSWORD=$$(grep KEY_PASSWORD keystore.properties | cut -d= -f2) && \
		npx @bubblewrap/cli build --skipPwaValidation && \
		VERSION=$$(python3 -c "import json; print(json.load(open('twa-manifest.json'))['appVersion'])") && \
		mv app-release-signed.apk "easy-breezy-$$VERSION.apk" && \
		rm -f app-release-unsigned-aligned.apk app-release-signed.apk.idsig app-release-bundle.aab && \
		echo "APK: mobile/easy-breezy-$$VERSION.apk"

# Релиз: версия в pyproject/__init__ + uv.lock, коммит и тег vX.Y.Z
release:
	@test -n "$(VERSION)" || { echo "Использование: make release VERSION=x.y.z"; exit 1; }
	@test -z "$$(git status --porcelain)" || { echo "Рабочее дерево не чистое — сначала закоммитить"; exit 1; }
	sed -i 's/^version = ".*"/version = "$(VERSION)"/' server/pyproject.toml
	sed -i 's/^__version__ = ".*"/__version__ = "$(VERSION)"/' server/src/easy_breezy/__init__.py
	cd server && uv lock
	git add server/pyproject.toml server/src/easy_breezy/__init__.py server/uv.lock
	git commit -m "release: v$(VERSION)" && git tag "v$(VERSION)"

# Выкат на целевой сервер (см. deploy/ansible/README.md): сборка UI и
# arm64-образа, доставка по ssh, health-гейт, автооткат при провале
deploy:
	@test -n "$(VERSION)" || { echo "Использование: make deploy VERSION=x.y.z"; exit 1; }
	cd ui && npm run build
	ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml -e version=$(VERSION)

# Разовая подготовка целевого сервера (docker, юниты, заготовки конфигов)
provision:
	ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/provision.yml

# Продоподобный запуск: сервер отдаёт собранный UI (после build-ui)
run:
	cd server && uv run python -m easy_breezy

clean:
	rm -rf server/.venv server/.mypy_cache server/.ruff_cache server/.pytest_cache \
		ui/node_modules ui/dist
