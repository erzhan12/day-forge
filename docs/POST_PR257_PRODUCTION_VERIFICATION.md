# Production smoke после PR #257

22 октября 2026 года, Asia/Almaty. Браузерные измерения сохранены с 11:01 до 11:06; вход и финальные независимые чтения выполнены вокруг этого интервала. Проверен опубликованный релиз `2d607b70abbd10a4039a444f5b6031212f0b9ab7` на [dayforge.habitreward.org](https://dayforge.habitreward.org).

## Результат

Свежий вход, реальные AI-chat и draft, кнопка Undo и Logout прошли на desktop и mobile. Каждая AI-запись и её отмена подтверждены отдельным авторизованным HTTPS-клиентом. Ошибок приложения не обнаружено; runtime-код не менялся.

Выполнены четыре успешные AI-операции через UI: два chat и два draft. Подмены SDK, перехвата HTTP и заглушек не было. Внутренние retries провайдера отдельно не считались; provider/model из production-конфигурации не извлекались.

Три тестовых дня оставлены пустыми. Временный шаблон удалён, список шаблонов снова пустой; правила и окно 06:00–23:00 UTC сохранены. Тестовые браузерные сессии завершены Logout, созданная вкладка закрыта, viewport сброшен.

## Опубликованная сборка

[Deploy #39728917859](https://github.com/erzhan12/day-forge/actions/runs/39728917859) прошёл успешно. Публичная Login вернула HTTP 200 и полный SHA `2d607b7…`. Этот же SHA прочитан из DOM авторизованных страниц и ответов независимого HTTPS-клиента. TLS проверялся с доверенным CA bundle, без отключения проверки сертификатов.

| Asset | SHA-256 |
| --- | --- |
| `/static/assets/app-BIArPliO.css` | `2a558214d7e0fc47a8d2b3a630003b22c8cdd739277af13449514c149703887b` |
| `/static/assets/app-exCm7APL.js` | `513aca2660c267ce9ab6d9ade36cdec2131cf805aad9aa7067dda234fa4e9650` |

Оба файла вернули HTTP 200 и `Cache-Control: max-age=315360000, public, immutable`. Авторизованный браузер загрузил именно эти пути. В опубликованном CSS проверено правило `.draft-error[data-v-b3efb8fc]` с `overflow-wrap:anywhere`; отдельное media-правило меняет только max-width.

## Аккаунт и подготовка

Использован ранее созданный отдельный production-аккаунт без административных прав, user ID 2. Его создание и отсутствие подключённых интеграций описаны в [первом production smoke](PRODUCTION_ACCOUNT_SMOKE_2026-10-20.md). Credentials прочитаны из существующего приватного файла вне репозитория. Пароль не менялся; credentials, cookies, CSRF и restore proofs в отчёт и evidence не включены.

До записи независимый клиент подтвердил пустые дни 26 и 27 октября с revision 0, пустые списки шаблонов и правил. Создан временный weekday-шаблон `PR 257 temporary smoke` с единственным Work-блоком `Release 257 draft`, 10:00–10:30. День 28 октября также предварительно прочитан пустым с revision 0.

Первое чтение 28 октября вернуло `auto_draft_pending=true` в независимом HTTP-клиенте, который не выполняет frontend JavaScript. При последующем открытии дня браузер показал кнопку Regenerate draft. Все четыре AI-операции ниже запущены явным действием через UI.

## Проверенные сценарии

CUA управляла встроенным Chromium. Desktop viewport измерен как 1440×900, mobile как 390×844 и 320×740. Это проверка мобильной ширины Chromium, не настоящего iOS Safari.

| Сценарий | Результат |
| --- | --- |
| Свежий desktop-вход | Анонимная Login, ввод credentials, открытие Schedule; SHA совпадает с Deploy |
| Desktop chat, 26 октября | Реальный запрос создал один Work-блок `Release 257 desktop chat`, 14:00–14:30; независимый GET подтвердил revision 1, статус active |
| Desktop chat Undo | Видимая кнопка Undo вернула пустой день с revision 2, статус active; Undo выключен |
| Desktop draft, 28 октября | Regenerate draft создал единственный шаблонный блок 10:00–10:30; независимый GET подтвердил revision 1, статус draft |
| Desktop draft Undo | Независимый GET подтвердил пустой день с revision 2, статус draft |
| Desktop Logout | Login после выхода; Back показал Login, reload защищённого URL перенаправил на Login с `next` |
| Свежий mobile-вход, 390 px | Ввод credentials после desktop Logout, новый Schedule с SHA `2d607b7…` |
| Mobile draft, 27 октября, 390 px | Реальная генерация создала шаблонный блок 10:00–10:30; revision 1, статус draft. Undo вернул пустой день с revision 2 |
| Mobile chat, 27 октября | Реальный запрос при 390 px создал один Work-блок `Release 257 mobile chat`, 15:00–15:30; revision 3, статус active. Результат и layout дополнительно проверены при 320 px |
| Mobile chat Undo, 320 px | Кнопка Undo вернула пустой день с revision 4; результат подтверждён независимым GET |
| Mobile Logout, 320 px | Logout доступен после прокрутки до footer. Выход, Back и reload показали Login |
| Повторный вход и Logout, 390 px | Новый вход и свежий GET 27 октября подтвердили пустой день, revision 4 и отсутствие временного шаблона. Logout, Back и reload снова показали Login |

После chat статус дня становится active. Undo возвращает блоки, но сохраняет active; кнопка Regenerate draft по действующему контракту доступна только на пустом draft-дне. Поэтому desktop draft проверен на отдельном 28 октября. На mobile draft проверен перед chat того же дня. Это не ошибка восстановления данных.

## Реальные AI-запросы

Desktop chat:

```text
Add a Work block titled "Release 257 desktop chat" from 14:00 to 14:30 on this schedule. Keep all other blocks unchanged.
```

Ответ: `Added the requested Work block from 14:00 to 14:30.`

Mobile chat:

```text
Add a Work block titled "Release 257 mobile chat" from 15:00 to 15:30 on this schedule. Keep all other blocks unchanged.
```

Ответ: `Added the requested Work block from 15:00 to 15:30.`

Оба draft использовали временный шаблон через обычную кнопку Regenerate draft. Desktop explanation: `Follows the weekday template exactly.` Mobile explanation: `Followed weekday template exactly; no history or rules to adjust.` Серверные snapshots подтвердили название, category, интервал и единственный блок каждой генерации.

## Layout и доступность Logout

Горизонтального переполнения в 19 DOM-измерениях нет: document scrollWidth не превышает innerWidth. На Schedule при 390 px ширина документа 375 px, при 320 px она 305 px из-за вертикальной полосы прокрутки.

На 390 px после AI-chat центр Logout попадал в кнопку: x=293,625, y=437,5, width=65,375, height=28. На 320 px высокая переписка перекрывала footer в исходной позиции прокрутки. После обычной прокрутки до footer кнопка оказалась над dock, и `elementFromPoint` подтвердил попадание в неё. Перед Logout после Undo: x=223,625, y=402, width=65,375, height=28. Клик завершил сессию. Дополнительного исправления отступов не потребовалось.

Проверка намеренно не добивалась ошибочного ответа модели вне рабочего окна на production. Перенос длинного сообщения и атомарный отказ уже воспроизведены в [браузерной проверке PR #257](AI_WINDOW_DURATION_FIXES.md#дополнение-22-октября-браузерная-проверка-ai-draft-после-pr-256); здесь подтверждены опубликованный CSS и успешные реальные AI-пути.

## Проверки и итоговое состояние

Validation опубликованного commit в Deploy прошла: Ruff, **2150 backend passed, 1 skipped**, Vue type-check, **1410 frontend passed в 104 файлах**, production build и production dependency audit с 0 vulnerabilities. Пропущен отдельный платный opt-in comparison. Новых изменений runtime или тестов в этом прогоне нет.

Финальные независимые чтения после удаления временного шаблона:

| Дата | Блоки | Revision | Статус |
| --- | --- | --- | --- |
| 26 октября | 0 | 2 | active |
| 27 октября | 0 | 4 | active |
| 28 октября | 0 | 2 | draft |

Списки templates/rules совпадают с исходными, окно дня сохранено. Account, Schedule rows, revision, durable receipts и AI audit остаются согласно контракту. Возврат к пустому расписанию не является побайтным rollback базы. Независимый клиент завершал каждую свою сессию через POST Logout; браузерные границы проверены отдельно через Back и reload.

Машиночитаемое evidence: [POST_PR257_PRODUCTION_VERIFICATION.json](evidence/POST_PR257_PRODUCTION_VERIFICATION.json). Содержит 19 DOM-измерений, 12 серверных snapshots, две исходные пустые даты, hashes assets и девяти оригинальных JPEG. Это журнал наблюдений, не HAR и не непрерывная запись экрана. Размер JPEG может отличаться от CSS viewport; размеры viewport измерены из DOM. Байты снимков не изменялись.

Снимки: [desktop chat](screenshots/post-pr257-2026-10-22/desktop-chat-applied.jpg), [desktop draft](screenshots/post-pr257-2026-10-22/desktop-draft-applied.jpg), [desktop Logout](screenshots/post-pr257-2026-10-22/desktop-logged-out.jpg), [mobile draft](screenshots/post-pr257-2026-10-22/mobile-draft-applied.jpg), [mobile chat 390](screenshots/post-pr257-2026-10-22/mobile-chat-applied-390.jpg), [mobile 320 до прокрутки](screenshots/post-pr257-2026-10-22/mobile-chat-applied-320.jpg), [mobile 320 footer](screenshots/post-pr257-2026-10-22/mobile-chat-320-footer.jpg), [Logout 320](screenshots/post-pr257-2026-10-22/mobile-logged-out-320.jpg), [Logout 390](screenshots/post-pr257-2026-10-22/mobile-logged-out-390.jpg).

Отдельными задачами остаются реальный iOS Safari, server-owned pending intent, живые OAuth-интеграции и нагрузочные границы. Этот smoke проверяет конкретные сценарии опубликованного релиза, а не качество модели на корпусе или отказоустойчивость инфраструктуры.
