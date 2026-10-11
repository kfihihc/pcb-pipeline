"""Optional outputs built on outside tools. None of them is part of the gate: what the gate decides comes
from kicad-cli and pcbkit only. release.py and review.py call these when [outputs] in pcb.toml enables
them; a tool that is not installed skips its output with an install hint and never changes the status
of a package. The one exception is panel = "self": then the panel is fabrication data and must succeed.

  kicanvas  KiCanvas page: every schematic sheet and the board in the browser (vendored kicanvas.js)
  ibom      InteractiveHtmlBom: interactive assembly BOM, both sides of the board, designators and fields
  pcbdraw   PcbDraw: stylised top and bottom drawings (SVG) for README and pinout docs
  panel     KiKit panel from layout/panel.toml, panel DRC (must be clean), render; release.py adds Gerbers
  emc       kicad-happy EMC pre-compliance scan: rule-based leads for the review, not verdicts
  status    what [outputs] asks for and which tools are installed

ibom, pcbdraw and panel run in the project's uv environment (`uv sync --group extras`) after the
kicad_compat patch; emc needs kicad-happy (scripts/setup_kicad_happy.sh of the pcb-review skill, or
KICAD_HAPPY_DIR).

usage: python3 pcbkit/extras.py {kicanvas,ibom,pcbdraw,panel,emc,status} [--out reports/extras] [--config pcb.toml]
"""
import argparse, html, json, os, re, shutil, subprocess, sys, tempfile, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import kicad_cli  # noqa: E402

KIT = Path(__file__).resolve().parent
KICANVAS_JS = KIT / 'vendor' / 'kicanvas.js'
KICAD_HAPPY_TAG = 'v2.3.1'
DEFAULTS = {'ibom': True, 'kicanvas': True, 'pcbdraw': True, 'emc': True, 'panel': 'ask', 'panel_config': 'layout/panel.toml'}
PANEL_MODES = ('self', 'fab', 'ask')
EXTRAS_HINT = 'uv sync --group extras'
SEVERITY_ORDER = ['critical', 'error', 'high', 'warning', 'medium', 'low', 'info']


class Unavailable(Exception):
    """The tool is not installed; the message says how to install it."""


def outputs(p):
    o = dict(DEFAULTS)
    o.update(p.section('outputs'))
    if o['panel'] not in PANEL_MODES:
        sys.exit(f'[outputs].panel = {o["panel"]!r}: use one of {", ".join(PANEL_MODES)}')
    return o


def attempt(name, func, *args, **kw):
    """Run one optional output for release.py and review.py: (result, None), or (None, note) when the
    tool is missing or fails. The note goes into the package README; the package status is unchanged."""
    try:
        return func(*args, **kw), None
    except Unavailable as e:
        return None, f'{name} skipped: {e}'
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return None, f'{name} failed: {str(e)[-300:]}'


# ---------------------------------------------------------------- running tools from the uv environment

_PYTHONS = {}
RUNNER = '''import json, sys
sys.path.insert(0, {kit!r})
import kicad_compat  # noqa: F401  system pcbnew + SWIG iterator patch, before the tool imports pcbnew
sys.argv = json.loads(sys.argv[1])
{call}
'''


def extras_python(p, module):
    """A python that can import `module`: this one, or the project's uv environment."""
    if module not in _PYTHONS:
        venv = Path(os.environ.get('UV_PROJECT_ENVIRONMENT') or '.venv')
        venv = venv if venv.is_absolute() else p.root / venv
        for py in (Path(sys.executable), venv / 'bin' / 'python'):
            if py.exists() and subprocess.run([str(py), '-c', f'import importlib.util as u; exit(u.find_spec({module!r}) is None)'],
                                                capture_output=True).returncode == 0:
                _PYTHONS[module] = py
                break
        else:
            raise Unavailable(f'{module} is not installed ({EXTRAS_HINT})')
    return _PYTHONS[module]


def run_tool(p, module, call, argv, cwd, env=None):
    code = RUNNER.format(kit=str(KIT), call=call)
    r = subprocess.run([str(extras_python(p, module)), '-c', code, json.dumps([str(a) for a in argv])], cwd=cwd,
                       capture_output=True, text=True, env={**os.environ, 'PYTHONWARNINGS': 'ignore', **(env or {})})
    if r.returncode:
        raise RuntimeError(f'{argv[0]} {argv[1] if len(argv) > 1 else ""} failed: ' + (r.stdout + r.stderr).strip()[-600:])
    return r


# ---------------------------------------------------------------- KiCanvas

def sheet_files(sch):
    """The root sheet and every sub-sheet file it uses, recursively, relative to the root sheet's folder."""
    seen, todo = [], [sch.name]
    while todo:
        rel = todo.pop(0)
        if rel in seen or not (sch.parent / rel).exists():
            continue
        seen.append(rel)
        todo += re.findall(r'\(property\s+"Sheetfile"\s+"([^"]+)"', (sch.parent / rel).read_text(encoding='utf-8'))
    return seen


def kicanvas(p, out):
    """out/index.html: a schematic viewer (every sheet) and a board viewer, plus the files they show and
    kicanvas.js. Browsers do not load the files over file://: serve the folder over HTTP (README.txt)."""
    if not KICANVAS_JS.exists():
        raise Unavailable(f'{KICANVAS_JS} missing (refresh pcbkit with new_project.py --update-kit)')
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(KICANVAS_JS, out / KICANVAS_JS.name)
    sheets = sheet_files(p.sch) if p.sch and p.sch.exists() else []
    for rel in sheets:
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p.sch.parent / rel, out / rel)
    for f in (p.pcb, p.pro):
        if f and f.exists():
            shutil.copy(f, out / f.name)
    def embed(files):
        return ('<kicanvas-embed controls="full">\n'
                + ''.join(f'  <kicanvas-source src="{html.escape(f)}"></kicanvas-source>\n' for f in files) + '</kicanvas-embed>\n')
    title = html.escape(f'{p.name} {p.section("project").get("revision", "")}'.strip())
    body = ''
    if sheets:
        body += f'<h2>原理图（{len(sheets)} 页）</h2>\n' + embed(sheets)
    if p.pcb and p.pcb.exists():
        body += '<h2>PCB</h2>\n' + embed([p.pcb.name])
    (out / 'index.html').write_text(
        f'<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n'
        '<script type="module" src="kicanvas.js"></script>\n'
        '<style>body{margin:0;font-family:sans-serif} h2{margin:10px 12px 4px;font-size:16px} '
        'kicanvas-embed{display:block;width:100%;height:85vh} p{margin:8px 12px;color:#666;font-size:13px}</style>\n'
        f'</head>\n<body>\n{body}'
        '<p>KiCanvas（alpha，MIT）只用来浏览；检查结论以 kicad-cli 和门禁报告为准。</p>\n</body>\n</html>\n', encoding='utf-8')
    (out / 'README.txt').write_text(
        'Open in a browser over HTTP (file:// does not work):\n'
        f'  python3 -m http.server --directory {out.name} 8000\n'
        '  then http://localhost:8000/   (any free port; Ctrl+C stops the server)\n', encoding='utf-8')
    return {'sheets': len(sheets), 'files': sorted(f.relative_to(out).as_posix() for f in out.rglob('*') if f.is_file())}


# ---------------------------------------------------------------- InteractiveHtmlBom, PcbDraw

def ibom(p, html_out):
    """Interactive HTML BOM of the board at html_out, with the [bom] required fields as columns."""
    html_out = Path(html_out).resolve()
    html_out.parent.mkdir(parents=True, exist_ok=True)
    fields = p.section('bom').get('required_fields', [])
    argv = ['ibom', p.pcb, '--no-browser', '--dest-dir', html_out.parent, '--name-format', html_out.stem,
            '--group-fields', ','.join(['Value', 'Footprint'] + fields)]
    if fields:
        argv += ['--extra-fields', ','.join(fields)]
    run_tool(p, 'InteractiveHtmlBom', 'from InteractiveHtmlBom.generate_interactive_bom import main; main()', argv,
             cwd=p.root, env={'INTERACTIVE_HTML_BOM_NO_DISPLAY': '1'})
    if not html_out.exists():
        raise RuntimeError(f'ibom wrote no {html_out.name}')
    return html_out


def pcbdraw(p, out):
    """out/pcbdraw-top.svg and out/pcbdraw-bottom.svg. PcbDraw's own component library draws common parts;
    the others show as bare pads (result['undrawn']: {'top'|'bottom': [footprint, ...]})."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    files, undrawn = [], {}
    for side, name in (('front', 'top'), ('back', 'bottom')):
        f = out / f'pcbdraw-{name}.svg'
        r = run_tool(p, 'pcbdraw', 'from pcbdraw.ui import run; run()', ['pcbdraw', 'plot', '--side', side, p.pcb, f], cwd=p.root)
        files.append(f)
        missing = sorted({m.group(1) for m in re.finditer(r'Component (\S+?)(?:\.back)? has no footprint', r.stdout + r.stderr)})
        if missing:
            undrawn[name] = missing
    return {'files': files, 'undrawn': undrawn}


# ---------------------------------------------------------------- KiKit panel

def panel(p, out, smt=None):
    """Panel per layout/panel.toml (a KiKit preset written as TOML) in out/: panel.kicad_pcb with zones refilled,
    drc.json, top.png. 'ok' needs a clean panel DRC and one connected substrate. With smt (the machine-placed
    designators) and 'ok' it also writes the fab files: gerbers/, gerbers.zip, positions.csv, jlc-cpl.csv
    (one row per board for every designator: KiKit's convention, used with the single-board BOM)."""
    o = outputs(p)
    cfg = p.root / o['panel_config']
    if not cfg.exists():
        raise RuntimeError(f'{o["panel_config"]} not found (start from layout/panel.toml in the pcbkit template)')
    preset = tomllib.loads(cfg.read_text(encoding='utf-8'))
    own = preset.pop('pcbkit', {})
    out = Path(out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pcb = out / 'panel.kicad_pcb'
    with tempfile.TemporaryDirectory() as d:
        js = Path(d) / 'preset.json'
        js.write_text(json.dumps(preset, indent=1))
        run_tool(p, 'kikit', 'from kikit.ui import cli; cli()', ['kikit', 'panelize', '-p', js, p.pcb, pcb], cwd=p.root)
    for t in ('fp-lib-table', 'sym-lib-table'):              # without them DRC reports every footprint as unknown
        if (p.kicad_dir / t).exists():
            shutil.copy(p.kicad_dir / t, out / t)
    kicad_cli('pcb', 'drc', '--refill-zones', '--save-board', '--format', 'json', '--severity-all', '-o', out / 'drc.json', pcb, cwd=out)
    d = json.loads((out / 'drc.json').read_text())
    g = p.section('gate')
    allowed = [(a['type'], a.get('contains', '')) for a in g.get('drc_allowed', []) + own.get('drc_allowed', [])]
    def listed(v): return any(v['type'] == t and c in v['description'] for t, c in allowed)
    groups = {k: [v for v in d.get(k, []) if not listed(v)] for k in ('violations', 'unconnected_items')}
    failing = dict(groups)
    if g.get('allow_unrouted'):
        failing['unconnected_items'] = []
    import kicad_compat as kc
    board = kc.load_board(pcb)
    box = board.GetBoardEdgesBoundingBox()
    outline = kc.pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    pieces = outline.OutlineCount()      # a panel without tabs passes DRC but falls apart: it must be one substrate
    lay = preset.get('layout', {})
    res = {'ok': not any(failing.values()) and pieces == 1, 'config': o['panel_config'], 'pieces': pieces,
           'boards': int(lay.get('rows', 1)) * int(lay.get('cols', 1)) if lay.get('type', 'grid') == 'grid' else None,
           'size_mm': [round(kc.pcbnew.ToMM(box.GetWidth()), 1), round(kc.pcbnew.ToMM(box.GetHeight()), 1)],
           'drc': {k: len(v) for k, v in groups.items()},
           'problems': ([f'the panel outline is {pieces} separate pieces, not one: boards are not held by tabs (check [tabs])']
                        if pieces != 1 else []) + [f'{v["type"]}: {v["description"]}' for vs in failing.values() for v in vs][:8]}
    kicad_cli('pcb', 'render', '--side', 'top', '--width', '1600', '--height', '1200', '--quality', 'basic', '-o', out / 'top.png', pcb, cwd=out)
    if smt is not None and res['ok']:
        common.export_fab(pcb, out, cwd=out)
        rows = common.export_positions(pcb, out / 'positions.csv', cwd=out)
        common.write_jlc_cpl(rows, smt, out / 'jlc-cpl.csv')
        res['placements'] = sum(r['Ref'] in smt for r in rows)
    for f in out.iterdir():
        if f.suffix == '.kicad_prl' or f.name.endswith('.lck') or f.name.endswith('-backups'):
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    return res


# ---------------------------------------------------------------- kicad-happy EMC

def kicad_happy():
    base = Path(os.environ.get('KICAD_HAPPY_DIR')
                or Path(os.environ.get('PCB_PIPELINE_CACHE', Path.home() / '.cache/pcb-pipeline')) / f'kicad-happy-{KICAD_HAPPY_TAG}')
    scripts = {'schematic': base / 'skills/kicad/scripts/analyze_schematic.py', 'pcb': base / 'skills/kicad/scripts/analyze_pcb.py',
               'emc': base / 'skills/emc/scripts/analyze_emc.py'}
    if not all(s.exists() for s in scripts.values()):
        raise Unavailable(f'kicad-happy {KICAD_HAPPY_TAG} not found in {base} (run scripts/setup_kicad_happy.sh of the pcb-review skill)')
    return scripts


def _cell(text):
    return str(text or '').replace('|', '\\|').replace('\n', ' ').strip()


def emc(p, out):
    """out/emc.json (kicad-happy's full report) and out/emc.md (findings table, most severe first)."""
    k = kicad_happy()
    if not (p.pcb and p.pcb.exists()):
        raise RuntimeError('emc needs the board')
    o = outputs(p)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:     # the analyzers also write a capability file into the working folder
        steps = []
        if p.sch and p.sch.exists():
            steps.append([k['schematic'], p.sch, '-o', 'sch.json'])
        steps.append([k['pcb'], p.pcb, '--full', *(['--schematic', 'sch.json'] if steps else []), '-o', 'pcb.json'])
        steps.append([k['emc'], *(['-s', 'sch.json'] if p.sch and p.sch.exists() else []), '-p', 'pcb.json', '-o', 'emc.json',
                      *(['--standard', o['emc_standard']] if o.get('emc_standard') else []),
                      *(['--market', o['emc_market']] if o.get('emc_market') else [])])
        for s in steps:
            r = subprocess.run([sys.executable, *map(str, s)], cwd=d, capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError(f'{Path(s[0]).name} failed: ' + (r.stdout + r.stderr).strip()[-400:])
        shutil.copy(Path(d) / 'emc.json', out / 'emc.json')
    data = json.loads((out / 'emc.json').read_text())
    findings = sorted([f for f in data.get('findings', []) if not f.get('suppressed')],
                      key=lambda f: SEVERITY_ORDER.index(f.get('severity')) if f.get('severity') in SEVERITY_ORDER else 99)
    s = data.get('summary', {})
    sev = s.get('by_severity', {})
    head = (f"标准 {data.get('target_standard', '')}；风险分 {s.get('emc_risk_score')}/100；"
            + '，'.join(f'{k} {v}' for k, v in sev.items())
            + '；可信度 ' + '，'.join(f'{k} {v}' for k, v in data.get('trust_summary', {}).get('by_confidence', {}).items()))
    lines = [f'# EMC 预检（kicad-happy {KICAD_HAPPY_TAG}，规则式，只作线索）', '', head, '',
             '每条都要对照设计核实：成立的改设计，能量化的写成 `checks/metrics.toml` 指标；不成立的在审查记录里写明理由。'
             '它按规则推断，不预测实际辐射值，也不能代替实验室测试。', '',
             '| 严重度 | 规则 | 可信度 | 问题 | 涉及 | 建议 |', '| --- | --- | --- | --- | --- | --- |']
    lines += [f"| {_cell(f.get('severity'))} | {_cell(f.get('rule_id'))} | {_cell(f.get('confidence'))} | {_cell(f.get('title'))} "
              f"| {_cell(', '.join((f.get('components') or []) + (f.get('nets') or []))[:120])} | {_cell(f.get('recommendation'))[:300]} |"
              for f in findings]
    (out / 'emc.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'summary': head, 'by_severity': sev, 'score': s.get('emc_risk_score'), 'findings': findings}


# ---------------------------------------------------------------- command line

def status(p):
    o = outputs(p)
    rows = [('kicanvas', o['kicanvas'], 'kicanvas.js vendored' if KICANVAS_JS.exists() else 'kicanvas.js missing')]
    for name, module in (('ibom', 'InteractiveHtmlBom'), ('pcbdraw', 'pcbdraw'), ('panel', 'kikit')):
        try:
            have = f'{module} in {extras_python(p, module)}'
        except Unavailable as e:
            have = str(e)
        rows.append((name, o[name], have))
    try:
        have = f'kicad-happy {KICAD_HAPPY_TAG}: {kicad_happy()["emc"].parents[3]}'
    except Unavailable as e:
        have = str(e)
    rows.append(('emc', o['emc'], have))
    for name, want, have in rows:
        print(f'{name:9} {str(want):6} {have}')
    if o['panel'] == 'ask':
        print('\npanel = "ask": decide before ordering whether to panelize yourself ("self", layout/panel.toml) '
              'or let the board house do it ("fab"), set [outputs].panel and record it in docs/DECISIONS.md')


def main():
    ap = argparse.ArgumentParser(description='Optional outputs (KiCanvas, iBOM, PcbDraw, KiKit panel, kicad-happy EMC)')
    ap.add_argument('what', choices=['kicanvas', 'ibom', 'pcbdraw', 'panel', 'emc', 'status'])
    ap.add_argument('--config'); ap.add_argument('--out', default='reports/extras')
    a = ap.parse_args()
    p = common.Project(a.config)
    out = p.root / a.out
    def shown(path):
        try:
            return p.rel(path)
        except ValueError:          # --out outside the project
            return str(path)
    try:
        if a.what == 'status':
            return status(p)
        if a.what == 'kicanvas':
            r = kicanvas(p, out / 'kicanvas')
            print(f'{shown(out / "kicanvas")}/index.html: {r["sheets"]} sheets + board; serve: python3 -m http.server --directory {shown(out / "kicanvas")} 8000')
        elif a.what == 'ibom':
            print(shown(ibom(p, out / 'ibom.html')))
        elif a.what == 'pcbdraw':
            r = pcbdraw(p, out)
            print(', '.join(shown(f) for f in r['files'])
                  + ''.join(f'\n  drawn as bare pads ({side}): {", ".join(names)}' for side, names in r['undrawn'].items()))
        elif a.what == 'panel':
            r = panel(p, out / 'panel')
            print(json.dumps(r, ensure_ascii=False, indent=1))
            if not r['ok']:
                sys.exit(f'panel not usable: see {shown(out / "panel")}/drc.json and top.png')
        elif a.what == 'emc':
            r = emc(p, out)
            print(f'{shown(out / "emc.md")}: {r["summary"]}')
    except Unavailable as e:
        sys.exit(f'{a.what} skipped: {e}')


if __name__ == '__main__':
    main()
