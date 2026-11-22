"""Pure-Python readers and writers for Real Racing 3 asset files.

Readers (never touch the file they open)
---------------------------------------
``m3g``          JSR-184 ``.m3g`` container / object table
``geometry``     Mesh -> VertexBuffer -> VertexArray resolved into plain arrays
``points``       ``.points`` anchor / hinge / spline / transform table
``banim``        ``.banim`` animation clips (tracks, curves, key frames)
``rig``          bone/skeleton rigging of a ``.banim`` (roles, matrices, frames)
``parts``        wheel mounts, aero parts and the per-car assembly plan
``wheelsize``    how the game scales the shared wheel template, per car
``texture``      ``.dxt.dds.z`` atlases and the tag -> atlas table
``ddsdecode``    DXT1/DXT3/DXT5 -> RGBA pixels (pure Python or numpy)
``etcdecode``    ETC1/ETC2, ATC and PVRTC -> RGBA pixels (the other GPU families)
``texport``      unpack every private texture container to PNG or DDS, and back
``pvr``          the 1024x1 ``.pvr`` ramps in ``vehicles/shaders``
``gamematerial`` ``materials.bin``: the 297 material states and 186 shader bindings
``carmaterial``  per-car, per-paint material + texture resolution
``driver``       the driver's models, animations and skins in ``<depot>/driver``
``dashplanes``   interior dash plane placement
``livery``       ``.liveries.bin.nct`` paint schemes and the slot string table
``appearance``   ``carappearances.appearances.nct`` records
``spec``         the per-car ``.bin.nct`` spec and the shared fixed tables
``upgrades``     ``carupgrade.upgrades.nct``: the 327 tuning trees and their steps
``catalog``      the material / part / paint catalogue (read from the tables)
``catalog_data`` the static half of the catalogue (slot names, tag docs)
``manifest``     ``asset_list_*`` manifests and the registry
``animxml``      ``_animations.xml`` clip lists
``nct``          the RC4 wrapper every ``.nct`` file is stored in

Writers (produce new files, never edit in place)
-----------------------------------------------
``m3gwrite``     build a ``.m3g`` from scratch or rebuild one byte exactly
``points_write`` build a ``.points`` file
``banim_write``  build a ``.banim`` file
``ddsencode``    RGBA pixels -> a DXT1/DXT5 page (the only family this writes)
``animxml``      ``build`` / ``save`` for ``_animations.xml``
``livery``       ``save`` / ``save_default``
``spec``         ``save_spec`` / ``save_cardesc``
``appearance``   ``save``
``car``          one-shot: clone a donor car into a brand new car id
"""

__all__ = [
    "animxml",
    "appearance",
    "banim",
    "banim_write",
    "car",
    "catalog",
    "catalog_data",
    "carmaterial",
    "dashplanes",
    "ddsdecode",
    "ddsencode",
    "driver",
    "etcdecode",
    "gamematerial",
    "geometry",
    "livery",
    "m3g",
    "m3gwrite",
    "manifest",
    "nct",
    "parts",
    "points",
    "points_write",
    "pvr",
    "rig",
    "spec",
    "texport",
    "texture",
    "upgrades",
    "wheelsize",
]
