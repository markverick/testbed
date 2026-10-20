import unittest
from datetime import datetime, timedelta, timezone

from internal.ndnd_prefix import AnnouncedPrefix, parse_status_report, plan_prefix_reconciliation


class TestNdndPrefixReconciliation(unittest.TestCase):
    def test_parses_rib_and_only_local_dv_prefixes_from_status_xml(self):
        output = b'''<?xml version="1.0"?>
<ndndStatus dvState="available">
  <rib>
    <entry prefix="/ndnd/ucla/ping">
      <route faceId="14" origin="app" cost="0" flags="child-inherit" />
      <route faceId="7" origin="dv" cost="1" flags="" />
    </entry>
    <entry prefix="/ndnd/CA"><route faceId="22" origin="app" cost="0" flags="" /></entry>
  </rib>
  <dv routerName="/ndnd/ucla" prefixListState="available">
    <prefixState>
      <entry prefix="/ndnd/ucla/ping" router="/ndnd/ucla">
        <validity><notAfter>20261018T120000</notAfter></validity>
        <nextHop faceId="14" cost="0" />
      </entry>
      <entry prefix="/ndnd/ucla/ping" router="/ndnd/arizona">
        <nextHop faceId="5" cost="0" />
      </entry>
    </prefixState>
  </dv>
</ndndStatus>'''
        registered, announced = parse_status_report(output, "/ndnd/ucla")
        self.assertEqual({"/ndnd/ucla/ping": {14}, "/ndnd/CA": {22}}, registered)
        self.assertEqual(frozenset({14}), announced["/ndnd/ucla/ping"].faces)
        self.assertEqual(datetime(2026, 10, 18, 12, tzinfo=timezone.utc),
                         announced["/ndnd/ucla/ping"].not_after)

    def test_withdraws_stale_face_and_announces_changed_face(self):
        operations = plan_prefix_reconciliation(
            {"/ndnd/ucla/ping", "/ndnd/CA"},
            {"/ndnd/ucla/ping": {14}},
            {
                "/ndnd/ucla/ping": AnnouncedPrefix(frozenset({5}), None),
                "/ndnd/CA": AnnouncedPrefix(frozenset({9}), None),
            },
            datetime(2026, 10, 18, 11, tzinfo=timezone.utc),
            timedelta(minutes=10),
        )
        self.assertEqual([
            ("withdraw", "/ndnd/CA", 9),
            ("withdraw", "/ndnd/ucla/ping", 5),
            ("announce", "/ndnd/ucla/ping", 14),
        ], operations)

    def test_does_not_reannounce_stable_unexpired_face(self):
        prefix = "/ndnd/ucla/ping"
        now = datetime(2026, 10, 18, 11, tzinfo=timezone.utc)
        announced = {prefix: AnnouncedPrefix(frozenset({14}), now + timedelta(minutes=30))}
        self.assertEqual([], plan_prefix_reconciliation(
            {prefix}, {prefix: {14}}, announced, now, timedelta(minutes=10)))

    def test_refreshes_stable_face_only_near_expiry(self):
        prefix = "/ndnd/ucla/ping"
        now = datetime(2026, 10, 18, 11, tzinfo=timezone.utc)
        announced = {prefix: AnnouncedPrefix(frozenset({14}), now + timedelta(minutes=8))}
        self.assertEqual([("announce", prefix, 14)], plan_prefix_reconciliation(
            {prefix}, {prefix: {14}}, announced, now, timedelta(minutes=10)))


if __name__ == "__main__":
    unittest.main()
