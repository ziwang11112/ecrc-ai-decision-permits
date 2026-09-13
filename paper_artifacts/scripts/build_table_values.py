"""Reconstruct current Tables 2–4 display CSVs from saved numeric inputs.

Uses the Python standard library only. Checks the saved source hashes and every
displayed data row against the included current TeX. No experiment, fitting or
bootstrap is executed. Run with --out NEW_DIRECTORY to keep package bytes intact.
"""
from pathlib import Path
from decimal import Decimal
from statistics import median
import argparse
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent


def rows(name):
    with (ROOT / 'data' / name).open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def emit_csv(path, records):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def check_tex(name, expected_lines):
    lines = [line.strip() for line in (ROOT / 'tables' / name).read_text(encoding='utf-8').splitlines()]
    start, end = lines.index(r'\midrule') + 1, lines.index(r'\bottomrule')
    actual = [line for line in lines[start:end] if line and line != r'\addlinespace']
    assert actual == expected_lines, f'{name}: displayed rows differ from the complete expected rows'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'exports')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    required = {'data/S6_performance_runs.csv', 'data/S6_performance_summary.csv',
                'data/S9_cells.csv', 'data/table5_cap_removal_complete.csv',
                'tables/delivery_cost.tex', 'tables/application_results.tex', 'tables/cap_precision.tex'}
    matched = [r for r in manifest['sources'] if r['standalone_path'] in required]
    assert {r['standalone_path'] for r in matched} == required
    for record in matched:
        assert hashlib.sha256((ROOT / record['standalone_path']).read_bytes()).hexdigest() == record['standalone_sha256']

    # Table 2: reaggregate five saved run-level p95 values per client/thread cell.
    runs, summary = rows('S6_performance_runs.csv'), rows('S6_performance_summary.csv')
    assert len(runs) == 30 and len(summary) == 6
    assert all(r['n_timed_requests'] == '64' for r in runs)
    by_summary = {(r['arm'], int(r['workers'])): r for r in summary}
    table2, lines2 = [], []
    for workers in (1, 4, 8):
        displayed = {'workers': str(workers)}
        rendered = []
        for arm in ('ecrc', 'ordinary'):
            cell = [r for r in runs if r['arm'] == arm and int(r['workers']) == workers]
            assert len(cell) == 5 and {int(r['rep']) for r in cell} == set(range(1, 6))
            values = [Decimal(r['p95_latency_ms']) for r in cell]
            stat = {'median': median(values), 'min': min(values), 'max': max(values)}
            saved = by_summary[arm, workers]
            assert saved['repetitions'] == '5'
            for key, value in stat.items():
                assert value == Decimal(saved[f'p95_latency_ms_{key}'])
                displayed[f'{arm}_{key}_ms'] = f'{value:.1f}'
            rendered.append(f"{stat['median']:.1f} [{stat['min']:.1f}, {stat['max']:.1f}]")
        table2.append(displayed)
        lines2.append(f"{workers} & {rendered[0]} & {rendered[1]}" + r'\\')
    check_tex('delivery_cost.tex', lines2)

    # Table 3: reuse the eight complete saved application cells.
    application = rows('S9_cells.csv')
    by_application = {(r['condition'], r['policy'], r['arm']): r for r in application}
    assert len(application) == len(by_application) == 8
    table3, lines3 = [], []
    for condition, response in [('normal', 'Normal'), ('response_loss', 'Loss')]:
        for policy, policy_label in [('depth_first', 'Depth-first'), ('round_robin', 'Round-robin')]:
            for arm, client in [('ecrc', 'ECRC'), ('ordinary', 'Ordinary')]:
                r = by_application[condition, policy, arm]
                assert r['batches'] == '18' and r['eligible_tasks'] == '144'
                record = {'response': response, 'policy': policy_label, 'client': client,
                          'timely': r['timely_tasks'], 'eventual': r['eventual_pass_tasks'],
                          'jobs': r['jobs'], 'launcher_seconds': f"{Decimal(r['launcher_wall_seconds']):.2f}"}
                table3.append(record)
                lines3.append(' & '.join(record.values()) + r'\\')
    check_tex('application_results.tex', lines3)

    # Table 4: retain the common-valid precision estimand and its saved intervals.
    cap = rows('table5_cap_removal_complete.csv')
    expected = {(c, m) for c in ('Development', 'External')
                for m in ('hist_gradient_boosting', 'regularised_logistic', 'history_baseline')}
    assert len(cap) == 6 and {(r['cohort'], r['model_name']) for r in cap} == expected
    table4, lines4 = [], []
    for r in cap:
        # The current table explicitly preserves this small positive lower limit.
        low_places = 5 if r['cohort'] == 'External' and r['model_name'] == 'hist_gradient_boosting' else 3
        record = {'cohort': r['cohort'], 'generator': r['model_label'], 'n_P': r['n_precision'],
                  'pooled_delta': f"{Decimal(r['pooled_precision_difference']):+.3f}",
                  'participant_equal_delta': f"{Decimal(r['macro_precision_difference']):+.3f}",
                  'ci_low': format(Decimal(r['macro_precision_ci_low']), f'.{low_places}f'),
                  'ci_high': f"{Decimal(r['macro_precision_ci_high']):.3f}"}
        table4.append(record)
        lines4.append(f"{record['cohort']} {record['generator']} & {record['n_P']} & ${record['pooled_delta']}$ & "
                      + '$' + record['participant_equal_delta'] + r'\;[' + record['ci_low'] + ',' + record['ci_high'] + ']$' + r'\\')
    check_tex('cap_precision.tex', lines4)

    args.out.mkdir(parents=True, exist_ok=True)
    for number, records in [(2, table2), (3, table3), (4, table4)]:
        emit_csv(args.out / f'table{number}_display.csv', records)
    report = {'passed': True, 'tables_checked': [2, 3, 4], 'display_rows_checked': 17,
        'source_hashes_checked': {r['standalone_path']: r['standalone_sha256'] for r in matched},
        'table2': {'run_rows': 30, 'summary_rows': 6, 'display_rows': 3,
                   'p95_summary_recomputed_from_saved_run_values': True, 'decimal_places': 1,
                   'range_meaning': 'minimum and maximum of five run-level p95 observations, not confidence intervals'},
        'table3': {'source_rows': 8, 'display_rows': 8, 'launcher_decimal_places': 2},
        'table4': {'source_rows': 6, 'display_rows': 6, 'decimal_places': 3,
                   'exception': 'External HGB lower endpoint displayed to five decimal places, retaining 0.00015.',
                   'intervals': 'Saved conditional intervals reused; no resampling.'},
        'manual_tables_not_numerically_reconstructed': [1, 5],
        'scope': 'All displayed data-row strings matched the included current TeX; captions, conceptual claims and literature judgments are not automatically verified.',
        'new_experiments_fitting_or_bootstrap': False}
    (args.out / 'TABLE_VALUE_CHECK.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
