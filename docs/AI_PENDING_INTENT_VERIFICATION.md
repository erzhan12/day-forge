# Server-owned AI pending intent: реализация и проверки

22 октября 2026 года. Основа: `main` после PR #259 (`995efbb`). Контракт записан первым отдельным коммитом `47917fd`: [AI_PENDING_INTENT.md](AI_PENDING_INTENT.md). Реализация находится в ветке `codex/server-owned-pending-intent`.

## Что изменилось

Миграция `ai.0008_pendingintent` добавляет серверную запись незавершённого запроса. На пользователя и Schedule разрешена одна открытая запись. UUID и независимая version ограничивают ответы, включая уточнения без изменения revision расписания. Срок исполнения составляет 15 минут и не продлевается вопросами.

`ai/pending_intents.py` проверяет owner, Schedule/date, состояние, expiry, revision и fingerprint контекста. Продолжение может заполнять сохранённые недостающие поля и выбирать существующий target из разрешённого списка. Известные значения сохраняются, принятые siblings не повторяются. Повторный вопрос не может расширить scope или скопировать одно разрешение в несколько действий. Ответ на одно поле сохраняет остальные незавершённые поля. Untimed add не может обойти сохранённый вопрос о времени.

При частичном применении accepted IDs берутся из результата persistence, без поиска по title и без доверия к assistant markers. Для оставшейся части сохраняются revision и fingerprint после записи. Отклонённый интервал сохраняет известную длительность. Намерение, расписание и durable receipt фиксируются атомарно под User lock; provider call выполняется вне транзакции. Ошибка поздней проверки откатывает план, после чего её terminal response сохраняется отдельно в той же внешней транзакции.

Для продолжения провайдер получает последнюю реплику и серверное summary. Предыдущая клиентская история не отправляется; импортированные названия маскируются и в summary. Новая команда вместо ответа проходит повторную интерпретацию только по последней реплике. `cancel` и `read` не применяют model actions. Явная Cancel обходит провайдера и rate limit, использует собственный durable request_id и не создаёт Undo.

Клиент хранит UUID/version намерения и включает их в замороженное тело запроса. Неопределённый transport outcome восстанавливается с прежним request_id и полным телом, включая ссылку на намерение. Clear, дата, аккаунт и session reset убирают ссылку. Устаревшее намерение запускает reconciliation дня перед следующей записью; Undo при таком конфликте консервативно инвалидируется, в том числе при expiry.

Обновлены API, архитектура, RULES, R11 design, итоговый аудит, список задач, README и rollback runbook. Privacy Policy теперь различает переписку новой команды и summary продолжения и сообщает о хранении receipts/intent records. Дата текста обновлена на 22 октября.

## Найденные ошибки и исправления

- Живая модель классифицировала собственный вопрос как `read`. Уточнено, что decision относится к последнему пользователю; все примеры ответа теперь содержат metadata. Повторный живой запрос создал intent и успешно применил ответ `14:00`.
- В одном живом вопросе модель вернула pending type `move`. `move`/`resize` нормализуются к каноническому `update` до проверки scope; ownership и разрешённые поля проверяются после нормализации.
- Проверка повторного вопроса первоначально позволяла использовать один исходный scope несколько раз. Теперь каждое предложение потребляет отдельное старое разрешение. Есть отрицательный тест дублирования вопроса.
- Ответ на одно поле мог преждевременно закрыть оставшиеся поля. Они сохраняются отдельной незавершённой частью с обновлёнными известными значениями и fingerprint.
- Конфликт повторного размещения мог расширить временные поля либо потерять известную длительность. Продолжение ограничивается прежним scope; длительность явного интервала сохраняется.
- Stale intent после записи в другой вкладке требовал обновления canonical state. Этот ответ теперь проходит через существующий механизм reconciliation.

## Автоматические проверки

Выполнены `make check` (2202 backend tests, один skip; 1422 frontend tests в 104 файлах), production frontend build, production dependency audit (0 vulnerabilities), проверка синтаксиса двух изменённых browser scripts и SSH pinning gate (7/7). Type-check и Ruff прошли. Результаты: [checks.json](evidence/server-pending-intent-2026-10-22/checks.json).

Единственный skip относится к отдельному платному R11 comparison, который включается через `R11_LIVE_AI=1`. Он не запускался: эвристики не удалялись, а реальные AI-сценарии этой задачи пройдены через браузер. Тесты можно повторить командами `make check` и `make frontend-build`; focused checks находятся в `test_ai_pending_intents.py`, `test_ai_pending_concurrency.py`, `test_ai_service_chat.py`, `useChat.test.ts` и `chatRequestRecovery.test.ts`.

Новые backend-проверки охватывают сохранение и replay вопроса, завершённого ответа и отмены; expiry/version; чужого owner и дату; изменение политики и revision до сети и во время неё; расширение actions/targets/полей; известную длительность; непринятых siblings; повтор принятой части; legacy question без executable scope; поздний rollback с сохранением receipt; неполный ответ и запрет untimed обхода. Ссылка на удалённый Schedule не создаёт его заново и не забирает first-visit auto-draft signal. Отдельные процессы с собственной SQLite connection встречаются внутри provider call: для apply и ask-only ровно один результат 200 и один 409. Ask-only меняет version с 1 на 2 при revision 0; apply создаёт один блок при revision 1.

Frontend-проверки охватывают UUID/version, Cancel и disabled state, clear/date boundaries, stale reconciliation, неизменность transport retry, remount recovery и отклонение повреждённой ссылки из sessionStorage. Service tests проверяют отсутствие forged transcript в provider context, privacy redaction, decision enum, discard actions при cancel/read и нормализацию pending aliases.

Миграция проверена на SQLite backup рабочей базы, открытой только для чтения. Обновление `ai.0007` → `ai.0008` сохранило 1043 строки в 22 существующих таблицах. Все прежние content types и permissions сохранились; Django добавил один content type и четыре permissions для новой модели. Исходный файл базы не изменился. См. [migration.json](evidence/server-pending-intent-2026-10-22/migration.json).

После проверки на копии выполнен `make migrate` для локальной рабочей базы. План содержал только `ai.0008_pendingintent`. Повторная сверка подтвердила сохранение всех тех же 1043 строк и прежних metadata rows; добавлены только новая таблица, content type и permissions. `manage.py check` и `makemigrations --check --dry-run` прошли. Временные копии с рабочими данными удалены после проверки. См. [local-migration.json](evidence/server-pending-intent-2026-10-22/local-migration.json).

## Браузер и реальный AI

Изолированная SQLite, отдельный неадминистративный fixture user, Redis с собственным key prefix, loopback `localhost:8007` и production assets. Реальный SDK и настроенный OpenRouter использовались без подмены ответов. Production и рабочая база не обслуживали эти сценарии. Взаимодействия выполнялись через встроенный браузер.

Desktop 1440×900: свежий вход, вопрос о переносе Gym, ответ `14:00`, перенос только Gym и Undo; частичное применение Kept + конфликтующий Conflict, уточнение `16:00`, ровно один Kept и один Conflict, два Undo; явная Cancel и Logout. Счётчик AIInteraction до и после Cancel остался 6, revision дня не изменилась.

Mobile 390×844: свежий вход, вопрос, отказ `No, do not move Gym`, отсутствие записи и Undo; новая команда `Add Walk at 15:00` вместо ответа на вопрос о Gym, сохранение исходного Gym и Undo Walk; частичное применение и завершение только Conflict с сохранённой длительностью 30 минут, два Undo.

Узкое окно 320×740: кнопка Cancel полностью помещается в экран. При `window.innerWidth=320` clientWidth и scrollWidth равны 305 с учётом scrollbar; горизонтального переполнения нет. Cancel убирает вопрос без записи и Undo.

Clear при открытом вопросе убрал Cancel и историю; новый вопрос после Clear получил отдельный UUID. Переход с открытым вопросом с 7 на 8 сентября убрал ссылку и переписку прежней даты. Затем вторая вкладка отметила Focus выполненным (revision 1). Ответ `14:00` в первой получил durable `409 pending_intent_stale`, не изменил revision и не вызвал AI: число AIInteraction осталось 17. Первая вкладка обновила checkbox Focus, показала ошибку и убрала Cancel. Новая русская команда перенесла только Gym на 14:00; Undo вернул Gym на 09:00 и сохранил completion Focus из другой вкладки. После возврата completion в исходное состояние Logout и Back показали Login.

Основной fixture содержит 18 записанных AI-turns, в том числе один отклонённый до исправления alias. Перед ним был отдельный первоначальный probe с ошибочной классификацией `read`. Новая команда во время уточнения использует два provider calls; число audit rows не является счётчиком SDK-вызовов. Сохранены [обезличенные receipts, scopes и итоговые блоки](evidence/server-pending-intent-2026-10-22/browser.json), без signed restore proofs, cookies и API key. Все fixture-дни вернулись к исходным интервалам и completion; Clear/date намеренно оставляют серверные записи до следующего запроса или expiry.

Скриншоты: [desktop: принятая часть](evidence/server-pending-intent-2026-10-22/desktop-partial.jpg), [desktop: завершение](evidence/server-pending-intent-2026-10-22/desktop-partial-resolved.jpg), [mobile: отмена](evidence/server-pending-intent-2026-10-22/mobile-320-pending.jpg), [mobile: stale и reconciliation](evidence/server-pending-intent-2026-10-22/mobile-stale-reconciled.jpg), [mobile: Logout/Back](evidence/server-pending-intent-2026-10-22/mobile-logout-back.jpg).

## Границы результата

Живой smoke проверяет конкретные диалоги, а не частоту семантических ошибок модели. Модель может ошибиться в классификации либо не вернуть часть намерения. Например, в отдельном запросе Accepted + Outside модель добавила только разрешённый Accepted и объяснила отказ Outside без structured ask. Намерение не выводится из свободного текста такого объяснения; Undo вернул исходный день. Это отдельный случай качества модели, а не разрешение повторять принятый блок.

Legacy question без metadata сохраняется без executable actions и требует отмены/очистки и новой формулировки. Записи intents остаются до удаления Schedule/аккаунта; expiry запрещает исполнение, но не удаляет данные. Существующие replay, implicit-add и category guards сохранены. Для их удаления нужен новый контролируемый live comparison.

Production deploy и контейнерная репетиция этой новой миграции в задачу не входили. При rollback на код без pending-intent поддержки AI следует приостановить, сохранив `ai_pendingintent` и durable receipts. Обратная миграция удалит intents и не должна сопровождать обычный image rollback. Реальный iOS Safari остаётся отдельной проверкой.
