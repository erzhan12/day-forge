# Текущая архитектура Day Forge

Состояние после R00–R12. Django ASGI и Vue/Inertia остаются одним приложением. SQLite используется локально и в текущем deployment. Запуск и проверки описаны в [README](../README.md), wire-контракты в [api.md](api.md), обязательные исключения в [RULES](../RULES.md). Исторические планы находятся в [features](features/README.md), активные задачи в [todo](../tasks/todo.md).

## Backend: путь изменения расписания

| Слой | Владелец | Ответственность |
|---|---|---|
| HTTP | `schedules/api.py`, `ai/views.py`, `analytics/views.py` | Разбор тела, user scope, параметры операции и ответы |
| Команды и снимки | `schedules/commands.py` | Значения без ORM, candidate state и diff |
| Проверки | `schedules/planning.py`, `time_validation.py`, `window.py` | Поля, интервалы, полный итоговый день и политика источника |
| AI планирование | `ai/mutation_planner.py`, `ai/free_slot.py` | Последовательность действий модели, partial apply и outcomes |
| Транзакция | `schedules/mutations.py` | User → Schedule → TimeBlock, expected revision, busy retry, снимок ответа |
| Запись | `schedules/persistence.py` | Применение принятого diff внутри транзакции |
| Wire | `schedules/serialization.py`, `common/http.py` | Общая сериализация и ограниченный JSON parser |

Обычный writer передаёт `expected_revision`; при конфликте ничего не записывается. Поддерживаемые maintenance-операции используют ту же границу с явным разрешением получить текущую версию. Пользовательская версия увеличивается один раз при изменении блоков или статуса. Успешный no-op не увеличивает её. Ответ содержит согласованные `schedule`, `blocks`, `revision`, захваченные до выхода из транзакции.

SQLite executor резервирует writer до чтения; блокировки строк PostgreSQL для этого не требуются. Разные пользователи всё равно конкурируют за один SQLite writer. При исчерпании bounded retry клиент получает контролируемый конфликт. Вызов AI и внешних providers выполняется вне write lock. Прямые ORM-записи не обеспечивают этот контракт; admin расписания и связанных политик оставлен для просмотра. Тесты и миграции могут создавать fixtures напрямую.

GET существующего подготовленного дня захватывает Schedule, блоки и page policies в read transaction без SQLite writer reservation. Отсутствующий день или first-use rows создаются под общим User lock; снимок ответа и creation flag захватываются до commit. Только создавший день запрос может включить auto-draft signal. Исчерпанная блокировка внутри page view возвращает 503 с `Retry-After: 1`. См. [A02/A03](AUDIT_FIXES_A02_A03.md).

Политики сохранены по источнику: manual требует сетку и обрезает время по окну, import допускает произвольные минуты и обрезает по окну, AI chat сохраняет свою обработку допустимого подмножества и времени, draft отклоняет недопустимый план, Undo принимает прежние off-grid/outside-window интервалы после проверки итогового дня. Проверка ownership категории остаётся у HTTP/AI adapters, а доменные функции не делают запросов к БД. Подробности и ограничения: [R04](REFACTORING_R04.md), [R05](REFACTORING_R05.md), [R07](REFACTORING_R07.md).

## Данные, время и аналитика

`Schedule` хранит день, статус и revision; `TimeBlock` хранит интервалы. `UserScheduleSettings` задаёт окно и IANA timezone. Этот сохранённый пояс определяет локальный день на backend и frontend, границы календарного запроса, notifications и PiP. Смена пояса инвалидирует соответствующие запросы и AI context, не переписывая времена старых блоков.

Каталог `Category` принадлежит пользователю и создаётся при первом доступе. Slug стабилен; label и цвет меняются. Удаление remap-ит ссылки на sink под user lock. Актуальный зафиксированный обзор сохраняет показатели и получает новую revision в той же транзакции; уже устаревший обзор остаётся устаревшим. `Template` и `Rule` принадлежат пользователю в `templates_mgr`; UI preferences остаются в том же приложении. Их перенос в отдельный app не требуется текущим контрактом.

`analytics/services.py` считает текущие агрегаты в памяти. `DailyReview` хранит заметки и явно зафиксированный обзор. Snapshot актуален только при статусе reviewed и совпадении `reviewed_revision` с revision дня. GET аналитики не записывает обзор. Явный review фиксирует агрегаты; последовательная очередь notes/review на frontend сохраняет порядок текста и фиксации. Streak и draft history используют тот же критерий актуальности. См. [R06](REFACTORING_R06.md), [R10](REFACTORING_R10.md).

Если зафиксированный обзор отсутствует или устарел, Analytics показывает `Update reviewed summary`. Этот явный POST пересчитывает обзор при текущей revision и сохраняет заметки. Актуальный зафиксированный обзор скрывает кнопку. Удаление категории само не восстанавливает ранее устаревшие показатели.

## AI

`ai/service.py` строит trusted schedule/rules context и передаёт предыдущий transcript как недоверенный текст. Модель предлагает действия. Нормализация категорий, typed schema, replay guard, prompt-context fingerprint и expected revision предшествуют принятию изменений. Planner возвращает допустимый diff и объясняет пропущенные действия через outcomes. Принятый diff записывается атомарно.

Chat response validation отклоняет пустой assistant content до обработки действий: без ask нужен непустой explanation, заданный ask также должен содержать текст. Выбранный content укладывается в лимит следующего входного turn. Ошибка даёт фиксированный 502, после которого frontend сохраняет допустимое `is_error` сообщение. Входная история из одних пробелов отклоняется до provider call. Draft validation остаётся отдельной. См. [A04/A05](AUDIT_FIXES_A04_A05.md).

`TimeBlock.origin` хранит назначенное сервером происхождение. Названия календарных блоков и старых блоков с неизвестным происхождением заменяются на `[private block]` в контексте чата и истории для черновика. Время, категория и completion остаются доступными для планирования. Совпадающие защищённые названия скрываются и в отправляемой копии переписки; локальный текст и данные replay guard не меняются. Undo сохраняет происхождение через подписанный `restore_proof`, связанный с расписанием, ID и названием. Без доказательства восстановленный блок получает `unknown`. Миграция 0010 не угадывает происхождение старых названий и не изменяет сами названия или интервалы.

`implicit_add` помогает распознать новую короткую активность, `replay_guard` проверяет повтор прежних add, `category_resolution` приводит слова модели к slug. Они сохранены после [R11](REFACTORING_R11.md). Корпус фиксированных SDK-ответов проверяет приложение, но не качество живой модели. Отказ и потеря semantic replay evidence при явном сбросе истории остаются известными ограничениями. Серверный `pending_intent` описан в [предложении](REFACTORING_R11_DESIGN.md) и пока не реализован.

`ai/chat_requests.py` резервирует UUID запроса под User lock до provider call и сохраняет terminal HTTP response в одной транзакции с изменением расписания. Повтор возвращает прежний результат до проверки устаревшей revision; смена lease-токена запрещает запись прежнему worker. `ChatRequest` хранится до удаления аккаунта и не зависит от удаления Schedule. Frontend сохраняет исходное тело в sessionStorage по account/date, повторяет неизвестный transport outcome с тем же UUID и предлагает Recover после ограниченного retry. Logout/Login и смена аккаунта очищают клиентские копии на уровне корня приложения. Подробности: [durable chat](DURABLE_AI_CHAT_REQUESTS.md).

## Frontend: владельцы состояния

| Владелец | Ответственность |
|---|---|
| `useSchedulePageController` | Составляет mutation owner, Undo, chat/draft и lifecycle страницы |
| `useScheduleRevision` | Канонический день, revision, writer phase, принятие ответа и reconciliation |
| `scheduleWriteCoordinator` | Pending settlement, минимальная подтверждённая revision и reload fields между экземплярами страниц |
| `useUndo`, `useMutationUndo` | Локальные снимки с датой, аккаунтом, версиями и регистрацией подтверждённого diff |
| `useChat`, `useDraft` | AI lifecycle, transcript, устаревшие ответы и ошибка провайдера |
| `useTimelinePresentation`, `useDrag` | Общая геометрия Classic/4a и проверка снимка перед drop |
| `useExternalSources`, `useEventImport` | Соединения провайдеров, lazy bootstrap и импорт событий |
| `useDatedResource`, `useIntegrationAccount`, `useTaskCompletion` | Scoped загрузки, connect/disconnect и optimistic task completion |
| `useAnalytics` | Заметки и упорядоченная фиксация обзора |

`Schedule.vue` связывает UI с этими владельцами. Date/account/context/request identity ограничивают принятие поздних ответов. Отмена HTTP не доказывает отмену серверной записи. Неопределённый результат требует reconciliation. POST/PATCH не повторяются автоматически. Стек Undo не переживает reload и не отменяет изменения другого устройства.

Координатор предоставляется корнем приложения через injection. При возврате A → B → A новый owner ждёт прежнюю запись и обновляет только текущий совпадающий аккаунт/день. Подтверждённая revision защищает и от старого navigation GET, пришедшего после POST. Блокировка сохраняется до завершения reload; ошибка синхронизации её не снимает. Analytics запрашивает вместе с днём review/streak. Session/user boundary очищает координатор; уничтоженный owner не может очистить состояние нового аккаунта. Это механизм текущего приложения, не durable journal и не межвкладочная синхронизация.

Theme задаётся одинаково в SSR и props. PiP принадлежит корню приложения, а страницы публикуют ему копии состояния. Переход между страницами не уничтожает окно; Login, потеря user identity и смена аккаунта очищают состояние и закрывают окно. Публикации уходящей Schedule используют поколение identity, поэтому запоздавший watcher или unmount не восстанавливает прежний снимок. Отклонённое редактирование категории возвращает принятую подпись или цвет и показывает `errors.detail`, если сервер не прислал ошибку поля. Подробности: [R09](REFACTORING_R09.md), [A06/A07](AUDIT_FIXES_A06_A07.md) и [RULES](../RULES.md).

## Интеграции и проверки

CalDAV, Google Calendar, Todoist и Habitica сохраняют собственные service adapters и независимые ключи Fernet. `common/integration_*` объединяет crypto, versioned cache, проверки конфигурации и resource-state envelope. Ключ кеша включает account version, дату, сохранённый пояс и нужный filter scope. Неудачный refresh сохраняет ранее показанные строки с ошибкой; disconnect инвалидирует reads и pending completion. Внешние задачи не включаются в AI context. См. [R08](REFACTORING_R08.md).

Google all-account failure сохраняет HTTP 200 с `account_errors` и failure metadata. Узкий hook adapter в `useDatedResource` сохраняет last-good события текущего контекста и показывает ошибку. Успешный пустой ответ очищает их; partial success принимает новый список вместе с per-account ошибками. Панель отображает banners независимо от строк. Смена даты, account/session context или saved zone не переносит прежний список в новый контекст.

Backend tests используют pytest, frontend tests используют Vitest. Общая локальная команда `make check` выполняет lint, type-check и оба suites; `make frontend-build` проверяет production assets. GitHub PR и deployment используют один reusable CI workflow с production dependency audit и SSH pinning check. Реальный запуск workflow в GitHub отдельно от локальных проверок ещё требует подтверждения. Browser smoke выполняется на тестовом пользователе и очищаемых данных; подключение к живым providers проверяется отдельно от fixtures.


## Версия frontend при deployment

Vite создаёт hashed assets и `.vite/release.json`. Workflow передаёт Git SHA через Docker build argument `RELEASE_VERSION`. `day_forge/frontend_release.py` проверяет metadata и файлы; settings использует версию для Inertia, а context processor передаёт entry/CSS в base.html. Metadata и backend поставляются в одном образе.

`common.middleware.FrontendVersionMiddleware` отклоняет старые JSON API запросы до view и обновляет старую Inertia-навигацию до bootstrap. `ReleaseInertiaMiddleware` сохраняет redirect после auth POST. `useHttp` отправляет версию bundle, `useFrontendRelease` и `FrontendReleaseNotice` предлагают ручной Reload без повторения записей. Проверки обновления, rollback и legacy клиента описаны в [отчёте](FRONTEND_RELEASE_VERIFICATION.md).
