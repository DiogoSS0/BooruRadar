# Mascot artwork

Updated 2026-09-08 following the user's supplied reclining-pose illustration.

- Source reference: `ChatGPT Image Sep 8, 2026, 05_17_01 PM.png`, supplied by the user.
- Final local asset: `apps/api/static/assets/booruradar-mascot-relaxed.png` (1774 × 887, RGB PNG).
- Editing tool: built-in `image_gen`; no CLI/API fallback.
- The output uses a dark matte, not alpha transparency. CSS softly blends its outer edge with the page canvas. The first checkerboard-background export was discarded.
- Desktop/tablet show the reclining figure; compact mobile crops retain the face and hands. The original scanner-pose asset remains available.

## Final prompt

```text
Use case: precise-object-edit. Edit the supplied image for the dark BooruRadar website. Replace only the ENTIRE white-and-cloud background with a completely uniform flat solid charcoal-blue color, exact RGB (16,23,31), HEX #10171F, covering every background pixel. Remove all clouds. Do not draw any checkerboard, texture, lighting, halo, glow, shadow, cloud, vignette or gradient. Keep the mascot's exact original face, hairstyle, hair clip, colors, clothing, hands under chin, horizontal lying pose, raised feet, proportions and linework. Do not redesign or restyle the character. Complete only the tiny garment edges previously hidden by clouds. Show the full character including hair tip, elbows, shoes and flowing fabric. Compact landscape canvas around 2:1, character almost filling canvas with a small safe margin. All negative space MUST be the same perfectly flat #10171F color. No transparency requested, no text.
```
