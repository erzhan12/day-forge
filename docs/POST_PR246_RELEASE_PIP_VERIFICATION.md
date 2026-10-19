# Релиз после PR #246 и настоящая проверка PiP

19 октября 2026 года, Asia/Almaty. База: `d449ec36201eefbf5e41e370ec723e41f792ea02`, `main` после PR #246.

## Результат

[Deploy #39209152976](https://github.com/erzhan12/day-forge/actions/runs/39209152976) завершился успешно в 11:22:41 по Asia/Almaty (06:22:41 UTC). Опубликованный HTML и frontend bundle содержат правильный SHA. Проверены публичные страницы и чтение Schedule, Settings и Analytics через существующую Chrome-сессию.

A07 закрыт в обычном Google Chrome на macOS через нативное управление CUA. Настоящее окно Document PiP открылось, сохранилось при переходе в Settings и закрылось при Logout и истечении сессии. После входа под другим локальным пользователем показало только его блок. Новых ошибок приложения не найдено; исходники приложения не менялись.

## Опубликованный релиз

| Проверка | Результат |
| --- | --- |
| Login, Privacy, Terms | HTTPS, HTTP 200 |
| Версия HTML | `d449ec36201eefbf5e41e370ec723e41f792ea02` |
| JS | `app-DWdcYqjF.js`, HTTP 200, SHA релиза встроен в bundle |
| CSS | `app-COtgMyyv.css`, HTTP 200 |
| Кеш JS/CSS | `max-age=315360000, public, immutable` |
| Анонимные Settings/Schedule | Redirect на Login |
| Inertia с версией PR #245 | HTTP 409 и `X-Inertia-Location` для обновления документа |
| Авторизованный Chrome | Schedule, Settings и Analytics открылись через существующую production-сессию |

JS SHA-256: `8636756d3c84eed72f9cb6254d7bcf85c6147d4d8058dcd5eb46db773e6aafce`.
CSS SHA-256: `d26f2305d3ef0accf5da103ac28ff78b6b40e68e7d401f75df97d1ebf341e85b`.

В локальной конфигурации по-прежнему нет credentials выделенного production-тестера. Найденная Chrome-сессия не идентифицирована как тестовая. Она позволила проверить авторизованное чтение, но не новый вход с паролем. Команды изменения блоков, фиксации review и Logout в production не выполнялись. Содержимое пользовательских страниц и вкладок Chrome в evidence не сохранялось.

## Изолированный PiP-стенд

Использован существующий [release_browser_server.py](../backend/scripts/release_browser_server.py) с новой базой под `/tmp`, отдельной session cookie и обычными backend endpoints. Рабочая база и `.env` не использовались для записи. Server работает с `DEBUG=0`, WhiteNoise и собранными assets; HTTP-настройки localhost задаёт сам fixture-скрипт. Это Django runserver, не повторная контейнерная репетиция.

Сборка получила SHA `d449ec3…`. SHA-256 её JS/CSS совпали с опубликованными файлами. AI и polling отключены, Redis не нужен, ключи интеграций заменены тестовыми значениями, подключённых аккаунтов нет. Реальные AI/provider calls в этом прогоне не выполнялись.

Первому fixture-пользователю задан текущий UTC-блок `PiP lifecycle fixture`. Второму задан другой блок, `Second account fixture`. Эти названия не относятся к production-расписанию.

Chrome отсутствовал среди управляемых browser tabs, но был доступен как нативное приложение. Проверка выполнена через `cua.getApp("com.google.Chrome")`, обычные клики и переключение окон. Встроенный браузер, Playwright-моки PiP и подмена `requestWindow` для этого сценария не использовались.

## Настоящий lifecycle окна

| Сценарий | Наблюдение |
| --- | --- |
| Show indicator | Открылось отдельное окно `about:blank`; accessibility document title `Focus`, тело содержит первый тестовый блок, оставшееся время и progressbar |
| Schedule после открытия | Кнопка стала `Hide indicator`; Chrome пометил вкладку как picture-in-picture |
| Schedule → Settings | Основная страница стала Settings; переключение обратно на PiP подтвердило, что окно и тестовый блок сохранились |
| Список окон при открытом PiP | Меню Chrome Window содержит два окна Day Forge: основное и PiP |
| Settings → Schedule → Logout | Login; picture-in-picture отметка пропала, меню Window содержит одно основное окно |
| Повторный вход | PiP не открылось автоматически; новое открытие выполнено кнопкой Show indicator |
| Истечение сессии | Удалены только строки `django_session` fixture-базы. Переход Schedule → Settings получил redirect на Login; PiP закрылось, в Window осталось одно окно |
| Другой пользователь | После входа под вторым локальным аккаунтом PiP не открылось само. По кнопке открылось с `Second account fixture`; первого названия в окне нет |
| Последний Logout и Back | Login, приватный Schedule не восстановился, PiP не открылось |

Закрытие проверялось по фактическому исчезновению второго окна и состоянию Chrome, а не только по успешному redirect. Сохранённый root snapshot не извлекался из памяти браузера. Защиту поздней публикации дополнительно проверяют существующие тесты generation/account boundary.

| Снимок | Что подтверждает |
| --- | --- |
| [Открытое PiP](screenshots/post-pr246-pip-2026-10-19/pip-open.png) | Настоящее отдельное окно и первый тестовый блок |
| [PiP после Settings](screenshots/post-pr246-pip-2026-10-19/pip-retained-settings.png) | Сохранение окна при Inertia-навигации |
| [PiP второго аккаунта](screenshots/post-pr246-pip-2026-10-19/pip-second-account.png) | Отсутствие прежнего блока после session boundary |

Снимки содержат только отдельное PiP-окно локального стенда. Полное окно Chrome с посторонними вкладками не включено в отчёт.

## Проверки

- Deploy CI на `d449ec3` прошёл: backend lint/tests, frontend type check/tests/build, production npm audit, image-retention и SSH pinning.
- Дополнительная production-сборка с release SHA прошла; JS/CSS совпали с опубликованными файлами.
- Фокусные frontend suites: **106 passed, 6 файлов** (`useFocusIndicator`, `FocusIndicatorHost`, `scheduleFocusIndicator`, `FocusIndicatorView`, `ShowIndicatorButton`, `focusIndicatorStorage`).
- Новых runtime-изменений нет. Полные локальные suites повторно не запускались; полный набор прошёл в Deploy CI.
- Fixture-база прошла SQLite integrity check. В ней два тестовых пользователя, нет интеграций и оставшихся сессий. Созданная вкладка закрыта, fixture-сервер остановлен, временная база и сборка удалены. Другие вкладки и production-сессия сохранены.

Машиночитаемые результаты и HTTP-события локального стенда: [evidence](evidence/POST_PR246_RELEASE_PIP_VERIFICATION.json). Они не содержат credentials, cookies, production-блоков или raw accessibility tree.

## Воспроизведение

1. Собрать frontend с release SHA в новый каталог под `/tmp`.
2. Запустить `release_browser_server.py ROOT BUILD_DIR`. Для PiP можно явно отключить AI и polling, использовать пустой `REDIS_URL` и тестовые integration keys. Production system checks не следует отключать.
3. В свежей fixture-базе установить сегодняшний блок в текущий UTC-интервал. Открыть `http://127.0.0.1:8008/accounts/login/` в обычном Chrome и войти fixture-пользователем, указанным в скрипте. Отклонить сохранение тестового пароля.
4. Нажать Show indicator. Через переключение окон Chrome перейти в основное окно, затем в Settings и обратно к PiP. Не использовать `Back to tab` в PiP для проверки сохранения окна: эта кнопка сама закрывает его.
5. Вернуться на Schedule и выполнить Logout. Сравнить список Window до и после: два окна, затем одно.
6. Войти снова, открыть PiP, удалить сессии только fixture-базы и перейти по защищённой ссылке. Проверить Login и отсутствие окна.
7. Войти вторым локальным пользователем с другим текущим блоком. Проверить, что окно открывается только по жесту и показывает новый блок.

Для истечения сессии использовать только новую базу с marker-файлом fixture:

```python
from pathlib import Path
import sqlite3

root = Path("/tmp/YOUR_PIP_FIXTURE").resolve()
assert root.is_relative_to(Path("/tmp").resolve())
assert (root / "release-fixture.marker").is_file()
with sqlite3.connect((root / "fixture.sqlite3").as_uri() + "?mode=rw", uri=True) as db:
    db.execute("DELETE FROM django_session")
```

После проверки закрыть созданную вкладку и остановить только fixture-сервер. Production-сессию и другие окна пользователя сохранять.

## Что остаётся

Новый вход с паролем, mutations и Logout на выделенном production-тестере остаются незакрытым smoke. Также этот прогон не проверял настоящий iOS Safari, нагрузку, живые OAuth reconnect/completion и качество AI. Закрытие A07 относится к нативному Chrome на локальном стенде с frontend assets текущего production-релиза.
