# UV tiling and texture pages

Two questions, one answer each:

1. **Which materials tile?**  All of them.  There is no clamp anywhere.
2. **When is a UV outside 0..1 safe?**  Always for the *sampler*, but it
   changes what you see, because 0..1 is the whole texture page.

## The UV space

RR3 stores UVs in a 4x4 tile space: `u` runs 0..4, `v` runs -3..1.  The
converter maps that onto Blender's 0..1, V-up space:

```
u' = u / 4
v' = (1 - v) / 4
```

So **UV 0..1 in Blender = the entire texture page, once.**  A UV of 2.0
shows the page twice; 0.5 shows the middle half.  That is the whole rule.

## Evidence that nothing clamps

I walked every body and shared mesh of all 540 cars (67,419 meshes) and
measured the converted UV range per material tag.  If a material clamped,
no shipped mesh could ever leave 0..1 while still drawing correctly:

| tag | meshes | with UVs outside 0..1 | widest converted range |
|---|---:|---:|---|
| `scratches` | 2564 | 1867 | [-13.694, 6.517] |
| `badges` | 4884 | 475 | [-2.009, 12.374] |
| `misc` | 12659 | 457 | [-14.838, 15.343] |
| `tyre` | 3127 | 399 | [-0.748, 2.998] |
| `wheel` | 8498 | 385 | [-0.853, 1.996] |
| `cab` | 2671 | 234 | [-11.250, 5.507] |
| `headlight_glow` | 2303 | 220 | [-0.025, 1.259] |
| `windows_shattered` | 230 | 203 | [-6.438, 6.561] |
| `lights` | 5662 | 168 | [-3.551, 3.877] |
| `chassis` | 2590 | 97 | [-4.673, 2.886] |
| `ext` | 11267 | 95 | [-14.937, 12.241] |
| `wheel_blur` | 4109 | 30 | [-0.133, 1.008] |
| `rotor` | 1081 | 24 | [-0.007, 1.007] |
| `windows` | 5684 | 20 | [-1.990, 7.788] |
| `banner` | 50 | 10 | [-0.037, 1.037] |
| `_headlight_glow` | 6 | 2 | [-0.020, 1.019] |
| `cloak` | 1 | 1 | [-0.918, 0.928] |
| `int` | 1 | 0 | [0.332, 0.800] |
| `(none)` | 29 | 0 | [0.000, 1.000] |
| `light_blue` | 3 | 0 | [0.000, 0.484] |

17 of the 20 tags appear outside 0..1 in shipped artwork.  The three that
do not (`int`, `light_blue`, and meshes with no `_mm_` tag at all) are rare
one-off cases, not evidence of clamping - there is no sampler state in the
m3g format at all, and the shaders sample with plain `texture2D`, which is
GL_REPEAT by default in this engine.

**Conclusion: you may use UVs outside 0..1 freely.  Nothing will clamp.**

## But: 0..1 is the whole page, so tiling repeats the whole page

This is the part that bites.  A car's paint page is one 1024x1024 livery
atlas shared by many meshes.  If you set a body panel's UV to 1.5, it
repeats **the entire atlas** - including the parts other panels use.  You
will see half a door, a mirror, and somebody's headlight on your bonnet.

That is why the shipped meshes that *do* tile are the ones whose artwork
was authored to tile:

* `tyre` - the tread is a strip that repeats around the circumference
* `wheel` - the rim face repeats radially on some rims
* `badges` - decal strips repeat along a body side
* `scratches` - the damage overlay tiles over a whole panel
* `misc` - grille mesh, vents
* `windows_shattered` - the crack pattern tiles

and the ones that never tile are the ones mapped one-to-one onto a
dedicated region of the atlas:

* `ext` (paint) - 11,267 meshes, only 95 ever tile
* `windows` - 5,684 meshes, only 20 ever tile
* `lights`, `cab`, `chassis` - same story

So the practical rule for new artwork:

| you want | do this |
|---|---|
| paint one panel from one region of the atlas | keep UV inside 0..1, and place it in that region |
| a repeating tread / grille / crack pattern | go past 0..1, but the *whole page* repeats, so give that mesh its own page |
| a texture that must not repeat | keep UV inside 0..1 |

## Giving a mesh its own page

A mesh samples whatever page its material points at.  Materials are per
mesh in the m3g (`materialId` -> the file's material list), and the material
name is `Vehicle Exterior_mm_<tag>`.  The engine then looks the *tag* up in
the livery table to find the actual page, so:

* every mesh with the same tag shares one page
* a car has one page per tag: `_ext` (the livery atlas), `_misc`, `_lights`,
  `_badges`, `_cab`, `_int`, `_chassis`, `_windows`, `_wheel`, `_tyre`, ...
* to give one mesh its own page you must give it its own tag, and a tag
  that is not in `liveryStringTable.bin.nct` has **no page at all** - the
  engine falls back to whatever the m3g carries, which for a shipped car is
  nothing, so the mesh draws with a placeholder

**So: do not invent tags.**  Use one of the 30 tags in the part-name list,
and accept that meshes sharing a tag share a page.

## Page sizes, for reference

From a 2012 Lexus LFA (the shape is typical):

| page | size | format |
|---|---|---|
| `_ext` (per paint scheme, in `livery/`) | 1024x1024 | DXT1 |
| `_int` | 1024x1024 | DXT1 |
| `_mask` | 1024x1024 | DXT1 |
| `_cab`, `_lights`, `_misc`, `_sw`, `_wheel`, `_wheel_blur` | 512x512 | DXT1 / DXT5 |
| `_badges`, `_sha` | 256x256 | DXT5 / DXT1 |

## The four GPU families

Every texture exists in four encodings, and the manifest lists all four:

```
<name>.dxt.dds.z    DXT1 / DXT3 / DXT5
<name>.etc.dds.z    ETC1 / ETC2
<name>.atc.dds.z    ATC
<name>.ptc.pvr.z    PVRTC
```

A depot only unpacks the one its target GPU needs, so seeing only
`.dxt.dds.z` on disk is normal - the other three rows in the manifest point
at files that were never written.  When you ship a texture you only need to
write the family the user's depot is built for.

**PVRTC is gamma-encoded; DXT/ETC/ATC are linear.**  Measured against the
same artwork: ATC differs from DXT by 1.97 (mean absolute difference, 0-255),
ETC by 2.37, PVRTC by 54.38 raw - but only 2.56 once you push it through
`display = (linear/255) ** (1/2.2) * 255`.  Do not treat that as a decode
bug.  `rr3lib/etcdecode.py` has `to_display()` for it.