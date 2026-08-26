# Adapter Contract

Concrete adapters subclass `BooruAdapter`, declare a unique `adapter_name` and an
`AdapterFamily`, and implement six asynchronous operations:

1. `detect` performs read-only site-family detection.
2. `health_check` reports public endpoint health.
3. `discover_capabilities` reports the operations supported by that deployment.
4. `fetch_public_statistics` returns named metric envelopes.
5. `fetch_recent_posts` returns metadata only.
6. `fetch_tag_statistics` returns tag counters with provenance.

Adapters receive a shared `httpx.AsyncClient`; they do not create hidden global
clients. Callers can therefore apply a consistent user agent, timeout, connection
pool, and test transport.

Capability discovery lets partially compatible or configured deployments state what
they actually expose. If a method is called despite an absent capability, a concrete
adapter should raise `UnsupportedCapabilityError`.

## Family placement

- Danbooru implementations: `booruradar/adapters/danbooru/`
- Gelbooru implementations: `booruradar/adapters/gelbooru/`
- Shimmie implementations: `booruradar/adapters/shimmie/`
- Other site-specific implementations: `booruradar/adapters/custom/`

Milestone 0 defines these extension points but ships no concrete collector. An
adapter must not download images or return direct media URLs; the project collects
public metadata only.
