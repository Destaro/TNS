"""Profile TNS for performance/MP-relevant patterns. python3 -I profile.py <struggle> <vanilla_root>"""
import os, re, sys, collections, json
sys.path.insert(0, os.path.dirname(__file__))
M, V = sys.argv[1], sys.argv[2]
exec(open(os.path.join(os.path.dirname(__file__), 'audit_lib.py')).read())

out = collections.OrderedDict()
CHEAP = {'tag', 'has_country_flag', 'has_global_flag', 'is_greater_power', 'ai', 'year', 'exists', 'has_country_modifier',
         'civilized', 'war', 'NOT', 'is_vassal', 'owns', 'primary_culture', 'government', 'is_culture_group', 'capital'}
LOOPS = {'any_pop', 'any_owned', 'any_owned_province', 'any_country', 'any_neighbor_country', 'any_core', 'any_state',
         'any_greater_power', 'any_sphere_member', 'any_substate', 'every_province', 'all_core'}

def keys_deep(items, acc):
    for k, v in items:
        if k: acc[k] += 1
        if isinstance(v, list): keys_deep(v, acc)

mtth = []; trig_only = 0; prov_mtth = 0
for fn in sorted(os.listdir(os.path.join(M, 'events'))):
    if not fn.endswith('.txt'): continue
    for k, v in parse(text(os.path.join(M, 'events', fn))):
        if k not in ('country_event', 'province_event') or not isinstance(v, list): continue
        d = dict((kk, vv) for kk, vv in v if kk)
        if d.get('is_triggered_only') == 'yes': trig_only += 1; continue
        trig = d.get('trigger', [])
        if not isinstance(trig, list): trig = []
        first = next((kk for kk, vv in trig if kk), None)
        acc = collections.Counter(); keys_deep(trig, acc)
        loops = sorted(set(acc) & LOOPS)
        mtth.append({'file': fn, 'id': d.get('id'), 'type': k, 'first': first, 'loops': loops,
                     'once': d.get('fire_only_once') == 'yes', 'n_conditions': sum(acc.values())})
        if k == 'province_event': prov_mtth += 1
out['events_triggered_only'] = trig_only
out['events_polled(MTTH)'] = len(mtth)
out['province_events_polled'] = prov_mtth
out['polled_events_no_trigger_block'] = sum(1 for e in mtth if e['first'] is None)
out['polled_events_first_condition_not_cheap'] = sum(1 for e in mtth if e['first'] and e['first'] not in CHEAP)
out['polled_events_with_loop_scopes'] = sum(1 for e in mtth if e['loops'])
out['polled_events_with_loops_by_scope'] = dict(collections.Counter(l for e in mtth for l in e['loops']).most_common())
out['worst_polled_events'] = sorted([e for e in mtth if e['loops']], key=lambda e: -e['n_conditions'])[:15]
out['polled_events_by_file_top'] = collections.Counter(e['file'] for e in mtth).most_common(15)

# decisions
dec = []
for fn in sorted(os.listdir(os.path.join(M, 'decisions'))):
    if not fn.endswith('.txt'): continue
    for k, v in parse(text(os.path.join(M, 'decisions', fn))):
        if k != 'political_decisions' or not isinstance(v, list): continue
        for dk, dv in v:
            if not dk or not isinstance(dv, list): continue
            d = dict((kk, vv) for kk, vv in dv if kk)
            pot = d.get('potential', [])
            if not isinstance(pot, list): pot = []
            acc = collections.Counter(); keys_deep(pot, acc)
            first = next((kk for kk, vv in pot if kk), None)
            aiw = d.get('ai_will_do')
            dec.append({'file': fn, 'key': dk, 'first': first, 'loops': sorted(set(acc) & LOOPS),
                        'has_tag_or_flag': bool(set(acc) & {'tag', 'has_country_flag', 'has_global_flag', 'ai', 'primary_culture', 'is_culture_group'}),
                        'ai0': isinstance(aiw, list) and any(kk == 'factor' and vv == '0' for kk, vv in aiw)})
out['decisions_total'] = len(dec)
out['decisions_potential_without_tag_flag_ai_or_culture'] = sum(1 for d in dec if not d['has_tag_or_flag'])
out['decisions_potential_with_loop_scopes'] = sum(1 for d in dec if d['loops'])
out['decision_files_top'] = collections.Counter(d['file'] for d in dec).most_common(10)
out['sample_unfiltered_decisions'] = [f"{d['file']}:{d['key']}" for d in dec if not d['has_tag_or_flag']][:25]

# pops
pops_n = 0; pops_size = 0
pd = os.path.join(M, 'history', 'pops', '1836.1.1')
for root, _, files in os.walk(pd):
    for fn in files:
        if not fn.endswith('.txt'): continue
        t = text(os.path.join(root, fn))
        sizes = re.findall(r'\bsize\s*=\s*(\d+)', t)
        pops_n += len(sizes); pops_size += sum(int(s) for s in sizes)
out['start_pops_count'] = pops_n
out['start_pops_total_size'] = pops_size
cult = len(re.findall(r'^\t\w+\s*=\s*\{\s*$', text(os.path.join(M, 'common', 'cultures.txt')), re.M))
out['cultures_approx'] = cult

# provinces
dm = text(os.path.join(M, 'map', 'default.map'))
m = re.search(r'max_provinces\s*=\s*(\d+)', dm); out['max_provinces'] = int(m.group(1)) if m else None

# script feature usage
feat = collections.Counter()
for d in ('events', 'decisions', 'common'):
    for root, _, files in os.walk(os.path.join(M, d)):
        for fn in files:
            if fn.endswith('.txt'):
                t = strip_comments(text(os.path.join(root, fn)))
                for kw in ('set_variable', 'change_variable', 'check_variable', 'set_global_flag', 'set_country_flag',
                           'random_list', 'random_country', 'any_country', 'on_action', 'ai = no', 'host', 'news = yes', 'major = yes'):
                    feat[kw] += t.count(kw)
out['feature_counts'] = dict(feat)

# vanilla leakage (no replace_path)
modfile = open(os.path.join(os.path.dirname(M), 'struggle.mod')).read()
out['replace_paths'] = re.findall(r'replace_path\s*=\s*"([^"]+)"', modfile)
out['vanilla_event_files_leaking_in'] = sorted(set(os.listdir(os.path.join(V, 'events'))) - set(os.listdir(os.path.join(M, 'events'))))

# repo hygiene
big = []
for root, dirs, files in os.walk(os.path.dirname(M)):
    if '.git' in root.split(os.sep): continue
    for fn in files:
        p = os.path.join(root, fn); s = os.path.getsize(p)
        if s > 5_000_000 or fn.lower().endswith(('.rar', '.zip', '.xcf', '.psd')) or '.vs' in root.split(os.sep):
            big.append((round(s / 1e6, 1), os.path.relpath(p, os.path.dirname(M))))
out['repo_heavy_or_junk_files'] = sorted(big, reverse=True)[:25]
json.dump(out, open(sys.argv[3], 'w'), indent=1, default=str)
for k, v in out.items():
    if k in ('worst_polled_events',): continue
    print(k, ':', v if not isinstance(v, list) or len(str(v)) < 600 else str(v)[:600] + '...')
