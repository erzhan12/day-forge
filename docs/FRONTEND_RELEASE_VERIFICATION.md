# Версия frontend, обновление и rollback

18 октября 2026 года. База: `a0fed38`, main после PR #244. Закрыт пункт о совместимости старой вкладки с новым релизом из итогового аудита.

## Реализация

Production build получает `RELEASE_VERSION`, в deployment это полный `${{ github.sha }}`. Vite встраивает идентификатор в JS и записывает `.vite/release.json` с версией, entry и CSS. Имена JS/CSS содержат content hash. Для обычного локального `make frontend-build` без идентификатора версия вычисляется из manifest; dev server сохраняет `development` и HMR.

Django загружает metadata и проверяет наличие assets при production startup. Неполная сборка останавливает запуск с понятной ошибкой. HTML подключает файлы из metadata и содержит ту же версию, которую Inertia отдаёт в page JSON. WhiteNoise помечает hashed frontend assets как immutable. Metadata читается из файлов внутри образа, независимо от runtime `.env` и общего bind mount staticfiles. При возврате предыдущего образа возвращаются его версия и ссылки на его assets.

Новый JS отправляет `X-Frontend-Version` со всеми JSON API запросами. Версия относится к запущенному bundle и не меняется при Inertia history/props updates. При несовпадении middleware возвращает `409 frontend_outdated` до выполнения view. Небезопасный запрос без заголовка тоже отклоняется, что закрывает первую установку поверх legacy frontend. Чтение без заголовка оставлено совместимым. Проверка версии дополняет CSRF, authentication, user identity и schedule revision.

У нового клиента появляется уведомление с Reload. Страница не перезагружается сама, введённый текст остаётся до решения пользователя. Никакой write не повторяется автоматически. У legacy клиента остаётся сообщение об ошибке с указанием перезагрузить страницу; новый banner отсутствует в его старом JS.

Старая Inertia-навигация получает `409 X-Inertia-Location` и загружает актуальный документ. Проверка выполняется до view, чтобы отклонённый переход не запускал bootstrap нового дня. Обёртка установленного Inertia middleware ограничивает его собственный refresh GET/HEAD запросами: POST Logout сохраняет redirect на Login, а следующий GET выполняет version handshake.

## Браузерная проверка

Использованы отдельная SQLite база и HTTP origin `http://localhost:8008`. Сервер работал с `DEBUG=0`, WhiteNoise, собранными файлами и обычными application endpoints. Между релизами сервер действительно останавливался и запускался с другим build directory; база, session key и staticfiles сохранялись.

Сборки A/B получены из текущего frontend с `RELEASE_VERSION=release-a/release-b`. Дополнительно собран настоящий frontend из `a0fed38`: постоянные app.js/app.css, Inertia `1.0`, без нового заголовка и banner. Для его загрузки fixture server использовал compatibility metadata, не меняя legacy JS.

| Сценарий | Результат |
| --- | --- |
| Сохранение в A | Блок создан, API получил `release-a`, HTTP 201. |
| Открытая форма A → B | POST со старой версией получил 409; введённое название осталось в форме. Блок не создан. |
| Reload после обновления | Meta/page version стали B; загрузился другой hashed JS. Ранее сохранённый блок A остался. |
| Работа B | Новый блок, Cancel удаления, Delete, Undo и completion/Undo прошли. |
| Открытая форма B → A | POST B отклонён сервером A; сохранённые блоки остались, ошибочный блок не создан. Reload загрузил JS A. |
| Навигация A → B и B → A | Settings и возврат к Schedule дали version 409, затем полный GET и совместимый JS. |
| Back/Forward после rollback | Отобразились актуальные Settings/Schedule с версией A. История другого релиза не стала текущей page version. |
| Legacy `1.0` → B | POST без заголовка отклонён; блоки и revision до/после совпали. Переход legacy вкладки в Settings загрузил B через version handshake. |
| Мобильная форма после Reload | Совместимый POST B сохранил блок. На фактических 390×844 banner имел ширину 390 px, overflow 0. |
| Реальный AI chat | Добавлен `Release smoke task` 14:00–14:30; Undo восстановил прежнее состояние. HTTP 200, успешная chat audit row. |
| Реальный AI draft | Новый день получил шесть блоков шаблона, статус draft; Undo вернул пустой день. HTTP 200, успешная draft audit row. |
| Settings и 4a | Смена темы через JSON API сохранилась. Мобильные Add/Undo прошли и в 4a. |
| Analytics | Completion 1/1, Mark reviewed и notes сохранились после повторного входа. |
| Logout | Desktop 1440×900 и mobile 390×844 перешли на Login. Отдельно прошёл Logout старой B вкладки на сервере A. Back после Logout и запрос соседней вкладки не показали приватную страницу. |
| Кеш assets | JS A и B имеют разные URL; оба отдаются с HTTP 200 и `public, immutable`. |

Машиночитаемые HTTP события, metadata, cache headers и сравнение legacy database snapshots сохранены в [evidence](evidence/FRONTEND_RELEASE_VERIFICATION.json). Артефакты содержат только данные изолированного пользователя; cookies, ключей и raw AI prompts в них нет.

## Найденные и исправленные ошибки

1. Ранний version guard обходил MessageMiddleware. Внешний inertia-django пытался сохранить flash messages и возвращал 500. Guard перенесён после MessageMiddleware; добавлен тест настоящего middleware stack, браузерный переход повторён успешно.
2. inertia-django 1.2 применял force refresh после устаревшего POST Logout. Он возвращал location POST-only URL вместо redirect на Login. Ошибка воспроизведена отдельным тестом и исправлена ограничением response refresh безопасными методами. Старый Logout проверен в браузере.

## Проверки

`make check`: Ruff прошёл, backend **2115 passed, 1 skipped**, frontend **1395 passed, 103 файла**, type check прошёл. Пропущен opt-in платный R11 comparison; реальные chat/draft выполнены отдельно через UI. `make frontend-build` прошёл. Production npm audit: **0 vulnerabilities**. Image-retention tests и SSH host-key pinning проверены без ослабления правил.

## Воспроизведение

Из корня репозитория, для нового каталога под `/tmp`:

```sh
mkdir -p /tmp/day-forge-release-example
RELEASE_VERSION=release-a npm --prefix frontend run build -- --outDir /tmp/day-forge-release-example/build-a
RELEASE_VERSION=release-b npm --prefix frontend run build -- --outDir /tmp/day-forge-release-example/build-b
uv run python backend/scripts/release_browser_server.py /tmp/day-forge-release-example /tmp/day-forge-release-example/build-a
```

Открыть `http://localhost:8008/accounts/login/`, войти как `release-browser` с паролем `release-browser-local-only`. Это отдельный локальный fixture account. Рабочая база и `.env` не изменяются. Сервер создаёт сегодняшний день и 11 июля 2027 года, подавляя непреднамеренный auto-draft при входе.

Оставить форму открытой, остановить только этот сервер и запустить ту же команду с `build-b`. Попытаться сохранить, проверить отказ и Reload. Для rollback повторить с `build-a`. Для проверки навигации держать вторую вкладку открытой и после перезапуска перейти в Settings. Сервер сохраняет безопасный request audit в `requests.jsonl`. Реальные AI запросы используют локальную конфигурацию provider; запускать сценарии последовательно.

## Границы результата

Это локальная репетиция production assets и HTTP/version protocol. Production rollout не выполнялся. Docker daemon недоступен, поэтому новый контейнер локально не собирался и не запускался. Dockerfile и workflow передают release ID, а проверенная структура build соответствует COPY в runtime image.

Rollback B → A проверен для двух релизов с новым протоколом. Неизменённый старый backend image до этого исправления не умеет отклонять новые несовместимые API запросы; перед таким rollback потребуется обновить вкладки. Смена версии также не отменяет уже отправленную запись и не реализует durable request identity. PiP с открытым окном, настоящий iOS Safari и интеграции с живыми внешними аккаунтами остаются отдельными задачами.
