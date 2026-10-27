# DIPLOMACY / official Script Extender 2.11.0

## 2.3.6 baseline

The local package under `SE144/dist/StrongholdEuropeDiplomatieV2` was built
against the official `v2.11.0` release, commit
`48fd239dc56300d9e3acacaa26a8cd87de0c6464`. The release archive used
for the isolated toolchain has SHA-256
`a7b2c58ffb07df60e5c2510795179b060da2f3b89fd32dedd1a1c257e93374c5`;
its `SHCDESE.dll` has SHA-256
`3b944cab94e1a2d389e3cd81aa241131c9d708e7c4f227eeed41439432caee99`.
The package DLL has SHA-256
`a501e563b9d4f6b450190b86e90344184cac22e31ba4059f8da96bd6c8a08c76`.

The source delta from 2.10.4 adds a tribe-owner query and an experimental
custom-media path relocation. The owner query is not substituted for the
existing owner-plus-global-identity checks. The RedBird/Iced binaries needed
by DIPLOMACY's optional native adapter are byte-identical to 2.10.4. This
release does not add a documented pre-animation combat veto or an identity-safe
command to cancel already armed attack targets.

The focused offline suite passed 78/78. A metadata signature check compared
224 direct SHCDESE member references from the built DIPLOMACY DLL with the
official 2.11.0 DLL and found zero missing or mismatched signatures. The
package build completed without installation. No game process was started or
controlled, and this package has not been publicly uploaded.

## 2.3.7 resource tribute

A gold tribute invoice can now be settled by one transfer of equivalent goods
when the vassal lacks gold. The amount uses the map's frozen sell-value table,
rounds up, and rejects excessive overpayment. Among payable goods the mod
chooses the smallest share of the vassal's stockpile. Recipient capacity and
inventory-read failures defer the attempt without counting a default. The
original gold quote remains in the contract; the actual goods and quantity
are recorded in the existing atomic transfer journal. Save validation and
commit bookkeeping use the same settlement predicate, so a loaded pending
resource transfer cannot silently underpay or change its denomination.

The fealty terms and alliance view now disclose this alternative. All nine
supported translation tables were updated. The local 2.3.7 package DLL has
SHA-256 `cd4d534525d8456a39adcecac3016d0336e498429b62377caaee13c9c4a1a4b9`.
Offline checks passed: 57/57 text/tribute/save/plugin tests, 49/49 adjacent
inventory/compatibility/publication tests, and the executable tribute fixture
ran nine groups with 30 assertions. The build completed without installation
or game operation.

## 2.3.8 tribute display

The alliance obligation row places the existing goods-instead-of-gold notice
before the potentially long payment deadline. This keeps the alternative
visible when the row is shortened by the panel layout. Tribute amounts,
deadlines, settlement and save behavior are unchanged.

The local 2.3.8 package was built against official SE 2.11.0. Its DLL has
SHA-256 `70e94a1432b0bb28b8790fe3c9546264c965853580d1a50c132c03d28eca77ff`.
The focused offline suite passed 75/75. No game process was operated.

## 2.3.9 native callback lifetime

Failed removal of the optional native truce hook now preserves the callback,
its original function and the owning transaction independently of the mod's
teardown. Roots are established before any native removal step can fail.
Successful disposal releases only the transaction; the delegates survive for
late native callbacks. Retries retain one record per transaction identity.

An executable fixture reproduced the old missing-root failure with forced GC.
The fixed suite passes 5/5 native-adapter tests, covering removal failure,
unrestored entry bytes, disposal failure, retry, GC and late callback identity.
Another 49 plugin/publication/synthetic-detour tests pass. The non-installing
2.3.9 build against official SE 2.11.0 produced a 760,832-byte DLL, SHA-256
`b67a093b554589b8c1cdbfa888f465bd83d969d2741c3b12f894ed337945c76e`.
No game process was operated or package installed/published.

Parallel offline engine research pins the crossbowman's sprite writes before
its later shot checks and rejects using `0x18E900` as a general cancellation
command. The 22 pinned census checks pass. These findings add no new combat
hook to 2.3.9; the visible-truce implementation remains incomplete.

The public source export was independently rebuilt with the same DLL hash.
GitLab main/tag `v2.3.9` are published at commit
`677deed74dd81864dcd629525576719ce26a64ad`. ModDB's matching ZIP is ready
under `_Veroeffentlichung/ModDB/SHCDE-Diplomacy-2.3.9.zip`; upload awaits
an authenticated ModDB session. No game operation or installation occurred.
