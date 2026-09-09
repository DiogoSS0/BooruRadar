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
| `konachan` | `https://konachan.com` | `MoebooruAdapter` | `moebooru` | `observed`, `posts` |
| `konachan-safe` | `https://konachan.net` | `MoebooruAdapter` | `moebooru` | `observed`, `posts` |
| `yandere` | `https://yande.re` | `MoebooruAdapter` | `moebooru` | `observed`, `posts` |
| `e621` | `https://e621.net` | `E621Adapter` | `e621` | `observed`, `posts` |
| `derpibooru` | `https://derpibooru.org` | `PhilomenaAdapter` | `philomena` | `observed`, `posts` |
| `aibooru` | `https://aibooru.online` | `DanbooruAdapter` | `danbooru` | `estimated`, `posts` |

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

Safebooru is included in the daily `collect_catalog` one-shot, alongside every other configured
source except Danbooru. Danbooru keeps its independent collector.

## Aggregate-only adapters

`aggregate.py` and `counters.py` contain counter adapters for the expanded catalog.
See the [source guide](source-catalog.md) for the complete endpoint registry. These
advertise only detection, health, and public statistics. Health reuses the validated
count from the current inspection; recent posts and tags are unsupported. A blocked
source fails once with bounded response evidence. HTTP success alone is insufficient:
missing, negative, fractional, boolean, or malformed counts are rejected.

- Moebooru: `GET /post.xml?limit=1`, root `<posts count="…">`. Discard post attributes.
  See [official API documentation](https://konachan.com/help/api).
- e621: `GET /`, digits inside exactly one `home-footer-counter` HTML element.
  The source uses cached `Post.fast_count`; reported values may lag by up to 20 hours.
  Never use `/posts/count.json` as a site total: it caps large results. No digit image
  is downloaded. See [homepage source](https://github.com/e621ng/e621ng/blob/master/app/views/static/home.html.erb)
  and [count implementation](https://github.com/e621ng/e621ng/blob/master/app/controllers/posts_controller.rb).
- Derpibooru: `GET /api/v1/json/search/images?q=*&per_page=1&filter_id=56027`.
  Extract the integer `total` and discard image objects. The public Everything filter
  was verified on 2026-09-08 to have no hidden/spoilered tags or hidden complex filter.
  See [official API documentation](https://derpibooru.org/pages/api).
- AIBooru: the existing Danbooru adapter and estimated-count policy. Danbooru
  credentials are never shared with this target.

- Furbooru and Tantabus: validate system filter 2 has no hidden/spoilered tags or
  complex expressions on each inspection, then read the search `total`. Filter drift
  fails before fetching a potentially partial count.
- Manebooru and Ponerpics: `/pages/stats`, the explicitly labelled non-deleted image
  total. Their Everything filters still exclude tags, so search counts are not used.
- Gelbooru, Realbooru, and HypnoHub: one contiguous sequence of `/counter/N.gif`
  image tags in the homepage HTML, checking that each `alt` agrees with its digit.
  Image bytes are never requested; visitor counters are ignored.
- Xbooru and TBIB: aggregate-only Gelbooru DAPI XML; discard post objects.
- Rule34 Paheal: the homepage's explicit `Serving N posts` text; discard other counts.
- e-shuushuu: `/api/v1/images?per_page=1`, extract `total` only.
- Cosbooru: `/counts/posts.json`, aggregate-only Danbooru estimate. No credentials
  or recent-post requests are shared with this target.

`targets.py` also owns the editorial classifications and reference URLs. These are
community-level descriptions, separate from observed/estimated metrics. Unknown
sources stay unclassified. Konachan Safe declares `subset_of=konachan`; its posts
overlap with the parent and must not be added to it as unique content.

New rows are created disabled. The collector enables a new source in the same
transaction that commits its first accepted snapshot; failed normalization or commit
leaves it unpublished. An already disabled source with accepted history is not
automatically re-enabled.
