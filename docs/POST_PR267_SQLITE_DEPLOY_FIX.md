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
uv run python docs/evidence/post-pr267-sqlite-2026-10-23/probe_snapshot_test.py
make check
```

Диагностический runner требует доступный Git commit `2354cde` для старого варианта. Он создаёт отдельный временный тестовый модуль, отказывается перезаписывать существующий файл и удаляет свой модуль в `finally`. В обычный CI runner не включён.

## Полный локальный прогон

`make check`: 2359 backend passed, 1 skipped; 1459 frontend passed в 105 файлах. Ruff и TypeScript прошли. Единственный skip относится к прежнему opt-in R11 live comparison. Image retention tests прошли; production npm audit сообщил 0 vulnerabilities. Django system check не обнаружил проблем, `makemigrations --check --dry-run` не нашёл изменений. [Checks](evidence/post-pr267-sqlite-2026-10-23/checks.json).

## Публикация

На момент подготовки PR исправление ещё не опубликовано. Для закрытия задачи требуются успешные PR CI и ревью, merge в main, полный Deploy с health-check и проверка публичной версии. Итог публикации будет добавлен после завершения этого прогона.
