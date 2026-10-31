#!/usr/bin/env bash
# Socket-activated loopback endpoint for SSH forwarding into the private network.
set -euo pipefail
mysql_ip=$(docker inspect lifetime-mysql-1 --format '{{with index .NetworkSettings.Networks "lifetime_backend"}}{{.IPAddress}}{{end}}')
test -n "$mysql_ip"
# Only discovery needs root/Docker access; the TCP forwarder runs as nobody.
exec /usr/bin/setpriv --reuid=65534 --regid=65534 --clear-groups \
    /usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=30s "$mysql_ip:3306"
