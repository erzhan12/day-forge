# Устранение npm advisories

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
