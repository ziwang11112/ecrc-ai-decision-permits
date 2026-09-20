"""Render the three current technical figures into a fresh directory."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Fresh output directory')
    parser.add_argument('--font', default='Arial', help='Paper font is Arial; e.g. DejaVu Sans permits a layout variant on Linux')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error('Choose a fresh output directory')
    if out.is_relative_to(HERE):
        parser.error('Keep generated figures outside the tracked source folder')
    for record in json.loads((HERE/'SOURCE_MANIFEST.json').read_text())['files']:
        if hashlib.sha256((HERE/record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Source hash mismatch: '+record['path'])
    from matplotlib import font_manager
    font_manager.findfont(args.font, fallback_to_default=False)
    shutil.copytree(HERE/'source',out)
    (out/'figures').mkdir()
    drawing = out/'supplement/figure_revision'
    scripts = [drawing/'draw_workflows.py',drawing/'counterexample/draw_effect_counterexample.py']
    for script in scripts:
        if args.font != 'Arial':
            text = script.read_text().replace("FONT = 'Arial'", 'FONT = '+repr(args.font))
            text = text.replace('"font.family": "Arial"','"font.family": '+repr(args.font))
            text = text.replace('"font_family": "Arial"','"font_family": '+repr(args.font))
            script.write_text(text)
        subprocess.run([sys.executable,'-B',str(script)],check=True,cwd=out)
    report={'font':args.font,'paper_font':args.font=='Arial','new_experiments':0,
            'figures':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((out/'figures').glob('*.pdf'))}}
    if len(report['figures']) != 3:
        raise ValueError('Expected exactly three figure PDFs')
    (out/'FIGURE_BUILD.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
