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

Raw response bodies are transient parser input. Adapters retain only bounded response
evidence: endpoint identifier, HTTP status, truncated content type, and a SHA-256
fingerprint. Payload text, file/CDN URLs, and media bytes are not persisted or emitted
by the collection CLI.

## Explicit collection targets and policies

The manual CLI does not infer a family from an arbitrary URL. `CollectionTarget`
binds a fixed key and canonical URL to an adapter type and a
`SnapshotCollectionPolicy`; construction validates that their family and adapter
names agree.

| CLI target | Canonical URL | Adapter | Family | `total_posts` policy |
| --- | --- | --- | --- | --- |
| `danbooru` | `https://danbooru.donmai.us` | `DanbooruAdapter` | `danbooru` | `estimated`, `posts` |
| `safebooru` | `https://safebooru.org` | `GelbooruAdapter` | `gelbooru` | `observed`, `posts` |

The policy also owns the aggregate statistics source URL and chooses which previous
metric envelope is compatible as an anomaly baseline. A previous value with a
different provenance or unit is ignored instead of being compared.

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

Optional official Danbooru HTTP Basic Auth is configured with `DANBOORU_LOGIN` and
`DANBOORU_API_KEY`. Both non-blank values are required; otherwise requests remain
unauthenticated. Credentials are never placed in URLs or collection evidence.

HTTP 403 responses and responses marked `cf-mitigated: challenge` are classified as
`source_access_blocked`. They are not parsed as API data or retried. The collector
retains the endpoint identifier, HTTP status, content type, and response SHA-256,
while discarding the challenge body.

## Safebooru through the Gelbooru family

`GelbooruAdapter` supports Safebooru's public DAPI XML shape using `GET /index.php`:

- `page=dapi&s=post&q=index&limit=1` for detection, health, and the public
  `total_posts` count;
- `page=dapi&s=post&q=index&limit=<n>` for recent post metadata;
- `page=dapi&s=tag&q=index&name=<tag>` for each explicitly requested tag.

`total_posts` comes directly from the `<posts count="…">` attribute and is recorded
with `observed` provenance. A successful HTTP status is not sufficient validation:
the adapter also requires valid XML, the expected root element, a non-negative integer
count, and required post attributes.

The adapter maps post ID, rating, tag names, and an HTML post-page URL. Safebooru's
`change` attribute is not treated as an upload timestamp, so `created_at` remains
unknown. Any direct media attributes in the XML are discarded. Recent-post requests
are capped at 1,000; tag requests are capped at 25 explicit names. When `tag_names`
is `None`, no tag request is made.

Safebooru collection is available only through the explicit manual target in this
slice. No scheduler or systemd service/timer was added or changed.
