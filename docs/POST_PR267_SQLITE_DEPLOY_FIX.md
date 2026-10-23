# Стабилизация SQLite snapshot-теста после PR #267

23 октября 2026 года. Исходный main: `2354cde35a9e28f611600caa7149c9416acfe9c2`. Ветка исправления: `codex/fix-sqlite-snapshot-test`.

## Причина остановки Deploy

[Deploy #39971679120](https://github.com/erzhan12/day-forge/actions/runs/39971679120) остановился на `test_schedule_get_snapshot_stays_coherent_across_concurrent_commit`: 1 failed, 2358 passed, 1 skipped. Сборка образа, публикация и health-check не запускались. Production на тот момент сохранил ранее проверенный `2f78696`; PR #267 менял только документацию и evidence. [Метаданные упавшего запуска](evidence/post-pr267-sqlite-2026-10-23/failed-deploy.json).

Тест открывает read snapshot, читает старый Schedule и запускает независимый SQLite writer. Writer меняет revision и заголовок блока, затем выполняет commit. До чтения блоков тест ждал 100 мс через `time.sleep(0.1)` и проверял `committed.is_set()`. Сигнал о начале commit не гарантирует его завершения за 100 мс. Кроме того, исключение writer могло остаться скрытым за этой общей проверкой.

Контрольный запуск с дополнительной задержкой commit в одну секунду воспроизвёл отказ старого теста. Этот результат показывает зависимость от скорости commit; сам исходный CI traceback не устанавливает, почему именно writer не завершился за 100 мс.

## Изменение

После чтения старого Schedule reader подаёт writer сигнал старта и вызывает `future.result(timeout=5)`. Чтение блоков продолжается только после завершения настоящего commit. Ошибки writer передаются в тест напрямую. Пятисекундный timeout ограничивает зависание.

Удалены фиксированный sleep и три промежуточных события. Добавлена проверка, что hook между чтением Schedule и блоков действительно выполнился. Сохранились проверки старой revision 0 и заголовка `Old` в HTTP-ответе, а также новой revision 1 и заголовка `New` в свежем чтении после запроса. Runtime-код `_read_schedule_page`, транзакция и правила SQLite не менялись.

## Проверки устойчивости и чувствительности

| Проверка | Результат |
| --- | --- |
| Весь SQLite concurrency-модуль | 16 passed |
| Исправленный snapshot-тест на новых копиях test DB | 30 последовательных повторов прошли |
| Старый тест, commit замедлен на 1 секунду | Ожидаемый отказ на проверке завершения commit |
| Исправленный тест с тем же замедлением | Прошёл |
| Исправленный тест без read snapshot | Ожидаемый отказ: старый Schedule сочетается с заголовком `New` |
| Ошибка writer перед commit | Исходный `RuntimeError: controlled writer failure` передан в тест |

Временные варианты выполнялись только в отдельных subprocess на копиях pytest-базы. Production и рабочая SQLite база не использовались. 30 повторов и четыре контрольных случая дали 34 успешные проверки ожидаемого поведения. Замедление writer используется только в отдельном диагностическом прогоне, в основном snapshot-тесте sleep отсутствует. [Результаты и hashes](evidence/post-pr267-sqlite-2026-10-23/probes.json).

Воспроизведение из корня репозитория:

```sh
uv run pytest backend/tests/test_schedule_mutations_sqlite.py -q
uv run python docs/evidence/post-pr267-sqlite-2026-10-23/probe_sqlite_snapshot.py
make check
```

Диагностический runner требует доступный Git commit `2354cde` для старого варианта. Он создаёт отдельный временный тестовый модуль, отказывается перезаписывать существующий файл и удаляет свой модуль в `finally`. Имя `probe_sqlite_snapshot.py` не совпадает с pytest-шаблонами тестовых файлов. Обычный `pytest --collect-only -q` нашёл 2360 штатных случаев, включая один opt-in skip, без запуска диагностического runner.

## Полный локальный прогон

`make check`: 2359 backend passed, 1 skipped; 1459 frontend passed в 105 файлах. Ruff и TypeScript прошли. Единственный skip относится к прежнему opt-in R11 live comparison. Image retention tests прошли; production npm audit сообщил 0 vulnerabilities. Django system check не обнаружил проблем, `makemigrations --check --dry-run` не нашёл изменений. [Checks](evidence/post-pr267-sqlite-2026-10-23/checks.json).

## Публикация

Исправление вошло в [PR #268](https://github.com/erzhan12/day-forge/pull/268), merge commit `2496bd770288593978631d37371f7d02fff201a5`. [PR CI](https://github.com/erzhan12/day-forge/actions/runs/39974051806) прошёл. [Claude Review](https://github.com/erzhan12/day-forge/pull/268#issuecomment-6367859419) одобрил PR. Единственное замечание об удалении `start` не применено: writer явно вызывает `start.wait(5)` перед `BEGIN IMMEDIATE`. Событие необходимо, чтобы запись началась после чтения старого Schedule.

[Deploy #39974398612](https://github.com/erzhan12/day-forge/actions/runs/39974398612) успешно опубликовал `2496bd7`: повторная validation, build/push, deploy и health-check прошли. Таким образом, восстановлена публикация main после остановки Deploy PR #267. [Метаданные успешного запуска](evidence/post-pr267-sqlite-2026-10-23/successful-deploy.json).

Независимый HTTPS-запрос после health-check подтвердил Login 200 с точной версией `2496bd770288593978631d37371f7d02fff201a5`; JS/CSS вернули 200 и immutable cache policy. [Публичная проверка](evidence/post-pr267-sqlite-2026-10-23/published-release.json).

Первый публичный probe после `docker compose up -d`, во время stabilization wait, получил 502. После завершения health-check повторная проверка прошла. Этот переход сохранён в [startup probe](evidence/post-pr267-sqlite-2026-10-23/startup-probe.json); непрерывная доступность во время рестарта этим Deploy не установлена.

В последующем обновлении отчёта runner переименован из `probe_snapshot_test.py` в `probe_sqlite_snapshot.py`, чтобы opt-in диагностика не попадала под автоматический pytest discovery. Его содержимое не менялось; обычный сбор всех тестов проверен отдельно. Новые production-записи, AI-вызовы, изменения конфигурации и миграции для этого исправления не выполнялись.
