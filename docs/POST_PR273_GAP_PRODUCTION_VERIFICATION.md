# Production-проверка gap после PR #273

Дополнение 26 октября: [production-проверка после PR #275](POST_PR275_USER_ADMIN_VERIFICATION.md) подтвердила отсутствие 500 в User add/change с пустым и заполненным preferences inline и реальный запрет policy-записей через HTTPS POST. Ниже сохранены результаты 25 октября. Лишние поля пустого inline убраны отдельным локальным UI-дополнением, которое ещё не опубликовано.

25 октября 2026 года, Asia/Almaty. Проверен опубликованный релиз `8fd831d39aa0a17a5c3a0efb187dc1bb20527479` на [dayforge.habitreward.org](https://dayforge.habitreward.org). [Deploy #40128965066](https://github.com/erzhan12/day-forge/actions/runs/40128965066) прошёл все jobs; health-check завершился 25 октября в 01:20:10 по Алматы с HTTP 200 на первой попытке.

**English summary.** Production release `8fd831d` has migration `0007` applied and a persistent SQL default of 10. Gap values 0/10/20 survived reload and fresh login on the dedicated test account. A new non-staff user's first preferences GET returned 200 and created exactly one row; a historical ORM INSERT also received 10 in a transaction that was rolled back. A separate User admin 500 was reproduced and fixed locally; that admin fix is not deployed yet.

## Опубликованный код и схема

- HTML Login и Settings возвращают точный Inertia version `8fd831d39aa0a17a5c3a0efb187dc1bb20527479`.
- Production-контейнер запущен из `ghcr.io/erzhan12/day-forge:8fd831d39aa0`, его health имеет значение `healthy`.
- JS `/static/assets/app-BvVrdCI3.js` и CSS `/static/assets/app-Cm2RWFvr.css` загружаются с HTTP 200, корректными MIME-типами и immutable caching. Hashes сохранены в evidence.
- Через SSH с проверкой уже закреплённого host key прочитана настоящая production-база внутри контейнера. В `django_migrations` присутствует `templates_mgr.0007_alter_userpreferences_default_block_gap_minutes`.
- `PRAGMA table_info(templates_mgr_userpreferences)` подтверждает `NOT NULL` и `database_default="10"` у `default_block_gap_minutes`. `PRAGMA integrity_check` возвращает `ok`.

Миграции вручную не запускались: проверено состояние после штатного Deploy. Контейнер не перезапускался, старая версия на production не устанавливалась.

[Deploy](evidence/post-pr273-gap-2026-10-25/deploy.json), [контейнер](evidence/post-pr273-gap-2026-10-25/runtime.json), [production-схема](evidence/post-pr273-gap-2026-10-25/production-schema.json).

## Сохранение 0/10/20

Использован существующий выделенный non-staff тестовый аккаунт. Его исходный gap равнялся 10. Credentials прочитаны из приватного файла вне репозитория и отправлены только на HTTPS production-домен. Проверка выполнена независимым HTTP-клиентом с обычной сессией, CSRF, текущим `X-Frontend-Version` и проверкой владельца страницы Settings перед записью.

| Значение | PATCH | Повторный GET | Новый HTML Settings | Logout и свежий вход |
| --- | --- | --- | --- | --- |
| 0 | 200, сохранено 0 | 200, gap 0 | gap 0 | gap 0 |
| 10 | 200, сохранено 10 | 200, gap 10 | gap 10 | gap 10 |
| 20 | 200, сохранено 20 | 200, gap 20 | gap 20 | gap 20 |

GET/PATCH сохраняют `Cache-Control: private, no-store`. На каждом этапе тема и подсказки совпадали с исходными. После матрицы gap восстановлен в 10 и проверен ещё одним новым входом. Финальный Logout подтверждён редиректом защищённого API на Login.

Расписания не редактировались, AI не вызывался. После проверки у тестового аккаунта осталось 22 Schedule и 0 блоков, как до неё. API-записи обновляют timestamp preferences; восстановление значения не означает побайтный rollback базы.

[Результаты API и hashes assets](evidence/post-pr273-gap-2026-10-25/preferences-api.json).

## Первое создание preferences и старый INSERT

Через ORM в production-контейнере создан временный пользователь без staff/superuser-прав. Его credentials были случайными и хранились в отдельном файле с правами `0600` вне репозитория.

1. До входа и после Login POST проверено отсутствие `UserPreferences`. Редирект после Login не выполнялся, чтобы Schedule/Settings не создали preferences раньше целевого запроса.
2. Первый `GET /api/user/preferences/` вернул HTTP 200, тему `classic` и gap 10. Прямое чтение базы подтвердило ровно одну строку.
3. Повторный GET вернул 200; строка и её ID остались прежними.
4. Дополнительно загружена историческая ORM-модель `UserPreferences` из состояния `0005`. Её INSERT не передаёт колонку gap. На действующей production-схеме такой INSERT получил значение 10 от базы.
5. Исторический INSERT и его вспомогательный пользователь создавались внутри одной короткой `transaction.atomic()` с явным rollback. Загрузка исторической модели не выполняла миграции и не меняла схему.
6. Выполнен Logout временного пользователя. Его аккаунт и связанные настройки удалены; отсутствие аккаунта проверено. Временный файл credentials удалён. Gap и количество расписаний/блоков исходного тестового аккаунта остались прежними.

Это напрямую подтверждает отсутствие 500 при первом создании настроек текущим релизом и работу SQL-default для старого INSERT. Полный HTTP-сценарий со старым образом остаётся результатом отдельной [контейнерной репетиции](BLOCK_GAP_MIGRATION_REHEARSAL.md), а не переключением production на старую версию.

[Результаты первого запроса, старого INSERT и очистки](evidence/post-pr273-gap-2026-10-25/first-preferences.json).

## Найденный 500 в User admin

При подготовке нового аккаунта браузер открыл `/admin/auth/user/add/` на опубликованном релизе и получил страницу `Server Error (500)`. Это отдельный путь от API preferences.

Причина подтверждена локально: `UserPreferencesInline` наследует `PolicyInspectionMixin.has_add_permission(request)`, а Django вызывает inline-метод как `has_add_permission(request, obj)`. Возникает `TypeError`. Ошибка относится и к форме изменения пользователя, когда Django строит этот inline.

Исправление: метод принимает необязательный `obj=None` и продолжает возвращать `False`. Право менять сами пользовательские записи не меняется; запись preferences через admin по-прежнему запрещена.

Регрессионные тесты проверяют настоящие GET форм добавления и изменения пользователя с пустым и непустым preferences inline. Сформированный POST к форме пользователя пытается передать тему и gap через inline: пользователь сохраняется, но preferences не создаются и не меняются, включая timestamps существующей строки.

До исправления два теста падали с тем же `TypeError`, 9 проходили. После исправления все 11 admin-тестов проходят. **Исправление admin пока локальное и требует отдельной публикации.** Для production-проверки первого preferences GET временный пользователь был создан через ORM, поэтому ошибка admin не оставила этот сценарий непроверенным.

![Production User admin: Server Error (500)](screenshots/post-pr273-gap-2026-10-25/user-add-500.png)

## Автоматические проверки и границы

- Deploy опубликованного `8fd831d`: 2362 backend passed, 1 существующий opt-in skip; 1459 frontend passed. Lint, TypeScript, npm production audit, image retention, SSH pinning и production build прошли.
- После локального исправления User admin: `make check` прошёл, 2364 backend passed, 1 skip; 1459 frontend passed в 105 файлах. Ruff и TypeScript прошли.
- `makemigrations --check --dry-run`: изменений нет. Django system check: ошибок нет.
- В этом прогоне не выполнялись AI-запросы, изменения расписания, OAuth, production-рестарт, image rollback или reverse migrations. Responsive UI настройки и AI-placement 0/10/20 проверялись ранее и описаны в [gap smoke](BLOCK_GAP_PRODUCTION_VERIFICATION.md).

[Сводка проверок](evidence/post-pr273-gap-2026-10-25/checks.json). В evidence нет логинов, паролей, cookies, CSRF-токенов, ключей SSH или содержимого чужих расписаний.
