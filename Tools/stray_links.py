"""Which neighbour links exist ONLY because of a detached piece of a province (or unknown-colour pixels)?
usage: python3 -I stray_links.py <mod_dir> <report_dir> [--fix]
With --fix, provinces.bmp is cleaned in place (header and row layout kept byte-for-byte):
  every detached piece that creates a link the province's other parts don't have is
     repainted with the province that surrounds it (only pieces <= MAX_FIX px).
A piece's 'host' is the most common province on its outer ring."""
import os, re, sys, json, collections, struct
import numpy as np
from scipy import ndimage

MOD, REP = sys.argv[1], sys.argv[2]
FIX = '--fix' in sys.argv
MAX_FIX = 400
BMP = os.path.join(MOD, 'map', 'provinces.bmp')
labels = np.load(os.path.join(REP, 'labels.npy')).copy(); H, W = labels.shape
txt = lambda p: open(p, 'rb').read().decode('cp1252', 'replace')
dm = txt(os.path.join(MOD, 'map', 'default.map'))
def ids(key):
    m = re.search(key + r'\s*=\s*\{([^}]*)\}', dm)
    return {int(x) for x in re.findall(r'\d+', m.group(1))} if m else set()
WATER = ids('sea_starts') | ids('lakes')
names, rgb = {}, {}
for line in txt(os.path.join(MOD, 'map', 'definition.csv')).splitlines()[1:]:
    p = line.split(';')
    if p and p[0].strip().isdigit() and len(p) > 3:
        try: rgb[int(p[0])] = (int(p[1]), int(p[2]), int(float(p[3])))
        except ValueError: continue
        names[int(p[0])] = p[4].strip() if len(p) > 4 else ''
nm = lambda i: f'{i} {names.get(i, "?")}' + (' [water]' if i in WATER else '')
S8 = np.ones((3, 3), bool)

# Pixels in colours with no province (lakes, as in vanilla's 1,222,200) are left alone.
unknown_before = int((labels == 0).sum()); unknown_fixed = 0

# ---- step 2: detached pieces that add links --------------------------------
def neighbours_of(mask_full_sl, sl):
    ring = ndimage.binary_dilation(mask_full_sl, structure=np.array([[0,1,0],[1,1,1],[0,1,0]])) & ~mask_full_sl
    return collections.Counter(labels[sl][ring].tolist())

objs = ndimage.find_objects(labels)
pieces = []
for pid in range(1, len(objs) + 1):
    sl0 = objs[pid - 1]
    if sl0 is None: continue
    sl = (slice(max(sl0[0].start - 1, 0), min(sl0[0].stop + 1, H)), slice(max(sl0[1].start - 1, 0), min(sl0[1].stop + 1, W)))
    mask = labels[sl] == pid
    lab, n = ndimage.label(mask)
    if n == 1: continue
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    nb = [neighbours_of(lab == k, sl) for k in range(1, n + 1)]
    for k in range(1, n + 1):
        others = collections.Counter()
        for j in range(1, n + 1):
            if j != k: others.update(nb[j - 1])
        new_links = set(nb[k - 1]) - set(others) - {pid, 0}
        if not new_links or sizes[k - 1] >= sizes.max(): continue
        rr, cc = np.nonzero(lab == k)
        host = nb[k - 1].most_common(1)[0][0]
        pieces.append({'province': pid, 'pixels': int(sizes[k - 1]), 'x': int(cc.mean() + sl[1].start), 'y': int(rr.mean() + sl[0].start),
                       'host': int(host), 'new_links': sorted(int(x) for x in new_links),
                       'rows': (rr + sl[0].start).tolist(), 'cols': (cc + sl[1].start).tolist()})

def describe(p):
    return {'category': p.get('category', ''), 'province': nm(p['province']), 'pixels': p['pixels'], 'at': [p['x'], p['y']], 'inside': nm(p['host']),
            'repainted_as': ('lake (no province)' if p.get('target') == 0 else nm(p['target'])) if p.get('category', '').startswith('fix') else 'unchanged',
            'creates_links_to': [nm(x) for x in p['new_links']]}

def category(p):
    land, host_land = p['province'] not in WATER, p['host'] not in WATER and p['host'] != 0
    if p['host'] == 0: return 'review: piece sits in a lake/undefined area'
    if p['pixels'] <= 5: return 'fix: pixel noise'
    if land and host_land and p['pixels'] <= MAX_FIX: return 'fix: land piece inside another land province'
    if not land and host_land and p['pixels'] <= 200: return 'fix: sea/lake piece stranded inside land'
    if not land and not host_land and p['pixels'] <= 200: return 'fix: sea piece inside another sea zone'
    if land and not host_land: return 'review: island belonging to a province elsewhere'
    return 'review: large piece'
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
TERRAIN = np.asarray(Image.open(os.path.join(MOD, 'map', 'terrain.bmp')))   # index 254 = water
LAKE_RGB = (1, 222, 200)   # the colour vanilla uses for lakes that are not provinces
for p in pieces:
    p['category'] = category(p)
    p['target'] = p['host']
    if p['category'] == 'fix: sea/lake piece stranded inside land':
        water_share = float((TERRAIN[p['rows'], p['cols']] == 254).mean())
        p['water_share'] = round(water_share, 2)
        if water_share >= 0.7:
            p['target'] = 0
            p['category'] = 'fix: real lake wrongly given a sea/lake province id'
fixable = [p for p in pieces if p['category'].startswith('fix')]
report = {
    'unknown_colour_pixels': unknown_before, 'unknown_colour_pixels_reassigned': unknown_fixed,
    'pieces_creating_extra_links': len(pieces), 'fixable': len(fixable),
    'land_land_links_from_pieces': sum(1 for p in pieces for x in p['new_links'] if p['province'] not in WATER and x not in WATER),
    'water_land_links_from_pieces': sum(1 for p in pieces for x in p['new_links'] if (p['province'] in WATER) != (x in WATER)),
    'by_category': dict(collections.Counter(p['category'] for p in pieces)),
    'largest': [describe(p) for p in sorted(pieces, key=lambda p: -p['pixels'])[:15]],
    'all': [describe(p) for p in sorted(pieces, key=lambda p: (p['province'], -p['pixels']))],
}
json.dump(report, open(os.path.join(REP, 'stray_links.json'), 'w'), indent=1)
print({k: v for k, v in report.items() if k not in ('largest', 'all')})

if FIX:
    for p in fixable:
        labels[p['rows'], p['cols']] = p['target']
    raw = bytearray(open(BMP, 'rb').read())
    off = struct.unpack('<I', raw[10:14])[0]
    w, h = struct.unpack('<ii', raw[18:26]); bpp = struct.unpack('<H', raw[28:30])[0]
    assert (w, abs(h), bpp) == (W, H, 24)
    stride = (W * 3 + 3) & ~3
    orig = np.load(os.path.join(REP, 'labels.npy'))
    rr, cc = np.nonzero(labels != orig)
    for r, c in zip(rr.tolist(), cc.tolist()):
        stored = (H - 1 - r) if h > 0 else r
        o = off + stored * stride + c * 3
        R, G, B = rgb.get(int(labels[r, c]), LAKE_RGB) if labels[r, c] else LAKE_RGB
        raw[o:o + 3] = bytes((B, G, R))
    open(BMP, 'wb').write(bytes(raw))
    print('repainted pixels:', len(rr))
