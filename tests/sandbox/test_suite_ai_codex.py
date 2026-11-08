"""Local ChatGPT/Codex Sprite request checks; no web access and no game writes."""
from __future__ import annotations
import hashlib
import io
import json
import sys
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import suite_ai_codex as ai  # noqa: E402


def sample_bundle(tmp_path: Path, *, variants=2, overrides=None):
    from PIL import Image
    original = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    original.paste((130, 160, 200, 255), (4, 4, 60, 32))
    source = io.BytesIO()
    original.save(source, format="PNG")
    plan = {"width": 1536, "height": 1024, "scale": 28, "left": -1,
            "top": 64, "sourceWidth": 64, "sourceHeight": 32}
    # 28*64 doesn't fit a 1536 canvas; use computed lossless factor 22.
    plan["scale"] = 22
    plan["left"] = (1536 - 64 * 22) // 2
    plan["top"] = 1024 - 64 - 32 * 22
    canvas = Image.new("RGBA", (1536, 1024), (0, 0, 0, 0))
    canvas.paste(original.resize((64 * 22, 32 * 22), Image.Resampling.NEAREST),
                 (plan["left"], plan["top"]))
    registered = io.BytesIO()
    canvas.save(registered, format="PNG")
    sourcebytes = source.getvalue()
    registeredbytes = registered.getvalue()
    req = {
        "format": ai.FORMAT, "version": 1, "assetClass": "building",
        "goal": "Make a visibly damaged version while keeping the original baseline.",
        "model": "gpt-image-2.6-flare", "variants": variants,
        "quality": "high", "complexity": "high", "background": "transparent",
        "output_format": "png", "requiresManualApproval": True,
        "automaticInstallation": False, "size": "1536x1024",
        "registration": plan, "referenceWidth": 64, "referenceHeight": 32,
        "referenceSHA256": hashlib.sha256(sourcebytes).hexdigest(),
        "modelReferenceSHA256": hashlib.sha256(registeredbytes).hexdigest(),
        "referenceFiles": ["model_reference.png"],
        "prompt": "Edit source image. Retain the existing ground position and alpha. "
                  "Only change the art inside the original registered rectangle."
    }
    req.update(overrides or {})
    bundle = tmp_path / "request.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("reference.png", sourcebytes)
        z.writestr("model_reference.png", registeredbytes)
        z.writestr("request.json", json.dumps(req))
        z.writestr("WORKFLOW.txt", "Dry run before execution.")
    return bundle


def test_offline_validation_and_source_hashes(tmp_path):
    bundle = sample_bundle(tmp_path)
    req, files = ai.load_request(bundle)
    assert req["variants"] == 2
    assert files[0][0] == "model_reference.png"
    assert ai.main(["--bundle", str(bundle), "--output",
                    str(tmp_path / "candidate"), "--dry-run"]) == 0
    assert not (tmp_path / "candidate").exists()


def test_default_validation_does_not_start_codex(tmp_path, monkeypatch):
    bundle = sample_bundle(tmp_path)
    monkeypatch.setattr(ai, "_generate_one", lambda *_args:
                        pytest.fail("Offline validation must not start Codex"))
    args = ["--bundle", str(bundle), "--output", str(tmp_path / "output")]
    assert ai.main(args) == 0
    assert not (tmp_path / "output").exists()


def test_invalid_source_and_model_do_not_generate(tmp_path):
    for overrides in (
        {"model": "unknown"},
        {"variants": 17},
        {"referenceSHA256": "a" * 64},
        {"size": "64x32"},
        {"registration": {"width": 1024}},
        {"referenceFiles": ["reference.png"]},
        {"input_fidelity": "high"},
    ):
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        folder.mkdir()
        bundle = sample_bundle(folder, overrides=overrides)
        with pytest.raises(ValueError):
            ai.load_request(bundle)


def test_cannot_write_directly_to_game_folder(tmp_path):
    target = tmp_path / "Stronghold Crusader Definitive Edition" / "BepInEx"
    with pytest.raises(ValueError, match="Spielverzeichnisses"):
        ai._safe_output(target)


def test_inverse_registration_reuses_existing_strict_geometry(tmp_path):
    bundle = sample_bundle(tmp_path)
    req, images = ai.load_request(bundle)
    normalized, metadata = ai.normalize_model_output(images[0][1], req)
    assert normalized is not None
    assert ai.png_dimensions(normalized) == (64, 32)
    assert metadata["registered"]
    assert metadata["sampling"] == "nearest"


def test_mock_generator_records_bound_candidate_receipts_and_completed_run(tmp_path, monkeypatch):
    bundle = sample_bundle(tmp_path, variants=1)
    request, images = ai.load_request(bundle)
    assert request["_request_sha256"] == hashlib.sha256(
        zipfile.ZipFile(bundle).read("request.json")).hexdigest()
    monkeypatch.setattr(ai, "_generate_one",
                        lambda *_args: (images[0][1], "synthetic-offline-test"))
    result = ai.execute(request, images, tmp_path / "candidate_run")
    status = json.loads((tmp_path / "candidate_run" / "run-status.json").read_text())
    meta = json.loads((tmp_path / "candidate_run" / "variant_01_meta.json").read_text())
    assert result["generated"] == 1
    assert status["status"] == "candidates_ready_for_review"
    assert status["completedVariants"] == 1
    assert meta["requestSHA256"] == request["_request_sha256"]
    assert meta["candidateSHA256"] == hashlib.sha256(
        (tmp_path / "candidate_run" / "variant_01.png").read_bytes()).hexdigest()
    assert meta["needsManualReview"] is False
    assert not meta["inGameTested"]
    assert not result["installed"]


@pytest.mark.parametrize("goal,prompt,approval", [("x", "x", False), ("", "", None), ("a", "edit", True)])
def test_short_or_empty_briefs_have_no_approval_or_minimum_text_gate(tmp_path, monkeypatch, goal, prompt, approval):
    bundle = sample_bundle(tmp_path, overrides={"goal": goal, "prompt": prompt, "requiresManualApproval": approval})
    request, images = ai.load_request(bundle)
    assert request["goal"] == goal
    assert isinstance(request["prompt"], str) and request["prompt"]
    monkeypatch.setattr(ai, "_generate_one", lambda *_args: pytest.fail("Offline validation must not generate"))
    assert ai.main(["--bundle", str(bundle), "--output", str(tmp_path / "unused")]) == 0


def test_interrupted_multi_variant_generation_is_marked_partial(tmp_path, monkeypatch):
    bundle = sample_bundle(tmp_path, variants=2)
    request, images = ai.load_request(bundle)
    calls = {"n": 0}

    def fake_image(*_args):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("offline simulated second request failure")
        return images[0][1], "offline-first"

    monkeypatch.setattr(ai, "_generate_one", fake_image)
    folder = tmp_path / "interrupted"
    with pytest.raises(ValueError, match="simulated"):
        ai.execute(request, images, folder)
    status = json.loads((folder / "run-status.json").read_text())
    assert status["status"] == "partial_failure"
    assert status["expectedVariants"] == 2
    assert status["completedVariants"] == 1
    assert (folder / "variant_01_meta.json").is_file()
    assert not (folder / "variant_02.png").exists()


def test_real_unity_game_root_detected_even_when_directory_renamed(tmp_path):
    synthetic_game = tmp_path / "RenamedQA"
    synthetic_game.mkdir()
    (synthetic_game / "UnityPlayer.dll").write_bytes(b"sentinel")
    (synthetic_game / "Stronghold Crusader Definitive Edition.exe").write_bytes(b"sentinel")
    with pytest.raises(ValueError, match="Spielinstallation"):
        ai._safe_output(synthetic_game / "work" / "ai_candidate")


def test_local_codex_session_receives_registered_reference(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import Mock
    bundle = sample_bundle(tmp_path, variants=1)
    request, images = ai.load_request(bundle)
    client = Mock()
    client.generate.return_value = (images[0][1], "offline-generation-id")
    @contextmanager
    def fake_session(cwd):
        yield client
    monkeypatch.setattr(ai, "session", fake_session)
    result = ai.execute(request, images, tmp_path / "session-output")
    assert result["candidates"][0]["provider"] == "codex-chatgpt"
    assert result["candidates"][0]["generationId"] == "offline-generation-id"
    assert client.generate.call_args.args[1] is request
    assert client.generate.call_args.args[2] == images


def test_unaligned_model_output_retains_raw_and_reports_alignment_gate(tmp_path, monkeypatch):
    bundle = sample_bundle(tmp_path, variants=1)
    request, images = ai.load_request(bundle)
    with zipfile.ZipFile(bundle) as archive:
        wrong_size = archive.read("reference.png")
    monkeypatch.setattr(ai, "_generate_one", lambda *_args: (wrong_size, "offline"))
    folder = tmp_path / "unaligned"
    result = ai.execute(request, images, folder)
    assert result["normalizedCandidates"] == 0
    assert (folder / "variant_01_model_raw.png").read_bytes() == wrong_size
    assert not (folder / "variant_01.png").exists()
    assert json.loads((folder / "run-status.json").read_text())["status"] == "alignment_review_required"


def test_loopback_dispatch_accepts_both_source_bound_formats(tmp_path):
    import sprite_editor_local as local
    bundle = sample_bundle(tmp_path, variants=1)
    request, images, runner = local.image_job(bundle.read_bytes())
    assert runner is local.execute_workshop
    assert request["_request_sha256"]
    assert images[0][0] == "model_reference.png"


def test_local_editor_launcher_preserves_navigation_fragment(monkeypatch):
    import sprite_editor_local as local
    calls = []
    monkeypatch.setattr(local.subprocess, "Popen", lambda args, **kwargs: calls.append(args))
    local.launch("en", area="ai")
    assert calls[0][-3:] == ["en", "--area", "ai"]
    with pytest.raises(ValueError):
        local.launch("en", area="execute")


def test_loopback_workshop_zip_roundtrip_with_synthetic_codex(tmp_path, monkeypatch):
    import gc
    # Earlier GUI tests leave unreachable Tcl/Variable cycles in this process.
    # Finalize them on their owning main thread before HTTP allocations can
    # trigger collection in the request worker (which has no Tk event loop).
    gc.collect()
    from http.client import HTTPConnection
    from threading import Thread
    import sprite_editor_local as local
    bundle = sample_bundle(tmp_path, variants=1)
    request, images = ai.load_request(bundle)
    monkeypatch.setattr(ai, "_generate_one", lambda *_args: (images[0][1], "offline-loopback"))
    with local.EditorServer(port=0) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = HTTPConnection(local.HOST, server.server_port, timeout=10)
            headers = {"Origin":server.origin, "X-SpriteSuite-Session":server.token,
                       "Content-Type":"application/zip"}
            connection.request("POST", "/codex/generate", bundle.read_bytes(), headers)
            response = connection.getresponse()
            assert response.status == 200
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                status = json.loads(archive.read("run-status.json"))
                meta = json.loads(archive.read("variant_01_meta.json"))
                assert status["status"] == "candidates_ready_for_review"
                assert meta["requestSHA256"] == request["_request_sha256"]
                assert meta["candidateSHA256"] == hashlib.sha256(archive.read("variant_01.png")).hexdigest()
            connection.close()
            headers["Origin"] = "https://untrusted.invalid"
            connection = HTTPConnection(local.HOST, server.server_port, timeout=10)
            connection.request("POST", "/codex/generate", bundle.read_bytes(), headers)
            response = connection.getresponse()
            assert response.status == 403
            response.read()
            connection.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)


def test_loopback_dispatch_retains_existing_damage_contract(tmp_path):
    import sprite_editor_local as local
    bundle = sample_bundle(tmp_path, variants=1)
    with zipfile.ZipFile(bundle) as archive:
        source = archive.read("reference.png")
    damage = {"format":"stronghold-building-damage-request", "version":1,
              "provider":"codex-chatgpt", "stageId":"offline-fixture",
              "model":"gpt-image-2.6-flare", "quality":"high", "size":"auto",
              "prompt":"Preserve source registration while editing the building.",
              "referenceSHA256":hashlib.sha256(source).hexdigest(),
              "referenceWidth":64, "referenceHeight":32, "referenceFiles":["reference.png"]}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,"w") as archive:
        archive.writestr("reference.png",source)
        archive.writestr("request.json",json.dumps(damage))
    checked, images, runner = local.image_job(stream.getvalue())
    assert runner is local.execute_damage
    assert checked["stageId"] == "offline-fixture"
    assert images == [("reference.png",source)]


@pytest.mark.parametrize("host", ["auth.openai.com", "chatgpt.com"])
def test_managed_login_accepts_documented_official_browser_hosts(host, monkeypatch):
    from unittest.mock import Mock
    import sprite_codex_session as codex_module
    codex = object.__new__(codex_module.CodexSession)
    codex.connected = Mock(side_effect=[False, True])
    codex.request = Mock(return_value={"type":"chatgpt", "authUrl":"https://"+host+"/login", "loginId":"fixture"})
    codex.events = Mock(return_value=iter([{"method":"account/login/completed", "params":{"loginId":"fixture", "success":True}}]))
    opened = []
    monkeypatch.setattr(codex_module.webbrowser,"open",lambda url: opened.append(url) or True)
    codex.login()
    assert opened == ["https://"+host+"/login"]
