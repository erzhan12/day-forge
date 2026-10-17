# Браузерная проверка desktop и mobile

Проверка выполнена 17 октября 2026 года во встроенном браузере Codex через CUA. Запрошенные сценарии прошли на desktop 1440×900 и мобильной ширине 390×844. Дополнительно проверены форма, навигация и Logout при 320×740. Фактические размеры подтверждены через `window.innerWidth` и `window.innerHeight`.

Исправлены три ошибки: отсутствие доступной кнопки Undo на телефоне, показ сохранённого расписания через Back после Logout и переполнение ручной формы при 320 px. Отчёт закрывает основные сценарии и R11 mobile smoke. Специальные случаи A00–A07 с управляемыми гонками и внешними аккаунтами остаются отдельно в [todo](../tasks/todo.md).

## Окружение и тестовые данные

- Локальный сайт: `http://localhost:5173`, Django на порту 8006.
- Отдельный пользователь `browser-smoke-20261017`, без staff/superuser и подключённых внешних аккаунтов. Все изменения относятся к его синтетическим данным.
- Desktop: 19–21 апреля 2027 года. Mobile: 26–28 апреля 2027 года. Для review подготовлены 15 и 16 октября 2026 года.
- Один weekday-шаблон: `Smoke preparation` 09:00–09:25, `Smoke focus` 10:00–10:30, `Smoke lunch` 12:00–12:30. Часовой пояс UTC.
- Настроенный chat: OpenRouter, `x-ai/grok-4.3`. Настроенный draft: OpenRouter, `gpt-4o`. Запросы выполнялись через обычный backend без подмены ответов.

Первый chat-запрос получил валидный ответ модели, но применение закончилось HTTP 500. Работавший с 11 октября процесс Django был запущен с `--noreload`, а его файл лога уже отсутствовал. После перезапуска на текущем коде ошибка больше не воспроизводилась. Точный traceback старого процесса восстановить не удалось, поэтому это не считается доказанным дефектом текущей ветки.

Всего сохранено восемь ответов AI: шесть chat и два draft. Семь запросов завершились успешно после перезапуска; восьмой относится к первоначальному HTTP 500. Валютная стоимость в обычном приложении не записывается, поэтому здесь она не оценивается. Числа из отдельного R11 сравнения к этому прогону не относятся.

[Снимок проверенных данных и AI-аудита](evaluations/browser-smoke-2026-10-17.json) содержит только тестового пользователя: команды, ответы, действия, outcomes, итоговые расписания и review. Входные пароли и API-ключи в артефакт не включены.

## Найденные ошибки и исправления

### Undo был доступен только с клавиатуры

Все основные изменения регистрировали Undo с `silent: true`. История существовала, но toast с кнопкой не показывался. На desktop работал ⌘Z/Ctrl+Z, а в мобильном интерфейсе способа отменить действие не было. До исправления при 390 px DOM содержал ноль кнопок Undo после изменения расписания.

[Контроллер страницы](../frontend/src/composables/useSchedulePageController.ts) теперь отдаёт существующий `canUndo`, а [панель дня](../frontend/src/pages/Schedule.vue) показывает постоянную кнопку. Она отключена при пустой истории текущего дня и во время мутаций. Политика тихих уведомлений сохранена. Проверены отмена AI-добавления, удаления, переноса после уточнения и целого draft. Цепочка «AI-добавление → удаление → Undo удаления → Undo добавления» вернула пустой день.

Добавлены проверки кнопки и блокировки во время незавершённой записи в [Schedule.test.ts](../frontend/tests/Schedule.test.ts); связь с реальным Undo контроллера проверяется в [useSchedulePageController.test.ts](../frontend/tests/useSchedulePageController.test.ts).

### Back показывал расписание после Logout

Logout закрывал серверную сессию и очищал composables, но Back возвращал страницу из истории Inertia. Прямой запрос к защищённому URL уже перенаправлял на Login. Ошибка была в восстановлении клиентского снимка.

В [настройках](../backend/day_forge/settings.py) включён `INERTIA_ENCRYPT_HISTORY`. Общий [рендер Login](../backend/schedules/views.py) вызывает `clear_history`, поэтому предыдущий ключ истории удаляется и старые приватные записи требуют повторного обращения к серверу. Это штатный механизм [Inertia history encryption](https://inertiajs.com/history-encryption), поддерживаемый установленными клиентом и Django adapter.

На обеих ширинах проверен Logout с последующим Back: видна форма входа, кнопки Logout и старого блока нет. Мобильный адрес после проверки: `/accounts/login/?next=/schedule/2026-10-16/`; desktop: `/accounts/login/?next=/schedule/2026-10-15/`. В консоли предупреждений и ошибок не было.

Проверка после исправления выполнена в новой вкладке. Шифрование применяется к новым записям истории; уже сохранённые старой версией plaintext-записи невозможно зашифровать задним числом. В [backend-тестах](../backend/tests/test_inertia_identity.py) закреплены флаги для Schedule, Settings, Analytics, Logout и Login после истечения сессии.

### Форма выходила за край при 320 px

В [AddBlockForm.vue](../frontend/src/components/AddBlockForm.vue) поля Start, End и Category стояли в одной непереносимой строке. При ширине viewport 320 px `scrollWidth` достигал 336 px, а правый край Category был около 336.4 px.

Строка теперь переносится, labels имеют гибкую ширину, а поля занимают доступное место. При повторной проверке `scrollWidth` равен 320 px; правые края Start и End находятся на 154 и 288 px, Category переносится ниже и также заканчивается на 288 px. Через исправленную форму создан блок `Mobile manual` 09:00–09:30. При 390 px форма тоже помещается.

## Пройденные сценарии

| Сценарий | Desktop | Mobile |
| --- | --- | --- |
| Вход отдельным тестовым пользователем | Пройден | Пройден |
| Реальный chat создаёт блок с заданным временем и категорией | `Desktop AI focus`, затем `Desktop live AI` | `Mobile AI фокус` 10:00–10:30, work |
| Реальный диалог с уточнением | Одноходовое добавление | `Move Mobile manual.` → вопрос времени → `11:00`; перенесён существующий блок, дубликата нет |
| Keyboard Undo | ⌘Z удалил AI-добавление | Для мобильной проверки использовалась кнопка |
| Кнопка Undo после AI-добавления | Пройден | Пройден |
| Cancel в подтверждении удаления | Блок остался | Блок остался |
| Delete и Undo удаления | Блок восстановлен | Блок восстановлен; проверена цепочка с отменой AI-добавления |
| Ручное создание блока | 09:00–09:30 | 09:00–09:30, включая 320 px |
| Реальная генерация draft по шаблону | Три блока, статус draft | Три блока, статус draft |
| Undo всего draft | День пуст; draft не запускается заново | День пуст; draft не запускается заново |
| Переход на соседний день | Чужих блоков/диалога нет; Undo отключён | То же |
| Back/Forward до Logout | Восстанавливается нужный день | То же, включая зашифрованную историю |
| Review и заметки | Reviewed summary, 1/1, заметка сохранена | То же, без горизонтального скролла |
| Logout | Переводит на Login | Переводит на Login |
| Back после Logout | Login вместо старого расписания | Login вместо старого расписания |
| Logout при раскрытом chat | Центр кнопки получает клик | При 320 px и семи строках черновика центр кнопки получает клик |

Для проверки перекрытия Logout при 320×740 измерены: кнопка от y=243 до y=271, верх dock y=497.5. `document.elementFromPoint` в центре кнопки возвращал саму кнопку; обычный клик завершил выход. На desktop такой же hit-test тоже прошёл. Принудительных кликов сквозь перекрытия не использовалось.

Дополнительная проверка базы подтвердила итог: desktop и mobile manual-блоки снова на 09:00–09:30; оба draft-дня пустые со статусом draft; оба review имеют статус reviewed, сохранённые заметки и `reviewed_revision`, равный revision расписания.

## Скриншоты

| Доказательство | Файл |
| --- | --- |
| Desktop draft и доступный Undo | [desktop-draft.png](screenshots/browser-smoke-2026-10-17/desktop-draft.png) |
| Mobile chat, блок и Undo | [mobile-chat.png](screenshots/browser-smoke-2026-10-17/mobile-chat.png) |
| Mobile подтверждение удаления | [mobile-delete-dialog.png](screenshots/browser-smoke-2026-10-17/mobile-delete-dialog.png) |
| Восстановление удалённого блока | [mobile-undo-restored.png](screenshots/browser-smoke-2026-10-17/mobile-undo-restored.png) |
| Перенос после живого уточнения | [mobile-clarification.png](screenshots/browser-smoke-2026-10-17/mobile-clarification.png) |
| Mobile draft | [mobile-draft.png](screenshots/browser-smoke-2026-10-17/mobile-draft.png) |
| Форма 320 px до исправления | [mobile-form-before-320.png](screenshots/browser-smoke-2026-10-17/mobile-form-before-320.png) |
| Форма 320 px после исправления | [mobile-form-after-320.png](screenshots/browser-smoke-2026-10-17/mobile-form-after-320.png) |
| Logout и раскрытый chat при 320 px | [mobile-logout-reachable-320.png](screenshots/browser-smoke-2026-10-17/mobile-logout-reachable-320.png) |
| Back после мобильного Logout | [mobile-back-after-logout.png](screenshots/browser-smoke-2026-10-17/mobile-back-after-logout.png) |
| Back после desktop Logout | [desktop-back-after-logout.png](screenshots/browser-smoke-2026-10-17/desktop-back-after-logout.png) |
| Mobile review | [mobile-review.png](screenshots/browser-smoke-2026-10-17/mobile-review.png) |
| Desktop review | [desktop-review.png](screenshots/browser-smoke-2026-10-17/desktop-review.png) |

## Автоматические проверки и границы

- Backend: 2038 passed, один платный R11-тест пропущен по умолчанию.
- Frontend: 1389 passed, 102 файла.
- Ruff: без ошибок.
- Vue type-check и production build: прошли после последнего CSS-исправления.
- Новые регрессионные проверки: доступность Undo без клавиатуры, его блокировка во время записи и шифрование/очистка Inertia history.

Это проверка встроенного Chromium на мобильных viewport, а не физического iPhone. iOS Safari, экранная клавиатура и focus zoom остаются отдельным пунктом. Сценарии внешних аккаунтов, искусственно задержанных записей, category repair и PiP здесь не объявляются пройденными.
