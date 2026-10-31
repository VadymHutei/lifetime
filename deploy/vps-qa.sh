#!/usr/bin/env bash
set -euo pipefail
cd "${LIFETIME_ROOT:-/opt/lifetime}"
test "$(id -u)" = 0
umask 077
mysql_image='mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7'
password=$(openssl rand -hex 32)
printf 'MYSQL_ROOT_PASSWORD=%s\nMYSQL_ROOT_HOST=%%\nMYSQL_DATABASE=lifetime_test\n' "$password" > .qa-mysql.env
printf 'TEST_MYSQL_URL=mysql+pymysql://root:%s@lifetime-qa-mysql:3306/lifetime_test?charset=utf8mb4\n' "$password" > .qa-app.env
runtime_image=${RUNTIME_IMAGE:-lifetime:2.1.1-security-20261031-r2}
docker build -f deploy/Dockerfile.qa --build-arg RUNTIME_IMAGE="$runtime_image" -t lifetime:qa-security-20261031 .
docker network create lifetime_qa
cleanup() {
    docker rm -f lifetime-qa-mysql >/dev/null 2>&1 || true
    docker network rm lifetime_qa >/dev/null 2>&1 || true
    rm -f .qa-mysql.env .qa-app.env
}
trap cleanup EXIT
docker run -d --name lifetime-qa-mysql --network lifetime_qa --memory 640m --cpus 0.75 \
    --env-file .qa-mysql.env --tmpfs /var/lib/mysql:rw,size=512m \
    "$mysql_image" --innodb-buffer-pool-size=64M --max-connections=40 --performance-schema=OFF
for attempt in $(seq 1 90); do
    if docker exec lifetime-qa-mysql mysqladmin ping -h 127.0.0.1 --silent >/dev/null 2>&1; then break; fi
    sleep 2
done
docker run --rm --name lifetime-qa-tests --network lifetime_qa --memory 384m --cpus 0.75 \
    --env-file .qa-app.env lifetime:qa-security-20261031 /qa/.venv/bin/python -m pytest -q "$@"
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-security-20261031 /qa/.venv/bin/python -m ruff check lifetime migrations scripts tests
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-security-20261031 /qa/.venv/bin/python -m ruff format --check lifetime migrations scripts tests
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-security-20261031 /qa/.venv/bin/python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-security-20261031 /qa/.venv/bin/python -m pip_audit -r /qa/requirements-dev-lock.txt --disable-pip --no-deps
# QA includes the sanitized legacy geography seed, never historical request logs.
