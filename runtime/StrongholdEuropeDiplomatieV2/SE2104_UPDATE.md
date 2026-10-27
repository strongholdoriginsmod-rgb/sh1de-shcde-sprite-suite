# Diplomacy 2.3.5 / official SE 2.10.4 — local update

The local package under `dist/StrongholdEuropeDiplomatieV2` builds against the
official SE 2.10.4 release (tag `dc86a6b91f5f2b491fc815e926542db1f921538d`,
SHCDESE.dll SHA-256 `20543f2eb7cba4a25298493ec51efc3a5a12af55252bef23566e047f6c0827a4`).
The 2.10.4 companions match the previously pinned 2.9.0 companion hashes.
The 445-member compatibility contract and package verifier pass. The package
was installed into the isolated game COPY on 2026-09-26 together with official
SE 2.10.4 and the independently built STRATEGY update. A menu startup loaded
all three mods with zero SE compatibility issues; Diplomacy reported 451/451
resolved bindings and 18/18 attested prerequisites. The final startup log is
`work/verification/se2104-diplomacy235-strategy-final-startup.log`. Tribute
and truce behavior still require an in-mission game test.
The verified mod DLL is SHA-256
`b6c29e5035cd81cd0d07206cb18cf8d82814b24cb696dbe0c4a171abc9de3aed`.
The C# model suite passes, and the affected Python harnesses pass (96 targeted
tests; the broader Diplomacy run had 325 passing and one outdated ledger
expectation, which passed on its focused rerun after correction).

Tribute now retains one overdue invoice at its agreed amount after grace.
The daily retry does not record further defaults or terminate an alliance.
Payment restores vassal command eligibility and begins a full new interval;
repricing only applies after that payment. Save schema 13 preserves its binary
field layout and imports schema-12 missed payments by moving the due date back
one interval. Existing in-flight legacy break transactions remain decodable.
The two directions, technical transfer journal and inventory locking stay on
their existing paths. The management panel displays the arrears explicitly.

This is **deferred payment of one invoice**, not unlimited compounding debt or
automatic in-kind conversion. A resource substitute requires an authenticated
valuation and a multi-good transfer journal; the present tribute journal only
authorizes the contracted good and amount. Arbitrary substitution would lose
save/load recovery guarantees. A practical next step is a bounded in-kind
settlement proposal with an explicit rate, payer/recipient confirmation and
recovery tests.

Truce still protects tribe attack orders, projectile creation and damage, but
autonomous units may enter attack animations before those hooks run. In 2.10.4,
`OnUnitAIStateChange` only intercepts selected state writes and exposes no
target identity or guarantee of complete attack coverage. `AITargetSelectionResult`
is a three-field interop struct, not a vetoable target-selection event. Mapping
truce to a native alliance would alter AI/diplomatic behavior. A safe fix needs
an SE-supported pre-target/pre-attack admission hook with attacker and target
life identities, owner/team context, and a veto that leaves AI state and
animation bookkeeping coherent. Until verified in game, visual peace is an
open item and release acceptance explicitly checks it.

New upstream APIs since 2.9.0 include `GetSelectedChimps()` and type-level
projectile/unit range controls. The former is relevant to manual-order
attribution, but a multi-selection discrepancy is still under investigation;
the latter does not solve treaty target admission. The private SE 2.10.0 C#
commander observation candidates in `engine-research/extensions` are build-only
and are not part of the official 2.10.4 release or this Diplomacy runtime.

SE 2.10.4 also names several previously opaque native fields (including the
unit's manned state and moat-work index), which helps observational adapters.
The upstream `GamePathingManagerAPI.GetUnitTypePathfindingConnectionClassPermissions`
still advances rows by `PATHFINDING_UNIT_TYPE_COUNT` (89) in source, whereas
the pinned engine uses a 90-integer native row stride. STRATEGY continues to
use only class one, whose row offset is zero. No new official semantic route
or pre-attack admission contract appeared in the 2.10.1–2.10.4 changes.

The 2026-09-26 private C# hook investigation is recorded in
`../../../engine-research/reports/DIPLOMACY_TRUCE_ATTACK_ADMISSION_20260926.md`.
The exact pinned engine has 89 type-dispatch entries but no qualified common
pre-animation veto or life-identity-safe cancellation contract yet. The
visual-truce release gate remains closed; no experimental hook was installed.
