"""Find map problems that make units take bizarre routes in Victoria 2.
usage: python3 -I adjacency_check.py <mod_dir> <report_dir>   (needs labels.npy from positions_check.py)
The engine derives province neighbours from touching pixels in provinces.bmp (4-neighbour, and the
left/right edges wrap), plus map/adjacencies.csv. So a few stray pixels of province A sitting inside
province B on another continent make A and B neighbours, and pathfinding will happily use that link."""
import os, re, sys, json, csv, collections
import numpy as np
from scipy import ndimage

MOD, REP = sys.argv[1], sys.argv[2]
labels = np.load(os.path.join(REP, 'labels.npy')); H, W = labels.shape
txt = lambda p: open(p, 'rb').read().decode('cp1252', 'replace')
dm = txt(os.path.join(MOD, 'map', 'default.map'))
def ids(key):
    m = re.search(key + r'\s*=\s*\{([^}]*)\}', dm)
    return {int(x) for x in re.findall(r'\d+', m.group(1))} if m else set()
SEA = ids('sea_starts'); LAKE = ids('lakes'); WATER = SEA | LAKE
names, colors = {}, collections.defaultdict(list)
for line in txt(os.path.join(MOD, 'map', 'definition.csv')).splitlines()[1:]:
    p = line.split(';')
    if p and p[0].strip().isdigit() and len(p) > 3:
        names[int(p[0])] = p[4].strip() if len(p) > 4 else ''
        try: colors[(int(p[1]), int(p[2]), int(float(p[3])))].append(int(p[0]))
        except ValueError: pass
nm = lambda i: f'{i} {names.get(i, "?")}'
out = collections.OrderedDict()

# 1. colours on the map that no province owns, and colours shared by two provinces
out['pixels_with_unknown_colour'] = int((labels == 0).sum())
out['duplicate_colours_in_definition'] = [v for v in colors.values() if len(v) > 1]

# 2. adjacency from pixels (4-neighbour, with horizontal wrap)
def pairs(a, b):
    m = a != b
    return set(zip(a[m].tolist(), b[m].tolist()))
adj = collections.defaultdict(set)
for a, b in list(pairs(labels[:, :-1], labels[:, 1:])) + list(pairs(labels[:-1, :], labels[1:, :])):
    adj[a].add(b); adj[b].add(a)
wrap = pairs(labels[:, 0], labels[:, -1])
for a, b in wrap: adj[a].add(b); adj[b].add(a)

# 3. fragments: every connected piece of a province other than its biggest
objs = ndimage.find_objects(labels)
centroid = {}
frag_rows = []
for pid in range(1, len(objs) + 1):
    sl = objs[pid - 1]
    if sl is None: continue
    mask = labels[sl] == pid
    lab, n = ndimage.label(mask)  # 4-connectivity
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    big = int(np.argmax(sizes)) + 1
    rr, cc = np.nonzero(lab == big)
    cy, cx = rr.mean() + sl[0].start, cc.mean() + sl[1].start
    centroid[pid] = (cx, cy)
    if n == 1: continue
    coms = ndimage.center_of_mass(mask, lab, range(1, n + 1))
    for k in range(1, n + 1):
        if k == big: continue
        fy, fx = coms[k - 1][0] + sl[0].start, coms[k - 1][1] + sl[1].start
        # which provinces does this fragment touch?
        fr = lab == k
        ring = ndimage.binary_dilation(fr) & ~fr
        touch = set(np.unique(labels[sl][ring]).tolist()) - {pid}
        dist = float(np.hypot(min(abs(fx - cx), W - abs(fx - cx)), fy - cy))
        frag_rows.append({'province': pid, 'name': names.get(pid, ''), 'water': pid in WATER, 'pixels': int(sizes[k - 1]),
                          'at': [round(fx, 1), round(fy, 1)], 'main_at': [round(cx, 1), round(cy, 1)],
                          'distance_from_main': round(dist, 1), 'touches': sorted(touch)})

def sep(a, b):
    (ax, ay), (bx, by) = centroid[a], centroid[b]
    return float(np.hypot(min(abs(ax - bx), W - abs(ax - bx)), ay - by))

# stray = small fragment well away from the main body, i.e. an island-hop the map author did not intend
strays = [f for f in frag_rows if f['pixels'] <= 200 and f['distance_from_main'] > 40]
out['fragments_total'] = len(frag_rows)
out['stray_fragments'] = len(strays)
out['stray_fragments_list'] = sorted(strays, key=lambda f: -f['distance_from_main'])

# 4. long-distance links created by pixels: neighbours whose bodies are far apart
long_links = []
for a in adj:
    for b in adj[a]:
        if a < b and a in centroid and b in centroid and a and b:
            d = sep(a, b)
            if d > 250:
                long_links.append({'a': nm(a), 'b': nm(b), 'distance': round(d), 'land_land': a not in WATER and b not in WATER})
out['long_pixel_links'] = sorted(long_links, key=lambda x: -x['distance'])

# 5. wrap-around links (left and right map edges touch)
out['wrap_links'] = sorted([nm(a) + ' <-> ' + nm(b) for a, b in wrap if a and b and not (a in WATER and b in WATER)])

# 6. adjacencies.csv
rows = []
for i, line in enumerate(txt(os.path.join(MOD, 'map', 'adjacencies.csv')).splitlines(), 1):
    if not line.strip() or line.startswith('#'): continue
    p = [x.strip() for x in line.split(';')]
    if not p[0].isdigit(): continue
    rows.append((i, p))
bad_adj = []
for i, p in rows:
    try: a, b = int(p[0]), int(p[1])
    except ValueError: bad_adj.append({'line': i, 'issue': 'non-numeric', 'raw': p}); continue
    typ = p[2] if len(p) > 2 else ''
    thr = int(p[3]) if len(p) > 3 and p[3].lstrip('-').isdigit() else 0
    issue = []
    for x in (a, b):
        if x not in centroid: issue.append(f'{x} not on map')
    if thr and thr not in centroid: issue.append(f'through {thr} not on map')
    if typ not in ('sea', 'impassable', 'canal', 'land'): issue.append(f'unknown type "{typ}"')
    if typ == 'sea' and thr and thr not in WATER: issue.append(f'through {thr} is not water')
    if a in centroid and b in centroid:
        d = sep(a, b)
        if typ != 'impassable' and d > 150: issue.append(f'{round(d)} px apart')
        if a in WATER or b in WATER:
            if typ == 'sea': issue.append('sea crossing between a water province')
    if issue: bad_adj.append({'line': i, 'from': nm(a), 'to': nm(b), 'type': typ, 'through': thr, 'issue': '; '.join(issue), 'comment': p[-1] if len(p) > 5 else ''})
out['adjacencies_csv_rows'] = len(rows)
out['adjacencies_csv_problems'] = bad_adj

# 7. land provinces with no land or sea neighbour at all (units can never leave)
isolated = [nm(p) for p in centroid if p not in WATER and not (adj[p] - {0})]
out['isolated_land'] = isolated

json.dump(out, open(os.path.join(REP, 'adjacency_report.json'), 'w'), indent=1)
for k, v in out.items():
    if isinstance(v, list): print(f'{k}: {len(v)}')
    else: print(f'{k}: {v}')
