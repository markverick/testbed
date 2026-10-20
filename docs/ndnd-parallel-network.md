# NDNd Parallel Network Design

**Status:** Proposed; not deployed.

## Goal

Operate an NDNd/DV network alongside the existing NFD/NLSR testbed on selected
hosts, without changing the existing stack's names, certificates, routes, ports,
processes, or user-facing services.

The NDNd network must have an independent namespace and trust root. Its
bootstrap artifacts must be available without relying on the NDNd network.

## Requirements

The deployment must provide:

- A public data feed with each node's name, NDNd router prefix, IP addresses,
  links, and link costs.
- At least two UDP-reachable nodes, each running an NDNd-connected ping server.
- A public NDNd root certificate and CA profile.
- Names under `/ndnd`, with no collision with existing `/ndn` names.
- A public HTTPS origin for the feed and trust/bootstrap artifacts. Do not fetch
  these artifacts from the NDNd network itself.

## Names and Inventory

Use one DV network prefix, `/ndnd`. Do not split it into `/ndnd/edu`, `/ndnd/com`,
or other per-organization networks.

Each enabled host has an explicit, unique `ndnd_router_prefix` in host inventory:

```yaml
ndnd_enabled: true
ndnd_dv_enabled: false
ndnd_router_prefix: /ndnd/ucla
```

For the initial three routers, the proposed values are:

| Inventory host | NDNd router prefix |
| --- | --- |
| UCLA | `/ndnd/ucla` |
| ARIZONA | `/ndnd/arizona` |
| MEMPHIS | `/ndnd/memphis` |

These are explicit values, not derived from `site`, `default_prefix`, or the
uppercase inventory key. Validation must require that each enabled router name
is a direct child of `/ndnd` and is unique as an NDN name. Existing `site`,
`default_prefix`, `router_name`, advertised prefixes, and `is_root_ca` remain
unchanged and continue to configure the NFD/NLSR testbed.

The DV config uses `network: /ndnd` and the host's `ndnd_router_prefix` as
`router`. That satisfies the current DV rule requiring the router name to be
exactly one component below its network. The router certificate identity is
`<ndnd_router_prefix>/32=DV` (for example, `/ndnd/ucla/32=DV`). The forwarder's
`fw.router_name`, DV config, certificate request, trust schema, and feed must
all use the same inventory value.

## Independent Trust and CA

The NDNd trust hierarchy is independent of the existing `/ndn` testbed root:

- Root identity and network prefix: `/ndnd`.
- A separate root signing key and persistent keychain, never copied from or
  shared with `root-ca-home`.
- One separately issued `/32=DV` router certificate per NDNd router prefix.
- A separate NDNd DV trust schema and pinned root anchor. Trust rules authorize
  only the `/ndnd` root and the configured router identities to sign their
  permitted DV data.
- Separate CA endpoint/configuration and issuance secret. Do not reuse the
  existing `/root-ca` endpoint, `/ndn` root certificate, site certificate,
  `ndn_repo_anchors`, or `is_root_ca` selector.

Select the NDNd CA host centrally in service configuration (initially UCLA),
not with a new overloaded NFD host flag. Keep private signing material outside
Git and inaccessible to router, forwarder, ping-server, and status containers.
Give each router its own key and certificate.

The NDNd Go repository provides an NDNcert client. After DV has converged,
operators can manually enroll a router key with:

```bash
mkdir -p dist/ndnd-dv-independent/enrollment
docker compose --profile ndnd-enroll run --rm ndnd-dv-enroll \
  sec keygen /ndnd/ucla/32=DV ecc secp256r1 \
  > dist/ndnd-dv-independent/enrollment/ucla-dv.key
docker compose --profile ndnd-enroll run --rm ndnd-dv-enroll \
  certcli /config/ndnd-root.ndncert \
  --key /config/enrollment/ucla-dv.key \
  --output /config/enrollment/ucla-dv \
  --challenge pin --no-probe
docker compose --profile ndnd-enroll run --rm -i ndnd-dv-enroll \
  sec key-import dir:///config/keys \
  < dist/ndnd-dv-independent/enrollment/ucla-dv.key
docker compose --profile ndnd-enroll run --rm -i ndnd-dv-enroll \
  sec key-import dir:///config/keys \
  < dist/ndnd-dv-independent/enrollment/ucla-dv.cert
```

The CA operator obtains the one-time PIN from the restricted CA logs and relays
it to the router operator through the approved out-of-band channel. Never put
the PIN, private key, or CA secret in the public profile or feed.

Run the pinned
`ghcr.io/ucla-irl/ndncert-ca:20250923` as a separate CA service with only the
NDNd socket and dedicated `/ndnd` keychain. Its `ndn-cxx` Face honors
`NDN_CLIENT_TRANSPORT=unix:///run/ndnd/ndnd.sock`; an isolated smoke test
confirmed that this image registers `/ndnd/CA` on a local NDNd forwarder.

Use NDNcert over NDNd for interactive client enrollment. For unattended router
bootstrap and renewal before/after DV routes are available, run a separate HTTPS
CSR signer at `/ndnd-ca/sign`, backed by the same `/ndnd` root key. Require a
distinct `VAR_NDND_ROOT_CA_SECRET`, allowed source IPs, and a per-host CSR prefix
restriction of `<ndnd_router_prefix>/32=DV`. The secret stays in each host's
untracked `.env`; it is not the existing `/ndn` root secret.

Enable `ndnd_enabled` first with `ndnd_dv_enabled: false`. The NDNd forwarder
and CA start, create the independent root identity, and publish its certificate
and profile over HTTPS. Compare the displayed root fingerprint through the
operator's trusted channel, then set the global
`ndnd_root_certificate_sha256` pin and enable `ndnd_dv_enabled`. Rendering must
fetch and validate the HTTPS profile and root certificate against that pin
before producing DV config. This gate prevents an unverified key fetched from
the same HTTPS origin from silently becoming a trust anchor.

## Public Bootstrap Artifacts

Publish these artifacts through the existing Caddy HTTPS static-file service at
`https://suns.cs.ucla.edu/file-server/ndnd/`. This origin is served outside the
NDNd network and must remain available when every NDNd node is down:

- `ndnd-network.json`: node names and prefixes, IP addresses, direct links, and
  costs. Generate it from the same explicit router and NDNd-link configuration
  used to render router configs; do not copy the NLSR neighbor graph implicitly.
- `ndnd-root.ndncert`: the public root certificate only.
- `ndnd-ca-profile.json`: public CA identity/prefix, profile and issuance policy,
  validity limits, NDNcert PIN challenge and client procedure, HTTPS bootstrap
  signer endpoint, root certificate URL/name, and fingerprint.
- The public DV trust schema, if clients or operators need it to validate DV
  data.

The feed must identify the actual NDNd links, not all NFD/NLSR adjacencies. DV
currently uses unit link cost; the feed reports cost `1` for each link. For the
initial mesh, explicitly record the UCLA-Arizona, UCLA-Memphis, and
Arizona-Memphis links. Submit the public feed URL and its schema to NDN-FCH
maintainers as the NDNd network feed; do not modify the
existing NFD testbed feed in place.

HTTPS authenticates the website, not automatically the NDN root key. Publish a
root-certificate fingerprint in the profile and require operators/clients to
pin or independently verify it before trusting the root certificate.

## Forwarding and Services

- NDNd forwarder: its own `/run/ndnd/ndnd.sock`, config, and UDP port 6364.
- DV router: separate `ndnd-dv` container using only the NDNd socket and its
  new, isolated `dist/ndnd-dv-independent` keychain/config; network peers are
  permanent UDP faces over port 6364. Preserve existing `/ndn` DV key material.
- A host-cron reconciliation reads the current RIB face for each configured app
  prefix, then uses `ndnd dv prefix-announce ... face=<face-id>` to install the
  local PET next hop and advertise it through DV. It withdraws announcements
  whose app route is no longer registered. This uses the existing NDNd image;
  no source patch or NLSR registration is required.
- Ping responder: run an NDNd-compatible ping server on at least two enabled
  nodes using the NDNd transport/socket. Do not mount `/run/nfd` or depend on
  NLSR for NDNd ping registration.
- Keep the existing NFD/NLSR services on `/run/nfd` and port 6363 unchanged.
- Do not add Certbot, WebTransport, or public WebSocket access as part of this
  design.

## Rollout and Acceptance

1. Validate all enabled router prefixes are unique direct children of `/ndnd`;
   validate link endpoints and positive costs.
2. Generate the NDNd trust schema and per-node configs from the explicit
   inventory and NDNd topology; render-check UCLA, Arizona, and Memphis.
3. Create the independent `/ndnd` root key and certificate in protected storage.
   Issue router certificates from it and verify their chains and identities
   against the new NDNd anchor and schema. Confirm no `/ndn` anchor or private
   key is mounted into NDNd CA/DV services.
4. Publish and fetch the feed, root certificate, CA profile, fingerprint, and
  trust schema from `https://suns.cs.ucla.edu/file-server/ndnd/` without using
  an NDNd Interest.
5. Start the three NDNd forwarders and DV routers without changing NFD/NLSR.
   Verify NDNd DV neighbors and learned routes.
6. Verify the reconciler announces ping and CA prefixes with the current local
  face IDs, then restart an app and confirm its new face is reannounced.
7. Verify UDP reachability and successful NDNd ping requests to responders on
   at least two nodes. Confirm the NFD UDP port, socket, routes, and services
   remain unchanged.
8. Provide the feed URL to NDN-FCH maintainers and confirm it contains all
   required fields before requesting FCH inclusion.

Do not deploy until every acceptance item passes. Rollback disables the NDNd
profile/services and removes their listener from the selected hosts; it does not
modify NFD/NLSR configuration or trust.
