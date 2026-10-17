#!/bin/sh
set -eu

: "${ORIGIN_TOKEN:?ORIGIN_TOKEN is required}"
if [ "${#ORIGIN_TOKEN}" -ne 48 ]; then
    echo 'ORIGIN_TOKEN must contain exactly 48 lowercase hexadecimal characters' >&2
    exit 1
fi
case "$ORIGIN_TOKEN" in
    *[!0-9a-f]*) echo 'ORIGIN_TOKEN must be lowercase hexadecimal' >&2; exit 1 ;;
esac
