#!/usr/bin/env bash
# Restore only into a new disposable MySQL container; production is read-only here.
set -euo pipefail
cd /opt/lifetime
test "$(id -u)" = 0
umask 077
backup=$(find /opt/lifetime/backups -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
test -n "$backup"
restore_image=${RESTORE_IMAGE:-$(cat "$backup/image-id.txt")}
(cd "$backup" && sha256sum --check SHA256SUMS)
password=$(openssl rand -hex 32)
printf 'MYSQL_ROOT_PASSWORD=%s\nMYSQL_ROOT_HOST=%%\nMYSQL_DATABASE=lifetime_restore\n' "$password" > .restore-mysql.env
printf 'DB_BACKEND=mysql\nDB_HOST=lifetime-restore-mysql\nDB_NAME=lifetime_restore\nDB_USER=root\nDB_PASSWORD=%s\nANALYTICS_SECRET=isolated-restore-check-0123456789abcdef\n' "$password" > .restore-app.env
docker network create lifetime_restore
cleanup() {
    docker rm -f lifetime-restore-mysql >/dev/null 2>&1 || true
    docker network rm lifetime_restore >/dev/null 2>&1 || true
    rm -f .restore-mysql.env .restore-app.env
}
trap cleanup EXIT
docker run -d --name lifetime-restore-mysql --network lifetime_restore --memory 640m --cpus 0.75 \
    --env-file .restore-mysql.env --tmpfs /var/lib/mysql:rw,size=512m \
    mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7 \
    --innodb-buffer-pool-size=64M --performance-schema=OFF
for attempt in $(seq 1 90); do
    if docker exec lifetime-restore-mysql mysqladmin ping -h 127.0.0.1 --silent >/dev/null 2>&1; then break; fi
    sleep 2
done
docker exec lifetime-restore-mysql sh -c 'umask 077; printf "[client]\nuser=root\npassword=%s\n" "$MYSQL_ROOT_PASSWORD" > /tmp/restore.cnf'
gzip -dc "$backup/lifetime.sql.gz" | docker exec -i lifetime-restore-mysql mysql --defaults-extra-file=/tmp/restore.cnf --no-login-paths lifetime_restore
docker run --rm -i --network lifetime_restore --memory 256m --cpus 0.75 --env-file .restore-app.env \
    "$restore_image" python - <<'PY'
import json
from sqlalchemy import text
from lifetime import create_app
app = create_app()
with app.extensions['reference_engine'].connect() as conn:
    assert conn.scalar(text('SELECT DATABASE()')) == 'lifetime_restore'
    assert conn.scalar(text('SELECT version_num FROM alembic_reference_version')) == 'reference_0002'
    assert conn.scalar(text('SELECT version_num FROM alembic_version')) == 'analytics_0003'
    assert conn.scalar(text('SELECT COUNT(*) FROM life_expectancy')) == 885
assert len(app.extensions['reference'].list_locations('uk')) == 225
assert app.extensions['reference'].get_location('WLD')['values']['total'] == 73.4818184164654
client = app.test_client()
assert client.get('/readyz').status_code == 200
assert client.get('/uk').status_code == 200
assert client.post('/uk/result', data={'birth_date':'2000-01-01','country':'UKR','sex':'total'}).status_code == 200
assert app.extensions['analytics'].report('overview')['total'] > 0
assert app.extensions['analytics'].replay()['failed'] == 0
print(json.dumps({'restore':'passed','observations':885,'public_locations':225,'active_dataset':app.extensions['reference'].active_dataset()['id']}, default=str))
PY
printf 'Restored backup successfully: %s\n' "$backup"
