# Easy Breezy — Android APK (TWA)

APK — тонкая обёртка Trusted Web Activity над PWA
`https://easy-breezy.duckdns.org`: интерфейс открывается в Chrome-движке,
обновляется с сервера (пересборка APK не нужна), web push работает.
Capacitor сознательно не используется: в его WebView Push API мёртв.

## Артефакты

- `app-release-signed.apk` — ставится на телефон (в git не попадает).
- `twa-manifest.json` — источник правды генерации проекта (в git).
- `android.keystore` + `keystore.properties` — ключ подписи и пароли
  (в git НЕ попадают; потеря ключа = переустановка приложения с нуля,
  для домашнего APK некритично).
- `ui/public/.well-known/assetlinks.json` — отпечаток подписи; раздаётся
  сервером, чтобы Android открывал приложение без адресной строки.
  При новом keystore обновить отпечаток (`apksigner verify --print-certs`).

## Пересборка

Требуется JDK 17 и Android SDK в `~/.bubblewrap` (bubblewrap найдёт их
через `~/.bubblewrap/config.json`; разово скачаны 2026-07-12):

```bash
make apk          # из корня репозитория
# или вручную:
cd mobile
export BUBBLEWRAP_KEYSTORE_PASSWORD=$(grep KEYSTORE_PASSWORD keystore.properties | cut -d= -f2)
export BUBBLEWRAP_KEY_PASSWORD=$(grep KEY_PASSWORD keystore.properties | cut -d= -f2)
npx @bubblewrap/cli build --skipPwaValidation
```

Изменение имени/цветов/иконки — правкой `twa-manifest.json`, затем
`npx @bubblewrap/cli update --skipVersionUpgrade` и сборка. Новая версия
приложения — поднять `appVersionCode`/`appVersionName` в манифесте.

Установка: перекинуть APK на телефон (или `adb install
app-release-signed.apk`), разрешить установку из файла.
