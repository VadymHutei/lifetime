#!/usr/bin/env bash
# Root-only operations for this dedicated Compose project. Never uses global down/prune.
set -euo pipefail
umask 077
cd /opt/lifetime
test "$(id -u)" = 0
set -a
. /opt/lifetime/.env
set +a
dc() { docker compose --env-file /opt/lifetime/.env -f /opt/lifetime/deploy/compose.vps.yaml "$@"; }
root_sql() {
    dc exec -T mysql sh -c 'umask 077; printf "[client]\nuser=root\npassword=%s\n" "$MYSQL_ROOT_PASSWORD" > /tmp/lifetime-root.cnf; exec mysql --defaults-extra-file=/tmp/lifetime-root.cnf --no-login-paths "$@"' sh "$@"
}
cli() { dc exec -T app flask --app lifetime "$@"; }
certbot() {
    docker run --rm --memory 256m --cpus 0.5 \
        -v /opt/lifetime/certificates:/etc/letsencrypt \
        -v /opt/lifetime/acme:/var/www/acme \
        "$CERTBOT_IMAGE" "$@"
}
case "${1:-status}" in
    init)
        if test -e .initialized; then
            echo 'Already initialized: use the documented backup/upgrade workflow.' >&2
            exit 1
        fi
        dc config --quiet
        dc build app
        dc up -d mysql --wait --wait-timeout 240
        root_sql <<SQL
REVOKE ALL PRIVILEGES ON lifetime.* FROM 'lifetime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON lifetime.* TO 'lifetime'@'%';
CREATE USER IF NOT EXISTS 'lifetime_migrate'@'%' IDENTIFIED BY '$MIGRATION_PASSWORD';
GRANT ALL PRIVILEGES ON lifetime.* TO 'lifetime_migrate'@'%';
SQL
        DB_PASSWORD="$MIGRATION_PASSWORD" dc run --no-deps --rm -e DB_USER=lifetime_migrate -e DB_PASSWORD app flask --app lifetime migrate
        DB_PASSWORD="$MIGRATION_PASSWORD" dc run --no-deps --rm -e DB_USER=lifetime_migrate -e DB_PASSWORD app flask --app lifetime import-data
        dc up -d app proxy --wait --wait-timeout 120
        dc exec -T proxy nginx -t
        touch .initialized
        ;;
    tls)
        certbot certonly --webroot -w /var/www/acme -d lifetime.ukubuka.net \
            --non-interactive --agree-tos --register-unsafely-without-email
        cp deploy/nginx.vps-tls.conf proxy/20-tls.conf
        dc exec -T proxy nginx -t
        dc exec -T proxy nginx -s reload
        curl --retry 5 --retry-all-errors --retry-delay 1 --resolve lifetime.ukubuka.net:443:127.0.0.1 --fail --silent --show-error https://lifetime.ukubuka.net/readyz
        ;;
    renew)
        certbot renew --quiet
        dc exec -T proxy nginx -t
        dc exec -T proxy nginx -s reload
        ;;
    renew-check)
        certbot renew --dry-run
        ;;
    maintenance)
        # Rotate, reopen, ingest and only remove completed files after verified success.
        if test -s edge/edge.jsonl; then
            rotated="edge-$(date -u +%Y%m%dT%H%M%S)-$$.jsonl"
            mv edge/edge.jsonl "edge/$rotated"
            install -o 10001 -g 10001 -m 0640 /dev/null edge/edge.jsonl
            dc exec -T proxy nginx -s reopen
            sleep 2
        fi
        for file in edge/edge-*.jsonl; do
            test -f "$file" || continue
            result=$(cli analytics ingest-edge "/var/lib/lifetime/$file")
            printf '%s\n' "$result"
            # All three counters must be zero. A nonmatching/missing counter fails closed.
            for key in dropped invalid_lines disabled; do
                printf '%s' "$result" | grep -Eq "\"$key\": 0([,}]|$)" || exit 1
            done
            rm -- "$file"
        done
        result=$(cli analytics replay)
        printf '%s\n' "$result"
        for key in failed corrupt; do
            printf '%s' "$result" | grep -Eq "\"$key\": 0([,}]|$)" || exit 1
        done
        ;;
    purge)
        result=$(cli analytics purge)
        printf '%s\n' "$result"
        if printf '%s' "$result" | grep -Eq '"database_failed": [1-9]'; then exit 1; fi
        ;;
    backup)
        destination="backups/$(date -u +%Y%m%dT%H%M%S)-$$"
        mkdir -m 0700 "$destination"
        root_sql --execute='SELECT VERSION(), DATABASE();' lifetime
        dc exec -T mysql mysqldump --defaults-extra-file=/tmp/lifetime-root.cnf --no-login-paths \
            --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF \
            --default-character-set=utf8mb4 lifetime | gzip > "$destination/lifetime.sql.gz"
        test -s "$destination/lifetime.sql.gz"
        gzip -t "$destination/lifetime.sql.gz"
        tar --exclude='state/.gunicorn' -czf "$destination/config-state.tgz" .env state certificates deploy proxy
        docker image inspect "$LIFETIME_IMAGE" --format '{{.Id}}' > "$destination/image-id.txt"
        cp VERSION "$destination/VERSION"
        root_sql --batch --execute='SELECT version_num FROM alembic_reference_version; SELECT version_num FROM alembic_version; SELECT * FROM active_reference;' lifetime > "$destination/schema-dataset.txt"
        (cd "$destination" && sha256sum lifetime.sql.gz config-state.tgz > SHA256SUMS)
        printf 'Backup created: /opt/lifetime/%s\n' "$destination"
        # Dedicated backup children only; never follow symlinks or touch other projects.
        find /opt/lifetime/backups -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf -- {} +
        ;;
    status)
        dc ps
        cli version
        cli analytics report --group overview
        ;;
    *) echo 'Usage: vps-admin.sh init|tls|renew|renew-check|maintenance|purge|backup|status' >&2; exit 2 ;;
esac
