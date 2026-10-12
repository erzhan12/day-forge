# R12: текущая документация и итоговая проверка

Дата: 11 октября 2026 года. Этап выполнен локально после R00–R11. Изменения проверены в общем рабочем дереве; публикация PR и deployment в эту задачу не входили.

## Документация

- [ARCHITECTURE.md](ARCHITECTURE.md) описывает текущих владельцев HTTP, команд, проверки итогового дня, транзакции, persistence и состояния frontend. В нём указаны границы SQLite, Undo, аналитики, интеграций и AI.
- [RULES.md](../RULES.md) содержит текущие инварианты и исключения. Старые 1036 строк сохранены дословно в [RULES_HISTORY.md](archive/RULES_HISTORY.md), с отдельной исторической пометкой. Из текущего справочника убраны несуществующий `justCompletedId`, старый dispatcher и утверждения об отсутствии пользовательского timezone.
- [api.md](api.md) приведён к обязательному `expected_revision`, каноническому снимку ответа, source policies и saved timezone. Уточнены restore, frozen review, category maintenance и metadata интеграций. Одинаковый restore сохраняет ID; изменённый создаёт новые. AI audit выполняется best effort и не является подтверждением commit.
- [tasks/todo.md](../tasks/todo.md) отделяет оставшуюся работу от выполненных и заменённых предложений. Старые 1075 строк сохранены дословно в [TODO_HISTORY.md](archive/TODO_HISTORY.md). Остались эффект и зависимость каждого follow-up, включая связь limiter с R03. Уже реализованный atomic swap правил закрыт.
- [features/README.md](features/README.md) обозначает номерные feature-планы и reviews как исторические документы. Исходные планы не переписывались. [PHASES.md](../PHASES.md) также помечен историческим roadmap.
- [tasks/lessons.md](../tasks/lessons.md) сохраняет действующие классы ошибок: retained rows, disconnect, диалоги, reactive snapshots и конкурентный drag. Примеры обновлены после переносов, повторы сокращены.

## Команды

[README](../README.md), [AGENTS](../AGENTS.md), [Makefile](../Makefile) и [deployment README](../deployment/README.md) согласованы с текущими entry points. `make migrate` применяет существующие миграции; создание вынесено в `make makemigrations`. `make seed SEED_USER=username` требует пользователя до запуска Django. `make frontend-install` использует lockfile через `npm ci`. `make check` включает Ruff, backend suite, frontend type-check и frontend suite; production build выполняется отдельной командой.

PR и deployment используют один reusable CI workflow. Production dependency audit и SSH host-key pinning остаются обязательными проверками. Локальные проверки не подтверждают успешный запуск workflow в GitHub Actions.

## Категории frontend

Удалён каталог вымышленных fallback-категорий из `utils/categories.ts`. Backend создаёт каталог при загрузке Schedule, Settings и Analytics; production страницы получают реальные пользовательские строки. Формы ручного добавления, импорта и шаблона выбирают default/sink из этого каталога.

Runtime-проверка отклоняет пустой или повреждённый каталог: более восьми строк, неверные поля, повторные ID/slug, отсутствие единственного sink или default. Страницы показывают понятную ошибку с предложением reload. При переходе valid → invalid controller блокирует клавиатурный и прямой Undo, активный drag отменяется с освобождением обработчиков. Уже отправленный запрос может завершиться на сервере, его результат нужно согласовать с каноническим состоянием.

Fixtures передают полный каталог. Сохранён fallback цвета для отображения, он не создаёт категорий и не разрешает запись несуществующего slug. Независимый review проверил bootstrap, переход valid → invalid, блокировку Undo и cleanup drag. Блокирующих замечаний не осталось.

## Проверки

| Проверка | Результат |
|---|---|
| `uv run pytest backend/tests/ -q` | 1946 passed, 22,90 с |
| `cd frontend && npm test` после последнего изменения | 1355 passed, 102 файла, 11,00 с |
| `npm run build` | vue-tsc и Vite прошли |
| Ruff, Django check | Прошли |
| `makemigrations --check --dry-run` | No changes detected |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| SSH pinning invariant | Все 5 SSH/SCP команд strict и pinned |
| Makefile | `check` содержит оба suites; `migrate` не создаёт миграции; seed без пользователя отказывает до Django |
| Локальные ссылки текущих entry-point документов | Все целевые файлы существуют |

Первый frontend-прогон обнаружил шесть PiP-тестов с неполным каталогом в fixtures. Fixtures исправлены без ослабления проверок PiP. Последующий полный прогон прошёл. Дополнительные regression-тесты проверяют повреждённые категории, Undo и отмену drag после смены каталога.

## Браузер и реальные AI-запросы

Проверки выполнены на локальном обычном backend, с тестовым пользователем `playwright` и синтетическими данными:

| Сценарий | Результат |
|---|---|
| Login, навигация, Settings, категории и шаблоны | Страницы открываются, формы используют живой каталог |
| Ручное добавление и completion | Создан Personal-блок, completion сохранён |
| Cancel/Delete/Undo | DOM-диалог управляется автономно; Undo восстановил блок и completion |
| Notes, review, Markdown export | Заметки сохранены, обзор зафиксирован, экспорт содержит оба блока и completion 1/2 |
| Desktop Logout и повторный Login | Logout открыл форму входа, новый Login вернул расписание |
| Реальный AI chat | Audit 335: успешное добавление `R12 real chat`, Work, 14:00–14:30 |
| Реальный AI draft | Audit 336: успешный `Deep work`, Work, 09:00–12:00; день остался draft |
| Реальный AI и клавиатурный Undo после последнего изменения | Audit 337: `R12 AI Undo`, 15:00–15:30; Undo удалил этот блок и сохранил остальные |

OpenRouter был доступен, заглушки не использовались. Эти smoke-запросы проверяют соединение и применение результата. Они не заменяют контролируемое сравнение качества R11. Заглушки позволяют проверить поведение приложения при заданном ответе, но не качество или доступность живой модели.

Viewport override 390×844 принят инструментом, но измеренный `window.innerWidth/innerHeight` остался 1280×720. Поэтому мобильный browser smoke остаётся открытым. Временный override сброшен.

Перед браузерными проверками сохранена согласованная SQLite backup. После них удалены только синтетические блоки и обзор двух исходно пустых дней через maintenance executor под User lock. Дни возвращены в draft; revision увеличены монотонно до 59 и 16, откат версии не выполнялся. Все 335 исходных TimeBlock и 27 DailyReview совпадают с backup по всем колонкам; preferences и schedule settings не изменились. AI audit 335–337 сохранён. Повторная загрузка обеих дат показала пустые рабочие расписания. Временные вкладки закрыты, обычные dev servers оставлены работающими.

## Оставшаяся работа

В [todo](../tasks/todo.md) сохранены первый PR CI run, контролируемое AI-сравнение R11, мобильный smoke и предложения server-owned pending intent/request identity. Review также зафиксировал существующую проблему SettingsCategoriesPanel: отклонённый label/color может остаться в DOM, а `errors.detail` для 429/409 не выводится. Она не введена R12 и оставлена отдельным follow-up с regression-тестами.
