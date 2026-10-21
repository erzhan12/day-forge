# Production и rollback после PR #252

21 октября 2026 года, Asia/Almaty. Проверен опубликованный релиз `52bc5c9dc209a0eca85ec031be3ada945480319b`: он содержит durable request_id из PR #252 и исправление зависимости из PR #254.

## Результат

Production smoke на выделенном тестовом аккаунте прошёл: свежий вход, реальный AI, точный повтор request_id, конфликт другого тела, Undo и Logout. В интерфейсе проверены AI/Undo на mobile 390×844, навигация Settings → Back и завершение сессии. Свежий desktop-вход, пустой день после Undo и Logout проверены при измеренных 1440×900.

Контейнерная репетиция на копии локальной SQLite-базы прошла: миграция `ai.0006 → ai.0007`, сохранение исходных строк, HTTP replay, rollback с отключённым AI, ручная запись на старой версии и повторное обновление. Сохранённый receipt пережил обе смены образа; повтор UUID не вызвал fixture provider второй раз и не убрал более новые ручные записи. Рабочая исходная база не менялась.

Исправлен блокирующий Deploy патч зависимости. Runtime-код приложения в этой задаче не менялся. Добавлены воспроизводимый контейнерный раннер и порядок безопасного rollback через границу нового chat-протокола.

## Почему потребовался PR #254

[Первый Deploy после #252](https://github.com/erzhan12/day-forge/actions/runs/39481554138) остановился на production dependency audit до сборки образа. `follow-redirects@1.16.0` получил high findings [GHSA-q3jh-wrc6-jgq8](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8) и [GHSA-8r9p-f939-6h3c](https://github.com/advisories/GHSA-8r9p-f939-6h3c); обе исправлены в `1.16.1`.

[PR #254](https://github.com/erzhan12/day-forge/pull/254) обновил только эту запись lockfile и dependency report. Audit gate не отключался. PR прошёл CI и получил Claude Review **APPROVED**, без замечаний. После merge прошёл [Deploy #39482514988](https://github.com/erzhan12/day-forge/actions/runs/39482514988): validation, build/push, deploy и HTTPS health-check. Финальный probe получил HTTP 200 с первой попытки.

Во время замены контейнера до финального health-check браузер один раз показал 502. После стабилизации Login и авторизованные сценарии работали. Непрерывная доступность во время смены образа этим прогоном не подтверждается.

## Опубликованный релиз

Анонимная Login и авторизованный браузер загрузили `52bc5c9…`. HTTPS проверялся с валидацией сертификата; для независимого Python-клиента использован доверенный CA bundle certifi, без отключения TLS-проверок.

| Asset | SHA-256 |
| --- | --- |
| `/static/assets/app-mNWRl_8o.js` | `eec7dcd96f389dc9d0574c28ccd7032f5c11348564f983d852a8b995db1afafc` |
| `/static/assets/app-DhYMgyGp.css` | `f1b175f0173a8efb42595af259316daff29ebc1275cae2f1246ff7211d67cbdd` |

Оба asset вернули HTTP 200 и `max-age=315360000, public, immutable`.

## Production: UUID и сохранение результата

Использован существующий неадминистративный тестовый аккаунт из [предыдущего smoke](PRODUCTION_ACCOUNT_SMOKE_2026-10-20.md). Credentials прочитаны из приватного файла вне репозитория. Изменения ограничены предварительно проверенными пустыми датами 22 и 23 октября; другие расписания и настройки не редактировались.

Повтор UUID выполнен независимым HTTPS-клиентом, который прошёл обычный password login и отправлял CSRF, frontend-version и owner headers. Ответы провайдера не подменялись.

| Проверка на 23 октября | Наблюдение |
| --- | --- |
| Исходный запрос | Реальный AI создал единственный Work-блок `Release request-id smoke`, 14:00–14:30. Ответ 200 содержит исходный UUID и `request_completed: true` |
| То же тело и UUID | Возвращены тот же status и побайтно тот же JSON. Свежий GET показал один блок и неизменную revision, хотя original expected_revision уже устарела |
| Другое тело с тем же UUID | 409 `request_id_conflict` |
| Undo | Restore исходного пустого snapshot с подтверждённой текущей revision вернул пустой день |
| Тот же UUID после Undo | Возвращён прежний receipt, но свежий GET остался пустым и не изменил revision. Старый snapshot не стал новой записью |
| Logout | Login после выхода; последующий защищённый GET потребовал вход |

В production не внедрялась искусственная потеря соединения и не запускалась конкурентная нагрузка. Это проверка повторного HTTP-запроса и durable результата на опубликованной ASGI-конфигурации. Отдельный точный счётчик вызовов провайдера из production не извлекался; сведения об идентичном ответе и состоянии расписания записаны независимо от AI audit.

## Production: браузер

Все UI-действия выполнены через CUA во встроенном Chromium. Поле чата отправило реальный запрос: `Add a Work block titled "Release browser smoke" from 15:00 to 15:30. Keep all other blocks unchanged.` AI применил этот блок на 22 октября. Отдельная вкладка выполнила свежий серверный GET и подтвердила title, Work, 15:00–15:30, revision 1.

Видимая кнопка Undo убрала блок. Повторный GET из второй вкладки подтвердил пустой день и revision 2. Settings → Back вернул исходную дату; согласование завершилось, ручное редактирование снова доступно. Logout с открытым чатом показал Login. Back оставил Login вместо приватного Schedule, а reload второй вкладки также потребовал вход.

На mobile фактический viewport был 390×844, scrollWidth 390. Центр Logout попадал в саму кнопку, перекрытия чатом не было. Прямоугольник кнопки: x=308,625, y=437,5, width=65,375, height=28.

Для desktop выполнен новый вход и свежий GET 22 октября: пустой день, revision 2, viewport и scrollWidth 1440×900 / 1440. Logout, Back и reload снова показали Login. Первая смена viewport применилась ко второй вкладке; проверка размеров это выявила, и desktop-сценарий повторён именно на вкладке 1440×900. Несколько ожиданий автоматизации истекли раньше завершения навигации; итоговое состояние проверено повторным чтением без повторной отправки POST.

Всего выполнены две успешные реальные AI-операции: одна через HTTPS-клиент и одна через UI. Внутренние SDK retries отдельно не считались. На обеих тестовых датах после проверки нет блоков. ChatRequest и AI audit намеренно сохраняются согласно retention, аккаунт остаётся для следующих smoke.

Снимки: [AI apply](screenshots/post-pr252-2026-10-21/mobile-ai.jpg), [Undo](screenshots/post-pr252-2026-10-21/mobile-undo.jpg), [mobile Logout](screenshots/post-pr252-2026-10-21/mobile-logout.jpg), [desktop после Undo](screenshots/post-pr252-2026-10-21/desktop-clean.jpg), [desktop Logout](screenshots/post-pr252-2026-10-21/desktop-logout.jpg). Байты сохранены без обработки.

## Обновление и rollback на копии базы

Раннер: [rehearse_chat_requests.py](../deployment/scripts/rehearse_chat_requests.py), fixture provider: [rehearsal_chat_provider.py](../deployment/scripts/rehearsal_chat_provider.py). Команда воспроизведения и ограничения источника описаны в [runbook](../deployment/README.md#rolling-back-across-the-durable-chat-boundary-pr-252).

Источник: локальная рабочая SQLite-база, 1198 строк в 25 таблицах, скопированная через SQLite backup API. Production-база не скачивалась. Использованы production Dockerfile/entrypoint, uvicorn, реальный Redis, лимит web 250 MiB и внутренний Docker network. Только reverse proxy опубликован на loopback. Интеграционные ключи фиктивные, polling отключён, AI отвечает через изолированный fixture provider без внешних соединений.

Сверка строк внутри копии исключает `django_migrations`: подготовительное обращение пустой 0007 удаляет и затем заново создаёт её metadata-запись. Прикладные строки сохраняются. Рабочая исходная база сравнена целиком, без этого исключения, и осталась неизменной.

Старый образ собран из `7a86aca`, новый из `f282fc0`. Git tree нового исходника совпадает с production merge `52bc5c9`; baked frontend-version отличается, что отражено в evidence. Локальные образы имеют платформу Linux arm64, production собирается отдельно. Равенство production-бинарников или hashes локальных и опубликованных assets не утверждается.

| Этап | Результат |
| --- | --- |
| Подготовка | Новая приватная директория под `/tmp`; существующие Docker projects не переиспользуются. Уже применённая 0007 обращена только в копии с пустой таблицей requests, чтобы получить настоящий pending migration. Источник не затронут |
| 0006 → 0007 | Новая версия применила миграцию. Исходные строки сохранены, integrity check `ok` |
| Реальный HTTP через ASGI/Redis | Fixture AI создал один блок. Повтор UUID вернул те же status/body, другое тело получило 409. Counter fixture provider равен 1 |
| Ручная запись после receipt | Добавлена отдельная запись; сохранённый ответ остаётся старым snapshot |
| Rollback образа | Таблица и receipt сохранены без обратной миграции. Новый bundle получил `frontend_outdated`. При пустом LLM_API_KEY старый chat вернул 503 без provider call; ручная запись прошла |
| Повторное обновление | Startup идемпотентен. UUID вернул исходный receipt, provider counter остался 1, обе более новые ручные записи сохранились |
| Завершение | Logout, Django check, отсутствие migration drift, сохранение исходных domain rows и неизменность рабочей базы подтверждены |

Сохранить таблицу при rollback недостаточно: старый backend не умеет возвращать durable receipt. Runbook теперь требует отключить AI на время возврата к версии до #252 и восстановить исходный turn после обновления. Удалять завершённые identities или ограничивать response путём обрезания нельзя без отдельного изменения контракта.

## Проверки и границы

После патча зависимости прошли `make check` (2138 backend, 1 skipped, 1409 frontend, Ruff и type-check), production frontend build и production audit с 0 vulnerabilities. Такие же проверки прошли в Deploy. Пропущен существующий opt-in платный comparison. Новые скрипты отдельно прошли Ruff и полный контейнерный прогон.

В production существование нового request store подтверждено успешными terminal receipts и replay. Прямое чтение таблицы django_migrations и SSH-доступ не использовались. Здесь не проверялись реальный iOS Safari, живые OAuth-интеграции, нагрузка или качество модели на корпусе. Server-owned pending intent остаётся отдельной задачей.

Машиночитаемые наблюдения, digests и hashes снимков: [POST_PR252_RELEASE_VERIFICATION.json](evidence/POST_PR252_RELEASE_VERIFICATION.json). Credentials, cookies, CSRF, restore proofs и raw production JSON в него не включены. Тестовые сессии завершены, созданные вкладки закрыты, viewport сброшен. Приватные копии баз и sandbox logs удалены после сохранения безопасного evidence.
