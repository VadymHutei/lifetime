# LifeTime на VPS

Фактичне розгортання: **31 жовтня 2026**, LifeTime **2.1.0**,
[https://lifetime.ukubuka.net](https://lifetime.ukubuka.net).
SSH — `ssh codex-vps`, користувач `codex`, адміністративні команди через
`sudo -n`. Секрети не потрібні в чаті.

## Розташування та ізоляція

- `/opt/lifetime` — окремий Docker Compose project `lifetime`.
- Конфігурація — `deploy/compose.vps.yaml`; це **самостійний** файл,
  його не треба об’єднувати з кореневим Compose або nexus overlay.
- Контейнери — `lifetime-app-1`, `lifetime-mysql-1`, `lifetime-proxy-1`.
- Назовні відкриті лише 80/443; app:8000 і MySQL:3306 не опубліковані.
- Для локального DB-клієнта налаштовано окремий account і SSH-доступ
  через loopback `127.0.0.1:3307`: [DATABASE_ACCESS.md](DATABASE_ACCESS.md).
- Власні мережі `lifetime_frontend` (172.30.57.0/24) і внутрішня
  `lifetime_backend`; жодного приєднання до мережі kyiv-alert.
- IP proxy `172.30.57.2`; застосунок довіряє лише цьому `/32`.
- MySQL 8.4.11, nginx 1.30.6, Python 3.14.8; сторонні images pinned digest.
- Memory limits: app 320 MiB, MySQL 640 MiB, proxy 64 MiB. Restart policy
  `unless-stopped`, Docker увімкнений при завантаженні ОС.
- Runtime MySQL account має тільки SELECT/INSERT/UPDATE/DELETE на `lifetime.*`;
  окремий `lifetime_migrate` — для міграцій/імпорту. Root не використовується app.

Стан kyiv-alert до та після розгортання однаковий: container ID
`180eecde51f43983a263eab2330b7979bcc89b1b1a00bd791572f9998b738ca5`,
StartedAt `2026-10-30T22:17:26.956076272Z`, RestartCount `0`, health `healthy`.
Його код, конфігурація, контейнери, firewall-доступи й volumes не змінювалися.
На VPS додано лише правила 80/tcp і 443/tcp для LifeTime.

## DNS та HTTPS

У DNS-зоні `ukubuka.net` власник створив:

| Тип | Ім’я | Значення | TTL |
| --- | --- | --- | --- |
| A | lifetime | 91.239.232.166 | 3600 |

NS змінювати не потрібно. Наявні A для `@` і `*` на `195.140.162.38`
залишаються; окремий запис `lifetime` має пріоритет над wildcard.
Не додавайте AAAA до налаштування та перевірки IPv6 на цьому VPS.
Перевірено публічний HTTP ACME challenge, HTTPS із перевіркою сертифіката
та зовнішній POST-розрахунок 200/noindex/no-store.

Окремий Let’s Encrypt certificate містить SAN `lifetime.ukubuka.net`;
початковий строк дії — до **2027-01-28 22:07:02 UTC**.
Сертифікати та ACME account зберігаються у `/opt/lifetime/certificates`.
Оновлення HTTP-01 автоматичне; порт 80 потрібен і надалі.
Certbot account зареєстровано без email; email-сповіщення CA не налаштовані.
Тестове поновлення `renew --dry-run` завершилося успішно.
Примітка: коротка помилка curl відразу після першого nginx reload була
пов’язана з асинхронним застосуванням конфігурації; наступні зовнішні
TLS/HTTP перевірки успішні. Операторська команда тепер має bounded retries.

## Дані й секрети

- `/opt/lifetime/.env` — згенеровані окремі паролі та стабільний HMAC secret,
  mode 0600; значення не записані в Git або цю документацію.
- `lifetime_mysql-data` — persistent MySQL volume.
- `/opt/lifetime/state` — durable spool; власник 10001:10001.
- `/opt/lifetime/edge` — sanitized proxy JSONL; у app доступ тільки для читання.
- Raw IP вимкнено; DOB, body та raw query не записуються у БД/edge/spool.
- Dataset id: `f1087cd51f3d16450ec98242e9c4b7d7704d224b883d3ec2b78b01a25c63012b`;
  рік 2024, 295 entities, 885 observations, 225 публічних географій.
- Schema revisions: `reference_0002`, `analytics_0003`.

Runtime source — commit `5fd1f9839de6013538663958b13f7cf26afcc83a`;
Deployment files зберігаються окремо від runtime, який не змінено.
Код передано whitelist-архівом із поточного checkout, без `.env`, `.git`,
IDE файлів та історичних SQL dumps. Наявні staged зміни користувача збережені;
Під час початкового запуску push і новий release tag не виконувалися.
Release image: `lifetime:2.1.0-vps-20261031`, фактичний image ID:
`sha256:4164d376924928f20c1b066e47c4cdc20711e399e9929953708be5d919570935`.
Не перезаписуйте цей tag під час наступного оновлення.

## Обслуговування

Systemd timers, журнали — `journalctl -u lifetime-<action>.service`:

| Timer | Розклад | Дія |
| --- | --- | --- |
| lifetime-maintenance | кожні 5 хв | rotate/reopen edge, ingestion, replay |
| lifetime-purge | щодня 03:15 UTC | retention БД/spool |
| lifetime-backup | щодня 03:30 UTC | MySQL dump, state/config/certificates |
| lifetime-renew | 00:10 і 12:10 UTC | перевірка поновлення TLS, nginx test/reload |

Timers мають `Persistent=true`, jitter до 30 с; спільний `flock`
не допускає накладання цих jobs. Збої ingestion/replay/purge переводять
service у failed; журнали збережені в systemd. Зовнішні сповіщення не налаштовані.
Edge file видаляється лише після перевіреного ingestion без dropped,
invalid_lines і disabled. Повторний import ідемпотентний.
Detailed analytics: 90 днів, aggregates: 365. Docker logs обмежено 3 × 5 MiB
на контейнер. Backup retention — приблизно 15 днів.

Основні команди з локального комп’ютера:

```sh
ssh codex-vps sudo -n bash /opt/lifetime/deploy/vps-admin.sh status
ssh codex-vps sudo -n systemctl list-timers lifetime-*
ssh codex-vps sudo -n journalctl -u lifetime-maintenance.service -n 50 --no-pager
ssh codex-vps sudo -n systemctl start lifetime-backup.service
ssh codex-vps sudo -n bash /opt/lifetime/deploy/vps-admin.sh renew-check
```

Усі Compose-команди на сервері мають явно вказувати `.env` та самостійний файл:

```sh
cd /opt/lifetime
sudo docker compose --env-file /opt/lifetime/.env -f /opt/lifetime/deploy/compose.vps.yaml ps
sudo docker compose --env-file /opt/lifetime/.env -f /opt/lifetime/deploy/compose.vps.yaml exec -T app flask --app lifetime analytics report --group overview
```

Не друкуйте `docker compose config` без `--quiet`, `.env`, Docker Env або
MySQL client option files — вони містять секрети.
`vps-admin.sh init` призначений лише для першого встановлення; після успіху
повторний запуск блокує `.initialized`.

## Резервування та перевірене відновлення

Backups — root-only `/opt/lifetime/backups/<UTC timestamp>-<pid>/`:
`lifetime.sql.gz`, `config-state.tgz`, VERSION, image ID, revisions/dataset
та SHA256SUMS. Dump — official MySQL client, `--single-transaction`, без DDL.
Секрет client передається через option file всередині MySQL, без пароля в CLI.
State архівується під час роботи: spool є додатковим best-effort доповненням
до консистентного SQL snapshot, а не спільною транзакцією з ним.

Перша копія `/opt/lifetime/backups/20261030T230633-13057` перевірена:
SHA-256, gzip, імпорт у **окремий тимчасовий MySQL container** без host ports,
обидві revisions, dataset, 885 observations/225 географій, readiness,
GET/POST калькулятор, analytics/replay. Production не був restore target.
Тимчасовий container, мережа, QA credentials після перевірки видалені.
Повторна ізольована репетиція:

```sh
ssh codex-vps sudo -n bash /opt/lifetime/deploy/vps-restore-check.sh
```

Копії наразі **на тому самому VPS**. Для захисту від втрати диска/сервера
потрібне окреме зовнішнє сховище; його не було надано для цього запуску.
Архів `config-state.tgz` містить секрети — переносити його лише захищеним
каналом і з обмеженим доступом.

Перед оновленням: зупинити maintenance timers, зробити backup і репетицію
restore; зібрати новий унікальний image tag, застосувати міграції окремим
обліковим записом, перевірити readiness/POST, повернути timers.
Для schema rollback використати старий image та backup у **новій БД**,
не завантажувати dump поверх live database. Докладні правила — MYSQL.md.
Не виконувати глобальні Docker prune/down, `down --volumes` чи перезапуск VPS
для звичайного оновлення LifeTime: сервер спільний із kyiv-alert.

## Фактичні перевірки

- Compose config, build із hashed runtime lock, pip check, MySQL migrate/import,
  nginx -t, readiness усіх трьох контейнерів — успішно.
- Linux Python 3.14.8 + окремий disposable MySQL 8.4.11: **105 passed,
  534 subtests passed**. Два інші тести завершилися помилкою через відсутність
  історичного `db_data.sql` у QA image; вони окремо виконані локально:
  **2 passed**. Історичний SQL із IP logs навмисно не передавався на VPS.
  QA script тепер явно deselect ці два audit checks; повний набір повторно
  після цього не запускався, оскільки 105 тестів уже пройшли без runtime змін.
- Початковий повний Windows run: 84 passed, 22 MySQL skips, 1 помилка sandbox
  WinError 5 у concurrent local-key test. Цей тест пройшов у Linux QA.
- Ruff check/format, pip check, pip-audit runtime (відомих вразливостей немає),
  локальний offline rebuild — успішно, dataset без змін.
- HTTPS smoke: GET uk/en, static, HEAD, legacy 301/410, 404/405, POST result,
  noindex/no-store, query/path redaction, edge-only 413, forwarding/request-id
  overwrite, 458 sitemap URLs, 16 request IDs → 16 events після повторного
  ingestion; raw IP/DOB/тестового секрету в БД/edge немає; spool порожній.
  Із app цей smoke використовує private proxy IP зі справжньою TLS/SNI
  перевіркою; зовнішній HTTPS GET/POST перевірено окремо з комп’ютера оператора.
- Браузер: публічна сторінка/desktop, 320 px viewport без горизонтального
  переповнення (document scrollWidth 305 при innerWidth 320).
- Maintenance, purge, backup, renew services — `Result=success`, `ExecMainStatus=0`;
  staging dry-run поновлення сертифіката успішний.
- Порівняння kyiv-alert до/після: без diff, healthy, жодного рестарту.
