# RR3 Mod Manager — backlog from the 2026-11-06 review

Recorded from the user's walkthrough of the manager (m10604). Items are ticked as
they land, with a note saying what was done; the ones still open are the ones to
pick up next.

Legend: **[bug]** broken today · **[ui]** interaction / polish · **[feat]** new
capability · **[hold]** placeholder, deliberately not built yet.

---

## 1. Cars page

- [x] **[ui]** Column widths cannot be adjusted; long car names get clipped.
      **DONE 2026-11-06 - Interactive headers, widths in settings.ini, right-click menu (fit / widen / reset).**
      `CarTable.__init__` currently does `h.setSectionResizeMode(0, Stretch)`
      and `ResizeToContents` for the rest, so the user cannot drag anything.
      Plan: `Interactive` + `setStretchLastSection(False)`, remember widths in
      `settings.ini`, add a "reset columns" action.
- [x] **[ui]** Finding a car is hard. Today there is one free-text box
      **DONE 2026-11-06 - make, class and status combos plus a clear button; the count follows the filter.**
      (`Filter by name, make or model`) plus two checkboxes (body model / own
      geometry). Plan: manufacturer combo, class combo (S/R/M4/…), PR range,
      "in career / in motorsport" toggles, and a tag row for our own mods.
      Data is already in `CarEntry` (make, model, class comes from the CSV, see
      §8) so this is mostly wiring.
- [x] **[feat]** Sort by column is enabled but the id column sorts as text.
      **DONE 2026-11-06 - id, class and paints are numeric items so the sort is numeric.**

## 2. Build a car

Many gaps; the user wants to keep testing before we enumerate them. Known today
from `BuildDialog`: pack folder, existing car, donor, new name, display key,
aero on/off. Missing at least: car id, appearance id, model token, paint /
livery choice, PR + stats, class and tier, and the series placement that
`rrmod/series.py` already supports.

- [x] **[feat]** Ride height tab in the car detail pane. **DONE 2026-11-23** -
      `rrmod/ui/suspui.py` + `edit.set_suspension_range()`: both halves of the
      slider are editable in millimetres, and writing a down range solves for
      the tyre diameter (`spec.diameter_for_down`). Group 90 tests the up half
      on its own, group 91 the pair.
- [x] **[bug]** A build did not keep `f21/f22` in step with the wheel size.
      **DONE 2026-11-23** - the Build dialog now has `4. Its ride height`,
      *after* the wheel scale because the down half is measured from the drawn
      wheel. `app.py` applies `set_suspension_range` on both branches right
      after the wheels are written. Before this, `build_suspension` cloned the
      donor's 140 byte record verbatim, so the tyre diameter stayed the donor's
      while the wheel scale rewrote the loaded radius - measured on the LFA as a
      donor (f21 = 712, own f1 = 340, down 32 mm), a build at wheel scale 1.0
      landed at **113 mm** down, x1.2 at 56 mm, x0.9 at 144 mm.
- [ ] **[bug]** The upper half of the ride-height slider prints one millimetre
      less than it is stored as, sometimes. Five readings, no single rule fits:
      0.010 -> +10, 0.015 -> +15, 0.180 -> +180, 0.005 -> +5/+4, 0.025 -> **+24**.
      The down half is exact.

      **DEFERRED 2026-11-25** - the user asked to leave this for later ("记下来，
      晚点再做"), so it is parked here, not forgotten.  The down half, the
      write path and the display of a shipped car are all correct; this is the
      readout of a hand-typed up value.

      The experiment that closes it, in order:

      1. Take one car, change **only** `f23/f24` (up travel), leave `f21/f22`
         (tyre diameter) and the appearance block alone. Sweep 0.005 / 0.010 /
         0.015 / 0.025 / 0.180 and read the screen after each.
      2. If the screen now tracks the float exactly, the second variable was the
         tyre: log the diameter next to each reading and fit
         `screen = f(travel, diameter)`.
      3. If it still disagrees, the readout is not `int(f32 * 1000)` of this
         field alone - look for a second consumer of `f23/f24` (the workspace
         `suspensiondata` copy is synced per edit, so a stale hash would show
         the *old* number, which matches "one off" only by coincidence).

      Tool: `work/_silvia_range.py [up] [down]` already does the write + print,
      and `work/_push_silvia.py` pushes the table; both are gitignored.

- [x] **[feat]** Finish the field list, then re-review.
      **DONE 2026-11-06 - appearance id, model token and the donor-alias switch are
      in the dialog and reach `install_pack`.**
- [x] **[feat]** PR, stats, class and the paint schemes.
      **DONE 2026-11-08 - `rrmod/stats.py` reads and writes the nine fixed-index
      figures (weight, top speed and its cap, 0-60 and its cap, braking, grip)
      and the *Build a car* dialog shows them next to the donor's, so a new car
      can be given its own. `Spec.set_class()` writes the class string and
      `build_livery(paints=[...])` trims the donor's schemes to the ones ticked.
      PR, the engine block and the drivetrain stay read-only: their position
      depends on the length of the strings around them, so a mis-write would
      change the handling with no way to notice.**
- [x] **[feat]** The series placement for a new car.
      **DONE 2026-11-08 - section 6 of *Build a car*, "Where it races".
      `series.place()` is `build()` + `write()` in one call for callers holding a
      working copy rather than a loaded career; with no events given it copies
      the template's first tier, so "same races as the series I copied, but only
      my car may enter" is the default. `series.title_from("2012_lexus_lfa_copy")`
      gives `Lexus Lfa Copy Cup`. The career file is parsed off the UI thread
      (14 MB, 6.9 s) and only when the box is ticked. `editor.for_career()` now
      mirrors all fourteen career files, not just `events.dat.nct` +
      `gametext.txt` - adding a line to one text file without the others would
      leave the set unpaired, which `Texts.from_blobs` rejects. Tests:
      "a new car can be given a series to race in", 16 assertions.**

## 3. Sharing mods  **[done - see Done on 2026-11-16]**

- [x] **[feat]** Export everything we changed into one package, import it on
      **DONE 2026-11-06 - `rrmod/share.py`, `Share this car...` / `Import a
      share...` on the Cars page, 23 assertions. The pack holds the car's own
      files plus its spec and livery table; the three manifests are deliberately
      left out, because the receiving install has its own.**
      another install. `rrmod/modpack.py` already defines `car.json` for the
      Blender hand-off; the sharing pack is a superset: the pack plus the spec,
      the livery file, the `rr3mods.json` record, and a table delta (career /
      cardesc / appearances) so it can be merged rather than overwritten.
- [x] **[feat]** Import must run through the same guards as deploy
      **Partly: the share is refused unless `base` is installed and the car and
      appearance ids match. The table/career guards do not apply, since a share
      carries no tables.**
      (`check_table` / `check_career`) so a pack built against an older game
      cannot drop the device's newer rows.
- [x] **[hold]** Placeholder button in the Cars page toolbar.
      **No longer a placeholder: it works.**
- [x] **[feat]** Share more than a car: drivers, the career, brands and maps.
      **DONE 2026-11-16 - `rrmod/publish.py` writes six kinds (`car`, `pages`,
      `driver`, `brand`, `career`, `track`) as `.rr3mod`, and `rrmod/pack.py`
      reads them back with a dependency check. The career is merged, never
      replaced, and the pack's note says so. See `## Done on 2026-11-16`.**
- [x] **[feat]** A share can add or replace files but never delete one, so
      taking a mod off means deleting the car and reinstalling it.
      **DONE 2026-11-15 - `rrmod/backup.py` keeps the device's own bytes for
      exactly the files a push overwrites, one folder per push as a stack, and a
      file the device did not have is recorded as absent so an uninstall deletes
      it. Deploy page: `Take the last push back`.**

## 4. Music

Facts confirmed on the retail depot: 167 playlists, every one holds exactly
three songs (`Music_Track_1/2/3`), 166 distinct track base names, 17 audio
files. Playlist files are `<track>-<time>-<id>.bin.nct`.

- [x] **[feat]** Two panes: (a) the audio files in `audio/music`, (b) every
      **DONE 2026-11-06 - `Tracks` and `Audio files` tabs on the Music page.**
      track with its three assigned songs.
- [x] **[feat]** Multi-select tracks (checkbox column + ctrl/shift click), then
      **DONE 2026-11-06 - tick boxes on the tree, `Tick everything`, `Batch edit
      the ticked events`, and a `shuffle` action that seeds a reproducible
      three-song draw per event.**
      bulk-assign: pick N songs, cycle them round-robin into the three slots.
      `rrmod/ui/musicbatch.py` already has the cycling engine; it needs the
      track-list UI in front of it.
- [x] **[hold]** Random-music patch.
      **Still a placeholder, as agreed. The button explains what it would take.** Requires patching the game binary
      (`lib/arm64-v8a/libRealRacing3.so`) so it enumerates `audio/music` at
      launch and picks three at random per event. `analysis/so_patch.py`
      already patches the `.so` in place inside `base.apk` (the entry is
      STORED, so no re-signing), so the tooling exists, but the code cave does
      not. Placeholder button, clearly marked "not built".

## 5. Career editor

Currently a flat list of 1602 series. The user wants to navigate by
section → series → tier → event, pick cars from a real picker, pick tracks from
a real picker, and set a cover picture.

- [x] **[ui]** Group tree: Motorsports / Career → the 31 menu groups → series →
      **DONE 2026-11-06 - three-level tree, 404 career / 89 motorsport / 1109 not
      in a menu.**
      tiers → events. Data: `Career.group_map()` and `Career.tier_map()`.
- [x] **[feat]** Car picker dialog, reusable everywhere.
      **DONE 2026-11-06 - `rrmod/ui/picker.py`, used by the career dialog and
      Build a car. 511 of 540 cars have a picture.** Manufacturer list →
      car list with a thumbnail, searchable, multi-select. **Images are already
      in the game**: `gui_assets/<size>/car_sales/cars/build_*/` holds atlases
      whose images are named `car_sales_car_<carId>.png`, and 510 of our 540
      cars have one. That is better than any external source and needs no
      licensing question.
- [x] **[feat]** Track picker dialog.
      **DONE 2026-11-06 - 126 of the 162 track names have real artwork in the
      game's own atlases, so no user-supplied pictures were needed. The other 36
      are listed without a picture.** No in-game track artwork worth using, so:
      list + optional user-supplied picture attached via a `...` button, stored
      in our state folder keyed by track name.
- [x] **[feat]** Cover picture for a self-made series, plus the intro text.
      **DONE 2026-11-06 - `rr3lib/pvr.encode` was written and verified byte for
      byte against a shipped atlas page, so the encoder this item was blocked on
      exists now. The intro text is the series description.**
      MonkeyTool's flow (`nfsnl_rr3career.cpp:719-760`) is the reference: decode
      the user image, resize to the size the existing cards use (340x471 on the
      `events/career` atlas), add it as a new page to
      `gui_assets/<size>/events/career/sprites.android.atlas` and the matching
      `sprites_N.rgb.pvr.z`, then point the group's `base[3]` at it. **This
      needs a PVR *encoder*** — `rr3lib/pvr.py` can only read today.

## 6. Graphics

Facts: 113 plist keys and 190 feats keys, and **all 42 shipped profiles have
the identical key set** (41 plists and 42 feats compared, zero differences).
So every legal value can be harvested from the shipped profiles.

- [x] **[bug]** On/off keys render as text edit boxes instead of checkboxes.
      **DONE 2026-11-06 - 243 checkboxes, 51 combo boxes, 9 text boxes.**
      The table is a `QTableWidget` with `DoubleClicked|EditKeyPressed` on all
      cells; booleans need a `Qt.ItemIsUserCheckable` cell or a delegate.
- [x] **[ui]** Enumerated keys should be combo boxes filled with the values that
      **DONE 2026-11-06 - `gfx.choices()` harvests them from the 42 shipped
      profiles; 98 plist keys and 33 feats keys have a choice. The free-text
      escape hatch is the third kind of cell.**
      actually appear across the shipped profiles, e.g.
      `AA_LEVEL ∈ {0,4}`, `CUBE_MAP_DIMENSIONS ∈ {256,384,512,1024}`,
      `MIPMAP_BIAS ∈ {-2.0,-1.0,0.0}`, `EXPECTED_RENDERER ∈ {GL_ES_2,GL_ES_3}`,
      `TEXTURE_MIPMAP_LEVELS_TO_SKIP ∈ {0..3}`, `CAR_INTERIOR_LOD ∈ {A,B}`.
      Keep a free-text escape hatch per key, marked as "not seen in any shipped
      profile".
- [x] **[feat]** Load another profile's plist (e.g. `AndroidXtraHigh.plist`)
      **DONE 2026-11-06 - `Base profile` combo + `Use this profile`, with the
      identifier keys forced back so the engine still accepts the file. Writing
      straight into the install folder is what `gfx.apply(out_dir=...)` already
      does; pushing is the deploy step.**
      and copy it over `AndroidHigh`, then push. Also allow writing straight
      into the install folder for USB-copy users instead of adb.

## 7. Localisation

- [x] **[feat]** Language switch (at minimum English + 简体中文).
      **DONE 2026-11-06 - not by wrapping `tr()` around every literal, which is
      what went wrong first: the switch walks the live widget tree instead, so
      the English text stays in the source. 259 strings, all translated.**
      **This is cheapest now and most expensive later**: the UI currently has
      zero `tr()` calls and roughly 650 hard-coded English literals across
      `rrmod/ui/*.py`. Doing it before the UI grows means wrapping as we go;
      doing it after means a mechanical sweep over every file.

## 8. Reference data

- [x] **[feat]** `real_racing_3_cars_v14_0.csv` from
      **DONE 2026-11-06 - shipped as `rrmod/data/cars.csv`, matched to 527 of
      540 cars (494 by display name, 16 exact, 13 by model).**
      <https://github.com/toUpperCase78/real-racing-3-cars> gives per-car
      Manufacturer / Model / PR / Top Speed / Acceleration / Braking / Grip /
      Class / Type / Series / Price / Service Time / Service Cost / availability
      flags. 540 rows, matching our 540 cars. Name matching on
      manufacturer+model hits 312/540 exactly; the rest need a normalisation
      pass (e.g. `NISSAN 240Z (S30) R3` vs `Datsun 240Z`). The repo's `Images/`
      folder is screenshots only — no per-car art, so §5 uses the in-game
      atlases instead.

---

## Still open

Everything below is known, sized, and deliberately not done yet.  The reasons are
recorded so they are not re-litigated from scratch.

### Blender add-on

- [x] **[feat]** Multi-LOD export. One `.m3g` holds one level, so the exporter
      now names the file after the collection the meshes are in
      (`LOD_A.m3g`, `SHARED.m3g`, `INT_A.m3g`, `FRONTEND.m3g`) and refuses a
      selection that spans two levels. `rrmod.slots` reads exactly those names,
      so no manifest is involved: `car.json` stays optional and nothing writes
      it. The `identity` strings (year/make/model/display name) are still typed
      into the manager - the folder name `2012_my_car` already carries the two
      that matter, and the rest is a showroom label.

### Build a car

- [x] **[feat]** Writing the PR. `Spec.set_pr()` writes the + 4 slot only; the
      final PR (+ 5) is left to the game, which derives it from the base and the
      upgrade route. Writing a stale final value would just display a wrong
      number; writing a made-up one could be above or below what the parts add
      up to. 33 specs have no `CAR_NAME_*` and report nothing rather than a
      guess. Tests: "the starting PR can be set, and only the starting one".
- [x] **[feat]** The engine block (final drive, power, torque, redline, limiter,
      shift points). `Spec.set_engine()` writes **by byte offset** for exactly
      the reason the read side does; `gears` is refused because it decides how
      many ratios follow it. `ENGINE_LIMITS` guards the values. Tests: "the
      engine figures are written by byte offset".
- [x] **[feat]** Sound. `Spec.set_sound(family)` rewrites the three strings
      (accel / decel / idle) and keeps the car's own `id_<n>`; the 105 cars with
      no audio fields refuse rather than having an offset invented. Tests: "the
      engine sound is three strings, and it can be pointed elsewhere".
- [x] **[feat]** Aspiration, layout, unlock rule and both prices.
      `Spec.tail()` reads them, `set_aspiration` / `set_layout` / `set_unlock` /
      `set_price` write them, and `statlib.tail()` / `set_tail()` put them behind
      one call for the dialog. The layout of the tail, which held for all 540
      shipped cars with no exception:

      ```
      aspiration  layout  gears  <engine block>  route  unlock
        4 x u32 (0, 0, 0, a small id)  extra-string  4 x u32 (all zero)  cash  gold
      ```

      Three things are worth keeping: `aspiration` is the token *before* the
      layout and the layout is the one before the gear count (not the other way
      round); the `extra-string` is empty on 532 cars and holds
      `r3_spec_logo.xml` on the eight R3 specials, so skipping it by its own
      length prefix is what keeps their money from landing 20 bytes late; and the
      aspiration and the layout have to be written from the six and four values
      the game knows, because the engine block is *found* by those two words - an
      unknown one would hide the gear count, the power figures and the upgrade
      route from every reader in `rr3lib/spec.py`. 252 cars sell for cash only,
      280 sell for both, 0 sell for gold only, and 8 (the R3 specials) sell for
      neither. Tests: "the spec ends with two words, a rule and two prices".

      A note on `handling`: the spec's handling string is the upgrade route key,
      so it was never a separate field - see the route picker below.
- [x] **[feat]** The upgrade route picker. `rr3lib/upgrades.py` reads the table
      and `Spec.set_upgrade_route()` writes the one string that points a car at
      a tree; the dialog lists all 327 routes with the ten templates first.
      **The old note in this file was wrong**: the table is not "ten named
      blocks", it holds **327** route blocks of 1,199-1,716 B each, found by
      shape (a name string followed by >= 3 upgrade-area names starting with
      `Engine`) - the `u32 1005` at the top is not a record count and the four
      bytes after a name are 0 for 326 of the 327, so neither can be used as a
      key. The key lives in the spec at `gears + 4 * (13 + gears)` bytes past the
      gear count, which is why it is read by offset and not by token index. 459
      of 540 cars point at a tree that exists, 75 point at nothing, and 6 point
      at trees the table does not contain (`CHEVROLET_C6R_GT2`,
      `2020_GT3_UPGRADE_TREE`) - those are the game's own broken references and
      are left alone. Tests: "the upgrade route is one string, and the tree lives
      elsewhere".
      **Still open from this group:** copying a template block into a *new* tree
      (so two cars can share a tree we made), and "write your own" steps.
- [x] **[feat]** Series placement: which menu group a new car's series goes in.
      Done with the build dialog's section 6; see the entry in group 2 above.
- [x] **[ui]** PR/engine/sound have a home in the dialog: the figures table now
      covers 23 fields, `gears`/`pr_max`/class/drivetrain are shown read-only
      with a tooltip, and the engine sound is a 53-entry dropdown. In the modify
      branch they stay behind "Also change what it drives like" so an edit to a
      car's files never quietly retunes it.
- [x] **[ui]** The tail has controls of its own under the figures table: two
      closed dropdowns (six aspirations, four layouts), a text box for the unlock
      rule and two spin boxes for the prices. They are not table rows because two
      of them are words from a list and two are money. `tail_changes()` hands back
      only what differs from the source car, so a build that touches nothing
      writes nothing - the spec's own setters compare before they splice.

### Drivers

- [x] **[feat]** Say which driver pose a car uses, and which low-poly copy of it.
      **DONE - see Done on 2026-11-19.**  The field is the thirteenth token after
      the `CAR_NAME_` string in the car's data record, which is why it is walked
      rather than read at an offset; `rr3lib/driver.set_field()` writes it and the
      *Animation* tab's "Driver pose" dropdown chooses it.  The dependency problem
      is reported rather than refused: `set_driver_pose()` returns the low-poly
      model when the pose has one and `""` when it does not, and the pane says
      which of the two it is before the file is written.
      *(Original note: 131 cars match a pose of their own, 409 fall back to
      `driver.banim`; 33 poses are in use but only 12 have a `driver_lod_c_<x>.m3g`,
      so 24 play through the generic figure, and `f1412t2` / `f1f14t` have a model
      no car asks for.)*
- [ ] **[feat]** Build a low-poly model for a pose that has none.  The manager can
      only choose among the 12 the game ships; making the other 21 look right means
      exporting a `driver_lod_c_<x>.m3g` from Blender beside the `driver_<x>.banim`.
      The add-on can import and export both, so this is authoring work rather than
      a missing capability.

### Decals

- [x] **[feat]** Read the decal list and say which shapes will draw. Done: the
      Decals page (`rrmod/ui/decalui.py`) lists all 229 records with the name the
      player sees, whether each draws a glyph or a picture, and whether its code
      point is in the font. See `## Done on 2026-11-20`.
- [x] **[feat]** Add a shape, which means writing a glyph into `r3_decals.ttf`.
  Done: `rr3lib/ttf.py` rebuilds the font, `edit.add_decal_shape` writes the glyph and the record in one undo step, and the Decals page has a canvas to draw on.  See `## Done on 2026-11-22`.
      The record half is done (D2, see `## Done on 2026-11-21`): a record can be
      renamed, recategorised, moved and given another picture.  What is still
      missing is the glyph itself - a new record can only reuse a code point the
      font already carries.
      The list side is done (`rr3lib.decals.add`); what is missing is a TrueType
      outline writer - 232 glyphs, `unitsPerEm=2048`, `indexToLocFormat=1`, a
      format 4 cmap whose two encodings share one subtable. A record with no
      glyph behind it is the fault the page already reports.

### Textures and materials

- [x] **[feat]** `manifestlib.owner_of(path)` - which of the 1,236 asset lists
      claims a path, and the edit that keeps it there. The index is cheap (0.25 s
      for 114,307 paths, 0 duplicates across all lists) so it is built at
      startup. `edit.sync_file()` used to update three books and silently ignore
      the other 1,233; that is why adding a brand triggered a download. Done -
      see "Done on 2026-11-13".
- [x] **[feat]** A `common/` texture needs **four** rows in
      `asset_list_vehicle_common.txt`, not one.  Done in `edit._sync_common_page`
      and `edit.add_common_page` - see "Done on 2026-11-15". That file is four contiguous
      family blocks of 298 rows each - `atc`, `dxt`, `etc`, `ptc` - and each
      block is sorted by stem, so a new file goes into *all four* at its sorted
      position inside its own block. Only `dxt` exists on disk; the other three
      are for the other GPU variants. The registry needs one row.
- [x] **[feat]** Appending a part name and a tag name to
      `liveryStringTable.bin.nct`.  Done as `SlotTable.append` +
      `edit.add_slot_names` - see "Done on 2026-11-15". Both are plain appends (2,068 -> 2,070 names,
      70,134 -> ~70,172 B, round trip byte for byte). A part name alone is not
      enough: `texture_slot_for_tag()` looks for `ext_<tag>`, then `int_<tag>`,
      then the bare tag, so a new tiled tag needs its own row or the mesh gets a
      material but no page.
- [x] **[feat]** `rrmod/deps.py`: reference counting for files under
      `vehicles/common`.  Done, with the Dependencies page on top of it - see
      "Done on 2026-11-15" and "Done on 2026-11-16". A JSON, not a database - the only dependency shape this
      game has is "which mods point at this shared file", with no version ranges
      and no transitive deps. `shipped: true` marks the game's own pages so they
      are never counted and never deleted. This is what keeps a shared texture
      alive until the last mod that used it is uninstalled.
- [x] **[feat]** A material editor for `materials.bin`. Done as a *clone*, which
      is the only edit that cannot move an offset: a whole block is appended at
      the end of the material table, and a copy this program added can be spliced
      back out. A field inside a block is still never edited - the records are
      `u32 key + u32 len + payload` with no back-pointer, so one wrong byte
      shifts everything after it and the engine loads a table that looks
      plausible and is wrong. See "Done on 2026-11-18". Reading was already
      solved: 296 instances / 136 templates / 186 shaders, the
      `instance -> K_TEMPLATE -> shader` chain verified with 0 exceptions, and
      5,887 records that rebuild byte for byte.
- [ ] **[feat]** Tiled interior materials on a body mesh. The game already does
      this on 19 cars - `2020_mclaren_speedtail` runs `car_dash_flat` on
      `LOD_A_CHASSIS_mm_chassis` - so nothing needs inventing. What stops it is
      UV: interior meshes tile out to +-60 while body UVs are packed into 0..4 of
      an atlas, and no body part name carries a `mat00`..`mat07` tag (all 70 such
      names are `LOD_*_INT_*`). So the work is (a) re-unwrap in Blender, (b) add
      the part and tag names to the string table. Note `car_interior.vsh/fsh`
      has no `SPEC_MASK_TEXTURE` / `REF_TEXTURE_MASK`, so a tiled part cannot do
      the clear-coat layering that `car_paint_carbon_fibre` does.

### Sharing

- [x] **[feat]** A share can add and replace files, never remove one. Undoing a
      mod means deleting the car and reinstalling it.
      **DONE 2026-11-15 - `rrmod/backup.py` keeps the device's own bytes for
      exactly the files a push overwrites, and records a file the device did not
      have as absent so taking the push back deletes it. See `## Done on
      2026-11-15`.**
- [x] **[feat]** Only cars can be shared. Driver poses, careers, brands and track
      maps each need their own pack type; the career one must *merge* rather than
      replace, or importing someone's share wipes the series you added.
      **DONE 2026-11-17 - `rrmod/publish.py` writes all six kinds, and a career
      pack's note says plainly that it is merged. See `## Done on 2026-11-17`.**

### Loose ends

- [ ] **[hold]** Random-music patch inside `libRealRacing3.so`.
      `analysis/so_patch.py` can patch the `.so` in place inside `base.apk` (the
      entry is STORED, so no re-signing), but the code cave that enumerates
      `audio/music` and picks three songs per event has not been written. The
      button in the Music page says so.
- [x] **[ui]** The career editor can add a tier to an existing series, drop one,
      and edit a single event while leaving the others alone.
      `rrmod/series.py` grew `add_tier` / `remove_tier` / `set_event`, all three
      of which edit the records the game already reads instead of rebuilding the
      list, so every tier id survives - which matters because a save file or an
      unlock rule can refer to one. `add_tier` copies the series' *last* tier
      (so the reward curve, banners and flags come along) and appends it at
      index `max+1`; `remove_tier` refuses to leave a series with none and pulls
      the later indices down so they stay 0..n-1 (safe: all 1602 shipped series
      already run 0..n-1); `set_event` treats `-1` and an empty track as "leave
      it alone", so the dialog only hands back what the user moved. In the UI
      that is `Add a tier` / `Remove a tier` / `Change event...` plus a
      double-click on the event table, and `EventDialog` (which must not keep its
      record in `self.event` - `QDialog.event()` is a Qt virtual, and a dict
      there throws `TypeError: ... 'dict' object is not callable`). Tests 650 →
      672.
- [x] **[feat]** Every event type is now the name the game itself gives it.
      The table was in the game's own code all along: `libRealRacing3.so` holds an
      array of 24-byte records at file offset `0xae038`, each
      `{pointer, 0x403, name pointer}`, and **the index into that array is the
      event type number**. Read in order it says `Elimination, Head 2 Head, Cup,
      Unknown Type, Endurance, Unknown Type, Unknown Type, Speed Record, Unknown
      Type, Autocross, Speedsnap, Drag Race, Hunter, Time Trial, Fuel, NASCAR,
      Speed Gate` - so types 3, 5, 6 and 8 are gaps in the game's *own*
      enumeration, not names that went missing. `EVENT_TYPES` now names all
      thirteen and `type_name()` says "the game leaves this one unnamed" for the
      four gaps. Two entries have a second witness: all 434 series with "Time
      Trial" in the title hold nothing but type 13, and every one of type 14's 37
      events carries `Fuel:<n>;forceManual` in its parameter block while the table
      calls 14 "Fuel". Type 9 is confirmed by the only tier in the whole career
      that names its mode: `%S Autocross Throwdown` is three type 9 events and
      nothing else. MonkeyTool's `kRsTypes[] = {2,1,0,4,7,10,11,13}` agrees with
      this table on all eight of its entries, which is what makes the reading
      safe rather than merely plausible. Tests 1030 → 1043 (group 75).
- [x] **[bug]** `MIPMAP_BIAS` is written as -2.0 by the ultra profile and read
      back as 0 by the engine.
      **DONE 2026-11-16 - it is not a writer bug, and the answer came from
      reading the engine's own dump instead of guessing.** A boot log with the
      ultra profile live (`re/logs/final_verify.log`) matches the pushed file on
      **111 of 113 keys**, so the file was read correctly; `MIPMAP_BIAS` and
      `3D_SCENE_SCALE` are the only two the engine resolves to something else.
      `3D_SCENE_SCALE` differs from the *shipped* value on every boot in the
      archive too, which proves the engine overrides some keys after loading
      rather than ignoring the file. `MIPMAP_BIAS` reaches the shaders
      (`texture2DWithBias` and the `NOBIAS` feature in `shaders_src/`), and the
      device that produced the log lists `GL_EXT_shader_texture_lod` but nothing
      that would bias a lookup in GL state - so a bias it cannot apply is
      reported as 0. `AndroidXtraHigh` ships `-2.0` **on Android**, so the value
      itself is legal; the device is what cannot honour it. Nothing to fix in
      the writer, so instead the manager can now *prove* it: see the next entry.
- [x] **[feat]** Read back what the engine really used. `rrmod/bootlog.py` parses
      the dump the engine prints after `Loaded settings file` and diffs it
      against the plist on disk; **Check a boot log** on the Graphics page opens
      it as a table with mismatches first, and the keys the engine owns carry the
      reason instead of looking like a failed edit. Two traps it handles: a multi
      line string only carries its `: STRING` on the last physical line, and a
      key the file does not name is *absent* from the dump rather than 0. Tests
      1200 → 1218 (group 83).
- [ ] **[ui]** The animation page can swap track numbers but nothing on screen
      has been checked after a swap - only the bytes were.
- [x] **[hold]** Suspension travel range. Researched and answered on 2026-11-23 and written
      up in `docs/避震行程-调节范围.md`: there is **no min/max pair** in any
      table. `custom.suspension.nct` is a one-item unlock (`FullAdjustSuspension`),
      `suspensiondata` floats 23/24 are the front/rear travel in metres (Silvia
      0.010/0.015, LFA 0.032/0.031, Cobra 0.150/0.150) - so the earlier "float 24
      is the range, float 25 is the rear" guess is dead. The visible limit also
      comes from the 266 byte appearance block, proven by the Reventón -> Chiron
      swap shrinking the adjustable range. **Answered on screen 2026-11-23**:
      Silvia (id 114) at f23/f24 = 0.180/0.180 shows **+180/-9 front, +180/-14
      rear** - so the *up* travel is f23/f24 straight (no clamp), the *down*
      travel does not follow them at all, and the 1 mm gap is float32 truncation
      (0.010 reads as 9). Model, settled the same day by a third value
      (0.005/0.005 -> +5/+4 up, -9/-14 down, unchanged): `[-geometry, +travel]`.
      The down half never looks at this table, so lowering a car means editing
      the 266 byte appearance block, not writing a smaller travel.
- [x] **[re]** Which bytes of the appearance block hold the down travel. **Answered
      2026-11-23**: none of them directly - the engine *derives* it. The downward
      half of the ride-height slider is
      `tyre diameter (suspensiondata f21/f22) - 2 * loaded radius (appearance
      f1/f5)`, i.e. twice the tyre's static deflection, displayed as
      `int(metres * 1000)`. Two on-screen proofs, both turning on that
      truncation: the Silvia (0.634 - 2*0.312 = 0.00999999 -> shows -9,
      0.639 - 2*0.312 = 0.01499999 -> shows -14) and the Essenza SCV12
      (0.612 - 2*0.306 = 1.1e-8 -> shows 0, 0.672 - 2*0.336 = 9e-9 -> shows 0 -
      which is why that car cannot be lowered at all while its f23/f24 of
      0.632/0.634 let it rise 63 cm). The reason this hid for so long: for 280
      of the 341 cars the appearance loaded radius was authored as
      `(diameter - travel)/2`, so the formula just reproduces the travel and the
      difference is invisible. `spec.suspension_down_travel()` now exposes it,
      group 89 tests it. Also corrected in the same pass: record fields 10..20
      and 25..31 are **u32 percentages**, not zeros - they only looked like zero
      because a `<34f` read turns them into denormals; `spec.SUSP_INT_FIELDS` +
      `suspension_percent()` say so and group 88 tests it. Dead ends kept in the doc: `+46/+50/+54` of the block
      (260 -> 520 on screen, no change), `.points` wheel heights (model space),
      cardesc floats, `custom.suspension`'s -100/+40, `consts.stats`.
      `+46/+50/+54` itself is still unmapped, as is `+62/+66/+70` (7000..10000,
      tracks the car class).
- [x] **[feat]** Texture import/export. `rrmod/textures.py` plus the Textures
      tab's two buttons: **Save this page as a PNG** decodes whichever copy is on
      disk, **Put a picture in this page** encodes it back. New on the writer
      side is `rr3lib/ddsencode.py` (DXT1/DXT5; a shipped 1024x1024 page comes
      back at a mean difference of 0.84 of a level). Only the DXT family can be
      written, and which family a page *is* depends on what the depot unpacked,
      not on what the livery names - `textures.page_path` tries all four suffixes
      and `describe` reports the one it found. A picture of the wrong size is
      refused rather than rescaled, because the game allocates by size.
- [x] **[hold]** Writing the ETC, ATC and PVRTC families.  ETC1 and ATC are done
      (`rr3lib/blockencode.py`, mean difference 1.89 and 1.04 against the DXT copy
      of the same page) and `rrmod.textures` writes a page back into whichever
      family the file on disk is in.  PVRTC is **not** a missing encoder: its
      blocks interpolate their endpoints across block edges, so a block-at-a-time
      encoder writes a file that decodes to a picture that looks wrong.  That one
      needs a whole-picture solver and stays read-only.  See
      `## Done on 2026-11-22`.
- [ ] **[hold]** Interiors. Nothing is understood beyond "the `_int` atlases and
      the `LOD_x_INT_*` parts exist": which slots the game reads, how the
      dashboard planes and the steering wheel animation line up, and how the
      cockpit camera picks a part are all open. Left for later on purpose - it
      is a research project, not a feature.
- [x] **[feat]** A material manager of its own (browse `materials.bin`'s 296
      instances and 186 shader templates, see which cars use which). The Parts
      pane covers "point this mesh at that material"; this covers "what is in
      the library at all". Done as `rrmod/matmanager.py` + `rrmod/ui/matui.py`,
      a **Materials** tab: 296 rows, **101 with a livery slot, 99 of those in
      use**, joined against `liveryStringTable.bin.nct` and every car's livery
      file. Read only on purpose - `materials.bin` has no length prefixes, so a
      wrong byte shifts every record after it; changing a look is done by
      pointing a car at a different row on the Parts/Paints tabs. 19 assertions
      in test group 52.

### Active aero, the parts the game does not cover

- [ ] **[hold]** **NASCAR roof spoilers.** The `2020_*_nascar` cars carry a roof
      flap that flips up under braking, and it is not driven by the car's own
      `_wing.banim`: none of the 42 `NascarAirBrake` cars has a `_wing.banim`
      with a track for it. The flap meshes are
      `LOD_A_WING_ROOF_*` / `LOD_A_ROOF_FLAP_*` (they exist and import fine), so
      the missing piece is *where the animation lives* - either a shared banim
      under `vehicles/common/`, or a hard coded motion rule keyed off the
      `NascarAirBrake` flag. Reversing it means: find the flap mesh names, then
      search every `.banim` in the install for a track whose pivot sits on the
      roof, then confirm on screen. Slow and test heavy, so it waits.
      *Placeholder in the UI:* the Animation tab says "the game moves this wing"
      for these cars and offers no track, which is correct today.
- [ ] **[feat]** **Custom aero behaviours.** The game ships four:
      `DeployWhenBraking`, `DeployAtSpeed`, `BrakeAndSpeedCombo`,
      `NascarAirBrake`. They are not enough. The Pagani Huayra splits its
      spoilers left and right and moves them *with the steering*, and no shipped
      behaviour does that; a `DeployWhenSteering`-style behaviour would have to be
      invented. What is known: the behaviour word is a short ASCII string in the
      spec, `Spec.set_aero` can write any word, and the engine matches it against
      a table compiled into `libRealRacing3.so` - so an invented word is ignored
      rather than crashing. Making one actually work needs either a `.so` patch
      (the same machinery the random-music patch would use) or finding that the
      engine already understands more words than the shipped cars use.
      *Placeholder:* `rrmod.anim.AERO_CHOICES` is where a new entry would go;
      the dropdown reads it, so adding one there is all the UI needs.

### Map importer

- [ ] **[hold]** Importing a track. MonkeyTool can do it, and the shape of the
      job is clear (`Tracks/<name>/processed/high/<name>.m3g`, plus
      `resources/track`, plus a `.points`-like table for the start line and the
      grid slots), but three things are not: the **intro fly-by** is a `.banim`
      of its own with a camera path, the **car positions** on the grid are
      stored somewhere nobody has found yet, and the **minimap** is generated
      from the mesh rather than stored. Reversing those is a project, not a
      feature. A copy of MonkeyTool's importer without them would produce a
      track that loads and cannot be raced.

### Interiors

- [ ] **[hold]** See the "Interiors" entry above; kept here as its own heading
      because the user asked for it to be tracked separately.


## Done on 2026-11-08 (evening)

- [x] **[feat]** The Parts pane reads the *shared* file too. A Model dropdown
      lists every `.m3g` the car actually has, so the wheels, tyres, brake discs
      and calipers are reachable at all - they live in `<car>_shared.m3g`, never
      in the body. `materials.parts(..., model=)` reads whichever file is picked,
      and each row now carries the texture page its mesh tag samples.
- [x] **[feat]** A Textures tab: the 33 `ext_*` / `int_*` page slots, where each
      one's picture comes from (this car, `common/`, or not named at all), and
      which meshes read it. `A picture of your own...` swaps the page through
      `edit.set_texture_slot`, which is the other half of "a different tyre,
      disc or carbon weave" - the material is the first half.
- [x] **[fix]** The material groups were wrong. Seven of the prefixes in
      `GROUPS` (`car_rim`, `car_brake`, `car_caliper`, `car_chassis`,
      `car_carbon`, `car_interior`, `car_int`) matched nothing at all; the table
      is now built from what the 102 writable materials are really called
      (`Car paint` 24, `Bumper paint` 22, `Interior` 11, `Badges` 8, `Wheels` 7,
      `Bumpers` 6, `Trim` 6, `Glass` 5, `Lights` 5, `Brakes` 2, `Tyres` 2,
      `Mirrors` 2, `Effects` 2).
- [x] **[feat]** *Build a car* can write the aero clips. Section 5 of the dialog
      shows the donor's `_animations.xml`, lets a row be edited, added, removed
      or replaced by a default rest/up/down set, and hands the result to
      `anim.apply_xml` for both branches - so "add a wing to a car that never had
      one" is now possible without opening the Animation tab first.

## Done on 2026-11-08 (later)

- [x] **[feat]** The LOD slot table. `rrmod/slots.py` lists all 17 slots the game
      has (LOD A..H, `shared`, `int_a`, `int_b`, `frontend`, `wing_banim`,
      `animations`, `points`, `int_points`, `dashplanes`), works out which file
      goes where from its *name*, and renames it to what the game expects on the
      way in. `car.json` is no longer required: a folder of exported files is
      enough, and the manifest is only read for the `identity` block that a file
      name cannot carry. The Build dialog shows the table with a
      `Set file...` / `Clear slot` button per row, and *Modify an existing car*
      goes through the same table (`edit.install_slots`).
- [x] **[feat]** Each paint scheme can have its own finish. A car that ships one
      gloss and one matte factory colour needed this: `edit.set_paint_finish`
      grew `per_paint={index: material}`, and the Build dialog's paint table
      gained an editable Finish column, an Atlas column and a body-atlas picker
      (`edit.set_livery_texture`, which copies the picture in under the scheme's
      own stem).
- [x] **[feat]** A car's *Paints* tab is editable now: pick a scheme, change its
      finish from the game's own 15, its starting colour from a colour wheel, or
      its body atlas from a file, then save. `rrmod/ui/paintui.py`.
- [x] **[feat]** A car's *Parts* tab shows every mesh of a LOD, the material the
      engine will resolve for it, and where that answer came from (the paint
      scheme / the car's table / the shipped default / a hard coded fallback) -
      then lets one be pointed somewhere else. The dropdown only offers the 102
      materials the livery string table has a slot for, which is exactly the set
      that can be written; that is also the answer to "some parts use a texture
      in `common/`". `rrmod/materials.py` + `rrmod/ui/materialui.py`.
- [x] **[feat]** *Build a car* got an **Auto** tick box for the new car id (on by
      default; it follows the next free id so a mistyped id cannot overwrite
      another car), the full aero behaviour list (the same four the Animation tab
      has, plus the two speeds for the two that take them), and 17 slot rows.
- [x] **[docs]** `docs/锚点名清单.md`: all 142 anchor names the shipped cars use,
      with counts, the 4 that every car has (`POINT_WHEEL_FL/FR/BL/BR`), and the
      typos in the shipped data that should not be copied.

## Done on 2026-11-08

- [x] **[ui]** *Build a car* no longer runs off the bottom of the screen: the
      four sections live in a `QScrollArea` inside a resizable dialog. Asked for
      as "构建车辆面板过长且无法调整窗口大小".
- [x] **[feat]** Paint finishes. `custom.paints.nct` turned out to be a plain
      table of 31 rows (material name, starting colour, swatch overlay) and
      `custom.colours.nct` the game's own 42 colour palette; `rrmod/paints.py`
      reads both, keeping the file's 102 byte `Author:` trailer, and
      `edit.set_paint_finish` points a car's body (slot 30) and wing (slot 745)
      at any of the 15 materials. The dropdown lists materials, not rows,
      because eight rows share `car_paint_gloss`. The paint table in *Build a
      car* grew a Finish column, an *Apply to all* button, a colour picker
      (`QColorDialog`) and an editable `#rrggbb` cell.
- [x] **[ui]** The selected car's picture now sits beside its name in the
      detail pane, cut from the game's own `car_sales_car_<id>.png` (510 of 540
      cars have one; the rest say "no picture" rather than showing a blank).
- [x] **[ui]** *Tools ▸ Set window icon...* picks a picture for the title bar
      and the task bar and remembers it in `settings.ini`. The icon on the `.exe`
      file itself still needs a rebuild (`tools/rrmod.spec`'s `icon=`).

- [x] **[feat]** Brands: a *Brands* tab listing every manufacturer the install
      files a car under, with the game's own logo art, plus adding a brand and
      giving it a logo picture. `rrmod/brands.py` +
      `rrmod/ui/brandsui.py`. 53 brands, all 53 have a logo in
      `gui_assets/<size>/common/manufacturer_logos/` (67 pictures, 60 named
      `logo_<stem>.png`); 502 of 540 cars also carry a
      `GAMETEXT_CAR_MANUFACTURER_*` key for the display name. A brand is only a
      string in the spec (`Spec.set_make`, token 3), so a new one needs no record
      anywhere except our own `rr3mods.json` bookkeeping; its logo goes in as a
      new atlas page through `rrmod/atlas.add_picture` and is staged like any
      other edit.
- [x] **[feat]** *Build a car* now has a Make box (any shipped make, or type a
      new one; it follows the donor unless you have typed something), and the
      whole chain `install_pack(make=...)` → `build_car(make=...)` →
      `build_spec(make=...)` → `Spec.set_make` is wired. Round trip checked:
      LFA `Lexus` → `Nonesuch Motors`, 874 → 884 bytes, and model/id/appearance/
      class/stats all survive a re-parse.
- [x] **[feat]** Track maps: `rrmod/maps.py` keeps pictures the user brings, one
      per circuit, in a folder next to `rr3mods.json`, and the track picker
      prefers them over the game's card. The game has no stored layout map at all
      (the minimap is generated from the mesh), so this is a placeholder for
      whatever a real one would need.
- [x] **[feat]** ATC, ETC and PVRTC textures all decode now
      (`rr3lib/etcdecode.py`), through the same `texport.decode_frame` entry the
      DXT pages use. Measured against the DXT copy of the same art: ATC differs
      by 1.97/255, ETC by 2.37/255, PVRTC by 54 raw but 2.56 after the 2.2 gamma
      curve PVRTC pages are stored in.
- [x] **[feat]** Paint schemes and the class string for a new car
      (`build_livery(paints=...)`, `Spec.set_class`, the fourth section of the
      Build dialog), and the spec's own figures (`rrmod/stats.py`, nine writable
      numbers plus eight read-only ones).

## Done on 2026-11-09

- [x] **[bug]** The working copy never mirrored `vehicles/data`, and every symptom
      the user reported (m18743) came from that one gap: "this car is not
      installed" when ticking the wing box, the box then greyed out for good, the
      parts and paint lists emptied with no way back, "no such file or directory"
      when saving a paint finish, and an empty Deploy list. `Workspace.ensure_data()`
      now mirrors the whole tree (1142 files, 3.3 MB - picking leaves *was* the bug),
      `Editor._mirrored()` falls back to the install rather than trusting a partial
      workspace, and `capture()` walks the whole tree.
- [x] **[bug]** The same gap, one folder over: `vehicles/common` (298 files,
      13.4 MB - the glass, carbon, rotor and stitching pages every livery names by
      bare name) was never mirrored either, so replacing a shared page always
      failed with "not in this install, in any of the four GPU families".
      `ensure_common()` mirrors it, `mirrored()` wants both trees, and
      `SHARED_DIRS` keeps a staged shared page from being read as a car called
      "common" in the Deploy list.
- [x] **[ui]** The Deploy list has a checkbox per row (all ticked by default, with
      All / None), so a single file or a selection can be pushed. Quitting with
      something still staged now asks first ("Quit, keep them staged" / "Stay") -
      the working copy survives the process, but the user is entitled to know.
- [x] **[ui]** The Animation tab says so when a car has no wing animation at all
      ("Behaviour: none. This car has no wing animation...") instead of leaving the
      box greyed out. The flag and the banim are two different things; the message
      names the missing half.
- [x] **[bug]** `deployui._push_failed()` was a comma expression
      (`QMessageBox.critical(self, "Push failed"), text[:2000]`), so the failure
      dialog never had a body.

## Done on 2026-11-10

### Authoring a wing animation by hand

The Blender add-on could write a `.banim` from `AERO_*` empties, which is what the
vehicle importer builds. A wing the user has *split out of the body* has no empties
and no `rr3_track` tags - it is just four meshes with actions on them - so nothing
picked it up. Three changes make that the easy case instead of the impossible one.

- [x] **[feat]** `tracks_from = NAME`: the meshes whose name holds `part_filter`
      (default `WING`) become the tracks, grouped by **part base name** and numbered
      in **alphabetical order**. `LOD_A_WING_REAR_mm_ext` + `LOD_A_WING_REAR_mm_misc`
      are one part (`WING_REAR`) and get **one** track; `WING_STRUT` is track 1 and
      `WING_STRUT_REAR` track 2. No empties, no tags.
      The rule is not a guess: across the 52 cars that ship a wing `.banim`, the
      number of distinct base names (minus `*_BRAKES` riders) equals the number of
      tracks **52 times out of 52**, and on the three cars with a `_LEFT`/`_RIGHT`
      pair the alphabetical order is the one that puts the left flap on the left
      (verified against the x of track channel 0). m3g file order is *not* the
      track order - it disagrees on 2 of 3 such cars.
      `*_BRAKES` is skipped: a wing brake light is its own mesh but rides on the
      wing, and no shipped car gives it a track.
- [x] **[bug]** `NAME` mode used to be re-sorted by object name after grouping,
      which undid the numbering: `LOD_A_WING_STRUT_REAR_mm_misc` sorts before
      `LOD_A_WING_STRUT_mm_misc` (capital `R` is below lower case `m`), so the two
      struts swapped tracks and each flap followed the other's motion.
- [x] **[bug]** An animated mesh exported with `use_world=True` (the panel default)
      had its origin baked into the vertices. The game places a part at
      `pivot + R @ vertex`, so the part ended up at twice its offset from the car.
      `m3gexport.collect_parts` now forces **local** coordinates for any mesh that
      is animated - it has an action of its own, or sits under an `AERO_*` empty
      that has one. Static meshes are untouched (their origin is zero, so both
      paths agree). Measured on the LFA project: the wing's local box is
      `(-0.511, -0.257, -0.104) .. (0.511, 0.109, 0.029)`; it used to export as
      `(-0.511, 0.829, 1.715) .. (0.511, 0.962, 2.08)` and now exports as
      `(-0.511, -0.104, -0.109) .. (0.511, 0.029, 0.257)` after the axis swap.

Smoke suite: 16 -> 18 steps (`part tracks`, `animated parts stay local`).

## Done on 2026-11-11

### Undo used to break the whole app

A user report read like five bugs (undo loses the edit but the car page keeps it,
the paint and parts lists go blank, Deploy cannot read the workspace, only deleting
the workspace folder helps). It was **one bug with three knock-on defects**, all
rooted in ``workspace.clear()``.

- [x] **[bug]** ``clear()`` deleted every file but left the folders and left the
      ``_data_done`` / ``_common_done`` flags set. The next ``ensure_car`` saw the
      flag, skipped the mirror, and the workspace stayed empty for the rest of the
      session. ``mirrored()`` only checked ``isdir``, so it kept saying yes and every
      page read through the empty copy: no spec means no cars, so Deploy listed
      nothing and the paint page raised ``no such file``. Deleting the folder by hand
      worked only because that made ``exists()`` false.
      Fix: ``_has_files()`` (a directory with no files in it is not a mirror),
      ``clear()`` resets both flags and ``rmdir``s the emptied folders, and
      ``mirrored()`` / ``ensure_car`` / ``ensure_data`` / ``ensure_common`` all use
      ``_has_files`` so a stale flag heals itself.
- [x] **[bug]** The car detail page was never re-read after an undo, so it kept
      showing the edit that had just been thrown away. ``_staged_cleared()`` is now
      separate from ``_staged_changed()``: a discard refreshes the detail page, an
      ordinary staged edit does not - refreshing on every edit would wipe a
      half-typed value in a pane the user has not saved yet.
- [x] **[feat]** ``Workspace.mark_pushed()``: a pushed file used to stay in the
      staged list for ever, so Deploy kept offering it, the quit prompt kept asking,
      and a second push sent the same bytes again. The push now records the md5, size
      and mtime of what was sent, and ``pending()`` skips a row that still matches.
      Size and mtime are compared before hashing (a pushed LOD is several MB, and
      the summary is drawn on every refresh): 8 ms -> 0.7 ms for three LODs.
      Editing the file brings the row back by itself.

Not a code problem: ``adb devices`` reported ``emulator-5554  offline``. Restarting
the server (``adb kill-server`` then ``start-server``) brought it back.

Tests: 672 -> **693** (group 58).

### Find device, the size of the working copy, and the asset lists

Three more reports from the same evening. Two were real, one was a misunderstanding
that turned out to hide a third bug.

- [x] **[bug]** *Find device* kept failing. ``settings.ini`` held ``adb_port=5555``
      and that value was passed as ``ANDROID_ADB_SERVER_PORT`` - but 5555 is the
      emulator's own adbd port, the adb *server* listens on 5037. Every call to it
      hung until the timeout, which the interface then reported as "adb sees no
      devices". ``_port_works()`` now checks a remembered port once and falls back
      to the default; the answer is cached, so the cost is 6.1 s once and 0.08 s
      after that. **The probe has to be ``adb devices``, not ``adb version``** -
      with no server running, ``version`` starts one on the port it was told about
      and reports success, on a server that cannot see the device. ``adb devices``
      alone is not enough either: it prints the ``List of devices attached`` header
      even when the list is empty, so the test is a real device line. ``probe()``
      also reports the port that actually worked (``effective_port()``), because
      the interface saves that answer straight back into ``settings.ini`` and
      echoing the requested value kept the dead setting alive for ever.
      ``DeployPage._remember_port()`` finishes the job: *Find device* now puts the
      port that answered back into the box, so the dead 5555 stops being paid for
      on every call.
- [x] **[bug]** The working copy copied far more than an edit needs:
      ``ensure_data()`` mirrored all 1142 files of ``vehicles/data`` and
      ``ensure_common()`` all 298 files (13.4 MB) of ``vehicles/common``. Now
      ``ensure_data()`` copies only what the readers ask for (540 specs, the nine
      shared tables, ``custom.*``, two livery tables - about 1.6 MB), and two new
      functions copy the rest per car: ``ensure_livery()`` for the car's own livery
      table and ``ensure_car_pages()`` for the texture pages it names. Measured:
      **14-19 pages / 0.95-1.39 MB per car** (median 1.31 MB over all 540), against
      13.4 MB for the whole shared tree. ``mirrored()`` no longer requires
      ``vehicles/common``, and ``for_tables()`` takes the donor so a build can read
      the donor's paint schemes.
- [x] **[bug]** Discarding an edit left the asset lists edited. An edit that adds a
      file appends a row for it; keeping that row after the file is gone makes the
      next push merge a row onto the device that names a banim or an m3g the device
      does not have. ``Workspace._reset_manifests()`` puts the workspace's lists
      back to the install's copies on every discard. The invariant to test is
      byte equality with the install, **not a row count** - an earlier edit may
      already have written a row for the same path, so the second one rewrites it
      in place and the count does not move.
- [x] **[ui]** The asset lists are rewritten during Push (merged onto the device's
      own copies), so they never appear in the Prepare list - which reads as "the
      lists were forgotten". ``deploy.following_manifests()`` names them, and the
      Deploy page says so under the table: *"Push also rewrites 2 asset list(s),
      merged onto the device's own copies: ... They are not staged files, so they
      are not in the list above."*

Tests: 693 -> **701** (group 58, eight assertions added).

## Done on 2026-11-11 (night)

### A wing needs paint rows, and folders need the search bit

Three faults found while getting the hand-built LFA wing into the game. Two are
in the manager, one in the Blender add-on.

- [x] **[bug]** A wing the studio did not model comes out **almost black**.
      The paint a part wears is decided by the livery table, not by the model:
      `LOD_A_WING_REAR_mm_ext` is slot **745**, and a scheme with no row for 745
      falls back to `car_flat`, whose `mu_MaterialSpecularColour_Base` is
      `0,0,0`, whose `Power` is 1 and whose fresnel ramp is the only pure black
      one in the game. Every shipped car with a body coloured wing writes the
      body's material into the wing's slot, scheme by scheme - that is the fix.
      New `edit.sync_wing_paint(root, name, *, body_part, parts)` reads the wing
      meshes out of the model (`edit.wing_parts()`), and for each one whose slot
      **no scheme covers** copies the body's material into it. Slots that are
      already covered are left alone, so a carbon wing keeps its carbon. Both
      build branches call it, passing `parts=` the meshes the pack actually
      brought in - a shipped wing the donor already painted must not be
      repainted by us.
- [x] **[bug]** `chmod -R 644` on a pushed folder clears the execute bit on
      every folder it walks into, and a folder without execute cannot be
      **searched**: the game then cannot `stat` anything inside it. This was not
      theoretical - a push ending in `chmod 660 <car>/*` turned the LFA's
      `livery` folder into `drw-rw----`, the six paint atlases inside became
      unreadable, and the renderer drew the magenta "missing texture"
      checkerboard. Logcat said so plainly:
      `search permission is denied during stat() for a component of the path`.
      New `Device.fix_permissions()` gives folders **2770** (the setgid bit keeps
      the group right for files the engine writes) and files **660**, in two
      separate `find` passes. `push_tree()` uses it.
- [x] **[feat]** The Blender add-on writes a wing `.banim` the engine actually
      plays: the **container** (magic `0x7F7F7F00`, variant, version, the trailer
      words, the `AE_*` name list) cannot be computed - the trailer is an engine
      hash over six fixed values - so the operator gained a **Container from**
      file picker and `rr3_export._inherit_container()` copies it from a shipped
      `_wing.banim` with the same track count. The **curves** are written as
      nodes in slot 0 (one per frame) and **Bezier control points in slot 1**
      (two per span, at the 1/3 and 2/3 marks); writing samples into slot 1 makes
      the engine read them as controls and the part hitches at every keyframe.
      All 96 shipped wing tracks satisfy `n1 == 2 * (n0 - 1)` - 95 of 96 exactly,
      the odd one out being a two-key constant.

Tests: 701 -> **724** (group 59: wing paint rows, the folder mode, and the
no-blanket-chmod guard).

## Done on 2026-11-12

### The trailer was the whole reason the wing vanished

- [x] **[bug]** A wing `.banim` exported without a donor file **loads and then
      does nothing**: the engine reads the clip, finds no trailer, and never
      applies it, so the part stays at its modelled origin. On a car whose wing
      was cut out of the body and given its own origin that is indistinguishable
      from the wing having been deleted. The previous fix made the operator
      *require* a donor instead of solving it, so a user who exported through a
      path without one silently shipped a dead file.

      The trailer is `u32 n` followed by `n` words, one per track, and `n` is
      always the track count. The words are **constants of the part**, not
      hashes: crc32, crc32c, adler32, fnv1/fnv1a, djb2, sdbm, elf, oaat, java,
      murmur3 and xxh32 over every spelling of the name (with and without
      `LOD_A_`, `AERO_`, `_mm_ext`, ascii and utf-16) produce none of them. What
      does hold is that across the 52 cars whose track count matches their part
      count, the **multiset** of trailer words equals the multiset of the six
      part constants every single time:

      | part | word | cars |
      |---|---|---|
      | `WING` | `0x6C8C2CFD` | 10 |
      | `WING_REAR` | `0xAD45C13F` | 39 |
      | `WING_REAR_LEFT` | `0x4202CB14` | 3 |
      | `WING_REAR_RIGHT` | `0x344991DE` | 3 |
      | `WING_STRUT` | `0x89CEF5E4` | 13 |
      | `WING_STRUT_REAR` | `0x57529DC8` | 16 |

      So `rr3_export.TRAILER_WORDS` + `trailer_words_for(bases)` write the
      trailer from the part names, `_synthesize_container()` supplies the magic
      (`0x7F7F7F00`) and the plain variant, and the **donor became optional**.
      Verified: exporting the LFA wing with a donor and without one produces
      **byte-identical** files (19,536 B, md5 `38176db29b51b9da…`).
- [x] **[bug]** The manager now says so when a staged `.banim` has no trailer:
      `anim.read()` adds a warning that names the symptom ("the game will load it
      and then never move anything, so the wing will look as if it is missing")
      rather than the field. The animation page shows it before a push, which is
      the only place it can still be caught.
- [x] **[note]** The m3g `aero` flag (`gap81[17]`) was **not** the cause and is
      not needed: the working build the user already confirmed had it clear on
      all four wing meshes. It is also not a general rule - 1,347 shipped meshes
      carry a morph table with the flag clear, and 6 cars with a wing `.banim`
      have no flagged `_mm_ext` at all. Where the flag *is* set (83 meshes) a
      tail is always present, so a future flag writer must write `count = 0` at
      minimum rather than nothing.

Tests: 724 -> **729** (group 60: a trailerless banim is reported, a trailered
one is silent, and the trailer survives a round trip).

## Done on 2026-11-14

### Undo steps became a panel you can see, name, pin and move

- [x] **[feat]** `rrmod/history.py`: one folder per edit with a `.json` note
      beside it (`title`, `when`, `files`, `pinned`), a twenty-step limit that
      skips pinned steps, `restore()` that walks newest-first so the oldest
      ticked step's bytes win, and `set_dir()` so the whole history can live on
      another disk.  `edit._begin()` now only mints the name; the folder and the
      note are made in `_backup()`, the first place that knows the working copy.
- [x] **[ui]** `rrmod/ui/historyui.py`: a `QDockWidget` that can be dragged out
      and left floating beside the window, four columns (tick / time / what it
      did / files), *Undo these (N)*, *Pin*, *Forget*, *Tick all*, *Folder...*,
      and a footer saying where the copies are and how much room is left.  Ctrl+H
      shows it; it starts hidden.
- [x] **[feat]** `workspace.undo_steps(stamps_)` replaces the single-step undo,
      so "take me back to before the wing *and* the paint" is one action.
- [x] **[feat]** `settings.history_dir()` / `history_keep()`, and the twelve edit
      functions now give their step a sentence instead of a folder name.

`Tests: 749 -> **776** (group 62)`

### A project file that remembers the answers, not just the bytes

- [x] **[feat]** `rrmod/project.py`: `.rr3proj` is a zip holding
      `project.json` plus `files/<game path>`.  The manifest carries the name,
      who made it, when, `install_md5` (the registry file's md5, the one list
      that names every asset and that this program never writes to), and
      **`params` - the three dozen keys `BuildDialog.result_info()` returns**,
      which until now were never written down anywhere.  A rebuild meant
      retyping the id, the appearance record, the paint slots, the aero
      behaviour and the two prices from memory.
- [x] **[feat]** `save()` / `read()` / `describe()` / `open_project()`.
      Level 1 deflate on purpose: measured on a real car (33 files, 7.37 MB),
      level 1 gives 4.90 MB in 0.23 s against level 9's 4.84 MB in 0.33 s, and
      the `.dds.z` and `.bin` inside come out at 100% anyway - only the `.m3g`
      is being squeezed, at 46%.  Files over 4 MB are stored rather than
      deflated.  `open_project()` writes into the working copy and stages, so
      the Deploy tab offers exactly what the project holds.
- [x] **[ui]** *File > Save a project...* (Ctrl+S) and *Open a project...*.
      `build_car()` now keeps `params_from(result_info())` - the dialog's
      answers are gone the moment it closes.  Opening a project made against a
      different build says so instead of silently writing an id the game has
      since taken.
- [x] **[feat]** The undo steps travel with the project, under `history/`, and
      come back titled `(from a project)`.  Opening the same project twice bumps
      the suffix instead of chaining it (`-p1`, `-p2`, never `-p1-p1`).

`Tests: 776 -> **804** (group 63)`

## Done on 2026-11-13

### The three brand bugs, and the 1,233 asset lists nobody was updating

- [x] **[feat]** `manifestlib.owner_of(path)` - which of the 1,236 asset lists
      claims a path. `AssetIndex` / `build_asset_index()` / `owner_of(pkg, path)`
      scan 114,307 paths in **0.25 s** with **0 duplicates across all lists**, so
      the index is built at startup and never cached to disk. The mapping is a
      function, not a guess: one path, one book.

      The ordering rule reproduces **1,227 of 1,233** lists: four GPU family
      blocks (`.atc.dds.z`, `.dxt.dds.z`, `.etc.dds.z`, `.ptc.pvr.z`) each
      contiguous and sorted inside itself, non-texture rows first. Two traps:
      `family_of()` must use `suffix in path`, not `endswith` (a row ending
      `.dxt.dds.z.bin` is not a texture and judging by `endswith` turns 468 lists
      into "unordered"); and an insert goes into the **first** run of its family
      (`same[0]`), not the last, or 8 lists stop reproducing. The remaining 6 are
      histories of an append-after-the-fact and are ascending internally anyway.
- [x] **[bug]** Adding a brand triggered a **download**. `edit.sync_file()` only
      ever updated three books (the per-car list, the registry, and
      `asset_list_vehicle_data.txt`) and silently ignored the other 1,233. A logo
      page lives under `gui_assets/` and is claimed by
      `asset_list_gui_assets_core.txt`, which nobody wrote, so the engine saw a
      file on disk that no list mentioned and asked the cloud for it.
      `_sync_other_list()` now claims the right book, **seeds it from the install
      when the working copy does not have it**, and refuses to write at all when
      no book claims the path and no book claims any of its folders
      (`"no asset list claims ... so the game would never find it"`).
- [x] **[bug]** A logo added to a brand **did not appear**. Two reasons:
      `atlas._INDEX`/`_PIXELS` were module-level caches with no invalidation, and
      `BrandsPage._logo_for()` read `self.depot` - the install - while
      `add_logo()` writes into the working copy. Now `_read_depot()` prefers the
      working copy and `_write()` calls `atlas.forget()` plus clears its own
      pixmap cache.
- [x] **[bug]** A brand could not be removed, and **undo threw away the car as
      well**. `unregister_brand()` existed but had no button; `undo_last()` called
      `ws.clear()`, which empties the whole working copy. Now `Remove...` forgets
      one brand (refusing the game's own makes, and saying how many cars still
      name it), `undo_last()` walks back **one edit** via
      `workspace.undo_step()`, and `discard_staged()` is the separate "throw it
      all away" action.
- [x] **[note]** Undo needed two supporting pieces that were missing.
      `.absent` markers: a file the edit *creates* gets an empty
      `<rel>.absent` entry, so undoing removes it - without that, undoing "add a
      banim" left the banim behind, a half-undo that is harder to spot than none.
      And "first copy wins" in `_backup()`: one edit that touches the same file
      several times (the logo writes the atlas, then its manifest row, then
      another page's row) used to overwrite its own backup with its own output,
      so the undo restored the edit. That was the last failing assertion.
- [x] **[feat]** `workspace.ensure_lists()` mirrors every `apk/res/asset_list*`
      into the working copy. Without it the index cannot tell "no book claims
      this path" from "that book was never mirrored", and the second case looks
      exactly like the download bug.

Tests: 729 -> **749** (group 61: the index claims a new page by its neighbours,
the atlas row is rewritten rather than appended, undo deletes the new page,
restores the atlas byte for byte, leaves nothing staged, and the brand page has
its remove button).

## Done on 2026-11-15

### A shared page is four rows, one dependency, and one push that can be undone

- [x] **[feat]** Book a page added to `vehicles/common` in all four GPU families.
      `asset_list_vehicle_common.txt` is 1,192 rows of 298 stems, but the four
      families sit in four consecutive runs (atc 0-298, dxt 298-596, etc 596-894,
      ptc 894-1192) and the four hashes of one stem never match, so a page has to
      be inserted four times, once inside each run.  `edit._sync_common_page()`
      does that and reports how many rows it added; adding the same page twice
      adds none.
- [x] **[feat]** Know who names a shared page, and who brought it here.
      `rrmod/deps.py` answers the first by scanning all 540 livery tables on
      demand (0.3 s, never cached, so it cannot go stale) and the second from
      `deps.json`, because nothing on disk records that.  The key is the stem
      without its GPU suffix.  `shipped()` asks the *install*, found through the
      working copy's `pending.json` - asking the working copy would call a page
      added a minute ago the game's own.
- [x] **[feat]** Add a name the game has never heard of to the slot table.
      `SlotTable.append()` / `append_all()` and `serialize_slot_table()` /
      `save_slot_table()` / `slot_table_path()` in `rr3lib/livery.py`, wrapped by
      `edit.add_slot_names()`.  A mesh name the string table does not list gets no
      material, and slots are positions, so the only safe change is appending:
      2,068 -> 2,069 names, +26 bytes, every existing slot keeps its number.
- [x] **[feat]** Remember what the device held before a push, and put it back.
      `rrmod/backup.py` copies the device's own bytes for exactly the files in the
      plan - including the asset lists that are about to be merged - into
      `_backup/<id>/` with a `_before.json`, and keeps a stack in `_state.json`.
      A file the device did not have is recorded as `absent` so an uninstall
      deletes it.  Taking an older push off first is refused: two mods that touch
      one file must come off in the reverse order they went on.
- [x] **[ui]** A button that takes the last push back, and a line saying how much
      is remembered.  The copy is taken on the worker thread while the push is
      being prepared, so a few hundred megabytes of pull cannot freeze the window.

Tests: 804 -> **862** (groups 64, 65, 66).

## Done on 2026-11-16

### The second half of phase 2: pointing a slot at a page the game already has

- [x] **[feat]** A texture slot can be pointed at a page that already ships.
      `edit.set_texture_slot_page()` changes one livery row and copies nothing -
      another tyre tread, another brake disc, another interior weave, all already
      on the device.  `textures.shipped_pages()` lists the candidates and
      `_kind_of()` keeps the list to pages of the same kind, because 298 pages at
      once is a menu nobody can use.  The family suffix is taken from the row
      being replaced, not from the disk: every one of the 14,370 livery rows names
      a `.ptc.pvr.z` page while all 298 files on disk are `.dxt.dds.z`.
- [x] **[ui]** Materials -> Textures has a third button, "Use another shipped
      page...", with a "only pages of the same kind" tick box and a confirmation
      that says plainly that no space is used and only the livery table is pushed.
- [x] **[feat]** A Dependencies page (the ninth tab) that answers two questions
      that must not share an answer: who names a page *now* (a live scan of all
      540 livery tables, 0.3 s, never cached) and who *brought* it (deps.json).
      A shipped page is never deletable - 51 of the 298 are named by no car and
      are still the game's.  Only a page this program added that nothing names
      any more is offered for removal, and deleting it takes the file, its four
      rows in `asset_list_vehicle_common.txt` and its registry row.
- [x] **[ui]** The page lists every page with its user count, marks the ones this
      program added, reports the two pages a stock install names but does not
      hold (`common/car_tyre_01`, `common/car_windows_banner_nascar_2021`) and
      says why that is a report rather than a fault.

Tests: 862 -> **903** (groups 67, 68).

## Done on 2026-11-17

### Phase 3: one build, two programs, and a pack that says what it needs

- [x] **[feat]** `rrmod/profile.py`: the ten pages split into the ones a mod
      studio shows and the ones a manager shows.  The line is drawn by *who owns
      the truth* - the studio makes mods and needs no device, the manager installs
      them and does not edit the career.  Shared by both: Cars, Materials,
      Dependencies, About.  Studio only: Career, Brands, Publish.  Manager only:
      Music, Graphics, Deploy.  Switching profile uses `QTabWidget.setTabVisible`,
      so a page is hidden and never destroyed - no page loses what it was in the
      middle of, and nothing is built twice.  The window title follows
      (`RR3 Mod Studio` / `RR3 Mod Manager`), the choice is remembered in
      `settings.ini`, and `--studio` / `--manager` / `--all` override it.
- [x] **[feat]** `rrmod/pack.py`: the `.rr3mod` format - one zip, a `mod.json`
      naming the kind, what it carries and **what it needs**, and `check()`
      answering `ready` / `missing` / `absent`.  A format 1 share is lifted to a
      car pack so old files keep working.
- [x] **[feat]** `rrmod/publish.py`: six kinds gathered into a pack - a car (with
      the non-shipped shared pages it names), shared pages, a driver pose and the
      low-poly body that can wear it, a manufacturer's logo, the career (merged,
      never replaced) and a circuit picture - plus `install()` back.
- [x] **[ui]** A Publish page (the eighth tab): pick a kind, pick the thing, see
      what it would carry, write the file; and the other direction, open a pack
      somebody sent and see what it needs *before* installing it.

Tests: 903 -> **942** (groups 69, 70).

## Done on 2026-11-18

### Phase 4: a material is a block, so a copy is appended and never edited

- [x] **[feat]** `rr3lib/gamematerial.py` grew a writing half:
      `block_spans()` (297 spans, the first record of every one is `K_TWOSIDED`),
      `encode_record` / `encode_records` (`encode_records(load_records(p)) == p`
      byte for byte), `clone_block(recs, name, new_name, template=, overrides=)`,
      `insert_block` / `insert_blocks`, `save_bytes`. The clone copies the whole
      block - application, cull, blend, primitive, stencil and flags included -
      because a new name that is not an instance of that template looks its
      shader up and finds nothing. 292 bytes on a full install
      (135,065 -> 135,357 B), 297 materials and 186 shaders all still readable.
- [x] **[feat]** `edit.add_material()` / `edit.remove_material()`. Adding appends
      the block, re-hashes `asset_list_startup.txt` (the one list that claims
      `materials.bin`) and the registry, and gives the new name a livery slot in
      the same step, because a material with no slot is one no car can wear.
      Removing splices that one block out and refuses two cases: the game's own
      296 (told apart by asking the install, which never changes) and a copy a
      car still names, unless forced.
- [x] **[feat]** The Materials page writes. `Copy this one...` asks for a name
      (default `<source>_copy`) and keeps the source's application, cull, blend,
      flags and colour; `Delete this copy` is only enabled for a material this
      program added. The page says in as many words why a field inside a block is
      not editable here.
- [x] **[feat]** A `material` pack kind: `publish.cloned_materials()` lists what
      the working copy added, `publish.materials()` packs the library with those
      names in the manifest, and installing merges - a block the receiver already
      has is left as they tuned it, so two people who each cloned one end up with
      both.
- [x] **[bug]** Three real bugs found on the way, all of them silent:
      `_install_abs()` was missing the `.depot` segment, so the "is this the
      game's own?" check always said no; `Editor.depot` returned
      `ws.depot` (the *install*) instead of `ws.ws_depot` (the working copy), so
      the page could not see the row it had just made; and `for_materials()`
      mirrored `materials.bin` but not the folder the slot table lives in, so the
      automatic slot was dropped without a word.

Tests: 942 -> **970** (group 71)

## Done on 2026-11-19

### A car's driver pose is a field in its data record, walked not offset

- [x] **[feat]** `rr3lib/driver.py` can read *and write* the seated pose.
      `field_offset()` finds it by walking: from the end of the `CAR_NAME_` string,
      twelve tokens along, the thirteenth is the field's length prefix. Walking
      rather than an offset matters - the tokens in between are not the same shape
      in every record (`nnnnnnnnnnnn` 108, `ssnnnnnnnnnn` 52, `snnnnnnnnnnn` 51,
      `nnnnnnnnnn` 1), and nine records fold the field into what a naive tokenizer
      reads as one number. `field_in_record()` returns three states on purpose:
      a name, `""` for "this car has none and the game uses `driver.banim`", and
      `None` for "the record cannot be read". 540/540 hit, zero disagreements with
      the old whole-file scan: 224 named, 316 empty, 0 unreadable.
- [x] **[feat]** `driver.set_field()` writes it and keeps the encryption as it
      found it (`nctlib.looks_encrypted` -> the same `encrypt` on the way out). The
      record is a self-describing token stream, so splicing is safe: clear the
      field on a copy of the LFA's record and the file is 874 bytes again, byte for
      byte. It refuses a name that is not a `.banim` and a name that is not ASCII.
- [x] **[feat]** `edit.set_driver_pose()` plus the *Animation* tab's "Driver pose"
      dropdown (the generic entry first, then the 35 poses the install ships). The
      dependency is reported rather than refused: only 12 of the 33 poses have a
      `driver_lod_c_<x>.m3g`, so the pane says either "this pose has its own
      low-poly model, X, so the outside view is shaped for it" or "this pose has no
      low-poly model of its own, so the outside view uses the generic
      `driver_lod_c.m3g` and the figure holds a pose nothing modelled for it".
- [x] **[bug]** `edit._driver_dir()` returns the **depot root**, not the `driver`
      folder, because every reader in `rr3lib.driver` takes a depot and appends
      `driver` to it. It also never mirrors the folder (64 files, 3.2 MB): no car
      edit writes there, so the working copy falls back to the install's copy and
      nothing is copied per car.
- [x] **[ui]** The pane has to call `_collect()` after a change, or the record is
      written but never staged - the same trap the wing and paint editors avoid the
      same way.

Tests: 970 -> **993** (group 72)

## Done on 2026-11-20

### The decal list, read and reported

- [x] **[feat]** `rr3lib/decals.py`: `custom.decals.nct` reads and writes byte for
      byte. 229 records, `version 11`, 142-160 bytes each, and 162 bytes of author
      trailer behind the last one that has to come back untouched.
- [x] **[feat]** A record draws **either** a glyph **or** a page: 187 name a code
      point, 42 name a `.pvr` under `vehicles/decals/`. Nothing in the file says
      which, so the reader decides by which field is filled - and a reader that
      only looks at one field loses most of the list.
- [x] **[bug]** A code point is written two ways: 148 records spell it `0x0029`
      and 81 spell it as the character itself. Accepting only one spelling drops
      two thirds of the shapes without any error at all.
- [x] **[feat]** `rrmod/decals.py` reads the font as well: 232 glyphs, 237 mapped
      code points, and **all 163 code points the list uses are in it**. So
      `missing_from_font` is 0 on a shipped install, which makes it a real signal
      rather than a permanent complaint.
- [x] **[ui]** The Decals page (`rrmod/ui/decalui.py`) lists every record with the
      name the player sees, the kind, what it draws, its category and its name key,
      with a filter and a "only the ones that will not draw" tick. It runs on a
      worker thread because reading the font's cmap is not free.
- [x] **[bug]** 199 of the 229 name keys are absent from `gametext.txt` and that is
      normal - the game shows the shape itself. So the page falls back to the code
      point or the page's file name rather than showing a blank row, and it marks
      which rows have no key.
- [x] **[ui]** The tab count went from 10 to 11 and `profile.py` had to learn the
      page, or the studio and the manager would both have shown a tab nobody could
      place.

Tests: 1003 -> **1030** (group 74)

## Done on 2026-11-21

### A decal record can be changed, and the whole file still comes back

- [x] **[feat]** `rr3lib/decals.py` grew `code_point_text`, `set_record` and
      `move`, and `rrmod/edit.py` grew `set_decal`, `add_decal`, `remove_decal`
      and `move_decal`.  All four round trip: renaming a record and renaming it
      back restores the file byte for byte, and so does adding one and removing
      it, for both halves of the format.
- [x] **[ui]** The Decals page has "Change this record...", "Add a record..." and
      "Remove this record", plus a dialog that shows what the record has.  It
      reports only the fields that actually changed, so opening a record and
      pressing OK writes nothing.
- [x] **[bug]** Reading a working copy threw `TextError: no gametext.txt or
      text_<lang>.txt was given`, because `gametext.txt` lives at the root of
      `.depot` and no car edit ever mirrors it.  `rrmod/decals.py` now has
      `_texts()`, which lets the names fall back instead of failing the page.
- [x] **[bug]** `rows()` had no `position`, so the dialog could not tell whether
      the order had been changed.  It is in the row now.

Tests: 1043 -> **1069** (group 76)

## Done on 2026-11-22

### A shape is two files, so it is written as one step

- [x] **`rr3lib/ttf.py` reads and writes `r3_decals.ttf`.**  312,380 B, eleven
  tables, 232 glyphs (186 drawn, 46 empty), 237 code points, both cmap encodings
  sharing one format 4 subtable.  An untouched font is handed back byte for byte;
  a font with a new glyph is rebuilt whole, because one glyph moves `glyf`,
  `loca`, `hmtx`, `hhea`, `maxp`, `cmap` and `head` at once.
- [x] **Two bugs found by testing, not by reading.**  The table directory's
  `searchRange` shift overflowed 16 bits (`struct.error: 'H' format requires
  0 <= number <= 65535`), and `_build_format4` could not tell "this segment uses
  the delta" from "the offset really is zero", which moved 23 code points onto
  the wrong glyphs.  `hhea.numberOfHMetrics` also has to follow the glyph count
  or a new glyph's advance is read out of its neighbour's side bearing.
- [x] **`edit.add_decal_shape()` writes the glyph and the record in one undo
  step, font first.**  A record that names a code point the font does not have
  draws nothing and says nothing about why; a glyph no record names is merely
  invisible.  `remove_decal_shape()` empties the glyph only when no other record
  still names it.
- [x] **`rrmod/ui/shapedlg.py` draws one.**  Seven presets, a canvas where a click
  adds a point and a double click removes one, `fit_contours` to grow a drawing to
  the em box, and a code point picker that refuses one the font already uses.

Tests: 1069 -> **1107** (group 77 and the dialog checks).

### A page can be written in three of the four families

- [x] **`rr3lib/blockencode.py`: ETC1 and ATC block encoders.**  ETC1 tries both
  the individual and the differential base colour modes per block and keeps the
  closer one; ATC runs one line of four colours through the block and picks the
  endpoints that leave the fewest pixels off the line.  Measured against the DXT
  copy of the same page: **ETC1 1.89, ATC 1.04** mean absolute difference per
  channel, which is the format's own precision and not a comparison of two
  pictures.
- [x] **`texport.build_texture` writes `.etc.dds.z` and `.atc.dds.z`, and
  `ddsencode.header` takes a fourcc.**  The two families share DXT1's eight bytes
  per block, so the header differs only in the four characters.
- [x] **`rrmod.textures.replace` encodes back into the family the file on disk is
  in.**  A depot unpacked for a Mali device holds only the ETC copy, and writing a
  DXT file under an `.etc` name would produce a page the engine decodes as
  garbage.
- [x] **PVRTC still refused, now with the reason.**  Its endpoints are
  interpolated across block boundaries, so encoding one block changes its
  neighbours; `build_texture` says "interpolate" and stops.
- [x] **Two pixel-order bugs caught by comparing pixels, not by round tripping.**
  ETC walks a block as `x = i >> 2, y = i & 3` and ATC as `x = i & 3,
  y = i >> 2`.  Both wrong ways still decode to a picture, so only a comparison
  against the DXT copy finds them.

Tests: 1107 -> **1127** (group 78).

## Done on 2026-11-23

### Two shared folders, pictures that travel, and a family chosen on install

- [x] **The dependencies page has one tab per shared folder.**  The game keeps
  `vehicles/common` (298 pages, named by the 540 livery tables) and
  `Tracks/common` (2,313 files, named by nothing but the artist's own path inside
  each track model).  Same rules - four rows per stem, a shipped page is never
  deleted, only orphans are offered - but different enough that one page could
  not honestly describe both.
- [x] **The track side reads its users out of the models as bytes.**  Parsing the
  30 track models as m3g takes 18.1 s; finding the same `Tracks/common/...`
  strings with a regex takes 0.52 s.  `track_report` answers in 0.59 s:
  1,290 pages named, 2,313 on disk, 1,025 unreferenced, 2 missing.
- [x] **A track page's asset list is looked up, never guessed.**  Nineteen lists,
  one per top folder.  A page under `mat/metal/` belongs to
  `asset_list_track_common_mat.txt`; a path with no folder in it is refused,
  because a page booked into the wrong list is a page the engine never finds.
- [x] **A page keeps the picture it was made from.**  `textures.replace` copies
  the source PNG into `<working copy>/_rrmod_source/`, a pack carries it under
  `pictures/`, and the receiver encodes it for their own GPU.  Shipping the
  finished page would pin the pack to the author's hardware.
- [x] **`publish.install(..., family=)`.**  `auto` (whichever family this install
  already holds), `dxt`, `etc` or `atc`; the choice is remembered in
  `settings.ini`.  The page keeps the size the shipped one had, because the game
  allocates by size and nothing here rescales.
- [x] **A missing shared page is a warning, not a refusal.**  It used to block the
  install, which meant a trimmed install could not take a whole car over one
  texture it did not carry.  Every other kind of missing requirement still
  refuses - a pose with no driver in it is broken, not merely ugly.
- [x] **`pack.check` understands a pack that carries only pictures.**  A manifest
  with no finished files is not empty when it lists pictures; those become pages
  at install time.
- [x] **The textures pane follows the model dropdown.**  `car_pages(model=...)`
  reads one file instead of all four, so switching to the interior stops listing
  the body's meshes.
- [x] **A numbered `_mm_` tag falls back to the unnumbered page.**
  `_mm_windows001` reads `ext_windows`, because the slot table has no
  `ext_windows001`; `mat00`..`mat07` are exempt, being eight genuinely different
  pages.

Tests: 1127 -> **1190** (groups 79, 80 and 81).

## Done on 2026-11-24

### One car list, and an install that asks

- [x] **The car list is one table, not three.**  "The game's cars" beside "my
  mods" beside "unmanaged" made the delete button depend on a `rr3mods.json`
  record that nothing could check - and a shipped car is cheap to get back
  (reinstall the data package, or read `_rrmod_backup`), so refusing to delete it
  bought nothing.  Every car can be deleted now; its origin is one word in the
  detail pane and one of three *Show* filters.
- [x] **`publish.install(..., keep=True)`.**  Installing a pack asks whether to
  copy the files it is about to overwrite.  *Keep a copy* (the default) puts them
  in the same per-step folder the undo panel reads, so *Undo these* walks the
  install back; *Install, no copy* writes straight over and leaves an empty step
  rather than a step that cannot restore anything.
- [x] **The question is asked before the work, not after.**  The answer decides
  what the install has to do, so it is asked while there is still nothing to
  undo.

Tests: 1190 -> **1200** (group 82).

## Done on 2026-11-25

### A car you can rename, refile and repaint from the build dialog

- [x] **`edit.set_identity(root, name, display_name=, make=, model=)`.**  A
  shipped car's name is a *key* (`CAR_NAME_718_RSK`) into `gametext.txt` and the
  twelve `text_<lang>.txt` files, so a rename rewrites the text entry in every
  language and leaves the key alone; a car this program built holds the string in
  its spec, and that is what changes instead.  The make is the make string plus
  `CAR_MANUFACTURER_*` (502 of 540 specs carry one) - writing only the make left
  the car filed under its old brand, because the Brands list reads the key first.
  Nothing is written when nothing differs, which matters: a rename touches
  thirteen files and a geometry swap should touch none of them.
- [x] **The two name boxes the dialog already had now work on both branches.**
  *Display key* (what the game shows - a literal in the spec for a car built
  here, the text entry behind `CAR_NAME_*` for a shipped one) and *Model token*
  (the game's internal name) were disabled whenever the modify branch was picked,
  which is exactly where they were needed.  They are prefilled from the installed
  car and only what differs is written, so a geometry swap still touches nothing.
  No second pair of boxes: the same two answers, one home.
- [x] **The class and the drivetrain are dropdowns, not reference text.**  They
  were the two rows the table said "shown for reference; this one cannot be
  written" about - and a car whose drivetrain is wrong drives wrong.  The lists
  are the words the 541 shipped specs actually use: drivetrain `RWD 443 /
  AWD 82 / FWD 12 / RLY 3`, class `Race 301 / Supercar 155 / Prod 85`.  A spec
  holding something else keeps it and is marked *not one the game knows* rather
  than being silently replaced.
- [x] **`spec._splice` and `spec._refresh` move token offsets instead of
  re-tokenizing.**  `tokenize()` decides "is this a string?" by testing whether
  the next bytes print, and the word in front of a `CAR_*` key is usually
  `01 00 00 00` - so a 32-byte replacement string (`0x20` = space) re-read as "a
  one-byte string" and every field after it shifted away.  `_anchor_car_strings`
  repairs a file that was already written that way when it is next read.
- [x] **The paint table is the car's own schemes in the modify branch.**  It used
  to list the *donor's*, which is meaningless for a car that is already
  installed.  The first column reports what will happen to each row - `kept`,
  `new`, `delete` - and a queued deletion is greyed rather than removed, so
  pressing the button again puts the scheme back.
- [x] **Add a scheme / Delete scheme(s) on both branches.**  `LiveryFile` grew
  `next_paint_name()` (continues the shipped `NN_<car>.livery` numbering, which
  is what the frontend orders the colour list by) and `clone_paint()` - neither
  existed, so the Cars page's *Add a scheme...* had been raising `AttributeError`
  into a message box since it was written.
- [x] **A car needs at least one scheme.**  Deleting every row is refused with a
  warning before anything is queued; `edit.remove_paint_scheme` refuses it again
  on its own, because the dialog is not the only caller.  The atlases the removed
  schemes pointed at stay on disk - two schemes can share one picture.
- [x] **Colours are keyed by the index the build writes, not by the row.**  The
  new car keeps only the ticked schemes and they are renumbered from zero, so
  recolouring row 3 after unticking row 0 painted the wrong scheme.
- [x] **Multi-select in both paint tables.**  A batch is several presses on the
  same rows: the selection is restored after each redraw, with one `select()`
  call for the whole set - `selectRow()` clears what was already selected, so
  calling it per row kept only the last one.
- [x] **Every paint cell is selectable.**  `setFlags(Qt.ItemIsEnabled)` alone
  drops `ItemIsSelectable`, and a table whose rows cannot be selected cannot be
  multi-selected at all - the delete button answered "select a scheme first"
  forever.

Tests: 1200 -> **1301** (group 83: the two word fields, the three identities, the
paint queues and the clone round trip).

## Round G: the gear count, the maximum PR, and a folder that is optional

### The gear count is rebuilt, not written

- [x] **`spec.set_gears(count)`.**  The count cannot be written on its own the
  way the other engine figures can: it decides how many ratio floats follow it,
  so a different number in place makes the game walk the rest of the block at the
  wrong stride.  This rebuilds the ratio list instead - `count` floats right after
  the thirteen-word engine block, the last of which is the reverse ratio - then
  rewrites the count in front of it.  Measured on the 541 shipped specs: the list
  always ends on a number *larger* than the one before it (that is the reverse
  gear), and a one-gear car's single entry is its final drive, so only the
  forward ratios are rebuilt.
- [x] **A new gear is interpolated geometrically** between the two ratios it is
  squeezed into, because that is the shape a real gearbox has and it keeps the
  top gear where the designer put it.
- [x] **Removing a gear takes the one just below the top**, not the top itself:
  the car keeps the top speed it was given and simply has bigger steps, and
  "one more gear" followed by "one fewer" is an exact undo.
- [x] **`spec._verify_gears` re-reads the whole file afterwards.**  Four bytes per
  gear went in or came out, so every token after the list moved; if the name, the
  PR, the figures, the prices or the upgrade route no longer read back, the
  change is refused rather than written.
- [x] **`spec.gear_ratios()`** - the list as stored, for the dialog and the tests.
- [x] **`spec._retokenize(plain)`**, used by every writer that re-splits a file it
  just rewrote.  `tokenize()` guesses "is this a length?" from what follows, so a
  file carrying a 32-byte brand key re-splits wrongly and the name, the brand and
  the PR all vanish - the engine block write had the same latent bug.  The
  anchored split is also checked to detokenize back to the same bytes.
- [x] **A gear count below two is refused in words**: the one-gear cars are the
  Formula E racers, whose single ratio is their final drive, and there is no
  forward list to rebuild from.

### The maximum PR is an override, not a formula

- [x] **`spec.set_pr_max(value)`** writes the float one word after the base PR.
  The number *is* derived in the game's pipeline - 11 groups of shipped cars with
  byte-identical figures always carry identical `(pr, pr_max)` pairs - but the
  formula could not be recovered from the files: a quadratic fit over eight
  figures leaves a mean error of 5.6 PR points, and `pr_max / pr` is nearly
  constant for some routes (`2022_FORMULA_1` 0.17 % spread) and 20 %+ for others
  (`NASCAR_STOCK_2015` 17.9 %), so it is not a function of the route either.
  Exposing it as an explicit override with a tooltip saying so is the honest
  answer; the alternative was a formula that silently disagrees with the game.
- [x] **Both PRs are in the figures table**, with a note on the row.

### Changing an installed car no longer needs a folder

- [x] **`slots.problems(folder, mapping, required=False)`** - the modify branch
  checks only the slots that were actually filled, and tolerates an empty folder.
- [x] **The slot table says `(keeps <file>)`** for a slot a modify build leaves
  alone, so the page reads as "here is what it has, replace whichever you like"
  rather than as a table of missing files.
- [x] **`_modify_work()`** decides whether the dialog has anything to do at all:
  a mapping, an identity, a figure, a tail field, a paint queue, clips, a sound, a
  route, wheel sizes, the aero mode or the seated pose.  Nothing at all is
  refused with "nothing to do"; a settings-only change is accepted.
- [x] **`app.build_car` skips `install_slots` when no folder was chosen** and
  still writes the spec, the livery table and the text tables.

### The dialog froze for ten seconds when a car was picked

- [x] **`depot.spec_stems(root)`** - car name to spec stem, built from the spec
  directory and the appearance table alone, cached per install and rebuilt when
  either changes.  `anim.spec_path` used to fall back to `depot.scan`, which walks
  all 541 car folders to count their files (2.3 s); `stats.load` calls
  `spec_path`, and every panel of the Build dialog calls `stats.load` several
  times per car, so picking a car froze the window.  The index agrees with a full
  scan on all 541 cars and costs 0.9 s once, then nothing.

Tests: 1301 -> **1330** (group 61: the stem index, growing/shrinking the gear
list, the round trip, the refusals, the maximum PR, and the optional folder).
`work/_ui_smoke.py`: 52 -> **72** checks (the gears and PR rows are editable and
carry their notes, a fractional or impossible count is refused, and a dialog with
no folder is accepted while one that changes nothing is not).

## Round H: the two ends never agreeing, and a name that never arrived

Both complaints turned out to be one deploy path that had been lying, and the
proof is a before/after on the real device.

### "The two ends are always inconsistent"

- [x] **`deploy.MAX_CMD` and the retry.**  The emulator's `su` refuses a long
  argument: a 31-file `md5sum` batch (4.3 KB of quoted paths) came back **empty
  with exit code 255** while a 20-file one (2.7 KB) answered.  `remote_md5` read
  that silence as "the device has none of these files", so **every** file of a
  car was reported missing on every compare, however often it had just been
  pushed - which is exactly what "it always says the two ends differ" looked
  like.  A batch is now capped by the *length* of the command (1500 chars) as
  well as by the path count, and a batch of several paths that answers nothing
  is retried one path at a time instead of being believed.
- [x] Measured on the tourbillon before the fix: `rows 33, diff 33` (all
  "missing"); after: `rows 48, diff 12` - and those twelve were real.

### A rename never reached the game

- [x] **`deploy.compare_car` now looks where a rename actually writes.**  A
  rename touches nothing inside the car folder: the spec holds a `CAR_NAME_*`
  key and the name lives in `gametext.txt` + the twelve `text_<lang>.txt`, while
  the brand lives in the spec's make string and its `CAR_MANUFACTURER_*` key.  A
  build adds a row to `cardesc` and one to the appearance table.  None of those
  were compared, so the page listed a renamed car as identical, there was no row
  to tick, and the showroom kept the old name however many times the rename was
  repeated.  It compares them now (48 rows for one car).
- [x] Confirmed on the device: `CAR_NAME_TOURBILLON` was `'Bugatti Tourbillon'`
  there and `'Tourbillon'` here.  Pushed the twelve files, and the device now
  reads `'Tourbillon'` under `'Bugatti'`.
- [x] **`deploy.check_texts`** refuses to push a text table with fewer lines than
  the device has.  The tables are parallel arrays keyed by line number, so a
  shorter copy does not delete a name - it shifts every name below the gap onto
  the wrong key.
- [x] **The Display key tooltip says what the game shows.**  The brand is drawn
  on its own line above, so the name is normally the model alone (`LFA`, not
  `Lexus LFA`) - 526 of the 541 shipped cars are named that way, and the fifteen
  that are not are the NASCAR stock cars.  No automatic stripping: those fifteen
  prove the game allows both.

### The reconcile step was raising on every push

- [x] **`_device_lists` pulls a tar, not a folder.**  `adb pull` of a directory
  fails part way through when the destination path has non-ASCII characters
  (`cannot create 'E:/...数据包.../rrmod_lists/x.txt': Not a directory`) - and a
  Chinese install path is the normal case here.  So the device packs the lists
  with `tar` and the archive is read on this side.  Before this the whole
  reconcile raised, `deployui.push` swallowed it into `{"error": ...}`, and the
  registry was never re-made after a deploy.  Verified: 1237 lists, 47134 rows,
  0 corrections on a device that had just been pushed.

Tests: 1330 -> **1341** (group 62: the length-bounded batch, the per-path
retry, a batch that answers not being repeated, the text-table line guard, and
the rel list a per-car compare now builds).

## Round I: the textures a car and a scheme actually load

The ask was one thing said seven ways: *the pictures are the missing half of a
build.* A folder of exported art went in and nothing was ever written for it -
`misc.png` sat next to `LOD_A.m3g` and only the model was picked up. This round
gives textures the same treatment the models already had, on all four surfaces
that edit them.

### The naming rules, measured rather than guessed

- [x] **A car's own pages** are `<car>_<stem><suffix>`, the same shape as
  `LOD_A.m3g` -> `<car>_a.m3g`. Measured over the 541 shipped cars: `misc` 478,
  `wheel` 475, `wheel_blur` 474, `mask` 466, `lights` 464, `cab` 463,
  `ext_shadows_high` 463, `int` 463, `sha` 463, `int_shadows` 462, `sw` 461,
  `badges` 453.
- [x] **A scheme's pictures** live in `<car>/livery/` as
  `<car>_ext_<colour>` (plus `int_<colour>`), measured over 2209 files: `red`
  141, `white` 139, `blue` 139, `black` 130, `yellow` 82, `silver` 76, `grey`
  64, `orange` 54, `green` 46. The colour word is the one the scheme's `rgb`
  rounds to, so the name says what the picture is.
- [x] **A shared page** is `car_<label>_<NN>` for car parts (`car_tyre` 55,
  `car_windows` 41, `car_rotor` 10) and `<label>_mat<NN>` for interior
  materials (`leather_black`, `carbon_fibre`, ... `_mat00`..`_mat07`), measured
  over the 304 files in `vehicles/common`.
- [x] **`rrmod/texslots.py`** holds all of it - `car_pages`, `livery_pages`,
  `scheme_slots`, `guess`, `target_rel`, `colour_word`, `common_name` - and is
  Qt-free on purpose, so the writers and the tests can use it without a display.

### Build a car

- [x] **"1b. The textures in the folder".** A slot table (`Slot | File |
  Becomes`) under the model slots, filled by the same guess-then-rename logic
  the m3g table uses; `Set file...` overrides a guess, `Clear slot` leaves the
  slot alone. A second table lists the livery pictures the folder has and what
  each will be written as.
- [x] **Nothing is encoded until Build is pressed.** The panel says so in as
  many words, because the earlier build was reading pictures and converting
  them while the folder was being scanned - a build that was then cancelled
  left encoded pages behind.
- [x] **Adding a paint scheme is a table now.** Nine rows - the body (`ext`,
  marked `(needed)`) plus the eight optional pages - each showing its final
  file name. The colour button that the existing paint list already had is now
  here too, and the colour word follows the swatch into the name.
- [x] **The atlas cell became a `...` button** on both the Build dialog's paint
  table and the Cars page's. It opens every picture that scheme loads - the
  body and any page it overrides - with what each is set to now and what it
  will be written as.

### Cars page and Dependencies page

- [x] **A "Textures" tab** on a car: the eight slots, the file each loads now,
  the name it would be written as, and a Save that writes them (converting any
  picture at that moment, not when it was picked).
- [x] **The Dependencies texture half manages only `vehicles/common`.** It used
  to mix in every car's `<car>_misc`, which made a shared-page list that was
  mostly not shared. Adding one asks for a **label** (`tyre`, `windows`,
  `rotor`, ...), offers the name the rule would give it, and encodes the
  picture into the shared folder with its four asset-list rows.

### The one thing that had to be fixed before any of it worked

- [x] **A page is found by trying every family, not by joining the path.** The
  livery tables name `.ptc.pvr.z` while a DXT depot holds `.dxt.dds.z`, so the
  first version of `car_pages` reported all 541 cars as having no pages at all.
  It now looks for whichever family is actually on disk - and PVRTC is refused
  as a *target*, because its blocks interpolate across block edges.

Tests: 1341 -> **1406** (groups 84-86: the slot tables and the colour word, the
three writers, and the shared-page naming). `work/_ui_smoke.py`: 72 -> **104**
(the two tables, the `...` panel, the new-scheme dialog, the car's Textures tab,
and the label-driven add). i18n: 22 new Chinese strings, missing back to zero.

## Round J: the wheels the importer never brought in, and normals that would not bend

Two things the importer left behind, both found by using it rather than reading
it.

### The motion-blur stand-in of every wheel was missing

- [x] **A wheel ships two blur meshes, not one.** Measured on the Reventon, the
  LFA and the Countach: `LOD_x_WHEEL_BLUR_mm_wheel` (the silhouette, 684 verts)
  and `LOD_x_WHEEL_BLUR_mm_wheel_blur` (a flatter sheet over it, 361 verts), with
  a separate pair under `..._WHEEL_REAR_BLUR_...` on cars whose rear wheel
  differs. `parts.WheelSet` knew the first one's name and the importer ignored
  every one of them, so a spinning car had no blur at all.
- [x] **They go where the rim goes.** Both are modelled in the rim's frame
  (`x = 0` on the outer face), so each hangs off the same `WHEEL_<corner>` pivot,
  takes the same half turn on the right side, and takes the same radial scale.
  LOD F's blur is the whole car already assembled (x spans +-1.04), so that one
  goes to the origin under `WHEEL_LODF_ASSEMBLED` and is not rescaled - exactly
  the rule its wheel already followed.
- [x] **`<car>_LOD<X>_blur`, and visible.** `rr3_wheel_blur = True` marks them, and
  *Export all meshes* skips them - selecting one by hand still exports it.
- [x] **Revised the same day: the folder is no longer hidden.** The first cut hid
  it in the viewport *and* in the render, on the theory that it only doubles the
  wheel. The user then could not find the blur wheels at all and read it as "the
  import did not bring them in" - a folder the importer hides is a folder nobody
  looks in. They come in visible now; hiding one sub-collection is the user's
  call, and `blur_wheels` still turns the import off entirely.
- [x] `parts._blur_names()` returns the whole list (sorted, so the order is
  stable); `front_wheel_blur` / `rear_wheel_blur` stay as the first name for the
  report and the older tests.

### Normals: baked on the way in, frozen ever after

- [x] **The cause of "proportional editing makes sharp triangles".** Import used
  to bake the file's per-vertex normals as *custom split normals*. Those are
  frozen data: move a vertex and the normals keep pointing where they did, so
  the surface shades as facets that do not match its shape while the rest of the
  panel looks fine.
- [x] **Measured, not guessed.** Chiron body shell, 3921 manifold edges, six
  neighbouring vertices pulled 0.25 m: baked normals leave **4 edges with a
  normal discontinuity over 10 deg, worst 58.86 deg**; computed normals leave
  **0, worst 0.04 deg**.
- [x] **`file_normals` is off by default.** Import now sets `shade smooth` and
  lets Blender recompute. Hard edges survive because an RR3 hard edge is two
  vertices in the same place, not a flag. The look barely moves: over LOD A of
  the Reventon the file's normals sit a median **0.6 deg** from the geometric
  ones (p90 5.5 deg), and the authored outliers are real (brakes 7.6 deg median,
  steering wheel 4.5 deg) - turning `file_normals` on brings those back.
- [x] **`rr3.clear_custom_normals`** (*Car ▸ Make normals editable*) repairs a
  scene that was imported before this, without re-importing.

### Anchors: export what is selected, and nothing else

- [x] **The switch already existed and was invisible.** `export_scene.rr3_points`
  has had `only_selected` ("Selected empties only") all along - but it lives in
  the file browser's sidebar, and a scene holding two cars' anchors is exactly
  when nobody looks there. The N panel now has *Selected anchors (.points)*: the
  same operator with the switch pre-ticked.
- [x] **An empty selection is refused, not widened.** With `only_selected` on and
  nothing (or only meshes) selected the export stops with "nothing selected"
  instead of writing the whole scene - a silent fallback would overwrite the
  other set of anchors, which is the one thing this option is for.

Docs: `rr3_blender_addon/README.md` (two new parameter rows, two long notes, the
new operator, the selected-anchors button), `docs/插件使用手册.md` (task A gains
the three sub-collections and the normals note; task F gains the two-sets-of-
anchors paragraph; six rows in the troubleshooting table). Tests: smoke 20 -> 23
steps (the blur folder with its 8 meshes and their pivots; normals editable by
default and still bakable, plus the repair operator; the selected-only anchors
export and its refusal). Operators: 19 -> 20.

## Round K: the alpha the pages were already carrying, and a weld that keeps creases

### Texture alpha

- [x] **"Four channels" proves nothing.** Every depot page is a 32-bit DDS. Measured
  on the Chiron: `cab` / `int` / `lights` / `misc` / `sw` / `wheel` are flat 1.0;
  `badges` is 60 % clear, 26 % opaque, 14 % in between (a cut-out); `wheel_blur`
  has no clear pixels at all, 44 % in between, mean 0.839 (a soft mask). None of
  it was reaching the shader - the glass fallback was a hard-coded Alpha 0.35.
- [x] **`_image_alpha()`** reads the pixels through `foreach_get` into a preallocated
  `array`, cached by image name + size: ~30 ms per page, once per import.
- [x] **`_wire_alpha()`** links `Alpha` only when the page uses it, and picks the
  method from the data: fully clear pixels present -> **DITHERED** (a cut-out,
  where a real blend would sort two crossing badge quads wrongly); none -> 
  **BLENDED** (a ramp, where dithering shows as noise).
- [x] Wired in both material paths (name colours and game materials). The glass
  0.35 now only applies when its page has no usable alpha; the material is tagged
  `rr3_alpha_from_texture`.

### Welding without losing the creases

- [x] **The importer now keeps the file's normals as a `rr3_normal` attribute**
  (POINT, FLOAT_VECTOR, 12 B/vertex), whether or not they are baked as custom
  normals. Without it, nothing after a weld can tell a panel crease from a UV
  seam.
- [x] **`rr3.weld_and_mark_sharp`** (*Weld, keep hard edges*): record the normal
  each corner used per (face, position), `remove_doubles`, then mark an edge
  sharp when the faces that now share it used different normals at either end.
  Edges with 3-4 faces are compared pairwise - welding stacks decal and badge
  islands into the same edge, and the first cut skipped those, leaving every
  crease around an overlay smooth (82 deg off on the Chiron's badge corners).
- [x] **Measured** against the shading as imported, over all 19,554 face corners
  of `LOD_A_BODY_mm_ext`:

  | | mean | corners over 5 deg | worst |
  |---|---|---|---|
  | plain *Merge by Distance* | 17.51 deg | 51.1 % | 144.1 deg |
  | weld + hard edges | 0.36 deg | 1.1 % | 82.3 deg |

  1,790 edges marked, 5,965 vertices -> 3,655.
- [x] The 1.1 % left are decal and badge overlays: their authored normal disagrees
  with their own geometry (the decal takes the panel's shading). That can only
  exist while the vertices are split, so no weld keeps it - the exact-shading
  path stays "`file_normals` on, do not weld".

Tests: smoke 23 -> 25 steps (the alpha wiring with its two modes; the weld against
a plain merge, numbers above). Operators: 20 -> 21.
