"""Fix misplaced points in Victoria 2 map/positions.txt using provinces.bmp.
usage: python3 -I positions_fix.py <mod_dir> <report_dir> [--fill-missing]
Needs positions_check.py to have run first (uses its labels.npy).
- Points more than TOL px outside their province are moved to the nearest spot inside it
  (at least a few px from the border). Units and labels that are far off go to the province's
  most interior point instead.
- Naval bases more than NAVAL_TOL px from their province move to the nearest sea pixel on its coast.
- Empty duplicate blocks ("3352 = {}") are removed; a province with no block gets one.
- With --fill-missing, land provinces also get unit/text/factory/construction/fort/railroad
  points where the block has none.
Only blocks that change are rewritten; every other byte of the file is kept."""
import os, re, sys, json
import numpy as np
from scipy import ndimage

MOD, REP = sys.argv[1], sys.argv[2]
FILL = '--fill-missing' in sys.argv
TOL, NAVAL_TOL, FAR = 3.0, 25.0, 10.0
P = os.path.join(MOD, 'map', 'positions.txt')
raw = open(P, 'rb').read().decode('cp1252')
labels = np.load(os.path.join(REP, 'labels.npy'))
H, W = labels.shape
dm = open(os.path.join(MOD, 'map', 'default.map'), 'rb').read().decode('cp1252')
def ids(key):
    m = re.search(key + r'\s*=\s*\{([^}]*)\}', dm)
    return {int(x) for x in re.findall(r'\d+', m.group(1))} if m else set()
WATER = ids('sea_starts') | ids('lakes')
objs = ndimage.find_objects(labels)
names = {}
for line in open(os.path.join(MOD, 'map', 'definition.csv'), 'rb').read().decode('cp1252').splitlines()[1:]:
    p = line.split(';')
    if p and p[0].strip().isdigit() and len(p) > 4: names[int(p[0])] = p[4].strip()

# ---- block parsing with spans ----------------------------------------------
TOK = re.compile(r'#[^\n]*|"[^"]*"|[{}=]|[^\s{}="#]+')
def parse_block(s):
    toks = [t for t in TOK.findall(s) if not t.startswith('#')]; i = 0
    def block():
        nonlocal i
        out = []
        while i < len(toks):
            t = toks[i]
            if t == '}': i += 1; return out
            if i + 1 < len(toks) and toks[i + 1] == '=':
                i += 2
                if toks[i] == '{': i += 1; out.append([t, block()])
                else: out.append([t, toks[i]]); i += 1
            else: i += 1
        return out
    return block()

def find_blocks(s):
    """Yield (pid, start, end) for top-level 'N = { ... }' blocks (end is exclusive)."""
    out = []; i = 0; n = len(s)
    for m in re.finditer(r'(?m)^(\d+)\s*=\s*\{', s):
        if m.start() < i: continue
        d = 0; j = m.end() - 1
        while j < n:
            c = s[j]
            if c == '#':
                j = s.find('\n', j); j = n if j < 0 else j; continue
            if c == '{': d += 1
            elif c == '}':
                d -= 1
                if d == 0: break
            j += 1
        out.append((int(m.group(1)), m.start(), j + 1)); i = j + 1
    return out

def fmt(v):
    return f'{v:.6f}'
def emit(pid, items):
    lines = [f'{pid} = {{']
    def rec(items, ind):
        for k, v in items:
            if isinstance(v, list):
                lines.append(' ' * ind + f'{k} = {{')
                rec(v, ind + 4)
                lines.append(' ' * ind + '}')
                lines.append('')
            else:
                lines.append(' ' * ind + f'{k} = {v}')
    rec(items, 4)
    lines.append('}')
    return '\n'.join(lines)

# ---- geometry helpers ------------------------------------------------------
cache = {}
def geom(pid):
    if pid in cache: return cache[pid]
    sl = objs[pid - 1]
    pad = 2
    r0, r1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, H)
    c0, c1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, W)
    mask = labels[r0:r1, c0:c1] == pid
    lab, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    main = lab == (int(np.argmax(sizes)) + 1)
    dist = ndimage.distance_transform_edt(mask)
    dmain = np.where(main, dist, 0)
    pr, pc = np.unravel_index(int(np.argmax(dmain)), dmain.shape)
    rows, cols = np.nonzero(main)
    cy, cx = rows.mean(), cols.mean()
    g = dict(r0=r0, c0=c0, mask=mask, dist=dist, main=main, pole=(pc + c0 + 0.5, pr + r0 + 0.5),
             maxd=float(dmain.max()), centroid=(cx + c0 + 0.5, cy + r0 + 0.5))
    cache[pid] = g; return g

def inside(pid, x, y):
    r, c = int(y), int(x)
    return 0 <= r < H and 0 <= c < W and labels[r, c] == pid

def dist_out(pid, x, y):
    if inside(pid, x, y): return 0.0
    g = geom(pid); rows, cols = np.nonzero(g['mask'])
    return float(np.sqrt(((rows + g['r0'] + 0.5 - y) ** 2 + (cols + g['c0'] + 0.5 - x) ** 2).min()))

def snap_inside(pid, x, y, used):
    """Nearest pixel of the province's main part that is >= min(3, maxd/2) px from its border,
    avoiding exact reuse of points already placed in this block."""
    g = geom(pid); t = min(3.0, g['maxd'] / 2)
    cand = np.argwhere(g['main'] & (g['dist'] >= t))
    if not len(cand): cand = np.argwhere(g['main'])
    py, px = cand[:, 0] + g['r0'] + 0.5, cand[:, 1] + g['c0'] + 0.5
    d = (px - x) ** 2 + (py - y) ** 2
    for k in np.argsort(d)[:200]:
        pt = (round(float(px[k]), 6), round(float(py[k]), 6))
        if pt not in used: return pt
    k = int(np.argmin(d)); return (float(px[k]), float(py[k]))

def label_point(pid):
    g = geom(pid); cx, cy = g['centroid']
    r, c = int(cy) - g['r0'], int(cx) - g['c0']
    if 0 <= r < g['main'].shape[0] and 0 <= c < g['main'].shape[1] and g['main'][r, c] and g['dist'][r, c] >= min(3, g['maxd'] / 2):
        return (cx, cy)
    return g['pole']

def coast_point(pid, x, y):
    g = geom(pid)
    r0, c0 = max(g['r0'] - 6, 0), max(g['c0'] - 6, 0)
    r1, c1 = min(g['r0'] + g['mask'].shape[0] + 6, H), min(g['c0'] + g['mask'].shape[1] + 6, W)
    sub = labels[r0:r1, c0:c1]
    near = ndimage.binary_dilation(sub == pid, iterations=4)
    water = np.isin(sub, list(WATER))
    cand = np.argwhere(near & water)
    if not len(cand): return None
    py, px = cand[:, 0] + r0 + 0.5, cand[:, 1] + c0 + 0.5
    k = int(np.argmin((px - x) ** 2 + (py - y) ** 2))
    return (float(px[k]), float(py[k]))

def get_xy(v):
    xs = [i for i, (k, _) in enumerate(v) if k == 'x']; ys = [i for i, (k, _) in enumerate(v) if k == 'y']
    return [(xs[n], ys[n]) for n in range(min(len(xs), len(ys)))]

# ---- main ------------------------------------------------------------------
blocks = find_blocks(raw)
from collections import Counter as _C
counts = _C(p for p, _, _ in blocks)
seen = {}
edits = []   # (start, end, replacement)
log = []
for pid, s, e in blocks:
    body = raw[s:e]
    if re.fullmatch(r'\d+\s*=\s*\{\s*\}', body) and counts[pid] > 1:
        edits.append((s, e, None)); log.append(('removed empty duplicate block', pid, '')); continue
    if pid > len(objs) or objs[pid - 1] is None: continue
    items = parse_block(body[body.index('{') + 1:])
    water = pid in WATER
    changed = []
    used = set()
    def fix_point(key, holder, idxs, kind):
        (ix, iy) = idxs
        x, y = float(holder[ix][1]), float(holder[iy][1])
        d = dist_out(pid, x, y)
        if kind == 'naval':
            if d <= NAVAL_TOL: return
            np_ = coast_point(pid, x, y)
            if not np_: return
        elif d <= TOL:
            used.add((x, y)); return
        elif kind in ('unit', 'text') and d > FAR:
            np_ = label_point(pid) if kind == 'text' else geom(pid)['pole']
        else:
            np_ = snap_inside(pid, x, y, used)
        used.add(np_)
        holder[ix][1], holder[iy][1] = fmt(np_[0]), fmt(np_[1])
        changed.append(f'{key} {d:.0f}px off')
    present_keys = set()
    for it in items:
        k, v = it
        if not isinstance(v, list): continue
        present_keys.add(k)
        if k == 'building_position':
            for bit in v:
                bk, bv = bit
                if isinstance(bv, list):
                    present_keys.add('building_position.' + bk)
                    for idxs in get_xy(bv):
                        fix_point('building_position.' + bk, bv, idxs, 'naval' if bk == 'naval_base' else 'building')
        elif k in ('text_position', 'unit', 'town', 'city', 'factory', 'building_construction', 'military_construction'):
            for idxs in get_xy(v):
                fix_point(k, v, idxs, 'text' if k == 'text_position' else 'unit' if k == 'unit' else 'point')
    if FILL and not water:
        def add(key, pt):
            items.insert(0 if key == 'text_position' else len(items), [key, [['x', fmt(pt[0])], ['y', fmt(pt[1])]]])
            changed.append(f'{key} added')
        if 'text_position' not in present_keys: add('text_position', label_point(pid))
        if 'unit' not in present_keys: add('unit', geom(pid)['pole'])
        for key in ('factory', 'building_construction', 'military_construction'):
            if key not in present_keys:
                g = geom(pid); add(key, snap_inside(pid, g['pole'][0] + 4, g['pole'][1] + 4, used))
    if changed:
        edits.append((s, e, emit(pid, items)))
        log.append(('moved', pid, '; '.join(changed)))

# provinces on the map with no block at all
have = {p for p, _, _ in blocks}
appended = []
for pid in range(1, len(objs) + 1):
    if objs[pid - 1] is None or pid in have or pid not in names: continue
    g = geom(pid); t = label_point(pid); u = g['pole']
    items = [['text_position', [['x', fmt(t[0])], ['y', fmt(t[1])]]], ['text_rotation', '0'], ['text_scale', '1'],
             ['unit', [['x', fmt(u[0])], ['y', fmt(u[1])]]]]
    appended.append(f'# {names[pid]}\n' + emit(pid, items))
    log.append(('added block', pid, names.get(pid, '')))

out = []; last = 0
for s, e, rep in sorted(edits):
    out.append(raw[last:s])
    if rep is not None: out.append(rep)
    else:
        # drop the empty block and the whitespace after it
        while e < len(raw) and raw[e] in ' \t': e += 1
        if e < len(raw) and raw[e] == '\n': e += 1
    last = e
out.append(raw[last:])
new = ''.join(out)
if appended: new = new.rstrip('\n') + '\n' + '\n'.join(appended) + '\n'
open(P, 'wb').write(new.encode('cp1252'))
json.dump(log, open(os.path.join(REP, 'positions_fix_log.json'), 'w'), indent=0)
from collections import Counter
print(Counter(a for a, _, _ in log)); print(len(new) - len(raw), 'bytes delta')
