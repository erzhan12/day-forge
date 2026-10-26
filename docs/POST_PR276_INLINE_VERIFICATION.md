# Production-проверка preferences inline после PR #276

26 октября 2026 года, Asia/Almaty. [Deploy #40232227232](https://github.com/erzhan12/day-forge/actions/runs/40232227232) успешно опубликовал `8a4743fe10cd08ce5902c36db77403be40158bc9`. Health-check вернул HTTP 200 на первой попытке в 01:49:35 по Алматы.

**English summary.** Production now omits editable controls and Add/Remove actions from empty preferences inlines on User add/change forms. Existing preferences remain visible as read-only text. Ten real HTTPS cases confirmed that ordinary User edits still succeed, injected preference writes are ignored and direct preference writes return 403. All temporary users and the isolated admin session were removed. No further application changes were needed.

## Релиз и проверка в Chrome

Login вернул точный Inertia version `8a4743fe10cd08ce5902c36db77403be40158bc9`. Запущен контейнер `ghcr.io/erzhan12/day-forge:8a4743fe10cd` с health `healthy`. JS/CSS загружаются с HTTP 200, правильными MIME-типами и immutable caching. TLS и закреплённый SSH host key проверялись штатно.

В production подготовлены два временных non-staff пользователя без usable password: один без preferences, второй с темой Strategic, gap 20 и подсказкой `Published inline verification`. Формы просмотрены в Chrome через существующую admin-сессию.

| Форма | Результат в браузере |
| --- | --- |
| User add | Открывается без 500. В секции preferences нет полей theme/chat_suggestions/gap, Add или Remove |
| User change без preferences | Открывается без 500. Пустая секция не содержит editable controls, Add или Remove |
| User change с preferences | Strategic, gap 20, подсказка и даты отображаются текстом. Полей ввода и Add/Remove нет |
| Заполненный inline после POST-проверок и reload | Все значения и отображённые timestamps совпадают с исходными |

Проверка DOM охватывает все `input`, `select`, `textarea` внутри preferences, кроме служебных hidden-полей. У пустого inline остаётся заголовок секции; лишних полей под ним нет. Его наличие не является ошибкой и не требует дополнительного изменения.

[Deploy](evidence/post-pr276-inline-2026-10-26/deploy.json), [runtime](evidence/post-pr276-inline-2026-10-26/runtime.json), [версия и assets](evidence/post-pr276-inline-2026-10-26/public-release.json), [наблюдения браузера](evidence/post-pr276-inline-2026-10-26/browser.json).

Скриншоты: [User add](screenshots/post-pr276-inline-2026-10-26/add-user.png), [пустой change inline](screenshots/post-pr276-inline-2026-10-26/empty-preferences.png), [заполненный до POST](screenshots/post-pr276-inline-2026-10-26/filled-preferences-before.png), [после POST](screenshots/post-pr276-inline-2026-10-26/filled-preferences-after.png). На них только синтетические аккаунты без пароля.

## Серверный запрет записи

POST отправлены отдельным HTTP-клиентом через настоящий production HTTPS endpoint, не Django Test Client. На сервере подготовлена изолированная сессия существующего администратора с TTL 300 секунд. Её cookie оставалась в памяти серверного процесса. Запросы использовали настоящие CSRF cookie/form tokens; отказ CSRF не засчитывался как отказ в правах.

| Проверка | Результат |
| --- | --- |
| User add GET | 200, editable preference controls отсутствуют |
| User add POST с подставленными preferences | 302, создан только обычный пользователь без пароля; preferences не созданы |
| User change POST для пользователя без preferences | 302, контрольное `first_name` сохранено; подставленные preferences не созданы |
| User change POST с попыткой сменить theme/gap/chat_suggestions | 302, контрольное имя сохранено; все поля preferences неизменны |
| User change POST с `preferences-0-DELETE=on` | 302, существующая строка preferences не удалена и не изменена |
| Прямой preferences add GET и POST | оба 403 |
| Прямой preferences change POST | 403 |
| Прямой preferences delete GET и POST | оба 403 |

Всего зафиксированы десять HTTPS cases; GET change-форм перед POST и чтения после записи дополняют эти результаты. Сохранение контрольного имени подтверждает, что сервер обработал обычную User форму. Сравнение hashes полного набора полей preferences, включая timestamps, подтверждает игнорирование policy-записей. До и после проверки у пустого пользователя 0 строк preferences, у заполненного одна и та же строка с gap 20.

[HTTP-результаты](evidence/post-pr276-inline-2026-10-26/admin-http.json).

## Очистка и проверки

Третий временный пользователь появился при положительной проверке User add POST. После завершения удалены все три тестовых пользователя, связанные preferences и изолированная admin-сессия. Приватный каталог с метаданными стенда удалён. Исходная браузерная сессия сохранена, созданная для проверки вкладка закрыта.

У существующего выделенного тестового аккаунта hash всей строки preferences, 22 Schedule и 0 блоков совпали до и после прогона. Admin audit успешных тестовых User POST сохранён. Побайтный rollback production-базы не выполнялся.

В Deploy прошли 2364 backend-теста, 1 существующий opt-in skip и 1459 frontend-тестов в 105 файлах. Lint, TypeScript, production npm audit, image retention, SSH pinning и production build прошли. Локально на том же исходном коде повторно прошли 11 admin-тестов. Runtime-код в этой проверке не менялся, поэтому полный локальный набор повторно не запускался.

[Очистка и сохранность](evidence/post-pr276-inline-2026-10-26/cleanup.json), [сводка проверок](evidence/post-pr276-inline-2026-10-26/checks.json).

Новых ошибок не обнаружено. Публикация `extra=0` и её production-проверка закрыты. AI, расписания, OAuth, миграции, production-рестарт и rollback вне штатного Deploy в этом smoke не использовались.

## Публикация после PR #277

26 октября отдельная проверка [Deploy #40235378375](https://github.com/erzhan12/day-forge/actions/runs/40235378375) подтвердила публикацию `4cd59c5579f94fab9c1a3172c3eaf9b649e98c09`. Все jobs прошли; health-check получил HTTP 200 на первой попытке в 02:29:49 по Алматы.

Независимый HTTPS-клиент без cookies получил Login с HTTP 200. Точный SHA совпал в `meta frontend-version`, Inertia version и содержимом опубликованного JS. Редиректов к другому ресурсу не было, проверка TLS оставалась включённой.

| Asset | GET | Размер | Content-Type | If-None-Match |
| --- | --- | --- | --- | --- |
| `app-37OoBZo1.js` | 200 | 491966 байт | `text/javascript` | 304, пустой body |
| `app-Cm2RWFvr.css` | 200 | 72635 байт | `text/css` | 304, пустой body |

Оба assets имеют immutable cache policy. SHA-256, ETag и полные response metadata сохранены в [HTTPS evidence](evidence/post-pr277-release-2026-10-26/public-release.json). [Метаданные Deploy](evidence/post-pr277-release-2026-10-26/deploy.json) фиксируют опубликованный commit и завершение jobs.

Встроенный Chromium отрисовал Login с формой Sign in и применённым оформлением. DOM страницы содержит тот же SHA и ссылки на проверенные JS/CSS; computed styles и [скриншот](screenshots/post-pr277-release-2026-10-26/login.png) подтверждают применение CSS. Ошибок в console log новой вкладки не было. `link.sheet` не доступен через изолированный DOM-инструмент, поэтому он не использовался как критерий загрузки: проверены HTTPS-ответ, computed styles и изображение страницы. [Браузерные результаты](evidence/post-pr277-release-2026-10-26/browser.json).

В самом Deploy прошли 2364 backend-теста, 1 существующий opt-in skip и 1459 frontend-тестов, а также lint, TypeScript, production npm audit, image retention, SSH pinning и production build. [Сводка](evidence/post-pr277-release-2026-10-26/checks.json).

Ошибок публикации не обнаружено, runtime-код не менялся. Эта проверка ограничена публичной Login и её сборкой. Авторизованных запросов, AI-вызовов, изменений расписания/настроек и SSH-команд не было; тестовые аккаунты не создавались. Результаты User admin на `8a4743f` сохранены выше. Временная браузерная вкладка закрыта.
