"""Short private .NET Framework compiler scratch without game or system writes."""
from __future__ import annotations
import os
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
from suite_windows_csharp_scratch import short_csharp_scratch, CSharpScratchError


def test_compiler_scratch_is_private_and_automatically_cleaned(tmp_path,monkeypatch):
    private=tmp_path/"user-local"
    monkeypatch.setenv("LOCALAPPDATA",str(private))
    with short_csharp_scratch() as compiler:
        assert compiler.is_dir()
        assert compiler.is_relative_to(private/"SpriteSuite"/"CSharpScratch")
        file=compiler/"OriginsCampaignData.g.cs"
        file.write_text("public class Demo {}",encoding="utf8")
        assert file.is_file()
        old=compiler
    assert not old.exists()
    assert (private/"SpriteSuite"/"CSharpScratch").is_dir()
    assert not list((private/"SpriteSuite"/"CSharpScratch").iterdir())


def test_multiple_compilers_never_share_same_running_scratch(tmp_path,monkeypatch):
    private=tmp_path/"local"
    monkeypatch.setenv("LOCALAPPDATA",str(private))
    with short_csharp_scratch() as first:
        with short_csharp_scratch() as second:
            assert first!=second
            (first/"a.txt").write_text("first")
            (second/"b.txt").write_text("second")
            assert not (first/"b.txt").exists()
            assert not (second/"a.txt").exists()
        assert first.exists()
        assert not second.exists()
    assert not first.exists()


def test_compiler_scratch_rejects_non_directory_destination(tmp_path,monkeypatch):
    base=tmp_path/"local"
    monkeypatch.setenv("LOCALAPPDATA",str(base))
    (base/"SpriteSuite").mkdir(parents=True)
    target=base/"SpriteSuite"/"CSharpScratch"
    target.write_bytes(b"user-owned-file")
    with pytest.raises(CSharpScratchError,match="linked"):
        with short_csharp_scratch():
            pytest.fail("Must not enter file-owned scratch")
    assert target.read_bytes()==b"user-owned-file"
