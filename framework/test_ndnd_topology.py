import unittest

from internal.ndnd import validate_ndnd_topology


class TestNdndTopology(unittest.TestCase):
    def setUp(self):
        self.hostvars = {
            'UCLA': {'ndnd_enabled': True, 'ndnd_dv_enabled': True, 'ndnd_router_prefix': '/ndnd/ucla'},
            'ARIZONA': {'ndnd_enabled': True, 'ndnd_dv_enabled': True, 'ndnd_router_prefix': '/ndnd/arizona'},
            'MEMPHIS': {'ndnd_enabled': True, 'ndnd_dv_enabled': True, 'ndnd_router_prefix': '/ndnd/memphis'},
        }
        self.links = [
            {'a': 'UCLA', 'b': 'ARIZONA', 'cost': 1},
            {'a': 'UCLA', 'b': 'MEMPHIS', 'cost': 1},
            {'a': 'ARIZONA', 'b': 'MEMPHIS', 'cost': 1},
        ]

    def validate(self):
        validate_ndnd_topology(self.hostvars, '/ndnd', self.links, '/ndnd/KEY/root/self/v=1')

    def test_accepts_unique_direct_children_and_unit_mesh(self):
        self.validate()

    def test_rejects_missing_router_prefix(self):
        del self.hostvars['UCLA']['ndnd_router_prefix']
        with self.assertRaisesRegex(ValueError, 'ndnd_router_prefix is required'):
            self.validate()

    def test_rejects_nested_router_prefix(self):
        self.hostvars['UCLA']['ndnd_router_prefix'] = '/ndnd/edu/ucla'
        with self.assertRaisesRegex(ValueError, 'exactly one component'):
            self.validate()

    def test_rejects_duplicate_router_prefix(self):
        self.hostvars['ARIZONA']['ndnd_router_prefix'] = '/ndnd/ucla'
        with self.assertRaisesRegex(ValueError, 'duplicates UCLA'):
            self.validate()

    def test_rejects_dv_without_forwarder(self):
        self.hostvars['UCLA']['ndnd_enabled'] = False
        with self.assertRaisesRegex(ValueError, 'requires ndnd_enabled'):
            self.validate()

    def test_rejects_dv_without_root_anchor_name(self):
        with self.assertRaisesRegex(ValueError, 'ndnd_root_cert_name must be set'):
            validate_ndnd_topology(self.hostvars, '/ndnd', self.links)

    def test_rejects_unknown_link_endpoint(self):
        self.links[0]['b'] = 'UNKNOWN'
        with self.assertRaisesRegex(ValueError, 'endpoints must be ndnd_enabled'):
            self.validate()

    def test_rejects_non_unit_link_cost(self):
        self.links[0]['cost'] = 3
        with self.assertRaisesRegex(ValueError, 'cost must be 1'):
            self.validate()

    def test_rejects_duplicate_undirected_link(self):
        self.links.append({'a': 'ARIZONA', 'b': 'UCLA', 'cost': 1})
        with self.assertRaisesRegex(ValueError, 'duplicate link'):
            self.validate()


if __name__ == '__main__':
    unittest.main()