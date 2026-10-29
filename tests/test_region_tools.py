#!/usr/bin/env python3
"""The other-language tools (tools/codematch.py, match_region.py, shift_table.py,
region_tables.py) on made-up code: a "game" of a few ARM and Thumb functions, and a "translation"
of it with bytes inserted here and there (its code moved), an overlay loaded elsewhere, an
autoload block and a data table. No game content: the functions are invented.

    python3 tests/test_region_tools.py      (or pytest tests/test_region_tools.py)
"""
import os
import random
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import codematch  # noqa: E402
import match_region  # noqa: E402
import region_tables  # noqa: E402
import shift_table  # noqa: E402
from ndsrom import NITROCODE  # noqa: E402

RAM = 0x02000000
ITCM = 0x01FF8000


def arm_function(rng, words):
    """An ARM function: push, some data processing with random registers, a branch, a
    PC-relative load, pop; then a literal pool with an address."""
    out = [0xE92D4010]                                   # push {r4, lr}
    for _ in range(words - 5):
        out.append(0xE0800000 | rng.randrange(16) << 12 | rng.randrange(16))  # add rX, r0, rY
    out.append(0xEB000000 | rng.randrange(0x1000))       # bl somewhere
    out.append(0xE59F0000 | rng.randrange(4) << 12 | 8)  # ldr rX, [pc, #8]
    out.append(0xE8BD8010)                               # pop {r4, pc}
    out.append(0x02000000 | rng.randrange(0x100000))     # a literal: an address
    return b''.join(struct.pack('<I', w) for w in out)


def thumb_function(rng, halfwords):
    out = [0xB510]                                       # push {r4, lr}
    for _ in range(halfwords - 5):
        out.append(0x1800 | rng.randrange(8) << 6 | rng.randrange(8) << 3 | rng.randrange(8))  # add rX, rY, rZ
    out.append(0xF000 | rng.randrange(0x800))            # bl pair
    out.append(0xF800 | rng.randrange(0x800))
    out.append(0x4800 | rng.randrange(8) << 8 | 2)       # ldr rX, [pc, #8]
    out.append(0xBD10)                                   # pop {r4, pc}
    return b''.join(struct.pack('<H', h) for h in out)


def build(rng, inserts):
    """A module's functions, and the same with `inserts` bytes of padding before the functions
    at those indices (a translation's moved code): (functions, image, image2, offsets, offsets2).
    Branch targets and literal pools of the moved copy are re-rolled, as a build would."""
    funcs = []
    for i in range(40):
        if i % 3 == 2:
            funcs.append(('t', thumb_function(rng, rng.randrange(6, 30))))
        else:
            funcs.append(('a', arm_function(rng, rng.randrange(6, 20))))
    image, image2, offs, offs2 = bytearray(), bytearray(), [], []
    for i, (kind, code) in enumerate(funcs):
        offs.append(len(image))
        image += code
        if i in inserts:
            image2 += bytes(inserts[i])
        offs2.append(len(image2))
        # The same instructions with other branch targets and literals (what the masks hide).
        moved = bytearray(code)
        if kind == 'a':
            for p in range(0, len(moved), 4):
                w = struct.unpack_from('<I', moved, p)[0]
                if (w >> 25) & 7 == 5:
                    struct.pack_into('<I', moved, p, (w & 0xFF000000) | rng.randrange(0x1000))
                elif codematch.is_addr(w):
                    struct.pack_into('<I', moved, p, 0x02000000 | rng.randrange(0x100000))
        else:
            for p in range(0, len(moved) - 1, 2):
                h = struct.unpack_from('<H', moved, p)[0]
                if (h >> 11) in (0x1E, 0x1F):
                    struct.pack_into('<H', moved, p, (h & 0xF800) | rng.randrange(0x800))
        image2 += moved
        # (ARM functions start at a multiple of 4, as a build places them.)
        while len(image) % 4:
            image.append(0)
        while len(image2) % 4:
            image2.append(0)
    return funcs, bytes(image), bytes(image2), offs, offs2


def main_with_autoload(main_code, itcm_code):
    """A main program image: the code, then an autoload block (the ITCM's) and the module
    parameters the nitrocode marker points at, as the start-up code expects them."""
    main = bytearray(main_code)
    while len(main) % 4:
        main.append(0)
    list_off = len(main)
    main += struct.pack('<3I', ITCM, len(itcm_code), 0)
    params_off = len(main)
    data_off = params_off + 0x1C + 4
    main += struct.pack('<7I', RAM + list_off, RAM + params_off, RAM + data_off, 0, 0, 0, 0)
    main += struct.pack('<I', NITROCODE)
    main += itcm_code
    return bytes(main)


def make_pair(seed=1):
    rng = random.Random(seed)
    m_funcs, m1, m2, m_offs, m_offs2 = build(rng, {7: 0x30, 20: 0x1000, 31: 0x8})
    i_funcs, i1, i2, i_offs, i_offs2 = build(rng, {5: 0x10})
    o_funcs, o1, o2, o_offs, o_offs2 = build(rng, {3: 0x100})
    # A data table in the overlay (the map windows): the same bytes in both.
    table = b''.join(struct.pack('<I', 0x200000 + i) for i in range(18))
    o1t, o2t = o1 + table, o2 + bytes(0x40) + table
    table1, table2 = len(o1), len(o2) + 0x40
    ov_base1, ov_base2 = 0x021C0000, 0x021C0020
    rom1 = codematch.Rom.from_images('IREO', RAM, main_with_autoload(m1, i1), {36: (ov_base1, o1t)})
    rom2 = codematch.Rom.from_images('IRES', RAM, main_with_autoload(m2, i2), {36: (ov_base2, o2t)})
    rows, expect = [], {}
    for name, funcs, offs, offs2, base, base2, module in (
            ('m', m_funcs, m_offs, m_offs2, RAM, RAM, 'main'), ('i', i_funcs, i_offs, i_offs2, ITCM, ITCM, 'itcm'),
            ('o', o_funcs, o_offs, o_offs2, ov_base1, ov_base2, 'ov36')):
        for k, ((kind, _), off, off2) in enumerate(zip(funcs, offs, offs2)):
            fname = f'{name}_func_{k}'
            rows.append((module, base + off, kind == 't', fname))
            expect[fname] = base2 + off2
    data = {'MAP_CONFIGS': ('ov36', ov_base1 + table1, len(table))}
    return rom1, rom2, rows, expect, data, ov_base2 + table2


def test_autoloads():
    rom1, _, _, _, _, _ = make_pair()
    assert ITCM in rom1.auto and rom1.module('itcm')[0] == ITCM
    assert rom1.module('ov36')[0] == 0x021C0000 and rom1.module('ov99') is None


def test_match_and_shift():
    rom1, rom2, rows, expect, data, table2 = make_pair()
    lines, data_lines, notes = match_region.match(rows, rom1, rom2, data)
    assert data_lines == ['data MAP_CONFIGS ov36 %08x' % table2], data_lines
    assert any(l.startswith('main') for l in lines) and any(l.startswith('ov36') for l in lines)
    with tempfile.TemporaryDirectory() as tmp:
        shifts = os.path.join(tmp, 'IRES.shifts')
        with open(shifts, 'w') as f:
            f.write('code IRES\nfrom IREO\ngame Pokemon Negro 2\n' + '\n'.join(data_lines + lines) + '\n')
        table = os.path.join(tmp, 'IREO.txt')
        with open(table, 'w') as f:
            for module, addr, thumb, name in sorted(rows, key=lambda r: r[1]):
                f.write('%08x %s %s %s %s\n' % (addr, 't' if thumb else 'a', module, '?' if module.startswith('ov') else '-', name))
        header, _ = shift_table.shift_table(table, shifts, os.path.join(tmp, 'IRES.txt'), rom2)
        assert header['code'] == 'IRES' and header['game'] == 'Pokemon Negro 2'
        got, firsts, data_rows = {}, {}, {}
        for line in open(os.path.join(tmp, 'IRES.txt')):
            addr, kind, module, first, name = line.split()
            if kind == 'd':
                data_rows[name] = int(addr, 16)
            else:
                got[name] = int(addr, 16)
                firsts[name] = first
        assert data_rows == {'MAP_CONFIGS': table2}
        wrong = {n: (hex(got[n]), hex(expect[n])) for n in expect if got[n] != expect[n]}
        # Every function of every module lands where the translation has it (the short ones
        # included: they follow the running shift).
        assert not wrong, (wrong, notes)
        # The overlay's first bytes come from the other ROM when it is given.
        ov = rom2.module('ov36')
        for name, addr in got.items():
            if name.startswith('o_'):
                assert firsts[name] == ov[1][addr - ov[0]:addr - ov[0] + 4].hex()
        # Without a ROM they are left for the program to read.
        shift_table.shift_table(table, shifts, os.path.join(tmp, 'IRES2.txt'))
        assert all(l.split()[3] == '?' for l in open(os.path.join(tmp, 'IRES2.txt')) if l.split()[2] == 'ov36' and l.split()[1] != 'd')


def test_region_tables_skips_missing_source(capsys=None):
    # The repository's shift files name tables the build makes; with an empty folder none is
    # made, and nothing fails.
    with tempfile.TemporaryDirectory() as tmp:
        sys.argv = ['region_tables.py', tmp]
        region_tables.main()
        assert not [n for n in os.listdir(tmp) if n.endswith('.txt')]


def test_shift_lines_and_load():
    lines = codematch.shift_lines([('main', 0x02000000, 0, 'a'), ('main', 0x02000010, 0, 'b'),
                                   ('main', 0x02000020, 0x30, 'c'), ('ov1', 0x021C0000, 0x20, 'd')])
    assert lines == ['main 02000000 +0x0 a', 'main 02000020 +0x30 c', 'ov1 021c0000 +0x20 d']
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'x.shifts')
        with open(path, 'w') as f:
            f.write('# a comment\ncode IRES\nfrom IREO\ngame Pokemon Negro 2\ndata MAP_CONFIGS ov36 021ca034\n' + '\n'.join(lines) + '\n')
        header, shifts, data = codematch.load_shifts(path)
        assert header == {'code': 'IRES', 'from': 'IREO', 'game': 'Pokemon Negro 2'}
        assert data == {'MAP_CONFIGS': ('ov36', 0x021ca034)}
        assert codematch.shifted(shifts, 'main', 0x02000018) == 0x02000018
        assert codematch.shifted(shifts, 'main', 0x02000024) == 0x02000054
        assert codematch.shifted(shifts, 'ov1', 0x021C0100) == 0x021C0120
        assert codematch.shifted(shifts, 'ov2', 0x021C0100) == 0x021C0100


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print(name, 'ok')
