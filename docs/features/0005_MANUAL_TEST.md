# Фаза 5 — Templates, Rules & Drafts: план ручного тестирования

Что покрываем: per-user CRUD для `Template` + `Rule` на `/settings/`,
эндпоинт `POST /api/ai/schedules/<date>/generate-draft/`, auto-draft
триггер на свежеоткрытом дне, ручную кнопку **Regenerate draft**,
draft badge и правила перехода `status` (`draft → active` при первом
реальном edit'е).

---

## Подготовка

Два терминала (из **корня проекта**):

```bash
# Terminal 1 — Django (:8006)
# Перед запуском задать LLM_API_KEY в .env (без него драфты не работают).
# Опционально подкрутить LLM_DRAFT_MODEL / LLM_DRAFT_RATE_LIMIT_PER_HOUR / LLM_HISTORY_DAYS.
make run

# Terminal 2 — Vite (:5173)
make frontend-dev
```

- [X] Открыть http://localhost:5173/ и залогиниться.
- [X] DevTools → **Network** (фильтр `Fetch/XHR`) и **Console**. Держать на виду.
- [X] Проверять `AIInteraction` строки для драфтов:
  ```bash
  uv run python backend/manage.py shell -c "from ai.models import AIInteraction; [print(i.id, i.kind, i.success, i.user_command[:30]) for i in AIInteraction.objects.order_by('-id')[:10]]"
  ```

Эндпоинты за которыми смотрим: `POST /api/ai/schedules/<date>/generate-draft/`,
`GET/POST/PUT/DELETE /api/templates/...`,
`GET/POST/PATCH/DELETE /api/rules/...`.

### Заметка о возврате в состояние "freshly drafted"

Несколько тестов ниже требуют schedule со `status="draft"` и хотя бы
одним авто-сгенерированным блоком. Естественный путь туда — зайти на
дату, на которой ты НИКОГДА не был раньше: `auto_draft_pending` это
**one-shot** server prop, который `true` только на запросе, который
*создаёт* строку `Schedule`. Поэтому каждый сценарий использует свежую
дату.

Чтобы попасть в `status="draft" && blocks=[]` (состояние, которое
снова показывает Regenerate pill), нажми **⌘Z (или Ctrl+Z)** для undo
драфта. Undo идёт через `restore_blocks([])`, который специально **не**
флипает `status` — это единственный надёжный способ очистить blocks,
сохранив draft badge. Удаление блоков по одному в UI флипает
`status → active` на первом же delete (потому что каждый
forward-mutating endpoint вызывает `mark_active_on_edit()` —
переименован из `mark_active_if_draft()` в Phase 6, чтобы покрывать
ещё и `reviewed → active`), и Regenerate pill пропадает.

---

## Тест 1 — Первый запуск: нет шаблона, нет auto-draft

**Исходное состояние**: свежий аккаунт (нет templates, нет rules), нет
строки `Schedule` на сегодня.

- [X] Запустить `uv run python backend/manage.py createsuperuser` если нужно.
- [X] Зайти на `/schedule/<today>/`.

**Ожидаемое поведение**:

- [X] Страница рисуется мгновенно (нет spinner overlay).
- [X] Запрос `POST /generate-draft/` НЕ улетает.
- [X] В теле schedule один пустой gap на весь день (06:00–23:00).
- [X] В правой части date navigator'а отрисован "Regenerate draft" pill —
  визуально **disabled / приглушённый** с inline-причиной
  `No <weekday|weekend> template configured.` прямо под ним.
- [X] Иконка шестерёнки (⚙) находится между pill'ом и стрелкой "вперёд",
  ведёт на `/settings/`.

---

## Тест 2 — Страница Settings: создание weekday template

- [X] Кликнуть по шестерёнке → попадаем на `/settings/`.
- [X] Отрисованы два пустых слота: `No weekday template yet.` и
  `No weekend template yet.`, каждый с кнопкой **Create template**.
- [X] Кликнуть **Create template** под weekday-слотом. Появляется форма
  с типом слота как read-only тегом.
- [X] Добавить три блока (например, 07:00–07:30 health, 09:00–12:00 work,
  17:30–18:30 health) и нажать **Save**.
- [X] **Network**: `POST /api/templates/` → `201`.
- [X] Форма перерисовывается в edit-режиме (теперь появилась кнопка
  **Delete template**).
- [X] Попробовать ввести overlap (09:30–10:00 внутри deep-work блока)
  и сохранить → **400** с inline-списком ошибок под таблицей блоков.
- [X] Исправить overlap и сохранить ещё раз → `200`.

---

## Тест 3 — Страница Settings: CRUD правил (rules)

- [X] В секции **Rules** ввести "No meetings before 9" и нажать **Add rule**.
- [X] Строка появляется с priority `0`.
- [X] Кликнуть по тексту строки → переключается на inline-edit input.
  Изменить на "No meetings before 9 AM" и нажать Enter.
- [X] **Добавить второе правило** "Lunch always 12-13" через **Add rule**
  (нужно минимум 2 правила для теста ▲▼ — стрелки disabled когда у
  правила нет соседа в нужную сторону: `:disabled="idx === 0"` для ▲
  и `:disabled="idx === localRules.length - 1"` для ▼).
- [X] Кликнуть ▲ на нижней строке, чтобы поднять её priority. Бэкенд
  делает **один PATCH** (когда у соседа priority отличается —
  свапает значения; когда priorities равны — просто бампает на ±1)
  — оба варианта дают `200`. Строки меняются местами в UI.
- [X] Тогглнуть чекбокс → строка визуально выцветает, текст получает
  strikethrough (CSS `.inactive`).
- [X] Кликнуть × → confirm dialog → `DELETE /api/rules/<id>/` → строка
  пропадает.

---

## Тест 4 — Auto-draft срабатывает при заходе на новый день

**Исходное состояние**: weekday template существует (после Тест 2),
`LLM_API_KEY` задан.

- [ ] Перейти стрелками даты на будущий weekday, который ты НИКОГДА не
  посещал (например, `/schedule/2026-05-11/`, понедельник).
- [ ] **Network**: страница рендерится с `auto_draft_pending=true` в
  Inertia props, затем автоматически улетает
  `POST /api/ai/schedules/2026-05-11/generate-draft/`.
- [ ] В теле schedule отрисован spinner overlay по центру с текстом
  "Generating draft…".
- [ ] Пока генерится: command bar input отключён, кнопка "+ Add Block"
  отключена, click-to-add по gap-слотам подавлен (cursor: not-allowed).
- [ ] Через ~5–10с draft отрисовывается. У каждого блока ожидаемый
  цвет категории. Pill в date navigator'е теперь читается
  "Draft — edit to keep" (`DraftBadge`); Regenerate pill пропал
  (он рендерится только когда `blocks.length === 0`).
- [ ] В шелле `AIInteraction` показывает строку с `kind=draft`,
  `success=True`.

---

## Тест 5 — `status` флипается на первом реальном edit'е

Стартуем с свежедрафтнутого schedule (Тест 4 оставляет тебя в этом
состоянии на дате X — если X "израсходован", перейди на другую свежую
дату и дай auto-draft отработать).

- [ ] Кликнуть по любому блоку для inline-edit заголовка и нажать Enter.
- [ ] **Network**: `PATCH /api/blocks/<id>/` → `200`. Inertia partial
  reload запрашивает `["blocks", "schedule"]`.
- [ ] Badge "Draft — edit to keep" **пропадает** (status флипнулся в
  `active` на сервере, и partial reload это подхватил).
- [ ] **(Phase 6 артефакт)** В правой части date navigator'а появляется
  ссылка "View analytics" — это нормально, не баг.

Для каждой из вариаций ниже зайди на свежую дату, чтобы auto-draft
снова отработал, выполни действие и подтверди что badge пропадает:

- [ ] Тогглнуть чекбокс (completion) → флипает.
- [ ] Перетащить блок на новый слот → флипает.
- [ ] Добавить новый блок через форму "+ Add Block" → флипает.
- [ ] Команда AI command bar с реальным действием ("add coffee at 10:00")
  → флипает.

---

## Тест 6 — AI command no-op НЕ флипает `status`

**Исходное состояние**: свежедрафтнутый schedule (`status=draft`,
блоки на месте).

- [ ] В command bar ввести что-то, от чего AI откажется, например
  "what's the weather like".
- [ ] `POST /api/ai/schedules/<date>/command/` возвращает `200` с
  `actions: []` и объяснением в баре.
- [ ] Badge "Draft — edit to keep" **остаётся** (RULES.md: 200 с нулём
  actions это успешный no-op; флип статуса гейтится на
  `len(parsed_actions) > 0`).

---

## Тест 7 — Undo драфта

**Исходное состояние**: свежедрафтнутый schedule.

- [ ] Нажать ⌘Z (или Ctrl+Z).
- [ ] **Network**: `POST /api/schedules/<date>/blocks/restore/` с
  `{"blocks": []}`.
- [ ] Schedule становится пустым; draft badge пропадает (нет блоков);
  `status` остаётся `draft` (проверим в следующем шаге).
- [ ] Pill **Regenerate draft** снова появляется в date navigator'е,
  **enabled** (template существует, `status=draft`, `blocks=0`).

Опциональная проверка через шелл:
```bash
uv run python backend/manage.py shell -c "from schedules.models import Schedule; s = Schedule.objects.get(date='2026-05-11'); print(s.status, s.time_blocks.count())"
# → draft 0
```

---

## Тест 8 — Manual regenerate

**Исходное состояние**: пустой drafted schedule (то состояние, в котором
тебя оставил Тест 7 — `status=draft`, `blocks=[]`).

- [ ] Кликнуть pill **Regenerate draft**.
- [ ] Появляется spinner overlay; улетает `POST /generate-draft/`.
- [ ] Draft регенерится; badge снова флипает в "Draft — edit to keep".

---

## Тест 9 — 409 при regenerate с существующими blocks

UI прячет кнопку Regenerate когда блоки есть, поэтому это curl-only
проверка серверного guard'а.

- [ ] Залогиниться через curl (выставит sessionid + XSRF-TOKEN cookies):
  ```bash
  curl -s -c cookies.txt -b cookies.txt \
    -H "Content-Type: application/json" \
    -d '{"username":"<your-username>","password":"<your-password>"}' \
    http://localhost:8006/accounts/login/ > /dev/null

  CSRF=$(grep XSRF-TOKEN cookies.txt | awk '{print $NF}')
  ```
- [ ] Дёрнуть generate-draft на дате с блоками:
  ```bash
  curl -X POST -b cookies.txt \
    -H "X-XSRF-TOKEN: $CSRF" \
    -H "Content-Type: application/json" \
    http://localhost:8006/api/ai/schedules/<date-with-blocks>/generate-draft/
  # → 409 {"errors":{"detail":"Schedule already has blocks; delete them before regenerating."}}
  ```

Путь 409 **не** жжёт rate-limit budget (см. Тест 10).

---

## Тест 10 — Rate limit (отдельный counter, preconditions не жгут budget)

### 10a. Сжечь budget реальными LLM-вызовами

- [ ] Поставить `LLM_DRAFT_RATE_LIMIT_PER_HOUR=2` в `.env` и перезапустить Django.
- [ ] Зайти на свежий weekday (например, `/schedule/2026-05-12/`) —
  auto-draft срабатывает (counter = 1).
- [ ] ⌘Z для undo (состояние: `status=draft`, `blocks=[]`).
- [ ] Кликнуть **Regenerate draft** — отрабатывает (counter = 2).
- [ ] ⌘Z ещё раз.
- [ ] Кликнуть **Regenerate draft** → `429`. Inline-ошибка под телом
  schedule читается "Draft rate limit reached. Try again later."
- [ ] Подтвердить что **command bar всё ещё работает** (отдельный
  counter; AI command на другом schedule не должна 429-ить).

### 10b. 409 / 422 / 413 / 400 НЕ должны тратить budget

Это пинит регрессию которую мы заложили в этом PR.

- [ ] Сбросить кэш чтобы counter стартовал с 0:
  ```bash
  uv run python backend/manage.py shell -c "from django.core.cache import cache; cache.clear()"
  ```
  (FileBasedCache хранит entries в `.cache/` — clear кэша атомарно
  сбрасывает все counters.)
- [ ] С `LLM_DRAFT_RATE_LIMIT_PER_HOUR=2` дёрнуть endpoint 3 раза через
  curl на дату с блоками (форсит 409 каждый раз):
  ```bash
  for i in 1 2 3; do
    curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST -b cookies.txt \
      -H "X-XSRF-TOKEN: $CSRF" \
      -H "Content-Type: application/json" \
      http://localhost:8006/api/ai/schedules/<date-with-blocks>/generate-draft/
  done
  # → 409 409 409  (НЕ 409 409 429)
  ```
- [ ] Проинспектировать counter: должен отсутствовать или быть равным 0.
  ```bash
  uv run python backend/manage.py shell -c "from django.core.cache import cache; print(cache.get('ai_draft_rl:1'))"
  # → None
  ```

---

## Тест 11 — Изоляция между пользователями

- [ ] Создать второго суперюзера через `createsuperuser`.
- [ ] Под пользователем A создать weekday template с именем "A weekday".
- [ ] Разлогиниться, залогиниться под B. Зайти на `/settings/`.
- [ ] Страница показывает два пустых слота — template'а A не видно.
- [ ] Зайти на `/schedule/<today>/`. Кнопка Regenerate **disabled** для
  пользователя B, потому что у него нет template'а.
- [ ] Подтвердить через шелл:
  ```bash
  uv run python backend/manage.py shell -c "from templates_mgr.models import Template; [print(t.user.username, t.type) for t in Template.objects.all()]"
  ```
- [ ] (Cross-user PK guard) Под пользователем B попытаться сделать PUT
  на template пользователя A по id — сервер возвращает **404** (не 403):
  ```bash
  curl -X PUT -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
    -H "Content-Type: application/json" \
    -d '{"name":"hacked","type":"weekday","blocks":[]}' \
    http://localhost:8006/api/templates/<user-A-template-id>/
  # → 404 {"errors":{"detail":"Not found."}}
  ```

---

## Тест 12 — 422 fallback (template удалён между загрузкой страницы и кликом)

- [ ] Открыть `/schedule/<future-weekday>/` с присутствующим weekday
  template'ом. Дождаться окончания auto-draft, затем ⌘Z для очистки
  блоков. Теперь Regenerate pill виден и enabled.
- [ ] В другой вкладке браузера открыть `/settings/` и **удалить**
  weekday template.
- [ ] Вернуться на вкладку schedule БЕЗ перезагрузки и кликнуть
  **Regenerate draft**. Inertia-проп `has_template_for_type` устарел,
  поэтому кнопка локально всё ещё enabled.
- [ ] **Network**: `POST /generate-draft/` → `422`.
- [ ] Inline-ошибка читается "No template configured. Open Settings to
  create one." Ручное редактирование (drag, edit, delete, +Add Block)
  всё ещё работает.
- [ ] После клика по шестерёнке и пересоздания template'а возврат на
  schedule перерендеривает с `has_template_for_type=true`, и кнопка
  снова enabled.
