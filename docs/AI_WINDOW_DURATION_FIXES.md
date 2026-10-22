# AI: рабочее окно и проверки изменения длительности

22 октября: [production smoke после PR #257](POST_PR257_PRODUCTION_VERIFICATION.md) подтвердил опубликованный релиз и CSS переноса. Свежий вход, реальные chat/draft, Undo и Logout прошли на desktop/mobile. Временный шаблон удалён, три тестовых дня пустые.

18 октября 2026 года. Выполнены два пункта из [todo](../tasks/todo.md): исправлено уточнение при добавлении вне рабочего окна и дополнена матрица feature 0068. Новые проверки обнаружили ещё одну ошибку в результате частичного применения; она также исправлена.

## Уточнение для добавления вне окна

При настроенном дне 08:00–20:00 добавление Meeting на 06:30–07:00 или 20:05–20:35 отклонялось правильно, но UI получал общий ответ о свободных начале и конце. Причина: `_build_resolution_ask` выбирал generic skipped-create до проверки `out_of_window`.

Теперь сервер возвращает установленное сообщение:

> That time is outside your schedule window. Please give a time within your day.

Приоритет: конкретное предложение свободного слота, вопрос о направлении, неразрешимый конфликт, отсутствие слота в выбранном направлении, `no_slot`, `out_of_window`, общий skipped-create, прочие ошибки интервала. Более конкретные прежние вопросы остаются выше вопроса о рабочем окне. Выбор типа вопроса проверен при обоих порядках outcomes. Обычная ошибка другого create по-прежнему использует общий ответ.

HTTP-регрессии проверяют пользовательское окно, отсутствие новых блоков, сохранение существующего блока, статуса draft и revision 0. Тест на новое уточнение сначала падал на прежнем сообщении, затем прошёл после изменения порядка веток.

## Найденная ошибка: resize → metadata

Исходный Lunch занимает 12:00–13:00, Meeting 13:00–14:00. В одном turn модель предлагает Lunch длительностью 90 минут, затем переименовывает его. Увеличение времени должно быть отклонено из-за конфликта, а переименование может примениться.

До исправления нормализация намеренно не помещала конфликтующее время в `chain_effective`, чтобы последующий move не наследовал неверную длительность. Но metadata-follow-up наследовал флаг duration и вычисленные минуты, взяв фактический конец из старого effective interval. Проверка пересечения видела 13:00 вместо запрошенных 13:30. В БД время оставалось прежним, а outcome ошибочно сообщал `applied` без конфликта и вопроса.

При наследовании duration provenance теперь также сохраняется `prev.new_end`. Это удерживает попытку изменения для проверки, не передавая отклонённую длительность следующему move. Итог: название изменено, время обоих блоков прежнее, `end_time` пропущен, outcome `partial`, reason `overlap`, есть вопрос о более раннем или позднем слоте. Revision увеличивается только из-за принятого переименования.

Регрессия воспроизведена в pure planner test: до исправления ожидался `partial`, получался `applied`. HTTP-тест отдельно проверяет результат, неизменность интервалов и сохранённое название.

## Дополненная матрица

| Группа | Проверяемые границы |
| --- | --- |
| Длительность | Absolute и relative до ровно пяти минут; конец ровно на day_end; выход за day_end; точная полночь; relative crossing-midnight; длительность больше 24 часов; большие положительные duration/delta и отрицательный delta до миллиарда минут. Нет wraparound и ValueError. |
| Порядок отказов | End 00:00 и отрицательный end дают interval. Sub-five-minute off-grid результат даёт interval раньше granularity. Off-grid конец за окном даёт out_of_window раньше granularity. |
| Legacy-границы | Неизменённый start до окна допустим, если новый end достигает окна. Неизменённый off-grid start не мешает допустимому on-grid end. End, оставшийся до day_start, отклоняется. |
| Цепочки | Move → duration сохраняет обе границы; duration не наследует прежний supplied-end clamp или bare-move provenance. Проверены унаследованные start до окна и off-grid start. |
| Непредставимый end | Положительный и отрицательный выход за сутки × последующие relative resize, move и metadata. Время не восстанавливается из clamped stand-in. Независимое переименование может примениться частично. |
| Пересечения | Неизменённый сосед, изменяемый сосед и смешанный набор. Сохранены reason overlap/unresolved_conflict, IDs конфликтов и исходные интервалы. |
| Предложения | Earlier и later предложения используют запрошенную ширину 90 минут, а не старые 60 минут. При exact конфликте остаётся вопрос о направлении. |
| Metadata | Duration → rename сохраняет принятый end либо отклоняет конфликтующий end с partial outcome. Проверены оба результата. |
| HTTP | Четыре пользовательские формулировки: 20 минут, один час, на 30 минут длиннее, на 15 минут короче. Добавлены проверки полночных/больших/отрицательных/off-grid отказов, пользовательского day_end, конфликта и частичного переименования. |

Основные файлы: [planner tests](../backend/tests/test_ai_mutation_planner.py), [chat view tests](../backend/tests/test_ai_views_chat.py), [planner](../backend/ai/mutation_planner.py), [resolution ask](../backend/ai/views.py). Формат действий и API не менялся; миграций нет.

## Проверки

- Фокусные planner + chat view: 294 passed.
- Полный backend: 2092 passed, один opt-in платный R11-тест пропущен.
- Полный frontend: 1392 passed в 102 файлах.
- Ruff, Vue type-check, production build и `git diff --check` прошли.
- Обычный suite не обращается к AI-провайдеру. HTTP-тесты используют управляемый `run_chat` и настоящий planner/persistence; они проверяют серверный контракт, а не качество распознавания живой моделью.

Команды из корня проекта:

```sh
uv run pytest backend/tests/test_ai_mutation_planner.py backend/tests/test_ai_views_chat.py -q
uv run pytest backend/tests/ -q
uv run ruff check backend/
cd frontend
npm run type-check
npm test
npm run build
```

## Дополнение 21 октября: отклонённый AI-draft

Завершена незакоммиченная правка поверх `2df2e50` (PR #255). Раньше генерация draft с блоком вне рабочего окна возвращала только `Times must fall within 05:00-22:00.` Из сообщения не было понятно, какой блок предложила модель и был ли сохранён остальной черновик.

Теперь `400` содержит прежние `errors.action_index` и `errors.detail`. Для `out_of_window` текст называет блок, его интервал, настроенное окно и результат отказа. Например:

> AI scheduled "Deep work" (21:30-22:30) outside your day window (05:00-22:00). The draft was not saved. Try generating it again.

Сообщение формируется в draft HTTP adapter из уже разобранной команды и настроек, проверенных под блокировкой. Общий planner, chat, правила рабочего окна, схема ответа и миграции не меняются. Ошибки других типов сохраняют прежний текст, включая `Blocks would overlap.`

Проверки через настоящий HTTP view, planner и persistence подтверждают:

- Для первого и второго действий выход до начала или после конца окна возвращает правильные index, название и время.
- Ни один блок не сохраняется, в том числе допустимый сосед. Revision 7, статус и `updated_at` существующего пустого расписания остаются прежними. Audit attempt не отмечается успешным.
- После отказа можно повторить генерацию с прежней revision. Блок ровно на границах 05:00–22:00 принимается, revision становится 1, статус остаётся draft. В audit остаются неуспешная и успешная попытки.
- Frontend передаёт подробный текст в `lastDraftError`, завершает spinner, сохраняет пустой canonical state и revision, не создаёт Undo и очищает ошибку после успешного повторного запроса.
- Если planner неожиданно вернул отсутствующий, отрицательный или выходящий за список index, adapter сохраняет исходный текст ошибки и `400`, не подставляя чужой блок и не выбрасывая `IndexError`. Эти три случая проверены через fault injection в HTTP suite.

Четыре тестовых случая нового сообщения проверены на исходном коде `2df2e50` в отдельной временной копии исходников. Все четыре упали на прежнем общем тексте. С правкой проходят. Рабочая база и исходники для этого сравнения не менялись.

Результаты локальной проверки:

| Проверка | Результат |
| --- | --- |
| Draft HTTP suite | 41 passed |
| Frontend `useDraft` | 11 passed |
| `make check` | Ruff, 2150 backend-тестов, один opt-in тест пропущен, Vue type-check и 1410 frontend-тестов в 104 файлах прошли |
| `make frontend-build` | Production build прошёл |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| `bash deployment/tests/test_image_retention.sh` | PASS |
| `git diff --check` | Прошёл |

Дополнительный `ruff format --check` показывает существующие отклонения в других частях `ai/views.py`: они воспроизводятся и на исходном `2df2e50`. Новый блок сообщения и изменённый Python-тест соответствуют formatter; постороннее форматирование в правку не включено. Обязательный Ruff lint проходит.

Этот прогон использует управляемый ответ `run_draft`, чтобы воспроизводимо получить обе ошибки рабочего окна. Живой AI и браузер здесь не запускались. Frontend проверен на границе composable; качество генерации и визуальное отображение этим дополнением не подтверждаются. Производственные данные и настройки не менялись.

Первое [Claude Review в PR #256](https://github.com/erzhan12/day-forge/pull/256#issuecomment-6318357868) вернуло APPROVED с двумя рекомендациями. Защита индекса добавлена вместе с тремя fault-injection случаями. Предложение перевести дополнение на английский не принято: существующий отчёт ведётся на русском, API-справочник и описание PR остаются английскими.

Второе [ревью](https://github.com/erzhan12/day-forge/pull/256#issuecomment-6318467852) также вернуло APPROVED. По его замечаниям fallback `None → 0` записан явным условием, а fault-injection тесты проверяют весь `errors`, включая ожидаемый `action_index`.

Команды для повторения из корня проекта:

```sh
uv run pytest backend/tests/test_ai_views_draft.py -q
make check
make frontend-build
npm --prefix frontend test -- --run tests/useDraft.test.ts
npm --prefix frontend audit --omit=dev --audit-level=high
bash deployment/tests/test_image_retention.sh
git diff --check
```

## Дополнение 22 октября: браузерная проверка AI-draft после PR #256

Проверена локальная production-сборка поверх `c21f9cc` через встроенный Chromium и CUA. Использованы два свежих fixture-окружения: до исправления CSS и после него. В каждом отдельная SQLite-база, non-staff аккаунт, namespaced localhost Redis и настроенное окно 05:00–22:00. Настоящий SDK transport заменён управляемым ответом; HTTP views, авторизация, CSRF, разбор ответа, planner и persistence работают без подмены.

### Проверенные сценарии

| Сценарий | Размер viewport | Результат |
| --- | --- | --- |
| Блок 04:30–05:30 до начала окна | 1440×900 и 390×844 | Правильные название, интервал и границы окна; HTTP 400; ни одного блока в БД; revision 7 и статус draft сохранены; Undo выключен |
| Блок 21:30–22:30 после конца окна | 1440×900 и 320×740 | Тот же атомарный отказ; допустимый сосед 09:00–09:30 также не записан |
| Клавиатурный Undo после отказа | Desktop и mobile | `Nothing to undo.`; запроса restore и изменения revision нет |
| Повторная генерация с 05:00–05:30 или 21:30–22:00 | Desktop и mobile | Ошибка исчезает, оба блока сохраняются, revision становится 8; Undo включается |
| Undo успешного draft | Desktop и mobile | Restore возвращает пустой день с revision 9; Undo снова выключен |
| Длинное название из 255 символов без пробелов | 1440×900, 390×844 и 320×740 | Обнаружено переполнение сообщения; после исправления текст полностью переносится внутри контейнера |

Исходная матрица из четырёх сценариев выполнена до CSS-правки. На новой сборке повторены полные цепочки отказ → генерация → Undo на desktop и mobile, включая сохранение того же длинного названия после исправления времени. Все тестовые дни оставлены пустыми. Финальный Logout показал Login.

В двух окружениях выполнено 15 управляемых SDK completion: 9 до CSS-правки и 6 после. Внешних AI-запросов нет. Снимки SQLite и журнал HTTP отдельно подтверждают последовательности `400 → 200 → restore 200`, сохранность revision при отказе и audit `success=false/true` для отказа и принятого повтора. Результаты не являются проверкой качества живой модели или опубликованного production.

### Найденная и исправленная ошибка

Ограничение названия в planner до 255 символов не гарантирует, что оно помещается в интерфейс. Строка из 255 `W` без пробелов выходила из `.draft-error` и создавала горизонтальную прокрутку всей страницы. Добавлен `overflow-wrap: anywhere` в `Schedule.vue`; полное название в API и тексте сообщения сохранено.

| Измерение | До исправления | После исправления |
| --- | --- | --- |
| Desktop: ширина документа при viewport 1440 | 3610 px | 1425 px |
| Desktop: scrollWidth / clientWidth сообщения | 3217 / 640 px | 640 / 640 px |
| Mobile: ширина документа при viewport 320 | 3217 px | 305 px |
| Mobile: scrollWidth / clientWidth сообщения | 3217 / 305 px | 305 / 305 px |
| Mobile 390: scrollWidth / clientWidth после исправления | — | 375 / 375 px |

Разница между viewport и шириной документа после исправления обусловлена вертикальной полосой прокрутки. Новая сборка имеет версию `build:31d514caf6cdfdea2c19`, CSS `app-BIArPliO.css` и JS `app-BJ5vBv9P.js`. После пересборки сервер запущен с новой fixture-базой, страница перезагружена и выполнен новый вход.

Доказательства: [JSON с 25 DOM-измерениями и 29 снимками состояния](evidence/AI_DRAFT_WINDOW_BROWSER.json), [desktop до](screenshots/ai-draft-window-2026-10-22/desktop-long-before-fix.jpg), [desktop после](screenshots/ai-draft-window-2026-10-22/desktop-long-after-fix.jpg), [mobile до](screenshots/ai-draft-window-2026-10-22/mobile-long-before-fix.jpg), [mobile после](screenshots/ai-draft-window-2026-10-22/mobile-long-after-fix.jpg), [обычная ошибка на исправленной mobile-сборке](screenshots/ai-draft-window-2026-10-22/mobile-after-rejected-fixed.jpg).

### Проверки и воспроизведение

`make check` прошёл: Ruff, 2150 backend-тестов, один платный opt-in R11-тест пропущен, Vue type-check и 1410 frontend-тестов в 104 файлах. Production build прошёл. Production dependency audit: 0 vulnerabilities. Image-retention tests, formatter для изменённого fixture-скрипта и `git diff --check` прошли. Повторный запуск fixture на существующей директории отклонён до изменения её БД.

В существующий [fixture-сервер](../backend/scripts/browser_audit_server.py) добавлен флаг `--draft-window`. Нужен локальный Redis на 6379; сервер использует dummy AI key и слушает только 127.0.0.1:8007. Лимит draft повышен до 100 только внутри этого тестового процесса.

```sh
make frontend-build
uv run python backend/scripts/browser_audit_server.py /tmp/day-forge-draft-window-new --draft-window
```

В другом терминале задать ответ модели через `controls.json`, используя выбранную новую директорию:

```python
import json
from pathlib import Path

root = Path("/tmp/day-forge-draft-window-new")
config = json.loads((root / "controls.json").read_text())
config.update(ai="draft", draft_actions=[
    {"type": "add", "title": "Valid fixture block", "start_time": "09:00", "end_time": "09:30", "category": "work"},
    {"type": "add", "title": "Draft early block", "start_time": "04:30", "end_time": "05:30", "category": "work"},
])
replacement = root / "controls.next.json"
replacement.write_text(json.dumps(config))
replacement.replace(root / "controls.json")
```

Открыть `http://localhost:8007/accounts/login/`, войти с локальными fixture credentials из скрипта и перейти на `/schedule/2027-08-02/`. Нажать Regenerate draft, проверить сообщение, пустой день и выключенный Undo. Заменить время второго действия на 05:00–05:30, повторить генерацию и нажать Undo. Для позднего отказа использовать 21:30–22:30 и исправить конец на 22:00. Для проверки переноса задать `title="W" * 255`. Дни 2027-08-02…2027-08-06 заранее созданы пустыми с revision 7, поэтому их открытие не запускает auto-draft.

Тестовая вкладка закрыта, viewport сброшен, оба fixture-сервера остановлены, приватные базы и staticfiles удалены. Удалены только 12 Redis-ключей с точными префиксами этих запусков. SHA-256 рабочей SQLite-базы совпадает до и после проверки. Проверка настоящего iOS Safari остаётся отдельной задачей.

### Автоматическая проверка после ревью PR #257

Добавлен [Playwright-сценарий](../frontend/scripts/check-draft-error-wrap.mjs) для свежего fixture-сервера с `--draft-window`. Он проходит Login и генерацию через UI, получает настоящий HTTP 400 от Django и проверяет полное название из 255 `W`, границы рабочего окна, ширину сообщения и документа при viewport 320 и 1440 px. После каждого измерения сценарий временно отключает перенос и требует, чтобы переполнение появилось. Это подтверждает, что проверка обнаруживает удаление CSS-исправления. Команда запуска и требования описаны в [README harness](../frontend/scripts/playwright/README.md#isolated-draft-error-layout-regression). Сценарий запускается отдельно, в CI и `make e2e` не входит.

Проверка прошла в headless Chromium: scrollWidth/clientWidth равны 320/320 px на mobile и 640/640 px на desktop. Без переноса scrollWidth составляет 3217 px на обеих ширинах. В этом браузере полоса прокрутки не уменьшает доступную ширину, поэтому mobile-измерение отличается от CUA. Использован один дополнительный stubbed SDK completion, внешних AI-запросов нет. После отказа день пустой, revision 7, статус draft, audit `success=false`; исходный `controls.json` восстановлен. Прибраны браузер, отдельный сервер, приватная база и пять ключей Redis с префиксом этого запуска. [Результат и SHA-256 проверенных исходников](evidence/AI_DRAFT_ERROR_WRAP_REGRESSION.json) сохранены отдельно от предыдущей матрицы из 15 completion.

Fixture-сервер теперь создаёт случайный `DJANGO_SECRET_KEY` для каждого запуска `--draft-window`, вместо известного ключа из репозитория. Это изменение касается только изолированного процесса проверки.
