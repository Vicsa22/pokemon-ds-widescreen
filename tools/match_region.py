#!/usr/bin/env python3
"""Where another copy of a game (another language: the Spanish Black 2, say) has the functions
of a function table made from the English copy. A developer tool, run once with both ROMs; its
output, a shift file of addresses only (tools/bw2/IRES.shifts, ...), goes in the repository and
is what the builds use (tools/region_tables.py makes the other copy's table from it).

    python3 tools/match_region.py <table.txt> <its ROM> <other ROM> <out.shifts> [--game NAME]

<table.txt> is the English copy's table as the build makes it (tools/bw2/funcmap.py,
tools/bw1/funcmap.py, tools/platinum/CPUE.txt), with or without the overlays' first bytes.
Each of its functions is looked for in the other ROM by its code (tools/codematch.py); the
result is written as shifts: from an address of the English copy on, the other copy has the
code that many bytes later, until the next line of the same module. Functions that are not
found (rewritten for the language) keep the shift of the one before them. The few data tables
the frontend patches (frontend/bw2map.h) are found by their exact bytes and written as
"data NAME module address" lines.

Check the summary it prints: most functions of every module should be found; a module with
few found has the other copy's code arranged differently and needs a look.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codematch import COMPARE, Module, Rom, shift_lines  # noqa: E402

# The data tables the frontend changes in memory (frontend/bw2map.h, by the English copies'
# addresses): name -> (module, address, size), per game code. Found in the other copy by their
# exact bytes (the map windows and heap sizes do not change with the language).
DATA = {
    'IREO': {'MAP_CONFIGS': ('ov036', 0x021ca01c, 29 * 72), 'HEAP_SETUP_NTR': ('main', 0x0208ee68, 16)},
    'IRDO': {'MAP_CONFIGS': ('ov036', 0x021ca050, 29 * 72), 'HEAP_SETUP_NTR': ('main', 0x0208ee94, 16)},
    'IRBO': {'MAP_CONFIGS': ('ov021', 0x021d3700, 21 * 72), 'HEAP_SETUP_NTR': ('main', 0x0209d8b0, 16)},
    'IRAO': {'MAP_CONFIGS': ('ov021', 0x021d3718, 21 * 72), 'HEAP_SETUP_NTR': ('main', 0x0209d8c8, 16)},
}
# (The tables name an overlay with three digits, ov036, as the decompilations do; a shift file
# or a test may say ov36: both are the same module.)


def same_module(a, b):
    return a == b or (a.startswith('ov') and b.startswith('ov') and a[2:].isdigit() and b[2:].isdigit() and int(a[2:]) == int(b[2:]))

# The names of the games by code, for the shift file's header (the launcher has its own).
GAMES = {
    'IRBS': 'Pokemon Negro', 'IRAS': 'Pokemon Blanco', 'IRES': 'Pokemon Negro 2', 'IRDS': 'Pokemon Blanco 2',
    'IPKS': 'Pokemon Oro HeartGold', 'IPGS': 'Pokemon Plata SoulSilver', 'CPUS': 'Pokemon Platino',
}


def load_table(path):
    """[(module, address, thumb, name)] from a function table (tools/bw2/funcmap.py's lines)."""
    rows = []
    for line in open(path):
        words = line.split()
        if len(words) < 5 or words[1] not in ('a', 't'):
            continue
        rows.append((words[2], int(words[0], 16), words[1] == 't', words[4]))
    return rows


def module_order(name):
    return (name != 'main', name not in ('itcm', 'dtcm'), int(name[2:]) if name[2:].isdigit() else 0, name)


def match(rows, src, dst, data=None, log=sys.stderr):
    """(shift lines, data lines, notes) for the functions of `rows` (load_table's) found in dst."""
    by_module = {}
    for module, addr, thumb, name in rows:
        by_module.setdefault(module, []).append((addr, thumb, name))
    out, notes, data_lines = [], [], []
    for module in sorted(by_module, key=module_order):
        funcs = sorted(by_module[module])
        m = Module(module, src, dst)
        if not m.ok:
            notes.append(f'{module}: not in both ROMs; its {len(funcs)} functions keep their addresses')
            continue
        missed = []
        for i, (addr, thumb, name) in enumerate(funcs):
            # (A function's size: up to the next one in the module, as far as the comparison
            # looks anyway.)
            size = min(COMPARE, funcs[i + 1][0] - addr) if i + 1 < len(funcs) else COMPARE
            if m.find(addr, size, thumb) is None:
                missed.append(name)
            out.append((module, addr, m.shift, name))
        notes.append(f'{module}: {m.found} of {len(funcs)} functions found, {m.missed} not'
                     + (' (' + ', '.join(missed[:6]) + (', ...' if len(missed) > 6 else '') + ')' if missed else ''))
        for name, (dmod, daddr, dsize) in sorted((data or {}).items()):
            if not same_module(dmod, module):
                continue
            found = m.find_bytes(daddr, dsize)
            if found is None:
                notes.append(f'{module}: data table {name} not found; the wider map windows stay off')
            else:
                data_lines.append('data %s %s %08x' % (name, module, found))
    return shift_lines(out), data_lines, notes


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    game = None
    for i, a in enumerate(sys.argv[1:]):
        if a == '--game' and i + 2 <= len(sys.argv[1:]):
            game = sys.argv[i + 2]
            args = [x for x in args if x != game]
    if len(args) != 4:
        sys.exit(__doc__)
    table, src_path, dst_path, out_path = args
    rows = load_table(table)
    if not rows:
        sys.exit(f'{table}: no functions')
    src, dst = Rom(src_path), Rom(dst_path)
    if src.code == dst.code:
        print(f'warning: both ROMs have game code {src.code}: the same copy twice?', file=sys.stderr)
    lines, data_lines, notes = match(rows, src, dst, DATA.get(src.code))
    for n in notes:
        print(n, file=sys.stderr)
    game = game or GAMES.get(dst.code, dst.code)
    with open(out_path, 'w') as f:
        f.write(f'# {game} ({dst.code}): where it has the functions of the {src.code} table, as shifts\n'
                '# from that table\'s addresses: <module> <address from which> <shift> <the first function so moved>.\n'
                '# Made by tools/match_region.py; read by tools/shift_table.py and tools/region_tables.py.\n'
                f'code {dst.code}\nfrom {src.code}\ngame {game}\n')
        for l in data_lines + lines:
            f.write(l + '\n')
    print(f'{out_path}: {len(lines)} shift lines, {len(data_lines)} data tables, for {game} ({dst.code}) from {src.code}')


if __name__ == '__main__':
    main()
