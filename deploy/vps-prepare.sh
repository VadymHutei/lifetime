#!/usr/bin/env bash
set -euo pipefail
test "$(sudo -n id -u)" = 0
test ! -e /opt/lifetime
sudo -n install -d -m 0750 -o codex -g codex /opt/lifetime
sudo -n docker pull nginx:stable-alpine
sudo -n docker pull certbot/certbot:latest
sudo -n docker image inspect nginx:stable-alpine certbot/certbot:latest --format '{{index .RepoDigests 0}}'
