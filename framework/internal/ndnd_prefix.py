import xml.etree.ElementTree as ET

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class AnnouncedPrefix:
    faces: frozenset[int]
    not_after: datetime | None


def _parse_time(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y%m%dT%H%M%S")
    return parsed.replace(tzinfo=timezone.utc)


def parse_status_report(
    output: bytes, router: str
) -> tuple[dict[str, set[int]], dict[str, AnnouncedPrefix]]:
    root = ET.fromstring(output)
    if root.tag != "ndndStatus":
        raise ValueError(f"unexpected NDNd status document root {root.tag!r}")
    if root.get("dvState") != "available":
        raise ValueError("DV status is unavailable")

    registered: dict[str, set[int]] = {}
    rib = root.find("rib")
    if rib is None:
        raise ValueError("NDNd status report has no RIB section")
    for entry in rib.findall("entry"):
        prefix = entry.get("prefix")
        if not prefix:
            continue
        for route in entry.findall("route"):
            face_id = route.get("faceId")
            if route.get("origin") == "app" and face_id is not None:
                registered.setdefault(prefix, set()).add(int(face_id))

    dv = root.find("dv")
    if dv is None or dv.get("routerName") != router:
        raise ValueError("DV router status is missing or does not match this host")
    if dv.get("prefixListState") != "available":
        raise ValueError("DV prefix state is unavailable")

    announced: dict[str, AnnouncedPrefix] = {}
    for entry in dv.findall("./prefixState/entry"):
        if entry.get("router") != router:
            continue
        prefix = entry.get("prefix")
        if not prefix:
            continue
        faces = frozenset(
            int(face_id)
            for hop in entry.findall("nextHop")
            if (face_id := hop.get("faceId")) is not None
        )
        validity = entry.find("validity")
        not_after = validity.findtext("notAfter") if validity is not None else None
        announced[prefix] = AnnouncedPrefix(
            faces=faces,
            not_after=_parse_time(not_after) if not_after else None,
        )
    return registered, announced


def plan_prefix_reconciliation(
    prefixes: set[str],
    registered: dict[str, set[int]],
    announced: dict[str, AnnouncedPrefix],
    now: datetime,
    refresh_before: timedelta,
) -> list[tuple[str, str, int]]:
    operations = []
    now = now.astimezone(timezone.utc)
    for prefix in sorted(prefixes):
        current_faces = registered.get(prefix, set())
        current = announced.get(prefix, AnnouncedPrefix(frozenset(), None))
        operations.extend(("withdraw", prefix, face)
                          for face in sorted(current.faces - current_faces))
        operations.extend(("announce", prefix, face)
                          for face in sorted(current_faces - current.faces))
        if current.not_after is not None and current.not_after <= now + refresh_before:
            operations.extend(("announce", prefix, face)
                              for face in sorted(current.faces & current_faces))
    return operations
