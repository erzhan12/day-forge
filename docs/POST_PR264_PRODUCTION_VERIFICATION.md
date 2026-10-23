# Production после PR #264

После merge PR #267 Deploy остановился на нестабильной синхронизации отдельного SQLite snapshot-теста, до сборки образа. Исправление теста опубликовано через PR #268, Deploy `2496bd7` завершился успешно. Runtime-код приложения не менялся; результаты проверки Schedule admin сохраняются. Подробности находятся в [отдельном отчёте](POST_PR267_SQLITE_DEPLOY_FIX.md).

Обновление после PR #266: исправление Schedule admin опубликовано как `2f78696`. Пустой и непустой inline открываются без 500; read-only интерфейс и отказы add/delete проверены на production. Подробности находятся в разделе [«Проверка после Deploy PR #266»](#проверка-после-deploy-pr-266). Исходные AI-проверки ниже относятся к прежнему релизу `ee8d914`.

23 октября 2026 года, Asia/Almaty. Проверен текущий опубликованный релиз `ee8d914443d8b5f7141201bcca3b304e45989f05`. Он включает merge PR #264 (`560e03f`) и последующий PR #265 с настройкой промежутка между блоками. Ветка отчёта и дополнительного исправления: `codex/post-pr264-production-verification`.

## Результат

[Deploy PR #264](https://github.com/erzhan12/day-forge/actions/runs/39930768640) и [Deploy текущего релиза](https://github.com/erzhan12/day-forge/actions/runs/39947942233) завершились успешно. Проверены validation, build/push, deploy и health-check. Login и авторизованные desktop/mobile страницы загрузили `ee8d914`. JS/CSS вернули 200 с immutable cache policy. [Версия и assets](evidence/post-pr264-2026-10-23/public-release.json), [Deploy #264](evidence/post-pr264-2026-10-23/deploy-pr264.json), [текущий Deploy](evidence/post-pr264-2026-10-23/deploy-current.json).

Все запрошенные AI-сценарии прошли: `after` в названии, уточнение времени, отказ с сохранением разрешения, корректный повтор, частичный план без дублей, replay `request_id`, Undo и Logout. Использован настоящий production-провайдер, без заглушек или подмены браузерных ответов. Scoped AI-audit подтвердил 15 успешных обращений: по пять через desktop, mobile и независимый HTTP-клиент. [Сводка AI-audit](evidence/post-pr264-2026-10-23/ai-audit-summary.json).

Дополнительная административная проверка нашла отдельный 500 при просмотре Schedule. Он воспроизведён локально и исправлен в PR #266. Публикация и отдельная production-проверка исправления описаны в дополнении ниже.

## Аккаунт и границы записи

Использован прежний выделенный неадминистративный аккаунт, user ID 2. Credentials прочитаны из приватного файла вне репозитория. Пароль, настройки, шаблоны и интеграции не менялись. Production-база не скачивалась, SSH не использовался.

Перед записью независимый HTTPS-клиент подтвердил пустые даты 10, 11 и 12 ноября 2027 года, revision 0. Первые две использованы браузером, третья отдельным HTTP-клиентом. После login приложение открывало сегодняшний день; перед записью выполнялась явная навигация на выбранную будущую дату. [Preflight](evidence/post-pr264-2026-10-23/preflight.json).

## Браузер: desktop и mobile

Браузерные действия выполнены через CUA. Desktop: измеренные 1440×900. Mobile: свежий вход и реальные AI-запросы при 390×844, затем завершённый partial, Undo и Logout при 320×740. Вторая browser-сессия начата после подтверждённого desktop Logout.

| Сценарий | Desktop | Mobile |
| --- | --- | --- |
| Anchor | Ручной `R264 desktop anchor`, 09:00–09:30 | Ручной `R264 mobile anchor`, 09:00–09:30 |
| Название с `after` | Запрос `R264 desktop after anchor` после anchor, длительность 30 минут, сначала вопрос о начале | Та же структура с `R264 mobile after anchor` |
| Первое уточнение | Вопрос без нового блока; предыдущая Undo доступна | То же |
| Неверный ответ `08:00` | Relative guard оставил вопрос «after R264 desktop anchor»; новых записей нет, Undo сохранена | Вопрос «after R264 mobile anchor», без записи и потери Undo |
| Корректный повтор | `14:00` создал один блок 14:00–14:30, намерение закрыто | `15:00` создал один блок 15:00–15:30, намерение закрыто |
| Undo | Первая вернула только anchor, вторая пустой день | То же |
| Partial | Сразу принят `R264 desktop accepted` 13:00–13:30; второй блок остался pending с общим вопросом | Сразу принят `R264 mobile accepted` 13:00–13:30; второй остался pending |
| Завершение partial | `15:00 to 15:30` добавил только unresolved, ровно два блока | Ровно два блока; независимые GET до/после подтвердили сохранение ID accepted `1163` |
| Undo partial | Сначала убран unresolved, затем accepted | Обе отмены выполнены кнопкой при 320 px |
| Logout | При открытом чате hit-test центра Logout положителен, физическое нажатие открыло Login | То же при 320 px, кнопка не перекрыта чатом |
| История | Back показывает Login, reload защищённого адреса перенаправляет на Login | То же |

Независимые HTTPS-чтения подтвердили корректные интервалы, отсутствие дублей и возврат к пустым дням. В mobile partial accepted имеет тот же ID до и после уточнения. В desktop результат содержит исходный accepted и один unresolved; AI-audit показывает только unresolved во втором действии. [Server observations](evidence/post-pr264-2026-10-23/server-observations.json), [browser observations](evidence/post-pr264-2026-10-23/browser-observations.json).

При 320 px clientWidth и scrollWidth равны 305 px, innerWidth 320 px включает scrollbar. Горизонтального переполнения нет. Проверка Logout выполнялась по измеренному центру кнопки с `elementFromPoint`, затем настоящим нажатием CUA. [Desktop после корректного повтора](screenshots/post-pr264-2026-10-23/desktop-corrected-time-applied.jpg), [mobile после повтора](screenshots/post-pr264-2026-10-23/mobile-corrected-time-applied.jpg), [Logout при 320 px](screenshots/post-pr264-2026-10-23/mobile-320-logout-visible.jpg).

Первый Clear сразу после mobile Undo не очистил диалог в том же кадре. После завершения Undo отдельное нажатие Clear сработало. Запрос partial отправлен только после визуального подтверждения пустого чата. Этот промежуточный кадр не засчитан как очистка и не потребовал нового AI-вызова.

## Durable request_id через production HTTP

Отдельный клиент использовал настоящие JSON endpoints, CSRF, frontend version и отдельную сессию тестового аккаунта. Это самостоятельный серверный прогон, он не перехватывал браузерный transport.

- Точные тела и UUID первого вопроса, успешного ответа, Cancel, partial и его завершения вернули побайтно прежние ответы. Состояние и revision при replay не изменились.
- Прежний UUID с изменённым телом вернул `409 request_id_conflict`.
- Replay успешного ответа после restore/Undo вернул receipt, но не восстановил блок.
- Новый UUID со ссылкой на закрытый intent вернул `409 pending_intent_stale`.
- Explicit Cancel закрыл новое намерение без записи; его replay также не изменил день.
- Partial создал один accepted. Завершение добавило только unresolved и сохранило ID accepted. Оба replay не добавили дублей.
- После restore к пустому baseline replay завершения partial также не восстановил блоки.

[HTTP smoke](evidence/post-pr264-2026-10-23/http-smoke.json): `success: true`. Здесь Undo проверяется через тот же revision-guarded restore endpoint; настоящая кнопка Undo отдельно проверена в обоих браузерных сценариях. После завершения HTTP-клиент вышел из аккаунта и подтвердил Login на защищённом GET. Потеря transport и конкурентная нагрузка в этом прогоне не инжектировались.

AI-audit по Schedule IDs 134, 135 и 136 подтвердил ровно по пять записей, все `success=True`. Replay и Cancel дополнительных AIInteraction не создали. Сохранены только scoped records собственных синтетических дней, без административной шапки или посторонних записей: [desktop](evidence/post-pr264-2026-10-23/desktop-model-audit.json), [mobile](evidence/post-pr264-2026-10-23/mobile-model-audit.json), [HTTP](evidence/post-pr264-2026-10-23/http-model-audit.json).

В этих 15 ответах модель не присылала `task_id: null` в исполняемых add. Проверка подтверждает работу пользовательских сценариев и канонического prompt. Защитная нормализация null-target отдельно покрыта регрессионными тестами PR #264; искусственный ответ провайдера в production не внедрялся. Null в pending metadata или execution outcomes не является исполняемым add.

## Дополнительная находка: Schedule admin 500

В отдельной Chrome-вкладке с существующей staff-сессией открыт только собственный тестовый Schedule 134. Страница `/admin/schedules/schedule/134/change/` показала `Server Error (500)`. AIInteraction admin с фильтром по Schedule доступен, через него получен scoped audit выше. Staff-сессия пользователя не менялась и не завершалась.

Локальный отрицательный контроль воспроизвёл ошибку на пустом и непустом inline: `ScheduleInspectionOnly.has_add_permission()` принимал только `request`, а Django `InlineModelAdmin` передаёт также `obj`. Общий mixin используется и для ModelAdmin, и для TimeBlockInline.

Исправление добавляет `obj=None` и по-прежнему возвращает `False`. Запрет add/change/delete не ослаблен. Новые HTTP-тесты реально рендерят обе страницы с inline, проверяют 200, видимость блока при его наличии, отказ POST с 403 и неизменность status/revision/числа блоков. Профильный admin-набор: 9 passed. [Находка и проверка](evidence/post-pr264-2026-10-23/admin-inspection.json).

На момент исходного прогона исправление было локальным. После merge PR #266 production admin перепроверен, результаты находятся в дополнении ниже. Связь возникновения дефекта именно с PR #264 или #265 не установлена.

## Автоматические проверки и cleanup

На исходниках опубликованного `ee8d914` `make check` прошёл: 2357 backend passed, 1 skipped; 1459 frontend passed в 105 файлах. После локального admin-исправления повторный `make check`: 2359 backend passed, 1 skipped; 1459 frontend passed. Ruff и TypeScript прошли в обоих прогонах. Skip относится к прежнему платному opt-in R11 comparison, реальные AI-вызовы этого smoke выполнены отдельно.

`uv run python backend/manage.py check` не обнаружил проблем, `makemigrations --check --dry-run` не нашёл изменений. Миграции для admin-исправления не требуются. [Проверки и hashes](evidence/post-pr264-2026-10-23/checks.json).

Финальный независимый GET подтвердил пустые дни с revisions 8, 8 и 5. Schedule rows, AI-audit и durable receipts сохраняются по контракту; Undo не означает побайтный откат всей базы. API-reader завершил свою сессию, защищённый GET вернул Login и ту же версию релиза. [Финальное состояние](evidence/post-pr264-2026-10-23/final-production-state.json).

Собственные тестовые вкладки закрыты, viewport сброшен, временные API cookie jars удалены. Пользовательские вкладки и исходный приватный файл credentials сохранены. Локальные dev-серверы не перезапускались. В evidence нет cookies, паролей, API keys или restore proofs.

## Ревью PR #266

[Claude Review](https://github.com/erzhan12/day-forge/pull/266#issuecomment-6366398802) одобрил исправление без блокирующих замечаний. Единственная рекомендация P3 выполнена: импорт `reverse` перенесён в общий блок импортов тестового модуля. Профильный admin-набор повторно прошёл все 9 тестов, Ruff прошёл. Перенос импорта не меняет runtime-код исправления.

## Проверка после Deploy PR #266

23 октября 2026 года. [Deploy #39964952164](https://github.com/erzhan12/day-forge/actions/runs/39964952164) опубликовал `2f78696d6ba9cc46b8588161ce873ecf51dd022a`. Validation, build/push, deploy и health-check завершились успешно. Публичная Login и авторизованный API подтвердили ту же версию; JS/CSS доступны. [Deploy](evidence/post-pr266-2026-10-23/deploy.json), [версия и assets](evidence/post-pr266-2026-10-23/release.json).

В отдельной Chrome-вкладке с прежней staff-сессией проверен только собственный тестовый Schedule 134, 10 ноября 2027 года. До записи отдельный неадминистративный HTTPS-клиент подтвердил пустой день, status `active`, revision 8. Это та же карточка, которая ранее показывала 500. [Baseline](evidence/post-pr266-2026-10-23/baseline.json).

| Проверка | Production-результат |
| --- | --- |
| Пустой inline | Страница `View schedule` открылась без 500, таблица Time blocks пуста |
| Непустой inline | Через обычный revision-guarded API тестового аккаунта создан единственный `R266 admin inspection`, 09:00–09:30, ID 1166. После reload admin показал эту строку без 500 |
| Schedule и inline read-only | В обоих состояниях нет доступных полей ввода, submit-кнопок Save, видимого Add another или inline Delete. Внизу доступна только ссылка Close |
| Создание через admin | Прямые GET `/admin/schedules/schedule/add/` и `/admin/schedules/timeblock/add/` показали `403 Forbidden` в staff-сессии |
| Удаление через admin | Прямые GET delete-страниц Schedule 134 и временного TimeBlock 1166 показали `403 Forbidden`; удаление через admin не выполнялось |
| Сохранность состояния | Независимый API GET после admin-проверок подтвердил прежние revision 9, status `active` и единственный неизменённый блок |
| Cleanup | Временный блок убран через штатный restore API с актуальной revision. Итог: пустой день, status `active`, revision 10. Повторный reload admin снова показал пустой inline без 500 |

[Browser observations](evidence/post-pr266-2026-10-23/admin-browser.json), [страницы отказа](evidence/post-pr266-2026-10-23/admin-forbidden-pages.json), [состояние после проверок](evidence/post-pr266-2026-10-23/after-admin-checks.json), [финальное состояние](evidence/post-pr266-2026-10-23/final-state.json). Снимки показывают только дату, статус и inline, без account fields: [пустой](screenshots/post-pr266-2026-10-23/empty-inline.png), [непустой](screenshots/post-pr266-2026-10-23/nonempty-inline.png).

Для непустого inline Django создаёт скрытую ссылку Add another в DOM. Проверено, что она не видна и не доступна как элемент интерфейса; её наличие в разметке не засчитано как разрешение на запись. Невидимые элементы не активировались.

Прямой staff POST в production не отправлялся. Его отказ с 403 и неизменность расписания проверены настоящими HTTP-тестами того же опубликованного кода: локальный admin-набор повторно прошёл 9 тестов, а Deploy выполнил полный набор с 2359 backend passed, 1 skipped и 1459 frontend passed. Проверки production отделены от этой регрессии в [checks.json](evidence/post-pr266-2026-10-23/checks.json).

Staff credentials и cookies не извлекались, staff-сессия пользователя сохранена. Созданная вкладка закрыта. Отдельный API-клиент тестового пользователя выполнил Logout и подтвердил Login на защищённом GET; его приватные scratch-файлы удалены. Исходные credentials сохранены вне репозитория. Новых AI-вызовов, SSH, скачивания production-базы или изменений настроек не было.

Дополнительных runtime-исправлений не потребовалось. Проверка Schedule admin после PR #266 закрыта в указанных границах.

## Что осталось

Для AI-сценариев после PR #264 и Schedule admin после PR #266 открытых исправлений этого прогона не осталось. Настройка gap из PR #265 проверена позднее на production `a2e6133`: 0/10/20 после нового входа, реальный AI и Undo на desktop/mobile прошли. См. [отдельный отчёт](BLOCK_GAP_PRODUCTION_VERIFICATION.md). Настоящий iPhone/Safari, внешние OAuth-интеграции, нагрузка, новый сравнительный корпус R11 и контейнерный rollback в исходные проверки не входили.
