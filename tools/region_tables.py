#!/usr/bin/env python3
"""The other languages' function tables, for a build: for every shift file in the repository
(tools/bw1/*.shifts, tools/bw2/*.shifts, tools/platinum/*.shifts, made by
tools/match_region.py) whose English table is in the folder, writes that language's table
beside it, named by its game code (IRES.txt from IREO.txt and tools/bw2/IRES.shifts).

    python3 tools/region_tables.py <funcs folder>

Run by the build scripts after the English tables are made (tools/pc/build_all.sh,
tools/android/build_all.sh, tools/mac/build_all.sh, tools/switch/build_game.sh). A shift file
whose English table is missing is reported and skipped.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codematch import load_shifts  # noqa: E402
from shift_table import shift_table  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def shift_files():
    return sorted(p for sub in ('bw1', 'bw2', 'platinum') for p in glob.glob(os.path.join(HERE, sub, '*.shifts')))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = sys.argv[1]
    made = 0
    for path in shift_files():
        header, _, _ = load_shifts(path)
        code, source = header.get('code'), header.get('from')
        if not code or not source:
            print(f'{path}: no code/from header; skipped', file=sys.stderr)
            continue
        table = os.path.join(folder, source + '.txt')
        if not os.path.isfile(table):
            print(f'{path}: {table} is not there; {code} skipped', file=sys.stderr)
            continue
        _, n = shift_table(table, path, os.path.join(folder, code + '.txt'))
        print(f'{code}.txt: {n} lines for {header.get("game", code)}, from {source}.txt and {os.path.relpath(path, HERE)}')
        made += 1
    print(f'{made} other languages\' tables' if made != 1 else "1 other language's table")


if __name__ == '__main__':
    main()
