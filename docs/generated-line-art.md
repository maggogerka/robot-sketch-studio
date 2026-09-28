# Generated Line-Art Import

This workflow is for an image that is already clean line art. It is not a photo
enhancer: it deliberately runs no neural model, XDoG, or Canny and never invents
missing anatomy or objects.

## Recommended input

- PNG (including transparent background), JPG, JPEG, or WebP;
- black or dark lines on white/transparent background;
- no shading, hatching, gray texture, fill, text, or duplicate outlines;
- separated facial features and as few accidental touching strokes as possible.

Suggested instruction for an image generator:

> Transform the input into clean minimalist black pen line art on a pure white
> or transparent background. Preserve identity, pose, proportions, silhouette,
> facial features, hair and important clothing structure. Use a small number of
> long smooth connected strokes. Remove shadows, textures, noise, hatching,
> dots, fill and duplicated outlines. Do not add objects or change composition.

## UI workflow

1. Select **Generated Line-Art Import · offline**.
2. Drop, browse, or paste the image from the clipboard.
3. Set the final physical paper size and actual pen-tip width. The default
   Rotrics profile is 80 × 113 mm; do not resize it after import.
4. Start with **Preserve Quality** and press **Auto · analyze**. Auto estimates
   source stroke width, resolution/noise and fills the advanced millimetre
   controls. For shorter jobs, try **DexArm Optimized**.
5. Compare the source, cleaned mask, centerline overlay and SVG preview. Each
   ordinary thick contour should have one centerline; eyes, lips, glasses, hair
   and clothing detail should remain independent.
6. Download `drawing-speed.svg`. `centerline-overlay.png` is the diagnostic map;
   `trajectory-speed.json` contains exact paths and measured metrics.

Changing threshold, noise size, minimum path, gap, smoothing, simplification,
duplicate radius, paper, margin, or pen width schedules a quick preview update.
The optimized profile automatically returns to Preserve Quality settings only
when the measured centerline/face topology is materially better.

## Advanced controls

- **Confidence cutoff** controls hysteresis high confidence; weak pixels survive
  only when connected to supported ink.
- **Noise** removes only isolated low-confidence components below that physical
  size. It is not a blanket short-line filter.
- **Min path** protects useful short high-confidence facial detail while
  rejecting insignificant skeleton fragments.
- **Gap closing** permits only a short, direction-compatible endpoint join.
- **Smoothing** is the bounded cubic fitting tolerance.
- **Simplify** reduces polyline nodes before fitting without changing topology.
- **Duplicate radius** suppresses physical parallel overlap from the same
  component; face-region thresholds remain more conservative.

## API

Analyze without creating a job:

~~~bash
curl -F image=@line-art.png \
  -F 'options={"engine":"generated_line_art","drawing_preset":"generated_line_art"}' \
  http://127.0.0.1:8000/api/v1/line-art/analyze
~~~

Submit the same multipart fields to `/api/v1/jobs` for final output. Set
`line_art_auto: false` to use manual values. The endpoint remains offline even
when the app is exposed as a processing host.

Automated tests validate geometry and SVG compatibility, but they do not prove
physical Rotrics/DexArm behaviour. Always inspect imported scale and perform a
raised-pen/dry run before drawing.

Developed by maggogerka.
