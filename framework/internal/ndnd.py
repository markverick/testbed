import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from Cryptodome.PublicKey import ECC, RSA
from ndn.app_support.security_v2 import parse_certificate
from ndn.encoding import Component, Name, parse_data
from ndn.encoding import ContentType, SignatureType
from ndn.security.validator import verify_ecdsa, verify_rsa


def _verify_certificate(wire: bytes, issuer_wire: bytes) -> bool:
    cert = parse_certificate(wire)
    issuer = parse_certificate(issuer_wire)
    if cert.meta_info.content_type != ContentType.KEY or issuer.meta_info.content_type != ContentType.KEY:
        return False
    locator = cert.signature_info.key_locator
    if locator is None or Name.to_bytes(locator.name) not in (
            Name.to_bytes(issuer.name[:-2]), Name.to_bytes(issuer.name)):
        return False
    _, _, _, pointers = parse_data(wire)
    if cert.signature_info.signature_type == SignatureType.SHA256_WITH_ECDSA:
        return verify_ecdsa(ECC.import_key(bytes(issuer.content)), pointers)
    if cert.signature_info.signature_type == SignatureType.SHA256_WITH_RSA:
        return verify_rsa(RSA.import_key(bytes(issuer.content)), pointers)
    return False


def is_certificate_request_name(prefix: str, name: list[bytes]) -> bool:
    prefix_name = Name.normalize(prefix)
    if len(name) != len(prefix_name) + 4 or name[:len(prefix_name)] != prefix_name:
        return False
    return (name[len(prefix_name)] == Component.from_str('KEY')
            and name[len(prefix_name) + 2] == Component.from_str('self')
            and Component.get_type(name[-1]) == Component.TYPE_VERSION)


def bootstrap_ndnd_root(profile_url: str, certificate_url: str, expected_sha256: str,
                        network: str, anchor_path: str) -> str:
    if urlsplit(profile_url).scheme != 'https' or urlsplit(certificate_url).scheme != 'https':
        raise ValueError('NDNd root bootstrap URLs must use HTTPS')
    with urlopen(profile_url, timeout=20) as response:
        profile = json.loads(response.read())
    if profile.get('schema_version') != 1 or profile.get('ca_prefix') != network:
        raise ValueError(f'NDNd CA profile does not describe network {network}')
    if profile.get('root_certificate_url') != certificate_url:
        raise ValueError('NDNd CA profile root certificate URL does not match configuration')
    if not expected_sha256:
        raise ValueError('Pin ndnd_root_certificate_sha256 before enabling NDNd DV')
    if profile.get('root_certificate_sha256') != expected_sha256:
        raise ValueError('NDNd CA profile fingerprint does not match configured pin')
    with urlopen(certificate_url, timeout=20) as response:
        published_cert = response.read()
    if published_cert[:1] == b'\x06':
        wire = published_cert
    else:
        wire = base64.b64decode(b''.join(published_cert.split()), validate=True)
    cert = parse_certificate(wire)
    cert_name = Name.to_str(cert.name)
    if Name.to_str(cert.name[:-4]) != network:
        raise ValueError(f'NDNd root certificate identity is not {network}')
    if profile.get('root_certificate_name') != cert_name:
        raise ValueError('NDNd root certificate name does not match the published profile')
    if hashlib.sha256(wire).hexdigest() != expected_sha256:
        raise ValueError('NDNd root certificate fingerprint does not match configured pin')
    if not _verify_certificate(wire, wire):
        raise ValueError('NDNd root certificate is not self-signed by its own key')

    path = Path(anchor_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    content = base64.encodebytes(wire)
    if path.exists() and path.read_bytes() == content:
        return cert_name
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return cert_name


def validate_ndnd_topology(hostvars: dict, network: str, links: list, root_cert_name: str = '') -> None:
    enabled = {name: values for name, values in hostvars.items()
               if values.get('ndnd_enabled', False)}
    dv_enabled = {name: values for name, values in hostvars.items()
                  if values.get('ndnd_dv_enabled', False)}
    network_name = Name.normalize(network)
    router_names = {}

    for host, values in enabled.items():
        prefix = values.get('ndnd_router_prefix')
        if not isinstance(prefix, str) or not prefix:
            raise ValueError(f'{host}: ndnd_router_prefix is required when ndnd_enabled is true')
        try:
            router = Name.normalize(prefix)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{host}: invalid ndnd_router_prefix {prefix!r}: {exc}') from exc
        if len(router) != len(network_name) + 1 or router[:len(network_name)] != network_name:
            raise ValueError(f'{host}: ndnd_router_prefix must be exactly one component below {network}')
        wire_name = Name.to_bytes(router)
        if wire_name in router_names:
            raise ValueError(f'{host}: ndnd_router_prefix {prefix} duplicates {router_names[wire_name]}')
        router_names[wire_name] = host

    for host in dv_enabled:
        if host not in enabled:
            raise ValueError(f'{host}: ndnd_dv_enabled requires ndnd_enabled')
    if dv_enabled and not root_cert_name:
        raise ValueError('ndnd_root_cert_name must be set before enabling NDNd DV')
    if root_cert_name:
        try:
            root_name = Name.normalize(root_cert_name)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'invalid ndnd_root_cert_name {root_cert_name!r}: {exc}') from exc
        if not network_name == root_name[:len(network_name)]:
            raise ValueError(f'ndnd_root_cert_name must be under {network}')

    if enabled and not links:
        raise ValueError('ndnd_links must define the topology when NDNd is enabled')
    seen_links = set()
    for link in links:
        if not isinstance(link, dict):
            raise ValueError(f'ndnd_links entry must be a mapping: {link!r}')
        a, b, cost = link.get('a'), link.get('b'), link.get('cost')
        if a not in enabled or b not in enabled:
            raise ValueError(f'ndnd_links endpoints must be ndnd_enabled hosts: {a!r}, {b!r}')
        if a == b:
            raise ValueError(f'ndnd_links cannot contain a self-link: {a}')
        if isinstance(cost, bool) or not isinstance(cost, int) or cost != 1:
            raise ValueError('NDNd DV currently uses unit link cost; ndnd_links cost must be 1')
        key = frozenset((a, b))
        if key in seen_links:
            raise ValueError(f'ndnd_links contains duplicate link: {a}-{b}')
        seen_links.add(key)
    if enabled and not seen_links:
        raise ValueError('ndnd_links must contain at least one link')