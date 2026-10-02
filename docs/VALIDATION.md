# LifeTime 2.0.0 — перевірки релізу

Дата: **2026-10-03** (Europe/Kyiv). Усі перевірки локальні; production БД
та сайт не змінювалися. GitHub Actions workflow доданий, віддалений CI ще
не запускався. Деталі запуску — [OPERATIONS](OPERATIONS.md).

## Поведінка

| Вимога | Доказ |
|---|---|
| HTML/CSS UX, мінімальний JS | Браузер: 320/390/768/1280 px; немає горизонтального overflow сторінки; навігація переноситься, видимий keyboard focus. Перевірено пошук географії, результат, редагування, перемикання мови й Enter. Console без JS/CSP errors. |
| Без JS | HTTP-тести надсилають звичайні HTML-форми без виконання JS; перевіряють native form/formaction, поточні значення й errors. Окреме вимкнення JS у браузерному профілі не виконувалося. |
| Flask/backend | Чисті міграції, readiness, validation/duplicates, leap dates, future dates, beyond-reference, великі numeric aliases, bad Host, nested English404, physical DB isolation, 16 concurrent factories. |
| Дані | Offline rebuild, SHA-256, provenance, coverage/precision/nulls, 225 public geographies, 188 legacy aliases, staged import/idempotency, активація/rollback; немає мережі у розрахунках. |
| SEO | 450 uk/en geography pages, 458 canonical sitemap URL, HTML metadata/H1, JSON-LD parse, XML parse, reciprocal locale links, configured origin, noindex/no-store, legacy redirects/410. |
| Аналітика | HTTP/static/HEAD/error capture, UA/IP/forwarded header spoofing, redaction before storage, trusted edge dedup, 80 threaded + 40 multiprocessing events, bounded locked DB fallback, durable replay, recovery/retention, schema upgrade. |
| Версія | VERSION 2.0.0 у CLI, footer, health/readiness, JSON-LD, package metadata та telemetry; annotated Git tag на release commit. |

## Runtime і збірка

- Windows: Python 3.14.3 у `.venv`; Linux: офіційний Python 3.14.8,
  SQLite 3.46.1, Gunicorn 26.2.0 (2 workers × 4 threads).
- Чисте встановлення runtime і dev locks із `--require-hashes` на Linux,
  `pip check`: без конфліктів. Runtime `pip-audit`: відомих вразливостей
  не знайдено на дату перевірки.
- Ruff check/format, pytest; на Windows і Linux **74 tests + 512 subtests**, успішно.
  Команди — README; тести використовують окремі тимчасові БД.
- `python -m build --no-isolation`: sdist та wheel 2.0.0 збираються.
  Wheel встановлено в ізольований каталог і запущено поза checkout:
  templates/static/translations/migrations на місці, external dataset bundle
  імпортується, `/readyz`, uk/en, sitemap/robots і POST працюють.
- Docker Compose config/build; новий named volume; explicit migrate/import;
  nonroot UID10001, read-only filesystem, writable data volume, Gunicorn
  і healthcheck. Старі SQL/IP logs/secrets не входять до image.
- Backup → restore у новий ізольований каталог зберіг active dataset та
  початкові analytics event IDs; readiness і POST працюють після restore.
  Dataset rollback `old → new → old` та atomic failed import перевірені тестами.
- Nginx 1.31.5-alpine перевірив template через `nginx -t`;
  [EDGE_CHECK.json](EDGE_CHECK.json): 6 request IDs → 6 events, включно
  з HEAD/413/502/504; spoofed headers відкинуто, повторний ingestion без
  дублів, DOB/credentials відсутні в sanitized log та БД.
- Фінальний image `lifetime:2.0.0` зібрано й запущено на loopback 8057;
  browser POST/Enter залишає поточну мову, footer/CLI показують 2.0.0.

## Навантаження й межі

[LOAD_CHECK.json](LOAD_CHECK.json): 100 успішних GET `/en` через 20 clients,
**100 нових подій**, без втрат/дублів. Локальний Docker: 28.01 requests/s,
p50 664.12 ms, p95 976.17 ms, max 1159.51 ms. Це коротка перевірка
конкурентного виконання й persistence, не гарантія production capacity.

TLS/DNS/реальний production proxy, зовнішній monitoring та deployment
scheduler для replay/purge залежать від інфраструктури й потребують
налаштування оператором. Якщо БД і spool-диск одночасно недоступні,
fail-open logger сигналізує втрату; абсолютної гарантії доставки немає.
Bot/suspicious — технічна класифікація, не доказ людини або шахрайства.

## Виправлення за незалежним review

Виправлено переповнення numeric alias; bad Host error rendering;
втрату/застарівання полів при зміні мови; locale unmatched404; видимість
dataset revision і dynamic year; backup metadata race; physical DB alias
isolation; race публікації локального HMAC key; міграцію address_key_id;
мобільну навігацію та native implicit submit locale.

Усі зміни review мають поведінкові regression checks або перевірку браузером.
Сабагенти: Sol/high — reference/domain, analytics, незалежний review;
Sol/medium — UI/HTTP acceptance; координатор — integration/SEO/config/release.
