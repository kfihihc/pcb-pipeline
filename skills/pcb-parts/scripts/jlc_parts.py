"""Search the JLCPCB assembly parts library offline and check a BOM against it.

Data: the SQLite (FTS5) builds published by kicad-jlcpcb-tools (MIT, https://github.com/Bouni/kicad-jlcpcb-tools),
derived from yaqwsx/jlcparts. Every answer carries the snapshot date of the database it came from; stock and
prices change daily, so confirm with `live` (LCSC's public product endpoint) before ordering.

  jlc_parts.py fetch [--db basic|current|all]   download to ~/.cache/pcb-pipeline/jlcpcb-tools (basic 0.4 MB,
                                                current ~180 MB without obsolete parts, all ~950 MB)
  jlc_parts.py info                             databases present, snapshot dates, part counts
  jlc_parts.py search WORDS... [--category S] [--package 0603] [--type basic,preferred,extended]
                                [--min-stock N] [--limit 20] [--qty 10] [--db current] [--json]
  jlc_parts.py show C5446 [C25804 ...] [--json]
  jlc_parts.py check parts/parts.csv [--column LCSC] [--qty-column Qty] [--boards 10] [--json]
  jlc_parts.py live C5446 [...]                 live LCSC stock, price ladder and datasheet URL (unofficial endpoint)

Words of 3+ characters use the full-text index; shorter ones ("1k", "5V") are matched as substrings.
"""
import argparse, csv, datetime, json, os, sqlite3, sys, urllib.request, zipfile
from pathlib import Path

CACHE = Path(os.environ.get('PCB_PIPELINE_CACHE', Path.home() / '.cache/pcb-pipeline')) / 'jlcpcb-tools'
BASE = 'https://bouni.github.io/kicad-jlcpcb-tools/'
DBS = {'basic': ('basic-parts-fts5.db', 'chunk_num_basic_parts_fts5.txt'),
       'current': ('current-parts-fts5.db', 'chunk_num_current_parts_fts5.txt'),
       'all': ('parts-fts5.db', 'chunk_num_fts5.txt')}
COLS = ['LCSC Part', 'MFR.Part', 'Manufacturer', 'Package', 'Library Type', 'Stock', 'Price',
        'First Category', 'Second Category', 'Description', 'Datasheet']
TYPE_ORDER = {'Basic': 0, 'Preferred': 1, 'Extended': 2}
EXTENDED_FEE_USD = 3.0   # JLCPCB one-off loading fee per extended part type (check jlcpcb.com before quoting)


def fetch(which):
    name, chunk_file = DBS[which]
    CACHE.mkdir(parents=True, exist_ok=True)
    n = int(urllib.request.urlopen(BASE + chunk_file, timeout=60).read().decode().strip())
    zpath = CACHE / (name + '.zip')
    with zpath.open('wb') as out:
        for i in range(1, n + 1):
            url = f'{BASE}{name}.zip.{i:03}'
            print(f'downloading {url}', file=sys.stderr)
            with urllib.request.urlopen(url, timeout=600) as r:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(CACHE)
    zpath.unlink()
    (CACHE / (name + '.fetched')).write_text(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
    print(json.dumps(info(), indent=1))


def connect(which):
    order = [which] if which else ['current', 'all', 'basic']
    for w in order:
        path = CACHE / DBS[w][0]
        if path.exists():
            c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            c.row_factory = sqlite3.Row
            return c, w
    sys.exit(f'no parts database in {CACHE}: run `jlc_parts.py fetch --db current` (or basic)')


def snapshot(c):
    try:
        return c.execute('select date from meta').fetchone()[0]
    except Exception:
        return 'unknown'


def info():
    out = {}
    for w, (name, _) in DBS.items():
        path = CACHE / name
        if path.exists():
            c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            meta = c.execute('select partcount, date from meta').fetchone()
            out[w] = {'file': str(path), 'parts': meta[0], 'snapshot': meta[1], 'size_mb': round(path.stat().st_size / 2**20)}
    return out


def prices(text):
    out = []
    for tier in (text or '').split(','):
        if ':' not in tier:
            continue
        rng, price = tier.split(':', 1)
        lo, _, hi = rng.partition('-')
        try:
            out.append((int(lo or 1), int(hi) if hi else None, float(price)))
        except ValueError:
            continue
    return out


def unit_price(text, qty):
    tiers = prices(text)
    for lo, hi, p in tiers:
        if qty >= lo and (hi is None or qty <= hi):
            return p
    return tiers[0][2] if tiers else None


def row(r, qty=1):
    d = {k: r[k] for k in COLS}
    d['Stock'] = int(d['Stock'] or 0)
    d['Unit Price'] = unit_price(d['Price'], qty)
    return d


def fts_quote(word):
    return '"' + word.replace('"', '""') + '"'


def search(a):
    c, which = connect(a.db)
    match, like, args = [], [], []
    for w in a.words:
        (match if len(w) >= 3 else like).append(w)
    for col, val in (('First Category', a.first), ('Second Category', a.category), ('Package', a.package)):
        if val:
            if len(val) >= 3:
                match.append(f'"{col}":{fts_quote(val)}')
            else:
                like.append(val)
    sql = 'select * from parts'
    where = []
    if match:
        where.append('parts match ?'); args.append(' AND '.join(m if m.startswith('"') and '":' in m else fts_quote(m) for m in match))
    for w in like:
        where.append('("Description" like ? or "MFR.Part" like ? or "Package" like ?)'); args += [f'%{w}%'] * 3
    if a.type:
        types = [t.strip().capitalize() for t in a.type.split(',')]
        where.append('"Library Type" in (%s)' % ','.join('?' * len(types))); args += types
    if where:
        sql += ' where ' + ' and '.join(where)
    rows = [row(r, a.qty) for r in c.execute(sql + ' limit 5000', args)]
    rows = [r for r in rows if r['Stock'] >= a.min_stock]
    rows.sort(key=lambda r: (TYPE_ORDER.get(r['Library Type'], 9), -r['Stock']))
    return {'db': which, 'snapshot': snapshot(c), 'query': vars(a) | {'func': None}, 'count': len(rows), 'parts': rows[:a.limit]}


def show(codes, which=None):
    c, w = connect(which)
    out = []
    for code in codes:
        r = c.execute('select * from parts where "LCSC Part" = ?', (code.upper(),)).fetchone()
        out.append(row(r) | {'Price tiers': prices(r['Price'])} if r else {'LCSC Part': code, 'missing': True})
    return {'db': w, 'snapshot': snapshot(c), 'parts': out}


def check(a):
    c, which = connect(a.db)
    lines = list(csv.DictReader(Path(a.file).open(encoding='utf-8-sig')))
    need, report, types = {}, [], {'Basic': 0, 'Preferred': 0, 'Extended': 0}
    for ln in lines:
        code = (ln.get(a.column) or '').strip().upper()
        if not code:
            report.append({'line': ln, 'problem': f'no {a.column}'}); continue
        qty = int(float(ln.get(a.qty_column) or 1)) * a.boards
        need[code] = need.get(code, 0) + qty
    total = 0.0
    for code, qty in sorted(need.items()):
        r = c.execute('select * from parts where "LCSC Part" = ?', (code,)).fetchone()
        if r is None:
            report.append({'LCSC': code, 'problem': f'not in the {which} database (obsolete, LCSC-only, or use --db all)'}); continue
        d = row(r, qty)
        types[d['Library Type']] = types.get(d['Library Type'], 0) + 1
        if d['Stock'] < qty:
            report.append({'LCSC': code, 'problem': f"stock {d['Stock']} < needed {qty}"})
        if d['Unit Price'] is not None:
            total += d['Unit Price'] * qty
    return {'db': which, 'snapshot': snapshot(c), 'boards': a.boards, 'unique_parts': len(need), 'library_types': types,
            'parts_cost_usd': round(total, 2), 'extended_fees_usd': types.get('Extended', 0) * EXTENDED_FEE_USD,
            'problems': report, 'note': 'parts cost excludes PCB, assembly, stencil, shipping and taxes; '
                                        f'extended fee assumes {EXTENDED_FEE_USD} USD per extended part type'}


def live(codes):
    out = []
    for code in codes:
        req = urllib.request.Request(f'https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={code}', headers={'User-Agent': 'Mozilla/5.0'})
        try:
            r = (json.loads(urllib.request.urlopen(req, timeout=30).read()).get('result') or {})
        except Exception as e:
            out.append({'LCSC': code, 'error': str(e)}); continue
        out.append({'LCSC': code, 'MPN': r.get('productModel'), 'Manufacturer': r.get('brandNameEn'), 'Package': r.get('encapStandard'),
                    'LCSC stock': r.get('stockNumber'), 'Datasheet': r.get('pdfUrl'), 'Description': r.get('productIntroEn'),
                    'Price ladder (USD)': [(p.get('ladder'), p.get('usdPrice') or p.get('productPrice')) for p in r.get('productPriceList') or []]})
    return {'source': 'wmsc.lcsc.com (LCSC distribution stock, not JLCPCB assembly stock)',
            'queried': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'parts': out}


def table(rows):
    for r in rows:
        print(f"{r['LCSC Part']:>10}  {r['Library Type'][:4]:4}  {r['Stock']:>9}  {('%.4f' % r['Unit Price']) if r['Unit Price'] is not None else '-':>7}  "
              f"{r['Package'][:14]:14}  {r['MFR.Part'][:24]:24}  {r['Manufacturer'][:12]:12}  {r['Description'][:70]}")


def main():
    ap = argparse.ArgumentParser(description='JLCPCB parts library: search and BOM check')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('--db', default='current', choices=list(DBS))
    sub.add_parser('info')
    s = sub.add_parser('search'); s.add_argument('words', nargs='*')
    s.add_argument('--category', help='second category, e.g. "Chip Resistor"'); s.add_argument('--first', help='first category')
    s.add_argument('--package'); s.add_argument('--type', help='basic,preferred,extended'); s.add_argument('--min-stock', type=int, default=0)
    s.add_argument('--limit', type=int, default=20); s.add_argument('--qty', type=int, default=10); s.add_argument('--db', choices=list(DBS)); s.add_argument('--json', action='store_true')
    sh = sub.add_parser('show'); sh.add_argument('codes', nargs='+'); sh.add_argument('--db', choices=list(DBS)); sh.add_argument('--json', action='store_true')
    ck = sub.add_parser('check'); ck.add_argument('file'); ck.add_argument('--column', default='LCSC'); ck.add_argument('--qty-column', default='Qty')
    ck.add_argument('--boards', type=int, default=1); ck.add_argument('--db', choices=list(DBS))
    lv = sub.add_parser('live'); lv.add_argument('codes', nargs='+')
    a = ap.parse_args()
    if a.cmd == 'fetch':
        return fetch(a.db)
    if a.cmd == 'info':
        return print(json.dumps(info(), indent=1))
    if a.cmd == 'search':
        res = search(a)
        if a.json:
            return print(json.dumps(res, indent=1, ensure_ascii=False))
        print(f"# {res['count']} matches in {res['db']} (snapshot {res['snapshot']}); unit price at qty {a.qty}")
        return table(res['parts'])
    if a.cmd == 'show':
        res = show(a.codes, a.db)
        return print(json.dumps(res, indent=1, ensure_ascii=False))
    if a.cmd == 'check':
        res = check(a)
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 1 if res['problems'] else 0
    if a.cmd == 'live':
        return print(json.dumps(live(a.codes), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
