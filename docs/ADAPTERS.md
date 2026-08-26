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

An adapter must not download images or return direct media URLs; the project collects
public metadata only.

## Modern Danbooru

`DanbooruAdapter` supports the verified modern API shape using:

- `GET /posts.json` for detection, health, and recent post metadata;
- `GET /counts/posts.json` for `total_posts`;
- `GET /tags.json` for explicitly requested tag names.

Danbooru's count endpoint estimates by default, so `total_posts` is always recorded
with `estimated` provenance. Tag counts and mapped post metadata are `observed`.
Recent-post requests are capped at 100. Tag requests are capped at 25 explicit names;
when `tag_names` is `None`, the adapter returns no tags and performs no request. This
prevents an accidental full tag crawl.

The adapter maps only post ID, creation time, raw rating, tag names, and the HTML post
page URL. Media asset objects, direct file/CDN URLs, and image bytes are discarded.
