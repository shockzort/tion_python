# Easy Breezy — Android APK (TWA)

APK — тонкая обёртка Trusted Web Activity над PWA
`https://easy-breezy.duckdns.org`: интерфейс открывается в Chrome-движке,
обновляется с сервера (пересборка APK не нужна), web push работает.
Capacitor сознательно не используется: в его WebView Push API мёртв.

## Артефакты

- `easy-breezy-<версия>.apk` — единственный итог сборки, ставится на телефон
  (в git не попадает; промежуточные `app-release-*` удаляются после сборки).
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
приложения — поднять `appVersionCode`/`appVersion` в манифесте
(поле именно `appVersion`: bubblewrap читает версию из него, поле с другим
именем молча игнорируется и в APK уезжает пустой `versionName`).
`update` скачивает иконки с живого URL — стенд должен быть доступен
(`https://easy-breezy.duckdns.org`), иначе проект остаётся без drawable
и сборка падает на `resource drawable/splash not found`.

Установка: перекинуть APK на телефон (или `adb install
easy-breezy-<версия>.apk`), разрешить установку из файла.

## Если «не удалось установить»

Подпись и манифест проверяются так (build-tools из `~/.bubblewrap`):

```bash
BT=~/.bubblewrap/android_sdk/build-tools/35.0.0-2
$BT/apksigner verify --print-certs easy-breezy-<версия>.apk   # v1+v2+v3 = true
$BT/aapt dump badging easy-breezy-<версия>.apk | head -1      # versionCode/Name
```

Частые причины при валидной подписи:

1. На телефон улетел не тот файл (раньше рядом лежал
   `app-release-unsigned-aligned.apk` — неподписанный; теперь промежуточные
   артефакты удаляются сборкой).
2. На телефоне уже стоит приложение с тем же package
   (`org.duckdns.easybreezy`), но другой подписью (старый keystore,
   debug-сборка) — удалить установленное и поставить заново.
3. Битый файл после передачи — сверить размер/хэш.

Точный код ошибки даёт только `adb install` с ПК
(`INSTALL_FAILED_UPDATE_INCOMPATIBLE` = п. 2 и т.д.) — установка «с файла»
на телефоне показывает лишь «не удалось установить».

## Если видна адресная строка (не полный экран)

TWA раскрывает браузерную бровку в двух случаях:

1. **Не прошла верификация Digital Asset Links** — Chrome при первом
   запуске скачивает `/.well-known/assetlinks.json` с живого сайта;
   если сайт в этот момент лежал, результат кэшируется. Проверка:

   ```bash
   curl -s https://easy-breezy.duckdns.org/.well-known/assetlinks.json
   # отпечаток должен совпадать с:
   ~/.bubblewrap/android_sdk/build-tools/35.0.0-2/apksigner verify \
       --print-certs easy-breezy-<версия>.apk | grep SHA-256
   ```

   Лечение: поднять сайт, переустановить APK (или стереть данные Chrome).
2. **Safe Browsing пометил домен** («Опасный сайт») — Chrome принудительно
   показывает тулбар с предупреждением поверх любого, даже верифицированного
   TWA. Лечение — снимать флаг, а не менять обёртку: репорт ложного
   срабатывания / Search Console / свой домен — план и ссылки в
   `docs/status.md`.
