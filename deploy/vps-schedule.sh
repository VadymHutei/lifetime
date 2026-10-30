#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0
for action in maintenance purge backup renew; do
    cat > "/etc/systemd/system/lifetime-$action.service" <<EOF
[Unit]
Description=LifeTime $action
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/flock -w 120 /run/lifetime-maintenance.lock /bin/bash /opt/lifetime/deploy/vps-admin.sh $action
TimeoutStartSec=600
Nice=10
EOF
    case "$action" in
        maintenance) schedule='*:0/5';;
        purge) schedule='*-*-* 03:15:00 UTC';;
        backup) schedule='*-*-* 03:30:00 UTC';;
        renew) schedule='*-*-* 00,12:10:00 UTC';;
    esac
    cat > "/etc/systemd/system/lifetime-$action.timer" <<EOF
[Unit]
Description=Schedule LifeTime $action

[Timer]
OnCalendar=$schedule
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
EOF
done
systemctl daemon-reload
systemctl enable --now lifetime-maintenance.timer lifetime-purge.timer lifetime-backup.timer lifetime-renew.timer
systemctl list-timers 'lifetime-*' --no-pager
