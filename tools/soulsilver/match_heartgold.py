#!/usr/bin/env python3
"""Where another copy of SoulSilver's code has SoulSilver's (US) functions: HeartGold (US), or
either game in another language. A developer tool, run once; its output (addresses only:
tools/soulsilver/heartgold-us.json, soulsilver-es.json, ...) is what the build uses
(tools/soulsilver/tables_only.py puts every such file in the tables).

    python3 tools/soulsilver/match_heartgold.py <soulsilver-us.nds> <other.nds> <gen dir> OUT.json
                                                [--code IPGS] [--game "Pokemon Plata SoulSilver"]
    python3 tools/soulsilver/match_heartgold.py <heartgold-us.nds> <other.nds> - OUT.json --via heartgold-us.json

HeartGold's code is SoulSilver's with a few changes: 115 of the 121 code sections are the same
size, most byte for byte. A translation keeps the code too, but moves it: its texts and tables
are other sizes, so functions sit at other addresses, in the main program as well as in the
overlays. Each of SoulSilver's functions (the chunks in <gen dir>/rc_tables.cpp) is looked for
by its instructions with branch targets and literal-pool offsets masked (tools/codematch.py),
near where the running shift says first. The result is, per section, the stretches where the
other copy's address is SoulSilver's plus a shift: {"section": [[from, to, shift], ...]}
(SoulSilver addresses, from inclusive, to exclusive). Functions that are not found keep the
shift of the one before them. The game code and name come from the other ROM unless given.

Without SoulSilver's build (<gen dir> given as -), the functions come from the layout file
instead of the chunk table: its named addresses within its code ranges, which are where the
chunks start. And with --via, the first ROM is HeartGold (US) rather than SoulSilver: its own
shift file says where it has each SoulSilver function, so its bytes stand in for SoulSilver's,
and the shifts written are still from SoulSilver's addresses, as the tables need them.

Check the summary it prints: most functions of every section should be found.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from codematch import Module, Rom  # noqa: E402

LAYOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'layouts', 'soulsilver-us.json')

GAMES = {
    'IPKE': 'Pokemon HeartGold (USA)',
    'IPGS': 'Pokemon Plata SoulSilver', 'IPKS': 'Pokemon Oro HeartGold',
}


def chunks_of(gen):
    """(start, end, thumb, section index) of every chunk, and the sections' names."""
    text = open(os.path.join(gen, 'rc_tables.cpp')).read()
    chunks = [(int(a, 16), int(b, 16), int(t), int(s)) for a, b, t, s in
              re.findall(r'\{0x([0-9A-F]+)u, 0x([0-9A-F]+)u, (\d), (\d+), [^}]*\}', text)]
    names = re.findall(r'\{"(\w+)", 0x[0-9A-F]+u, 0x[0-9A-F]+u, ', text)
    return chunks, names


def chunks_of_layout(layout):
    """The same from the layout file, without a build: a chunk per named address inside a code
    range, up to the next named address or the range's end."""
    chunks, names = [], []
    for s, e in enumerate(layout['sections']):
        names.append(e['name'])
        named = sorted(set(e['named']))
        for start, end, thumb in e['ranges']:
            inside = [a for a in named if start <= a < end]
            if not inside or inside[0] != start:
                inside.insert(0, start)
            for a, b in zip(inside, inside[1:] + [end]):
                chunks.append((a, b, int(thumb), s))
    return chunks, names


def match(layout, chunks, names, src, dst, via=None, log=sys.stderr):
    """{section: [[from, to, shift], ...]} for the sections whose code moved. `via`: the shifts
    of the first ROM's own copy ({section: [[from, to, shift], ...]}) when it is not SoulSilver,
    so that a SoulSilver address is read from it where it has that function."""
    result = {}
    for e in layout['sections']:
        module = e['source'] if e['source'] in ('main', 'itcm') else 'ov%d' % int(e['source'])
        a, b = src.module(module), dst.module(module)
        if not a or not b:
            print(f"{e['name']}: {module} is not in both ROMs", file=log)
            continue
        if a == b and not (via or {}).get(e['name']):
            continue  # (the same code at the same address: nothing moved)
        sec = names.index(e['name'])
        m = Module(module, src, dst)
        own = (via or {}).get(e['name'], [])

        def via_shift(addr):
            for f, t, d in own:
                if f <= addr < t:
                    return d
            return 0

        segs = []
        for start, end, thumb, s in chunks:
            if s != sec:
                continue
            # (Through the first ROM's own shift: the running shift is kept in SoulSilver's terms.)
            d = via_shift(start)
            m.shift -= d
            m.find(start + d, end - start, bool(thumb))
            m.shift += d
            if segs and segs[-1][2] == m.shift:
                segs[-1][1] = end
            else:
                segs.append([start, end, m.shift])
        # Stretches that need no shift are left out.
        segs = [s for s in segs if s[2]]
        if segs:
            result[e['name']] = segs
        print(f"{e['name']}: {m.found} functions found, {m.missed} not, {len(segs)} shifted stretches", file=log)
    return result


def main():
    args, code, game, via = [], None, None, None
    it = iter(sys.argv[1:])
    for a in it:
        if a == '--code':
            code = next(it, None)
        elif a == '--game':
            game = next(it, None)
        elif a == '--via':
            via = json.load(open(next(it)))
        else:
            args.append(a)
    if len(args) != 4:
        sys.exit(__doc__)
    ss_rom, other_rom, gen, out = args
    layout = json.load(open(LAYOUT))
    src, dst = Rom(ss_rom), Rom(other_rom)
    if via:
        if src.code != via['code']:
            sys.exit(f'{ss_rom} is {src.code}, but the --via file is for {via["code"]}')
    elif src.code != 'IPGE':
        print(f'warning: {ss_rom} is {src.code}, not SoulSilver (US, IPGE): the tables are made from it', file=sys.stderr)
    code = code or dst.code
    game = game or GAMES.get(code, code)
    chunks, names = chunks_of_layout(layout) if gen == '-' else chunks_of(gen)
    result = match(layout, chunks, names, src, dst, via['shifts'] if via else None)
    json.dump({'game': game, 'code': code, 'like': 'IPGE', 'shifts': result}, open(out, 'w'), indent=1)
    print(f'{out}: {game} ({code}), {sum(len(v) for v in result.values())} shifted stretches in {len(result)} sections')


if __name__ == '__main__':
    main()
