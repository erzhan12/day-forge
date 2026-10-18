# Итоговый аудит Day Forge после R00–R12

Текущий статус после исправлений: A00–A07 реализованы, основные desktop/mobile сценарии и live R11 закрыты в PR #241. Последующий [браузерный прогон A00–A06](BROWSER_VERIFICATION_A00_A07.md) проверил управляемые ошибки и гонки и исправил category confirmation/mobile overflow. Для A07 остаётся browser case с действительно открытым PiP: встроенный браузер не открыл окно. Подтверждённый cleanup выполнен после PR #243; удаления, сокращение инструкций Claude и проверки описаны в [cleanup-отчёте](AUDIT_CLEANUP.md). Ниже сохранены исходные находки аудита; открытые задачи находятся в [todo](../tasks/todo.md).

Дата: 11 октября 2026 года. Проверено локальное рабочее дерево поверх `c62963d26e1582f86515d08963837c71408eb105`. Изменения R00–R12 ещё не оформлены отдельными коммитами. Аудит сохраняет отчёт; исправления найденных дефектов в исходники не вносились.

Последующие исправления: A00–A07 реализованы локально. Контракты, миграция и проверки A00/A01 описаны в [первом отчёте](AUDIT_FIXES_A00_A01.md); межстраничная запись и SQLite read path описаны в [отчёте A02/A03](AUDIT_FIXES_A02_A03.md); chat history и Google all-failed описаны в [отчёте A04/A05](AUDIT_FIXES_A04_A05.md); откат category draft и граница публикации PiP описаны в [отчёте A06/A07](AUDIT_FIXES_A06_A07.md). Браузерная проверка этих исправлений остаётся недоступной по политике безопасности. Находки ниже сохраняют состояние на момент аудита.

## Вывод

Архитектура стала проще для следующих изменений: поддерживаемые операции записи используют общий транзакционный исполнитель, правила итогового дня выделены из HTTP, состояние расписания и Undo имеют явного владельца, инфраструктура интеграций объединена. Django/Vue монолит подходит текущему приложению. Оснований для нового фреймворка, слоя репозиториев или разделения на сервисы аудит не дал.

Полный набор тестов проходит, но остаются непокрытые комбинации событий. Подтверждены регрессия зафиксированного обзора дня после удаления категории, устаревший экран при возврате к незавершённой записи и ошибка GET при длительной блокировке SQLite. Найдены существовавшие ранее пробелы chat-протокола, Google Calendar и очистки PiP. Названия импортированных календарных событий могут входить в контекст AI вопреки категорическому обещанию privacy-страницы. Согласование этого обещания с поведением и исправление найденных случаев полезнее следующего широкого переноса файлов.

Суммарный код приложения вырос на 198 строк по сопоставимому подсчёту. Сокращение отдельных крупных файлов сопровождалось новыми модулями и контрактами. Следующее сокращение стоит проводить через удаление подтверждённо лишних интерфейсов и запасных веток.

## Как проверялось

Три субагента Sol high независимо проверили backend, frontend и AI/интеграции. Основной агент проверил воспроизведения, CI/deployment, остаточную совместимость, команды, документацию и объём кода. Источники сверялись с `git show c62963d:<path>`, чтобы отделить новые регрессии от старых проблем.

Воспроизведения выполнялись на временных SQLite базах и в отдельных Vitest fixtures вне репозитория. Они проверяют конкретные границы и порядок ответов. Полная Schedule/Inertia навигация и реальный PiP для этих гонок в браузере не воспроизводились; соответствующие ограничения указаны ниже. Рабочая БД проверялась только чтением, без вывода пользовательских записей.

Среда: Python 3.14.0, Node 22.22.3. Результаты текущего аудита:

| Проверка | Результат |
|---|---|
| `make check` | Ruff, 1946 backend-тестов, frontend type-check, 1355 frontend-тестов прошли |
| Backend-тесты | 12,22 с |
| Frontend-тесты | 102 файла, 9,83 с |
| `cd frontend && npm run build` | Type-check и Vite build прошли |
| `manage.py check` | Нет замечаний |
| `makemigrations --check --dry-run` | Нет незаписанных изменений моделей |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| `git diff --check` | Прошёл |
| Профильные наборы тестов субагентов | Прошли; их количество не суммируется с полным набором тестов, поскольку наборы пересекаются |
| Изолированные воспроизведения | Повторно проверены category/review, GET contention, remount race, PiP cleanup, Google failure, повторный rejected category edit и chat schema |

В рабочей SQLite базе найдено 0 неположительных интервалов, 0 неизвестных категорий блоков, 0 reviewed-дней без актуального snapshot и 0 существующих каталогов с неверным количеством sink/default или более восьми строк. Это проверка локальных данных, не production-базы.

Реальные AI-запросы в этом аудите не повторялись. Предыдущий [R12-отчёт](/Users/erzhan/DATA/PROJ/day-forge/docs/REFACTORING_R12.md) фиксирует успешные реальные chat/draft и AI Undo. Мобильный browser smoke, реальные внешние аккаунты и первый запуск CI на PR остаются отдельными проверками. Фиксированные ответы проверяют приложение, но не качество живой модели.

## Архитектура: что получилось

| Область | Текущее состояние | Оценка |
|---|---|---|
| Запись расписания | `commands` → `planning` → `mutations` → `persistence` | Полезная граница. Исправление общей проверки не требует менять каждый HTTP endpoint |
| Конкуренция | User → Schedule → TimeBlock, SQLite writer reservation, expected revision, snapshot ответа внутри транзакции | Защищает поддерживаемые операции записи от stale writes. Резервирование writer следует ограничить операциями, которым оно требуется |
| Source policies | Manual/import/chat/draft/restore имеют явные различия | Сохранять различия. Универсальная проверка с множеством флагов снова смешает продуктовые контракты |
| Состояние frontend | `useScheduleRevision` владеет canonical state, page controller собирает Undo/chat/draft | Ownership понятен. Между уничтоженным и новым владельцем пока отсутствует сигнал о завершившейся записи |
| Аналитика | GET считает в памяти, review хранит frozen snapshot с revision tag | Правильное разделение. Category maintenance не согласован с новым tag |
| Время | Сохранённый IANA timezone, общий frontend clock, civil-day helpers | Существенное уменьшение расхождений. Нужны сохранённые DST/midnight тесты |
| Интеграции | Узкие общие crypto/cache/state helpers, отдельные provider adapters | Удачная степень обобщения. Google all-account failure требует отдельной ветки при сохранении partial success |
| AI | Контекст и revision до/после provider, typed actions, partial outcomes | Защита записей стала яснее. Intent/replay эвристики и dialogue protocol требуют отдельной оценки поведения |
| CI и документация | Общий PR/deploy gate, текущие справочники, исторический архив | Локальные команды проверены. Остались старый ручной скрипт и дублирующиеся инструкции для Claude |

В проверенных операциях записи не найден обход общего executor, который позволял бы старому снимку записаться без revision-проверки. Direct ORM, fixtures и миграции остаются исключениями. Admin для расписания и влияющих политик ограничен просмотром. Полный набор тестов включает отдельные SQLite connections и конкурирующие write reservations, а не только spies на lock.

Общий снимок schedule/blocks сериализуется внутри транзакции. Category/settings/rules/template writers используют User lock для согласования AI context. HTTP ownership и transport validation остаются у adapters, доменное планирование не выполняет скрытые ORM-запросы. Эти границы стоит сохранить.

## Подтверждённые проблемы

P1 означает проблему, которую стоит закрыть до публикации следующей версии. P2 означает ограниченный функциональный дефект, который стоит исправить ближайшими небольшими изменениями. P3 означает редкий случай доступности или локальную проблему lifecycle. Уверенность относится к описанному механизму, а не к частоте в production.

| ID | Приоритет | Происхождение | Проблема |
|---|---|---|---|
| A00 | P1 | Была в `c62963d` | Название импортированного события попадает в контекст AI, privacy-страница обещает обратное |
| A01 | P2 | Новая комбинация revision и frozen review | Удаление категории лишает reviewed-день актуального snapshot, UI не предлагает refreeze |
| A02 | P2 | Новый mutation owner | Возврат на день до commit оставляет новый экран с прежним снимком после успешной записи |
| A03 | P3 | Новое резервирование writer на GET | Долгая SQLite блокировка превращает чтение существующего дня в 500 |
| A04 | P2 | Была в `c62963d` | Пустой assistant content после допустимого ответа модели ломает следующий chat turn |
| A05 | P2 | Была в `c62963d`, общий контракт R08 её не устранил | Полный отказ Google-аккаунтов стирает последние успешно показанные события |
| A06 | P2 | Была до R12, уже отмечена в todo | Повторный отказ category edit может оставить несохранённое значение в DOM; server detail теряется |
| A07 | P3 | Была в `c62963d` | Уходящая Schedule может восстановить старый snapshot в памяти после очистки на Login |

### A00. Privacy-обещание не соответствует пути импортированного события

Источники: [privacy.html:77](/Users/erzhan/DATA/PROJ/day-forge/backend/templates/legal/privacy.html:77), [privacy.html:114](/Users/erzhan/DATA/PROJ/day-forge/backend/templates/legal/privacy.html:114), [AddToScheduleDialog.vue:120](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/components/AddToScheduleDialog.vue:120), [ai/views.py:464](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/views.py:464), [prompts.py:455](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/prompts.py:455), [service.py:403](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/service.py:403).

Privacy-страница утверждает, что данные Google Calendar и названия событий календарей никогда не включаются в запросы к AI. При добавлении события диалог копирует `event.title` в обычный TimeBlock. AI chat загружает все блоки дня, форматирует каждое название и передаёт контекст провайдеру. Поля происхождения и исключающего фильтра нет. История прошлых дней, используемая при генерации черновика, также включает названия блоков.

Условие передачи: пользователь сначала добавляет событие в расписание, затем использует chat или позже генерирует draft с этим днём в history. Само открытие панели календаря не запускает этот путь. Название уже принятого календарного события остаётся данными, которые privacy-страница категорически исключает из передачи.

Вызов настоящего prompt builder с синтетическим imported-title marker дал `Imported title included in chat context: True`. Service path и отсутствие фильтра независимо перепроверены субагентом. Реальные пользовательские названия в проверке не отправлялись. Те же import/prompt paths были в `c62963d`; проблема не внесена рефакторингом. Уверенность высокая. Это фактическое расхождение передачи данных и опубликованного описания, без вывода о юридическом соответствии.

Нужно выбрать и реализовать контракт: сохранять происхождение импортированных блоков и исключать или обезличивать их внешние поля до передачи в чат и историю для черновика, либо явно описать принятие события в AI-обрабатываемое расписание и согласовать интерфейс, опубликованное описание и правила провайдера. Изменение одного слова в privacy без продуктового решения недостаточно. Тест должен пройти через import → stored block → final SDK messages; текущий legal-page тест проверяет наличие обещания в HTML, а не его выполнение.

### A01. Category maintenance делает frozen review устаревшим

Источники: [categories.py:190](/Users/erzhan/DATA/PROJ/day-forge/backend/schedules/categories.py:190), [mutations.py:185](/Users/erzhan/DATA/PROJ/day-forge/backend/schedules/mutations.py:185), [analytics/services.py:116](/Users/erzhan/DATA/PROJ/day-forge/backend/analytics/services.py:116), [Analytics.vue:123](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/pages/Analytics.vue:123).

Сценарий: reviewed-день содержит блок в удаляемой категории. Удаление remap-ит блок в sink и увеличивает revision. Затем remap-ятся category maps в DailyReview, но `reviewed_revision` остаётся прежним. `status` всё ещё `reviewed`.

GET аналитики считает review устаревшим и показывает текущие вычисления. Кнопка Mark reviewed скрыта по одному статусу, поэтому пользователь не может повторно зафиксировать этот день обычным UI. Streak и draft history также используют критерий актуальности snapshot. Для сегодняшнего дня даже число skipped может начать меняться после завершённого обзора.

Воспроизведение на временной БД:

```text
before: reviewed 0 0 True frozen skipped 0
after:  reviewed 1 0 False frozen skipped 0 live skipped 1
```

Уверенность высокая: проверены реальные models, category maintenance и predicates, затем условие кнопки в UI. В исходном состоянии отметка revision отсутствовала, remap не отключал frozen review.

Рекомендуемый контракт: при чистом category remap сохранить frozen totals/time-dependent counts и атомарно перевести tag на новую revision, только если review был актуален до операции. Уже устаревший snapshot нельзя объявлять актуальным. Альтернатива: переводить день в active и разрешать review заново. Выбрать один вариант и закрепить тестом category delete → analytics/streak/history. Notes должны сохраниться, повторное удаление не должно создавать новую revision.

### A02. Запись завершается после возврата на тот же день

Источники: [DateNavigator.vue:20](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/components/DateNavigator.vue:20), [useScheduleRevision.ts:225](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useScheduleRevision.ts:225), [useSchedule.ts](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useSchedule.ts).

Порядок событий: ручная запись дня A отправлена; пользователь переходит на B и обратно на A; обратный GET выполнен до commit и вернул старую revision; POST затем успешно завершается. DateNavigator использует Inertia GET, новый экземпляр страницы получает нового владельца. Старый владелец уже disposed и отклоняет свой поздний ответ, новый не получает сигнала о commit.

Данные сохранены на сервере. Новый экран остаётся старым до refresh; следующая запись получает 409 и reconciliation. Потеря данных этим сценарием не подтверждена. В `c62963d` ручной `useSchedule.apiFetch` вызывал глобальный reload после успеха, в том числе после ухода исходной страницы. Новый owner правильно убрал этот побочный эффект, но не заменил его сигналом для повторно открытого дня.

Уверенность высокая в поведении owner. Изолированный fixture моделирует реальный remount и порядок GET/POST; полноценный браузерный сценарий с задержкой ответа ещё нужен. Существующий A→B→A тест возвращает уже новую revision, поэтому не покрывает этот порядок.

Исправление: сообщать корню о pending/dirty date и обновлять только совпадающий текущий account/date после settlement, либо временно ограничить навигацию во время записи с явно описанным поведением Back/Forward. Не возвращать безусловный reload чужой даты и не повторять POST автоматически. Минимальный regression-тест должен использовать remount, старый return-GET и поздний успешный commit.

### A03. Schedule GET без необходимости захватывает SQLite writer

Источники: [schedules/views.py:116](/Users/erzhan/DATA/PROJ/day-forge/backend/schedules/views.py:116), [mutations.py:76](/Users/erzhan/DATA/PROJ/day-forge/backend/schedules/mutations.py:76).

Даже для существующего дня `schedule_view` вызывает `run_user_maintenance`, который сначала делает UPDATE User. Другая write transaction блокирует такой GET. После исчерпания retries выбрасывается `ScheduleChanged`, но page view его не перехватывает. Результат запроса будет 500, тогда как старый `get_or_create` существующего дня обходился чтением.

Воспроизведение: новая временная БД, заранее созданный день и policies, отдельное соединение держит `BEGIN IMMEDIATE`. Старый read успешен, текущий view выбрасывает `ScheduleChanged`. Для быстрого воспроизведения SQLite timeout установлен в 0,1 с. В текущей конфигурации timeout не переопределён; установленный Python использует 5 с, executor выполняет до трёх попыток. Обычная короткая запись, вероятно, успеет завершиться. Это редкая ошибка доступности и ненужная конкуренция чтения с записью.

Исправление: отделить coherent read существующего дня от создания отсутствующего. Creation сохраняет writer boundary и auto-draft one-shot contract. Для исчерпанного contention на page request нужен контролируемый ответ. Проверить GET существующего дня под независимым writer, согласованность schedule/blocks и гонку двух first visits. Простого переноса SELECT за пределы транзакции недостаточно.

### A04. Допустимый ответ AI создаёт недопустимую историю

Источники: [schemas.py:306](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/schemas.py:306), [useChat.ts:271](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useChat.ts:271), [ai/views.py:833](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/views.py:833).

`{"actions": [], "explanation": "", "ask": null}` проходит response validation. Frontend сохраняет `assistant.content = ""`. Следующий пользовательский turn отправляет эту историю и получает `400: messages[1].content cannot be empty`. Whitespace-only explanation и ask также проходят response schema, но дают недопустимый transcript.

Уверенность высокая: response validator и next-turn validator вызваны напрямую, client assignment проверен в исходнике. Этот дефект был в исходном commit. Реальный provider в аудите не генерировал такой ответ.

Исправление: согласовать response и transcript contracts. Когда `ask` отсутствует, должен существовать допустимый nonblank assistant content. При недопустимом ответе reject должен происходить до применения действий. Если выбран server-owned fallback, он должен сохранять смысл ask/applied/replay markers. Тестировать пустоту, whitespace, no-op и ответ с принятыми действиями.

### A05. Полный отказ Google Calendar принят как успешный пустой календарь

Источники: [gcal_sync/views.py:249](/Users/erzhan/DATA/PROJ/day-forge/backend/gcal_sync/views.py:249), [useDatedResource.ts:143](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useDatedResource.ts:143), [useGoogleCalendar.ts:25](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useGoogleCalendar.ts:25).

Все подключённые аккаунты могут завершиться ошибкой. Backend сохраняет контракт HTTP 200 и `account_errors`, возвращает `events: []` и `meta.resource_state: provider_error` либо `credentials_error`. Общий loader делает commit любого корректного `ok` ответа, Google adapter заменяет ранее показанные события пустым массивом.

Vitest воспроизводит same-date refresh после успешной загрузки: events становятся `[]`, resourceState равен provider_error, общий `state.error` остаётся null. Per-account ошибки доступны UI, но последние успешные события теряются. Такое blanking было до R08; новый metadata-контракт теперь позволяет отличить его от успешного пустого дня.

Исправление оставить у Google adapter или в явном adapter hook: `ready` с пустыми events должен очистить старый день; partial success должен показать успешные аккаунты вместе с ошибками; all-failed должен сохранить last-good rows только текущей date/context и показать сбой. Проверить credentials-only failure, первый пустой failure, date change и disconnect.

### A06. Повторный rejected category edit оставляет несохранённое поле

Источник: [SettingsCategoriesPanel.vue:34](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/components/settings/SettingsCategoriesPanel.vue:34).

Уточнение предыдущего R12 review: первый отказ с новым сообщением вызывает rerender и возвращает label к prop. Если следующий отказ записывает то же значение `error`, rerender не происходит. После второго rejected изменения input может показывать новое имя, хотя prop и БД остались прежними. Изолированный component test подтвердил: первый отказ вернул `Work`, второй оставил `Rejected two` при prop `Work`.

Панель читает только `errors.category`; реальный `errors.detail` для 429/409 заменяется общим `Could not save category`. Уверенность высокая для повторного label rejection и detail mapping. Color отдельно не воспроизводился; код использует аналогичный обработчик.

Исправление: явное управление draft/accepted values, восстановление по результату отказа, общий detail extraction. Проверить два последовательных одинаковых отказа, label/color и 429/409. Глобальная форма/state-machine для этого не нужна.

### A07. PiP snapshot очищается до финальной публикации уходящей страницы

Источники: [useFocusIndicatorController.ts:141](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useFocusIndicatorController.ts:141), [Schedule.vue:173](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/pages/Schedule.vue:173).

Root watcher синхронно очищает snapshot при Login/account change и закрывает PiP. Затем `onBeforeUnmount` уходящей Schedule без проверки identity публикует прежние блоки обратно. Explicit Logout заранее вызывает `resetSession` и в fixture оставляет пустой снимок. Session-expiry или другой переход на Login может пройти без этого шага.

Fixture с реальным root controller и упрощённым publisher подтвердил повторное появление active snapshot в памяти после закрытия окна. Окно закрыто, его title остаётся `Focus`. Видимая утечка в открытом PiP этим воспроизведением не установлена. Поведение публикации было в `c62963d`.

Исправление: связать публикацию с account/generation или отбрасывать её после Login/session boundary. Нельзя просто удалить final publish для всех переходов: он сохраняет актуальную информацию при уходе в Settings/Analytics. Нужен интеграционный тест настоящей уходящей Schedule, root clear и identity change.

## Риски, которые требуют дополнительного измерения

### Обновление frontend при несовместимом API

[vite.config.ts:20](/Users/erzhan/DATA/PROJ/day-forge/frontend/vite.config.ts:20) выдаёт постоянные `assets/app.js` и `assets/app.css`; [base.html](/Users/erzhan/DATA/PROJ/day-forge/backend/templates/base.html) подключает их напрямую. `INERTIA_VERSION` в project settings не задан; установленный inertia-django 1.2.0 использует постоянное `1.0`. Проверка middleware показала, что старый client version `1.0` не вызывает refresh. WhiteNoise в production по умолчанию задаёт max-age 60 с для таких assets, а уже открытая вкладка может жить дольше кеша.

Постоянная версия существовала ранее. После обязательного `expected_revision` старый frontend не может продолжать обычные mutations: сервер безопасно отказывает, но пользователь получает неработающий экран до reload. Нужен deployment smoke старой вкладки и release-specific Inertia version. Hashes/manifest и lazy imports можно добавить после этого, если требуется управление кешем или измеренная оптимизация загрузки. Rollback и сохранённая история вкладки тоже должны быть проверены. Реальный deployment этим аудитом не выполнялся.

### Неопределённый результат completion во внешнем сервисе

[useTaskCompletion.ts:55](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useTaskCompletion.ts:55) после network/parse failure возвращает строку задачи и разрешает повтор. [Habitica endpoint](/Users/erzhan/DATA/PROJ/day-forge/backend/habitica_sync/views.py:227) может отправить второй `score/up`, если первый upstream вызов выполнился, а его ответ потерялся.

Rollback и возможность повторного POST подтверждены кодом. Повторное начисление в Habitica не проверялось на живом аккаунте и не считается установленным дефектом. Нужно сначала проверить provider semantics, затем выбрать reconcile/uncertain state либо request identity. Автоматический retry после неопределённого результата добавлять не следует. Риск был до R08.

### Изменение перетаскиваемого блока во время жеста

[useDrag.ts:236](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/composables/useDrag.ts:236) исключает dragged block из проверки внешних coordinate changes. Это старое поведение, явно закреплённое тестом. Если его время изменилось извне и клиент уже принял новую revision, drop может применить координаты старого жеста к новому состоянию. Соседи при этом защищены.

Перед изменением нужно определить, является ли drop осознанным новым placement или stale intent. Проверять изменение времени dragged block отдельно от metadata/completion и собственных preview changes. Этот пункт не должен превращаться в безусловное удаление существующего исключения без contract-test.

### Качество AI и инфраструктура

R11 gaps остаются: действия модели вопреки отказу, потеря ответа после commit, потеря replay evidence после reset transcript. Pending intent и durable request identity пока являются предложениями. Несколько успешных live smoke не измеряют false additions, лишние questions или стоимость.

Общий набор тестов использует LocMem cache для изоляции. Он не является нагрузочным тестом production Redis и нескольких вкладок. SQLite сохраняет одного writer для всех пользователей; увеличение числа ASGI workers не устраняет это ограничение. Перед сменой БД полезны latency/busy metrics и конкретный concurrent workload. Текущий deployment имеет ограничение памяти и один uvicorn worker; Docker image, реальный rollout и внешний health check заново не выполнялись.

## Что можно сократить или удалить

Таблица сохраняет кандидатов на момент первоначального аудита. 18 октября 2026 года они выполнены после повторного поиска потребителей. Дополнительно удалён неиспользуемый `scheduleDiff.ts`. Результаты и проверки приведены в [cleanup-отчёте](AUDIT_CLEANUP.md).

| Кандидат | Основание и эффект | Необходимая проверка |
|---|---|---|
| `_load_active_rules` в [ai/views.py:102](/Users/erzhan/DATA/PROJ/day-forge/backend/ai/views.py:102) | Нет вызовов/import consumers. Правила уже захватываются в `_load_ai_context_sync` и apply-context helpers. Удалить старое объяснение второго пути | Rule ordering/fingerprint tests; обновить устаревшие комментарии тестов |
| `POLICIES` в [planning.py:49](/Users/erzhan/DATA/PROJ/day-forge/backend/schedules/planning.py:49) | Нет consumers; отдельные policy constants используются напрямую | Planner suite |
| Validation re-exports в [templates_mgr/api.py:608](/Users/erzhan/DATA/PROJ/day-forge/backend/templates_mgr/api.py:608) | `parse_time_or_error`, `validate_five_minute_or_error`, `validate_time_range` экспортируются «для тестов», но тесты их не импортируют | Template/schedule contract tests; сохранить реально используемый parser |
| Неиспользуемые HTTP time wrappers | После удаления re-exports у `schedules.http.validate_five_minute_or_error` и HTTP `validate_time_range` не останется consumers. Доменный `time_validation.validate_time_range` нужен | Repository-wide imports search, time validation suite |
| Параметр `status` у `_action_error` | Все call sites используют значение 400 по умолчанию | AI response/error contract tests |
| `_snapshotBlocks` у `useChat.submitTurn` | Не читается, но проходит через Schedule → ChatSidebar/CommandBar. Реальный предыдущий снимок приходит из `result.mutation` | Chat/component tests, partial apply/Undo |
| `snapshotBlocks` в injected Undo context | Consumers используют только `pushUndo`; лишний член расширяет injection/API | Удалить member из context и completion types. Прямой snapshot для drag сохранить |
| Неиспользуемые exports и return members | У `clearChatSession`, `clearDraftSession`, `useProvidedFocusIndicatorController` нет consumers. Page controller возвращает значения, которые Schedule не читает | Lifecycle tests; внутренние reset helpers оставить, если они используются |
| Fallback presentation в [Timeline4a.vue:31](/Users/erzhan/DATA/PROJ/day-forge/frontend/src/components/Timeline4a.vue:31) | Единственный production caller всегда передаёт готовую `presentation`; leaf tests поддерживают лишний альтернативный вход | Сделать presentation обязательной, убрать redundant geometry props; обновить leaf fixtures и frozen-drag tests |
| `main.py` | Только starter `Hello from day-forge!`, references в командах приложения не найдены | Проверить внешние scripts/IDE launch settings; удалить пустой entry point |
| `scripts/test10_audit_envelope.py` (удалён) | Старый standalone script не передаёт revision, ожидает старую структуру audit и не превращает returned failure в ненулевой exit. Может менять `.env` и перезапускать все dev servers | Перенести нужные проверки в существующие deterministic tests; retire script либо явно пометить историческим. Скрипт в аудите не запускался |
| Дублирование [CLAUDE.md:23](/Users/erzhan/DATA/PROJ/day-forge/CLAUDE.md:23) и AGENTS/README | Seed всё ещё указан без обязательного `--user`. Review workflows читают CLAUDE.md, поэтому это действующий источник путаницы | Короткая текущая инструкция со ссылкой на общий command reference; сохранить Claude-specific workflow rules |

`CommandPlan.candidates` и `.restore` имеют только тестовых consumers, runtime использует `.diff`. Их сокращение ниже по приоритету: сначала определить минимальный контракт planner и сохранить тесты поведения. Удаление полей ради уменьшения DTO без ясного потребителя не является самостоятельной целью.

Не удалять `schedules/validators.py`: migration 0001 импортирует этот dotted path. Не удалять provider adapters/отдельные encryption keys, replay guards, source policies, revision reconciliation, drag snapshot checks, account epochs, notes queues и security gates ради числа строк. У них есть действующие consumers и тестируемые исключения.

## Измерения размера

Подсчитаны tracked и non-ignored untracked files. Обычный `git diff --stat` не включает новые неотслеживаемые модули и поэтому преувеличивает сокращение в этом рабочем дереве. Строки включают комментарии и пустые строки.

| Группа | `c62963d` | После R00–R12, до этого отчёта | Изменение |
|---|---:|---:|---:|
| Backend `.py`, без tests и migrations | 15 020 | 15 446 | +426 |
| Frontend `src` `.ts/.vue/.css` | 17 509 | 17 281 | −228 |
| Production-код, сумма этих групп | 32 529 | 32 727 | +198 |
| Backend/frontend test files | 43 492 | 49 712 | +6 220 |
| Docs и основные рабочие Markdown | 40 387 | 41 807 | +1 420 |

Подсчёт test files не включает Playwright scripts и исторические пустые app `tests.py`. Docs включают архив; его рост означает сохранение истории и новые отчёты. Эти категории отличаются от первоначального ручного аудита, поэтому нельзя напрямую сравнивать их с его округлёнными числами.

Отдельные файлы: Schedule 1257 → 769 строк, schedules API 897 → 502, AI views 1454 → 1179, AI planner 1190 → 1018. Новый revision owner занимает 337 строк, page controller 84, executor 220, shared planner 460. Это декомпозиция с контрактами, не соответствующее количество удалённых строк.

Production build: app.js 478,55 КБ, gzip 157,52 КБ; CSS 70,48 КБ, gzip 12,23 КБ. Все страницы сейчас eager-imported. Lazy-loading Settings/Analytics является кандидатом после измерения загрузки и исправления asset versioning; доказанной пользовательской задержки в этом аудите нет.

## Рекомендуемый порядок следующих изменений

1. Согласовать передачу данных и опубликованное описание A00. Зафиксировать выбор продукта для импортированных событий и проверить итоговые сообщения AI, включая историю для черновика.
2. Исправить A01 отдельным commit: frozen review и category maintenance, с проверкой analytics/streak/history. Это наиболее ясная регрессия persisted lifecycle.
3. Согласовать assistant response/transcript contract A04 и Google all-failed handling A05. Оба изменения локальны и требуют boundary tests вместо новых общих фреймворков.
4. Исправить повторный category rejection A06 и подтвердить PiP session-expiry cleanup A07 на настоящем page swap. Для category delete можно переиспользовать DOM-dialog pattern, чтобы smoke не зависел от native confirm.
5. Закрыть A02 с remount regression-test и браузерной задержкой POST. Отдельно сделать coherent read path и controlled contention response A03. Не смешивать эти случаи с заменой SQLite.
6. Выполнить небольшой cleanup подтверждённых consumers: dead helpers/exports, лишний chat snapshot argument, injected Undo member и Timeline4a fallback. Сначала точечные tests, затем общий `make check` и build.
7. Подготовить release-specific Inertia version и проверить старую вкладку при обновлении и rollback. Запустить PR CI, production image/migration rehearsal на копии базы и настоящую проверку мобильных сценариев.
8. Затем выполнить контролируемое AI-сравнение с фиксированным набором диалогов, моделью, prompt и spend cap. Только его результат может обосновать удаление intent/replay эвристик.

Каждый пункт можно завершить с рабочим приложением. Для будущих исправлений сохранять отдельный воспроизводимый тест исходной ошибки и проверять соседние контракты. Новый большой этап рефакторинга до закрытия этих комбинаций не требуется.

## Воспроизведения и ограничения доказательств

Временные файлы этого аудита сохранены локально. Они не включены в suite репозитория и могут исчезнуть при очистке `/tmp`:

```sh
# В корне проекта, обе программы создают собственную временную SQLite базу.
PYTHONPATH=backend DJANGO_SETTINGS_MODULE=day_forge.settings uv run python /tmp/day-forge-audit-reviewed-category.py
PYTHONPATH=backend DJANGO_SETTINGS_MODULE=day_forge.settings uv run python /tmp/day-forge-audit-schedule-get.py

# Backend-shaped Google all-failed response после успешного same-date read.
frontend/node_modules/.bin/vitest run --config /tmp/day-forge-final-audit/vitest.config.mts

# Root PiP + publisher, remounted mutation owner и повторный category rejection.
cd /tmp/dayforge-front-audit
/Users/erzhan/DATA/PROJ/day-forge/frontend/node_modules/.bin/vitest run --config /tmp/dayforge-front-audit/vitest.config.ts pip-order.test.ts remount-pending.test.ts category-editor.test.ts
```

Логи полных проверок находятся в `/tmp/day-forge-final-audit/check.log` и `build.log`, machine-readable подсчёт в `metrics.json`. При исправлении нужно перенести соответствующий сценарий в постоянный regression-test и заменить диагностические assertions на ожидаемое исправленное поведение.

Source findings и временные fixtures не доказывают отсутствие остальных багов. Здесь не проводились нагрузочный тест, проверка живых внешних аккаунтов, penetration test, production rollout или A/B качества модели. Текущие contracts и known gaps описаны в [ARCHITECTURE.md](/Users/erzhan/DATA/PROJ/day-forge/docs/ARCHITECTURE.md), [RULES.md](/Users/erzhan/DATA/PROJ/day-forge/RULES.md), [R11 design](/Users/erzhan/DATA/PROJ/day-forge/docs/REFACTORING_R11_DESIGN.md) и [todo](/Users/erzhan/DATA/PROJ/day-forge/tasks/todo.md).
