"""Read/export QA; renders actual PDFs and never reruns scientific analyses."""
from pathlib import Path
import csv, hashlib, json
import pymupdf as fitz
from PIL import Image

HERE=Path(__file__).resolve().parent
manifest=json.loads((HERE/'build_manifest.json').read_text())
records=[]
for item in manifest['outputs']:
    path=HERE/item['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
    if path.suffix=='.pdf':
        doc=fitz.open(path);assert len(doc)==1;page=doc[0]
        assert abs(page.rect.width-6.6*72)<.01
        spans=[s for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for s in line['spans'] if s['text'].strip()]
        assert min(s['size'] for s in spans)>=9.49 and max(s['size'] for s in spans)<=11.01
        outside=[{'text':s['text'],'bbox':s['bbox']} for s in spans if s['bbox'][0]<-.5 or s['bbox'][1]<-.5 or s['bbox'][2]>page.rect.width+.5 or s['bbox'][3]>page.rect.height+.5]
        fonts=[]
        for font in page.get_fonts(full=True):
            basename,extension,kind,content=doc.extract_font(font[0]);assert content and extension in ('ttf','cff','otf')
            fonts.append(dict(name=basename,type=kind,embedded_bytes=len(content)))
        assert not outside,(path,outside)
        page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False).save(HERE/'review'/(path.stem+'.png'))
        overlaps=[]
        for i,a in enumerate(spans):
            for c in spans[i+1:]:
                aa,bb=fitz.Rect(a['bbox']),fitz.Rect(c['bbox']);inter=aa&bb
                if not inter.is_empty and inter.get_area()/min(aa.get_area(),bb.get_area())>.20:
                    overlaps.append([a['text'],c['text']])
        records.append(dict(path=item['path'],width_inches=page.rect.width/72,height_inches=page.rect.height/72,
                            minimum_font_pt=min(s['size'] for s in spans),maximum_font_pt=max(s['size'] for s in spans),all_text_black=all(s['color']==0 for s in spans),
                            fonts=fonts,text_outside_page=outside,potential_text_overlaps=overlaps))
    elif path.suffix in ('.png','.tiff'):
        with Image.open(path) as im:
            assert abs(im.size[0]-6.6*600)<2
            assert abs(im.info.get('dpi',(0,0))[0]-600)<1
snapshots=json.loads((HERE/'data/input_manifest.json').read_text())
assert all(hashlib.sha256((HERE/r['snapshot']).read_bytes()).hexdigest()==r['sha256'] for r in snapshots)
with (HERE/'data/fig3_plot_data.csv').open() as f: state=list(csv.DictReader(f))
with (HERE/'data/fig5_plot_data.csv').open() as f: online=list(csv.DictReader(f))
report=dict(pdfs=records,source_snapshots_unchanged=True,fig3_cells=len(state),fig3_all_six_observations_common=all(r['min']==r['max'] and r['n_observations']=='6' for r in state),
            fig5_estimates=len(online),fig5_pooled_estimates=sum(r['estimand']=='pooled' for r in online),fig5_participant_equal_estimates=sum(r['estimand']=='participant_equal_common_valid' for r in online),
            minimum_font_at_6_4_inches=9.5*6.4/6.6,visual_inspection_record='VISUAL_REVIEW.json (separate agent review)')
(HERE/'EXPORT_QA.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
