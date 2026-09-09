# Source catalog

The September 9, 2026 expansion configures **22 sources**, up from eight. All 14 new
adapters were exercised against live public counters before publication, without
writing to the retained local history database. Production publishes each new source
only after its first accepted collection. Current counts and observation times belong
in the public API, rather than a static table here.

## Measurement registry

Paths below are relative to the registered canonical domain. `observed` means a
counter reported by that community; it does not imply independently audited accuracy,
absence of caching, or unique images across different sites. `estimated` preserves the
Danbooru count endpoint's estimate semantics.

| Source / target key | Canonical domain | Measurement | Provenance |
| --- | --- | --- | --- |
| Danbooru / `danbooru` | danbooru.donmai.us | `/counts/posts.json` | estimated |
| Safebooru / `safebooru` | safebooru.org | DAPI XML root count | observed |
| Konachan / `konachan` | konachan.com | `/post.xml?limit=1` root count | observed |
| Konachan Safe / `konachan-safe` | konachan.net | `/post.xml?limit=1` root count | observed |
| Yande.re / `yandere` | yande.re | `/post.xml?limit=1` root count | observed |
| e621 / `e621` | e621.net | `/` homepage digit counter | observed |
| Derpibooru / `derpibooru` | derpibooru.org | Philomena search total, Everything filter 56027 | observed |
| AIBooru / `aibooru` | aibooru.online | `/counts/posts.json` | estimated |
| Gelbooru / `gelbooru` | gelbooru.com | `/` homepage digit counter | observed |
| Sakugabooru / `sakugabooru` | www.sakugabooru.com | `/post.xml?limit=1` root count | observed |
| Furbooru / `furbooru` | furbooru.org | Philomena search total, Everything filter 2 | observed |
| Tantabus / `tantabus` | tantabus.ai | Philomena search total, Everything filter 2 | observed |
| e6AI / `e6ai` | e6ai.net | `/` homepage digit counter | observed |
| Xbooru / `xbooru` | xbooru.com | DAPI XML root count | observed |
| The Big ImageBoard / `tbib` | tbib.org | DAPI XML root count | observed |
| Realbooru / `realbooru` | realbooru.com | `/` homepage digit counter | observed |
| Rule34 Paheal / `rule34-paheal` | rule34.paheal.net | `/` labelled post count | observed |
| HypnoHub / `hypnohub` | hypnohub.net | `/` homepage digit counter | observed |
| e-shuushuu / `e-shuushuu` | e-shuushuu.net | `/api/v1/images?per_page=1`, `total` | observed |
| Cosbooru / `cosbooru` | cos.lycore.co | `/counts/posts.json` | estimated |
| Manebooru / `manebooru` | manebooru.art | `/pages/stats`, non-deleted image total | observed |
| Ponerpics / `ponerpics` | ponerpics.org | `/pages/stats`, non-deleted image total | observed |

DAPI path: `/index.php?page=dapi&s=post&q=index&limit=1`.
Philomena search path: `/api/v1/json/search/images?q=*&per_page=1&filter_id=ID`.
The exact measurement URL is included as `source_url` on snapshots and eligible
rankings. No post IDs are used as estimates of collection size.

Furbooru and Tantabus also request `/api/v1/json/filters/2` during every inspection.
A changed or missing filter, hidden/spoilered tags, or a complex expression blocks the
candidate before its total is requested. Manebooru's Everything filter hides a tag;
Ponerpics' Everything filter has a complex exclusion. Their explicitly labelled
site-wide statistics avoid those subsets and exclude deleted/merged images.

Gelbooru's public homepage provides a counter even though its DAPI requires credentials.
Realbooru's DAPI rejects anonymous requests; its homepage provides an aggregate counter.
These adapters use those public pages directly and do not attempt authentication or
challenge bypass. e621 and e6AI use homepage counters, not capped search endpoints.

## Editorial classification

The machine-readable taxonomy is at `/api/v1/categories`. The initial ten categories
remain supported; **Animation, Cosplay, and Photography** bring the total to thirteen.
They describe the community's focus, not a complete inventory of all accepted tags.
For example, `ai-generated` marks communities focused on AI, not every community whose
rules permit some assisted artwork.

The source registry stores reference URLs and the review date. New classifications
were reviewed on September 9, 2026. `classification.notes` carries relevant context
and is shown in the detail panel:

- Safe includes only Safebooru and Konachan Safe. An anonymous default filter does not
  make a mixed community exclusively Safe.
- Sakugabooru focuses on animation; its [tagging rules](https://www.sakugabooru.com/wiki/show?title=tag_guidelines)
  also provide for nudity and graphic violence, so it is classified NSFW.
- e-shuushuu prohibits hentai, but its [rules](https://e-shuushuu.net/rules) permit
  artistic nudity. It is conservatively excluded from exclusively Safe results and
  has no Hentai category. Its [about page](https://e-shuushuu.net/about) describes its
  anime/manga focus, and the rules explicitly allow limited cosplay uploads.
- Cosbooru's [description](https://cos.lycore.co/wiki_pages/help:home) focuses on
  cosplay photography. Its rating rules cover mature material.
- Furbooru's [rules](https://furbooru.org/pages/rules) describe furry fan art;
  e6AI's [about page](https://e6ai.net/help/about) describes AI-generated furry content;
  Tantabus' [rules](https://tantabus.ai/pages/rules) describe its AI/pony community.
- [Gelbooru](https://gelbooru.com/index.php?page=aboutus),
  [Xbooru](https://xbooru.com/index.php?page=help&topic=rating),
  [TBIB](https://tbib.org/index.php?page=help&topic=rating),
  [HypnoHub](https://hypnohub.net/index.php?page=help&topic=rating),
  [Realbooru](https://realbooru.com/tos.php), and [Paheal](https://rule34.paheal.net/)
  are classified NSFW based on their public identity and content rules.
- [Manebooru](https://manebooru.art/pages/rules) and [Ponerpics](https://ponerpics.org/pages/rules)
  are pony fan-art communities accepting mature material.

Konachan Safe keeps `subset_of=konachan`. TBIB and pony archives also contain imports
or cross-posts; independent domains do not mean independent sets of images. The global
ecosystem summary remains global when filters change, and never sums these counts as
unique publications.

## Collection and unavailable candidates

`collect_catalog` derives its 21 daily targets from the registry, excluding Danbooru.
It processes them sequentially, isolates failures, and keeps the 20-hour minimum
interval and per-target locks. New sources with only one accepted observation have no
growth value. Failures retain the last accepted observation and its original time.

Candidates without a verified usable counter remain outside the registry: e926 and
several other sites blocked anonymous access; Rule34.xxx's API required authentication;
Ponybooru timed out; Twibooru's search count was reachable but its filter configuration
could not be independently verified. Zerochan returned posts without an aggregate total.
These are access/measurement findings, not claims that those communities are empty.
No placeholder rows, fabricated estimates, mirror padding, or synthetic history are
published. All the Fallen and categories for sexual content involving minors remain
outside this release.

See [production collection](production-collection.md) for deployment and scheduling.
