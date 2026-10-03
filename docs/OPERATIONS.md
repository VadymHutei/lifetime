# LifeTime: запуск, журнал і відновлення

Версія 2.1.0: основна БД — MySQL 8.4 LTS через PyMySQL, конфігурація `DB_*` у `.env`; креди production задає оператор перед запуском. Одна MySQL БД містить окремі reference/analytics таблиці. Контейнер: Python 3.14.8-slim з pinned digest, Gunicorn (2 workers × 4 threads), UID/GID `10001`, persistent volume `/var/lib/lifetime` для spool/ключа. Міграції та імпорт — явні операторські команди. Startup і HTTP їх не запускають. Legacy `app/`, SQL dumps, історичні IP logs, робочі БД і `.env` виключені з image.

## Локальний Docker

Потрібен Docker Compose з optional `env_file` (2.24+). Скопіюйте `.env.example` у `.env` і налаштуйте доступ до MySQL, створену БД та користувача. HTTP доступний на loopback `127.0.0.1:8057`. Нижче команди для зовнішнього сервера; локальна MySQL запускається додатковим `-f compose.mysql.yaml`, як описано в README. Профіль SQLite тепер потребує явного `DB_BACKEND=sqlite`.

```sh
docker compose config --quiet
docker compose build
docker compose run --rm app flask --app lifetime migrate
docker compose run --rm app flask --app lifetime import-data
docker compose up -d --wait
curl --fail http://127.0.0.1:8057/readyz
curl --fail http://127.0.0.1:8057/uk
docker compose run --rm app flask --app lifetime version
```

`/healthz` підтверджує процес; `/readyz` — reference schema й активний snapshot. Container healthcheck використовує readiness. Не видаляйте production volume через `down --volumes`.

## Production і proxy

Перед production стартом задайте `ENVIRONMENT=production`, справжній HTTPS origin `SERVICE_URL` без path/query та `ANALYTICS_SECRET` (щонайменше 32 символи). `LIFETIME_IMAGE` обирає immutable release image. Секрет генерується окремо і зберігається у захищеному deployment environment, не в Git. При bind mount власник data directory — `10001:10001`; named volume успадковує owner image directory. SQLite volumes локальні: не NFS та не незалежні replicas. Зберігайте HMAC secret разом з контрольованими backup secrets для порівнянності адресних токенів.

[deploy/nginx.conf](../deploy/nginx.conf) — optional template у контексті nginx `http` (наприклад `conf.d/default.conf`). Створіть захищений writable каталог `/var/log/lifetime` до старту nginx. Upstream `app:8000` доступний тільки proxy у приватній Docker мережі. TLS забезпечує production ingress. `TRUSTED_PROXY_CIDRS` має містити лише фактичний socket peer proxy. Edge переписує `X-Forwarded-For` одним client IP та генерує `X-Request-ID`; клієнтські forwarding headers/request id ігноруються. Application port не відкривайте назовні.

Static, robots і sitemap проходять WSGI capture. Sanitized proxy JSONL додатково охоплює HTTP 413/502 та інші edge-only відповіді. Для edge-only немає IP token: стандартний nginx не обчислює HMAC, а raw IP не пишеться. UA — coarse browser/crawler class; query values, body, cookies, credentials і Referer відсутні. Невідомі paths редагуються. Стандартні nginx error/access logs можуть містити DOB в URL, тому template вимикає raw error logs і замінює access log безпечним JSONL. Gunicorn access logs вимкнені; server warnings з malformed request lines приглушені. Використовуйте sanitized status/outcome, process/container diagnostics та infrastructure monitoring. DNS/TLS/network failure до HTTP не є Flask event.

Якщо edge volume змонтовано до app як `/var/lib/lifetime/edge`, операторські команди:

```sh
docker compose run --rm app flask --app lifetime analytics ingest-edge /var/lib/lifetime/edge/edge.jsonl
docker compose run --rm app flask --app lifetime analytics replay
docker compose run --rm app flask --app lifetime analytics purge
docker compose run --rm app flask --app lifetime analytics report --group overview
docker compose run --rm app flask --app lifetime analytics report --group bots --limit 100
```

Ingestion/replay ідемпотентні за request/event id. Edge final status доповнює app annotation без подвійного count. Ротуйте JSONL з reopen nginx (`nginx -s reopen`), імпортуйте завершений файл, перевіряйте summary і тільки потім видаляйте його; **edge files не входять до автоматичного DB purge**. Не залишайте паралельний default raw log. Raw IP для app вимкнений типово; opt-in `ANALYTICS_STORE_RAW_IP=true` потребує короткої retention й операторського доступу.

`valid`, `bots`, `invalid`, `suspicious` — незалежні вибірки з перетинами; їх counts не складаються. Overview matrix взаємовиключна. Browser UA має `unknown`, crawler UA — `claimed_bot`; автоматичного блокування або мережевого crawler verification немає. Ruleset/reasons збережені. Мітка не доводить, що відвідувач є людиною або шахраєм.

Планувальник deployment запускає `replay` регулярно та `purge` щодня. Defaults: detailed events 90 днів, opt-in raw IP 7, агрегати 365. `ANALYTICS_RETENTION_DAYS=0` вимикає detailed capture; `ANALYTICS_RAW_IP_DAYS=0` — raw IP; `ANALYTICS_AGGREGATE_DAYS=0` — aggregate retention. Daily report містить згорнуті expired events; поточні detailed — в overview. Spool: атомарні `0600` файли, flush/fsync; abandoned claims/partial files обробляються після 300 секунд. `dropped_event` у stderr і process metric сигналізують втрати при одночасній відмові DB/disk. Logger fail-open, відповідь сайту не змінюється. Purge при недоступній DB очищує expired spool і повертає `database_failed=1` — потрібен оператор. Process counters reset при рестарті; централізуйте stderr monitoring, це не глобальна durable метрика.

## Backup, restore, rollback

Для MySQL використовуйте `mysqldump --single-transaction` із захищеним option file;
повна процедура backup/isolated restore та мінімальні права — [MYSQL.md](MYSQL.md).
`flask backup` підтримує лише SQLite й відхиляє MySQL до створення destination.
Зміна DB_BACKEND не копіює старі SQLite logs або legacy MySQL таблиці.

Наведений нижче файловий backup застосовується лише до SQLite compatibility profile.

Перед міграцією збережіть image digest, VERSION і active dataset id. Backup використовує SQLite backup API, включаючи committed WAL contents:

```sh
docker compose run --rm app flask --app lifetime backup /var/lib/lifetime/backups/pre-upgrade
```

Destination має бути новим. Результат: `reference.sqlite3`, `analytics.sqlite3`, `metadata.json`. Це окремі узгоджені SQLite snapshots; shared transaction/FK між ними немає. Окремо збережіть spool і HMAC secret. Для одного контрольованого restore point зупиніть writers/edge ingestion перед backup і копіюванням spool. Зовнішні копії зберігайте захищено з retention: backup може містити opt-in raw IP й успадковує privacy policy.

Restore — у **новий ізольований каталог/volume** при зупинених writers. Відновіть SQLite snapshots, spool і secret, owner `10001:10001`; запустіть попередній image, перевірте `/readyz`, калькулятор і reports. Не підміняйте live files на працюючому контейнері, не переносіть старі `-wal`/`-shm` до database snapshot. CLI не має in-place restore. До production change відрепетируйте цей процес на staging.

Для rollback лише даних, без schema downgrade:

```sh
docker compose run --rm app flask --app lifetime activate-data DATASET_ID
docker compose restart app
```

Dataset id беріть з backup metadata чи import output. App/schema rollback використовує попередній immutable image й перевірений compatible backup. Legacy MySQL migration потребує окремого backup/export фактичної схеми; несумісні legacy seeds і historical IP logs у нові БД не імпортуються.

## Перевірено під час реалізації

Для MySQL 2.1.0 актуальні результати — [MYSQL_VALIDATION.md](MYSQL_VALIDATION.md)
та [MYSQL_BACKUP_CHECK.json](MYSQL_BACKUP_CHECK.json). Нижче — базові перевірки,
виконані під час створення 2.0.0.

Docker Compose config, official Python image pull, Linux runtime install із hashes і `pip check`, nonroot image build, міграції/імпорт до окремого validation volume, Gunicorn start та container readiness пройшли локально. Nginx 1.31.5-alpine `nginx -t` підтвердив template після підготовки log directory. Подальші зміни runtime/VERSION потребують нового image build. CI workflow визначений у repository; факт його додавання не означає запуск GitHub Actions.

Фактичний короткий load smoke: 100 GET `/en`, 20 clients, 100 нових events без дублів; близько 28 requests/s, p50 664 ms, p95 976 ms у локальному Docker. Це перевірений малий envelope, не гарантія capacity. Вимірювання — [LOAD_CHECK.json](LOAD_CHECK.json). Фактичний optional nginx smoke підтвердив 200/HEAD, edge-only 413/502/504, spoofed headers override, 6 request ids → 6 events, повторний ingestion без додаткового count і redaction у JSONL/БД: [EDGE_CHECK.json](EDGE_CHECK.json).
