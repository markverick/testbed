import unittest

from ndn.encoding import Name

from internal.ndnd import is_certificate_request_name


class TestCertificateRequestName(unittest.TestCase):
    def test_accepts_router_certificate_request_name(self):
        name = Name.normalize('/ndnd/ucla/32=DV/KEY/key-id/self/v=1')
        self.assertTrue(is_certificate_request_name('/ndnd/ucla/32=DV', name))

    def test_rejects_name_outside_allowed_router_identity(self):
        name = Name.normalize('/ndnd/arizona/32=DV/KEY/key-id/self/v=1')
        self.assertFalse(is_certificate_request_name('/ndnd/ucla/32=DV', name))

    def test_rejects_extra_name_suffix(self):
        name = Name.normalize('/ndnd/ucla/32=DV/extra/KEY/key-id/self/v=1')
        self.assertFalse(is_certificate_request_name('/ndnd/ucla/32=DV', name))

    def test_rejects_wrong_key_component(self):
        name = Name.normalize('/ndnd/ucla/32=DV/OTHER/key-id/self/v=1')
        self.assertFalse(is_certificate_request_name('/ndnd/ucla/32=DV', name))

    def test_rejects_non_version_final_component(self):
        name = Name.normalize('/ndnd/ucla/32=DV/KEY/key-id/self/final')
        self.assertFalse(is_certificate_request_name('/ndnd/ucla/32=DV', name))


if __name__ == '__main__':
    unittest.main()