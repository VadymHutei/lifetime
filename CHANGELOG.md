# Changelog

## 2.0.0 — 2026-10-03

### Сервіс

- Переписано backend на Flask 3.1.3, Python 3.14; factory, SQLAlchemy Core, Alembic та дві SQLite БД.
- Новий адаптивний HTML/CSS інтерфейс у стилі PassGen/GearLog, українська та англійська, мінімальний JS.
- Календарні розрахунки, POST-форма зі збереженням полів, перемикання мови без JS, нормальний результат при перевищенні статистичного орієнтира.
- World Bank WDI 2024: 225 публічних географій, три групи, джерело/рік/ревізія в UI, перевірений ідемпотентний імпорт та активація dataset.
- SEO: локалізовані title/description, canonical/hreflang/OpenGraph/JSON-LD, robots і sitemap; noindex/no-store для результатів та помилок.
- Сумісність старих адрес: 180 зіставлень, 8 explicit unavailable; російська версія та translation editor вилучені (410).
- Аналітика всіх HTTP-запитів, незалежна класифікація, операторські звіти, redaction, HMAC IP, durable spool/replay, retention та sanitized edge ingestion.
- Відтворювані runtime/dev locks, контейнер Python 3.14.8 із pinned digest, непривілейований Gunicorn, Compose, CI та backup/restore інструкції.
- Єдиний VERSION для runtime/package/footer/telemetry, annotated release tag `v2.0.0`.

Перевірки та межі локальної валідації — [docs/VALIDATION.md](docs/VALIDATION.md).
Публікація на production не виконувалася.

### Підготовка

- Проаналізовано вимоги до Flask backend, адаптивного HTML/CSS інтерфейсу, SEO, журналювання запитів і версіонування.
- Зафіксовано українську та англійську локалізації.
- Підготовлено дизайн-бриф за локальними PassGen і GearLog, архітектуру, план реалізації та правила роботи агентів.
- Підготовлено новий демографічний набір із provenance та відтворюваним оновленням; деталі — `docs/DATA_SOURCES.md`.

Підготовчий ідентифікатор був `2.0.0-dev.0`; окремого release-тега для нього немає.

## Legacy — без SemVer-тега

Існуючий застосунок у `app/`, останній коміт до підготовки — `ed623e4` від 2020-04-05. Історичну версію не позначаємо вигаданим номером.
