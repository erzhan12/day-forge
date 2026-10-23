# Production после PR #264

23 октября 2026 года, Asia/Almaty. Проверен текущий опубликованный релиз `ee8d914443d8b5f7141201bcca3b304e45989f05`. Он включает merge PR #264 (`560e03f`) и последующий PR #265 с настройкой промежутка между блоками. Ветка отчёта и дополнительного исправления: `codex/post-pr264-production-verification`.

## Результат

[Deploy PR #264](https://github.com/erzhan12/day-forge/actions/runs/39930768640) и [Deploy текущего релиза](https://github.com/erzhan12/day-forge/actions/runs/39947942233) завершились успешно. Проверены validation, build/push, deploy и health-check. Login и авторизованные desktop/mobile страницы загрузили `ee8d914`. JS/CSS вернули 200 с immutable cache policy. [Версия и assets](evidence/post-pr264-2026-10-23/public-release.json), [Deploy #264](evidence/post-pr264-2026-10-23/deploy-pr264.json), [текущий Deploy](evidence/post-pr264-2026-10-23/deploy-current.json).

Все запрошенные AI-сценарии прошли: `after` в названии, уточнение времени, отказ с сохранением разрешения, корректный повтор, частичный план без дублей, replay `request_id`, Undo и Logout. Использован настоящий production-провайдер, без заглушек или подмены браузерных ответов. Scoped AI-audit подтвердил 15 успешных обращений: по пять через desktop, mobile и независимый HTTP-клиент. [Сводка AI-audit](evidence/post-pr264-2026-10-23/ai-audit-summary.json).

Дополнительная административная проверка нашла отдельный 500 при просмотре Schedule. Он воспроизведён и исправлен локально, но исправление ещё не опубликовано. Поэтому результат запрошенных пользовательских сценариев положительный, а административный дефект остаётся открытым для production до следующего Deploy.

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

Это локальное исправление, production admin ещё не перепроверен после публикации. Связь возникновения дефекта именно с PR #264 или #265 не установлена.

## Автоматические проверки и cleanup

На исходниках опубликованного `ee8d914` `make check` прошёл: 2357 backend passed, 1 skipped; 1459 frontend passed в 105 файлах. После локального admin-исправления повторный `make check`: 2359 backend passed, 1 skipped; 1459 frontend passed. Ruff и TypeScript прошли в обоих прогонах. Skip относится к прежнему платному opt-in R11 comparison, реальные AI-вызовы этого smoke выполнены отдельно.

`uv run python backend/manage.py check` не обнаружил проблем, `makemigrations --check --dry-run` не нашёл изменений. Миграции для admin-исправления не требуются. [Проверки и hashes](evidence/post-pr264-2026-10-23/checks.json).

Финальный независимый GET подтвердил пустые дни с revisions 8, 8 и 5. Schedule rows, AI-audit и durable receipts сохраняются по контракту; Undo не означает побайтный откат всей базы. API-reader завершил свою сессию, защищённый GET вернул Login и ту же версию релиза. [Финальное состояние](evidence/post-pr264-2026-10-23/final-production-state.json).

Собственные тестовые вкладки закрыты, viewport сброшен, временные API cookie jars удалены. Пользовательские вкладки и исходный приватный файл credentials сохранены. Локальные dev-серверы не перезапускались. В evidence нет cookies, паролей, API keys или restore proofs.

## Что осталось

Опубликовать admin-исправление и повторить read-only просмотр Schedule с пустым и непустым inline. Для AI-сценариев, запрошенных после PR #264, новых исправлений не потребовалось. Настоящий iPhone/Safari, новые настройки gap из PR #265, внешние OAuth-интеграции, нагрузка, новый сравнительный корпус R11 и контейнерный rollback в этот smoke не входили.
