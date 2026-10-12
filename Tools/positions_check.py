"""Check Victoria 2 map/positions.txt against provinces.bmp.
Coordinates: x = column, y = row of the array PIL returns for provinces.bmp (verified on Sitka).
usage: python3 -I positions_check.py <mod_dir> <out_dir>
Writes positions_report.json + a per-province summary; caches the label map as labels.npy."""
import os, re, sys, json, collections
import numpy as np
from PIL import Image
from scipy import ndimage

MOD, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
MAP = os.path.join(MOD, 'map')
Image.MAX_IMAGE_PIXELS = None

def text(p):
    return open(p, 'rb').read().decode('cp1252', 'replace')

# --- definitions -------------------------------------------------------------
defs = {}
for line in text(os.path.join(MAP, 'definition.csv')).splitlines()[1:]:
    parts = line.split(';')
    if len(parts) < 4 or not parts[0].strip().isdigit():
        continue
    try:
        pid, r, g, b = int(parts[0]), int(parts[1]), int(parts[2]), int(float(parts[3]))
    except ValueError:
        continue
    defs[pid] = {'rgb': (r, g, b), 'name': parts[4].strip() if len(parts) > 4 else ''}

dm = text(os.path.join(MAP, 'default.map'))
def id_block(key):
    m = re.search(key + r'\s*=\s*\{([^}]*)\}', dm)
    return {int(x) for x in re.findall(r'\d+', m.group(1))} if m else set()
sea = id_block('sea_starts')
lakes = id_block('lakes')

# --- label map ---------------------------------------------------------------
cache = os.path.join(OUT, 'labels.npy')
if os.path.exists(cache):
    labels = np.load(cache)
else:
    img = np.asarray(Image.open(os.path.join(MAP, 'provinces.bmp')).convert('RGB'), dtype=np.uint32)
    key = (img[..., 0] << 16) | (img[..., 1] << 8) | img[..., 2]
    lut = {(r << 16) | (g << 8) | b: pid for pid, d in defs.items() for (r, g, b) in [d['rgb']]}
    uniq, inv = np.unique(key, return_inverse=True)
    mapped = np.array([lut.get(int(u), 0) for u in uniq], dtype=np.int32)
    labels = mapped[inv].reshape(key.shape)
    np.save(cache, labels)
H, W = labels.shape

# --- positions.txt -----------------------------------------------------------
TOK = re.compile(r'"[^"]*"|[{}=]|[^\s{}="]+')
def parse(s):
    s = re.sub(r'#[^\n]*', '', s)
    toks = TOK.findall(s); i = 0
    def block():
        nonlocal i
        out = []
        while i < len(toks):
            t = toks[i]
            if t == '}': i += 1; return out
            if i + 1 < len(toks) and toks[i + 1] == '=':
                i += 2
                if toks[i] == '{': i += 1; out.append((t, block()))
                else: out.append((t, toks[i])); i += 1
            elif t == '{': i += 1; out.append((None, block()))
            else: out.append((None, t)); i += 1
        return out
    return block()

pos_items = parse(text(os.path.join(MAP, 'positions.txt')))
positions = collections.defaultdict(list)
for k, v in pos_items:
    if k and k.isdigit(): positions[int(k)].append(v)

def xy(block):
    """Return list of (x,y) from a block that may hold one or many x/y pairs."""
    xs = [float(v) for k, v in block if k == 'x']; ys = [float(v) for k, v in block if k == 'y']
    return list(zip(xs, ys))

def flatten(block):
    pts = {}
    for k, v in block:
        if not isinstance(v, list): continue
        if k == 'building_position':
            for bk, bv in v:
                if isinstance(bv, list): pts['building_position.' + bk] = xy(bv)
        elif k in ('text_position', 'unit', 'town', 'city', 'factory', 'building_construction', 'military_construction', 'position'):
            pts[k] = xy(v)
    scal = {k: float(v) for k, v in block if k in ('text_rotation', 'text_scale') and not isinstance(v, list)}
    return pts, scal

def label_at(x, y):
    c, r = int(round(x)), int(round(y))
    if 0 <= r < H and 0 <= c < W: return int(labels[r, c])
    return -1

# --- province geometry -------------------------------------------------------
objs = ndimage.find_objects(labels)
present = {pid for pid in defs if pid - 1 < len(objs) and objs[pid - 1] is not None}
geo = {}
for pid in present:
    sl = objs[pid - 1]
    mask = labels[sl] == pid
    rows, cols = np.nonzero(mask)
    geo[pid] = {'pixels': int(mask.sum()), 'bbox': [int(sl[1].start), int(sl[0].start), int(sl[1].stop), int(sl[0].stop)],
                'centroid': [float(cols.mean() + sl[1].start), float(rows.mean() + sl[0].start)]}

def dist_to_province(pid, x, y):
    """Pixel distance from (x,y) to the nearest pixel of province pid (0 when inside)."""
    if label_at(x, y) == pid: return 0.0
    sl = objs[pid - 1]
    rows, cols = np.nonzero(labels[sl] == pid)
    rows = rows + sl[0].start; cols = cols + sl[1].start
    r, c = y, x
    return float(np.sqrt(((rows - r) ** 2 + (cols - c) ** 2).min()))

# --- checks --------------------------------------------------------------------
issues = collections.defaultdict(list)
per_prov = {}
for pid in sorted(defs):
    is_water = pid in sea or pid in lakes
    if pid not in present:
        if pid in positions: issues['positions_for_province_not_on_map'].append(pid)
        continue
    if pid not in positions:
        issues['no_positions_entry'].append(pid); continue
    if len(positions[pid]) > 1:
        issues['duplicate_positions_entry'].append(pid)
    pts, scal = flatten(positions[pid][-1])   # the engine keeps the last block
    bad = {}
    expected = ['text_position'] if is_water else ['text_position', 'unit', 'city', 'factory', 'building_construction', 'military_construction', 'building_position.fort', 'building_position.railroad']
    for k in expected:
        if k not in pts or not pts[k]:
            if k != 'city': bad[k] = 'missing'
    for k, lst in pts.items():
        for (x, y) in lst:
            d = dist_to_province(pid, x, y)
            limit = 25 if k == 'building_position.naval_base' else 0
            if d > limit:
                bad[k] = round(d, 1)
    if bad:
        per_prov[pid] = {'name': defs[pid]['name'], 'water': is_water, 'pixels': geo[pid]['pixels'], 'bad': bad}

cat = collections.Counter()
for pid, p in per_prov.items():
    for k, v in p['bad'].items():
        cat[(k, 'missing' if v == 'missing' else 'outside')] += 1
summary = {
    'map_size': [W, H], 'definitions': len(defs), 'provinces_on_map': len(present),
    'sea_or_lake': len(sea | lakes), 'positions_entries': len(positions),
    'provinces_with_problems': len(per_prov),
    'land_with_problems': sum(1 for p in per_prov.values() if not p['water']),
    'problem_counts': {f'{k} {t}': n for (k, t), n in sorted(cat.items(), key=lambda kv: -kv[1])},
    'other': {k: v for k, v in issues.items()},
}
json.dump({'summary': summary, 'provinces': per_prov, 'geo': geo}, open(os.path.join(OUT, 'positions_report.json'), 'w'))
print(json.dumps(summary, indent=1)[:4000])
