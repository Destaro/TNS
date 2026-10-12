"""Static audit of a Victoria 2 mod folder. Usage: python3 -I audit.py <mod_dir> <out_dir>"""
import os, re, sys, json, collections

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

