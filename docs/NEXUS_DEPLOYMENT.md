# Деплой LifeTime на nexus

**Історичний план від 2026-10-03.** Фактичний production із 2026-10-31
працює на окремому VPS; актуальні адреса, конфігурація й операції —
[VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md). Цей документ описує альтернативний
варіант nexus і стан репозиторію на дату аудиту, а не поточний запуск.

Інструкція для `lifetime.ukubuka.net`, Docker, наявного MySQL та nginx на nexus.
Домен підтверджено користувачем 2026-10-03. **Публічний запуск ще не готовий:**
потрібно опублікувати код 2.1.0, перевірити MySQL 9.7.2 та виконати контейнерні
перевірки. Наведені нижче команди для Bash на nexus; виконуйте кроки послідовно
і зупиняйтеся при помилці.

## Результат перевірки репозиторію

Стан 2026-10-03 після `git fetch --prune origin`:

| Об’єкт | Фактичний стан |
| --- | --- |
| Поточна гілка | `codex/mysql-support`, commit `5fd1f9839de6013538663958b13f7cf26afcc83a`, VERSION 2.1.0 |
| Незакомічена робота до аудиту | П’ять staged файлів `.idea/`; runtime змін немає. Файли користувача збережено |
| Локальні теги | Annotated `v2.0.0` і `v2.1.0`; `git ls-remote --heads --tags origin` не показує віддалених тегів |
| Віддалена версія v2 | Лише `codex/lifetime-v2` на `1860d9c`, VERSION 2.0.0; гілка `codex/mysql-support` відсутня |
| Основна гілка | `origin/master` на `aa9aa5c` досі legacy; локальна `master` відстає на два коміти. Зміна стосується Jinja2 у `app/requirements.txt` |
| Dependabot | Чотири віддалені гілки оновлюють legacy `app/requirements.txt`, який не входить до нового image |
| CI | Немає підтвердженого успішного LifeTime checks run для commit 2.1.0; наявні Dependabot runs не перевіряють новий runtime |

Фактичні перевірки поточного runtime:

- `pytest`: **85 passed, 22 skipped, 518 subtests passed**. Повторний запуск
  поза sandbox усунув помилки доступу до temporary SQLite files. MySQL тести
  пропущено, оскільки `TEST_MYSQL_URL` не задано.
- Ruff check, Ruff format check, `pip check`, `git diff --check` і staged
  diff check пройшли. Runtime `pip-audit` поза sandbox: відомих вразливостей немає.
- Offline rebuild відтворив dataset без diff: 295 entities, 885 observations,
  792 available, 93 missing, спільний рік 2024.
- Базовий Compose валідний. Локальний MySQL overlay потребує `DB_PASSWORD`;
  структурна перевірка з окремим тестовим значенням пройшла.
- Новий nexus overlay перевірено через Compose config, включно з відсутністю
  host ports, двома external networks і bind mounts. **Build/start/HTTP та
  `nginx -t` для нових шаблонів не виконано: локальний Docker daemon вимкнений.**
- Попередню перевірку MySQL 8.4 описано в [MYSQL_VALIDATION](MYSQL_VALIDATION.md);
  вона не доводить сумісність із MySQL 9.7.2 на nexus.

Під час цього аудиту додано цю інструкцію, два deployment templates і посилання
в README. Вони потребують окремого коміту; runtime і VERSION не змінювалися.

## Джерела конфігурації nexus

Доступні локальні `C:\dev\homelab-docs` та
`C:\dev\homelab-nexus-infrastructure`; GitHub доступ перевірено.
Віддалений infrastructure `main` — commit `77e21ccd2595da1909292159ad6e37e50626e418`.

- [Proxy Compose](https://github.com/VadymHutei/homelab-nexus-infrastructure/blob/77e21ccd2595da1909292159ad6e37e50626e418/proxy/compose.yml):
  контейнер `proxy`, external `home_proxy`, порти 80/443, mounts із `/srv/data/proxy`.
- [MySQL Compose](https://github.com/VadymHutei/homelab-nexus-infrastructure/blob/77e21ccd2595da1909292159ad6e37e50626e418/mysql/compose.yml):
  контейнер `mysql`, image `mysql:9.7.2`, external `home_data`.
- Документація homelab: `docs/hardware/nexus.md`, `docs/services/mysql.md`,
  `docs/infrastructure/reverse-proxy.md`, `docs/operations/deployment.md`.
  Власник підтвердив MySQL 9.7.2 і запущений proxy 2026-09-28; це датований
  стан, а не поточний SSH аудит. Сертифікати поновлюються вручну.

## 1 Підготувати код до публікації

На робочому комп’ютері перегляньте staged `.idea/` і вирішіть окремо, чи потрібні
ці IDE files у Git. Вони не впливають на runtime image. Не включайте їх випадково
в deployment commit і не видаляйте без потреби.

Узгодьте `codex/mysql-support` із новими комітами `origin/master` у чистому
checkout. Обидві гілки мають спільний ancestor `ed623e4`; автоматичний merge
у межах аудиту не виконувався. Для деплою виберіть явно перевірений commit v2,
а не default `master`, який запускає legacy.

Збережіть нові deployment files. Якщо staged `.idea/` ще присутні, commit
із явними pathspecs залишить їх поза цим комітом:

```sh
git add README.md docs/NEXUS_DEPLOYMENT.md deploy/compose.nexus.yaml deploy/nginx.nexus.conf
git commit --only README.md docs/NEXUS_DEPLOYMENT.md deploy/compose.nexus.yaml deploy/nginx.nexus.conf -m "Document LifeTime deployment on nexus"
git push -u origin codex/mysql-support
```

Після push дочекайтеся **LifeTime checks** для саме цього commit: tests,
MySQL integration, package build і container smoke. Запишіть повний commit SHA.
Наявні локальні release tags не містять нових deployment files; не пересувайте
їх. Теги публікуйте лише після acceptance відповідного release commit.

## 2 Перевірити сервер і сумісність MySQL

Увійдіть на nexus через наявний SSH доступ користувача `hutei`:

```sh
ssh hutei@nexus
hostname
docker version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker network inspect home_proxy home_data --format '{{.Name}} {{json .IPAM.Config}}'
docker inspect proxy --format '{{(index .NetworkSettings.Networks "home_proxy").IPAddress}}'
docker exec -it mysql mysql -u admin -p
```

У MySQL виконайте `SELECT VERSION(), @@hostname, CURRENT_USER();` і `exit`.
Запишіть **реальну IPv4 підмережу `home_data`** для MySQL account host та
**IP proxy у `home_proxy`** для `TRUSTED_PROXY_CIDRS=<IP>/32`.
Не використовуйте вигадану підмережу або довіру до `0.0.0.0/0`.

**До public запуску перевірте 9.7.2 на ізольованому QA MySQL тієї ж версії.**
Встановіть dev lock у `.venv`; задайте `TEST_MYSQL_URL` через захищене середовище
до disposable `lifetime_test` на QA server і виконайте `.venv/bin/python -m pytest -q`.
QA account потребує створення та видалення окремих тестових баз; очікується
повний набір 107 tests без 22 MySQL skips. Додатково перевірте container
migrate/import/start/readiness/POST та backup/restore з клієнтом відповідної
версії. Production nexus/MySQL credentials для цих тестів не використовуються.
Успішний CI на 8.4 не закриває цю перевірку 9.7.2. Альтернатива — окремий
MySQL 8.4 для LifeTime, але це інша схема розгортання, яку цей документ не налаштовує.

Потрібний Compose **2.24.4+**, оскільки overlay використовує `!reset` та
`!override` для заміни ports і volumes.
[Правила Compose merge](https://docs.docker.com/reference/compose-file/merge/).

## 3 Створити окрему базу та користувачів MySQL

Це інструкція першого запуску з **новою** БД `lifetime`. Перевірте, що такої
application schema ще немає. Якщо є — спочатку перевірений backup/restore
за [MYSQL](MYSQL.md) з клієнтом відповідної серверної версії.

```sh
docker exec -it -e MYSQL_HISTFILE=/dev/null mysql mysql -u admin -p
```

У SQL замініть `HOME_DATA_CIDR` фактичною IPv4 підмережею Docker, наприклад
`172.19.0.0/16` **тільки якщо inspect підтвердив саме її**. `RUNTIME_PASSWORD`
і `MIGRATION_PASSWORD` — два різні згенеровані паролі, заповнені локально.

```sql
SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = 'lifetime';
CREATE DATABASE lifetime CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'lifetime'@'HOME_DATA_CIDR' IDENTIFIED BY 'RUNTIME_PASSWORD';
CREATE USER 'lifetime_migrate'@'HOME_DATA_CIDR' IDENTIFIED BY 'MIGRATION_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, SHOW VIEW
  ON lifetime.* TO 'lifetime'@'HOME_DATA_CIDR';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX,
  REFERENCES, CREATE VIEW, SHOW VIEW
  ON lifetime.* TO 'lifetime_migrate'@'HOME_DATA_CIDR';
SHOW GRANTS FOR 'lifetime'@'HOME_DATA_CIDR';
SHOW GRANTS FOR 'lifetime_migrate'@'HOME_DATA_CIDR';
```

Account host із CIDR підтримується MySQL; обмеження беріть із фактичної
[мережі клієнта](https://dev.mysql.com/doc/mysql-security-excerpt/8.0/en/account-names.html).
Права на `*.*` і `GRANT OPTION` застосунку не потрібні.
Не видаляйте migration account після імпорту: міграції створюють views із
default [SQL SECURITY DEFINER](https://dev.mysql.com/doc/refman/8.4/en/create-view.html).
Production app працюватиме від `lifetime`, а DDL — лише через `lifetime_migrate`.
Не запускайте legacy SQL dumps або seeds.

## 4 Склонувати перевірений commit і створити каталоги

```sh
sudo install -d -m 0755 -o hutei -g hutei /srv/apps/services/lifetime
git clone --branch codex/mysql-support https://github.com/VadymHutei/lifetime.git /srv/apps/services/lifetime
cd /srv/apps/services/lifetime
git checkout --detach REPLACE_WITH_VERIFIED_COMMIT_SHA
git rev-parse HEAD
cat VERSION
sudo install -d -m 0700 -o 10001 -g 10001 /srv/data/lifetime/state
sudo install -d -m 0755 -o 10001 -g 10001 /srv/data/proxy/logs/lifetime
sudo touch /srv/data/proxy/logs/lifetime/edge.jsonl
sudo chown 10001:10001 /srv/data/proxy/logs/lifetime/edge.jsonl
sudo chmod 0640 /srv/data/proxy/logs/lifetime/edge.jsonl
```

`REPLACE_WITH_VERIFIED_COMMIT_SHA` — SHA з кроку 1, що включає deployment files.
Каталог clone має бути порожнім. Каталог edge logs має mode `0755`, щоб nginx
worker міг відкрити файл після reopen; сам файл доступний лише owner/group.
UID/GID `10001` — користувач усередині image;
окремий Linux login `lifetime` не потрібний. На сервері мають існувати
`/srv/apps/infrastructure/proxy` і його mounts; звірте фактичний шлях,
якщо infrastructure repository встановлений в іншому каталозі.

## 5 Заповнити захищений env

```sh
umask 077
cp .env.example .env
chmod 600 .env
nano .env
```

Основні значення:

```dotenv
ENVIRONMENT=production
SERVICE_URL=https://lifetime.ukubuka.net
LIFETIME_IMAGE=lifetime:2.1.0-nexus
DB_BACKEND=mysql
DB_HOST=mysql
DB_PORT=3306
DB_NAME=lifetime
DB_USER=lifetime
DB_PASSWORD='RUNTIME_PASSWORD'
DB_SSL_CA=
REFERENCE_DATABASE_URL=
ANALYTICS_DATABASE_URL=
ANALYTICS_SECRET=REPLACE_WITH_GENERATED_SECRET
ANALYTICS_STORE_RAW_IP=false
ANALYTICS_RETENTION_DAYS=90
ANALYTICS_RAW_IP_DAYS=7
ANALYTICS_AGGREGATE_DAYS=365
TRUSTED_PROXY_CIDRS=REPLACE_WITH_PROXY_IPV4/32
```

Генеруйте `ANALYTICS_SECRET` як 32 random bytes, наприклад `openssl rand -hex 32`,
і зберігайте його стабільно. Не записуйте секрет у Git або діагностичний звіт.
Пароль із `$` чи `#` беріть у single quotes у `.env`. Не виконуйте `source .env`.
`DB_HOST=mysql` доступний через `home_data`; `127.0.0.1` означав би app-контейнер.
Цей профіль передбачає довірену локальну bridge network. Якщо MySQL вимагає TLS,
додайте CA bind mount read-only і `DB_SSL_CA` із hostname, що відповідає SAN;
перевірку сертифікатів не вимикайте.

## 6 Зібрати образ і виконати міграції

Для наступних команд визначте Bash function у поточній shell:

```sh
cd /srv/apps/services/lifetime
dc() { docker compose -p lifetime -f compose.yaml -f deploy/compose.nexus.yaml "$@"; }
dc config --quiet
dc build
read -r -s -p 'Migration password: ' DB_PASSWORD
export DB_PASSWORD
dc run --rm -e DB_USER=lifetime_migrate -e DB_PASSWORD app flask --app lifetime migrate
dc run --rm -e DB_USER=lifetime_migrate -e DB_PASSWORD app flask --app lifetime import-data
unset DB_PASSWORD
dc up -d --wait --wait-timeout 90
dc ps
dc exec -T app flask --app lifetime version
dc exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).status)"
```

Перевіряйте exit code **кожної** команди до наступного кроку. Очікуються дві
migration histories `reference_0002`, `analytics_0003`, 225 public locations,
версія 2.1.0 та readiness 200. Збережіть dataset id з import summary.
HTTP порт не публікується на host: proxy використовує DNS alias `lifetime:8000`.
Не додавайте `compose.mysql.yaml` — цей запуск використовує наявний MySQL nexus.

## 7 Налаштувати DNS і TLS

У DNS створіть або перевірте запис `lifetime.ukubuka.net` до актуальної WAN
адреси nexus. Перевірте A та, якщо є, AAAA; не залишайте AAAA до непрацюючого
IPv6 ingress. Наявні router forwards 80/443 достатні; додатковий 8057 не потрібний.

Перевірте строк дії й SAN чинного сертифіката:

```sh
sudo openssl x509 -in /srv/data/proxy/certbot/conf/live/ukubuka.net/fullchain.pem -noout -dates -ext subjectAltName
```

Сертифікат має покривати `lifetime.ukubuka.net` або `*.ukubuka.net`.
Назва каталогу `ukubuka.net` сама по собі цього не доводить. Якщо покриття немає,
отримайте або поновіть сертифікат наявним ручним DNS challenge процесом,
зберігаючи SAN інших сервісів. Не замінюйте спільний сертифікат сертифікатом
лише для LifeTime. Чинний wildcard не потребує нового сертифіката для цього host.

## 8 Додати virtual host у nginx

```sh
cp deploy/nginx.nexus.conf /srv/apps/infrastructure/proxy/conf.d/lifetime.conf
docker exec proxy nginx -t
docker exec proxy nginx -s reload
```

Reload виконуйте лише після успішного `nginx -t`. Це snippet для наявного
`http { include /etc/nginx/conf.d/*.conf; }`; не замінюйте весь `nginx.conf`.
Після додавання файла до infrastructure repository збережіть його окремим
цільовим комітом, не включаючи сторонні staged/untracked files.

Template передає `/static`, robots і sitemap до Flask для capture, переписує
forwarding headers і request id, використовує Docker resolver при зміні IP app.
У двох server blocks задано safe JSONL access log замість успадкованого `main`;
raw error log вимкнений. Перевірте, що додаткові include/log destinations
не пишуть LifeTime request URI/query/Referer паралельно.

При пересозданні **proxy** його IP може змінитися. Повторіть inspect, оновіть
`TRUSTED_PROXY_CIDRS` у `.env` і застосуйте `dc up -d --force-recreate --wait`.
Шаблон передбачає прямий nginx ingress; якщо попереду з’явиться CDN або інший
proxy, forwarding і trusted peers треба звірити окремо.

## 9 Перевірити сайт перед відкриттям трафіку

Спочатку перевірте vhost локально з nexus, з чинним TLS verification:

```sh
curl --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail https://lifetime.ukubuka.net/readyz
curl --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail https://lifetime.ukubuka.net/uk
curl --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail https://lifetime.ukubuka.net/en
curl --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail https://lifetime.ukubuka.net/sitemap.xml
curl --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail --data 'birth_date=2000-01-01&country=UKR&sex=total' https://lifetime.ukubuka.net/uk/result
dc exec -T app flask --app lifetime analytics report --group overview
```

Потім повторіть public GET/POST із зовнішньої мережі. Перевірте footer 2.1.0,
правильні canonical/hreflang, `/ukr`→301, `/rus`→410, result noindex/no-store,
форму без JS, keyboard focus, 320 px і desktop. DOB у smoke є вигаданою.
Діагностичний GET із query перевіряйте лише з вигаданими значеннями:
у JSONL/DB/spool не повинно бути DOB, raw query чи credentials.

Окремо перевірте edge-only 413 великим тестовим body та ingestion/dedup за
`X-Request-ID`. `/readyz` перевіряє активний dataset і читання analytics table,
але **не доводить**,
що analytics INSERT працює: report має показати нові HTTP events, а spool і
container stderr — не показувати постійну відмову БД або `dropped_event`.

## 10 Налаштувати обслуговування журналів

Після успішного smoke налаштуйте scheduler на nexus. Мінімум: `analytics replay`
кожні п’ять хвилин, `analytics purge` щодня, ротація та ingestion edge JSONL.
Приклад user crontab для `hutei` з Docker доступом; шлях Docker перевірте
через `command -v docker`. `flock` не допускає одночасних maintenance jobs:

```cron
*/5 * * * * cd /srv/apps/services/lifetime && /usr/bin/flock -n /srv/apps/services/lifetime/.maintenance.lock /usr/bin/docker compose -p lifetime -f compose.yaml -f deploy/compose.nexus.yaml exec -T app flask --app lifetime analytics replay
15 3 * * * cd /srv/apps/services/lifetime && /usr/bin/flock -n /srv/apps/services/lifetime/.maintenance.lock /usr/bin/docker compose -p lifetime -f compose.yaml -f deploy/compose.nexus.yaml exec -T app flask --app lifetime analytics purge
```

Для edge log ротуйте файл через rename, створіть новий `edge.jsonl` із
owner `10001:10001`, mode `0640`, виконайте `docker exec proxy nginx -s reopen`.
Після reopen nginx може змінити owner файла на свого worker user; зберігайте
group `10001` і mode `0640`, щоб app міг читати JSONL через read-only mount.
Імпортуйте завершений файл із read-only mount, наприклад:

```sh
dc exec -T app flask --app lifetime analytics ingest-edge /var/lib/lifetime/edge/edge-20261003.jsonl
dc exec -T app flask --app lifetime analytics replay
```

У summary перевірте `dropped=0`, `invalid_lines=0`, `disabled=0`; якщо були
`spooled` events, перевірте успішний replay. Видаляйте завершений файл лише
після підтвердженого ingestion. Повторний import ідемпотентний. DB purge не
очищує edge files. Зберігайте output/errors maintenance в операторському
журналі й реагуйте на `database_failed` або `dropped_event`; не відкидайте їх.

## 11 Зафіксувати запуск і процедуру відновлення

Запишіть deployment commit, image id, VERSION, schema revisions, dataset id,
дату запуску та перевірені DNS/TLS/HTTP результати без credentials.
Image tag після build не є immutable digest: збережіть image id окремо.

Для наступних оновлень перед міграціями підготуйте перевірений MySQL dump і
restore у новій ізольованій БД, копію `/srv/data/lifetime/state`, захищений
`.env` і старий image. Для MySQL 9.7.2 використовуйте відповідний official client
і перевірте сумісність опцій [MYSQL](MYSQL.md), що раніше тестувалися на 8.4.
Не відновлюйте dump поверх працюючої БД і не виконуйте `down --volumes`.

Якщо перший запуск не пройшов acceptance, приберіть тільки новий LifeTime vhost,
перевірте nginx і reload, зупиніть `dc stop app`. Збережіть дані для діагностики;
не змінюйте shared MySQL/proxy або інші сервіси. Для наступних оновлень rollback
виконується старим image і сумісним backup у новій БД за [MYSQL](MYSQL.md).
