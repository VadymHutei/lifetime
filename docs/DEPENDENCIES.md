# LifeTime 2.1.0 — середовище й залежності

Дата перевірки: **2026-10-03**. Реалізований стек визначено в `pyproject.toml`; повні resolver locks із SHA-256 — `requirements-lock.txt` та `requirements-dev-lock.txt`. Dockerfile замінено новим runtime. Старий `app/requirements.txt` не використовується.

## Python

Ціль — **Python 3.14.8**, останній стабільний реліз, показаний на [python.org/downloads](https://www.python.org/downloads/) під час перевірки; [сторінка релізу](https://www.python.org/downloads/release/python-3148/) датує його 2026-09-30. Python 3.15 на перевіреній сторінці ще позначений pre-release; запланована дата релізу не є доказом випуску.

Локальний Windows інтерпретатор — Python 3.14.3. Цільовий Linux runtime — Python 3.14.8, SQLite 3.46.1; чисте hashed встановлення runtime/dev locks та запуск контейнера перевірено. Системний Python не змінювався. Офіційний image pinned digest: `sha256:89fb7d3da20043c370643435258bdd7ab755d326d359001d02988ed15ae5219e`. Деталі тестів — VALIDATION.

## Перевірені кандидати

Версії прочитані з публічного JSON API `https://pypi.org/pypi/<package>/json`, поля `info.version`, `info.requires_python`, `releases[version].upload_time_iso_8601`. Усі наведені релізи опубліковані не пізніше дати перевірки. Вебпошук може відставати: наприклад, API вже повертав SQLAlchemy 2.1.2, коли пошукова видача показувала 2.1.1.

| Пакет | Версія | Роль | Дата релізу (UTC) |
|---|---|---|---|
| [Flask](https://pypi.org/project/Flask/3.1.3/) | 3.1.3 | HTTP, шаблони, CLI | 2026-02-19 |
| [SQLAlchemy](https://pypi.org/project/SQLAlchemy/2.1.2/) | 2.1.2 | Доступ до довідкової БД та БД подій | 2026-10-02 |
| [Alembic](https://pypi.org/project/alembic/1.20.0/) | 1.20.0 | Версійовані міграції схеми | 2026-09-11 |
| [python-dateutil](https://pypi.org/project/python-dateutil/2.9.0.post0/) | 2.9.0.post0 | Календарні інтервали, якщо потрібні доменній моделі | 2024-03-01 |
| [Gunicorn](https://pypi.org/project/gunicorn/26.2.0/) | 26.2.0 | Production WSGI у Linux-контейнері | 2026-08-24 |
| [pytest](https://pypi.org/project/pytest/9.1.1/) | 9.1.1 | Тести реалізації | 2026-06-19 |
| [Ruff](https://pypi.org/project/ruff/0.16.10/) | 0.16.10 | Lint/format | 2026-10-01 |
| [pip-audit](https://pypi.org/project/pip-audit/2.10.1/) | 2.10.1 | Перевірка відомих вразливостей lock-файлу | 2026-06-10 |

Перевірені транзитивні залежності Flask: [Werkzeug 3.1.9](https://pypi.org/project/Werkzeug/3.1.9/), [Jinja2 3.1.6](https://pypi.org/project/Jinja2/3.1.6/), [MarkupSafe 3.0.3](https://pypi.org/project/MarkupSafe/3.0.3/), [itsdangerous 2.2.0](https://pypi.org/project/itsdangerous/2.2.0/), [click 8.5.0](https://pypi.org/project/click/8.5.0/), [blinker 1.9.0](https://pypi.org/project/blinker/1.9.0/). Їх та решту транзитивних залежностей має зафіксувати resolver у повному lock-файлі; цей перелік не підміняє resolution.

## Правила реалізації

1. На початку реалізації повторно перевірити stable-релізи. Свіжішу версію приймати після resolution і тестів; не обирати alpha/beta/rc або yanked-релізи автоматично.
2. Створити `.venv` на цільовому Python. Підтримувати явні прямі залежності у `pyproject.toml` і відтворюваний lock із точними версіями та, де підтримано інструментом, hashes. Окремо визначити runtime і dev-групи.
3. Перевірити чисте встановлення, `pip check`, тести, `pip-audit`; зафіксувати перевірені платформу й Python. Metadata `Requires-Python` саме по собі не доводить runtime-сумісність.
4. SQLite постачається з Python; записати фактичну версію `sqlite3.sqlite_version` у діагностиці/CI. Для PostgreSQL/MySQL додавати драйвер лише коли цей deployment-профіль реалізується.
5. Для Linux використовувати мінімальний офіційний Python image, перевірити існування потрібного tag і зафіксувати digest у release. Не переносити старий `tiangolo/uwsgi-nginx-flask:python3.7`.
6. Gunicorn перевіряти в Linux; локальна розробка Windows може використовувати Flask dev server. Dev server не є production-сервером.
7. CSS — звичайний файл, JS — vanilla modules/скрипти за потреби. Node/npm, frontend framework, SCSS-компілятор і bundler не є вимогою проєкту.
8. Секрети та deployment-параметри — environment і `.env.example`; версія сервісу — `VERSION`, не environment. Секретні значення не входять у lock, логи чи документацію.

У 2.1.0 додано [PyMySQL 1.2.3](https://pypi.org/project/PyMySQL/1.2.3/) із extra `rsa`, що встановлює cryptography для сучасної MySQL автентифікації. Версію перевірено 2026-10-03; офіційний реліз від 2026-09-17. Runtime lock містить 17 пакетів, включно з cryptography 50.0.2; tzdata 2026.4 забезпечує Europe/Kyiv у Windows. python-dateutil не знадобився: календарний модуль використовує standard library. pip check та runtime pip-audit пройшли без конфліктів і відомих вразливостей. Lock згенеровано pip-tools 7.6.1.

MySQL перевірено на **8.4.11** (LTS), official image `mysql:8.4` pinned digest `sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242`. Підключення — [SQLAlchemy MySQL dialect](https://docs.sqlalchemy.org/en/21/dialects/mysql.html) та [PyMySQL connection options](https://pymysql.readthedocs.io/en/latest/modules/connections.html). MariaDB/старі MySQL не входили до перевірки.

Оновлення lock (після перевірки stable-релізів і тестів):

```sh
python -m piptools compile pyproject.toml --generate-hashes --strip-extras --output-file requirements-lock.txt
python -m piptools compile pyproject.toml --extra dev --allow-unsafe --generate-hashes --strip-extras --output-file requirements-dev-lock.txt
```

Встановлення: `python -m pip install --require-hashes -r requirements-dev-lock.txt`.
Для runtime використовуйте `requirements-lock.txt`. Наявні hashes не заміняють поведінкових тестів і vulnerability audit.
