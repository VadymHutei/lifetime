# MySQL — експлуатація LifeTime 2.1.0

Профіль 2.1.0 використовує зовнішній MySQL 8.4 та одну application database для
довідників і аналітики. Compose запускає застосунок, а адресу та доступ до
наявного сервера задає оператор. Локальний MySQL для тестування не є
production сервером; тестові команди не повинні отримувати production credentials.

## Підключення

Параметри `.env`: `DB_BACKEND=mysql`, `DB_HOST`, `DB_PORT` (типово `3306`),
`DB_NAME`, `DB_USER`, `DB_PASSWORD`. Пароль задавайте у локальному незакоміченому
файлі або секреті оточення процесу, а не в CLI arguments чи URL, який друкується
в логах. `REFERENCE_DATABASE_URL` та `ANALYTICS_DATABASE_URL` — додаткові явні
overrides для окремих баз; повний URL містить credentials і теж є секретом.
`DB_SSL_CA` задає CA file, видимий для app; у Docker змонтуйте його read-only.
Цей параметр вмикає TLS із перевіркою сертифіката та hostname. Host повинен
відповідати SAN сертифіката сервера; неправильний CA/hostname відхиляється.
Без CA параметра використовуйте лише відповідно захищену довірену мережу.

Створіть чисту application database з `utf8mb4`, окремого runtime користувача
з доступом тільки до неї та окремий міграційний доступ для DDL. Виконайте
`flask --app lifetime migrate`, потім `flask --app lifetime import-data` у
заданому deployment environment. Це створює нову схему, а не імпортує legacy SQL
dumps чи старі IP-журнали. Перед першими змінами існуючої БД перевірте backup
і restore на окремому сервері.

## Backup офіційним клієнтом

`flask backup` призначений для SQLite. Для MySQL він завершується до створення
каталогу; SQL dump виконується офіційним `mysqldump` 8.4 на машині оператора.
Схема застосунку використовує InnoDB. Під час backup не запускайте міграції,
імпорт/активацію даних чи інші DDL. Зупиніть maintenance jobs для отримання
передбачуваного стану. `--single-transaction` дає консистентний InnoDB snapshot;
`--quick` читає рядки поступово, `--no-tablespaces` прибирає потребу в PROCESS,
а `--set-gtid-purged=OFF` підходить для цього application dump, не replication
bootstrap. [mysqldump 8.4](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html).

Створіть `/secure/lifetime-backup.cnf` поза repository, без виводу пароля:

```ini
[client]
host=mysql.example.internal
port=3306
user=lifetime_backup
password=REPLACE_LOCALLY
default-character-set=utf8mb4
```

На Linux встановіть ownership оператора й mode `600`; на Windows обмежте NTFS
ACL лише оператором. Застосуйте потрібні TLS client options. Backup account
потребує SELECT та, якщо є відповідні об’єкти, SHOW VIEW/TRIGGER; migrations
не потребують виконуватися від його імені.

Передайте `--defaults-extra-file` першим аргументом. Він доповнює інші option
files: перевірте, що локальні конфігурації не перекривають підключення, та
перевірте hostname/database перед export. Пароль не потрапляє в arguments.
Не використовуйте `--print-defaults`, який може розкрити опції.
[Option-file handling](https://dev.mysql.com/doc/refman/8.4/en/option-file-options.html).

```sh
mysql --defaults-extra-file=/secure/lifetime-backup.cnf --no-login-paths --database=lifetime --execute="SELECT @@hostname, DATABASE(), VERSION();"
mysqldump --defaults-extra-file=/secure/lifetime-backup.cnf --no-login-paths --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF --default-character-set=utf8mb4 --result-file=/backups/lifetime-2.1.0.sql lifetime
```

Використовуйте новий output filename, перевірте exit code `0`, ненульовий
розмір і SHA-256. Збережіть поруч image/version, active dataset id, час UTC
та schema revisions, без секретів. `--result-file` також уникає зміни encoding
через PowerShell stdout redirection. Backup містить приватну аналітику:
зберігайте його з обмеженим доступом і retention. Окремо захистіть persistent
spool, стабільний `ANALYTICS_SECRET` та конфігурацію: SQL dump їх не містить.
Варіант з двома overrides потребує dump обох баз і узгодженого maintenance
вікна; два незалежні exports не є спільним transaction snapshot.

## Restore rehearsal і rollback

Спершу відновіть dump у нову порожню `lifetime_restore` на ізольованому MySQL
8.4. Не використовуйте адресу production як restore target. Dump вище
зроблено без `--databases`, тому він не містить `CREATE DATABASE` / `USE`
для перемикання на вихідну application database. Створіть окремий protected
`lifetime-restore.cnf` з credentials тестового restore сервера.

```sh
mysql --defaults-extra-file=/secure/lifetime-restore.cnf --no-login-paths --database=lifetime_restore --execute="source /backups/lifetime-2.1.0.sql"
```

`source` працює також у Windows клієнті; використовуйте абсолютний шлях із
forward slashes. Перевірте exit code та помилки. Стандартний SQL restore
описаний у [MySQL restore documentation](https://dev.mysql.com/doc/refman/8.4/en/reloading-sql-format-dumps.html).

Направте окремий instance застосунку на restore database: перевірте обидві
таблиці Alembic revisions, active dataset та 225 публічних географій,
`/readyz`, POST-розрахунок, операторський analytics report і replay spool.
Звірте ключові row counts та dataset id із backup metadata. Не запускайте
нові міграції перед першою перевіркою відновленого release image.

Для rollback зупиніть writers, збережіть поточний backup/spool, відновіть
перевірений dump у нову database, переключіть connection configuration та
запустіть відповідний попередній image. Після readiness/smoke перевірок
повертайте трафік. Пряме завантаження dump поверх live database має
руйнівні наслідки й не входить до автоматичного deployment.

Цей документ є workflow; credentials, реальний production backup і
production restore не виконувалися під час розробки.
