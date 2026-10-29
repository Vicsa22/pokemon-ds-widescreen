#!/usr/bin/env python3
"""Makes another copy's function table (another language: tools/bw2/IRES.shifts for the Spanish
Black 2) from the English copy's table and the shift file tools/match_region.py wrote.

    python3 tools/shift_table.py <table.txt> <shifts file> <out.txt> [other ROM]

Every function's address is moved by the shift its module has from that address on; the data
tables the shift file names are added as "d" lines (frontend/bw2map.h reads them). The
overlays' first bytes are left as ? for the program to read from the player's ROM (as the
English tables made without a ROM have them), unless the other copy's ROM is given.
The table holds addresses, names and a few bytes per function: not the game's code.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codematch import Rom, load_shifts, shifted  # noqa: E402


def shift_table(table, shifts_path, out_path, rom=None):
    """Writes the shifted table; returns (header, number of lines)."""
    header, shifts, data = load_shifts(shifts_path)
    rows = []
    for line in open(table):
        words = line.split()
        if len(words) < 5 or words[1] not in ('a', 't', 'd'):
            continue
        module, name = words[2], words[4]
        addr = shifted(shifts, module, int(words[0], 16))
        first = '-'
        if module.startswith('ov') and words[1] != 'd':
            first = '?'
            if rom is not None:
                mod = rom.module(module)
                if mod and 0 <= addr - mod[0] and addr - mod[0] + 4 <= len(mod[1]):
                    first = mod[1][addr - mod[0]:addr - mod[0] + 4].hex()
        rows.append((addr, words[1], module, first, name))
    for name, (module, addr) in data.items():
        rows.append((addr, 'd', module, '-', name))
    with open(out_path, 'w') as f:
        for r in sorted(rows):
            f.write('%08x %s %s %s %s\n' % r)
    return header, len(rows)


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    table, shifts_path, out_path = sys.argv[1:4]
    rom = Rom(sys.argv[4]) if len(sys.argv) == 5 else None
    header, n = shift_table(table, shifts_path, out_path, rom)
    if rom is not None and header.get('code') and rom.code != header['code']:
        print(f'warning: {sys.argv[4]} is {rom.code}, but the shifts are for {header["code"]}', file=sys.stderr)
    print(f'{out_path}: {n} lines for {header.get("game", "?")} ({header.get("code", "?")}) from {table}')


if __name__ == '__main__':
    main()
