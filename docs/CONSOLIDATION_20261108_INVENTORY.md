# Consolidation inventory, 8 November 2026

The canonical integration starts from the published RC3 source commit
`9e681b9433a2fd379be3ae000f386e0e36d6f318`. Its integration worktree is
`SpriteSuite_ReleaseIntegration_20261108`. Recovered histories were compared by
file content as well as Git ancestry; their branch names and commit counts alone
are insufficient proof that they include RC3.

## Coverage and evidence

The read-only Git census covers 21 source locations across 9 common-directory
families, including damaged linked worktrees. It records 14 distinct named
working branches, counted by common directory plus branch name; detached,
broken or unavailable branch pointers are not invented as named branches.
The complementary physical census
covers all 23 `E:\SpriteSuite*` directories, including four directories without
physical source files. Modding Studio is also covered at its separate physical
source location. The source comparison records 12,144 file observations against
the immutable RC3 baseline. Generated test output, virtual environments, game
installations, credentials and private configuration contents are excluded from
the public report.

The complete local audit artifacts are retained outside the distributed source:

| Artifact | SHA-256 | Purpose |
| --- | --- | --- |
| `inventory-rc3-source-comparison.json` | `c141ed98d040134deda6baf887dcf140f96054e5c4d8e319e68d6befe5ee5e6a` | Source paths, Git identity/status and normalized SHA-256 against RC3 |
| `physical-source-inventory.json` | `1ffd5663bc97399d200e086c941235014112ab9dab09c608f5e4496f3d2fc612` | Physical fallback for broken or unavailable Git metadata |
| `legacy-dirty-sandbox-comparison.json` | `7e944a50dfcf03e10f19d8a9941666ba33e9481ac4d871bc3fa22532a1006244` | Focused comparison of the 22 modified legacy Sandbox/UI/language sources |
| `modding-studio-import-source-manifest.json` | Recorded per source file | Physical import receipt for 31 Studio package, CLI, launcher, example, test and documentation files |

The JSON source hashes normalize CRLF to LF for comparisons. The physical census
also records raw file hashes. Artifacts remain under the local
`work/consolidation-20261108` audit directory. Their contents are historical
snapshots, not live status reports.

## Classification

| Source group | Result and disposition |
| --- | --- |
| Legacy `SpriteSuite`, HEAD `00276ec8d8fe5647f5341cb84f3cdcb398919042` | Its 22 dirty Sandbox/UI/language files were compared directly with RC3 and the canonical working source. Twenty-one are already identical after newline normalization. |
| Legacy `config/suite-sprachen.json` | The remaining file is superseded: the canonical version retains all 534 legacy translation keys and values and contains 718 keys. No missing legacy behavior was found in this focused comparison. |
| Convergence and EditorAI / Unified consolidation sources | Their unique asset inspector, image registration, environment discovery, AI and runtime capability work is available to the coordinated integration. Recovery branches are evidence sources rather than replacement histories. |
| FinalUnified recovery root `46250d2b764383e85cd14a70f73787e1065e71d1` | A recovered snapshot with separate ancestry. Compare source paths and hashes rather than treating this root as a successor to RC3. |
| Unified release / HPFire family `673eb09442a8c3504ce637d61b15b39224a15c13` | Runtime and HP/fire source candidates were examined against RC3 and the canonical integration. Historical generated DLLs and private game fixtures stay local. |
| GeometryAI | Twelve physically available source/test files were classified semantically. Their separate editors and incompatible registration/compositing are superseded by the shared editor; the comparison is linked below. Original directories remain retained. |
| Modding Studio `e501348a741e9d6662b9232fc1e98f06c036596d` | Git objects/ancestry are damaged. Its physical package, CLI, launcher, synthetic examples and tests were imported with a 31-file SHA receipt. The original source remains unchanged. |
| Local configuration | Three distinct local configuration filenames were found. Machine settings are retained locally and excluded from public source; no private contents were imported. |
| Broken linked worktrees and generated QA directories | Physical source coverage supplements Git failures. No branch, worktree or directory was removed. |

## Verification performed for this import

The five Modding Studio Python test files passed together: **52 passed**. This
includes version-diagnostic behavior, source validation/export, isolated helper
execution, GUI operation and preservation of the parent application's Tk theme.
The Suite entrypoint opens Studio in the current project's metadata workspace.
Further lifecycle integration is validated separately after this snapshot.

The Windows start package builder passed **11 tests**, including real Windows
batch launches with an empty `PATH`, a Unicode extraction path and an actual
fresh venv. The recovery case intentionally fails setup after creating venv
Python, then verifies that the next launch retries setup. A successful later
launch skips setup. Archive tests verify committed source provenance, exclusions,
ZIP CRC and SHA-256. The copied CPython runtime also imports `ctypes`, `ensurepip`,
`ssl`, `sqlite3`, `tkinter`/Tcl and `venv` before an archive can be accepted.

The public start package includes CPython standard library/support files and
its license. `FIRST-RUN.txt` explains that first launch installs SHA-256-locked
dependencies from PyPI into a local venv. Preinstalled third-party libraries,
Qt/FMOD runtimes, private game files and local virtual environments are excluded.
The separate local offline portable builder is preserved.

## Cleanup order

No historical source directory is approved for immediate deletion. After the
complete release acceptance gate is confirmed, recheck every original `HEAD`,
Git status and physical source SHA against the audit. Archive any changed,
untracked, ignored or otherwise unique local material to a new destination;
verify archive CRC, an archive SHA-256 and the source-file SHA manifest. Confirm
that the accepted canonical commit contains the intended functionality and that
the restoration instructions work before removing a redundant worktree through
its owning Git repository. Broken Git pointers require physical archive
verification before any manual cleanup. Worktrees with unique issues or
unclassified GeometryAI source remain retained until their disposition is
recorded. Never prune all worktrees or delete a shared Git common directory as
part of this process.

GeometryAI disposition is completed in [the semantic comparison](SPRITESUITE_GEOMETRY_AI_KANDIDATENABGLEICH_20261108.md): its separate editors, incompatible registration and RGBA alpha compositing are replaced by the shared editor pipeline. The original sources remain retained for the pending game acceptance.
