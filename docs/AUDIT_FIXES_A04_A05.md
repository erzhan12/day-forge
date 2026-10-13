# Исправления A04 и A05

Дата: 11 октября 2026 года. Исправлены A04 и A05 из [итогового аудита](REFACTORING_FINAL_AUDIT.md). Изменения находятся в локальном рабочем дереве вместе с R00–R12 и A00–A03. Новых моделей и миграций нет; рабочая БД в этой задаче не менялась.

Два субагента Sol high реализовали backend AI и frontend Google Calendar. Третий проверил границы изменений без редактирования файлов. Основной агент проверил переход от ответа к следующему transcript, запустил полные suites, production build и HTTP-сценарии, обновил документацию.

## A04: допустимый ответ должен давать допустимое сообщение истории

Раньше chat envelope принимал пустое `explanation` при `ask: null`. Frontend сохранял его как `assistant.content`, и следующий запрос получал 400 из-за пустой истории. `ask` из пробелов также не был настоящим вопросом, но проходил response validation.

В [schemas.py](../backend/ai/schemas.py) закреплён контракт chat-ответа модели:

- Если `ask` равен `null`, `explanation` должен содержать текст после удаления крайних пробелов. Это относится и к no-op, и к ответу с действиями.
- Если `ask` задан, он должен содержать непустой вопрос. Пустое или состоящее из пробелов `explanation` при настоящем вопросе остаётся допустимым: frontend использует вопрос как content.
- Выбранный текст `ask ?? explanation` должен помещаться в `LLM_MAX_COMMAND_CHARS`, даже если отдельный output cap настроен выше. Существующие лимиты explanation и ask также сохраняются.

Проверка выполняется в service до обработки действий. Недопустимый provider reply возвращает существующий фиксированный 502: `The assistant's reply couldn't be applied. Try rephrasing.` Действия из него не применяются. Диагностика и raw response остаются в failure audit; они не попадают в клиентский error detail. Попытка провайдера расходует существующий rate-limit budget.

[Входная проверка transcript](../backend/ai/views.py) теперь отклоняет content из одних пробелов для любой роли. Это 400 до вызова провайдера. Frontend уже обрезает пользовательский ввод. Текст ответа модели не заменяется выдуманным сообщением; `is_ask`, `is_error` и replay markers сохраняют прежний смысл. Draft validation не изменялась: черновик не создаёт сообщения chat history.

В [test_ai_response_history.py](../backend/tests/test_ai_response_history.py) реальные views и service работают с фиксированными SDK-ответами. Проверены пустота и whitespace, no-op и допустимый add с недопустимым текстом, неизменность revision/блоков при отказе, безопасный error detail и failure audit. Отдельный диалог проходит ask с пустым explanation → действие → no-op; каждый следующий запрос несёт предыдущий assistant content и доходит до SDK. После parse failure следующий запрос принимает синтетический `is_error` bubble.

[Service tests](../backend/tests/test_ai_service_chat.py) проверяют и конфигурацию, в которой output cap больше лимита входного сообщения. В [useChat.test.ts](../frontend/tests/useChat.test.ts) существующая проверка следующего `is_ask` turn расширена на пустое и whitespace explanation. Контракт проверяется с обеих сторон, без изменения самого composable.

## A05: полный сбой Google сохраняет последний успешный список

Google events endpoint сохраняет HTTP 200 с `events` и `account_errors` при отказах отдельных аккаунтов. Метаданные отличают успешный результат `ready` от полного отказа `provider_error` или `credentials_error`. Раньше frontend принимал любой такой 200 как новый список и заменял события на `[]`.

В [useDatedResource](../frontend/src/composables/useDatedResource.ts) добавлен необязательный typed hook `onFailedSuccess`. После проверки ответа adapter может вернуть сообщение ошибки, чтобы сохранить строки текущего date/context вместо вызова commit. Остальные adapters этот hook не используют; их обработка успешных ответов не меняется.

[Google adapter](../frontend/src/composables/useGoogleCalendar.ts) использует hook для пустых `events` с `provider_error` или `credentials_error`. Он обновляет `accountErrors`, сохраняет последние успешные события текущего контекста, выставляет `resourceState` и видимую `state.error`. Для credentials failure предлагается reconnect, для provider failure повторная загрузка.

Поведение остальных ответов сохраняется:

- `ready` с пустыми events очищает прежние строки, включая случай успешного пустого аккаунта рядом с отказавшим аккаунтом.
- Partial success заменяет список событиями успешных аккаунтов и показывает per-account ошибки.
- Первый полный отказ показывает ошибку без событий. Смена даты, saved zone или account/session context очищает прежние данные.
- Disconnect очищает события, account errors и pending reads. Старый ответ не возвращает удалённые строки.

`useExternalSources` превращает Google `state.error` в provider banner. [ExternalEventsPanel](../frontend/src/components/ExternalEventsPanel.vue) уже отображал ошибки независимо от списка; его runtime-разметку менять не потребовалось. При полном отказе рядом остаются события и per-account сообщения. Без last-good списка панель показывает ошибку, не сообщает об успешном пустом календаре.

Регрессии в [useGoogleCalendar.test.ts](../frontend/tests/useGoogleCalendar.test.ts) используют backend-shaped metadata и проверяют provider/credentials failures, успешный пустой ответ, partial success, первый отказ, смену даты/контекста и disconnect. [useExternalSources.test.ts](../frontend/tests/useExternalSources.test.ts) монтирует настоящую панель вместе с controller: ошибка и сохранённое событие видны одновременно, а fresh disconnected bootstrap очищает их. Живой Google OAuth и внешние аккаунты в этой задаче не использовались.

## Проверки

| Проверка | Результат |
|---|---|
| `make check` | Ruff, 1980 backend-тестов, frontend type-check и 1381 frontend-тест в 102 файлах прошли |
| `make frontend-build` | Type-check и production Vite build прошли |
| Django system check | Нет замечаний |
| `makemigrations --check --dry-run` | Нет изменений моделей |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| `git diff --check` | Прошёл |
| Независимый review | Блокирующих замечаний по A04/A05 не осталось |

Production assets: app.js 482,53 КБ, gzip 158,70 КБ; CSS 70,48 КБ, gzip 12,23 КБ. Backend suite занял 20,54 с, frontend suite 17,98 с; это время текущего прогона, не benchmark.

### Основные сценарии через HTTP

Runner `/tmp/day_forge_http_smoke_a04_a05.py` использует `Django Client(enforce_csrf_checks=True)`, новую временную SQLite БД и синтетического пользователя. Все 44 проверки прошли. Сохранены предыдущие сценарии login/CSRF, Schedule/Settings, CRUD/reorder, stale 409, навигации по дням, SQLite contention, импорта, completion, AI chat/draft, Undo, notes/review/category maintenance и logout.

Добавлены parse failure с допустимым add и проверкой неизменности блока, статуса и revision, затем успешный chat turn с error history. Всего выполнены четыре вызова заглушки SDK.

Google endpoint проверен с двумя синтетическими аккаунтами и заглушкой service: готовые события, полный provider failure, полный credentials failure, partial success, partial empty success, успешный пустой календарь, отключение обоих аккаунтов и disconnected 503. Проверяются настоящие HTTP envelopes; сохранение списка и видимость banners отдельно проверяются во Vue tests.

Логи находятся в `/tmp/day-forge-a04-a05/`. Runner, SDK messages, Google envelopes и временная БД являются диагностическими файлами и могут исчезнуть при очистке `/tmp`. Реальных AI/Google provider-запросов не было. Фиксированные ответы проверяют приложение и wire-контракт, не качество модели или доступность внешнего сервиса.

### Ограничение браузера

В предыдущем запуске встроенный браузер отклонил открытие `http://localhost:5173/accounts/login/` по политике безопасности URL. Ответ прямо запретил обход через другие браузерные поверхности, raw CDP и косвенные команды. Данных об изменении политики нет; такие обходы не выполнялись.

Браузерная проверка, реальные клики, визуальное состояние Schedule и мобильная ширина остаются непроверенными в этом запуске. HTTP и mounted component tests не заявлены как browser smoke. Для закрытия ограничения нужен разрешённый браузерный сеанс.

## Следующая работа

A06 и A07 остаются отдельными исправлениями из итогового аудита. Browser verification A00–A05, первый PR CI run и deployment smoke остаются в [todo](../tasks/todo.md). Контролируемое сравнение живой модели не входило в эту задачу.
