# LifeTime

**2.0.0** — сервіс статистики тривалості життя та порівняння з уже прожитим
часом. Flask/Jinja, адаптивні HTML/CSS, мінімальний vanilla JS. Українська та
англійська; темний інтерфейс у стилі PassGen/GearLog. Основна форма, повторний
розрахунок і перемикання мови працюють без JavaScript.

Статистика населення **не прогнозує тривалість життя конкретної людини**.
Результат показує календарний вік, прожиті дні/тижні та статистичний орієнтир,
без «дати смерті». Дата народження не записується в БД або аналітику.

## Запуск

Python **3.14**, цільовий контейнер — **3.14.8**. Команди нижче — PowerShell,
із кореня repository. На Linux використовуйте `.venv/bin/python`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements-dev-lock.txt
.venv\Scripts\python -m flask --app lifetime migrate
.venv\Scripts\python -m flask --app lifetime import-data
$env:SERVICE_URL = 'http://127.0.0.1:8057'
.venv\Scripts\python -m flask --app lifetime run --host 127.0.0.1 --port 8057
```

Відкрийте <http://127.0.0.1:8057/uk>. `migrate` створює дві БД у `instance/`,
`import-data` перевіряє snapshot і активує його. HTTP-запити не виконують
міграцій, імпорту чи зовнішніх API-запитів. Повторний імпорт ідемпотентний.
Flask dev server призначений для локальної розробки; його стандартний access
log може містити query strings legacy-запитів, тому не використовуйте його
як публічний production server.

```powershell
docker compose build
docker compose run --rm app flask --app lifetime migrate
docker compose run --rm app flask --app lifetime import-data
docker compose up -d
```

Контейнер запускає Gunicorn від непривілейованого користувача. Дані зберігаються
в локальному persistent volume. Порт доступний лише через loopback.
Конфігурація — environment; Flask самостійно не читає `.env`. Compose читає
значення `.env` для підстановки; приклад — [.env.example](.env.example).
Для production потрібні HTTPS `SERVICE_URL`, довгий `ANALYTICS_SECRET`,
налаштований reverse proxy та точні trusted proxy CIDRs.

Повні інструкції запуску, backup/restore, rollback, retention та edge ingestion —
[OPERATIONS.md](docs/OPERATIONS.md).

## Дані й оновлення

Джерело — [World Bank WDI](https://data.worldbank.org/indicator/SP.DYN.LE00.IN),
випуск **2026-07-13**, спільний рік показників — **2024**. Публічно доступні
**225 географій**: 217 країн/територій/статистичних areas, світ і сім регіонів.
Окремі показники: `SP.DYN.LE00.IN` (загалом), `SP.DYN.LE00.FE.IN` (жінки),
`SP.DYN.LE00.MA.IN` (чоловіки). Total і регіони взяті з відповідних показників
джерела; сервіс не обчислює їх як середнє значень країн чи груп.

`data/life_expectancy/` містить snapshot, manifest, SHA-256, policy, legacy
aliases та сім оригінальних API responses. Повний набір: 295 об'єктів,
885 observations, 792 значення і 93 явні пропуски в додаткових агрегатах.
У публічних географій усі три показники доступні. Рік, джерело, випуск і
незалежна ревізія dataset показуються в інтерфейсі.

```powershell
# Відтворення з уже збережених відповідей, без мережі:
.venv\Scripts\python scripts/update_life_expectancy.py --offline --as-of 2026-10-03 --year 2024
# Після перегляду diff та проходження тестів:
.venv\Scripts\python -m flask --app lifetime import-data --path data/life_expectancy
.venv\Scripts\python -m flask --app lifetime activate-data DATASET_ID
```

Для завантаження свіжого джерела приберіть `--offline`, задайте актуальний
`--as-of` і перевірений спільний `--year`. Скрипт працює з repository checkout,
використовує старий довідник для відтворюваних aliases; перед оновленням
перевіряйте coverage та зміни географій. Wheel встановлює програму; зовнішній
перевірений bundle можна імпортувати через `--path`.

Методологія, ліцензія **CC BY 4.0**, обмеження оцінок/проєкцій, зміни регіонів
та особливості українських даних — [DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Аналітика й приватність

Окрема SQLite БД зберігає HTTP-події: успішні запити, redirects, static, HEAD
і помилки. Validity, client class, security class та HTTP outcome — незалежні
ознаки. Browser UA не доводить, що це людина; crawler UA означає лише
`claimed_bot`. Автоматичного блокування чи перевірки crawler через мережу немає.

```powershell
.venv\Scripts\python -m flask --app lifetime analytics report --group valid
.venv\Scripts\python -m flask --app lifetime analytics report --group bots
.venv\Scripts\python -m flask --app lifetime analytics report --group suspicious
.venv\Scripts\python -m flask --app lifetime analytics report --group overview
.venv\Scripts\python -m flask --app lifetime analytics replay
.venv\Scripts\python -m flask --app lifetime analytics purge
```

Вибірки `valid`, `bots`, `invalid`, `suspicious` можуть перетинатися;
`overview.matrix` розбиває події на взаємовиключні групи. Query values, body,
DOB, credentials та довільні частини path видаляються **до** DB/spool.
IP замінюється keyed HMAC, raw IP — лише explicit opt-in. Типова retention:
події 90 днів, raw IP 7, денні агрегати 365. `purge` потрібно запускати
оператором регулярно; він не виконується під час HTTP-запитів.

При недоступній БД працює durable spool і ідемпотентний replay. Якщо одночасно
недоступні БД і диск, подія може бути втрачена; є stderr-сигнал `dropped_event`.
Для відхилених proxy запитів потрібен [sanitized nginx log](deploy/nginx.conf)
та `analytics ingest-edge`. Edge-only події не містять IP/HMAC. Детальні межі
capture, dedup і ротація описані в operations. Публічної адмінпанелі немає.

## URL, SEO та версії

- `/uk`, `/en`, `/countries`, сторінки географій, `/methodology`, `/privacy`
  під відповідним мовним префіксом. Один H1, локалізовані metadata,
  configured canonical, reciprocal hreflang, OpenGraph та JSON-LD.
- `/robots.txt`, `/sitemap.xml`: лише canonical indexable сторінки;
  результати та помилки мають noindex/no-store.
- `/ukr`, `/eng` → 301 до сучасних URL; legacy GET result обробляється без
  redirect із DOB. `/rus/**` і `/translations*` → 410.
- Усі 188 legacy записів враховано: 180 зіставлень і 8 сторінок із поясненням
  недоступності даних, без підміни географії, noindex, поза sitemap.
- `VERSION` — єдине джерело версії footer, CLI, package, JSON-LD та analytics.
  Релізи мають annotated Git-теги `vMAJOR.MINOR.PATCH` і [CHANGELOG](CHANGELOG.md).

## Перевірки й структура

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check lifetime migrations scripts tests
.venv\Scripts\python -m pip check
.venv\Scripts\python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
git diff --check
```

Новий runtime — `lifetime/`; окремі міграції — `migrations/reference/` та
`migrations/analytics/`. `app/`, старі SQL і `db/` залишені як історичні
матеріали й не входять у runtime image. Не імпортуйте історичні IP logs.

Контракти: [AGENTS](AGENTS.md), [план](docs/V2_PLAN.md),
[архітектура](docs/ARCHITECTURE.md), [дизайн](docs/DESIGN_BRIEF.md),
[залежності](docs/DEPENDENCIES.md), [результати перевірок](docs/VALIDATION.md).
Код — [MIT](LICENSE). Дані мають окрему ліцензію джерела.
