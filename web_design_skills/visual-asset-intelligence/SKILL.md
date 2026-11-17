---
name: visual-asset-intelligence
description: Find, rank, verify, credit, optimize, and integrate authorized visual assets for web, application, presentation, and game projects.
---

# Visual Asset Intelligence

## Objective and scope

Deliver real, relevant, properly attributed visual assets when a project needs
them. Cover photographs, products, people, vehicles, buildings, landscapes,
animals, illustrations, icons, logos, textures, covers, thumbnails, and game
resources. Determine target dimensions, format, aspect ratio, resolution, and
intended placement before selecting an asset.

This skill guides asset work; it does not grant network, filesystem, or command
permissions. Use NIANG IA's bounded visual-asset tools for provider requests,
downloads, registration, and verification. Never invent tool results.

## When to use

Use for an explicit image/asset request or when the described interface,
product, editorial story, game, or presentation depends on visual media. Do not
add stock photos to a text-only or intentionally image-free project.

## Compatible technologies

The workflow is framework-independent and supports HTML/CSS/JavaScript, React,
Vue, Angular, Svelte, Next.js, mobile/desktop applications, presentations, and
game projects. Use project-native asset directories and formats. Raster formats
include JPEG, PNG, WebP, and AVIF when the runtime supports it; use SVG only
when its source is trusted and its content is safe.

## Professional method

1. Inspect user-supplied assets first. Then inspect project-local assets. Reuse
   a local asset only when the user provided it or confirmed its usage rights.
2. Identify each placement and its required subject, composition, orientation,
   minimum dimensions, transparency needs, and expected file-size budget.
3. Write several concise, descriptive search queries. Include useful synonyms
   and try English when it improves provider results; do not send private
   project text or credentials to a provider.
4. Search the approved providers in order: Pixabay, Unsplash, then Pexels only
   when its use is explicitly approved and an existing key is configured.
   Never scrape search engines or bypass a provider's API.
5. Compare candidates by tags/description relevance, resolution, orientation,
   dimensions, and provider metadata. Do not accept the first result blindly.
   The host's numeric score cannot assess composition or semantic image content;
   preview and review those properties rather than claiming they were tested.
6. Use the `visual_asset_use` tool for the chosen result. Pixabay/Pexels images
   are downloaded only to a new project-relative path and are checked as image
   bytes. Unsplash API images must remain hotlinked to the URL returned by its
   API; never save those bytes locally. Selecting an Unsplash image triggers
   its required `download_location` event.
7. Add visible provider/photographer credits where required and preserve the
   provenance in `assets/visual-assets.json`. Integrate distinct images for
   distinct products or stories; do not repeat one image to fill a gallery.
8. Run `visual_asset_verify` after integration. Fix missing files, bad formats,
   duplicate hashes, missing credits, placeholder references, or unresolved
   registry entries. Report composition/visual review as not tested unless a
   real visual review occurred.

## Provider and rights rules

| Priority | Provider | Use requirements |
|---|---|---|
| 1 | User-provided | Preserve the original. Ask before reuse if ownership or scope is unclear. |
| 2 | Project-local | Treat rights as unknown until authorized; inspect and register before reuse. |
| 3 | Pixabay API | Cache API results for at least 24 hours, avoid automated bulk searches/downloads, link users to Pixabay, and download an image before permanent project use. |
| 4 | Unsplash API | Use the API-returned hotlinked image URL, call `download_location` when the user chooses the photo for a project, and credit both the photographer and Unsplash with referral links. |
| 5 | Pexels API | Use only after explicit approval and only with a valid preconfigured key. Respect quotas; include a prominent Pexels link and photographer credit. |
| 6 | Image generation | Disabled by default. Use only after explicit user approval of the provider, cost, and generated nature of the image. Never describe generated output as a photograph. |

API credentials must stay in the local backend environment or approved secure
storage. Never put them in prompts, source files, URLs returned to the model,
logs, browser code, or project metadata. If a provider key is absent, say so;
do not silently substitute a paid service.

## Recommended architecture

- Keep provider adapters independent behind the host's `VisualAssetService`.
- Use only allow-listed HTTPS provider endpoints and image hosts.
- Keep provider credentials in the trusted local asset service; provider search,
  download, and project writes require NIANG IA approval.
- Store source, author, profile, license/terms URL, retrieval time, dimensions,
  format, hash, query, and project placement in `assets/visual-assets.json`.
- Never let the model provide an arbitrary URL for downloading; use a candidate
  returned by the current mission's search cache.

## Code example

Use the host-mediated tools rather than embedding provider keys or issuing raw
HTTP requests:

```text
visual_asset_search(
  query="black luxury sports car at dusk",
  orientation="landscape",
  min_width=1600,
  min_height=900,
  limit=8
)

visual_asset_use(
  candidate_id="pixabay:123456",
  relative_path="assets/images/hero-car.jpg",
  placement="home page hero"
)

visual_asset_verify(check_external_urls=false)
```

The IDs and paths above are illustrative. Use only IDs returned by the current
mission, and never claim an asset was fetched unless the tool confirms it.

## Best practices

- Prefer user assets and previously authorized project media.
- Use one distinct image per product/story and select orientation for the
  actual layout. Verify source dimensions rather than trusting file extensions.
- Use `srcset`/`sizes`, responsive CSS, `width`/`height`, `loading="lazy"` below
  the fold, and `fetchpriority="high"` only for the true hero image.
- Keep originals intact. Optimize a new derivative only when supported and
  justified; retain transparency and avoid excessive quality loss.
- Add useful alt text based on the image's actual content; use `alt=""` only for
  decorative images.
- Keep visible attribution and the asset registry in sync.
- Use `prefers-reduced-motion` for animated media and avoid loading large
  decorative assets before they are needed.

## Anti-patterns

- Scraping Google Images, bypassing API restrictions, bulk-downloading, or
  hotlinking Pixabay/Pexels assets permanently.
- Downloading Unsplash API images instead of using the returned hotlink.
- Treating a provider license as proof of model, trademark, property, or
  editorial-release rights.
- Exposing keys, inventing source URLs, reusing an unapproved local asset, or
  calling an unconfigured provider.
- Reusing one photo for unrelated products, shipping placeholders, or claiming
  visual relevance from tags alone.
- Installing an image library or calling an image-generation API without the
  user's approval.

## Error handling

Handle missing credentials, provider HTTP errors, 429 quotas, timeouts, invalid
JSON, unsafe redirects, oversized files, HTML masquerading as an image,
unsupported formats, and failed image decoding explicitly. Preserve a clear
provider status in the report. Try another permitted free provider only after
the current failure is reported; never use a paid fallback. If no verified
candidate is available, ask for a user asset or report the blocker instead of
leaving a fake path.

## Optimization

Select dimensions for the placement, not the largest available original. Prefer
WebP for supported raster delivery; use AVIF only when the project's browser or
runtime supports it and encoding is already available. Keep PNG for required
lossless transparency and SVG for trusted vector assets. Avoid downloading an
oversized original when a provider's appropriate rendition is available.

## Tests and validation

- Test each provider adapter with mocked API responses and a mocked clock/cache.
- Verify orientation, minimum dimensions, query relevance, ranking, de-duplication,
  allow-listed URLs, provider errors, quotas, and credential redaction.
- Test file magic/decoded type, dimensions, size limits, redirect policy,
  no-overwrite behavior, registry provenance, visible credits, and placeholders.
- Test local assets with unknown rights and require explicit authorization.
- Separate mocked API tests from live calls. Live tests may run only when an
  already-configured free API key exists and the user has authorized the call.
- Verify Cline actually loads this selected skill. Verify OpenCode by observing
  its real skill-tool load result; do not infer usage from file presence or
  selection alone.

## Final checklist

- [ ] Visual need and each placement are identified.
- [ ] User/project assets were checked before external search.
- [ ] Rights were confirmed and every selected asset is distinct and relevant.
- [ ] Provider, source, author, license, dimensions, hash, and placement are recorded.
- [ ] Files are valid images, not HTML or mislabeled content.
- [ ] Output paths exist and are referenced; no placeholders or broken local paths remain.
- [ ] Required photographer/provider credits are visible in the project.
- [ ] Images are sized and optimized without changing user originals.
- [ ] Responsive behavior and actual visual composition were reviewed or marked untested.
- [ ] Only actually performed API, skill-loading, and project checks are reported.

## Official documentation

- [Pixabay API](https://pixabay.com/api/docs/)
- [Pixabay Content License and Terms](https://pixabay.com/service/terms/)
- [Unsplash API documentation](https://unsplash.com/documentation)
- [Unsplash API guidelines](https://help.unsplash.com/api-guidelines/unsplash-api-guidelines)
- [Unsplash attribution](https://help.unsplash.com/api-guidelines/guideline-attribution)
- [Unsplash hotlinking](https://help.unsplash.com/api-guidelines/guideline-hotlinking-images)
- [Unsplash download tracking](https://help.unsplash.com/api-guidelines/guideline-triggering-a-download)
- [Pexels API documentation](https://www.pexels.com/api/documentation/)
- [Pexels License](https://www.pexels.com/license/)
- [Pillow documentation](https://pillow.readthedocs.io/)
