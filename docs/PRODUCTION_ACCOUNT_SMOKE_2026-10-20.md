# Production smoke на отдельном тестовом аккаунте

20 октября 2026 года, 16:44–16:48 по Asia/Almaty. Проверен опубликованный релиз `b8b133f750b822c9873d502a41ff25fab7fc50d5` после PR #250 на [dayforge.habitreward.org](https://dayforge.habitreward.org).

## Результат

Свежий вход с паролем, создание и переименование блока, Undo, подтверждение и отмена удаления, восстановление удалённого блока, навигация, реальный AI-запрос и Logout прошли на production. Записи и отмена проверены повторными серверными чтениями. Ошибок приложения не обнаружено, runtime-код не менялся.

Пункт **Production credential login and write smoke** закрыт. Этот прогон дополняет [проверку после PR #246](POST_PR246_RELEASE_PIP_VERIFICATION.md), где production проверялся через существующую пользовательскую сессию, а mutations выполнялись только на локальном стенде.

## Релиз и окружение

[Deploy #39265904184](https://github.com/erzhan12/day-forge/actions/runs/39265904184) прошёл успешно. Публичная Login вернула HTTP 200 с SHA `b8b133f…`; этот же SHA получен из HTML авторизованного Schedule. TLS проверялся штатно.

| Asset | SHA-256 |
| --- | --- |
| `/static/assets/app-ckrUuoMy.js` | `814b73f65045f52fd89c880364a48c85aeb8adac073ca452f28e624149779c62` |
| `/static/assets/app-COtgMyyv.css` | `d26f2305d3ef0accf5da103ac28ff78b6b40e68e7d401f75df97d1ebf341e85b` |

Оба файла вернули HTTP 200 и `Cache-Control: max-age=315360000, public, immutable`.

Браузерные действия выполнены через CUA во встроенном браузере. Проверены фактические viewport 1440×900 и 390×844. Это мобильная ширина Chromium, не настоящий iOS Safari. Дополнительная вкладка использовалась для свежего серверного чтения без сброса Undo в основной вкладке.

## Тестовый пользователь и границы записи

Через существующую Django admin-сессию Chrome создан `release-smoke-20261020` (user ID 2). У пользователя нет staff/superuser-прав, групп или подключённых Apple Calendar, Google Calendar, Todoist и Habitica. Отсутствие интеграций проверено в Settings и серверном bootstrap. Шаблоны не создавались, поэтому автоматическая генерация draft не запускалась.

Для аккаунта сгенерирован случайный пароль. Credentials сохранены в `~/.codex/private/day-forge/production-smoke-20261020.json` с правами `0600` вне репозитория; пароль, cookies, CSRF-токены и подписанные restore proofs в отчёт и evidence не включены. Встроенный браузер открыл анонимную Login отдельно от Chrome admin-сессии. Исходная Chrome-сессия и пользовательские вкладки сохранены.

Все изменения расписания относятся только к новому аккаунту и датам 20–21 октября 2026 года. Прямого доступа к production-базе, SSH-команд, миграций, скачивания базы и правок чужих расписаний не было.

## Проверенные сценарии

| Сценарий | Действия и результат |
| --- | --- |
| Свежий вход | Login первоначально анонимна. Введены credentials нового пользователя, открылся Schedule. После reload сессия сохранилась |
| Создание | На пустом 21 октября создан `Release smoke test`, Work, 14:00–14:30. После reload сервер вернул один блок с этими полями, revision 1 |
| Переименование и Undo | Название изменено на `Release smoke test edited`, затем нажата видимая кнопка Undo. После reload вернулись исходное название и интервал |
| Cancel удаления | В DOM-диалоге нажата Cancel. Блок остался на месте |
| Удаление и Undo | Подтверждение Delete убрало блок. Undo восстановил его; после reload остался один блок с исходными полями |
| Settings и история | Открыты Settings и Integrations. Back вернул нужную дату с блоком, Forward открыл Settings, повторный Back снова вернул расписание |
| Реальный AI на mobile | На пустом 20 октября отправлен один запрос на создание Work-блока `Release AI smoke`, 15:00–15:30. AI применил именно этот блок |
| Сохранение AI-записи | Отдельная вкладка получила серверный Schedule с одним блоком, category `work`, интервал 15:00–15:30, revision 1 |
| AI Undo на mobile | Нажата кнопка Undo. Reload отдельной вкладки вернул пустой `blocks`, revision 2 |
| Analytics | Переход View analytics открыл текущую аналитику 20 октября: пустой день, 0 минут по категориям. Mark reviewed и Notes не изменялись |
| Очистка | Ручной блок 21 октября удалён через обычный диалог. Reload подтвердил пустой день, revision 6. Позднейший свежий desktop-вход снова подтвердил отсутствие блоков |
| Logout на mobile | Кнопка доступна и не перекрыта чатом. После Logout появилась Login. Back, reload и прямой Schedule потребовали вход; reload второй вкладки тоже получил Login |
| Свежий desktop-вход и Logout | При измеренных 1440×900 выполнены новый вход, reload и проверка пустого дня. Logout, Back, reload и прямой Analytics снова показали Login |

На мобильном экране при открытом AI-чате центр кнопки Logout попадал в саму кнопку по `elementFromPoint`. Её прямоугольник: x=293,625, y=470,5, width=65,375, height=28. `scrollWidth` документа 375 px при `innerWidth` 390 px: горизонтального переполнения не было.

## Реальный AI-запрос

Отправлен один turn без заглушек, перехвата запросов и подмены ответа:

```text
Add a Work block titled "Release AI smoke" from 15:00 to 15:30 on this schedule. Keep all other blocks unchanged.
```

Ответ:

```text
Added the requested Work block from 15:00 to 15:30.
```

Production admin показала одну AIInteraction для тестового schedule ID 118: запись ID 853, kind `Chat`, success `True`, одно действие `add`, outcome `applied`. Сохранённый raw response содержит ожидаемые title/category/start/end, `ask: null`. Свежий GET подтвердил блок ID 1067; после Undo свежий GET подтвердил отсутствие блоков. Audit log сам по себе не использовался как доказательство сохранения расписания.

Это проверка доступности production AI и применения одного запроса. Она не измеряет качество модели, стоимость или поведение при потерянном HTTP-ответе. Точный provider/model в этом прогоне не извлекался из production-конфигурации.

## Проверки кода

`make check` прошёл на исходниках опубликованного `b8b133f…`:

- Ruff: без замечаний.
- Backend: **2118 passed, 1 skipped**, 16,99 с. Пропущенный тест требует отдельного opt-in платного AI-прогона; реальный production-запрос выше выполнен отдельно.
- Frontend type-check: прошёл.
- Frontend: **1395 passed, 103 файла**, 10,46 с.

Новых runtime-изменений нет. Повторная локальная production-сборка и платный R11 live comparison не запускались. Build/deploy CI опубликованного релиза прошёл.

## Evidence и итоговое состояние

Машиночитаемые результаты: [PRODUCTION_ACCOUNT_SMOKE_2026-10-20.json](evidence/PRODUCTION_ACCOUNT_SMOKE_2026-10-20.json). Это журнал наблюдений CUA и прочитанных серверных snapshots, не HAR и не непрерывная запись экрана. Метки времени в JSON указаны в UTC. Размеры viewport измерены через DOM; размер нативного JPEG-снимка может отличаться от viewport, в частности из-за полос прокрутки. Байты снимков сохранены без обработки.

| Снимок | Что показывает |
| --- | --- |
| [Созданный блок на desktop](screenshots/production-smoke-2026-10-20/desktop-created.jpg) | Ручной блок после reload |
| [Реальный AI на mobile](screenshots/production-smoke-2026-10-20/mobile-ai-created.jpg) | Запрос, ответ, блок 15:00–15:30 и доступную Logout |
| [Analytics после Undo](screenshots/production-smoke-2026-10-20/mobile-analytics-empty.jpg) | Пустую аналитику тестового пользователя |
| [Очистка на mobile](screenshots/production-smoke-2026-10-20/mobile-cleanup.jpg) | Отсутствие ручного блока после удаления и reload |
| [Очистка на desktop](screenshots/production-smoke-2026-10-20/desktop-cleanup.jpg) | Пустой день после нового входа |
| [Logout на desktop](screenshots/production-smoke-2026-10-20/desktop-logged-out.jpg) | Login после прямого открытия защищённой Analytics |

Тестовый аккаунт оставлен для следующих проверок. В обоих днях нет блоков. Строки Schedule, их revision/status и AI audit history сохранены: возврат содержимого к пустому состоянию не означает побайтный rollback базы. Тестовые сессии завершены обычным Logout. Созданные вкладки закрыты, временный viewport сброшен, временная копия credentials удалена после сохранения приватного файла.

Остаются отдельные проверки настоящего iOS Safari, живых OAuth/reconnect/completion интеграций и нагрузочных границ. Server-owned pending intent и durable AI request identity остаются задачами проектирования и реализации, этот успешный smoke их не закрывает.
