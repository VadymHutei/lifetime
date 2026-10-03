# LifeTime — правила роботи агентів

## Межі й стан

- Спілкуйся з користувачем українською. Працюй у цьому repository; PassGen/GearLog — read-only референси, якщо немає окремого запиту на їх зміну.
- Прямі вимоги користувача мають пріоритет. Контракт підготовки: `docs/V2_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN_BRIEF.md`, `docs/DATA_SOURCES.md`, `docs/DEPENDENCIES.md` та README.
- Реалізовано `2.1.0` із MySQL за прямим запитом користувача: runtime у `lifetime/`, міграції у `migrations/`, запуск/операції — README, `docs/OPERATIONS.md`, `docs/MYSQL.md`; перевірки — `docs/VALIDATION.md` та `docs/MYSQL_VALIDATION.md`. Legacy живе в `app/`, кореневих SQL та `db/` і не входить у runtime image.
- Перед змінами перевіряй `git status`; не стирай роботу користувача/інших агентів. Нові гілки, якщо потрібні, — `codex/<topic>`. Не створюй release tag до готовності релізу.

## Продукт та інтерфейс

- Flask і Jinja, семантичний HTML, звичайний адаптивний CSS, мінімальний vanilla JS. Не вводь frontend framework, SPA, bundler або обов'язковий Node toolchain.
- Мови — українська `uk` та англійська `en`; типова `uk`. Кольори, відступи й компоненти — за DESIGN_BRIEF, стилістика PassGen/GearLog.
- Основна POST-форма й навігація працюють без JS. Поля мають label, видимі defaults, збереження введеного при помилках, inline validation, keyboard focus. Перевіряй 320 px і desktop.
- Візуалізація статистичного сценарію не є особистим прогнозом смерті. Джерело, рік та група показуються біля значень. Перевищення середнього показника не створює негативного «залишку життя».
- Дата народження не додається в нові URL, telemetry, localStorage чи БД результатів за замовчуванням. Legacy GET result обробляється сумісно, із noindex/no-store і redaction.

## Backend

- Новий пакет — `lifetime/` із `create_app()`, services, repositories, routes, analytics, templates/static та CLI. Доменні розрахунки не залежать від Flask, SQL чи мережі.
- Clock / today передавай явно; «сьогодні» — Europe/Kyiv, часові мітки журналу — UTC. Використовуй календарні дати, а не сталий 31-денний місяць.
- SQLAlchemy Core + Alembic + PyMySQL; основний профіль — MySQL 8.4 LTS, одна БД, окремі reference/analytics таблиці та migration version tables, незалежні pools. InnoDB, utf8mb4, READ COMMITTED, короткі транзакції й bounded timeouts. SQLite — явна локальна сумісність через DB_BACKEND=sqlite (дві БД/WAL). Міграції/імпорт — окремий CLI, не при import модуля або HTTP-запиті.
- MySQL fields DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD складаються через URL.create, не string interpolation. Секрети не друкуй. DB_SSL_CA вмикає перевірений TLS; не вимикай перевірку сертифіката. MySQL тести працюють лише через TEST_MYSQL_URL із disposable lifetime_test, не production.
- Переклади — version-controlled файли. Не відновлюй `/translations` з admin_key у query чи мутації через GET.
- Параметризований SQL, allowlist для dynamic order/identifier, explicit transaction ownership. Тести використовують окремі тимчасові БД, ніколи production.
- Залежності перевіряй за офіційними stable-релізами, фіксуй resolver/lock після чистого встановлення. Не підміняй lock таблицею версій із документації. Точний baseline — DEPENDENCIES.

## Демографічні дані

- Канонічний prep dataset — `data/life_expectancy/`; raw responses, manifest/hashes, entity policy і legacy aliases утворюють один узгоджений набір.
- Оновлюй дані скриптом `scripts/update_life_expectancy.py`, не редагуй numeric values вручну. Зміни політики geography/mapping мають бути явними та перевіреними.
- WDI provider code не завжди ISO. Зберігай country/territory/area/aggregate та aggregate_type; source definitions мають пріоритет над схожістю назв.
- Роки не змішуються мовчки; missing — null із причиною, ніколи 0. Total береться з окремого indicator, регіон — із provider aggregate. Не усереднюй sexes/countries самостійно.
- Dataset import: hashes, schema, unique/FK/range/coverage checks, transaction, staged activation, rollback. Програма не звертається до World Bank під час користувацького розрахунку.
- Непідтверджені legacy aliases не підміняй близькою географією. Для 8 `retained_unavailable` — сторінка 200 із поясненням, noindex і поза sitemap; нове ручне зіставлення потребує перевіреного еквівалента. Невідомі поза mapping — 404.
- Старі SQL dumps мають дві несумісні схеми та історичні логи; не запускай усі seeds і не використовуй historical IP logs як нову аналітику. Перед зміною live DB потрібні перевірені backup/restore і міграція.

## Статистика запитів

- Validity, client class, security class і HTTP outcome — незалежні поля. 404 не доводить bot, browser UA не доводить human, claimed crawler не дорівнює verified crawler.
- Один HTTP request — один event id; окремі views/CLI reports для valid/bot/invalid/suspicious. Перетини звітів описуються явно.
- Capture охоплює нормальні відповіді, static, HEAD, redirects, 400/404/405/500. Reverse proxy має forwarding/request-id/edge-ingestion контракт для запитів, що не дійшли до Flask.
- Зберігання: короткий INSERT, durable spool fallback, ідемпотентний replay. Logger fail-open, без recursion; невідновні втрати мають dropped-event сигнал. Не використовуй тільки in-memory queue.
- Redaction виконується до DB/spool/edge log: не зберігай DOB, credentials, cookies, body, raw query/Referer. Bounded path/UA, CRLF stripping, IPv6. Не довіряй forwarded headers від довільного клієнта.
- Retention configurable, raw-IP opt-in з короткою retention; типово HMAC token. Звіти операторські, не публічні. Класифікація не запускає автоматичне блокування.

## SEO та версія

- Canonical/hreflang/sitemap будуй з configured `SERVICE_URL`, а не `request.host`. Production URL HTTPS; uk/en reciprocal links, правдивий JSON-LD через serializer, один H1, природні унікальні тексти.
- Sitemap містить лише indexable canonical 200 URL й реальний lastmod. Result/error/retired routes — noindex; noindex не підміняється robots Disallow.
- `/ukr`/`eng` public → відповідні uk/en 301, `/rus/**` → 410 із доступними мовами; legacy result окремо. Не перенаправляй невідомі країни на world мовчки.
- `VERSION` — єдине джерело SemVer, у тому числі prep prerelease. Footer, CLI, package metadata, JSON-LD і telemetry читають його. Dataset має незалежну версію.
- Фінальні SemVer-релізи й annotated Git tags `vMAJOR.MINOR.PATCH` — лише після acceptance, на release commit. Підтримуй CHANGELOG. Push/deployment — у межах запиту користувача.

## Сабагенти

- Підготовку й реалізацію v2 дозволено розділяти між сабагентами згідно з прямим запитом користувача. План моделей і рівнів — V2_PLAN; максимум координатор + 3 активні агенти.
- Давай вузьке завдання, ownership файлів, interfaces і критерії. Не редагуйте однакові файли одночасно. Координатор відповідає за shared config/factory/dependencies/VERSION/README/AGENTS і інтеграцію.
- Sol/high — domain/data/analytics/review; Sol/medium — UI; Luna/high — обмежені reference/content/SEO задачі з перевіркою. Використовуй доступний еквівалент, якщо модель недоступна.

## Перевірки

Команди з кореня після встановлення dev lock:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check lifetime migrations scripts tests
.venv\Scripts\python -m ruff format --check lifetime migrations scripts tests
.venv\Scripts\python -m pip check
.venv\Scripts\python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
.venv\Scripts\python scripts/update_life_expectancy.py --offline --as-of 2026-10-03 --year 2024
git diff --check
```

Offline rebuild має відтворювати узгоджений snapshot без зміни retrieval timestamp. Онлайн update перевіряє новий набір перед заміною старого; для нового періоду задавай `--as-of` та `--year` явно, перевіряй відмінності і coverage. Команди та фактичні результати описані в README/DATA_SOURCES.

Виконуй Python-команди через `.venv` (`.venv/Scripts/python.exe` на Windows, `.venv/bin/python` на Linux). Наявні поведінкові тести календаря, імпорту, HTTP/SEO, конфігурації, класифікації, redaction, concurrency, spool/replay і версій. Після UI змін — браузер desktop/mobile/keyboard і server-form без JS; після Docker — compose validation/build/start/HTTP smoke. Не видавай невиконані перевірки за пройдені й не запускай повний набір повторно без нових змін або ризиків.
