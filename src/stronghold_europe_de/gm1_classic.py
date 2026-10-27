"""Minimal GM1 reader for Stronghold 1 classic archives.

Layout (little-endian):
    header      88 bytes  = 22 uint32
    palette     5120 bytes = 10 * 256 * uint16
    offsets     n * uint32
    sizes       n * uint32
    imgheaders  n * 16 bytes
    data        rest
"""
import struct
from dataclasses import dataclass

DATA_TYPES = {
    1: "interface",        # TGX, 16bit
    2: "animation",        # TGX, 8bit palette indices
    3: "tile_object",      # tile diamond + optional TGX overlay
    4: "font",
    5: "uncompressed",
    6: "tgx_const_size",
    7: "uncompressed_2",
}


@dataclass
class ImageHeader:
    width: int
    height: int
    offset_x: int
    offset_y: int
    part_id: int
    part_count: int
    tile_offset_y: int
    direction: int
    horiz_offset: int
    building_width: int
    flags: int


class GM1:
    def __init__(self, path):
        with open(path, "rb") as fh:
            self.raw = fh.read()
        self.path = path
        h = struct.unpack_from("<22I", self.raw, 0)
        self.header = h
        self.num_images = h[3]
        self.data_type = h[5]
        self.data_size = h[20]
        off = 88
        self.palette = struct.unpack_from("<%dH" % (10 * 256), self.raw, off)
        off += 10 * 256 * 2
        n = self.num_images
        self.offsets = struct.unpack_from("<%dI" % n, self.raw, off); off += 4 * n
        self.sizes = struct.unpack_from("<%dI" % n, self.raw, off); off += 4 * n
        self.images = []
        for i in range(n):
            w, ht, ox, oy = struct.unpack_from("<4H", self.raw, off)
            pid, pc = struct.unpack_from("<2B", self.raw, off + 8)
            toy, = struct.unpack_from("<H", self.raw, off + 10)
            d, ho, bw, fl = struct.unpack_from("<4B", self.raw, off + 12)
            self.images.append(ImageHeader(w, ht, ox, oy, pid, pc, toy, d, ho, bw, fl))
            off += 16
        self.data_start = off

    def image_bytes(self, i):
        s = self.data_start + self.offsets[i]
        return self.raw[s:s + self.sizes[i]]

    @property
    def type_name(self):
        return DATA_TYPES.get(self.data_type, "unknown_%d" % self.data_type)

    def __repr__(self):
        return "<GM1 %s n=%d type=%s(%d)>" % (
            self.path.split("/")[-1], self.num_images, self.type_name, self.data_type)
