# Durable request_id для AI-chat

20 октября 2026 года. Реализация поверх `main` после PR #251 (`7a86aca`). Контракт основан на [R11 design](REFACTORING_R11_DESIGN.md).

## Результат

AI-chat использует постоянный UUID на один пользовательский turn. Если изменение сохранилось, а HTTP-ответ потерялся, повтор с тем же телом возвращает сохранённый результат. Повторное применение и новый вызов провайдера для завершённого запроса исключены. Одновременные одинаковые запросы делят одну серверную запись; проигравший получает явный in-progress response.

В браузере проверены потеря одного и обоих ответов после commit, recovery после перезапуска backend и reload, два одновременных HTTP-запроса, явный новый повтор и сохранение более новой ручной правки. Выполнены **7 реальных chat-вызовов и 1 draft-вызов** без подмены провайдера. Все завершились успешно. Полные тесты прошли: **2136 backend, 1409 frontend**, один платный opt-in comparison пропущен.

Production не обновлялся и не использовался для этих mutations. Браузер работал с изолированной SQLite-базой под `/tmp`, реальным AI и собранными assets. Redis и внешние интеграции на стенде отключены.

## Серверный контракт

Новая модель `ChatRequest` хранит owner, дату, UUID, SHA-256 полного JSON-тела, lease-токен и expiry, terminal HTTP status/body и время завершения. Миграция: `ai.0007_chatrequest`. Unique constraint задаёт namespace owner + civil date + chat endpoint. Endpoint выделен самой моделью, draft этот протокол не использует.

1. Валидация размера, JSON, сообщений, revision и UUID предшествует admission. UUID должен быть канонической строкой. Хеш включает исходные сообщения, markers, revision и дополнительные поля; порядок ключей объекта незначим.
2. Под общим User lock сервер ищет identity. Другое допустимое тело с тем же UUID получает `409 request_id_conflict`. Завершённый идентичный запрос возвращается до сравнения с текущей revision.
3. Новый запрос получает lease до provider call. Действующий lease возвращает `409 request_in_progress`, `Retry-After: 2`. Истёкший lease можно занять новым случайным токеном.
4. Контекст и revision проверяются обычным путём, provider работает вне write lock. Повтор сохранённого результата не вызывает provider, audit log или rate limiter.
5. Перед apply сервер проверяет lease-токен под User lock. Построение HTTP-результата, schedule mutation и сохранение terminal response находятся в одной внешней транзакции. Общий schedule executor сохраняет revision/fingerprint/ownership проверки и порядок User → Schedule → TimeBlock.
6. Ask, no-op, отклонённый apply и известная ошибка провайдера тоже получают terminal result. Для осознанного нового запроса после такой ошибки нужен новый UUID. Сбой identity store возвращает `503 request_unavailable`; клиент сохраняет исходную identity для recovery.

Terminal JSON содержит `request_id` и `request_completed: true`. Сохранённые status/body воспроизводятся без переоценки запроса по новым настройкам расписания. Это receipt прежней операции, поэтому его snapshot может быть старее текущего экрана. Клиент не должен откатывать canonical state к старой revision.

Lease длится `max(120, LLM_REQUEST_TIMEOUT * 4 + 30)` секунд. Если worker упал до atomic commit, после expiry запрос можно выполнить заново. При takeover возможен повтор provider call, но прежний worker уже не может применить свой результат. Гарантия относится к единственному применению расписания, а не к единственному сетевому вызову при падении процесса.

`AIInteraction` остаётся best-effort audit. Его `success` обновляется после commit и не используется для дедупликации. Ответ, возвращённый старому worker из уже завершённой записи, не превращает его собственную audit-попытку в успешную.

## Клиентское восстановление

`useChat` создаёт отдельный `crypto.randomUUID()`, сохраняя прежний числовой request counter для UI generation. Полное тело фиксируется до первого POST: последующие попытки не подменяют transcript или revision свежими props.

При неизвестном transport outcome клиент выполняет один немедленный повтор с тем же телом. Явный in-progress response не запускает цикл polling. Успех или terminal error принимается только с `request_completed: true` и UUID исходного запроса. Пустой HTTP 200 и несовпадающий UUID считаются неизвестным результатом, а не успешным пустым ответом. Если результат всё ещё неизвестен:

- исходный запрос хранится в account/date-scoped `sessionStorage` этой вкладки;
- новый AI-turn и clear заблокированы; синтетический `is_error` assistant не создаётся;
- показаны текст прежнего запроса и **Recover previous AI request**;
- recovery возвращает сохранённый результат либо завершает исходную незавершённую операцию;
- после обычного согласования расписания ручные изменения доступны;
- reload/remount сохраняет возможность recovery, а Login, Logout и смена аккаунта очищают приватные клиентские копии.

Очистка на уровне app root работает и после ухода со Schedule в Settings. После logical clear, смены даты или session boundary поздняя ошибка не запускает дополнительный автоматический POST. При недоступном sessionStorage новый запрос не отправляется, текст возвращается в input с понятной ошибкой.

Обычный recovery до reload сохраняет правильный Undo. После reload прежняя Undo-history не восстанавливается искусственно. Если сохранённый receipt старее новой ручной записи, клиент обновляет текущий день вместо принятия старого snapshot и не создаёт недостоверный Undo.

## Retention и миграция

Identity и response хранятся до удаления аккаунта. Связи с Schedule нет: удаление и повторное создание дня не разрешает заново применить прежний UUID. Автоматического prune нет. Сохранённый response содержит приватный snapshot расписания; доступ к нему имеет только аутентифицированный owner через повтор собственного запроса.

Удаление завершённых строк с последующим повторным приёмом тех же UUID нарушит гарантию. Будущая политика retention должна оставить durable tombstones или сохранить эквивалентную долгоживущую уникальность. При image rollback таблицу нужно сохранить. Обратная миграция с удалением identities не является безопасным продолжением этого протокола после начала его использования.

Миграция применена к локальной рабочей базе после SQLite backup API в приватный каталог вне репозитория. Проверены **1143 исходные записи в 23 таблицах**: ни одна не изменена и не удалена. Django добавил один content type и четыре permission для новой модели; отдельно добавлена запись миграции. Новая таблица пуста, SQLite integrity check вернул `ok`. `manage.py check` и `makemigrations --check --dry-run` прошли.

## Автоматические проверки

Новый backend suite `test_ai_chat_requests.py` проверяет:

- отсутствие/ошибочный UUID без записи контекста и расхода rate limit;
- точное воспроизведение status/body после потерянного ответа, несмотря на старую expected revision;
- разные messages, markers, revision и дополнительные поля при том же UUID;
- независимость owner/date namespaces и явный новый UUID для нового действия;
- terminal provider error, его replay и осознанный новый retry;
- rollback расписания при падении сохранения receipt, затем lease recovery;
- старый worker после takeover и сохранение identity после удаления Schedule;
- два отдельных процесса, отправляющих один и тот же HTTP-запрос через настоящий view: один provider call, один блок, одна revision и одна terminal row.

Frontend tests покрывают потерю fetch и response body, пустой HTTP 200 и receipt для другого UUID, неизменность повторяемого JSON, pending/recovery без второго user bubble, terminal provider errors, remount, старый receipt при новой ручной revision, Logout и logical clear, root boundary и недоступный sessionStorage. Отдельные component tests проверяют recovery control и очистку после ухода со Schedule.

| Проверка | Результат |
| --- | --- |
| `make check` | Ruff, backend, type-check и frontend прошли |
| Backend | 2136 passed, 1 skipped, 20,38 с |
| Frontend | 1409 passed, 104 файла, 11,26 с |
| Production assets | Три rehearsal-сборки прошли; последняя `durable-chat-20261020-verified` |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| Deployment image-retention tests | PASS |
| Django checks / migration drift / SQLite integrity | Прошли |

Пропущен opt-in платный R11 comparison; обычный фиксированный dialogue corpus вошёл в полный backend-прогон. Дополнительное удалённое PR CI и ревью выполняются при создании PR.

### Проверка PR #252

Первый удалённый [CI](https://github.com/erzhan12/day-forge/actions/runs/39474195686) прошёл: 2136 backend, 1 skipped и 1409 frontend, lint, type-check, production build, dependency audit и deployment checks. [Claude Review](https://github.com/erzhan12/day-forge/pull/252#issuecomment-6298151186) дал **APPROVED**, без блокирующих замечаний.

По замечаниям ревью исправлено сохранение пустого списка `outcomes` в audit, добавлены два регрессионных теста, worker для двухпроцессной проверки вынесен в отдельный Python-файл под lint, а поле `response_body` получило комментарий о retention. Повторный локальный `make check` прошёл: **2138 backend, 1 skipped и 1409 frontend**. Migration drift отсутствует. Клиентский код и протокол recovery не менялись; браузерные результаты ниже относятся к сборкам до этой небольшой правки audit. Исходные hashes браузерного прогона сохранены в evidence отдельно от hashes правок после ревью.

Предложенный индекс только по дате отложен: текущие запросы используют owner/date/UUID и существующий unique index, запросов по одной дате нет. Удаление identities по возрасту противоречит принятому контракту. Если появится отдельная операция по дате, индекс следует добавлять вместе с ней и проверкой её query plan.

## Браузерные проверки

Стенд использует существующий `release_browser_server.py` и новый loopback-only `chat_request_proxy.py`. Proxy передаёт запросы настоящему backend, теряет уже полученные ответы, возвращает пустой HTTP 200 либо отправляет две одинаковые копии одновременно. Provider responses не подменялись.

| Сценарий | Наблюдение |
| --- | --- |
| Desktop 1440×900, drop-once | Первый ответ потерян после commit; второй POST с тем же UUID и SHA-256 тела получил сохранённый результат. Один блок, один AI audit, рабочий Undo |
| Пустой HTTP 200 | После commit proxy вернул ответ без JSON. Клиент повторил исходный UUID и получил сохранённый результат; один блок и рабочий Undo |
| Mobile 390×844, drop-until-recover | Оба ответа потеряны, серверный GET показал один блок. UI удержал исходный запрос и заблокировал новый ввод |
| Restart backend и reload | Обычный restart сохранил SQLite и session. Recovery control и исходный текст восстановились; Recover получил terminal response без нового provider call |
| Parallel | Proxy одновременно отправил две копии одного POST. Backend вернул 409 и 200, создал один блок. Повторено для явного нового turn с другим UUID |
| Новый явный повтор | После Undo пользователь попросил то же название на другое время. Новый UUID создал именно новый блок; последующий Undo прошёл |
| Более новая ручная запись | После потерянных ответов добавлен `Concurrent manual`. Replay прежнего AI receipt не убрал ручной блок; свежий GET подтвердил оба изменения на revision 16 |
| Manual / deletion | Create, rename, toolbar Undo, Cancel удаления, Delete и восстановление через Undo прошли |
| Draft | Новый пустой день получил шесть блоков через реальный draft call. Undo и reload вернули пустой день |
| Навигация | Settings, Back/Forward, Analytics и дата сохранили нужный baseline |
| Logout | Mobile и desktop: Login, Back/reload и защищённые URL не восстановили приватный Schedule |

Proxy зафиксировал 14 transport attempts для 7 chat UUID. У всех повторов одного UUID совпал SHA-256 исходного тела. В двух parallel experiments upstream statuses были `[409, 200]`. Число реальных AI-операций определено по успешным AIInteraction; внутренние retries SDK отдельно не подсчитывались. В базе семь завершённых chat identities и семь успешных chat audit rows; отдельно один успешный draft audit. Добавленные тестовые блоки убраны, fixture sessions завершены Logout. Исходные baseline-блоки стенда сохранены.

На второй сборке `durable-chat-20261020-final` повторены mobile recovery с более новой ручной записью, ручное редактирование, draft/Undo, desktop drop-once/Undo и Logout. Более ранняя сборка дополнительно проверила restart/reload recovery. После проверки HTTP-обработки добавлена третья сборка `durable-chat-20261020-verified`: пустой HTTP 200 после commit также восстановился повтором исходного запроса. Все версии assets записаны в evidence. Mobile означает Chromium viewport; iOS Safari и production ASGI/Redis нагрузка этим прогоном не проверялись.

Машиночитаемый журнал: [DURABLE_AI_CHAT_REQUESTS_BROWSER.json](evidence/DURABLE_AI_CHAT_REQUESTS_BROWSER.json). Он содержит безопасные fixture observations, proxy digests/statuses, aggregate DB checks и hashes снимков. Credentials, cookies, restore proofs и production-записи исключены. Непрерывный HAR не записывался.

| Снимок | Что показывает |
| --- | --- |
| [Пустой HTTP 200](screenshots/durable-chat-2026-10-20/verified-empty-response-recovery.jpg) | Блок и сохранённый ответ после пустого HTTP 200 на последней сборке |
| [Desktop recovery](screenshots/durable-chat-2026-10-20/final-desktop-recovered.jpg) | Блок и полученный ответ на второй сборке |
| [Mobile pending](screenshots/durable-chat-2026-10-20/mobile-pending.jpg) | Исходный запрос и recovery после потери обоих ответов |
| [Recovery после restart](screenshots/durable-chat-2026-10-20/mobile-recovered-after-restart.jpg) | Сохранённый ответ после reload |
| [Parallel](screenshots/durable-chat-2026-10-20/mobile-parallel-once.jpg) | Один блок после двух одновременных запросов |
| [Recovery при ручной правке](screenshots/durable-chat-2026-10-20/mobile-preserved-newer-edit.jpg) | Полученный ответ; дополнительные блоки вне кадра, их сохранение подтверждено свежим GET в evidence |
| [Реальный draft](screenshots/durable-chat-2026-10-20/mobile-real-draft.jpg) | Сгенерированный день |
| [Logout](screenshots/durable-chat-2026-10-20/final-logout.jpg) | Login после защищённого URL |

Байты снимков сохранены без обработки. Viewport измерен через DOM; размер native JPEG может отличаться от viewport.

## Воспроизведение

1. Создать новый приватный каталог под `/tmp`. Собрать frontend с `RELEASE_VERSION` и `--outDir ROOT/build` внутри него.
2. Запустить `uv run python backend/scripts/release_browser_server.py ROOT ROOT/build`. Он создаёт собственную базу, применяет миграции и seed. Для live AI нужны локальные рабочие provider credentials. Настройки integrations должны быть fixture-only; polling отключён, аккаунты не подключены.
3. После создания marker запустить `uv run python backend/scripts/chat_request_proxy.py ROOT`. Открыть `http://127.0.0.1:8009/accounts/login/` и войти известным локальным fixture-пользователем из `release_browser_server.py`. Его пароль нельзя использовать на production.
4. Установить файл `ROOT/chat-proxy-mode` в `drop-once`, `drop-until-recover`, `empty-once` или `parallel` до отправки нового chat turn. Для ручного recovery после двойной потери переключить файл в `pass` и нажать Recover. Режим parallel дублирует первую попытку каждого нового UUID.
5. Проверить `ROOT/chat-proxy-evidence.jsonl`, fixture `ai_chatrequest` и `ai_aiinteraction`, затем Undo/cleanup, Logout и остановку только созданных процессов. Proxy не предназначен для production и публикуется только на loopback.

Server-owned pending intent, понимание отказа, semantic replay между разными UUID и качество модели остаются отдельными задачами. Этот шаг реализует durable transport identity и не удаляет прежние replay/intent эвристики.
