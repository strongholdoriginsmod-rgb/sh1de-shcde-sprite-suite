"""SE-2.x native runtime: adaptive reference capture + fail-closed ABI tests.

All fixtures are synthetic and located inside pytest tmp_path.
Tests never touch Steam or installed Script Extenders.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from stronghold_europe_de import runtime_build as runtime
from stronghold_europe_de import runtime_prerequisites as prereq
from stronghold_europe_de import runtime_reference_capture as capture


@pytest.fixture
def reference_set(tmp_path, monkeypatch):
    template = json.loads(
        (ROOT / "config" / "runtime-prerequisites.json").read_text("utf8")
    )
    base = tmp_path / "game"
    references = {}
    for i, row in enumerate(template["files"], 1):
        dest = base.joinpath(*row["relative_path"].split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((f"synthetic SE runtime reference {i} ".encode()
                         * 550)[:13000].ljust(13000, b"!"))
        references[dest.resolve()] = (row["assembly_name"],
                                      row["assembly_version"], row["mvid"])
    unsafe_relative, unsafe_name = prereq._ADAPTIVE_EXTRA_DEPENDENCIES["unsafe"]
    unsafe_file = base.joinpath(*unsafe_relative.split("/"))
    unsafe_file.parent.mkdir(parents=True, exist_ok=True)
    unsafe_file.write_bytes(b"synthetic unsafe interop assembly reference".ljust(
        13000, b"!"))
    references[unsafe_file.resolve()] = (
        unsafe_name, "6.0.0.0", "ac6e2d3e-c55b-405a-9cbb-2a0d9853626d"
    )
    se_path = base / prereq._REQUIRED_DEPENDENCIES["shcdese"][0]
    def fake_metadata(path):
        actual = references[Path(path).resolve()]
        if Path(path).resolve() == se_path.resolve():
            return (actual[0], "2.14.3.0", actual[2])
        return actual
    monkeypatch.setattr(prereq, "_read_managed_assembly_metadata", fake_metadata)
    monkeypatch.setattr(capture, "_read_managed_assembly_metadata", fake_metadata)
    monkeypatch.setattr(capture, "attest_native_layout", lambda _p: "modern")
    monkeypatch.setattr(prereq, "_nachsicht", lambda: True)
    return template, base, se_path, references


def test_adaptive_reference_capture_pins_every_real_input_without_installing(reference_set):
    template, root, _se, _references = reference_set
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    doc, abi = capture.capture_runtime_references(template, root)
    assert abi == "modern"
    assert doc["schema_version"] == 3
    assert doc["script_extender_version"] == "2.14.3"
    assert len(doc["files"]) == len(prereq._REQUIRED_DEPENDENCIES) + 1
    assert doc["config_id"].startswith("measured-se-abi-")
    verified = prereq.verify_runtime_prerequisites(doc, root)
    assert verified.script_extender_version == "2.14.3"
    assert len(verified.files) == len(prereq._REQUIRED_DEPENDENCIES) + 1
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_never_accepts_hash_drift_even_in_lenient_mode(reference_set):
    template, root, se, _references = reference_set
    doc, _abi = capture.capture_runtime_references(template, root)
    before = se.read_bytes()
    se.write_bytes(before[::-1])  # Same length, different contents.
    with pytest.raises(prereq.RuntimePrerequisiteError, match="SHA-256"):
        prereq.verify_runtime_prerequisites(doc, root)


def test_never_accepts_missing_reference_before_abi(reference_set, monkeypatch):
    template, root, se, _references = reference_set
    se.unlink()
    monkeypatch.setattr(capture, "attest_native_layout", lambda _p:
                        pytest.fail("Layout probe should not run"))
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="fehlt"):
        capture.capture_runtime_references(template, root)


def test_never_accepts_symlinked_reference(reference_set, tmp_path):
    template, root, se, _references = reference_set
    copied = tmp_path / "symlink-se.dll"
    copied.write_bytes(se.read_bytes())
    se.unlink()
    try:
        se.symlink_to(copied)
    except (NotImplementedError, OSError):
        pytest.skip("Test account does not allow symlinks")
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="Verknüpft"):
        capture.capture_runtime_references(template, root)


def test_legacy_version_is_not_rejected_if_required_apis_are_present(reference_set, monkeypatch):
    # Synthetic evidence: version 1.x is *not* denied by its number. This
    # does not claim that the actual 1.44 release contains RedBird APIs.
    template, root, se, _references = reference_set
    original = capture._read_managed_assembly_metadata

    def metadata(path):
        name, version, mvid = original(path)
        if Path(path).resolve() == se.resolve():
            return name, "1.44.0.0", mvid
        return name, version, mvid

    monkeypatch.setattr(capture, "_read_managed_assembly_metadata", metadata)
    monkeypatch.setattr(prereq, "_read_managed_assembly_metadata", metadata)
    contract, layout = capture.capture_runtime_references(template, root)
    assert contract["script_extender_version"] == "1.44.0"
    assert layout == "modern"
    assert len(prereq.verify_runtime_prerequisites(contract, root).files) == 16


def test_unknown_layout_is_not_approved(reference_set, monkeypatch):
    template, root, se, _references = reference_set
    monkeypatch.setattr(
        capture, "attest_native_layout",
        lambda _p: (_ for _ in ()).throw(
            capture.RuntimeReferenceCaptureError("not a reviewed layout")
        ),
    )
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="reviewed"):
        capture.capture_runtime_references(template, root)


def test_rejects_unreviewed_template_path_or_identity(reference_set):
    template, root, se, _references = reference_set
    modified = json.loads(json.dumps(template))
    modified["files"][0]["relative_path"] = "BepInEx/plugins/other/SHCDESE.dll"
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="Pfadliste"):
        capture.capture_runtime_references(modified, root)


def test_rejects_schema3_missing_shcdese_version_binding(reference_set):
    template, root, se, _references = reference_set
    doc, _ = capture.capture_runtime_references(template, root)
    doc["script_extender_version"] = "2.11.0"
    with pytest.raises(prereq.RuntimePrerequisiteError, match="does not match"):
        prereq.verify_runtime_prerequisites(doc, root)


def test_rejects_schema3_fake_assembly_name(reference_set):
    template, root, se, _references = reference_set
    doc, _ = capture.capture_runtime_references(template, root)
    doc["files"][0]["assembly_name"] = "Lookalike"
    with pytest.raises(prereq.RuntimePrerequisiteError, match="identity"):
        prereq.verify_runtime_prerequisites(doc, root)


def test_v2_legacy_identity_pins_still_enforced(reference_set):
    template, root, se, _references = reference_set
    prereq._validated_config(template)
    changed = json.loads(json.dumps(template))
    changed["files"][0]["assembly_version"] = "2.14.3.0"
    with pytest.raises(prereq.RuntimePrerequisiteError, match="Pinned identity"):
        prereq._validated_config(changed)


def test_build_gate_uses_actual_selected_game_instead_of_legacy_sha(reference_set, monkeypatch):
    template, root, se, _references = reference_set
    monkeypatch.setattr(runtime, "ROOT" if hasattr(runtime, "ROOT") else "PROJECT_ROOT", ROOT, raising=False)
    # Avoid using the real project file in this test; work through its
    # public object-shaped configuration in the captured target game.
    profile = tmp_project = root / "suite"
    config_dir = profile / "config"
    config_dir.mkdir(parents=True)
    (config_dir/"runtime-prerequisites.json").write_text(
        json.dumps(template), encoding="utf8"
    )
    config = SimpleNamespace(
        project_root=profile,
        target=SimpleNamespace(game_dir=root, reference_root=None),
    )
    verified = runtime._verify_prerequisites(config)
    assert verified.script_extender_version == "2.14.3"
    assert len(verified.files) == 16


def test_known_layouts_are_version_independent_not_magic_number(monkeypatch, tmp_path):
    # Native probe result is semantically a family, never 'allow 2.14.3'.
    fake = SimpleNamespace(
        returncode=0, stdout="legacy", stderr="",
    )
    monkeypatch.setattr(capture.shutil, "which", lambda _name: "powershell.exe")
    monkeypatch.setattr(capture.subprocess, "run", lambda *_a, **_kw: fake)
    assert capture.attest_native_layout(tmp_path/"old.dll") == "legacy"
    fake.stdout = "modern"
    assert capture.attest_native_layout(tmp_path/"new.dll") == "modern"
    fake.stdout = "unknown"
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="Unbekannte"):
        capture.attest_native_layout(tmp_path/"newer.dll")


@pytest.mark.parametrize("se_version", [
    "1.44.0",
    "2.10.4",
    "2.14.3",
    "3.1.9",
])
def test_no_se_major_minor_or_patch_version_gate(reference_set, monkeypatch, se_version):
    """Any version is eligible when its real identities and layout satisfy API contracts."""
    template, root, se, _references = reference_set
    original = capture._read_managed_assembly_metadata

    def current_reference(path):
        name, version, mvid = original(path)
        return (name, se_version + ".0", mvid) if Path(path).resolve() == se.resolve() else (name, version, mvid)

    monkeypatch.setattr(capture, "_read_managed_assembly_metadata", current_reference)
    monkeypatch.setattr(prereq, "_read_managed_assembly_metadata", current_reference)
    doc, abi = capture.capture_runtime_references(template, root)
    assert doc["script_extender_version"] == se_version
    assert abi == "modern"
    verified = prereq.verify_runtime_prerequisites(doc, root)
    assert verified.script_extender_version == se_version
    assert len(verified.files) == 16


def test_csharp_runtime_plugin_has_no_minimum_se_version():
    plugin = (
        ROOT / "runtime/StrongholdEuropeDE.Runtime/StrongholdEuropeRuntimePlugin.cs"
    ).read_text(encoding="utf8")
    assert '[BepInDependency("000shcdese")]' in plugin
    assert '[BepInDependency("000shcdese", "2.0.0")]' not in plugin
    assert "per-feature API/layout probes" in plugin


def test_no_major_version_gate_does_not_disable_native_layout_safety(reference_set, monkeypatch):
    template, root, se, _refs = reference_set
    old = capture._read_managed_assembly_metadata

    def legacy_version(path):
        name, version, mvid = old(path)
        if Path(path).resolve() == se.resolve():
            return name, "1.44.0.0", mvid
        return name, version, mvid

    monkeypatch.setattr(capture, "_read_managed_assembly_metadata", legacy_version)
    monkeypatch.setattr(
        capture, "attest_native_layout",
        lambda _path: (_ for _ in ()).throw(
            capture.RuntimeReferenceCaptureError("Native layout not verified")
        ),
    )
    with pytest.raises(capture.RuntimeReferenceCaptureError, match="not verified"):
        capture.capture_runtime_references(template, root)
