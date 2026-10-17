#!/usr/bin/env python3
"""Create a private origin credential without printing it or rotating it."""

import argparse
import ipaddress
import os
from pathlib import Path
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-ip", default="127.0.0.1")
    parser.add_argument("--env-file", type=Path, default=Path("deploy/team.env"))
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.bind_ip)
    if not (address.is_loopback or address in ipaddress.IPv4Network("10.0.0.0/8")
            or address in ipaddress.IPv4Network("172.16.0.0/12")
            or address in ipaddress.IPv4Network("192.168.0.0/16")):
        parser.error("bind address must be loopback or an RFC 1918 private address")
    content = (
        f"TEAM_BIND_IP={address}\nTEAM_ORIGIN_PORT=18081\n"
        f"ORIGIN_TOKEN={secrets.token_hex(24)}\n"
    )
    # Exclusive creation prevents accidental credential rotation on reruns.
    fd = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write(content)
    print(f"Created {args.env_file} (mode 600); keep this file out of Git.")


if __name__ == "__main__":
    main()
