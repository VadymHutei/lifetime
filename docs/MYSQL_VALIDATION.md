# LifeTime 2.1.0 — перевірка MySQL

Дата: 2026-10-03. Production credentials, сервер і дані не використовувалися.
Середовище: офіційний MySQL **8.4.11**, strict SQL mode та ONLY_FULL_GROUP_BY;
PyMySQL **1.2.3** з RSA extra; Python **3.14.3 / Windows** і **3.14.8 / Linux**.

## Перевірені сценарії

- Повний набір: **107 tests + 534 subtests** успішно на Windows і Linux,
  із реальною MySQL через `TEST_MYSQL_URL`, без пропуску MySQL integration tests.
- Reference: повний імпорт 295 entities / 885 observations; точний roundtrip
  усіх значень і 93 null; 225 public locations; FK/CHECK; idempotency;
  staged activation `old → new → old`; atomic rollback невдалого імпорту.
- MySQL `DOUBLE` зберігає початкову точність показників; BIGINT підтримує
  великі response sizes і daily counters. Таблиці використовують InnoDB/utf8mb4;
  окремий тест підтвердив це навіть за server/session defaults MyISAM/latin1.
- Одна MySQL БД містить обидва набори таблиць та незалежні Alembic histories:
  `reference_0002` і `analytics_0003`. Повторні міграції не змінюють дані.
- Factory не підключається до БД автоматично; явні CLI migrate/import працюють.
  HTTP uk/en, POST, errors, legacy redirects/410, 458 sitemap URLs та metadata
  перевірено на MySQL; 11 запитів → 11 analytics events без DOB.
- 120 конкурентних INSERT, 40 конкурентних app/edge merges → один event;
  справжній row lock → bounded timeout → durable spool → idempotent replay.
  Недоступний сервер дає readiness503 та spool, без падіння logger.
- Retention: batches по 1000 rows, 1050-row test, parallel purge 1250 rows,
  64-bit counters та backdated insertion race — без втрат/подвоєння агрегатів.
- Паролі зі спеціальними символами зберігаються в URL object без ручного
  escaping. Production MySQL вимагає password; repr URL маскує його.
  `DB_SSL_CA` використовує стандартний verified SSLContext; production
  certificate/hostname потрібно перевірити зі справжнім сервером перед deployment.
- SQLite compatibility tests проходять. MySQL-only зміни початкових міграцій
  не змінюють SQLite DDL; forward migrations не звужують уже записані числа.

## Контейнер і operations

Hashed runtime/dev locks встановлюються на Linux; `pip check`, Ruff check/format
і runtime `pip-audit` успішні, відомих вразливостей не знайдено на дату перевірки.
Wheel і sdist **2.1.0** збираються; нові міграції включені в wheel.

`compose.yaml` працює із зовнішнім MySQL; `compose.mysql.yaml` додає окремий
локальний сервер з volume без публічного DB port. Локальний preview запущено
на **127.0.0.1:8057**, MySQL БД `lifetime_preview`, 225 доступних географій;
readiness і footer підтверджують **2.1.0**. Перевірено реальний
`reference_engine.dialect.name == mysql` та server version8.4.11.

Backup/restore репетиція офіційним mysqldump8.4.11 —
[MYSQL_BACKUP_CHECK.json](MYSQL_BACKUP_CHECK.json): нова source DB → dump →
інша нова restore DB. Dataset id, counts і event id збережено; views посилаються
на відновлену БД, readiness та POST повернули200. Обидві disposable БД
після перевірки видалені. Production не зачіпався.

CI workflow доповнено справжньою MySQL service і MySQL container smoke;
віддалений GitHub Actions run ще не виконувався.

## Запуск тестів

Установіть dev lock. `TEST_MYSQL_URL` має вказувати **тільки** на disposable
database `lifetime_test`; QA account потребує створення/видалення ізольованих
тестових БД. Без цієї змінної тести реального MySQL пропускаються, решта працює.
Не задавайте production URL: analytics QA очищує свої тестові таблиці.

```sh
python -m pytest -q
python -m ruff check lifetime migrations scripts tests
python -m ruff format --check lifetime migrations scripts tests
```

Доступи production налаштовує оператор пізніше за [MYSQL.md](MYSQL.md).
SQLite чи legacy logs автоматично не копіюються в MySQL.
