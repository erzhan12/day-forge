# Production после PR #263

23 октября 2026 года, Asia/Almaty. Проверен опубликованный релиз `407620494de979f2e577808b944e25d8dbe1de4f`. Новые исправления находятся в ветке `codex/post-pr263-production-verification` и пока не опубликованы.

## Результат

[Deploy #39923902893](https://github.com/erzhan12/day-forge/actions/runs/39923902893) прошёл validation, build/push, deploy и health-check. Login и авторизованные страницы desktop/mobile загрузили `4076204`; JS/CSS вернули 200 и immutable cache policy. [Метаданные сборки](evidence/post-pr263-2026-10-23/public-release.json), [Deploy](evidence/post-pr263-2026-10-23/deploy.json).

Уточнение начала и частичный план без дублей прошли в production на desktop и mobile. Undo, физическое нажатие Logout и защищённая история также прошли. Повтор после отказа выявил два дополнительных случая: relation word внутри quoted title и перенос пустого `task_id` из pending metadata в исполняемый add. Поэтому полный production smoke не считается зелёным. Оба случая исправлены локально; результаты кандидата отделены ниже.

## Production: сценарии и данные

Использован прежний неадминистративный тестовый аккаунт, user ID 2. Credentials остались вне репозитория. До записи независимый HTTPS-клиент подтвердил пустые даты 1, 2 и 3 ноября 2027 года с revision 0. Пароль, настройки и интеграции не менялись. Production-база не скачивалась, SSH не использовался.

| Сценарий | Desktop 1440×900 | Mobile 390×844 |
| --- | --- | --- |
| Свежий вход и версия | Password login; SHA `4076204` | Повторён свежий login при измеренной ширине 390; тот же SHA |
| Только время начала | Вопрос без записи; `14:00` создал 14:00–14:30 | Вопрос без записи; `16:00` создал 16:00–16:30 |
| Undo добавления | День вернулся к пустому | День вернулся к пустому; GET подтвердил revision 2 |
| Частичный план | Сначала один accepted 13:00–13:30 и сохранённый вопрос; ответ `15:00 to 15:30` добавил только unresolved | Та же последовательность и ровно два разных блока |
| Undo частичного плана | Первая убрала unresolved, вторая accepted | Обе части отменены отдельно |
| Ответ до anchor | `08:00` отклонён из-за невалидного SDK-ответа, без записи | Настоящий relative guard отклонил `08:00` до anchor 09:00–09:30; предыдущая Undo сохранилась |
| Корректный повтор | `10:00` зациклился из-за `after` в quoted title | `10:00` получил 502 из-за `task_id: null`; повтор `10:00 to 10:30` применился один раз |
| Undo после успешного повтора | Уточнение отменено кнопкой Cancel; собственный anchor удалён | При 320×740 Undo вернула только anchor; затем собственный anchor удалён |
| Logout и история | После прокрутки hit-test центра кнопки положителен; физическое нажатие, Back и reload показали Login | То же при 320 px с открытым чатом. clientWidth и scrollWidth равны 305, innerWidth 320; горизонтального переполнения нет |

Действия с интерфейсом выполнены через CUA. Отдельный HTTPS-клиент подтвердил состояния после основных записей и отмен. Он не подменял браузерный транспорт. Login открывает сегодняшний день; перед тестовыми записями выполнялась явная навигация на проверенную будущую дату.

После 502 старый Undo консервативно инвалидируется. Поэтому desktop anchor удалён через штатный DOM dialog после Cancel. На mobile новая успешная AI-запись создала собственную Undo: она вернула anchor, который затем удалён тем же способом. Удалялись только созданные в этом прогоне блоки. После guard-only отказа без 502 существующая Undo оставалась доступной.

Итоговый независимый GET подтвердил все три даты пустыми: revisions 8, 10 и 4. Schedule rows, audit, receipts и intents сохраняются согласно контракту; очистка блоков не является побайтным откатом базы. Открытое HTTP-намерение закрыто явной отменой без AI. API logout и защищённый GET показали Login. [Финальное состояние](evidence/post-pr263-2026-10-23/final-production-state.json).

## Durable request_id

На третьей дате отдельный HTTPS-клиент проверил:

- Точное тело и UUID вопроса, успешного ответа и Cancel возвращают прежние JSON bytes.
- Replay после Undo возвращает старый receipt, но не восстанавливает удалённый блок и не меняет текущую revision.
- Изменённое тело с прежним UUID возвращает `409 request_id_conflict`.
- Новый UUID со ссылкой на закрытый intent возвращает `409 pending_intent_stale`.
- Replay частичного применения не создаёт второй accepted block.
- Продолжение partial на `15:00 to 15:30` получило 502 из-за null-target в add. Этот этап не засчитан как успешный; исходный accepted убран при cleanup.
- Повтор именно этого завершённого 502 после cleanup вернул побайтно тот же terminal response, без записи.

[HTTP evidence](evidence/post-pr263-2026-10-23/http-smoke.json) сохраняет `success: false`. [Финальный probe](evidence/post-pr263-2026-10-23/final-production-state.json) отдельно фиксирует точный replay ошибки. Cookies и restore proofs не публикуются. Потеря соединения и конкурентная нагрузка в production не инжектировались.

## Найденные ошибки

### Relation word внутри названия

Команда `Add a Work block titled "R263 desktop after anchor" after "R263 desktop anchor"` содержит одно условие размещения. Старый guard считал также `after` внутри названия и задавал общий вопрос даже после корректного `10:00`. Audit подтвердил, что модель вернула валидный add 10:00–10:30; запись заблокировал сервер. [Исходный ответ](evidence/post-pr263-2026-10-23/quoted-title-correction-audit.json).

Разбор теперь исключает relation words только внутри кавычек с точными известными названиями добавляемых или существующих блоков. Проверены обычные двойные и одинарные кавычки, типографские “…” и «…». Настоящее внешнее ограничение остаётся. Кавычки вокруг всей команды не скрывают его. Отрицательный контроль на исходном коде `4076204` воспроизводит ложный вопрос при валидном времени; исправленный код принимает его и продолжает отклонять время до Gym. [Контроль](evidence/post-pr263-2026-10-23/quoted-title-negative-control.json).

### Пустой target pending metadata в исполняемом add

В desktop-ответе `08:00` и HTTP-продолжении partial модель вернула `actions: [{type: "add", task_id: null, ...}]`. Строгий валидатор отклонил лишнее поле. Prompt говорил «An add has task_id=null» в разделе pending metadata, не называя формат достаточно явно. [Desktop audit](evidence/post-pr263-2026-10-23/rejected-model-audit.json), [HTTP audit](evidence/post-pr263-2026-10-23/http-provider-failure-audit.json).

Prompt теперь различает pending add proposal и executable add. На границе SDK чата удаляется только `task_id: null` у `add`; исходный JSON сохраняется для audit. Ненулевые IDs, null-target у move/resize/remove/update и другие неизвестные поля остаются ошибками. Общий валидатор и draft-формат не ослаблены. Права на продолжение, ownership, locked fields, accepted IDs и проверка реального anchor остаются прежними.

## Исправленный кандидат

Кандидат запущен на отдельной синтетической SQLite базе с настоящим OpenRouter, без заглушек провайдера. Браузер использует `127.0.0.1:8012` и отдельное имя session cookie; production credentials и данные в локальную базу не переносились. Fixture содержит Gym 09:00–09:30 и Focus 10:00–11:00. Корректные ответы выбирались после обоих блоков.

Desktop: quoted-title запрос, отказ на `08:00`, исправленный `14:00`, одно добавление 14:00–14:30 и Undo обратно к Gym/Focus прошли. Отдельный HTTP-прогон с реальным AI прошёл уточнение начала, exact replay, изменённое тело, replay после Undo, Cancel, partial completion без дубля и его replay после Undo. [Candidate HTTP](evidence/post-pr263-2026-10-23/candidate-http-smoke.json): `success: true`. Это локальный кандидат, а не повторная публикация production.

Mobile 320×740: запрос с названием `R263 mobile after anchor`, отказ на `08:00` и ответ `15:00` создали ровно один блок 15:00–15:30. Gym и Focus не изменились. Undo вернула исходные два блока. Logout, Back и reload защищённого адреса показали Login. При открытом чате scrollWidth равен clientWidth 305 px; горизонтального переполнения нет. [Desktop после исправления](screenshots/post-pr263-2026-10-23/candidate-desktop-corrected-applied.jpg), [mobile после исправления](screenshots/post-pr263-2026-10-23/candidate-mobile-corrected-applied.jpg).

Всего выполнены 11 успешных реальных AI-вызовов: по три в desktop/mobile браузере и пять через отдельный HTTP-клиент. Точные replay и Cancel не требуют новых вызовов модели. Read-only экспорт локальной SQLite подтвердил закрытие всех намерений, возврат браузерных дат к Gym/Focus, пустую HTTP-дату и отсутствие активных сессий после Logout. [Локальный audit, receipts и финальные состояния](evidence/post-pr263-2026-10-23/local-real-ai.json). [Наблюдения браузера](evidence/post-pr263-2026-10-23/browser-observations.json) содержат URL и версию каждого шага, чтобы различать production и локальный кандидат.

После проверки отдельный сервер остановлен, удалены только его Redis keys и временные API cookie jars. Созданные для проверки вкладки закрыты, viewport сброшен. Пользовательские серверы и вкладки сохранены. [Cleanup](evidence/post-pr263-2026-10-23/local-cleanup.json).

## Автоматические проверки и границы

`make check`: 2277 backend passed, 1 skipped; 1422 frontend passed в 104 файлах. Ruff и TypeScript прошли. Профильный набор service/pending/relative-guard: 209 passed. Единственный skip относится к прежнему платному opt-in R11 comparison; живые запросы этого smoke выполнены отдельно.

Новые тесты покрывают quoted names, quoted whole command, настоящий anchor, сохранность scope после отказа и после malformed provider reply, точный replay и неизменность соседей. Для null-target проверены raw audit, ненулевые IDs, остальные action types и неизвестные поля.

Команды для повторения автоматических проверок:

```sh
make check
uv run pytest backend/tests/test_ai_service_chat.py backend/tests/test_ai_pending_intents.py backend/tests/test_ai_relative_add_guard.py -q
uv run python backend/manage.py check
uv run python backend/manage.py makemigrations --check --dry-run
git diff --check
```

Django system check прошёл; изменений моделей нет, миграции не требуются. [Количество тестов и SHA-256 проверенных исходников](evidence/post-pr263-2026-10-23/checks.json). Изменены только backend chat prompt, нормализация ответа и разбор относительных условий, их тесты и документация. Контейнерная репетиция в этом прогоне не повторялась; предыдущая репетиция PR #263 описана в [отчёте после PR #262](POST_PR262_RELEASE_VERIFICATION.md).

Физический iPhone/Safari, внешние OAuth-интеграции, нагрузочная оценка и новый сравнительный корпус R11 не проверялись. Mobile здесь означает измеренные browser viewports 390 и 320 px. После merge и Deploy новых исправлений нужно повторить quoted-title continuation и add с null-target на тестовом production-аккаунте.
