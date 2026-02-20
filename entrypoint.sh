#!/bin/sh
set -e

# Fix ownership of /data for bind mounts (runs as root)
chown -R ksef:ksef /data 2>/dev/null || true

# Drop privileges to ksef user and exec the main process
exec gosu ksef python -u main.py
