import json
import unittest

import jinja2
import yaml
from ndn.app_support.light_versec import compile_lvs

from internal import conf
from internal.render import JINJA_FUNCTIONS


class TestNdndTemplateRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = conf.get()
        cls.environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(cls.config.environment_path),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        cls.hostvars = {}
        from internal.utils import get_files
        import os
        for path in get_files(cls.config.host_vars_path):
            with open(path) as stream:
                host = os.path.basename(path)
                values = yaml.safe_load(stream) or {}
                values['inventory_hostname'] = host
                values.update(cls.config.globals)
                cls.hostvars[host] = values
        for host, values in cls.hostvars.items():
            if values.get('ndnd_enabled'):
                values['ndnd_dv_enabled'] = True
                values['ndnd_root_cert_name'] = '/ndnd/KEY/root/self/v=1'

    @classmethod
    def render_template(cls, template_path, host):
        values = cls.hostvars[host].copy()
        values['hostvars'] = cls.hostvars
        return cls.environment.get_template(template_path).render(**values, **JINJA_FUNCTIONS)

    def test_ndnd_router_names_peers_and_schema(self):
        expected = {
            'UCLA': ('/ndnd/ucla', {'ARIZONA', 'MEMPHIS'}),
            'ARIZONA': ('/ndnd/arizona', {'UCLA', 'MEMPHIS'}),
            'MEMPHIS': ('/ndnd/memphis', {'UCLA', 'ARIZONA'}),
        }
        for host, (router, peers) in expected.items():
            with self.subTest(host=host):
                fw = yaml.safe_load(self.render_template('templates/ndnd/yanfd.yml.j2', host))
                dv = yaml.safe_load(self.render_template('templates/ndnd-dv/dv.yml.j2', host))['dv']
                self.assertEqual(router, fw['fw']['router_name'])
                self.assertEqual('/ndnd', dv['network'])
                self.assertEqual(router, dv['router'])
                self.assertNotIn('local_prefixes', dv)
                expected_ips = {self.hostvars[peer]['host_ip'] for peer in peers}
                self.assertEqual(expected_ips, {uri['uri'].split('//')[1].split(':')[0] for uri in dv['neighbors']})
                self.assertTrue(all(uri['uri'].endswith(':6364') for uri in dv['neighbors']))

        schema = self.render_template('templates/ndnd-dv/dv-schema.lvs.j2', 'UCLA')
        self.assertTrue(compile_lvs(schema).encode())

    def test_public_feed_describes_the_same_router_topology(self):
        feed = json.loads(self.render_template('templates/file-server/ndnd/ndnd-network.json.j2', 'UCLA'))
        self.assertEqual('/ndnd', feed['network_prefix'])
        nodes = {node['inventory_name']: node for node in feed['nodes']}
        self.assertEqual({'UCLA', 'ARIZONA', 'MEMPHIS'}, set(nodes))
        for host, node in nodes.items():
            self.assertEqual(self.hostvars[host]['ndnd_router_prefix'], node['router_prefix'])
            self.assertEqual(node['router_prefix'] + '/32=DV', node['router_identity'])
            self.assertEqual(6364, node['udp_port'])
        self.assertEqual({
            frozenset(('/ndnd/ucla', '/ndnd/arizona')),
            frozenset(('/ndnd/ucla', '/ndnd/memphis')),
            frozenset(('/ndnd/arizona', '/ndnd/memphis')),
        }, {frozenset((link['node_a'], link['node_b'])) for link in feed['links']})
        self.assertTrue(all(link['cost'] == 1 for link in feed['links']))


if __name__ == '__main__':
    unittest.main()
