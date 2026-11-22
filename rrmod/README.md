# RR3 Mod Manager

A manager for Real Racing 3 car mods.  It reads the game's own tables so it can
tell a car you made from one that shipped, keeps the three asset manifests honest
after every edit, and can push the result to a device over adb.

Start it with

    python -m rrmod

or, without a window, to check that the install is readable:

    python -m rrmod --check

The first run asks for the game folder - the one that contains `.depot` and
`apk`.  On this machine that is
`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files`.

## What is in here

| module | what it owns |
| --- | --- |
| `rrmod/depot.py` | reading the install: the car list, `rr3mods.json`, per car detail, which model folder a car borrows |
| `rrmod/slots.py` | the 17 slots the game has, and which file fills each one (a `car.json` is a hint, not a requirement) |
| `rrmod/modpack.py` | the `car.json` contract - the optional hint Blender can leave behind |
| `rrmod/edit.py` | every write: replace a file, add a file, set the aero flag, give a wing the body's paint, build a car, delete a car, backups, verify, and claiming the right one of the 1,236 asset lists for each file |
| `rrmod/workspace.py` | the working copy every edit lands in: seeding it from the install (car folders, `vehicles/data`, `common`, every `asset_list*`, `gui_assets`), deciding what counts as staged, and walking back one edit at a time |
| `rrmod/history.py` | the undo steps: one folder per edit, a `.json` note beside it saying what the edit was, a twenty-step limit that never drops a pinned step, and a folder of its own when the user picks one |
| `rrmod/project.py` | `.rr3proj`: a zip holding the changed files plus the answers the build dialog was filled in with, so a build can be put down and picked up again |
| `rrmod/deps.py` | who names a shared page: a live scan of all 540 livery tables, plus the record of which mod brought a page in. |
| `rrmod/decals.py` | the vinyl editor's shapes: the list, the font behind it, and which records will actually draw. |
| `rr3lib/blockencode.py` | the ETC1 and ATC block encoders, so a page can be written in the family the depot actually holds. |
| `rr3lib/ttf.py` | the decal font: reads the glyphs out of `r3_decals.ttf`, adds one, and writes the whole file back with every checksum recomputed. |
| `rrmod/backup.py` | the device's own bytes for exactly the files a push overwrites, one folder per push, kept as a stack. |
| `rrmod/pack.py` | the `.rr3mod` format: one zip, a manifest saying what kind of thing it is and what it needs, and the check that answers ready / missing / absent |
| `rrmod/publish.py` | gathering one thing into such a pack - a car, a driver pose, a manufacturer's logo, the career, shared pages, a circuit picture - and installing one back |
| `rrmod/profile.py` | which of the eleven pages the studio shows, and which the manager does |
| `rrmod/deploy.py` | adb: find the device, push, fix permissions, merge manifests, read the log |
| `rrmod/music.py` | the BGM playlists under `Tracks/data`, including the batch helpers |
| `rrmod/gfx.py` | `eds/AndroidHigh.plist` and `feats/AndroidHigh.feats`: five quality profiles, planned then written |
| `rrmod/bootlog.py` | what the engine says it actually ended up with, read back from its own start-up dump and diffed against the plist |
| `rrmod/anim.py` | a car's `_wing.banim` tracks, its `_animations.xml` clips, and which driver pose it is seated in |
| `rrmod/animcopy.py` | moving one car's animation onto another |
| `rrmod/series.py` | the career: `data/events.dat.nct` plus the fourteen text files, putting a new car in a series of its own, and adding or dropping a tier of an existing series without renumbering the rest |
| `rrmod/share.py` | zipping a car up for someone else, and taking one in |
| `rrmod/cars.py` | the reference spreadsheet: PR, class, top speed, price, seasons |
| `rrmod/stats.py` | the spec's own figures: weight, top speed, 0-60, braking, grip, class, the engine block, the engine sound, the upgrade route, and the two words and two prices the showroom reads |
| `rrmod/brands.py` | the manufacturers, their display names and their logo art |
| `rrmod/matmanager.py` | every row of `materials.bin`, joined with its slot and its users |
| `rrmod/materials.py` | which material the engine resolves for each mesh, and which ones can be written at all |
| `rrmod/paints.py` | `custom.paints.nct` (the finishes) and `custom.colours.nct` (the palette) |
| `rrmod/thumbs.py` | car pictures cut out of the game's own `car_sales` atlases |
| `rrmod/atlas.py` | the same, for any atlas folder: track cards, event art |
| `rrmod/tracks.py` | the 162 track names, their circuit, their time of day, their picture |
| `rrmod/maps.py` | pictures the user brings for a circuit, kept beside `rr3mods.json` |
| `rrmod/i18n.py` | the interface languages (`data/i18n/*.json`, English as the key) |
| `rrmod/ui/` | the window: Cars, Music, Graphics, Career, Brands, Materials, Dependencies, Publish, Deploy, About; a car's own tabs are Overview, Files, Paints, Parts, Animation |

`rr3lib/` underneath is the format library (m3g, banim, livery, spec, manifest,
appearance, link, nct ...) and is shared with the Blender add-on.

## Three facts the whole design rests on

**A car is identified by its appearance record, not by its file name.**  352 of
the 540 cars have a spec file name that differs from the appearance name
(`304_1959_porsche_718_rsk` is `1959_porsche_718`), and one points at a
completely different car.  Everything - the folder, the livery table, the asset
list - is keyed by the appearance name, so that is what the manager reads.

**The manifests are the engine's only trust anchor.**  `asset_list_base.txtCache.txt`,
`apk/res/asset_list_vehicle_data.txt` and `apk/res/asset_list_vehicle_<car>.txt`
each carry a size and an md5 per file.  A mismatch makes the engine re-download
the whole car instead of loading it, so every write goes through
`edit.sync_file()` and nothing else.

**A manifest row can describe a compressed file.**  In the shipped tables 15.8%
of the per-car rows have `packed != raw`; for those the md5 and the first size
are those of the *compressed* form, not of the bytes on disk (LFA body:
`packed=312052 raw=728986`, disk file is 728,986 B, registry md5 is not the file's).
The packer is unknown - zlib at every level, window and strategy misses the target
size - so a file we push is declared in the plain form (`packed == raw == size`,
md5 of the bytes on disk), which is the form the engine already accepts for the
`.banim` and `.xml` rows that earlier mods installed.  Never copy a `packed` value
from a donor row onto a file of a different size.

**One kind of car, one list.**  Every car in the install is in the same table and
can be modified, published whole or deleted.  The program used to keep a
`rr3mods.json` record of which cars were the game's own and refuse to delete
those, but the distinction earned nothing: a shipped car can be reinstalled from
the data package, deleting copies the files to `_rrmod_backup` first, and
"is this mine" was a question only the record could answer - so when the record
was wrong, the button was wrong.  What a car's origin still changes is a word in
its detail pane, and the *Show* filter can narrow the list to cars this program
installed, cars the game shipped, or cars it has not decided about yet.

**An install asks before it overwrites.**  A pack replaces the files it names,
so installing it offers two buttons: *Keep a copy, then install* (the default)
and *Install, no copy*.  The first copies each file it is about to overwrite into
the same per-step folder the undo panel already reads, so the install can be
walked back with *Undo these*; the second writes straight over and leaves no
bytes to walk back to.  It is the same mechanism as every other edit - only the
question is new, because an install is the one operation big enough that a user
might not want to pay for the copy.

## Working on a car

1. In Blender, export the files into a folder. **The file name is the slot**:
   `LOD_A.m3g`, `LOD_B.m3g` ... `LOD_H.m3g`, `SHARED.m3g`, `INT_A.m3g`,
   `INT_B.m3g`, `FRONTEND.m3g`, `wing.banim`, `wing.xml`, `car.points`,
   `int.points`, `car.dashplanes`.  One `.m3g` holds one LOD level, so the
   exporter names each file after the collection the meshes are in and refuses a
   selection that spans two levels - export `LOD_A` and `LOD_B` as two files, not
   one.  `car.json` is optional and only ever a hint - it can carry the identity
   fields the file names cannot (`year`, `make`, `model`, `display_key`), and
   deleting it costs nothing but those defaults.
2. *File - Build a car...*, pick that folder, and choose one of the two branches:
   **modify** an installed car in place, or **create a new car** from a donor.
   The dialog shows all 17 slots with the name each file will be written as, and
   any slot can be repointed at another file.
   * **modify** replaces the files of a car that is already installed, and can
     also change its wing behaviour and its `_animations.xml` - that is how a
     wing the studio left out gets added.
   * **create new** clones the donor's spec, appearance record, suspension/damage
     rows and paint schemes.  The dialog can override the figures
     (`rrmod/stats.py`), the class string, the make, which paint schemes survive
     (and each one's finish and atlas), the appearance id, the model token and
     whether the donor's file names are written alongside.  Section 6 can also
     put the car somewhere to race: a series of its own in a menu group, running
     the same events as a template, with only the new car on the grid.  The
     career file is only read when that box is ticked.
3. Every write lands in the working copy first, so nothing touches the install
   or the device until the *Deploy* tab is asked to push it.  The working copy
   mirrors the whole of `vehicles/data` (1142 files, 3.3 MB) and the whole of
   `vehicles/common` (298 files, 13.4 MB - the glass, carbon and rotor pages a
   livery names by bare name) rather than the few files an edit is expected to
   touch: a page that cannot read a car's spec, livery table or shared texture
   is a page that shows nothing, and picking which leaves to copy is the bug,
   not the fix.
4. *Deploy* tab: **Prepare** lists what would be pushed (everything staged, every
   row ticked), **Push** copies the ticked rows, **Check log** pulls the log and
   looks for the lines that say the game accepted it.

### Editing a career series

The *Career* tab reads `data/events.dat.nct` and the fourteen text files that go
with it. Three edits are made in place rather than by rebuilding the list, so the
tier ids survive - a save file or an unlock rule can point at one:

* **Add a tier** copies the series' *last* tier (its reward curve, banners and
  flags come along) and appends it at index `max + 1`. With no event list given it
  copies that tier's races too, because "one more of the same" is what it usually
  means.
* **Remove a tier** drops one tier and pulls the later indices down so they stay
  `0..n-1`. All 1602 shipped series already run `0..n-1`, so that renumbering is
  the only one that has to happen. A series must keep at least one tier: the game
  offers a series through its tiers, so one with none is a menu row that opens
  nothing.
* **Change event...** (or a double-click on the row) edits one event's track,
  type, laps, fame or reward. The dialog only hands back the fields that were
  actually moved.

Everything lands in the working copy and waits on the *Deploy* tab, same as any
other edit.

### Active aero: the four things that have to be true

A car only moves a wing when all four of these hold, and each one has its own
button:

| what | where | why it matters |
| --- | --- | --- |
| the moving geometry | Blender, exported into LOD A | no `WING` mesh, nothing to move |
| `<car>_wing.banim` | *Animation* tab | the curves; one track per moving part |
| `<car>_animations.xml` | *Animation* tab | without it the game has no `wing_up` to ask for |
| `DeployWhenBraking` in the spec | *Animation* tab checkbox | without it the game never asks |

The livery row (`745 LOD_A_WING_REAR_mm_ext -> 31 car_paint_gloss`) is the fifth,
but only cosmetic: without it the wing renders in its fallback material.

### Which track drives which part

The game pairs them **by name order** - the moving parts sorted by base mesh name
take tracks 0, 1, 2 in that order.  Nothing in the m3g, the banim or the xml
records the mapping; three separate searches for such a field came up empty.  So
the *Animation* tab shows the name order next to what each track actually does
(its pivot and its rotation span) and lets two tracks be swapped.  A track with
0 degrees of travel sitting on a part that should move is the usual giveaway.
Saving writes the renumbered banim and the xml together, and *Undo last edit*
puts both back.

### Copying an animation onto another car

`animcopy.copy_animation()` copies a banim and an xml from one car folder to
another under the target's name.  It refuses nothing, but it warns when the track
count does not match the target's moving part count - that mismatch is nearly
always a mistake.  A car with no `WING` mesh gets a warning too: the animation
would have nothing to move.

## Seating the driver

Which pose a car's driver holds is not in its spec - it is a field in the car's
data record (`vehicles/data/<id>_<car>.bin.nct`), the same file the game reads for
the car's own name and aliases.  The record is a stream of self-describing tokens,
so the field is found by walking: it is the **thirteenth token after the
`CAR_NAME_` string**.  Walking rather than using a byte offset matters - the
tokens between them are not the same shape in every record, and nine records have
a field that a naive tokenizer folds into a number.

Two things the picker says out loud, because both are invisible until the game is
running:

* An **empty** field is not a fault.  It means the car has no pose of its own and
  the game seats it with `driver.banim`, which is what 316 of the 540 cars do.
* Only **12** poses have a low-poly model of their own (`driver_lod_c_<x>.m3g`),
  while the records name **33**.  The other 24 play through the generic
  `driver_lod_c.m3g`, so the figure seen from outside holds a pose nothing
  modelled for it.  The game copes; it just looks approximate, and the pane says
  so before the file is written.

The 3.2 MB `driver/` folder is read from the install rather than mirrored into the
working copy: no car edit writes into it, so copying it would cost 64 files per
car for nothing.


A series is one championship in the career menu: a title, a description, a list
of tiers, and each tier holds the allowed cars and the races.  All of it lives in
`data/events.dat.nct` - 14 MB holding 1,602 series, 21,767 tiers and 50,374
events - and the titles are keys that point into `gametext.txt` and the twelve
`text_<lang>.txt` files, which are encrypted with a *second* RC4 key that has
nothing to do with the one the `.nct` tables use.

Making one follows the game's own recipe, which is what MonkeyTool's `rr3series`
does too: copy an existing series (the template), take the next free id, append it
to the end of the list (the limited-time records count series by index, so
inserting anywhere else would shift them), build the requested tiers by copying an
event of the same type out of the template tier, hang the series on a page of one
menu group, and write the title and description into all fourteen text files at
the same line index.

Two rules matter more than the rest:

* **The local depot never has the series you added on the device.**  It is a
  pristine copy of the game.  Editing its career and pushing the result deletes
  every series that was added on the device, so the *Career* tab starts from the
  device's own file - *Read from device* - and `deploy.check_career()` refuses any
  push whose file is missing a series or an event the device already has.  The
  career cannot be merged row by row the way the car tables can, so that refusal
  is the whole safety net.
* **A new series needs an id that is free *in the file being edited*.**  Ids are
  not dense: the device's `10000` is a series this project added earlier, and the
  next one is `10001` because it is `max + 1` over the device's copy, not over the
  depot's.

Tested end to end on the device: series `10001` "LFA Cup" (one tier, cars `[88]`,
three events - Bathurst 2 laps, Spa 1 lap, Laguna Seca 3 laps) in
`Career/STREAM_GROUP_AMATEUR`.  The device already had series `10000`
"LFA-AnimTest", which survived.  All fourteen files went up byte-identical, the
game booted with no `unable to load` line, and it did not rewrite the file back.

## Deploying

The manifest on disk is *not* authoritative and is never pushed as-is.  A real
device drifts away from any depot you keep: this one has a car that a previous
session installed (`2012_lexus_lfa_animtest`), four data tables whose hashes the
game itself rewrote, and sixteen `text_*.txt` rows that the depot does not even
have.  Pushing the disk registry over the device copy would delete all of it.

So `deploy.merge_manifests()` pulls the device's registry, vehicle data list and
per-car list, rewrites **only the rows for files this push carries**, appends any
row the device lacks, and pushes that.  Everything else on the device survives.
Measured on the real device: one file changed, 1 registry row and 1 per-car row
rewritten, 47,127 rows kept, and the game booted with `0 download errors` and 57
`all files up to date` - identical to the baseline before the push.

The merge output goes to the first writable of `<install>/_rrmod_backup/_merge`,
`%TEMP%/rrmod_merge/<tag>`, `./work/rrmod_merge/<tag>`.  The depot itself is
usually read only on purpose and is never written.

The staged list is **ticked row by row**, all rows ticked when the list is built.
Editing six cars and only trusting three of them is the ordinary case, so Push
sends what is ticked and All / None flip the whole column.  Closing the window
with something still staged asks first: the working copy survives the process, so
nothing is lost, but a user who forgot to push deserves to be told before the
window goes rather than on the next launch.

## Did the profile take effect?

A pushed profile is a wish list.  Only the engine can say what it ended up with,
and it does: right after `Loaded settings file: AndroidHigh.plist` it prints
every key it resolved, one per two lines.  **Check a boot log** on the Graphics
page reads that dump (`rrmod/bootlog.py`), diffs it against the plist on disk,
and lists the keys that did not arrive with the ones that did not take first.

This exists because `MIPMAP_BIAS` spent a week in the backlog as a suspected
writer bug: ultra writes `-2.0`, the log said `0`.  Reading the whole dump
settled it - the pushed file matched the engine on **111 of 113 keys**, and the
only two that differed were `MIPMAP_BIAS` and `3D_SCENE_SCALE`, the second of
which differs from the *shipped* value on every boot in the archive as well.
So the engine overrides a few keys after loading, and the writer was right all
along.  `MIPMAP_BIAS` goes to the shaders (`texture2DWithBias`, the `NOBIAS`
feature); a device that can only do shader-side LOD gets no GL-state bias and
reports 0.  `AndroidXtraHigh` ships `-2.0` on Android, so the value is legal -
it is the device that cannot honour it.

Two things the dump does that are easy to get wrong, both handled:
a multi-line string carries its `: STRING` on the **last** physical line only,
so `"Menu high\nA, 750\nE, 6"` reads back as `E, 6`; and a key the file does not
name is **absent** from the dump, not `0`, because the engine keeps its own
default for it.

## The history panel

Every edit copies the files it is about to change into a step folder before it
writes them, so a change can be walked back without touching the game folder or
the device.  The panel lists those steps and is a dock, not a dialog: drag it out
of the window and it stays floating beside it while the rest of the program is
used, the way an equaliser panel does; drag it back and it re-attaches.

* **A name, not a folder name.**  Each step writes a `.json` note beside its
  folder carrying the title the edit gave it ("Build 2012_lexus_lfa"), the time
  and the files it touched.  The note sits beside the folder rather than inside
  it because restoring a step copies back every file it finds - metadata in there
  would be "restored" onto the working copy as a stray file.
* **More than one step at a time.**  Tick two and press Undo and the files go
  back to the state before *either*; the restore walks the steps newest first, so
  the bytes that win are the oldest ticked step's.
* **A pin.**  Twenty steps are kept and the oldest is dropped first, except a
  pinned one.  A pinned step still counts towards the twenty - it is "the last to
  go", not "outside the count".
* **A folder of its own.**  *Where undo copies are kept...* moves the steps
  anywhere; the folder is tagged with the working copy's name so two installs do
  not mix.  Steps on another disk are real copies rather than fast renames, and
  the panel shows the free space so that is visible rather than surprising.

Ctrl+H shows or hides the panel; it starts hidden, so a user who never wants it
never sees it.

## Project files

The history answers "put that back" for the last few seconds of work.  It cannot
answer the other question - "keep this, I want to try a different wing from
here" - because it is bound to one working copy, it expires, and it holds only
bytes.  *File > Save a project...* writes a `.rr3proj`: a zip of the changed
files plus the answers the build dialog was filled in with.  *Open a project...*
puts them back into the working copy and stages them, so the Deploy tab offers
exactly what the project holds.  Neither ever writes to the game folder or the
device.

* **The answers, not just the bytes.**  A mod is more than files: the id a car was
  given, its appearance record, the paint slots, the aero behaviour and the two
  prices are scattered across eight `.nct` tables.  `result_info()` returns
  three dozen keys and none of them used to be written down, so a rebuild meant
  retyping them and hoping.  They go in `project.json` verbatim, minus the pack
  path and the slot mapping, which are paths and would not mean anything on
  another machine.
* **Level 1 on purpose.**  Measured on a real car (33 files, 7.37 MB): level 1
  gives 4.90 MB in 0.23 s, level 9 gives 4.84 MB in 0.33 s.  Most of the bytes are
  `.dds.z` and `.bin` that are already compressed and come out at 100%, so only
  the `.m3g` is actually being squeezed, at 46%.
* **A fingerprint of the install.**  `install_md5` is the md5 of the registry
  file, the one list that names every asset and that this program never writes to.
  Opening a project made against a different build says so rather than silently
  writing an id that the game has since taken.
* **It carries its way back.**  The undo steps go in too, under `history/`, and
  come back with a `(from a project)` title.  Opening the same project twice
  bumps the suffix rather than chaining it (`-p1`, `-p2`, never `-p1-p1`).

## Shared pages, and what depends on them

`vehicles/common` is the one folder a page can live in that many cars read: tyre
treads, window glass, brake rotors, chassis.  A livery table names a page by its
stem (`common/car_windows_04`), and the four GPU families are four files with
four different hashes behind that one name - so adding a page means booking four
rows in `asset_list_vehicle_common.txt`, each inside its own run of that list
(the list is 298 atc rows, then 298 dxt, then 298 etc, then 298 ptc, and a row
in the wrong run is a row the engine will not find).

* **Two questions, two sources.**  "Who names this now" is answered by scanning
  all 540 livery tables on demand - 0.3 s, and it cannot go stale because nothing
  is cached across edits.  "Who brought it here" is answered by `deps.json`,
  written when the page is added, because nothing on disk records that.
* **A shipped page is never a dependency.**  Whether the game shipped a page is
  asked of the *install*, found through the working copy's `pending.json`; asking
  the working copy would call a page added a minute ago the game's own.
* **Only orphans can be deleted.**  A page is offered for removal only when the
  game did not ship it and no livery table names it.  A page still in use is
  refused by name, and `force` exists for the case where the user knows better.
* **A mesh name needs a slot.**  The engine looks a whole mesh name up in
  `liveryStringTable.bin.nct`; no slot, no material.  Slots are positions, so the
  only safe change is appending - a hand made wing becomes slot 2068, 2069, and
  every existing slot keeps its number.

### The Dependencies page

The game has **two** shared folders, and they are not the same kind of thing:

| folder | who names a page | how many |
| --- | --- | --- |
| `vehicles/common` | the 540 livery tables, by stem | 298 pages |
| `Tracks/common` | nothing - the artist's own path, stored inside each track model | 2,313 files |

Both book four rows per stem (one per GPU family), both keep a shipped page
forever, and both only offer an orphan for deletion - but everything else differs,
so the page has one tab for each.  A track page is claimed by one of **nineteen**
asset lists (`asset_list_track_common_mat.txt` and friends), one per top folder,
and which folder a page lives in is what decides its list; a path with no folder
in it is refused rather than guessed at.

The car half shows one row per page name, sorted by how many cars read it, with
the ones this program added marked as its own.  Three lists:

* **every page** - name, how many cars name it, whether the game ships it, which
  mod brought it, and the files behind that name.  Filter by name, or tick "only
  the ones in use".
* **this program's own pages** - the ones nothing names any more, with a delete
  button that stays off until a row is picked.  Deleting one takes the file, its
  four rows in `asset_list_vehicle_common.txt` and its registry row.
* **pages a car names that are not here** - two of them in a stock install
  (`common/car_tyre_01`, `common/car_windows_banner_nascar_2021`).  The game
  copes, and a mod that supplies one is doing the game a favour rather than
  fixing a fault, so this list is a report and not a repair.

The track half works the same way against `Tracks/common`, reading its users out
of the 30 track models (as a regex over the bytes - parsing them as m3g takes
18 seconds and finding the same strings takes half a second) and its 1,290 pages
against the nineteen lists.

Reading takes about a third of a second for the car side and about 0.6 s for the
track side, both on a worker thread, because it opens all 540 livery tables or
all 30 track models.  The point of doing it live rather than caching is that a
page's users change the moment a car's texture row changes, and a stale count
would let the page be deleted while a car still names it.

## The decal list, and the font behind it

The vinyl editor's shapes are one table, `custom.decals.nct`, and one font,
`r3_decals.ttf`.  Both are readable and both round trip byte for byte, which is
what makes the Decals page a reader rather than a report:

* **A record draws either a glyph or a page.**  187 of the 229 records name a code
  point in the font; the other 42 name a `.pvr` picture under `vehicles/decals/`.
  Nothing in the file says which is which - it is decided by which field is
  filled in - so reading only one of the two fields loses most of the list.
* **A code point is written two ways.**  148 records spell it `0x0029` and 81
  spell it as the character itself.  Both are code points; a reader that accepts
  one spelling and not the other silently drops two thirds of the shapes.
* **The names are mostly absent on purpose.**  Only 30 of the 229 name keys exist
  in `gametext.txt`, and those are the two event categories where every record in
  the group shares one name.  The other 199 have no line at all and the game shows
  the shape itself, so the page falls back to something readable rather than a
  blank row - and it says which rows those are, because "no name" is normal while
  "no glyph" is a fault.
* **162 bytes of author trailer sit behind the last record.**  The count says where
  the list ends, so the trailer is carried through untouched - the same rule as
  `custom.paints.nct`.

A record can be renamed, moved to another category, repointed at another picture,
added and removed, all of which touch only `custom.decals.nct`.  Drawing a *new
shape* is the one job that needs both files, so it is written as one step: a
record naming a code point the font does not have draws nothing and says nothing
about why, and a glyph no record names is invisible.  `rr3lib/ttf.py` rebuilds
`r3_decals.ttf` rather than patching it - one new glyph moves `glyf`, `loca`,
`hmtx`, `hhea`, `maxp`, `cmap` and `head` - and it hands back an untouched font
byte for byte, because a rebuild that is merely *equivalent* is not something to
bet a game resource on.  Two things about it are worth remembering: the `cmap`
format 4 `idRangeOffset` means "in the array" or "use the delta" and nothing in
the format distinguishes them, so writing it wrong moves 23 code points to the
wrong glyph; and `hhea.numberOfHMetrics` has to follow the glyph count or every
new glyph's advance is read out of the previous one's side bearing.

## The four GPU families, and which of them can be written

Every page ships four times - `.dxt.dds.z`, `.etc.dds.z`, `.atc.dds.z`,
`.ptc.pvr.z` - and a depot unpacks only the one its device would load.  All four
decode; three can now encode:

| family | block | encoder | measured against the DXT copy |
|---|---|---|---|
| DXT1/DXT5 | 8/16 B | `rr3lib/ddsencode.py` | 0.84 mean |
| ETC1 | 8 B | `rr3lib/blockencode.py` | 1.89 mean |
| ATC RGB | 8 B | `rr3lib/blockencode.py` | 1.04 mean |
| PVRTC 4bpp | 8 B | *none* | - |

The numbers are the mean absolute difference per channel on
`gui_assets/960x640/splash/loading/sprites_0`, re-encoded from its own DXT copy
and decoded back - so they are the encoder's own error, not a comparison of two
different pictures.

**PVRTC is not a missing encoder, it is a different problem.**  Its blocks do not
carry two endpoints for their own 4x4 area: the endpoints are bilinearly
interpolated *across* blocks, so one block's bytes change its neighbours' pixels.
A block-at-a-time encoder produces a file that decodes to a picture and looks
wrong, which is worse than refusing, so `.ptc.pvr.z` is still read-only and
`build_texture` says why.

Two format details are worth remembering, both found by testing:

* **ETC's pixel order is transposed.**  The decoder walks a block as
  `x = i >> 2, y = i & 3`, not the usual `x = i & 3, y = i >> 2`.  Writing the
  other way round decodes to a picture, on its side.
* **ATC's pixel order is not.**  It reads `x = i & 3, y = i >> 2`.  The two
  formats disagree, and both still decode, so only a pixel comparison catches it.

ETC1 and ATC carry no alpha channel, and the game's pages of those families are
plain RGB, so an alpha page is refused rather than written with the channel
dropped - a decal that should be cut out would come out solid instead.

The page edits records too: a name key, a category, which half the record draws
from, and where in the list it sits.  Every one of those round trips byte for
byte, which is what the tests assert by renaming, adding, moving and removing a
record and comparing the whole file each time.

It does not **add a shape**.  Adding one means drawing a glyph into
`r3_decals.ttf`, and a record with no glyph behind it is exactly the fault the
page exists to report - so a new record has to reuse a code point the font
already carries, or point at a picture the game already ships.

One thing worth knowing when reading the code: the working copy holds the decal
table but not `gametext.txt`, which lives at the root of `.depot` and no car edit
ever writes it.  So reading a working copy has to be allowed to come up without
the text table, and the rows then show the shape's fallback name.  Failing
outright there is what the page did the first time it was pointed at a working
copy that already had a car in it.

## Taking a push back

A full copy of an install is 10.43 GB across 48,678 files and a car mod is a few
dozen files, usually under 30 MB.  So before a push overwrites anything, the
device's own bytes are copied for **exactly the files in the plan** - including
the asset lists that are about to be merged, because a car whose files were put
back but whose rows stayed in the lists would still appear in the menus, pointing
at nothing.

* **One folder per push, kept as a stack.**  Two mods that touch the same file
  have to come off in the reverse order they went on: the second one's copy of the
  file is what the first one's removal must put back.  Taking an older push off
  first is refused rather than half-done.
* **A file the device did not have is recorded as absent.**  An uninstall has to
  delete it, not leave it behind - that is the difference between a wing that
  vanishes from the menus and one that stays and crashes.
* **The record lives beside `rr3mods.json`.**  `_backup/<id>/` holds the bytes and
  a `_before.json` naming every file, its md5 and size; `_state.json` holds the
  stack.  Both are ours, not the game's, so nothing about them can make the engine
  ask for a download.

## Tests

    python tools\test_rrmod.py

Builds a miniature install (the LFA, the tables, the manifests, one car with a
four-track wing animation, the career file and its fourteen text files, all 42
graphics profiles) in `work/` and runs 1200 assertions over scan, bootstrap,
verify, replace, add, paint, backups, build, delete, the deploy plans, the music
round trip and the batch helpers, the graphics profiles, the animation tracks and
clips, copying an animation between cars, the two deploy guards, making,
describing, editing and removing a series, reading a career off a device, the car
and track pickers, turning a picture into a menu card, exporting and importing
a share, the four GPU texture families, the manufacturers and their logo art,
the track map pictures, the paint finishes the game's own customiser offers,
painting a car with one of them, the picture beside a car's name, the slot table
and the parts/pages panes, giving a car a page of its own, the build dialog's
aero clip table, modifying a car that is already installed (its files, its
wing behaviour, and its figures only when asked), the starting PR, the engine
figures, the engine sound, the upgrade route, the aspiration / layout / unlock
rule / prices at the tail of the spec, giving a new car a series to race in, the
working copy's copy of the shared data tree and the shared texture pages, pushing
the staged list one file at a time, and adding, dropping or editing one tier or
one event of a series without renumbering the rest, giving a wing the body's
paint only where the car has none, undoing an edit without
leaving the working copy unreadable, a file outside a car's folder being
claimed by the one asset list that owns it, the undo steps carrying a name, a
limit and a folder of their own, a project file that remembers the answers
as well as the bytes, a shared page booked four times in one list, a mesh name
appended to the slot table, a push remembered so it can be taken back in the
reverse order it went on, a slot pointed at a page the game already ships, the
dependencies page that tells an orphan from a page still in use, a pack that
carries its own list of what it needs and is refused when that list is wrong, the
two programs hiding each other's pages without losing them, a car given
another driver pose with the low-poly model it does or does not have, the
dependencies page keeping the two shared folders apart, a pack carrying the
picture a page was made from so the receiver encodes it for their own GPU, one
car list instead of one per origin, and an install that asks whether to keep a
copy of what it is about to overwrite.
It never writes to the real
depot (it reads it for the picker and texture checks, which is what makes them
worth having).

Every table in the interface can be resized by dragging its column edges, and the
long panes scroll.  The animation tab is the one that needed it most: a car with
four tracks and six clips does not fit in a fixed-height dialog.

## Pages, and where the tyres live

A car's meshes are split across several files, and the interesting ones are not
in the body:

| file | what is in it |
| --- | --- |
| `<car>_<lod>.m3g` | the body panels, glass, lights, interior |
| `<car>_shared.m3g` | **wheels, tyres, brake discs, calipers**, the bonnet camera, the glow meshes |
| `<car>_int_a.m3g` / `_int_b.m3g` | the interior seen up close, for the cars that have one |

So the Parts pane has a **Model** dropdown, and the shared file is the only way
to reach a tyre.  A mesh name ends in `_mm_<tag>`, and that tag picks the
*texture page* it samples: `_mm_tyre` reads `ext_tyre` (slot 4), `_mm_rotor`
reads `ext_rotor` (5), `_mm_wheel` reads `ext_wheel` (1938).  `ext_<tag>` wins
when the car names one, otherwise `int_<tag>`.

That gives two separate ways to change how a part looks, and they are not the
same thing:

* **the material** - `car_tires`, `car_tires_standard`, `car_rotor`,
  `car_rotor_low`, the seven `car_wheels_*`, `car_paint_carbon_fibre`.  That is
  the whole list; a caliper has no material of its own and uses `car_flat`.
* **the page** - any of the 33 `ext_*`/`int_*` slots, each of which can point at
  a picture of your own.  Every mesh that samples the page changes with it.

`rrmod.materials` reads both; `edit.set_part_material` writes the first and
`edit.set_texture_slot` the second.

### Taking a page out and putting it back

The Textures tab does both directions now:

* **Save this page as a PNG...** decodes whichever copy of the page is on disk
  and writes it out at full size.
* **Put a picture in this page...** encodes a picture back into the page.  It has
  to be the same size - the game allocates by size, so a different one is refused
  rather than rescaled.
* **Use another shipped page...** points the slot at a page that is already in
  `vehicles/common` - another tyre tread, another disc, another interior weave.
  Nothing is copied and nothing is encoded: only the livery row changes, so this
  costs no space and only the livery table is pushed.  The list is filtered to
  pages of the same kind (a tyre slot offers tyres, an interior slot offers the
  same `_matNN` weave), because all 298 pages at once is a menu nobody can use.

Only the DXT family could be written at first.  Since then ETC1 and ATC were
added (`rr3lib.blockencode`), so three of the four can be written and only PVRTC
cannot: its blocks interpolate their colour endpoints across block boundaries, so
a block-at-a-time encoder produces something that decodes, displays, and is
wrong.  Which family a page *is* depends on which copy the depot unpacked, not on
what the livery names.  A shipped livery often names a `.ptc.pvr.z` page while
the depot holds the `.dxt.dds.z` copy of the same picture; the game picks the
family when it loads, so writing the DXT copy is the right thing and the livery
needs no edit.  `rrmod.textures.page_path` therefore tries all four suffixes
before giving up, and `describe` reports the family it actually found.  When
writing, `replace` keeps the family of the file it found rather than forcing DXT
- a Mali install only has the ETC copy, and handing it DXT would decode to noise.

The encoders are `rr3lib.ddsencode` (DXT1 for three-channel pictures, DXT5 when
there is alpha) and `rr3lib.blockencode` (ETC1 and ATC).  The DXT one is a
bounding-box endpoint encoder with nearest-colour index selection, which
round-trips a shipped 1024x1024 page at a mean difference of **0.84 of a level**;
ETC1 lands at **1.89** and ATC at **1.04** on the same page.  All three are far
below the 2.2 gamma curve the PVRTC pages need, and invisible in the game.

### A page keeps the picture it was made from

A page on disk is a finished GPU file in one family.  Publishing that file would
pin a pack to the author's hardware, so `textures.replace` also copies the source
picture to `<working copy>/_rrmod_source/<page name>.png`.  A pack then carries
the **picture** (`pictures/` in the zip) instead of the page, and the person
installing it chooses the family - `auto` (the default, meaning "whichever family
this install already holds for that page") or DXT, ETC or ATC by name.  The
choice is remembered in the settings file.  A page nobody edited has no picture,
so it travels as the file it is and the pack says which pages those were.

## The Materials page, and what it may write

`materials.bin` is 296 material instances and 186 shader bindings, and the game
does not read a mesh's material out of the model: it looks the mesh slot up in
the car's livery table and uses *that* name, falling back to the shipped default
only when nothing is named.  So the useful question about a material is not
"what does it look like" but "who points at it", and that is what the Materials
tab answers - it joins three tables:

| table | what it contributes |
| --- | --- |
| `materials/materials.bin` | the row itself: application, blend, colour, feature flags, and the shader behind it |
| `vehicles/data/liveries/liveryStringTable.bin.nct` | whether the name has a **slot**, i.e. whether any car can point at it |
| `vehicles/data/liveries/<car>.liveries.bin.nct` | how many cars actually do |

The numbers on a full install: **296 rows, 101 with a slot, 99 of those in use**.
The other 195 exist and the game may use them internally, but no livery row can
name them, which is exactly why the Parts and Paints dropdowns only offer the
101 - offering a name with no slot would be offering something that does nothing.

Two things are worth knowing before reading the table:

* **The flags are the look.** `car_paint_matte` carries `SPEC_MASK_TEXTURE` and
  `car_paint_metallic_spec_red` carries `SPEC_FLAKES`; `car_paint_pearl_blue`
  and the candy colours carry `COLOURED_FRESNEL`.  Those are separate rows, not
  parameters of one row, which is why "changing the suffix" means picking a
  different material rather than editing this one.
* **26 of the 72 paint rows have no slot.**  All the candy colours and gold, plus
  their `car_bumper_paint_*` twins, are offered by the game's own customiser but
  cannot be written by a livery row.  The page shows them greyed out rather than
  hiding them, so it is clear why they are missing from the pickers.

Two things the page does write, and one it never will:

* **Copy this one...** appends a *whole block* to the end of the material table
  with a new name, so no existing offset moves.  The copy keeps the application,
  cull, blend, stencil and flags of its source - a new name that is not an
  instance of that template would look its shader up and find nothing - and it
  gets a livery slot in the same step, because a material with no slot is one no
  car can wear.  292 bytes on a full install, and `asset_list_startup.txt` (the
  one list that claims `materials.bin`) plus the registry are re-hashed with it.
* **Delete this copy** splices that one block out, and only ever a block this
  program added: the game's own 296 come from the install, which never changes,
  so they can be told apart however many copies are in the table.  A copy a car
  still names is refused unless forced, because that car would draw without it.
* **A field inside a block is not edited here.**  The records are
  `u32 key + u32 length + payload` with no back-pointer, so one wrong byte shifts
  every record after it and the game loads a table that looks plausible and is
  wrong.  Changing how a part looks is done by pointing a car at a *different*
  row, which is what the Parts and Paints tabs do.

## Paint finishes and colours

The game's customiser offers a fixed menu of paint finishes, and that menu is a
table, not code: `vehicles/data/custom.paints.nct` holds 31 rows, each naming a
material (`car_paint_gloss`, `car_paint_matte`, `car_paint_metallic_white` ...),
a starting colour, and the swatch overlay that goes with it.  The 42 colours in
`custom.colours.nct` are the game's own palette.

Two things matter when writing it back:

* **the file ends with a 102 byte trailer** (`Author:@depot` and a URL).  A naive
  parse and rewrite drops it, so `paints.parse_paints_with_tail` hands it back
  and `paints.save` puts it where it was.
* **`car_paint_gloss` is one material behind eight rows**, each with a different
  starting colour, so the dropdown is built from the material list rather than
  from the rows - otherwise it would offer "Gloss" eight times.

`rrmod.paints` reads it; `edit.set_paint_finish` writes a car's livery to use one
of them.  The body slot is 30 and the wing slot is 745, and both are written so
the wing never ends up a different colour from the body.

## The numbers a car has, and which ones can be changed

Everything on the car's own screen - weight, top speed, 0-60, braking, grip, the
PR, the engine, the drivetrain, the engine sound - lives in the car's spec file,
not in a table. `rrmod.stats` reads all of it and writes the parts whose position
is certain:

| group | how it is found | writable |
| --- | --- | --- |
| weight / top speed / 0-60 / braking / grip | fixed token index, identical in all 540 files | yes |
| class, drivetrain | fixed token index | class yes, drivetrain no |
| starting PR | the first number after `CAR_NAME_*`, checked against the two after it | yes |
| fully upgraded PR | the number after that | **no** - the game derives it |
| engine (gears, final drive, power, torque, redline, limiter, shift points) | scanned for the aspiration/layout pair, then read **by byte offset** | all but `gears` |
| engine sound | fixed token index, 435 of 540 cars | yes, as a family name |
| upgrade route | after the gear ratios, `gears + 4 * (13 + gears)` bytes past the gear count | yes, as a tree name |

Two of these are worth spelling out, because both look like they should be simple
and are not:

* **the engine block is addressed by byte offset, not by token index.** The gear
  ratios are floats, and a float's bytes can look like a string length prefix, so
  the tokenizer splits the block into fake strings - the token *offsets* survive
  that, the token *count* does not. MonkeyTool's token-walking version of this
  finds the block on only 75 of the 540 cars and reads the wrong field on those.
* **`gears` cannot be written.** It decides how many ratios follow it, so a
  different count makes everything after it read at the wrong stride. Changing
  the number of gears means rebuilding the block, which is a separate job.

The engine sound is three strings (`audio/Vehicles/<family>/id_<n>_accel`,
`..._decel`, `<family>_idle`). Pointing a car at another family rewrites all
three and keeps the car's own id in the file names, so a car that ships its own
take keeps it. The 105 cars with no audio fields at all (old F1 cars, the
NASCARs, some concepts) report nothing and refuse to be written rather than
having an offset invented for them.

The last one on that screen is not a number but a **name**: the upgrade route.
A car's tuning tree does not live in its spec, only the name of the tree does,
and the tree itself is one of 327 blocks in `carupgrade.upgrades.nct`. Pointing
a car at another tree is therefore a single string edit - the table is never
touched, which is why "give this car the PROD_02 tree" is a safe operation and
"edit PROD_02" is not. Ten of the 327 are the game's own templates (`PROD_01` ..
`RACE_03`); the rest are trees a shipped car or a racing class already uses
(`2022_FORMULA_1`, `LEXUS_LFA_2012`, ...). The key sits at
`gears + 4 * (13 + gears)` bytes past the gear count, i.e. after the gear ratios,
so it is read by offset for the same reason the engine block is.

## The four GPU texture families

Every texture in the game ships as four encodes of the same picture, one per GPU
family, and the per-car manifest carries a row for each:

| suffix | format | who uses it |
| --- | --- | --- |
| `.dxt.dds.z` | DXT1/3/5 (S3TC) | Adreno, desktop |
| `.etc.dds.z` | ETC1 / ETC2 (+EAC alpha) | Mali, most Android |
| `.atc.dds.z` | ATC (`ATC `, `ATCA`, `ATCI`) | Adreno's ATC path |
| `.ptc.pvr.z` | PVRTC 2bpp / 4bpp | PowerVR |

All four decode through one entry point - `rr3lib.texport.decode_frame` - because
`rr3lib/ddsdecode.py` and `rr3lib/pvr.py` hand block formats to
`rr3lib/etcdecode.py`.  Two things are worth knowing before touching that file:

* **PVRTC pages are gamma encoded.** Decoded PVRTC differs from the DXT copy of
  the same art by a mean of 54/255 raw, but by 2.5 after the 2.2 curve
  (`etcdecode.to_display`).  A fitted exponent puts the minimum exactly at 2.2.
  The decoders keep the bytes as the file has them; only comparisons and
  compositing go through the curve.
* **ETC blocks are walked transposed** (`x = i >> 2, y = i & 3`), matching
  MonkeyTool's reference decoder.  Reading them the conventional way raises the
  error against DXT from 2.37 to 6.71.

A depot is usually unpacked for one family only; the other three rows exist in
the manifests but have no file on disk.  That is normal - a missing `.etc` variant
is not a broken install, and `rrmod/edit.py` keeps treating it as such.

## Sharing a car

*Cars -> Share this car...* writes a zip holding the car's folder, its spec and
its livery table, plus a `mod.json` that says which car id and appearance id the
files were made against.  The three manifests are deliberately left out: the
receiver's copies have rows the sender never saw.

*Cars -> Import a share...* checks the zip against this install before touching
anything, and refuses rather than guesses when:

* the base car is not installed here (a share only replaces files of a car that
  already exists - it never invents one);
* the car id or appearance id moved, which would land a spec on the wrong car;
* the pack says `kind: "new"` (that is a `car.json` from the Blender add-on, not
  a share);
* a path in the zip climbs out of the install.

A share is not a backup.  It carries files, not history, so importing one
replaces what is there; the usual `_rrmod_backup/<stamp>` copy is made first and
*File -> Undo last edit* covers it.

## Packs, and the two programs

A share is one kind of pack.  The Publish page writes the general one,
`.rr3mod`, which is the same zip with a manifest that says more:

```json
{"format": 2, "kind": "car", "name": "2012_lexus_lfa",
 "requires": [{"kind": "driver", "name": "driver_laferrari.banim"}],
 "provides": {"cars": ["2012_lexus_lfa"], "pages": ["vehicles/common/..."]},
 "files": ["vehicles/2012_lexus_lfa/2012_lexus_lfa_a.m3g", "..."],
 "pictures": ["vehicles/common/car_windows_04.dxt.dds.z"]}
```

Seven kinds are written: `car`, `pages`, `driver`, `brand`, `material`, `career`, `track`.

* **The list of what it needs is the point.**  A car whose driver pose is not on
  the machine it is installed on is a car with no driver in it, and nothing about
  the files says so.  So the pack names its dependencies, and
  `pack.check()` answers one of three states: *ready* (installed and satisfied),
  *missing* (installed, but something it needs is not here) or *absent* (nothing
  of it is installed yet).  A format 1 share from before packs existed is read as
  a car pack and its `base` becomes a requirement, so old files keep working.
* **A page the game ships is a requirement, not a file.**  298 shared pages are
  on every install already; copying them into a pack would add megabytes that
  the receiver already has.  Only a page that is *not* the game's own travels.
* **A page travels as the picture it was made from, not as the page.**  The
  `pictures` list names entries under `pictures/` in the zip; installing one
  encodes it into the GPU family the installer picks (`auto`, `dxt`, `etc` or
  `atc`), which is the only way one pack can be right on a Mali device and an
  Adreno one.  A page nobody edited has no picture, so it travels as the file it
  already is and the pack reports which pages those were.
* **A missing page does not stop an install.**  It is reported as a warning:
  the car still works, one surface just draws without a texture.  Every other
  kind of missing requirement still refuses, because a pose with no driver in it
  is not a cosmetic problem.
* **Installing is a separate click from opening.**  Reading a pack is free and
  should stay free; installing it rewrites files, so it gets its own button and
  its own undo step.
* **The career is merged, not replaced.**  Its fourteen files are shared by every
  series in the game, so replacing them would delete the series the receiver
  added.  The note on a career pack says so.

`profile.py` splits the same build into two programs:

| | shows | does not show |
| --- | --- | --- |
| Mod studio | Cars, Career, Brands, Materials, Dependencies, Decals, Publish, About | Music, Graphics, Deploy |
| Mod manager | Cars, Music, Graphics, Materials, Dependencies, Deploy, About | Career, Brands, Decals, Publish |
| both (default) | all eleven | - |

The line is drawn by *who owns the truth*: the studio makes mods and needs no
device, the manager installs them and does not edit the career.  The pages are
hidden with `QTabWidget.setTabVisible`, never destroyed, so switching profile
never loses what a page was in the middle of.  `--studio`, `--manager` and
`--all` on the command line pick one at start-up and are remembered.

## Known gaps

* Wing track binding is *not* guessed.  The game pairs parts to tracks in name
  order; when that is wrong for a car the *Animation* tab is the fix, by hand.
  A `car.json` `aero` table carries the mapping for new cars.
* `_animations.xml` frame numbers cannot be derived from a banim's duration (only
  14 of 53 cars line up), so the file is authored rather than generated on
  export.  *Build a car* now has its own clip table for the new car, and the
  *Animation* tab does the same for a car that already exists.
* The compressed form of a manifest row.  When `packed != raw` the md5 refers to
  the packed file and we cannot reproduce it, so a replaced file is declared in
  the plain form.  The engine accepted that in the test above, but it means the
  row no longer says what the shipping tools would have said.
* The *Graphics* tab has been pushed to a device once: the ultra profile went up
  as two files plus one registry row, the game booted with 0 download errors and
  logged `Loaded settings file: AndroidHigh.plist`, and every value the log dumps
  (AA_LEVEL 4, CUBE_MAP_DIMENSIONS 1024, LENS_FLARE_SCALE 16, PROP_MIN_COVERAGE
  0.005, FONT_PAGE_SIZE 2048, AUDIO_MIX_RATE 48000) is the ultra one.  The two
  keys that do not come back as written are `MIPMAP_BIAS` (the engine reports 0
  because the bias reaches the shaders, not GL state - see *Did the profile take
  effect?* above) and `3D_SCENE_SCALE`, which the engine recomputes from the
  screen shape on every boot, shipped profiles included.
  The *Animation* tab's track swap has been pushed too (a banim, verified byte for
  byte on the device); what has not been checked is a swap that visibly changes
  which part moves on screen.
* Only 12 of the 33 driver poses the records name have a low-poly model of their
  own.  A car given one of the other 21 loads and drives fine, but the figure
  seen from outside is the generic `driver_lod_c.m3g` holding a pose nothing
  modelled for it.  Making a new pair means exporting a `driver_lod_c_<x>.m3g`
  and a `driver_<x>.banim` from Blender, which the add-on can do; the manager
  only chooses among the ones the game ships.
* A series can have one tier added, one tier dropped, or one event changed in
  place, and none of those renumber the rest: `series.add_tier()`,
  `series.remove_tier()` and `series.set_event()` keep every other tier id and
  index where it is, which is what the game's own files always do.  The builder
  still makes a whole list when a series is created from a template.
* Random music per race is a placeholder button that says so.  Choosing songs in
  bulk already works (the batch dialog's *shuffle* action); making the *game*
  pick at random means patching `libRealRacing3.so`, which is a different kind of
  job from rewriting `.nct` files.
* The tail of the spec is on the same screen as the figures: two closed
  dropdowns for the aspiration and the layout, a box for the unlock rule and two
  spin boxes for the cash and gold prices.  The two words are closed lists
  because the engine block is *found* by them - an aspiration the game does not
  know would hide the power figures and the upgrade route from every reader.
* *Build a car* now surfaces the figures (`rrmod/stats.py`), the class string,
  the paint schemes and the appearance/model identity, its two name combos open
  the picker, and section 6 puts the car in a career series.  The PR is writable
  too (`Spec.set_pr`), but `pr_max` is not: the game works the maximum out from
  the base PR and the upgrade route, so writing it would only be overwritten.
* `QComboBox` item text is not translated.  Several pages read
  `currentText()` back as the value, so translating the items would change
  behaviour; the labels beside them are translated instead.
* Importing a share over a car whose files were *added* by the sender (a wing
  banim, an animations xml) leaves those rows in place.  Removing a file is not
  something a share can express - delete the mod and reinstall to get back to
  stock.
* Track maps are a placeholder.  The game stores a card per circuit (126 of the
  162 track names) but no *layout* map: the minimap drawn while driving is
  generated from the track mesh, so there is nothing to read and nothing known
  about where a picture would have to be filed for the game to draw one.
  `rrmod/maps.py` therefore keeps the pictures the user brings in a plain folder
  next to `rr3mods.json` - one PNG per circuit, shared by every time of day - and
  the track picker uses it in place of the missing card.  It never goes into the
  install and is never pushed.

## The four GPU texture families, again

Every texture in a manifest has four rows (`.dxt.dds.z`, `.etc.dds.z`,
`.atc.dds.z`, `.ptc.pvr.z`) and only one of them has a file on disk, because a
depot is unpacked for one GPU family. That is not a missing file: `rrmod/edit.py`
skips the other three when verifying, and `rr3lib/etcdecode.py` can read any of
them, so a page that was unpacked for Mali still previews.

## Paint schemes are per scheme, not per car

A shipped car can have one gloss and one matte factory colour at the same time,
so a finish is a property of a *scheme*: `edit.set_paint_finish(per_paint=...)`
takes `{scheme index: material}`, and the *Paints* tab edits one row at a time.
The colour on a scheme is only the one the game's customiser starts from - the
shipped atlas still draws the car - which is why changing it needs the atlas
picker beside it to be worth anything.
