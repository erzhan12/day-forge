# Cleanup после итогового аудита

Дата: 18 октября 2026 года. База: `6278511` (`main` после PR #243). Выполнены кандидаты из раздела «Что можно сократить или удалить» в [итоговом аудите](REFACTORING_FINAL_AUDIT.md).

## Что удалено и упрощено

| Область | Изменение и основание |
| --- | --- |
| AI rules | Удалён `_load_active_rules` и оставшийся без использования импорт `User`. Правила уже читаются в `_load_ai_context_sync` и повторно проверяются при применении. Комментарии тестов теперь называют действующий путь. |
| Planner | Удалён реестр `POLICIES`, на который не было ссылок. Прямые константы политик остаются в вызывающих модулях. |
| HTTP validation | Удалены три неиспользуемых re-export из `templates_mgr.api` и два HTTP wrapper: `validate_five_minute_or_error`, `validate_time_range`. Parser `parse_time_or_error`, парная проверка времени и доменные валидаторы сохраняют действующих потребителей. |
| AI errors | У `_action_error` удалён параметр `status`. Все вызовы используют HTTP 400; форма ответа сохранена. |
| Chat | `submitTurn` принимает текст и `pushUndo`. Удалена передача неиспользуемого snapshot callback через Schedule, ChatSidebar и CommandBar. Предыдущие блоки для Undo приходят из подтверждённого `result.mutation`. |
| Undo injection | В `ScheduleUndoContext` остался `pushUndo`; completion использует этот общий тип. Тестовые providers обновлены. Прямой `snapshotBlocks` в useUndo и drag остаётся. |
| Lifecycle API | Удалены exports `clearChatSession`, `clearDraftSession`, `useProvidedFocusIndicatorController` без потребителей и пять лишних return members page controller. Внутренние reset/dispose и привязка состояния к владельцу продолжают работать. |
| Timeline4a | `presentation` обязательна. Удалены fallback builder, девять дублирующих входов геометрии/состояния и неиспользуемые exposed значения. В composable удалён оставшийся без потребителей `timelineEndMinutes`; конец оси доступен в самой presentation. Страница передаёт готовую модель; тесты строят её тем же builder. |
| Дополнительный мёртвый модуль | Удалён `frontend/src/utils/scheduleDiff.ts`. Поиск по приложению, тестам, конфигурации и scripts не нашёл импортов. Признак изменения и снимок для Undo уже принадлежат mutation controller и `registerMutationUndo`. Остались только упоминания старого решения в исторических планах. |
| Starter entry point | Удалён корневой `main.py` с `Hello from day-forge!`. Команды, deployment и доступные IDE launch settings его не используют. |
| Старый smoke script | Удалён `scripts/test10_audit_envelope.py`: запросы без revision, устаревший audit envelope, неверная обработка exit status, изменение `.env` и перезапуск серверов. Скрипт не запускался. |
| Claude instructions | CLAUDE.md ссылается на AGENTS, RULES, архитектуру, API и текущий runbook. Удалены повторяющиеся предупреждения о старом WSGI deployment и устаревшая карта фаз. Указан обязательный пользователь для seed. `.claude/rules/workflows.md` использует общие Make targets; Claude-specific safety/lessons rules сохранены. |

Поиск охватывал исходники, тесты, конфигурацию, deployment, scripts и доступные IDE settings. Исторические feature plans оставлены как записи прежних решений.

## Покрытие удалённого audit-скрипта

`backend/tests/test_ai_views_chat.py::TestAuditEnvelope` уже проверяет SHA-256 переданного transcript, число сообщений, текущий `kind=chat`, сохранение raw и отсутствие error class при успехе. В успешный сценарий добавлены assertions `success is True` и `actions_json == []`.

Ошибочный сценарий параметризован по unavailable, timeout, provider, invalid-input и parse errors. Он проверяет HTTP status, `success=False`, пустые actions, hash, число сообщений и конкретный error class. Для parse error отдельно проверяются безопасное клиентское сообщение и сохранённый error detail. Эти тесты используют штатный revision-aware HTTP helper и изолированные записи базы.

## Проверки

- Затронутые backend-наборы: 324 passed. Chat/draft, правила, planner, время и templates API.
- Затронутые frontend-наборы до последнего уточнения fixture: 310 passed. Chat/draft, компоненты, page controller, completion, Undo consumers, Schedule и drag.
- Полный backend: 2092 passed, 1 skipped. Пропущен opt-in платный live R11 comparison.
- Полный frontend после исправления fixture: 1392 passed, 102 файла.
- Ruff, frontend type check и production build прошли.
- `npm --prefix frontend audit --omit=dev --audit-level=high`: 0 vulnerabilities.
- `bash deployment/tests/test_image_retention.sh`: PASS.
- Deployment SSH pinning: все 7 команд SSH/SCP используют strict host checking и pinned known_hosts.
- `git diff --check`: без ошибок.

В frozen-drag тесте родитель теперь пересчитывает presentation при изменении часов и масштаба. Проверяются неизменные высота canvas и положение блока, а также обновление подписи текущего времени внутри видимой оси. Новое время в fixture остаётся в пределах замороженной оси, где NowLine должна быть видна.

Новые браузерные сценарии и реальные provider calls в этом cleanup не запускались. Результаты предыдущих browser/live прогонов сохранены в [основном отчёте](BROWSER_VERIFICATION_DESKTOP_MOBILE.md), [A00–A07](BROWSER_VERIFICATION_A00_A07.md) и [R11 comparison](R11_LIVE_COMPARISON.md).

## Размер и границы

Чистое сокращение относительно базы, с комментариями и пустыми строками:

| Группа | Сокращение |
| --- | ---: |
| Backend runtime | 55 строк |
| Frontend runtime | 127 строк |
| Старый script и starter entry point | 269 строк |
| Тесты после обновления fixtures | 18 строк |
| CLAUDE.md и Claude workflows | 101 строка |

Production-модули сокращены на 182 строки. С удалёнными script/entry point сокращение кода составляет 451 строку. Новые строки отчёта не включены в эти показатели; размер bundle не используется как доказательство эффекта, поскольку dead exports могли исключаться сборщиком раньше.

`CommandPlan.candidates` и `.restore` остаются до отдельного решения о минимальном контракте planner. Migration-imported `schedules/validators.py`, политики источников, provider adapters, revision/replay guards и lifecycle-защиты остаются необходимыми. Открытые PiP/iOS и продуктовые вопросы перечислены в [tasks/todo.md](../tasks/todo.md).
