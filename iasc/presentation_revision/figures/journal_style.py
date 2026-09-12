"""Shared 6.6-inch journal figure style; local Matplotlib only."""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
BLUE = '#24557A'
GREY = '#6E6E6E'
PALE = '#E7EEF3'
WIDTH = 6.6


def configure():
    for font in (Path('C:/Windows/Fonts/arial.ttf'), Path('C:/Windows/Fonts/arialbd.ttf')):
        if font.exists():
            font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family': 'Arial', 'font.size': 10,
                         'text.color': 'black', 'axes.labelcolor': 'black',
                         'xtick.color': 'black', 'ytick.color': 'black',
                         'axes.titlesize': 10, 'axes.labelsize': 10,
                         'xtick.labelsize': 9.5, 'ytick.labelsize': 9.5,
                         'legend.fontsize': 9.5, 'axes.linewidth': .6,
                         'lines.linewidth': 1, 'lines.markersize': 4,
                         'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'path', 'svg.hashsalt': 'iasc-restructure-20260912',
                         'savefig.facecolor': 'white', 'figure.facecolor': 'white'})


def clean_axes(ax):
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(width=.6, length=3)


def save(fig, number, name):
    output = HERE / 'exports'
    output.mkdir(parents=True, exist_ok=True)
    stem = f'fig{number}_{name}'
    items = []
    for extension in ('pdf', 'svg', 'png', 'tiff'):
        target = output / (stem + '.' + extension)
        options = {'dpi': 600}
        if extension == 'pdf':
            options['metadata'] = {'CreationDate': None, 'ModDate': None, 'Creator': 'Matplotlib; frozen source data'}
        if extension == 'svg':
            options['metadata'] = {'Date': None}
        if extension == 'tiff':
            options['pil_kwargs'] = {'compression': 'tiff_lzw'}
        fig.savefig(target, **options)
        items.append({'path': target.relative_to(HERE).as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': target.stat().st_size})
    # Convenient review raster is separate from publication outputs.
    review = HERE / 'review'
    review.mkdir(exist_ok=True)
    fig.savefig(review / (stem + '.png'), dpi=180)
    text_rows = [{'text': obj.get_text(), 'font_size_pt': obj.get_fontsize()}
                 for obj in fig.findobj(matplotlib.text.Text) if obj.get_text()]
    assert min(r['font_size_pt'] for r in text_rows) >= 9.5, text_rows
    (review / (stem + '_text_inventory.json')).write_text(json.dumps(text_rows, indent=2) + '\n', encoding='utf-8')
    plt.close(fig)
    return items
