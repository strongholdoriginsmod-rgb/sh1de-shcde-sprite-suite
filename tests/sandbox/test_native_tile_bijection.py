"""Exhaustive headless native diamond index contract (every original tile).

No GUI or game files. Reproduces native 800-row index mathematical
bijection, including strict validation of JSON booleans as coordinates.
"""
import pytest
from stronghold_europe_de.sandbox.map_sections import (
    NATIVE_DIAMOND, tile_index, tile_row_length
)


def test_every_native_diamond_coordinate_maps_to_unique_linear_index():
    assert NATIVE_DIAMOND==800
    expected=0
    for y in range(NATIVE_DIAMOND):
        width=tile_row_length(y)
        assert width>0 and width%2==0
        left=(NATIVE_DIAMOND-width)//2
        assert 0<=left<left+width<=NATIVE_DIAMOND
        for x in range(left,left+width):
            assert tile_index(x,y)==expected,(x,y,expected)
            expected+=1
    assert expected==320800


@pytest.mark.parametrize("x,y",[
    (True,399), (False,399), (399,True), (399,False),
    (399.0,399),(399,399.0),("399",399),(399,"399"),
])
def test_boolean_or_coerced_coordinates_never_mean_real_map_tiles(x,y):
    with pytest.raises(TypeError):
        tile_index(x,y)
