#!/usr/bin/env bash
set -euo pipefail
cd /opt/lifetime
test ! -e .env
tar -xzf source.tgz
umask 077
nginx_image=$(sudo -n docker image inspect nginx:stable-alpine --format '{{index .RepoDigests 0}}')
certbot_image=$(sudo -n docker image inspect certbot/certbot:latest --format '{{index .RepoDigests 0}}')
{
    printf 'LIFETIME_IMAGE=lifetime:2.1.0-vps-20261031\n'
    printf 'NGINX_IMAGE=%s\nCERTBOT_IMAGE=%s\n' "$nginx_image" "$certbot_image"
    for key in DB_PASSWORD MYSQL_ROOT_PASSWORD MIGRATION_PASSWORD ANALYTICS_SECRET; do
        printf '%s=%s\n' "$key" "$(openssl rand -hex 32)"
    done
} > .env
chmod 600 .env
sudo -n install -d -o 10001 -g 10001 -m 0700 state
sudo -n install -d -o 10001 -g 10001 -m 0750 edge
sudo -n install -o 10001 -g 10001 -m 0640 /dev/null edge/edge.jsonl
mkdir -m 0755 proxy acme
sudo -n install -d -m 0700 certificates backups
cp deploy/nginx.vps.conf proxy/10-http.conf
sudo -n docker inspect kyiv-alert-alert-1 --format '{{.Id}} {{.State.StartedAt}} {{.RestartCount}} {{.State.Health.Status}}' > kyiv-alert-before.txt
sudo -n bash deploy/vps-admin.sh init
