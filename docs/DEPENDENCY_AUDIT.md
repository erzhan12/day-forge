# Устранение npm advisories

## 21 октября 2026: блокировка Deploy после PR #252

Deploy для `8b51895` остановился на production audit до сборки и публикации образа. Lockfile содержал `follow-redirects@1.16.0`, для которого GitHub advisory database сообщает о двух high-проблемах: [array-form headers](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8) и [sensitiveHeaders regex](https://github.com/advisories/GHSA-8r9p-f939-6h3c). Обе исправлены в `1.16.1`. Пакет входит в production dependency tree через axios/Inertia; это не подтверждение эксплуатации в приложении.

Обновлена только запись `follow-redirects` в lockfile, с `1.16.0` до `1.16.1`. `package.json` и workflow не менялись, audit gate сохранён. После `npm ci` production audit вернул 0 vulnerabilities. Полный `make check` прошёл: 2138 backend, 1 skipped, 1409 frontend, Ruff и type-check. Production build прошёл. Пропущен существующий opt-in платный comparison.

Исходный неуспешный запуск: [Deploy #39481554138](https://github.com/erzhan12/day-forge/actions/runs/39481554138). Проверка durable request_id на production требует успешного Deploy исправленного релиза; успешные PR checks до публикации advisory не заменяют эту проверку.

## 12 октября 2026: dev-зависимости

Дата: 12 октября 2026 года. В `frontend/package-lock.json` обновлены dev-зависимости после того, как `npm audit` сообщил о шести advisory: двух moderate и четырёх high. Уязвимые пакеты не входили в production dependency tree. `frontend/package.json` не менялся, major-версии не менялись.

Обновлённые версии:

| Пакет | Было | Стало |
| --- | --- | --- |
| `vite` | 6.4.2 | 6.4.4 |
| `vitest` и `@vitest/mocker` | 4.1.4 | 4.1.11 |
| `brace-expansion` | 2.0.3 | 2.1.7 |
| `js-cookie` | 3.0.5 | 3.0.8 |
| `undici` | 7.24.7 | 7.30.0 |

Сначала `npm audit fix --dry-run` завершился внутренней ошибкой npm 10.9.8 при разрешении optional peer dependency Vitest (`Cannot read properties of null (reading 'edgesOut')`). npm 11 успешно обновил lockfile; затем `npm ci` установил зафиксированное дерево. Временный npm 11 запускался через `npx`, версия npm проекта и его скрипты не менялись.

Проверки после обновления прошли: `npm audit --audit-level=moderate` (0 advisories), `make check` (1 980 backend- и 1 387 frontend-тестов, Ruff и TypeScript), `make frontend-build` и `git diff --check`. Production bundle сохранил прежний размер: 483.34 kB JS до gzip (158.99 kB gzip) и 70.48 kB CSS (12.23 kB gzip).
