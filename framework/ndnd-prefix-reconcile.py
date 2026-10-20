#!/usr/bin/env python3

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import yaml

from internal import compose, conf
from internal.ndnd_prefix import parse_status_report, plan_prefix_reconciliation


ANNOUNCEMENT_TTL_MS = 60 * 60 * 1000
REFRESH_BEFORE = timedelta(minutes=10)


def _exec(service: str, command: list[str]) -> tuple[int, bytes]:
    code, output = compose.exec(service, command, timeout=20)
    if code != 0:
        print(f"NDNd prefix reconciliation: {service} command failed: {command}", file=sys.stderr)
        if output:
            print(output.decode(errors="replace"), file=sys.stderr)
    return code, output


def main() -> int:
    node = os.getenv("MANAGED_HOST")
    if not node:
        print("NDNd prefix reconciliation: MANAGED_HOST is not set", file=sys.stderr)
        return 2

    config = conf.get()
    host_path = Path(config.host_vars_path) / node
    with host_path.open() as stream:
        host = yaml.safe_load(stream) or {}
    if not host.get("ndnd_dv_enabled", False):
        return 0

    router = host.get("ndnd_router_prefix")
    if not router:
        print(f"NDNd prefix reconciliation: {node} has no ndnd_router_prefix", file=sys.stderr)
        return 2

    prefixes = {router + "/ping"}
    if node == config.globals.get("ndnd_ca_host"):
        prefixes.add(config.globals["ndnd_dv_network"] + "/CA")

    code, report = _exec("ndnd", ["/ndnd", "fw", "status-report"])
    if code != 0:
        return code

    registered, announced = parse_status_report(report, router)
    operations = plan_prefix_reconciliation(
        prefixes, registered, announced, datetime.now(timezone.utc), REFRESH_BEFORE)
    for action, prefix, face in operations:
        command = ["/ndnd", "dv", f"prefix-{action}", f"prefix={prefix}", f"face={face}"]
        if action == "announce":
            command.extend(("cost=0", f"expires={ANNOUNCEMENT_TTL_MS}"))
        code, output = _exec("ndnd-dv", command)
        if code != 0:
            return code
        if output:
            print(output.decode(errors="replace").strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())