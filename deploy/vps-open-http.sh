#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0
install -d -m 0755 /opt/lifetime/acme/.well-known/acme-challenge
printf 'lifetime-acme-ready\n' > /opt/lifetime/acme/.well-known/acme-challenge/verification
chmod 0644 /opt/lifetime/acme/.well-known/acme-challenge/verification
ufw allow 80/tcp comment 'LifeTime HTTP and ACME'
ufw allow 443/tcp comment 'LifeTime HTTPS'
ufw status
curl --fail --silent --show-error -H 'Host: lifetime.ukubuka.net' http://127.0.0.1/.well-known/acme-challenge/verification
