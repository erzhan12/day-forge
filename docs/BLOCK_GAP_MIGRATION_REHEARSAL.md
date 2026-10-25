# Контейнерная репетиция миграции gap и rollback образа

24 октября 2026 года, Asia/Almaty. Исходный main: `e99ed0ecc1f36ede1e617660f4bb0b69b148213e`. Исправленный кандидат: `592d8483dd90eec9a1a9a75ada9d8012cca15853`. Выполнены три локальных прогона на отдельных копиях `db/day_forge.db`: один воспроизводит ошибку, два подтверждают исправление. Использованы настоящие production entrypoint, uvicorn ASGI, Redis и reverse proxy.

**English summary.** Container rehearsal confirmed that gap values 0/10/20 survive upgrade, restart, image rollback and reupgrade. It exposed a rollback-only 500 when pre-gap code creates a user's first preferences row. A forward migration adding a database default of 10 fixes that insert while retaining customized gaps and legacy preference/manual writes. The fix is local and has not been deployed.

## Найденная ошибка

Миграция `templates_mgr.0006` добавляет обязательное поле `default_block_gap_minutes` с Python-default 10. Django заполняет существующие строки этим значением, но после миграции SQLite-колонка не имеет постоянного SQL-default.

Образ до PR #265 не знает о новом поле. После rollback его ORM вставляет preferences без этой колонки. Для пользователя, у которого preferences ещё нет, `GET /api/user/preferences/` пытается создать строку и возвращает 500 из-за `NOT NULL constraint failed: templates_mgr_userpreferences.default_block_gap_minutes`.

Уже существующие preferences продолжали работать: сохранённые 0/10/20 переживали rollback, изменение тем и подсказок в старом образе не затирало gap. Поэтому проверка только существующих пользователей пропустила бы ошибку.

Исходный отказ подтверждён двумя способами:

- Новый migration-тест использовал историческую ORM-модель из `0005` для INSERT после обновления схемы. До исправления: 1 failed, 1 passed; ошибка `NOT NULL` на поле gap.
- Контейнерный сценарий со старым образом `560e03f`, затем исходным main `e99ed0e` и rollback получил HTTP 500 при первом запросе preferences нового пользователя. Предыдущие этапы upgrade/restart/retention прошли. [Исходный контейнерный прогон](evidence/block-gap-migration-2026-10-24/unfixed-rehearsal.json) намеренно сохраняет `success: false`.

## Исправление

Поле модели сохраняет Python-default 10 и получает `db_default=10`. Новая миграция [0007](../backend/templates_mgr/migrations/0007_alter_userpreferences_default_block_gap_minutes.py) устанавливает постоянный DB-default. Опубликованная `0006` не менялась.

При пропуске колонки старым INSERT база записывает 10. Явные значения 0/10/20, owner, темы, подсказки, IDs и timestamps существующих preferences сохраняются. Тип, обязательность поля и API-валидация 0–120 с шагом 5 остаются прежними. SQL-default не заменяет проверку API и не делает null допустимым.

[Сравнение схем](evidence/block-gap-migration-2026-10-24/schema-comparison.json): после исходного обновления `not_null=true`, `database_default=null`; после исправления `not_null=true`, `database_default="10"`. При rollback миграции не обращались назад.

## Изоляция и исходная база

Исходная локальная база содержит 26 прикладных таблиц и 1204 строки; `templates_mgr.0005` применена, колонки gap ещё нет. Каждая репетиция получила новую копию через SQLite backup API. Исходная база открывалась только для чтения. Её семантический hash до и после всех прогонов совпал: `a50969fd1c0c6d2dd41b43fe97fa927887387b3fcaba5ac2acce4d987ff7c575`.

Runner сохраняет hashes исходных строк и проверяет их наличие после обновления. При сравнении старой и новой схемы из проекции preferences исключается только добавленная колонка gap; значения gap проверяются отдельно. Это сохраняет чувствительность сравнения к изменениям темы, подсказок и остальных полей. Все исходные строки сохранены.

Web и Redis работают во внутренней Docker-сети. Только proxy публикует `127.0.0.1:8014`; у web и Redis нет host ports. Используются отдельные secrets и dummy-настройки интеграций. AI и внешний polling выключены, provider отсутствует. Production, SSH и платные AI-сервисы не использовались. [Проверки сохранности и изоляции](evidence/block-gap-migration-2026-10-24/safety.json).

## Исправленный сценарий

| Этап | Проверенный результат |
| --- | --- |
| Старый образ `560e03f` на схеме `0005` | Три отдельных non-staff пользователя, существующие preferences и контрольные блоки; gap отсутствует в старом API |
| Обновление на кандидат `592d848` | Entrypoint применяет `0006` и `0007`; все прежние preferences получают 10, остальные поля и исходные строки совпадают |
| Сохранение gap через локальный proxy и реальный API | Три пользователя независимо сохраняют 0, 10 и 20 через PATCH; raw SQLite и GET подтверждают значения |
| Настоящий restart web | Entrypoint выполняется повторно; hash всей тестовой базы совпадает, 0/10/20 и контрольные блоки сохранены |
| Rollback на образ `560e03f` с той же базой, secrets и static volume | Старый API работает; сохранённые в колонке 0/10/20 остаются прежними |
| Записи старого кода | Каждый пользователь меняет тему и подсказки, создаёт ровно один блок 12:00–12:25 с `expected_revision`; revision растёт на 1, исходные блоки неизменны, gap не затирается |
| Первый preferences нового пользователя в старом образе | HTTP 200; неизвестная старому коду колонка получает DB-default 10 |
| Повторное обновление на `592d848` | GET возвращает 0/10/20, изменения тем и подсказок сохранены; контрольные и добавленные при rollback блоки совпадают по всем полям; новый пользователь сохраняет 10 |
| Завершение | Django system/migration checks проходят; контейнеры и сети всех трёх стендов удалены |

Сессии трёх пользователей сохранялись при смене образов; API-запросы использовали CSRF, актуальную версию frontend и идентификатор пользователя. HTTP proxy на loopback передаёт HTTPS forwarding header; реальная TLS-терминация здесь не проверяется.

Старый образ использует прежний фиксированный gap 10 и не показывает новую настройку. Сохранность 0/20 означает сохранность данных для повторного обновления, а не поддержку настройки старым кодом.

[Полный успешный прогон](evidence/block-gap-migration-2026-10-24/fixed-rehearsal.json). [Точные исходные commits и локальные image IDs](evidence/block-gap-migration-2026-10-24/images.json). Все образы собраны локально из указанных commits; это не скачанные production images.

## Воспроизведение

Runner: [deployment/scripts/rehearse_block_gap.py](../deployment/scripts/rehearse_block_gap.py). Подготовка образов описана в [deployment runbook](../deployment/README.md#gap-preference-migration-and-image-rollback). Нужна локальная копия базы до `0006`. База с уже существующей колонкой gap отклоняется: runner не удаляет пользовательские настройки для имитации старой схемы.

После сборки образов:

```sh
uv run python deployment/scripts/rehearse_block_gap.py \
  --source-db db/day_forge.db \
  --output-dir /tmp/day-forge-gap-rehearsal-new \
  --old-image day-forge-rehearsal:gap-before-265 \
  --old-version 560e03fbdd7757eb872f0535710d24a1ea622c0e \
  --new-image day-forge-rehearsal:gap-db-default \
  --new-version 592d8483dd90eec9a1a9a75ada9d8012cca15853 \
  --port 8014
```

`--output-dir` должен быть новым каталогом под `/tmp`; занятый Docker project отклоняется. Общий harness гарантирует teardown и записывает отказ в evidence при ошибке выполнения, сохранения логов или cleanup. Runner оставляет копии базы, sandbox secrets и контейнерные логи в закрытом временном каталоге для проверки. После этой репетиции все три каталога и временные исходники сборок удалены; в репозитории сохранён только обезличенный evidence.

## Тесты и дальнейшая публикация

- До исправления migration-регрессия воспроизводит `NOT NULL`; после исправления оба migration-теста проходят.
- 8 focused-тестов: миграции, исторический ORM INSERT, проекция сохранности, отказ от reverse migration и cleanup.
- `make check`: 2362 backend passed, 1 существующий opt-in skip; 1459 frontend passed в 105 файлах. Ruff и TypeScript прошли.
- `makemigrations --check --dry-run` не обнаружил изменений; Django system check прошёл.
- Production build выполнен production Dockerfile при сборке каждого образа. Image-retention tests прошли, production npm audit: 0 vulnerabilities.

[Результаты проверок](evidence/block-gap-migration-2026-10-24/checks.json).

25 октября, при подготовке PR #273: после замечания ревью проверка наличия `0005` в исходной базе заменена с `assert` на явный `ValueError`. Тест подтверждает отказ без изменения базы; отдельный запуск `python -O` тоже отклоняет такую базу. 8 focused-тестов и Ruff прошли повторно. Сохранённые контейнерные результаты относятся к указанному выше кандидату `592d848`; это уточнение ранней проверки входных данных не меняет миграцию или проверенный сценарий.

25 октября исправление опубликовано через PR #273: релиз `8fd831d` прошёл [production-проверку](POST_PR273_GAP_PRODUCTION_VERIFICATION.md). Прямое чтение базы подтвердило применённую `0007`, NOT NULL и SQL-default 10. Сохранение 0/10/20, первый preferences GET и исторический ORM INSERT прошли; временные записи удалены. Отдельный найденный 500 в User admin исправлен локально и ещё не опубликован.

Перед rollback рабочего релиза на код до PR #265 необходимо сначала применить совместимую схему с `0007`, затем оставить эту схему и DB-default на месте при смене образа. Обращение `0006` назад удаляет gap-значения и не входит в проверенный rollback.
