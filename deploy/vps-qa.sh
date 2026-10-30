#!/usr/bin/env bash
set -euo pipefail
cd /opt/lifetime
test "$(id -u)" = 0
umask 077
mysql_image='mysql:8.4@sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242'
password=$(openssl rand -hex 32)
printf 'MYSQL_ROOT_PASSWORD=%s\nMYSQL_ROOT_HOST=%%\nMYSQL_DATABASE=lifetime_test\n' "$password" > .qa-mysql.env
printf 'TEST_MYSQL_URL=mysql+pymysql://root:%s@lifetime-qa-mysql:3306/lifetime_test?charset=utf8mb4\n' "$password" > .qa-app.env
docker build -f deploy/Dockerfile.qa --build-arg RUNTIME_IMAGE=lifetime:2.1.0-vps-20261031 -t lifetime:qa-20261031 .
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
    --env-file .qa-app.env lifetime:qa-20261031 /qa/.venv/bin/python -m pytest -q \
    --deselect=tests/test_life_expectancy_data.py::LifeExpectancyDataTests::test_offline_rebuild_is_byte_for_byte_reproducible \
    --deselect=tests/test_reference.py::ReferenceTests::test_legacy_source_checksum_and_mapping_coverage
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-20261031 /qa/.venv/bin/python -m ruff check lifetime migrations scripts tests
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-20261031 /qa/.venv/bin/python -m ruff format --check lifetime migrations scripts tests
docker run --rm --memory 256m --cpus 0.75 lifetime:qa-20261031 /qa/.venv/bin/python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
# The two legacy-SQL audit checks and offline rebuild run in the original checkout.
# Historical SQL contains IP logs and is intentionally absent from all VPS images.
