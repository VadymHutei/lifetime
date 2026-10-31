# Аудит безпеки LifeTime — 2026-10-31

Реліз виправлень: **2.1.1**. Перевірено tracked files, усі доступні Git refs,
runtime/dev locks, Flask routes/config, SQL boundary, analytics redaction,
Docker/Compose/CI та фактичну production конфігурацію VPS.
Секретні значення, історичні IP та raw scanner output до звіту не включені.

## Знахідки та виправлення

| Знахідка | Доказ і ризик | Виправлення |
| --- | --- | --- |
| Приватна legacy DB-конфігурація в Git-історії | Чотири версії `app/config.py` містили literal DB password; файл давно видалений із HEAD. Чинність старого account не встановлена. | За прямим дозволом власника файл вилучається з історії всіх опублікованих гілок і локальних release tags; старі credentials слід відкликати на колишньому сервері. |
| Історичні IP-логи в SQL | `db_data.sql`: 637 IPv4 occurrences; `db/db_log.sql`: 142. Це дані запитів, а не демографічний довідник. | Вилучено цілі `INSERT INTO log` із поточних файлів та історії; schema й довідник збережені. Privacy guard забороняє повторний коміт таких rows. |
| Вразливі dev dependencies | `certifi 2026.7.22`, `filelock 4.0.9`, `setuptools 84.0.0`: 16 advisory records, із них один duplicate certifi record. Runtime lock до змін — без відомих advisories. | Resolver locks оновлено з SHA-256; certifi 2026.10.23, filelock 4.2.5, setuptools 84.2.1. Обидва повторні audits — clean. |
| Застарілий Python image | Runtime 3.14.8; 3.14.10 є security release. | Python 3.14.10-slim із verified immutable digest; MySQL також оновлено в межах LTS до 8.4.13. |
| Непідтримуваний legacy dependency manifest | `app/requirements.txt` пропонував Flask 1.1.1, старі Jinja2/PyMySQL/Werkzeug тощо, хоча `app/` не розгортається. | Manifest вилучено, `app/README.md` явно забороняє запуск legacy. Підтримуваний runtime описано тільки в root pyproject/locks. |
| Неповна CI перевірка supply chain | CI аудіював лише runtime, actions були mutable tags. | Audit обох locks, Gitleaks із checksum і redaction, tracked-file privacy guard, tests, Dependabot; actions pinned commit SHA. |
| Неправильні права вкладених каталогів image | Whitelist archive, розпакований з umask 077, давав root-owned 0700 каталоги. QA через recursive chown маскував їхню недоступність runtime user. | Dockerfile явно нормалізує тільки public runtime files/directories через `u=rwX,go=rX`; QA більше не змінює runtime ownership. Перед deploy перевіряється factory і повний snapshot від non-root без network. |

Advisories dev lock: certifi
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
setuptools [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w),
filelock — 13 CVE entries, що виправляються починаючи з 4.2.1;
встановлено новіший stable 4.2.5.
Поточні версії та hashes — у locks, а не в advisory counts.

[Python 3.14.10](https://www.python.org/downloads/release/python-31410/)
виправляє, зокрема, довіру до compromised CA keys і обробку links у tarfile.
[MySQL 8.4.13](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-4-13.html)
випущено 2026-10-20. Оновлення на іншу major-гілку Python/MySQL не виконувалося.

## Дані та приватність

Очищення SQL змінює тільки `legacy_input_sha256` у dataset manifest.
Offline updater реально відтворив bundle: `snapshot.json`, aliases, numeric
values, source year/release, raw hashes та retrieval timestamp не змінилися.
Ідентичність dataset залежить від усього manifest, тому provenance revision
стає `b6f5d7b916c784ffee8078f1b59a0ab86d4124c6c0bf969f74a3ad9435aa2d34`.
`db_data.sql` отримав `-text` Git attribute для byte-stable checksum на Windows/Linux.

Tracked export із поточними змінами: Gitleaks 8.30.1 — 0 findings.
Початковий history scan охопив 125 commits і також дав 0 findings, але ручна
перевірка виявила короткий пароль. Це демонструє обмеження entropy/token scan.
Локальна `.artifacts/db-access/lifetime-desktop.cnf` містить чинний секрет
за призначенням, ігнорується Git та не передавалася до release archive.
Файли `.env`, ключі SSH, working databases та backup не знайдено серед
поточних tracked files. Python wheel/sdist 2.1.1 перевірено: без app/SQL/private files.

## Runtime та VPS

Ручний перегляд і поведінкові тести підтверджують parameterized SQL,
Jinja autoescape/JSON serialization, bounded form input, generic error
responses, noindex/no-store результатів, CSP, no-referrer, точні trusted proxy
CIDRs, redaction до DB/spool/edge та fail-open logging. Калькулятор не має
session/account mutation; публічного admin API немає. DOB не зберігається.

На VPS перед upgrade: debug/raw IP вимкнені, DB/HMAC secrets окремо згенеровані
по 64 символи, `.env` mode 0600, state/backups/certificates 0700. App — non-root,
read-only filesystem, без capabilities. App/MySQL ports не публікуються;
DB access socket — лише loopback 127.0.0.1:3307 із SSH. UFW відкриває 22/80/443.
Maintenance/backup/purge/renew timers активні. Kyiv Alert має окремі мережі.

Початковий backup `/opt/lifetime/backups/20261030T235859-37744` успішно
відновлено в окремому тимчасовому MySQL: checksums, 885 observations,
225 публічних географій, обидві schema revisions, GET/POST та analytics/replay.
Backup виконувався з `BACKUP_PRUNE=false`; наявні копії не видалялися.

## Фактичні перевірки

- Windows Python 3.14.3: 84 passed, 22 MySQL skips, 518 subtests passed;
  concurrent-key test заблокував sandbox WinError 5, окремо поза sandbox — passed.
- Linux Python 3.14.10 + disposable MySQL 8.4.13: 104 passed, 532 subtests passed;
  3 тести та 2 subtests упали через hardcoded 2.1.0. Після переходу assertions
  на VERSION зачеплений MySQL suite і нові privacy tests — **7 passed,
  11 subtests passed**. Успішні незачеплені тести повторно не запускалися.
- Hashed clean Linux runtime/dev install, pip check, Ruff check/format — passed.
- Runtime/dev pip-audit — no known vulnerabilities; pip outdated — `[]`.
- Offline dataset rebuild та checksums — passed; wheel/sdist build — passed.
- Нові repository privacy regression tests локально — 2 passed.

## Межі та подальші дії

Очищення Git не відкликає credentials, не видаляє сторонні clones/forks,
GitHub pull-request refs, caches чи вже завантажені архіви. Старий пароль
потрібно відкликати, якщо відповідний account іще існує. У цьому аудиті
колишній DB host не адмініструвався. Чинні VPS secrets мають інше походження.
Після force-push інші checkout не повинні повертати старі refs.

Backup лишаються на тому самому VPS; зовнішнє сховище не налаштоване.
Локальний системний Python 3.14.3 залишається старішим: для development
варто встановити 3.14.10 і пересоздати venv з lock. Глобальну інсталяцію ОС
цей repository task не змінював. Пентест і окремий CVE scan усіх OS packages
container images не проводилися; чистий pip-audit стосується Python locks.
