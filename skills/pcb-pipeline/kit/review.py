"""Review packet: everything a reviewer (human or agent) needs in one folder, without opening KiCad.

  reports/review/
    top.png, bottom.png        3D renders of both sides (kicad-cli pcb render)
    schematic.pdf, pcb.pdf     schematic and per-layer copper/silk/fab plots
    gate.json                  gate summary (the gate is run first)
    diff.json                  board_diff against a base revision (--base <git ref>, e.g. main)
    caveats.md                 every [[caveat]] and [[layout]] note from data/parts/*/facts.toml, with pages
    kicanvas/                  schematic and board in the browser, served over HTTP   ([outputs].kicanvas)
    ibom.html                  interactive BOM                                        ([outputs].ibom)
    pcbdraw-top.svg, pcbdraw-bottom.svg   stylised board drawings                      ([outputs].pcbdraw)
    emc.md, emc.json           kicad-happy EMC pre-compliance findings (leads only)   ([outputs].emc)
    panel/                     KiKit panel, its DRC and render                        ([outputs].panel = "self")
    packet.md                  index: gate results, metrics, diff summary, open decisions, what to look at

Optional outputs whose tool is not installed are skipped with an install hint in packet.md.

usage: python3 pcbkit/review.py [--config pcb.toml] [--base main] [--no-gate]
"""
import argparse, json, shutil, subprocess, sys, tempfile, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import extras  # noqa: E402
from common import kicad_cli  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description='Build a review packet')
    ap.add_argument('--config'); ap.add_argument('--base'); ap.add_argument('--no-gate', action='store_true')
    a = ap.parse_args()
    p = common.Project(a.config)
    opts = extras.outputs(p)
    out = p.root / 'reports' / 'review'
    if out.exists():
        shutil.rmtree(out)                   # generated; never mix files from an earlier revision
    out.mkdir(parents=True)
    lines = [f'# 审查包：{p.name} {p.section("project").get("revision", "")}', '']
    # gate
    if not a.no_gate:
        subprocess.run([sys.executable, str(Path(__file__).with_name('gate.py')), '--config', str(p.cfg_path), '--out', 'reports'],
                       cwd=p.root, capture_output=True, text=True)
    summary = p.root / 'reports' / 'summary.json'
    if summary.exists():
        s = json.loads(summary.read_text())
        (out / 'gate.json').write_text(json.dumps(s, indent=1, ensure_ascii=False) + '\n')
        lines += ['## 门禁', '', '| 检查 | 结果 | 说明 |', '| --- | --- | --- |']
        lines += [f"| {r['check']} | {r['status']} | {r['detail'][:160]} |" for r in s['results']] + ['']
    m = p.root / 'reports' / 'metrics.json'
    if m.exists():
        vals = json.loads(m.read_text())['values']
        lines += ['## 指标数值', '', '```json', json.dumps(vals, ensure_ascii=False, indent=1)[:3000], '```', '']
    # renders and plots
    if p.pcb and p.pcb.exists():
        for side in ('top', 'bottom'):
            kicad_cli('pcb', 'render', '--side', side, '--width', '1600', '--height', '1200', '--quality', 'basic',
                      '-o', out / f'{side}.png', p.pcb, cwd=p.root)
        cu = common.copper_layers(p.pcb)
        kicad_cli('pcb', 'export', 'pdf', '--mode-multipage', '--layers', ','.join(cu + ['F.Silkscreen', 'B.Silkscreen', 'F.Fab', 'B.Fab']),
                  '--common-layers', 'Edge.Cuts', '--include-border-title', '-o', out / 'pcb.pdf', p.pcb, cwd=p.root)
        lines += ['## 图', '', '- `top.png`、`bottom.png`：正反面渲染（看金属壳下走线、盘中孔、丝印、极性、连接器朝向）',
                  '- `pcb.pdf`：各铜层与丝印、装配层', '']
    if p.sch and p.sch.exists():
        kicad_cli('sch', 'export', 'pdf', '-o', out / 'schematic.pdf', p.sch, cwd=p.root)
        lines += ['- `schematic.pdf`：原理图', '']
    # optional outputs (outside tools; advisory, never part of the gate)
    skipped, have_board = [], bool(p.pcb and p.pcb.exists())
    def optional(name, func, *args):
        res, note = extras.attempt(name, func, p, *args)
        if note:
            skipped.append(note)
        return res
    extra = ['## 浏览与辅助（可选输出，不进门禁）', '']
    if opts['kicanvas'] and optional('kicanvas', extras.kicanvas, out / 'kicanvas'):
        extra.append(f'- `kicanvas/`：浏览器里看原理图和 PCB。`python3 -m http.server --directory {p.rel(out / "kicanvas")} 8000`，'
                     '打开 http://localhost:8000/（`file://` 打不开）。KiCanvas 是 alpha，只用来浏览')
    if opts['ibom'] and have_board and optional('ibom', extras.ibom, out / 'ibom.html'):
        extra.append('- `ibom.html`：交互式 BOM，按位号或料号在正反面找器件（双击直接打开）')
    if opts['pcbdraw'] and have_board:
        r = optional('pcbdraw', extras.pcbdraw, out)
        if r:
            extra.append('- `pcbdraw-top.svg`、`pcbdraw-bottom.svg`：文档用的风格化板图'
                         + ''.join(f'；{"正面" if side == "top" else "背面"}只画了焊盘（PcbDraw 图库没有）：{", ".join(u.split(":")[-1] for u in names)}'
                                 for side, names in r['undrawn'].items()))
    if len(extra) > 2:
        lines += extra + ['']
    # panel: shown when the user chose to panelize; otherwise say what is still open
    if opts['panel'] == 'self' and have_board:
        r = optional('panel', extras.panel, out / 'panel')
        if r:
            lines += ['## 拼板（KiKit，`layout/panel.toml`）', '',
                      f"- {'可用' if r['ok'] else '**不可用**'}：{r['boards']} 块，{r['size_mm'][0]} × {r['size_mm'][1]} mm，"
                      f"外框 {r['pieces']} 块，拼板 DRC 违规 {r['drc']['violations']}、未连接 {r['drc']['unconnected_items']}",
                      *[f'  - {x}' for x in r['problems']],
                      '- 看 `panel/top.png`：连接桥是否都在、邮票孔是否避开悬伸器件、工艺边与光学点位置', '']
    elif opts['panel'] == 'ask':
        lines += ['## 拼板：未定', '', '`[outputs].panel = "ask"`：下单前要定自己拼（"self"，KiKit）还是交给板厂（"fab"）。'
                  '这由用户决定，定了写进 DECISIONS。', '']
    # EMC leads
    if opts['emc'] and have_board:
        r = optional('emc', extras.emc, out)
        if r:
            serious = [f for f in r['findings'] if f.get('severity') in ('critical', 'error', 'high', 'warning')]
            lines += [f'## EMC 预检（kicad-happy {extras.KICAD_HAPPY_TAG}，规则式，只作线索）', '', r['summary'], '',
                      '逐条核实：成立的改设计或写成指标；不成立的在审查记录里写理由。全部发现见 `emc.md`。', '']
            if serious:
                lines += ['| 严重度 | 规则 | 问题 | 涉及 |', '| --- | --- | --- | --- |']
                lines += [f"| {f.get('severity')} | {f.get('rule_id')} | {extras._cell(f.get('title'))} "
                          f"| {extras._cell(', '.join((f.get('components') or []) + (f.get('nets') or []))[:80])} |" for f in serious[:15]]
                lines += ([f'| … | | 另有 {len(serious) - 15} 条，见 emc.md | |'] if len(serious) > 15 else []) + ['']
    if skipped:
        lines += ['## 跳过的可选输出', ''] + [f'- {s}' for s in skipped] + ['']
    # diff against a base revision
    if a.base and p.pcb:
        rel = p.rel(p.pcb)
        r = subprocess.run(['git', 'show', f'{a.base}:{rel}'], cwd=p.root, capture_output=True)
        if r.returncode == 0:
            with tempfile.NamedTemporaryFile(suffix='.kicad_pcb') as t:
                t.write(r.stdout); t.flush()
                d = subprocess.run([sys.executable, str(Path(__file__).with_name('board_diff.py')), t.name, str(p.pcb), '--json', str(out / 'diff.json')],
                                   cwd=p.root, capture_output=True, text=True)
            if (out / 'diff.json').exists():
                dd = json.loads((out / 'diff.json').read_text())
                lines += [f'## 与 {a.base} 的版图差异', '',
                          f"- 器件：新增 {dd['footprints_added']}，删除 {dd['footprints_removed']}，移动/旋转 {dd['moved_or_rotated'][:30]}",
                          f"- 走线：+{dd['tracks']['added']} / -{dd['tracks']['removed']}（网络 {dd['tracks']['nets'][:20]}）；过孔 +{dd['vias']['added']} / -{dd['vias']['removed']}",
                          f"- 焊盘铜皮变化的器件：{dd['pads']['refs'][:30]}；板框变化：{dd['board_outline_changed']}", '']
        else:
            lines += [f'（{a.base} 中没有 {rel}，跳过版图差异）', '']
    # caveats from datasheet facts
    cav = ['# 数据手册注意事项与布局建议（来自 data/parts/*/facts.toml）', '']
    for f in sorted((p.root / 'data' / 'parts').glob('*/facts.toml')):
        facts = tomllib.loads(f.read_text(encoding='utf-8'))
        items = [('注意', c) for c in facts.get('caveat', [])] + [('布局', c) for c in facts.get('layout', [])]
        if items:
            cav.append(f"## {facts.get('part', {}).get('mpn', f.parent.name)}（{facts.get('part', {}).get('revision', '')}）")
            cav += [f"- {kind}（p.{c.get('page')}）：{c.get('text')}" for kind, c in items] + ['']
    (out / 'caveats.md').write_text('\n'.join(cav) + '\n', encoding='utf-8')
    lines += ['## 要逐条核对的数据手册注意事项', '', '见 `caveats.md`。', '']
    dec = p.root / 'docs' / 'DECISIONS.md'
    if dec.exists():
        heads = [l for l in dec.read_text(encoding='utf-8').splitlines() if l.startswith('## D-')]
        lines += ['## 设计决定（核对每条例外和阈值放宽都有出处）', ''] + [f'- {h[3:]}' for h in heads] + ['']
    lines += ['## 审查清单', '', '按 `docs/REVIEW-CHECKLIST.md` 逐项核对，结论写入 `docs/reviews/YYYY-MM-DD-<阶段>.md`（严重度：阻断 / 应改 / 建议 / 待确认）。']
    (out / 'packet.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{p.rel(out)}: ' + ', '.join(sorted(x.name for x in out.iterdir())))
    for s in skipped:
        print('  - ' + s)


if __name__ == '__main__':
    main()
