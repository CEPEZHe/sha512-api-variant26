# Практическая работа № 2 — вариант 26

**Тема курсовой:** «Веб-приложение с HTTP API для асинхронного вычисления хеш-сумм файлов по алгоритму SHA-512».

Проект реализует три этапа задания для группы ИКБО-70-24: CLI-вычисление SHA-512, HTTP API в XML со стандартным `BaseHTTPRequestHandler`, два слоя хранения (файловый и SQLite через SQLAlchemy ORM) и модельное тестирование Hypothesis `RuleBasedStateMachine`.

## Архитектура

- `src/hashing.py` — потоковое хеширование файла через `hashlib.sha512`, чтение блоками по 64 КиБ; файлы ограничены каталогом `sample_files`.
- `src/cli.py` — утилита командной строки: читает путь к JSON-файлу с заданием и печатает результат в стандартный вывод.
- `src/api.py` — все 11 HTTP-маршрутов варианта 26, валидация обязательных заголовков и XML.
- `src/jobs.py` — очередь задач на `ThreadPoolExecutor` и вызов CLI через `subprocess`; без `--test-mode` вычисление выполняется асинхронно.
- `src/stores.py` — взаимозаменяемые `FileStore` (JSON-файл) и `SQLAlchemyStore` (SQLite ORM).
- `src/client.py` — клиент API с методами, соответствующими маршрутам.
- `src/xml_codec.py` — безопасный разбор плоского XML и сериализация ответов.
- `src/report.py` — отчёт по формуле (26): полное внешнее соединение Query и Feedback после отбора Query за последние 8 минут.
- `tests/test_mbt.py` — генеративная модельная проверка API и слоя хранения для обеих реализаций.
- `scripts/demonstrate_mutation.py` — искусственная ошибка для демонстрации минимизированного контрпримера Hypothesis.

## Требования и установка

Python **3.11+**. Запускайте команды из корня репозитория.

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` включает SQLAlchemy, Hypothesis, coverage, ruff и radon. В Windows можно использовать `py -m ...` вместо `python -m ...`.

## Этап 1 — CLI и четыре примера

Входной файл — JSON вида `{"path": "sample_files/alpha.txt"}`. Выход — JSON в stdout с `path`, `sha512`, `bytes`, `algorithm`.

```bash
python -m src.cli examples/alpha.json
python -m src.cli examples/beta.json
python -m src.cli examples/gamma.json
python -m src.cli examples/empty.json
```

Можно сверить `sha512` с `hashlib.sha512` или `sha512sum` для каждого файла. Отдельные тесты этапа 1:

```bash
python -m unittest tests.test_hashing -v
```

Для безопасности сервер вычисляет контрольные суммы только файлов внутри `sample_files/`; путь с `..` или к постороннему файлу не принимается.

## Этап 2 — HTTP API и файловая СУБД

```bash
python -m src.api --backend file --database data/app.json --port 8000
```

## Этап 3 — SQLite + SQLAlchemy

```bash
python -m src.api --backend sqlite --database data/app.sqlite3 --port 8000
```

Или запустить `run.bat` (Windows) / `bash run.sh` (Linux). По умолчанию скрипты включают SQLite.

Для **детерминированных модельных тестов** сервер создаётся с `test_mode=True`: вместо реального запуска subprocess он немедленно записывает предсказуемый ответ с SHA-512 из 128 нулей. Это *только заглушка*, не результат настоящего хеширования. В обычном режиме задача попадает в пул потоков, а статус запроса изменяется `pending -> done/error`.

Пример вызова создания профиля из Python-клиента при запущенном сервере:

```python
from src.client import APIClient

client = APIClient("http://127.0.0.1:8000")
profile = client.api_profile_add(
    {
        "ip": "127.0.0.1",
        "locale": "ru",
        "platform": "Windows",
        "user_agent": "demo",
    }
)
query = client.api_query_add(
    {
        "profile": profile["key"],
        "parameter": "sample_files/alpha.txt",
        "description": "SHA-512 calculation",
        "tags": "demo",
    }
)
print(query)
print(client.api_query_fetch(query["key"]))
print(client.api_feedback_scan_query(query["key"]))
```

Сразу после `api_query_add` в обычном режиме запись может иметь статус `pending`. Повторите `api_query_fetch`, пока статус не станет `done` или `error`; после этого читайте `Feedback`. Поле `response` содержит JSON-строку с хешем и метаданными.

### Все 11 обработчиков

| Метод | Маршрут | Действие |
|---|---|---|
| POST | `/api/profile/add` | Создать Profile (XML) |
| POST | `/api/profile/scan` | Найти Profile (query string) |
| GET | `/api/profile/fetch` | Получить Profile по `key` |
| PUT | `/api/profile/update/:key` | Изменить Profile (XML) |
| POST | `/api/query/add` | Создать Query, запустить задачу (XML) |
| POST | `/api/query/scan/:profile` | Найти Query профиля |
| GET | `/api/query/fetch` | Получить Query по `key` |
| PUT | `/api/query/update/:key` | Изменить Query (XML) |
| POST | `/api/feedback/scan/:query` | Найти Feedback запроса |
| GET | `/api/feedback/fetch` | Получить Feedback по `key` |
| POST | `/api/report/scan` | Сформировать отчёт формулы (26) |

Все ответы — XML. Обязательные заголовки проверяются по порядку: для POST/PUT `Content-Type: text/xml` (иначе 415), для всех запросов `Accept: text/xml` (иначе 406), затем `Accept-Language: ru` (иначе 406).

## Настоящее MBT: действия генерирует Hypothesis

Тест `tests/test_mbt.py` **не** выполняет единственную фиксированную цепочку операций. Класс `BaseMachine(RuleBasedStateMachine)` имеет независимые правила `add_profile`, `add_query`, `update_profile`, `update_query`, `fetch_profile`, `fetch_query`, `scan_queries`, `scan_feedback`, `fetch_feedback`, `scan_profiles`, `scan_report` и `invariant` для проверки согласованности. Объекты между правилами передаются через `Bundle`; Hypothesis самостоятельно выбирает операции, их параметры и порядок. Ожидаемое состояние живёт в отдельных словарях модели, не в базе сервера. Проверка запускается отдельно с `FileMachine` и `SQLiteMachine`.

```bash
python -m unittest tests.test_mbt -v
```

Отчёт покрытия **только по сгенерированным MBT-тестам** с анализом ветвей:

```bash
python -m coverage erase
python -m coverage run --branch --source=src.api,src.stores,src.jobs,src.report,src.xml_codec,src.client -m unittest tests.test_mbt -v
python -m coverage report -m
python -m coverage html
```

В отчёте проверьте строки и ветви обработчиков API и фактические числа покрытия. Обработчики должны вызываться именно из Hypothesis, без примеси обычных `test_*` в отчёте. Никакое значение процента покрытия заранее не гарантируется — смотрите реальный результат.

### Демонстрация нетривиального контрпримера

```bash
python -m scripts.demonstrate_mutation
```

Команда создаёт сервер SQLite с **искусственной ошибкой**: изменение `tags` одного запроса дополнительно меняет `tags` всех соседних запросов того же профиля. Модель ожидает, что соседние запросы не изменяются. Hypothesis генерирует последовательности правил и пытается уменьшить найденный контрпример; в выводе ищите `Falsifying example` с последовательностью создания профиля, нескольких запросов и обновления одного из них. **Ненулевой код выхода у демонстрации ожидается**, потому что проверка должна найти внедрённый дефект. Если ошибка не обнаружена, скрипт завершится `RuntimeError`.

Самостоятельно покажите преподавателю две команды: успешное прохождение `python -m unittest tests.test_mbt -v` и находку контрпримера в `python -m scripts.demonstrate_mutation`. Сравните, почему без флага `mutation` тот же набор правил проходит.

## Проверка оформления кода

```bash
python -m ruff check src tests scripts --select E,F --line-length 80
python -m radon cc src tests scripts -s
```

Для контроля PEP8 **включите** длину строк, так как по методичке граница — 80 символов:

```bash
python -m ruff check src tests scripts --select E,F --line-length 80
```

Все импорты модулей размещены в начале файлов (не должно быть `E402`); функции изолированы и проектированы без чрезмерной сложности. Перед отправкой проверьте, что нет функций более 40 строк и оценок сложности выше порога преподавателя. Приоритет — действительные результаты инструментов, а не утверждение, будто проверки пройдены без запуска.

## Публикация на GitHub и сдача

В корне репозитория есть `.gitignore`, `README.md`, `src/`, `tests/`, `run.bat`, `run.sh`. Для выполнения требований по истории коммитов сохраняйте этапы работы раздельно, например `feat(cli): add streaming SHA-512 calculator`, `feat(api): add XML endpoints and file backend`, `feat(storage): add SQLite ORM backend`, `test(mbt): add stateful model and mutation demo`. **Не представляйте один финальный коммит как историю поэтапной разработки.**

После публикации откройте README непосредственно на GitHub, нажмите `Ctrl+P` → «Сохранить как PDF». В СДО отправьте **ссылку на публичный GitHub-репозиторий** и **PDF опубликованного README**. Файл `README.md` остаётся в репозитории.

## Ограничения

Приложение — учебное: нет авторизации и загрузки произвольных файлов через HTTP. Оно вычисляет SHA-512 только для уже существующих файлов в `sample_files`. Не выставляйте сервер в публичный интернет. Временные результаты SQLite, JSON-БД, кэш Python, `.coverage` и артефакты тестов не должны попадать в Git.
