"""Static audit of a Victoria 2 mod folder. Usage: python3 -I audit.py <mod_dir> <out_dir>"""
import os, re, sys, json, collections

MOD, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
P = lambda *a: os.path.join(MOD, *a)

def raw(path):
    with open(path, 'rb') as f:
        return f.read()

def text(path):
    b = raw(path)
    if b.startswith(b'\xef\xbb\xbf'):
        b = b[3:]
    return b.decode('cp1252', errors='replace')

def strip_comments(s):
    out = []
    for line in s.split('\n'):
        # remove comment, respecting quotes
        q = False; cut = len(line)
        for i, ch in enumerate(line):
            if ch == '"': q = not q
            elif ch == '#' and not q: cut = i; break
        out.append(line[:cut])
    return '\n'.join(out)

TOKEN = re.compile(r'"[^"]*"|[{}=]|[^\s{}="]+')

def tokens(s):
    return TOKEN.findall(strip_comments(s))

def parse(s):
    """Parse Clausewitz script into list of (key, value) where value is str or list."""
    toks = tokens(s); i = 0; n = len(toks)
    def block():
        nonlocal i
        items = []
        while i < n:
            t = toks[i]
            if t == '}':
                i += 1; return items
            if t == '{':  # anonymous block
                i += 1; items.append((None, block())); continue
            if i + 1 < n and toks[i+1] == '=':
                i += 2
                if i < n and toks[i] == '{':
                    i += 1; items.append((t, block()))
                elif i < n:
                    items.append((t, toks[i])); i += 1
            else:
                items.append((None, t)); i += 1
        return items
    return block()

def unq(v):
    return v[1:-1] if isinstance(v, str) and v.startswith('"') else v

report = collections.OrderedDict()
def add(cat, item):
    report.setdefault(cat, []).append(item)

# ---------- 1. encoding / BOM / bracket balance ----------
script_dirs = ['events', 'decisions', 'common', 'history/countries', 'history/units',
               'history/diplomacy', 'history/wars', 'common/countries', 'inventions', 'technologies']
for d in script_dirs:
    full = P(d)
    if not os.path.isdir(full): continue
    for fn in sorted(os.listdir(full)):
        fp = os.path.join(full, fn)
        if not os.path.isfile(fp) or not fn.endswith('.txt'): continue
        b = raw(fp)
        rel = os.path.relpath(fp, MOD)
        if b.startswith(b'\xef\xbb\xbf'):
            add('utf8_bom', rel)
        if b.startswith(b'\xff\xfe') or b.startswith(b'\xfe\xff') or b.count(b'\x00') > 10:
            add('utf16_or_nul', rel)
        try:
            b.decode('ascii')
        except UnicodeDecodeError:
            try:
                b.decode('utf-8'); add('utf8_non_ascii(chars show garbled in-game)', rel)
            except UnicodeDecodeError:
                pass
        toks = tokens(text(fp))
        depth = 0; minline = None
        for t in toks:
            if t == '{': depth += 1
            elif t == '}':
                depth -= 1
                if depth < 0 and minline is None: minline = 'extra closing brace'
        if depth != 0 or minline:
            add('bracket_mismatch', f'{rel}: net {depth:+d}' + (f' ({minline})' if minline else ''))

# ---------- 2. localisation keys ----------
loc = {}
locdup = collections.defaultdict(list)
for fn in sorted(os.listdir(P('localisation'))):
    if not fn.endswith('.csv'): continue
    for ln, line in enumerate(text(P('localisation', fn)).split('\n'), 1):
        if not line.strip() or line.startswith('#'): continue
        parts = line.split(';')
        k = parts[0].strip()
        if not k: continue
        kl = k.lower()
        if kl in loc:
            locdup[kl].append(f'{fn}:{ln}')
        else:
            loc[kl] = (fn, ln, parts[1] if len(parts) > 1 else '')
        if len(parts) < 2 or not parts[1].strip():
            add('loc_empty_english', f'{fn}:{ln} {k}')
def has(k): return k.lower() in loc
def missing(cat, k, where):
    if not has(k): add(cat, f'{k}  <- {where}')

# ---------- 3. countries ----------
ctext = text(P('common', 'countries.txt'))
tags = collections.OrderedDict()
for k, v in parse(ctext):
    if k is None: continue
    if k in ('dynamic_tags',): continue
    if k in tags: add('country_tag_duplicate', k)
    tags[k] = unq(v)
hist = {}
for fn in os.listdir(P('history', 'countries')):
    m = re.match(r'([A-Z0-9]{3})\s*-', fn)
    if m: hist.setdefault(m.group(1), []).append(fn)
for t, l in hist.items():
    if len(l) > 1: add('history_file_duplicate_tag', f'{t}: {l}')
flags = {f.lower() for f in os.listdir(P('gfx', 'flags'))}
govs = ['', '_communist', '_fascist', '_monarchy', '_republic']
partynames = {}
for tag, cf in tags.items():
    if tag == 'REB': continue
    cpath = P('common', cf)
    if not os.path.exists(cpath):
        # case-insensitive check (Windows is case-insensitive)
        d, b = os.path.split(cpath)
        if os.path.isdir(d) and b.lower() in {x.lower() for x in os.listdir(d)}:
            pass
        else:
            add('country_file_missing', f'{tag} -> common/{cf}');
    else:
        for k, v in parse(text(cpath)):
            if k == 'party' and isinstance(v, list):
                for pk, pv in v:
                    if pk == 'name': partynames.setdefault(unq(pv), tag)
    if tag not in hist and not tag.startswith(('D0', 'D1')):
        add('country_history_missing', tag)
    missing('loc_country_name', tag, 'countries.txt')
    missing('loc_country_adj', tag + '_ADJ', 'countries.txt')
    for g in govs:
        if f'{tag.lower()}{g}.tga' not in flags:
            add('flag_missing', f'{tag}{g}.tga')
for pn, tag in partynames.items():
    missing('loc_party', pn, tag)

# ---------- 4. decisions ----------
dec_keys = collections.defaultdict(list)
for fn in sorted(os.listdir(P('decisions'))):
    if not fn.endswith('.txt'): continue
    for k, v in parse(text(P('decisions', fn))):
        if k == 'political_decisions' and isinstance(v, list):
            for dk, dv in v:
                if dk is None or not isinstance(dv, list): continue
                dec_keys[dk].append(fn)
for dk, fns in dec_keys.items():
    if len(fns) > 1: add('decision_duplicate_key', f'{dk}: {fns}')
    missing('loc_decision_title', dk + '_title', fns[0])
    missing('loc_decision_desc', dk + '_desc', fns[0])

# ---------- 5. events ----------
ev_ids = collections.defaultdict(list)
ev_calls = []
LOCKEY = re.compile(r'^[A-Za-z0-9_.\-]+$')
def walk_calls(items, fn):
    for k, v in items:
        if k in ('country_event', 'province_event') :
            if isinstance(v, str): ev_calls.append((v, fn))
            elif isinstance(v, list):
                for kk, vv in v:
                    if kk == 'id': ev_calls.append((vv, fn))
        if isinstance(v, list): walk_calls(v, fn)
for fn in sorted(os.listdir(P('events'))):
    if not fn.endswith('.txt'): continue
    items = parse(text(P('events', fn)))
    for k, v in items:
        if k in ('country_event', 'province_event') and isinstance(v, list):
            d = {kk: vv for kk, vv in v if kk}
            eid = d.get('id')
            if eid is None: add('event_without_id', fn); continue
            ev_ids[eid].append(fn)
            for fld in ('title', 'desc'):
                val = d.get(fld)
                if isinstance(val, str):
                    u = unq(val)
                    if LOCKEY.match(u) and not has(u):
                        add('loc_event_text', f'{u}  <- {fn} id {eid} ({fld})')
            for kk, vv in v:
                if kk == 'option' and isinstance(vv, list):
                    for ok, ov in vv:
                        if ok == 'name' and isinstance(ov, str):
                            u = unq(ov)
                            if LOCKEY.match(u) and not has(u):
                                add('loc_event_option', f'{u}  <- {fn} id {eid}')
    walk_calls(items, fn)
for fn in sorted(os.listdir(P('decisions'))):
    if fn.endswith('.txt'): walk_calls(parse(text(P('decisions', fn))), 'decisions/' + fn)
for f in ('on_actions.txt',):
    if os.path.exists(P('common', f)): walk_calls(parse(text(P('common', f))), 'common/' + f)
for eid, fns in ev_ids.items():
    if len(fns) > 1: add('event_id_duplicate', f'{eid}: {fns}')
seen = set()
for eid, fn in ev_calls:
    if eid not in ev_ids and (eid, fn) not in seen:
        seen.add((eid, fn)); add('event_called_but_undefined', f'{eid}  <- {fn}')

# ---------- write ----------
with open(os.path.join(OUT, 'audit.json'), 'w') as f:
    json.dump(report, f, indent=1)
with open(os.path.join(OUT, 'audit.txt'), 'w') as f:
    for cat, items in report.items():
        f.write(f'\n===== {cat} ({len(items)}) =====\n')
        for it in items: f.write(it + '\n')
print(f'tags={len(tags)} decisions={len(dec_keys)} events={len(ev_ids)} lockeys={len(loc)}')
for cat, items in report.items():
    print(f'{len(items):6d}  {cat}')
