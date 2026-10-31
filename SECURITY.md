# Безпека LifeTime

Підтримується лише runtime `lifetime/` із кореневими hashed locks.
`app/` — історичний read-only референс, не придатний для запуску.

Не комітьте `.env`, приватні ключі/сертифікати, client option files,
backup, working databases або request logs. `.env.example` містить тільки
порожні значення та приклади. Перевірки перед push:

```powershell
.venv\Scripts\python scripts/check_repository_safety.py
.venv\Scripts\python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
.venv\Scripts\python -m pip_audit -r requirements-dev-lock.txt --disable-pip --no-deps
```

CI додатково запускає Gitleaks із повною redaction. Результат scanner не
доводить відсутності секретів: короткий старий пароль виявив ручний аудит.
Якщо секрет опубліковано, спочатку відкличте/замініть його на відповідному
сервісі; очищення Git не відкликає credentials і не видаляє чужі клони.
Повідомляйте власнику приватним каналом, не додаючи секрети в public issues.

Production: HTTPS, точні trusted proxy CIDRs, окремі DB accounts, raw IP
вимкнено, secrets поза Git. Перед upgrade БД — backup і перевірений isolated
restore. Для ручного backup без очищення попередніх копій:

```sh
sudo env BACKUP_PRUNE=false bash /opt/lifetime/deploy/vps-admin.sh backup
```

Після очищення історії 2026-10-31 інші checkout потрібно клонувати заново
або обережно синхронізувати з новими refs. Не merge/push стару історію назад.
Старі конфігураційні DB credentials потрібно вважати скомпрометованими;
їхній стан на колишньому сервері не встановлено. Чинні production secrets
згенеровано окремо, вони не збігаються за довжиною зі старим паролем.

Фактичні результати й межі — [аудит 2026-10-31](docs/SECURITY_AUDIT_2026-10-31.md).
