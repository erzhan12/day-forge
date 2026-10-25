# Production-проверка User admin после PR #275

Дополнение после PR #276: [production-проверка `8a4743f`](POST_PR276_INLINE_VERIFICATION.md) закрыла публикацию `extra=0`. Лишних полей пустого inline больше нет, существующие preferences показаны текстом, запрет записи подтверждён реальными HTTPS POST. Новых ошибок не найдено. Ниже сохранён исторический результат релиза `3a0e294`.

26 октября 2026 года, Asia/Almaty. [Deploy #40230966870](https://github.com/erzhan12/day-forge/actions/runs/40230966870) опубликовал `3a0e29416f2a74eccfdecc24293602aa80ef90a1`. Все jobs прошли; HTTPS health-check вернул 200 на первой попытке 26 октября в 01:34:13 по Алматы.

**English summary.** Production add/change User admin forms now render without 500, including users with no preferences and users with existing preferences. Ten real HTTPS checks confirmed that user edits succeed while injected preferences creates/updates/deletes are ignored and direct preferences writes return 403. Existing preferences, including timestamps, remain unchanged. Django still renders inert editable controls for an empty inline; a local `extra=0` follow-up removes those controls and passes the full suites, but is not deployed yet.

## Опубликованный релиз

Login возвращает Inertia version `3a0e29416f2a74eccfdecc24293602aa80ef90a1`. Запущен контейнер `ghcr.io/erzhan12/day-forge:3a0e29416f2a`, его health имеет значение `healthy`. JS/CSS загрузились с HTTP 200, правильными MIME-типами и immutable caching. Проверка TLS и закреплённого SSH host key оставалась включённой.

[Deploy](evidence/post-pr275-user-admin-2026-10-26/deploy.json), [runtime](evidence/post-pr275-user-admin-2026-10-26/runtime.json), [SHA и assets](evidence/post-pr275-user-admin-2026-10-26/public-release.json).

## Методика и очистка

В production через ORM подготовлены два временных пользователя: один без preferences, второй с темой `strategic`, gap 20 и синтетической подсказкой. У обоих нет usable password, staff/superuser-прав, групп, интеграций или расписаний. Позже положительная проверка User add POST создала третьего временного пользователя без пароля и без preferences.

Формы просмотрены в Chrome через существующую admin-сессию. POST отправлены отдельным HTTP-клиентом через настоящий HTTPS endpoint, а не Django Test Client. На сервере для этого подготовлена отдельная сессия существующего администратора с TTL 300 секунд. Cookie оставалась в памяти серверного процесса и не выводилась в evidence. Использованы настоящие CSRF cookie и form tokens; отказ CSRF не засчитывался как успешная проверка прав.

Нормальные поля User формы получены из её HTML. Для положительного контроля менялось только синтетическое `first_name` временного пользователя. Одновременно передавались подставленные поля inline. После запроса ORM подтверждала сохранение имени пользователя и неизменность полного набора полей preferences, включая timestamps. Это отличает запрет записи preferences от отказа всей формы.

После проверок удалены отдельная admin-сессия, три временных пользователя и их preferences. Исходная браузерная сессия администратора сохранена. У существующего выделенного тестового аккаунта hash всей строки preferences, 22 Schedule и 0 блоков совпали до и после проверки. Admin audit успешных тестовых User POST сохранён; побайтный rollback production-базы не выполнялся. AI, расписания и интеграции в этом прогоне не использовались.

[Сохранность и очистка](evidence/post-pr275-user-admin-2026-10-26/cleanup.json).

## Результаты production

| Сценарий | Результат |
| --- | --- |
| User add GET | 200; форма открылась в Chrome без 500 |
| User add POST с отключённым паролем и подставленным preferences inline | 302; создан только обычный пользователь, preferences не созданы |
| User change GET, preferences отсутствуют | 200 в Chrome и HTTP-клиенте; без 500 |
| User change POST, попытка создать preferences | 302; синтетическое имя сохранено, preferences по-прежнему отсутствуют |
| User change GET, preferences существуют | 200; Strategic, gap 20 и подсказка показаны только для чтения |
| User change POST, попытка изменить theme/gap/chat_suggestions | 302; имя сохранено, все поля preferences и timestamps прежние |
| User change POST с `preferences-0-DELETE=on` | 302; существующая строка preferences сохранена без изменений |
| Прямой preferences add GET и POST | оба 403; новая строка не создана |
| Прямой preferences change POST | 403; существующая строка неизменна |
| Прямой preferences delete GET и POST | оба 403; существующая строка не удалена |

Всего HTTP-клиент выполнил десять проверок с отдельными outcomes в evidence. Просмотр change-форм перед POST и повторные чтения дополняют эти десять записей. После POST заполненный inline повторно загружен в Chrome: Strategic, gap 20, подсказка и даты остались прежними.

[HTTP-результаты и hashes preferences](evidence/post-pr275-user-admin-2026-10-26/admin-http.json), [наблюдения браузера](evidence/post-pr275-user-admin-2026-10-26/browser.json).

Скриншоты: [User add](screenshots/post-pr275-user-admin-2026-10-26/add-user.png), [пустой inline](screenshots/post-pr275-user-admin-2026-10-26/empty-preferences.png), [заполненный inline после POST](screenshots/post-pr275-user-admin-2026-10-26/filled-preferences.png). Они показывают только синтетические аккаунты без пароля.

## Дополнение: лишние поля пустого inline

В опубликованном `3a0e294` пустой inline на add/change формах всё ещё показывает theme, chat suggestions, gap и Remove. Запрет записи при этом работает: реальные User add/change POST с такими полями не создают preferences. Заполненный inline показывает только текст.

Причина оставшихся контролов: у `StackedInline` не задан `extra=0`; для OneToOne-связи Django строит дополнительную пустую форму. Локально добавлен `UserPreferencesInline.extra = 0`. Это убирает пустые поля и сохраняет показ существующих preferences. Permission-методы по-прежнему возвращают `False`.

Существующие регрессионные тесты расширены: HTML User add и change не должен содержать именованные controls для theme/chat_suggestions/gap. Проверены пустое и непустое состояния, а также сохранён прежний crafted POST с проверкой отсутствия policy-записей.

До изменения два случая падали на видимых полях пустого inline, 9 admin-тестов проходили. После изменения все 11 проходят. **Это UI-дополнение пока локальное, production всё ещё показывает лишние поля пустого inline.** Исправление 500 и серверный запрет записи в production подтверждены независимо от него.

## Автоматические проверки

- Deploy опубликованного `3a0e294`: 2364 backend passed, 1 существующий opt-in skip; 1459 frontend passed. Lint, TypeScript, production audit, image retention, SSH pinning и build прошли.
- После локального `extra=0`: `make check` прошёл, 2364 backend passed, 1 skip; 1459 frontend passed в 105 файлах. Ruff и TypeScript прошли.
- `makemigrations --check --dry-run`: изменений нет. Django system check: ошибок нет.

[Сводка проверок](evidence/post-pr275-user-admin-2026-10-26/checks.json). Новые миграции, production-рестарт и rollback не выполнялись. Реальный iOS/Safari, AI и OAuth здесь не проверялись.
