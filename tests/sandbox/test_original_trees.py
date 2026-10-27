"""Native section-1014 tree records are independent, CRC-checked and read-only."""
from pathlib import Path
import pytest
from stronghold_europe_de.sandbox.map_sections import (
    load_original_trees, tile_index, NativeOriginalTree
)

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")

@pytest.mark.skipif(not MAPS.is_dir(), reason="SHCDE installation unavailable")
@pytest.mark.parametrize("name,expected", [
    ("Antioch.map",1139),
    ("Crusader Demo.map",1050),
    ("A Mighty Oasis.map",1242),
])
def test_original_tree_coords_are_native_diamond(name,expected):
    path=MAPS/name
    source_before=(path.stat().st_mtime_ns,path.stat().st_size)
    trees=load_original_trees(path)
    assert len(trees)==expected
    assert len({tree.record_number for tree in trees})==expected
    assert len({(tree.x,tree.y) for tree in trees})>expected//2
    assert all(0<=tile_index(tree.x,tree.y)<320800 for tree in trees)
    assert {tree.raw_group for tree in trees}.issubset({29,30,31,70,71,72,200})
    assert (path.stat().st_mtime_ns,path.stat().st_size)==source_before
