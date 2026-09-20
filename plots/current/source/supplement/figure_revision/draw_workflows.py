"""Vector ECRC workflow diagrams with semantic pastel fills; examples are illustrative.

Run from any directory: python draw_workflows.py
Requires matplotlib. No API/model call and no experimental data are generated.
"""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[1]
OUT = PAPER / 'figures'
WIDTH = 16.51
FONT = 'Arial'
CLIENT_BLUE = '#EDF5FC'
SERVICE_PURPLE = '#F3EEFA'
font_manager.findfont(FONT, fallback_to_default=False)
plt.rcParams.update({'font.family': FONT, 'font.size': 10,
    'text.color': 'black', 'pdf.fonttype': 42, 'ps.fonttype': 42,
    'svg.fonttype': 'none', 'savefig.facecolor': 'white', 'mathtext.fontset': 'dejavusans'})


def setup(height):
    fig = plt.figure(figsize=(WIDTH / 2.54, height / 2.54), facecolor='white')
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set(xlim=(0, WIDTH), ylim=(0, height)); ax.axis('off')
    ax._labels = []
    return fig, ax


def text(ax, x, y, value, size=10, bold=False, align='center'):
    t = ax.text(x, y, value, fontsize=size, fontweight='bold' if bold else 'normal',
                color='black', ha=align, va='center', linespacing=1.18, zorder=4)
    ax._labels.append(t)
    return t


def line(ax, points, dashed=False, width=.9, zorder=1):
    xs, ys = zip(*points)
    ax.plot(xs, ys, color='black', linewidth=width,
            linestyle=(0, (4, 3)) if dashed else '-', zorder=zorder)


def arrow(ax, start, end, dashed=False, width=1.0):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=10,
        color='black', linewidth=width, linestyle=(0, (4, 3)) if dashed else '-',
        shrinkA=0, shrinkB=0, zorder=2))


def elbow(ax, points, dashed=False):
    line(ax, points[:-1], dashed=dashed)
    arrow(ax, points[-2], points[-1], dashed=dashed)


def box(ax, x, y, w, h, dashed=False, width=.95, zorder=3, fill='white'):
    ax.add_patch(Rectangle((x, y), w, h, edgecolor='black', facecolor=fill,
                           linewidth=width, linestyle=(0, (4, 3)) if dashed else '-', zorder=zorder))


def fig1():
    fig, ax = setup(9.4)
    text(ax, .25, 9.03, '(a) Missing evidence', 11, True, 'left')
    text(ax, 5.90, 9.03, '(b) Unknown outcome (K = 1)', 11, True, 'left')
    line(ax, [(5.45, .45), (5.45, 8.65)], width=.75)
    # The permission example is independent of the recovery example on the right.
    box(ax, .45, 6.90, 4.55, 1.25)
    text(ax, 2.725, 7.71, 'Cancel X', 10.5, True)
    text(ax, 2.725, 7.22, 'No qualifying evidence', 10)
    arrow(ax, (2.725, 6.90), (2.725, 5.90))
    box(ax, .45, 4.65, 4.55, 1.25, width=1.35, fill=CLIENT_BLUE)
    text(ax, 2.725, 5.43, 'No cancel permit', 10.5, True)
    text(ax, 2.725, 4.96, 'No unit reserved', 10)
    arrow(ax, (2.725, 4.65), (2.725, 3.65))
    box(ax, .45, 2.70, 4.55, .95)
    text(ax, 2.725, 3.175, 'No cancellation call', 10.5, True)

    client, service = 8.32, 14.43
    text(ax, client, 8.37, 'ECRC client', 10.5, True)
    text(ax, service, 8.37, 'Service', 10.5, True)
    line(ax, [(client, 7.97), (client, .80)], dashed=True, width=.8)
    line(ax, [(service, 7.97), (service, 1.15)], dashed=True, width=.8)
    box(ax, 6.12, 7.20, 4.40, .62, fill=CLIENT_BLUE)
    text(ax, client, 7.51, 'Permit + arm A', 10)
    arrow(ax, (client, 6.88), (service, 6.88))
    text(ax, 11.35, 7.20, 'Cancel A', 10)
    # Service-effect and return annotations remain explicit, with no small subtitles.
    box(ax, 13.29, 6.04, 2.28, .58, fill=SERVICE_PURPLE)
    text(ax, service, 6.33, 'Effect A', 10, True)
    arrow(ax, (service, 5.63), (client, 5.63), dashed=True)
    text(ax, 11.35, 5.98, 'Reply lost', 10)
    line(ax, [(11.20, 5.49), (11.47, 5.77)], width=1.35, zorder=5)
    line(ax, [(11.20, 5.77), (11.47, 5.49)], width=1.35, zorder=5)
    box(ax, 5.90, 4.04, 4.84, 1.10, width=1.35, fill=CLIENT_BLUE)
    text(ax, client, 4.80, 'Qualified B: blocked', 10, True)
    text(ax, client, 4.35, 'A retains the sole unit', 10)
    arrow(ax, (client, 3.12), (service, 3.12))
    text(ax, 11.35, 3.48, 'Retry A (same ID)', 10)
    arrow(ax, (service, 2.08), (client, 2.08), dashed=True)
    text(ax, 11.35, 2.44, 'Original result', 10)
    box(ax, 5.99, .65, 4.66, 1.02, width=1.35, fill=CLIENT_BLUE)
    text(ax, client, 1.36, 'Record receipt', 10, True)
    text(ax, client, .94, '1 unit remains spent', 10)
    return fig, ax, {'kind': 'constructed_semantic_example', 'observations': False,
        'assumptions': ['K=1 cumulative action unit', 'X lacks evidence; A and B qualify',
                        'A is armed before dispatch; service result retrieval reuses its ID'],
        'preserved_claims': ['No permission for X', 'A persists despite lost reply',
                            'B cannot use A\'s retained unit', 'Recovery does not refill budget'],
        'panel_b_layout': 'Message sequence; vertical position indicates event order, not duration'}


def fig2():
    fig, ax = setup(11.45)
    # Enclosures distinguish state owners, rather than decorate every text fragment.
    box(ax, .15, .15, 10.10, 11.10, dashed=True, width=.85, zorder=0, fill=CLIENT_BLUE)
    box(ax, 10.70, .15, 5.66, 11.10, dashed=True, width=.85, zorder=0, fill=SERVICE_PURPLE)
    text(ax, .46, 10.87, 'Client', 11, True, 'left')
    text(ax, 10.99, 10.87, 'Independent service', 11, True, 'left')
    for x, label in [(2.00, 'Evidence\nmetadata'), (5.18, 'Configured\npolicy'), (8.36, 'Cumulative\nbudget')]:
        text(ax, x, 10.13, label, 10)
    arrow(ax, (2.00, 9.62), (3.20, 9.27))
    arrow(ax, (5.18, 9.62), (5.18, 9.27))
    arrow(ax, (8.36, 9.62), (7.16, 9.27))
    box(ax, 1.03, 8.05, 8.30, 1.22, width=1.20)
    text(ax, 5.18, 8.88, '1  Qualify + issue final permit', 11, True)
    text(ax, 5.18, 8.37, 'Final route + claims; reservation if action', 10)
    arrow(ax, (3.45, 8.05), (3.45, 5.45))
    text(ax, 2.14, 6.80, 'Action\nroute', 10)
    arrow(ax, (8.13, 8.05), (8.13, 7.68))
    box(ax, 6.35, 6.72, 3.56, .96)
    text(ax, 8.13, 7.42, 'Non-action permit', 10, True)
    text(ax, 8.13, 7.00, 'No dispatch', 10)
    arrow(ax, (3.45, 6.10), (6.35, 6.10))
    box(ax, 6.35, 5.62, 3.56, .96)
    text(ax, 8.13, 6.33, 'Unarmed expiry', 10, True)
    text(ax, 8.13, 5.90, 'Cancel + release', 10)
    box(ax, .70, 4.00, 5.65, 1.45, width=1.20)
    text(ax, 3.525, 5.10, '2  Arm', 11, True)
    text(ax, 3.525, 4.49, 'Irrevocable grant\nStable ID + bound intent', 10)
    arrow(ax, (6.35, 4.72), (11.12, 4.72))
    text(ax, 8.72, 5.07, 'ID + payload', 10)
    box(ax, 11.12, 3.12, 4.82, 3.20, width=1.20)
    text(ax, 13.53, 5.97, '3  Execute / retrieve', 10.5, True)
    text(ax, 13.53, 5.38, 'New ID: persist', 10)
    text(ax, 13.53, 4.98, 'effect + result together', 10)
    line(ax, [(11.40, 4.62), (15.65, 4.62)], width=.7, zorder=4)
    text(ax, 13.53, 4.17, 'Same ID + payload:', 10)
    text(ax, 13.53, 3.76, 'return stored result', 10)
    arrow(ax, (8.25, 4.68), (8.25, 3.55), dashed=True)
    box(ax, 6.50, 2.50, 3.50, 1.05)
    text(ax, 8.25, 3.21, 'Result unknown', 10, True)
    text(ax, 8.25, 2.77, 'Retain unit', 10)
    elbow(ax, [(10.00, 3.02), (10.47, 3.02), (10.47, 4.39), (11.12, 4.39)], dashed=True)
    # No cancellation edge exists after arm; recovery reuses the original operation.
    box(ax, .70, .60, 5.65, 1.55, width=1.20)
    text(ax, 3.525, 1.83, '4  Reconcile receipt', 11, True)
    text(ax, 3.525, 1.35, 'Held becomes committed', 10)
    text(ax, 3.525, .91, 'Budget remains spent', 10)
    elbow(ax, [(13.53, 3.12), (13.53, 1.38), (6.35, 1.38)])
    text(ax, 8.28, 1.76, 'Matching result', 10)
    return fig, ax, {'kind': 'contract_lifecycle_schematic', 'observations': False,
        'main_path': ['Final permission', 'Irrevocable arm', 'Execute or retrieve', 'Receipt reconciliation'],
        'recovery': 'Keep armed unit; retry original ID and payload',
        'pre_arm_expiry': 'Cancel and release before arm',
        'non_action': 'Final non-action permit cannot dispatch',
        'transaction_scope': 'Separate local client and service transactions; no global transaction',
        'dashed_enclosures': 'Independent persistence owners', 'dashed_arrows': 'Unknown outcome and retry'}


def main():
    OUT.mkdir(exist_ok=True)
    manifest = {'font': FONT, 'minimum_font_pt': 10, 'width_cm': WIDTH,
                'text_and_lines': '#000000', 'background': '#FFFFFF',
                'semantic_fills': {'client_permission_and_ledger': CLIENT_BLUE,
                                   'independent_service_and_effect': SERVICE_PURPLE},
                'color_is_redundant_with_labels_and_enclosures': True, 'figures': {}}
    for n, create in [(1, fig1), (2, fig2)]:
        fig, ax, semantics = create()
        fig.canvas.draw(); renderer = fig.canvas.get_renderer()
        outside = [t.get_text() for t in ax._labels if not (
            fig.bbox.contains(t.get_window_extent(renderer).x0, t.get_window_extent(renderer).y0)
            and fig.bbox.contains(t.get_window_extent(renderer).x1, t.get_window_extent(renderer).y1))]
        assert not outside, outside
        paths = {}
        for ext in ['pdf', 'svg', 'png']:
            path = OUT / f'fig{n}.{ext}'
            kwargs = {'dpi': 220} if ext == 'png' else {}
            if ext == 'pdf': kwargs['metadata'] = {'Title': '', 'CreationDate': None, 'ModDate': None}
            fig.savefig(path, **kwargs); paths[ext] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['figures'][str(n)] = {'semantics': semantics, 'sha256': paths,
            'text_count': len(ax._labels), 'height_cm': float(fig.get_figheight()*2.54)}
        plt.close(fig)
    manifest['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (HERE / 'WORKFLOW_PROVENANCE.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output_directory': str(OUT), 'minimum_font_pt': 10,
                     'color': 'black text and lines; pale blue client and pale purple service fills'}))


if __name__ == '__main__':
    main()
