# Браузерные проверки A00–A07

Проверка выполнена 17–18 октября 2026 года по Asia/Almaty (17 октября UTC), через CUA во встроенном браузере Codex. A00–A06 проверены через настоящий интерфейс. Для A07 проверены переходы на Login после Logout и истечения сессии, но проверка уже открытого окна PiP остаётся незавершённой: браузер объявляет поддержку API, однако окно не открывается.

Дополнение 19 октября: A07 закрыт через нативное управление обычным Google Chrome. Настоящее PiP сохранилось в Settings, закрылось при Logout и session expiry; после смены локального пользователя показало только новый блок. См. [последующий отчёт](POST_PR246_RELEASE_PIP_VERIFICATION.md). Ниже сохранён исходный прогон во встроенном браузере.

Исправлены две проблемы: системное подтверждение удаления категории заменено DOM-диалогом, а мобильная панель категорий больше не растягивает страницу. [Предыдущий отчёт](BROWSER_VERIFICATION_DESKTOP_MOBILE.md) сохраняет результаты основных сценариев с реальными AI-запросами. Этот прогон проверяет управляемые ошибки и гонки с заглушками провайдеров.

## Среда и доказательства

- Отдельный Django на `http://localhost:8007`, временная SQLite БД и отдельный namespace кеша. Обычный сервер на 8006 и рабочая БД не изменялись.
- Пользователь `audit-browser-local`, без staff/superuser. Два синтетических Google-аккаунта с адресами `example.invalid`, без действующих токенов.
- Vite обслуживает текущий frontend. Все действия пользователя, навигация, ввод, Cancel и подтверждения выполнены через CUA.
- Desktop 1440×900; мобильные проверки панели категорий и диалога при 390×844 и 320×740. Первые шаги импорта выполнены в исходном viewport 1280×720.
- Google service и AI SDK заменены только внутри отдельного fixture-процесса. Настоящие views, авторизация, CSRF, envelope, planner и persistence сохранены. Живые Google OAuth и AI-вызовы в этом прогоне не проверялись.
- [JSON-доказательства](evaluations/a00-a07-browser-2026-10-17.json): 63 записи HTTP/SDK/control, три SDK-запроса, состояния review до/после удаления категории, итоговые блоки и revision. Пароли, реальные токены и пользовательские данные не экспортированы.

## Пройденные сценарии

| Пункт | Действия и результат |
| --- | --- |
| A00: импорт без правила | `Private fixture appointment`, 10:03–10:37, попадает в расписание без округления, с категорией Other. |
| A00: правило и override | `Airport fixture` получает 20/10 минут пути и Personal, preview 14:40–16:10. В диалоге заменены значения на 5/15 и Health; сохранён блок 14:55–16:15. |
| A00: конфликт и повторное добавление | Повторный импорт занятого интервала показывает `This block overlaps with an existing block.` После удаления события повторное добавление в свободный интервал успешно. |
| A00: lifecycle off-grid | Удаление, Undo, completion и переименование сохраняют 10:03–10:37 и происхождение `calendar`. Итог подтверждён БД. Общий DOM-диалог блоков повторно проверен после его извлечения в общий компонент. |
| A00: конечный AI-ввод | После переименования импорта выполнен chat-запрос. Во всех трёх перехваченных SDK messages нет `Private fixture edited` и `Airport fixture`, есть `[private block]`. Сокрытие draft history отдельно покрыто backend suite; отдельного браузерного draft privacy-прогона здесь не было. |
| A01: category delete | После удаления расходной категории блоки и category maps переведены в sink. Актуальный review остался актуальным: revision/reviewed_revision 2/2, counts 1/1, заметка сохранена. Ранее устаревший review остался устаревшим: 3/0. |
| A01: repair | Analytics показывает `Current progress` и `Update reviewed summary`. Нажатие даёт `Reviewed summary`, убирает кнопку ремонта, сохраняет заметку и фиксирует reviewed_revision 3. |
| A02: A → B → A до commit | POST создания `Delayed A02 block` остановлен до view. После двух Inertia-переходов на A виден `Updating schedule`, новые записи запрещены. После явного release страница сама получает актуальные блоки и становится доступной; блок создан ровно один раз. |
| A03: SQLite contention | Отдельное соединение удерживает `BEGIN IMMEDIATE`. Существующий день открылся за 178 мс. Первый GET нового дня после штатных retries вернул 503 `Schedule temporarily unavailable. Please try again.`, не 500. CUA navigation deadline истёк раньше ответа; итоговый 503 подтверждён сервером и видимой страницей. |
| A04: ошибочный reply и продолжение | SDK отдаёт допустимый add с пустым explanation/ask. UI показывает фиксированную ошибку, HTTP 502, блок не появляется. Следующий `Try again.` из того же чата доходит до SDK, возвращает 200 и создаёт один `Audit AI recovery`, 13:00–13:30. |
| A05: полный provider failure | После успешного списка оба аккаунта отказывают. Фоновый refresh показывает общий баннер и две per-account ошибки, сохраняя прежние события. |
| A05: credentials, partial, empty | Retry при credentials failure сохраняет список и показывает Reconnect. Partial success оставляет события успешного аккаунта и ошибку второго. Следующий успешный пустой ответ очищает список и ошибки. |
| A05: новый контекст | После перехода с успешно загруженного 12 мая на 13 мая полный failure показывает ошибки без событий прежнего дня. |
| A06: повторный отказ | Несколько одинаковых 409 возвращают подпись Work, а не оставляют отвергнутый ввод. Отклонённый цвет rose возвращается в blue; `errors.detail` для 409 и 429 отображается. Для commit текстового поля использовались нативные клавиши CUA и Tab: одного программного fill было недостаточно. |
| A07: session boundary | Logout после попытки открыть PiP показывает Login. Удаление только fixture-сессий и переход по защищённой ссылке также показывают Login. Полный lifecycle настоящего PiP-окна не подтверждён, см. ниже. |

Для второго category-delete прогона через UI создана категория `Review audit`; два синтетических reviewed-дня привязаны к ней в fixture-БД. Снимки до и после находятся в JSON-доказательствах. Это подготовка состояния, не обход API во время проверяемого удаления. Первый native-confirm прогон не используется как доказательство нового диалога.

## Исправления

### Подтверждение удаления категории

`SettingsCategoriesPanel` использовал `window.confirm`. Команда клика завершилась CDP timeout, а `getJsDialog` не предоставил диалог. При восстановлении связи категория уже отсутствовала. Такой неопределённый результат мешает автономной проверке и делает повторный клик небезопасным.

Существующий диалог удаления блока выделен в [DeleteConfirmationDialog.vue](../frontend/src/components/DeleteConfirmationDialog.vue). Блоки сохраняют прежний текст и Undo. Категории получают свой заголовок и предупреждение о переносе ссылок и необратимости. Cancel не отправляет запрос и возвращает фокус. Подтверждение отправляет один DELETE; повторный confirm во время запроса игнорируется. Если категория исчезла или её подпись изменилась, подтверждение закрывается.

В браузере подтверждены Cancel, возврат фокуса на Delete, успешное удаление и мобильный диалог. В [регрессионных тестах](../frontend/tests/SettingsCategoriesPanel.test.ts) закреплены отмена, смена категории до подтверждения и единственный запрос при повторном confirm. Существующие проверки Escape, keyboard containment и удаления блоков сохранены.

### Переполнение мобильной панели категорий

До исправления при viewport 390 px `document.documentElement.scrollWidth` составлял 459 px. Строки категорий не переносились. Теперь строки и форма создания допускают перенос, ширина input ограничена доступным местом, swatch не сжимается. Повторные измерения: 390/390 и 320/320, горизонтального переполнения нет.

## A07: что не удалось подтвердить

Ограничение этого исходного прогона закрыто 19 октября в нативном Chrome. Описанные ниже попытки во встроенном браузере сами по себе успешной PiP-проверкой не считаются.

На Schedule доступна кнопка `Show indicator`, и браузер объявляет `documentPictureInPicture`. После семантического и нативного клика, в видимом окне и после свежей загрузки, кнопка не перешла в `Hide indicator`; доступного PiP-окна не появилось. Прочитанное состояние DOM API также не показывало открытого окна. Повторные клики не считаются успешной проверкой.

Поэтому переход Schedule → Settings с сохранением открытого PiP, затем Login с закрытием окна и защитой от поздней публикации остаётся отдельным незакрытым browser case. Существующие автоматические тесты root controller, publisher generation и pending-window cleanup прошли, но они не заменяют этот сценарий. Требуется браузерный сеанс с работающим Document PiP. Сам факт успешного Logout не доказывает очистку открытого PiP.

## Воспроизведение

Fixture-сервер сохранён в [backend/scripts/browser_audit_server.py](../backend/scripts/browser_audit_server.py). Он не импортируется приложением и отказывается использовать существующую директорию. Нужны установленные зависимости, настроенный Redis по обычным правилам AI system check и работающий Vite на 5173.

```sh
uv run python backend/scripts/browser_audit_server.py /tmp/day-forge-browser-new-run
```

Открыть `http://localhost:8007/accounts/login/`. Локальные fixture credentials заданы в скрипте; этот сервер нельзя использовать для настоящих аккаунтов. База, `controls.json` и `audit.jsonl` находятся в новой директории. Рабочие настройки и БД не переписываются.

Поля `controls.json`: `google` принимает `good`, `provider_error`, `credentials_error`, `partial`, `empty`; `ai` принимает `good`, `invalid`, `add`; `category_error` равен 0, 409 или 429. Менять только нужное поле, сохраняя остальные. Google обновляется через обычный 60-секундный poll либо видимую кнопку Retry после ошибки.

Для A02 установить `delay_write: true`, удалить старые marker-файлы в этой расходной директории, создать блок 10 мая 2027 года и дождаться `write_waiting`. Перейти стрелками на 11 мая и обратно, затем создать `release_write`. Пауза ограничена 90 секундами; факт явного release записывается в audit.

Для A03 открыть отдельное sqlite3-соединение к fixture-БД, удерживать `BEGIN IMMEDIATE`, проверить существующий и новый день, затем выполнить rollback. Для session expiry удалить сессии только в этой БД. Эти операции не относятся к рабочей базе проекта.

Автоматический UI-раннер Playwright в обход CUA не запускался. Сохранённый сервер воспроизводит данные и ошибки, но сам по интерфейсу не кликает.

## Проверки и артефакты

- Backend: 2038 passed, один платный R11-тест штатно пропущен.
- Frontend после исправлений: 1392 passed, 102 файла. Фокусные category/block tests: 68 passed.
- Ruff, Vue type-check, production build и `git diff --check` прошли.
- Рабочий сервер на 8006 оставлен запущенным. Fixture-процесс на 8007 остановлен после проверки; его временная БД сохранена для диагностики.

| Скриншот | Что видно |
| --- | --- |
| [Импорт без правила](screenshots/a00-a07-browser-2026-10-17/import-no-rule.png) | Off-grid время 10:03–10:37 |
| [Travel rule](screenshots/a00-a07-browser-2026-10-17/travel-rule-prefill.png) | Padding 20/10 и исходная категория |
| [Конфликт](screenshots/a00-a07-browser-2026-10-17/import-overlap.png) | Отказ повторного импорта |
| [Повторное добавление](screenshots/a00-a07-browser-2026-10-17/import-readded-free-slot.png) | Событие снова в свободном интервале |
| [Chat failure](screenshots/a00-a07-browser-2026-10-17/chat-invalid-reply.png), [recovery](screenshots/a00-a07-browser-2026-10-17/chat-recovered.png) | Ошибка и следующий успешный turn |
| [Google provider failure](screenshots/a00-a07-browser-2026-10-17/google-provider-failure-retained.png) | События рядом с ошибками |
| [Credentials failure](screenshots/a00-a07-browser-2026-10-17/google-credentials-retained.png) | Сохранённый список и Reconnect |
| [Ready empty](screenshots/a00-a07-browser-2026-10-17/google-ready-empty.png) | Успешный пустой список |
| [Failure нового дня](screenshots/a00-a07-browser-2026-10-17/google-new-date-failure-empty.png) | Нет событий прежней даты |
| [A02 до commit](screenshots/a00-a07-browser-2026-10-17/a02-before-commit.png), [после](screenshots/a00-a07-browser-2026-10-17/a02-after-commit.png) | Блокировка и автоматическое согласование |
| [A03 existing](screenshots/a00-a07-browser-2026-10-17/a03-existing-day-under-lock.png), [new day](screenshots/a00-a07-browser-2026-10-17/a03-new-day-503.png) | Чтение под lock и контролируемый отказ |
| [Review до ремонта](screenshots/a00-a07-browser-2026-10-17/stale-review-before-repair.png), [после](screenshots/a00-a07-browser-2026-10-17/review-repaired.png) | Сохранённая заметка и Reviewed summary |
| [Повторный отказ](screenshots/a00-a07-browser-2026-10-17/category-second-rejection.png), [429](screenshots/a00-a07-browser-2026-10-17/category-color-429.png) | Принятые подпись/цвет и detail |
| [Desktop dialog](screenshots/a00-a07-browser-2026-10-17/category-delete-dialog.png), [mobile](screenshots/a00-a07-browser-2026-10-17/mobile-category-dialog.png) | DOM-подтверждение категории |
| [Mobile до](screenshots/a00-a07-browser-2026-10-17/mobile-categories-before.png), [320 px после](screenshots/a00-a07-browser-2026-10-17/mobile-categories-after-320.png) | Исправленное переполнение |
| [Login после expiry](screenshots/a00-a07-browser-2026-10-17/a07-expired-session-login-mobile.png) | Настоящий переход на Login |
