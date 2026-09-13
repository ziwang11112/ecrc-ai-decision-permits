"""Verify and summarize saved latency, application and cap-precision results.

Standard library only. Reaggregates saved latency observations and compares all
formatted output rows with the saved expected CSVs. No measurement, model
fitting or resampling occurs. Without --out, verification writes no files.
"""
from pathlib import Path
from decimal import Decimal
from statistics import median
import argparse
import csv
import hashlib
import io
import json

ROOT = Path(__file__).resolve().parent.parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def rows(name):
    with (ROOT / 'data' / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def encode_csv(records):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Optional fresh directory for CSV summaries and verification JSON')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    required = {'data/S6_performance_runs.csv', 'data/S6_performance_summary.csv',
                'data/S9_cells.csv', 'data/cap_removal_complete.csv',
                'expected/latency_summary.csv', 'expected/application_summary.csv',
                'expected/cap_precision_summary.csv'}
    matched = [r for r in manifest['sources'] if r['standalone_path'] in required]
    require(len(matched) == len(required) and {r['standalone_path'] for r in matched} == required,
            'Source manifest must identify all required numeric inputs and expected outputs')
    for record in matched:
        blob = (ROOT / record['standalone_path']).read_bytes()
        require(hashlib.sha256(blob).hexdigest() == record['standalone_sha256'],
                'Source hash mismatch: ' + record['standalone_path'])

    runs, saved_summary = rows('S6_performance_runs.csv'), rows('S6_performance_summary.csv')
    require(len(runs) == 30 and len(saved_summary) == 6, 'Latency source condition counts')
    require(all(r['n_timed_requests'] == '64' for r in runs), 'Latency request counts')
    by_summary = {(r['arm'], int(r['workers'])): r for r in saved_summary}
    require(len(by_summary) == 6, 'Duplicate latency summary condition')
    latency = []
    for workers in (1, 4, 8):
        record = {'workers': str(workers)}
        for arm in ('ecrc', 'ordinary'):
            cell = [r for r in runs if r['arm'] == arm and int(r['workers']) == workers]
            require(len(cell) == 5 and {int(r['rep']) for r in cell} == set(range(1, 6)),
                    'Five distinct saved latency repetitions required')
            values = [Decimal(r['p95_latency_ms']) for r in cell]
            stats = {'median': median(values), 'min': min(values), 'max': max(values)}
            saved = by_summary[arm, workers]
            require(saved['repetitions'] == '5', 'Saved latency repetition count')
            for key, value in stats.items():
                require(value == Decimal(saved[f'p95_latency_ms_{key}']), 'Saved latency aggregate differs')
                record[f'{arm}_{key}_ms'] = f'{value:.1f}'
        latency.append(record)

    source_application = rows('S9_cells.csv')
    by_application = {(r['condition'], r['policy'], r['arm']): r for r in source_application}
    require(len(source_application) == len(by_application) == 8, 'Eight unique application cells required')
    application = []
    for condition, response in [('normal', 'Normal'), ('response_loss', 'Loss')]:
        for policy, policy_label in [('depth_first', 'Depth-first'), ('round_robin', 'Round-robin')]:
            for arm, client in [('ecrc', 'ECRC'), ('ordinary', 'Ordinary')]:
                row = by_application[condition, policy, arm]
                require(row['batches'] == '18' and row['eligible_tasks'] == '144', 'Application cell denominators')
                application.append({'response': response, 'policy': policy_label, 'client': client,
                                    'timely': row['timely_tasks'], 'eventual': row['eventual_pass_tasks'],
                                    'jobs': row['jobs'], 'launcher_seconds': f"{Decimal(row['launcher_wall_seconds']):.2f}"})

    source_cap = rows('cap_removal_complete.csv')
    expected_conditions = {(c, m) for c in ('Development', 'External')
                           for m in ('hist_gradient_boosting', 'regularised_logistic', 'history_baseline')}
    require(len(source_cap) == 6 and {(r['cohort'], r['model_name']) for r in source_cap} == expected_conditions,
            'Six unique cap-removal conditions required')
    precision = []
    for row in source_cap:
        low_places = 5 if row['cohort'] == 'External' and row['model_name'] == 'hist_gradient_boosting' else 3
        precision.append({'cohort': row['cohort'], 'generator': row['model_label'], 'n_P': row['n_precision'],
                          'pooled_delta': f"{Decimal(row['pooled_precision_difference']):+.3f}",
                          'participant_equal_delta': f"{Decimal(row['macro_precision_difference']):+.3f}",
                          'ci_low': format(Decimal(row['macro_precision_ci_low']), f'.{low_places}f'),
                          'ci_high': f"{Decimal(row['macro_precision_ci_high']):.3f}"})

    summaries = {'latency_summary.csv': latency, 'application_summary.csv': application,
                 'cap_precision_summary.csv': precision}
    outputs = {name: encode_csv(records) for name, records in summaries.items()}
    for name, blob in outputs.items():
        expected = (ROOT / 'expected' / name).read_bytes()
        require(blob == expected, 'Recomputed summary differs from saved expected CSV rows/format: ' + name)
    report = {'passed': True, 'summary_rows_checked': 17,
              'source_hashes_checked': {r['standalone_path']: r['standalone_sha256'] for r in matched},
              'expected_csv_bytes_equal': {name: True for name in outputs},
              'output_sha256': {name: hashlib.sha256(blob).hexdigest() for name, blob in outputs.items()},
              'latency': {'run_rows': 30, 'source_summary_rows': 6, 'summary_rows': 3,
                          'p95_aggregates_recomputed': True, 'decimal_places': 1,
                          'range_meaning': 'Minimum/maximum of five run-level p95 observations; not confidence intervals.'},
              'application': {'source_rows': 8, 'summary_rows': 8, 'launcher_decimal_places': 2,
                              'denominator': '144 previously exposed tasks reused across cells; 18 batches per cell.'},
              'cap_precision': {'source_rows': 6, 'summary_rows': 6, 'decimal_places': 3,
                                'exception': 'External HGB lower endpoint retains five places (0.00015).',
                                'intervals': 'Saved conditional intervals; no resampling.'},
              'scope': 'Saved numerical aggregation and complete expected CSV row/format verification.',
              'new_experiments_fitting_or_bootstrap': False}
    if args.out is not None:
        destination = args.out.resolve()
        require(not destination.exists(), 'Use a fresh output directory')
        destination.mkdir(parents=True, exist_ok=False)
        for name, blob in outputs.items():
            with (destination / name).open('xb') as stream:
                stream.write(blob)
        with (destination / 'RESULT_SUMMARY_CHECK.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
