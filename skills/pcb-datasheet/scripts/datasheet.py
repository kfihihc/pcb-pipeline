"""Datasheets as evidence: fetch with provenance, split into per-page text, search with page numbers,
render pages for visual reading, and check the curated facts file (facts.toml) against the PDF and
against the KiCad symbol and footprint that will be used.

  datasheet.py fetch URL|LCSC-code --mpn MPN [--root data/parts]   -> data/parts/<MPN>/datasheet.pdf + source.json
  datasheet.py text DIR                                            -> DIR/pages/NNN.txt (pdftotext -layout)
  datasheet.py grep DIR WORD... [--context 2] [--all]              matches with page numbers (any word; --all: every word on the page)
  datasheet.py render DIR PAGE [PAGE...] [--dpi 110]                -> DIR/pages/pNNN.png for figures, pinouts, tables
  datasheet.py check DIR/facts.toml [--symbol Lib:Name] [--footprint Lib:Name]
  datasheet.py pins Lib:Name                                       pins of a KiCad library symbol (number, name, type)

DIR is data/parts/<MPN> (MPN with "/" replaced by "_"). Needs poppler-utils (pdftotext, pdfinfo, pdftoppm).
"""
import argparse, datetime, hashlib, json, os, re, sqlite3, subprocess, sys, tomllib, urllib.request
from pathlib import Path

CACHE = Path(os.environ.get('PCB_PIPELINE_CACHE', Path.home() / '.cache/pcb-pipeline'))
SYM_DIR = Path(os.environ.get('KICAD10_SYMBOL_DIR', '/usr/share/kicad/symbols'))
FP_DIR = Path(os.environ.get('KICAD10_FOOTPRINT_DIR', '/usr/share/kicad/footprints'))
UA = 'Mozilla/5.0 (X11; Linux x86_64)'   # some CDNs stall requests that do not look like a browser
PIN_TYPES = {'input', 'output', 'bidirectional', 'tri_state', 'passive', 'free', 'unspecified', 'power_in', 'power_out',
             'open_collector', 'open_emitter', 'no_connect'}
FACT_SECTIONS = ['abs_max', 'recommended', 'characteristic', 'application', 'layout', 'caveat', 'pin']


def safe(mpn):
    return mpn.replace('/', '_').replace(' ', '_')


def resolve_urls(src):
    """Candidate PDF URLs for a URL or an LCSC code: LCSC's direct PDF link first (the parts database
    often stores a web viewer page instead of the PDF), then the database link."""
    if not re.fullmatch(r'C\d+', src, re.I):
        return [src], None
    urls, mpn = [], None
    try:
        req = urllib.request.Request(f'https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={src.upper()}', headers={'User-Agent': 'Mozilla/5.0'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read()).get('result') or {}
        if r.get('pdfUrl'):
            urls.append(r['pdfUrl']); mpn = r.get('productModel')
    except Exception as e:
        print(f'LCSC lookup failed: {e}', file=sys.stderr)
    for db in ('current-parts-fts5.db', 'parts-fts5.db', 'basic-parts-fts5.db'):
        path = CACHE / 'jlcpcb-tools' / db
        if path.exists():
            r = sqlite3.connect(f'file:{path}?mode=ro', uri=True).execute(
                'select "Datasheet", "MFR.Part" from parts where "LCSC Part" = ?', (src.upper(),)).fetchone()
            if r and r[0]:
                urls.append(r[0]); mpn = mpn or r[1]
                break
    if not urls:
        sys.exit(f'no datasheet URL for {src}')
    return urls, mpn


def pdfinfo(pdf):
    out = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True).stdout
    return {k.strip(): v.strip() for k, v in (l.split(':', 1) for l in out.splitlines() if ':' in l)}


def fetch(src, mpn, root):
    urls, found_mpn = resolve_urls(src)
    mpn = mpn or found_mpn
    if not mpn:
        sys.exit('--mpn is required for a URL')
    d = Path(root) / safe(mpn)
    d.mkdir(parents=True, exist_ok=True)
    data, url = None, None
    for url in urls:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        try:
            data = urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:
            print(f'{url}: {e}', file=sys.stderr); continue
        if data.startswith(b'%PDF'):
            break
        print(f'{url}: not a PDF ({data[:40]!r})', file=sys.stderr); data = None
    if data is None:
        sys.exit(f'no PDF from {urls}; download it by hand (manufacturer site preferred) into {d}/datasheet.pdf, then run `text`')
    pdf = d / 'datasheet.pdf'
    pdf.write_bytes(data)
    info = pdfinfo(pdf)
    meta = {'mpn': mpn, 'source': src, 'url': url, 'retrieved': datetime.date.today().isoformat(),
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'pages': int(info.get('Pages', 0)),
            'title': info.get('Title', ''), 'producer': info.get('Producer', ''), 'pdf_date': info.get('CreationDate', '')}
    (d / 'source.json').write_text(json.dumps(meta, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps(meta, indent=1, ensure_ascii=False))
    return d


def text(d):
    d = Path(d); pdf = d / 'datasheet.pdf'
    n = int(pdfinfo(pdf).get('Pages', 0))
    pages = d / 'pages'; pages.mkdir(exist_ok=True)
    empty = []
    for i in range(1, n + 1):
        out = pages / f'{i:03}.txt'
        subprocess.run(['pdftotext', '-layout', '-f', str(i), '-l', str(i), str(pdf), str(out)], check=True)
        if len(out.read_text(errors='replace').strip()) < 40:
            empty.append(i)
    note = f'; pages with almost no text (scanned or vector-only, read them as images): {empty}' if empty else ''
    print(f'{n} pages -> {pages}{note}')


def grep(d, words, context, need_all):
    pages = sorted((Path(d) / 'pages').glob('*.txt'))
    if not pages:
        sys.exit('run `datasheet.py text DIR` first')
    # spaces in a search phrase match any or no whitespace: text extraction often merges words ("AbsolutemAximum")
    pats = [re.compile(r'\s*'.join(re.escape(part) for part in w.split()), re.I) for w in words]
    for p in pages:
        lines = p.read_text(errors='replace').splitlines()
        body = '\n'.join(lines)
        if need_all and not all(x.search(body) for x in pats):
            continue
        hits = [i for i, l in enumerate(lines) if any(x.search(l) for x in pats)]
        shown = set()
        for i in hits:
            lo, hi = max(0, i - context), min(len(lines), i + context + 1)
            if i in shown:
                continue
            print(f'--- p.{int(p.stem)} line {i + 1}')
            for j in range(lo, hi):
                print(('> ' if j == i else '  ') + lines[j].rstrip()); shown.add(j)


def render(d, pages, dpi):
    d = Path(d); (d / 'pages').mkdir(exist_ok=True)
    for pg in pages:
        prefix = d / 'pages' / f'p{pg:03}'
        subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', str(pg), '-l', str(pg), '-singlefile', str(d / 'datasheet.pdf'), str(prefix)], check=True)
        print(f'{prefix}.png')


# ------------------------------------------------------------------ KiCad symbols and footprints
def sexp(text):
    """Minimal S-expression parser: lists, strings (unquoted) and atoms."""
    tokens = re.finditer(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+', text)
    stack, cur = [], []
    for t in tokens:
        s = t.group(0)
        if s == '(':
            stack.append(cur); cur = []
        elif s == ')':
            done = cur; cur = stack.pop(); cur.append(done)
        else:
            cur.append(s[1:-1].replace('\\"', '"') if s.startswith('"') else s)
    return cur


def find_symbol(lib_id):
    lib, _, name = lib_id.partition(':')
    path = SYM_DIR / f'{lib}.kicad_sym'
    if not path.exists():
        raise SystemExit(f'symbol library {path} not found')
    tree = sexp(path.read_text(encoding='utf-8'))[0]
    syms = {s[1]: s for s in tree if isinstance(s, list) and s and s[0] == 'symbol'}
    if name not in syms:
        raise SystemExit(f'{name} not in {path.name}')
    sym = syms[name]
    ext = next((x[1] for x in sym if isinstance(x, list) and x and x[0] == 'extends'), None)
    return syms[ext] if ext else sym


def symbol_pins(lib_id):
    sym = find_symbol(lib_id)
    pins = {}

    def walk(node):
        for x in node:
            if isinstance(x, list) and x:
                if x[0] == 'pin':
                    name = next((y[1] for y in x if isinstance(y, list) and y and y[0] == 'name'), '')
                    num = next((y[1] for y in x if isinstance(y, list) and y and y[0] == 'number'), '')
                    pins.setdefault(num, (name, x[1]))
                else:
                    walk(x)
    walk(sym)
    return pins


def footprint_pads(fp_id):
    lib, _, name = fp_id.partition(':')
    path = FP_DIR / f'{lib}.pretty' / f'{name}.kicad_mod'
    if not path.exists():
        raise SystemExit(f'footprint {path} not found')
    return {(q or b) for q, b, kind in re.findall(r'\(pad\s+(?:"([^"]*)"|([^\s()"]+))\s+(\w+)', path.read_text()) if (q or b) and kind != 'np_thru_hole'}


def norm(name):
    return re.sub(r'[^a-z0-9]', '', (name or '').lower().replace('~', ''))


def check(facts_path, symbol=None, footprint=None):
    facts_path = Path(facts_path)
    f = tomllib.loads(facts_path.read_text(encoding='utf-8'))
    problems, notes = [], []
    part = f.get('part', {})
    for key in ('mpn', 'manufacturer', 'datasheet'):
        if not part.get(key):
            problems.append(f'[part] {key} missing')
    src = facts_path.parent / 'source.json'
    pages = None
    if src.exists():
        meta = json.loads(src.read_text())
        pages = meta.get('pages')
        pdf = facts_path.parent / 'datasheet.pdf'
        if pdf.exists() and hashlib.sha256(pdf.read_bytes()).hexdigest() != meta.get('sha256'):
            problems.append('datasheet.pdf does not match the SHA-256 in source.json')
        if part.get('sha256') and part['sha256'] != meta.get('sha256'):
            problems.append('[part] sha256 differs from source.json: the facts were taken from another file')
    for sec in FACT_SECTIONS:
        for i, item in enumerate(f.get(sec, [])):
            tag = f'[[{sec}]] #{i + 1} {item.get("param") or item.get("name") or item.get("ref") or ""}'.strip()
            pg = item.get('page')
            if not isinstance(pg, int):
                problems.append(f'{tag}: no page number'); continue
            if pages and not 1 <= pg <= pages:
                problems.append(f'{tag}: page {pg} outside 1..{pages}')
            if sec in ('abs_max', 'recommended') and not any(k in item for k in ('min', 'max')):
                problems.append(f'{tag}: needs min and/or max')
            if sec in ('abs_max', 'recommended', 'characteristic') and 'unit' not in item:
                problems.append(f'{tag}: needs unit')
            if sec == 'pin' and item.get('type') and item['type'] not in PIN_TYPES:
                problems.append(f'{tag}: type {item["type"]} is not a KiCad pin type')
    pins = {str(p['number']): p for p in f.get('pin', [])}
    if len(pins) != len(f.get('pin', [])):
        problems.append('duplicate pin numbers in [[pin]]')
    symbol = symbol or f.get('kicad', {}).get('symbol')
    footprint = footprint or f.get('kicad', {}).get('footprint')
    if symbol and pins:
        sp = symbol_pins(symbol)
        for num in sorted(set(pins) | set(sp), key=lambda x: (len(x), x)):
            if num not in sp:
                problems.append(f'pin {num} ({pins[num].get("name")}) of the datasheet is not on symbol {symbol}')
            elif num not in pins:
                problems.append(f'symbol {symbol} pin {num} ({sp[num][0]}) is not in the datasheet pin table')
            elif norm(sp[num][0]) != norm(pins[num].get('name')) and norm(sp[num][0]) not in norm(pins[num].get('name')):
                problems.append(f'pin {num}: datasheet "{pins[num].get("name")}" vs symbol "{sp[num][0]}"')
        notes.append(f'{len(sp)} symbol pins compared')
    if footprint and pins:
        pads = footprint_pads(footprint)
        missing = sorted(set(pins) - pads)
        if missing:
            problems.append(f'datasheet pins without a pad on {footprint}: {missing}')
        notes.append(f'{len(pads)} footprint pads compared')
    counts = {sec: len(f.get(sec, [])) for sec in FACT_SECTIONS}
    for sec in ('pin', 'abs_max', 'recommended', 'application'):
        if not counts[sec]:
            notes.append(f'no [[{sec}]] entries')
    return {'facts': str(facts_path), 'counts': counts, 'problems': problems, 'notes': notes}


def main():
    ap = argparse.ArgumentParser(description='Datasheet evidence tools')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('src'); f.add_argument('--mpn'); f.add_argument('--root', default='data/parts')
    t = sub.add_parser('text'); t.add_argument('dir')
    g = sub.add_parser('grep'); g.add_argument('dir'); g.add_argument('words', nargs='+'); g.add_argument('--context', type=int, default=2); g.add_argument('--all', action='store_true')
    r = sub.add_parser('render'); r.add_argument('dir'); r.add_argument('pages', nargs='+', type=int); r.add_argument('--dpi', type=int, default=110)
    c = sub.add_parser('check'); c.add_argument('facts'); c.add_argument('--symbol'); c.add_argument('--footprint')
    p = sub.add_parser('pins'); p.add_argument('symbol')
    a = ap.parse_args()
    if a.cmd == 'fetch':
        d = fetch(a.src, a.mpn, a.root); text(d)
    elif a.cmd == 'text':
        text(a.dir)
    elif a.cmd == 'grep':
        grep(a.dir, a.words, a.context, a.all)
    elif a.cmd == 'render':
        render(a.dir, a.pages, a.dpi)
    elif a.cmd == 'check':
        res = check(a.facts, a.symbol, a.footprint)
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 1 if res['problems'] else 0
    elif a.cmd == 'pins':
        for num, (name, kind) in sorted(symbol_pins(a.symbol).items(), key=lambda x: (len(x[0]), x[0])):
            print(f'{num:>4}  {name:20} {kind}')


if __name__ == '__main__':
    sys.exit(main())
