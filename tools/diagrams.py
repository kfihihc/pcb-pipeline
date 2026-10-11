"""Check and render the Mermaid diagrams embedded in Markdown files.

Every ```mermaid block is rendered with mermaid.js in headless Chromium: a block that does not parse is
reported (exit 1). With --out, each diagram of the given files is also written as SVG, so documents can
link an image for viewers without Mermaid support (GitHub renders the code blocks itself).

usage: python3 tools/diagrams.py [--out docs/diagrams] FILE.md [...]
       python3 tools/diagrams.py --check $(git ls-files '*.md')
Needs: mermaid.min.js (11.x) in ~/.cache/pcb-pipeline/mermaid/ and a Chromium headless shell
(the Playwright cache, or set CHROME=/path/to/chrome).
"""
import argparse, glob, html, json, os, re, subprocess, sys, tempfile
from pathlib import Path

CACHE = Path(os.environ.get('PCB_PIPELINE_CACHE', Path.home() / '.cache/pcb-pipeline'))
MERMAID = CACHE / 'mermaid' / 'mermaid.min.js'
BLOCK = re.compile(r'```mermaid\n(.*?)```', re.S)
FONT = 'WenQuanYi Zen Hei, Noto Sans CJK SC, Microsoft YaHei, PingFang SC, sans-serif'


def chrome():
    if os.environ.get('CHROME'):
        return os.environ['CHROME']
    found = sorted(glob.glob(str(Path.home() / '.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell')))
    if not found:
        sys.exit('no headless Chromium: set CHROME=/path/to/chrome')
    return found[-1]


def render(blocks):
    """[(name, code)] -> {name: (svg or None, error or None)}"""
    page = f'''<!doctype html><html><head><meta charset="utf-8"><script src="file://{MERMAID}"></script></head><body>
<pre id="out">pending</pre><script>
const blocks = {json.dumps(blocks)};
mermaid.initialize({{startOnLoad: false, securityLevel: 'strict', theme: 'default',
  themeVariables: {{fontFamily: {json.dumps(FONT)}}}, flowchart: {{htmlLabels: false}}}});
(async () => {{
  const res = {{}};
  for (const [name, code] of blocks) {{
    try {{ const r = await mermaid.render('m' + Object.keys(res).length, code); res[name] = [r.svg, null]; }}
    catch (e) {{ res[name] = [null, String(e && e.message || e)]; }}
  }}
  document.getElementById('out').textContent = JSON.stringify(res);
}})();
</script></body></html>'''
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'render.html'
        f.write_text(page, encoding='utf-8')
        r = subprocess.run([chrome(), '--no-sandbox', '--disable-gpu', '--allow-file-access-from-files',
                            '--virtual-time-budget=20000', '--dump-dom', f'file://{f}'], capture_output=True, text=True, timeout=180)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    if not m or m.group(1) == 'pending':
        sys.exit('rendering did not finish: ' + r.stderr[-400:])
    return json.loads(html.unescape(m.group(1)))


def main():
    ap = argparse.ArgumentParser(description='Check and render Mermaid diagrams in Markdown')
    ap.add_argument('files', nargs='+'); ap.add_argument('--out'); ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if not MERMAID.exists():
        sys.exit(f'{MERMAID} missing: curl -L -o {MERMAID} https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js')
    blocks = []
    for f in a.files:
        for i, code in enumerate(BLOCK.findall(Path(f).read_text(encoding='utf-8')), 1):
            blocks.append((f'{Path(f).parent.name}-{Path(f).stem}-{i}' if Path(f).stem == 'SKILL' else f'{Path(f).stem}-{i}', code))
    if not blocks:
        print('no mermaid blocks'); return 0
    res = render(blocks)
    bad = 0
    for name, _ in blocks:
        svg, err = res.get(name, (None, 'not rendered'))
        if err:
            bad += 1; print(f'FAIL  {name}: {err[:300]}')
            continue
        svg = re.sub(r'<br\s*>', '<br/>', svg)          # HTML labels inside foreignObject must be well-formed XML
        try:
            import xml.dom.minidom
            xml.dom.minidom.parseString(svg)
        except Exception as e:
            bad += 1; print(f'FAIL  {name}: SVG is not valid XML ({e})')
            continue
        print(f'ok    {name}')
        if a.out and not a.check:
            Path(a.out).mkdir(parents=True, exist_ok=True)
            Path(a.out, f'{name}.svg').write_text(svg, encoding='utf-8')
    print(f'{len(blocks) - bad}/{len(blocks)} diagrams render')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
