# Existing profile schemas

These readable XML source files belong to the existing extension profile. The
old installation flattened them into its runtime and omitted the XML from several
extension directories. Their absence prevented the source runtime from loading
AppIndicator, User Themes, NoAnnoyance, Tiling Assistant, DING and the appearance
extension, even though the compositor itself started.

They were copied as text from the preserved pre-port runtime; provenance and
SHA-256 hashes are in `manifest.json`. Copyright/license notices remain in the
files. No compiled `gschemas.compiled`, typelib, executable or binary resource is
reused. `prepare-candidate.py` verifies these inputs and compiles new schemas,
then lets XML shipped with the managed extension directories override them.
The main profile installer should retain these text inputs when removing the
old binary bundle.
