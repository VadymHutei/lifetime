# Доступ до production MySQL із локального клієнта

Налаштовано 2026-10-31. Використовуйте окремий account `lifetime_desktop`,
а не credentials застосунку з `/opt/lifetime/.env`.

## Клієнт із вбудованим SSH-тунелем

MySQL connection:

| Поле | Значення |
| --- | --- |
| Host (на стороні SSH-сервера) | `127.0.0.1` |
| Port | `3307` |
| Database | `lifetime` |
| User | `lifetime_desktop` |
| Password | із локального захищеного файла нижче |

SSH settings:

| Поле | Значення |
| --- | --- |
| Host | `91.239.232.166` |
| Port | `22` |
| User | `codex` |
| Authentication | private key |
| Key file | `C:/Users/hutei/.ssh/codex_vps` |

Перевірку SSH host key залишайте ввімкненою. SSH alias `codex-vps`
вже налаштований у локальному OpenSSH config.

Пароль та параметри звичайного MySQL client збережено в
`C:/dev/lifetime/.artifacts/db-access/lifetime-desktop.cnf`.
Файл і весь каталог виключені з Git; Windows ACL дозволяє доступ лише
поточному користувачу та SYSTEM. Резервна копія credentials на VPS:
`/opt/lifetime/.desktop-client.cnf`, mode 0600, owner codex.
Не виводьте цей файл у журнали та не додавайте його в Git.

## Клієнт без вбудованого SSH

В окремому терміналі тримайте запущеним:

```sh
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:13306:127.0.0.1:3307 codex-vps
```

Після цього в MySQL-клієнті задайте host `127.0.0.1`, port **13306**,
database `lifetime`, user `lifetime_desktop` та пароль із файла.
Вбудований SSH у цьому варіанті не вмикайте: тунель уже створено командою.
Після завершення роботи зупиніть команду через Ctrl+C.

## Права та мережа

Account: `'lifetime_desktop'@'172.19.0.1'` — лише з host bridge поточної
мережі `lifetime_backend`. Права SELECT/INSERT/UPDATE/DELETE/SHOW VIEW
лише на `lifetime.*`, без глобальних адміністративних прав і GRANT OPTION.
Підключення дає можливість редагувати production-дані; schema changes
виконуються окремим migration account за процедурою backup/restore.

Порт 3306 контейнера не публікується Docker. Host socket
`lifetime-db-access.socket` слухає тільки `127.0.0.1:3307` та запускає
`lifetime-db-access.service`. Скрипт `deploy/vps-db-proxy.sh` визначає
поточний IP контейнера, потім запускає штатний systemd-socket-proxyd
від nobody. Після 30 секунд без з’єднань процес завершується; при наступному
підключенні IP визначається знову. Приватна Docker-мережа залишається internal.
Firewall для публічних MySQL-портів не відкривався.

Після пересоздання контейнера MySQL можна оновити target негайно:

```sh
ssh codex-vps sudo -n systemctl restart lifetime-db-access.service
```

Це перериває лише підключення через цей TCP proxy. При створенні мережі
`lifetime_backend` заново перевірте bridge IP та відповідний MySQL account host.
Для перевстановлення host units скопіюйте `deploy/lifetime-db-access.socket`
і `.service` до `/etc/systemd/system/`, виконайте daemon-reload та
`systemctl enable --now lifetime-db-access.socket`.

Account існує в системній БД MySQL і не входить до application-only dump
`lifetime.sql.gz`. При відновленні на новому MySQL створіть його заново
з тими самими обмеженими правами й потрібним host. Credentials збережено
окремим захищеним файлом.

## Перевірено

- Створено свіжий application backup до зміни account/network configuration.
- Реальний SSH-тунель із Windows та login PyMySQL під новим account успішні.
- Перевірено CURRENT_USER, DATABASE, VERSION, 885 observations і SHOW GRANTS.
- Публічний `91.239.232.166:3307` недоступний; socket слухає лише loopback.
- Тимчасовий тестовий SSH-тунель після перевірки зупинено.
- LifeTime readiness 200; kyiv-alert healthy без зміни ID/StartedAt/RestartCount.

Джерела: [MySQL account host](https://dev.mysql.com/doc/refman/8.4/en/account-names.html),
[systemd-socket-proxyd](https://www.freedesktop.org/software/systemd/man/262/systemd-socket-proxyd.html).
