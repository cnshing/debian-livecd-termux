# Historical GNOME bootstrap

The normal installer now uses the source-built recipes in `packages/livecd-*`
and connects their APT-owned runtime with `src/native/runtime.py`.

This directory preserves the earlier binary bootstrap and its input lockfile.
Its `prepare.py` entry point is not part of the normal installation path. The
small `fetch` helper is still imported by profile-specific asset hooks; importing
the module does not run the bootstrap.

The independently tested native source port now lives on as the recipes in `packages/`.
The packaged replacement needs its own complete builds and device acceptance;
historical bootstrap/device evidence is not a claim that it has passed those.
