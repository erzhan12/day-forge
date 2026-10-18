# Проверка deployment и контейнерный rollback после PR #245

18 октября 2026 года. Проверен `main` на `afc94f658f4f09e293bfd922fdc6aca271da8ffb`.

## Результат

[Deploy #39124762341](https://github.com/erzhan12/day-forge/actions/runs/39124762341) завершился успешно в 11:54:08 UTC. Прошли общий CI, build/push, deployment и внешний HTTPS health check. Дополнительная проверка опубликованного frontend подтвердила SHA релиза и совпадение файлов с локальной контейнерной сборкой.

Контейнерная репетиция прошла на SQLite-копии локальной рабочей базы. Обновление с PR #244, rollback между версиями с новым протоколом и возврат к legacy-образу сохранили данные. Новых ошибок приложения в этих сценариях не найдено. Добавлены воспроизводимый раннер и уточнения runbook о совместимости схемы и старых вкладок.

## Опубликованный релиз

Проверен `https://dayforge.habitreward.org` с обычной проверкой TLS-сертификата:

| Проверка | Результат |
| --- | --- |
| Login, Privacy, Terms | HTTP 200; страницы открылись в браузере |
| Версия HTML | `afc94f658f4f09e293bfd922fdc6aca271da8ffb` |
| JS | `/static/assets/app-DDE0P96J.js`, HTTP 200; SHA релиза встроен в bundle |
| CSS | `/static/assets/app-COtgMyyv.css`, HTTP 200 |
| Кеш JS/CSS | `max-age=315360000, public, immutable` |
| Совпадение frontend | SHA-256 опубликованных JS/CSS совпали с файлами локального production-контейнера |
| Settings/Schedule без сессии | Redirect на Login; приватная страница не отдана |
| Старая Inertia-навигация | `409 X-Inertia-Location`, указывающий на актуальный документ |

JS SHA-256: `80a730a9fab49b359efd6e3b693984d11c57796ced3ab9f40f18cf0e2fb2183f`.
CSS SHA-256: `d26f2305d3ef0accf5da103ac28ff78b6b40e68e7d401f75df97d1ebf341e85b`.

Production login после ввода credentials и операции под production-пользователем не проверены: в доступной локальной конфигурации нет этих credentials. Production-база не скачивалась и не изменялась. Авторизованные сценарии ниже относятся к отдельному контейнерному стенду.

## Стенд и образы

Docker Desktop удалось запустить. Локальный GitHub token не имеет доступа к закрытым GHCR packages, поэтому образы собраны из исходников штатным `deployment/docker/Dockerfile`:

| Образ | Исходники и версия |
| --- | --- |
| `day-forge-rehearsal:pr244` | Git archive `a0fed3845f1bf01b6f50f9f0100f4355faaeec64`, Inertia `1.0`, постоянные app.js/app.css |
| `day-forge-rehearsal:pr245` | `afc94f658f4f09e293bfd922fdc6aca271da8ffb`, та же версия встроена в frontend |
| `day-forge-rehearsal:compatible` | Исходники PR #245 с отдельной версией `rehearsal-compatible`; JS `app-jdPGjMOb.js` |

Все локальные образы имеют архитектуру ARM64 и запускают обычный entrypoint, непривилегированного пользователя `app` и один uvicorn worker. Это не скачанные production-образы AMD64 и не проверка побайтового совпадения всего runtime image. Совпадение frontend-файлов проверено отдельно.

SQLite-копия создана через backup API при read-only подключении к источнику. У стенда собственные Redis, session secret и staticfiles. Web имеет те же лимиты 250 MiB RAM и 500 MiB RAM+swap, что production Compose. Healthcheck взят из образа; интервал сокращён до двух секунд для репетиции. Проверены healthy status, отсутствие OOM и реальная операция Redis set/get/delete.

Web и Redis подключены только к Docker internal network. Пробное исходящее соединение из web вернуло `ENETUNREACH`. Только Caddy proxy имеет вторую сеть и опубликован на `127.0.0.1:8009`; Redis и web наружу не опубликованы. AI и polling выключены, ключи интеграций заменены тестовыми. Скопированные аккаунты не использовались. В браузере вход выполнен под новым пользователем стенда, созданным только в копии.

Localhost proxy передаёт `X-Forwarded-Proto: https`, представляя HTTPS termination перед Django. Production cookie flags и redirect settings не ослаблялись. Внешний TLS проверен на опубликованном сайте; локальный HTTP proxy не воспроизводит сертификаты Caddy production.

## Обновление и rollback

Раннер находится в [deployment/scripts/rehearse_release.py](../deployment/scripts/rehearse_release.py). Он использует реальные HTTP endpoints и cookies, не Django test client.

| Сценарий | Результат |
| --- | --- |
| Старт PR #244 на копии | Entrypoint, migrate, collectstatic и uvicorn прошли |
| PR #244 → PR #245 | Сессия сохранилась; HTML и assets переключились на SHA PR #245 |
| Legacy/headerless POST на PR #245 | HTTP 409 до записи; снимок всех таблиц до/после совпал |
| POST с версией `1.0` | HTTP 409 `frontend_outdated`, `Cache-Control: no-store` |
| Актуальный POST | HTTP 201; revision увеличилась на один; блок виден после GET |
| PR #245 → compatible → PR #245 | Образы и bundle сменились; POST compatible-вкладки после rollback отклонён без записи |
| PR #245 → PR #244 | После явного reload старое приложение читает сохранённые обоими релизами блоки |
| PR #244 → PR #245 повторно | Актуальный HTML и hashed assets восстановлены из образа |
| Исходные данные | Все исходные строки 24 таблиц остались в копии без изменений |
| Рабочая база-источник | Логический SHA-256 снимка до и после репетиции совпал |
| Logout с устаревшей версией | Redirect на Login; анонимные props и `clearHistory: true` |

Rollback к PR #244 требует обновить открытые вкладки перед дальнейшими записями. Его backend не содержит нового API version guard. Совместимость старого backend нельзя добавить переключением нового образа: это ограничение конкретного legacy-релиза, уже зафиксированное в отчёте PR #245.

## Миграции

PR #245 не добавляет миграций. Поэтому обычная смена PR #244/245 запускает migrate без изменения схемы. Откат образа в этой проверке не сопровождался обратной миграцией или восстановлением старой базы: записи, сделанные после обновления, должны сохраниться.

Отдельная копия исходного backup проверила настоящую pending migration:

1. Только на этой копии schedules приведена к 0009, без поля `origin`.
2. Entrypoint PR #245 применил 0010 и запустил collectstatic.
3. Все строки и остальные поля сохранились. Существующие блоки получили `origin=unknown`, как требует privacy-контракт миграции.
4. Повторный entrypoint не изменил логический снимок базы.
5. SQLite integrity check прошёл. `makemigrations --check --dry-run` не нашёл новых миграций.

Это проверка конкретной миграции 0010. Она не доказывает совместимость любых будущих schema changes со старыми образами. Перед будущим rollback требуется сверять схему и контракт обеих версий.

## Браузер поверх контейнеров

CUA, фактический viewport 1280×720. Сервер действительно менялся через Compose, вкладка оставалась открытой:

| Сценарий | Результат |
| --- | --- |
| Открытая форма PR #245 → compatible | Add отклонён; текст и время остались в форме; появился Reload |
| Reload после обновления | Версия `rehearsal-compatible`, JS `app-jdPGjMOb.js` |
| Открытая форма compatible → PR #245 | Add отклонён; `Browser rollback pending` остался в форме; данные отклонённых форм в базе отсутствуют |
| Reload после rollback | Вернулся SHA PR #245 и `app-DDE0P96J.js`; горизонтальный overflow 0 |
| Работа после rollback | Добавление, Cancel удаления, Delete, Undo удаления, completion и Undo completion прошли |
| Settings | Тема Dark 4a сохранилась через API и применилась на Schedule |
| Analytics | Mark reviewed и notes сохранились после ухода и возврата |
| Logout и Back | Login; история не восстановила приватную страницу |

[Снимок старой формы после rollback](evidence/DEPLOYMENT_REHEARSAL_PR245_ROLLBACK.png) содержит только данные тестового пользователя.

Реальные AI-запросы в изолированном контейнерном стенде не выполнялись. Их предыдущие успешные chat/draft проверки описаны в [отчёте PR #245](FRONTEND_RELEASE_VERIFICATION.md). Мобильный viewport и открытое PiP в этом дополнительном прогоне не проверялись.

## Автоматические проверки и воспроизведение

- `make check`: Ruff и type check прошли; backend 2118 passed, 1 opt-in paid comparison skipped; frontend 1395 passed, 103 файла.
- Production Docker builds: PR #244, PR #245 и compatible прошли. Полная сборка JS/CSS выполнена внутри Dockerfile.
- Ruff для нового раннера прошёл; `git diff --check` прошёл.
- Защита от существующего Docker project проверена на отдельной помеченной сети: раннер отказал до копирования базы и сохранил существующий ресурс.
- Финальная версия раннера повторно прошла весь цикл на `127.0.0.1:8010` и сама остановила контейнеры. После проверки временные копии баз и конфигурация стендов удалены; рабочая база осталась неизменной.
- Image-retention tests прошли. SSH pinning покрыт общим CI.
- `check --deploy`: ошибок нет, два известных предупреждения: SQLite writer contention (`schedules.W001`) и отсутствие Django HSTS preload (`security.W021`). Настройки ради исчезновения предупреждений не менялись.

Команды сборки и запуска раннера сохранены в [deployment runbook](../deployment/README.md#container-rehearsal-on-a-database-copy). Машиночитаемые результаты deployment, HTTP probes, образов и репетиции находятся в [evidence](evidence/DEPLOYMENT_REHEARSAL_PR245.json). Рабочие базы, credentials, cookies и raw container logs в репозиторий не добавляются.
