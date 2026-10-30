"""Finds where another copy of a game (another language, or the other version of a pair) has the
code of the copy a table was made from. Shared by tools/match_region.py (the function tables of
Black, White, Black 2, White 2 and Platinum) and tools/soulsilver/match_heartgold.py (SoulSilver's
chunk table): a developer tool's library, run with the two ROMs once; what it finds is written
down as addresses (the shift files), and the builds never need it.

A function is found by its instructions once addresses, branch targets and literal-pool offsets
are masked (tokens, as tools/bw1/match_bw2.py compares them). The other copy is searched first
near where the running shift says the function should be (a translation moves code by a little
at a time, as its texts and tables change size), then anywhere in the same module. A short
function's masked instructions can be found in more than one place, so a short one only counts
where the running shift already says it is.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ndsrom import NITROCODE, read_rom  # noqa: E402

# How far either side of the running shift a function is looked for before the whole module is
# searched; the texts of a translation rarely move code further than this at once.
WINDOW = 0x4000
# A function shorter than this moves the running shift only where it is found at it.
SHORT = 24
# The longest prefix of a function compared as plain bytes (a fast first look, before the masked
# comparison), and how much of a function is compared at most (a translation can change the end
# of a function that formats text; its start is what tells it).
NEEDLE = 16
COMPARE = 48


def autoloads(main, ram):
    """The main program's autoload blocks (the ITCM's and DTCM's code and data, copied out of it
    by the start-up code): address -> bytes, from the module parameters the "nitrocode" marker
    points at (the list of blocks, and where their images start). A block's entry is 12 bytes
    (address, size, bss size) in the DS SDK and 16 in the DSi-enhanced games' (the address again
    before the bss size); the list's length and the addresses tell which."""
    marker = struct.pack('<I', NITROCODE)
    pos = main.find(marker)
    while pos >= 0:
        p = pos - 0x1C
        if p >= 0:
            list_start, list_end, data_start = struct.unpack_from('<3I', main, p)
            lo, hi, data0 = list_start - ram, list_end - ram, data_start - ram
            if 0 <= lo <= hi <= len(main) and 0 <= data0 <= len(main):
                for stride in (12, 16):
                    if (hi - lo) % stride:
                        continue
                    out, data, ok = {}, data0, True
                    for i in range(lo, hi, stride):
                        addr, size = struct.unpack_from('<2I', main, i)
                        if not 0x01FF8000 <= addr < 0x0A000000 or data + size > len(main):
                            ok = False
                            break
                        out[addr] = main[data:data + size]
                        data += size
                    if ok:
                        return out
        pos = main.find(marker, pos + 1)
    return {}


class Rom:
    """A ROM's ARM9 code: the main program (at its load address), its autoload blocks and the
    overlays."""

    def __init__(self, path):
        with open(path, 'rb') as f:
            header = f.read(0x30)
        self.path = path
        self.code = header[0x0C:0x10].decode('ascii', 'replace')
        self.ram = struct.unpack_from('<I', header, 0x28)[0]
        self.main, self.ovs = read_rom(path)
        self.auto = autoloads(self.main, self.ram)

    @classmethod
    def from_images(cls, code, ram, main, ovs, auto=None):
        """The same from images in memory (tests)."""
        rom = cls.__new__(cls)
        rom.path, rom.code, rom.ram, rom.main, rom.ovs = '<memory>', code, ram, main, dict(ovs)
        rom.auto = dict(auto) if auto is not None else autoloads(main, ram)
        return rom

    def module(self, name):
        """(load address, bytes) of a module as the tables name them: main, ovNNN (an overlay),
        itcm or dtcm (the autoload block in that memory). None if the ROM has no such module."""
        if name == 'main':
            return self.ram, self.main
        if name.startswith('ov') and name[2:].isdigit() and int(name[2:]) in self.ovs:
            return self.ovs[int(name[2:])]
        ranges = {'itcm': (0x01FF8000, 0x02000000), 'dtcm': (0x027C0000, 0x02800000)}
        if name in ranges:
            lo, hi = ranges[name]
            for addr in sorted(self.auto):
                if lo <= addr < hi:
                    return addr, self.auto[addr]
        return None


def is_addr(w):
    return 0x01FF8000 <= w < 0x02400000 or 0x027E0000 <= w < 0x02800000


def tokens(code, thumb):
    """The instructions with what moves between builds masked: branch targets, PC-relative loads
    and words that look like addresses (literal pools)."""
    t = []
    if not thumb:
        for i in range(0, len(code) - 3, 4):
            w = struct.unpack_from('<I', code, i)[0]
            if is_addr(w):
                t.append(0xADD0ADD0)
                continue
            if (w >> 25) & 7 == 5:
                w &= 0xFF000000                                  # b / bl / blx
            elif (w & 0x0F7F0000) == 0x051F0000:
                w &= 0xFFFFF000                                  # ldr rX, [pc, #imm]
            t.append(w)
        return tuple(t)
    i, n = 0, len(code)
    while i + 1 < n:
        h = struct.unpack_from('<H', code, i)[0]
        if i % 4 == 0 and i + 3 < n and is_addr(struct.unpack_from('<I', code, i)[0]):
            t.append(0xADD0ADD0)
            i += 4
            continue
        if (h >> 11) == 0x1E:                                      # bl / blx pair
            if i + 3 >= n:                                           # (cut off: its first half)
                t.append(0xF000)
                break
            t.append(0xF000 | ((struct.unpack_from('<H', code, i + 2)[0] >> 11) << 16))
            i += 4
            continue
        if (h >> 11) == 0x09:
            h &= 0xFF00                                          # ldr rX, [pc, #imm]
        elif (h >> 12) == 0xD and ((h >> 8) & 0xF) < 0xE:
            h &= 0xFF00                                          # b<cond>
        elif (h >> 11) == 0x1C:
            h &= 0xF800                                          # b
        t.append(h)
        i += 2
    return tuple(t)


def needle(code, thumb):
    """The start of the function as plain bytes, up to the first instruction the masking
    changes (which the other copy may well have assembled differently): what bytes.find looks
    for before the masked comparison. Empty when the very first instruction is masked."""
    n = 0
    if not thumb:
        for i in range(0, min(len(code), NEEDLE) - 3, 4):
            w = struct.unpack_from('<I', code, i)[0]
            if is_addr(w) or (w >> 25) & 7 == 5 or (w & 0x0F7F0000) == 0x051F0000:
                break
            n = i + 4
        return code[:n]
    i = 0
    while i + 1 < min(len(code), NEEDLE):
        h = struct.unpack_from('<H', code, i)[0]
        if i % 4 == 0 and i + 3 < len(code) and is_addr(struct.unpack_from('<I', code, i)[0]):
            break
        if (h >> 11) in (0x1E, 0x09, 0x1C) or ((h >> 12) == 0xD and ((h >> 8) & 0xF) < 0xE):
            break
        n = i + 2
        i += 2
    return code[:n]


def locate(src, off, size, thumb, dst, near, window=WINDOW):
    """Where dst has the code at src[off:off+size]: (the offset into dst, how many places had
    it), or (None, 0). `near` is the offset into dst the running shift expects; of several
    places the nearest is taken."""
    size = max(4, min(size, COMPARE, len(src) - off))
    if off < 0 or off + size > len(src):
        return None, 0
    code = src[off:off + size]
    want = tokens(code, thumb)
    step = 2 if thumb else 4
    nd = needle(code, thumb)

    def hit(o):
        return o % step == 0 and 0 <= o and o + size <= len(dst) and tokens(dst[o:o + size], thumb) == want

    def scan(lo, hi):
        lo, hi = max(0, lo), min(len(dst), hi)
        found = []
        if nd:
            p = dst.find(nd, lo, hi)
            while 0 <= p < hi:
                if hit(p):
                    found.append(p)
                p = dst.find(nd, p + 1, hi)
        else:
            for o in range(lo - lo % step, hi, step):
                if hit(o):
                    found.append(o)
        return found

    found = scan(near - window, near + window + size)
    # (A needle of under 4 bytes is found all over a module: a function that starts with a
    # branch is not looked for outside the window.)
    if not found and len(nd) >= 4:
        found = scan(0, len(dst))
    if not found:
        return None, 0
    return min(found, key=lambda o: abs(o - near)), len(found)


def locate_bytes(src, off, size, dst, near, window=WINDOW):
    """Where dst has the bytes src[off:off+size] (a table of data) with the words that look like
    addresses left out of the comparison (a table's pointers move with the code): the offset,
    or None. The nearest to `near`; the whole of dst when the window has none."""
    if off < 0 or off + size > len(src):
        return None
    pattern = src[off:off + size]
    masked = [is_addr(struct.unpack_from('<I', pattern, i)[0]) for i in range(0, len(pattern) - 3, 4)]
    # The plain bytes up to the first address, for bytes.find; at least one word of them.
    n = next((i for i, m in enumerate(masked) if m), len(masked)) * 4
    if n < 4:
        return None
    nd = pattern[:n]

    def hit(o):
        if o + len(pattern) > len(dst):
            return False
        return all(m or pattern[i * 4:i * 4 + 4] == dst[o + i * 4:o + i * 4 + 4] for i, m in enumerate(masked))

    found = []
    for lo, hi in ((max(0, near - window), min(len(dst), near + window + size)), (0, len(dst))):
        p = dst.find(nd, lo, hi)
        while 0 <= p < hi:
            if hit(p):
                found.append(p)
            p = dst.find(nd, p + 1, hi)
        if found:
            break
    if not found:
        return None
    return min(found, key=lambda o: abs(o - near))


class Module:
    """One module's bytes in both copies, and where the function at an address of the first copy
    is in the second, keeping the running shift from one function to the next (so ask for them
    in address order)."""

    def __init__(self, name, src, dst):
        self.name = name
        self.found = self.missed = 0
        a, b = src.module(name), dst.module(name)
        self.ok = bool(a and b)
        if self.ok:
            (self.src_base, self.src), (self.dst_base, self.dst) = a, b
            # (An overlay or block loaded elsewhere in the other copy: its code moves with it.)
            self.shift = self.dst_base - self.src_base

    def find(self, addr, size, thumb):
        """The address the other copy has the function at, or None."""
        if not self.ok:
            return None
        # The main program's first 2 KB (the secure area) are encrypted in some dumps and in
        # the clear in others: their few stubs are not compared, and keep the running shift.
        if self.name == 'main' and addr - self.src_base < 0x800:
            return None
        o, places = locate(self.src, addr - self.src_base, size, thumb, self.dst, addr + self.shift - self.dst_base)
        if o is None:
            self.missed += 1
            return None
        self.found += 1
        shift = o + self.dst_base - addr
        if size < SHORT and shift != self.shift and places > 1:
            # (Not where the running shift says, and too short to be sure which of the places
            # that have its instructions is this one.)
            return None
        self.shift = shift
        return addr + shift

    def find_bytes(self, addr, size):
        """The address the other copy has the exact bytes at addr (a table of data), or None."""
        if not self.ok:
            return None
        o = locate_bytes(self.src, addr - self.src_base, size, self.dst, addr + self.shift - self.dst_base)
        return None if o is None else o + self.dst_base


def shift_lines(rows):
    """Shift lines from (module, address, shift, name) rows in table order: one where the shift
    changes within a module, as tools/bw1/white_shifts.txt has them."""
    lines, last = [], {}
    for module, addr, shift, name in rows:
        if last.get(module) == shift:
            continue
        last[module] = shift
        lines.append('%s %08x %+#x %s' % (module, addr, shift, name))
    return lines


# A shift file's header lines: the game code the shifts lead to, the code of the copy the table
# was made from, and the game's name.
HEADER_KEYS = ('code', 'from', 'game')


def load_shifts(path):
    """A shift file: its header words (code, from, game) and module -> sorted [(address from
    which, shift)], plus the data symbols it names: name -> (module, address in the other copy).
    Lines: "<module> <address> <shift> <name>", "data <name> <module> <address>", "<key> <value>"
    for the header; # starts a comment."""
    header, shifts, data = {}, {}, {}
    for line in open(path):
        words = line.split('#', 1)[0].split()
        if not words:
            continue
        if words[0] in HEADER_KEYS:
            header[words[0]] = ' '.join(words[1:])
        elif words[0] == 'data' and len(words) >= 4:
            data[words[1]] = (words[2], int(words[3], 16))
        elif len(words) >= 3:
            shifts.setdefault(words[0], []).append((int(words[1], 16), int(words[2], 16)))
    for v in shifts.values():
        v.sort()
    return header, shifts, data


def shifted(shifts, module, addr):
    """Where the other copy has what the first has at addr (unchanged where no shift is known)."""
    d = 0
    for start, delta in shifts.get(module, ()):
        if start > addr:
            break
        d = delta
    return addr + d
