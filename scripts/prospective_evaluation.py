"""Freeze, then run once, an internally generated synthetic evaluation.

This local file guard is not a signature, third-party registration, field trial,
or protection against an operator deliberately replacing files. Do not tune on
its result. A failed/consumed run remains recorded; use a documented new protocol.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import secrets
import uuid

from scripts import benchmark_pipeline as benchmark

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'halo-prospective-synthetic-protocol-1'
SCOPE = ('Previously unused internally generated synthetic seeds under a local frozen protocol. '
         'Not externally supplied data, third-party preregistration, field validation, or a prospective physical trial.')


def timestamp(): return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def known_seeds(reports):
    # Explicit historical/development ranges also cover outputs moved to archives.
    found = set(range(3101, 3113)) | set(range(88001, 88025)) | set(range(91001, 91025))
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'seed' and isinstance(item, int): found.add(item)
                elif key == 'seeds' and isinstance(item, list): found.update(x for x in item if isinstance(x, int))
                else: collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    for path in sorted(Path(reports).rglob('*.json')):
        collect(json.loads(path.read_text(encoding='utf-8-sig')))
    return found


def choose_seeds(excluded, count):
    if not 1 <= count <= 100: raise ValueError('Use between 1 and 100 paired seeds.')
    chosen = set()
    while len(chosen) < count:
        seed = 10_000_000 + secrets.randbelow(1_990_000_000)
        if seed not in excluded: chosen.add(seed)
    return sorted(chosen)


def freeze(path, *, count=24, reports=None):
    path = Path(path)
    if path.exists(): raise FileExistsError('Protocol exists; frozen protocols cannot be overwritten.')
    excluded = known_seeds(reports or ROOT/'reports')
    seeds = choose_seeds(excluded, count)
    protocol = {
        'version': VERSION, 'created_at': timestamp(), 'scope': SCOPE,
        'no_tuning_rule': 'Do not modify numerical code, thresholds, metrics or scenarios using this result. '
                          'Once viewed, these seeds become known regression cases. Report every miss, hold and failed run.',
        'source_sha256': benchmark.source_hashes(), 'pipeline_version': benchmark.observer.VERSION,
        'seeds': seeds, 'seed_selection': 'Cryptographically random unused integer seeds selected before generation; '
                                        'excludes reported seeds and explicit historical/development ranges.',
        'known_seed_count_at_freeze': len(excluded),
        'known_seed_set_sha256': digest(sorted(excluded)),
        'method': {'families': list(benchmark.FAMILIES), 'scenarios': list((*benchmark.SCENARIOS, *benchmark.MIXED)),
                   'case_count': count*len(benchmark.FAMILIES)*len((*benchmark.SCENARIOS, *benchmark.MIXED)),
                   'origins_min': [75, 90, 105, 120, 135, 150], 'horizons_min': [5, 15, 30],
                   'decision_minutes_inclusive': [70, 180], 'healthy_prefix_rows': 70,
                   'initial_settings': benchmark.core.Settings().model_dump(),
                   'comparators': list(benchmark.COMPARATORS),
                   'reported_outcomes': ['paired critical-warning lead time and missing warnings',
                       'expected signal-set completion and any-warning recall', 'inactive alarm burden',
                       'forecast coverage, paired persistence, absolute/signed error tails and subgroups'],
                   'validation_scope': 'Only 5/15/30-minute observation forecasts are scored against independent '
                       'synthetic plants. Scenario-informed 240-minute action planning remains a separate internal '
                       'consistency exercise. No confidence interval, economic effect or field safety claim.'},
    }
    protocol['sha256'] = digest(protocol)
    write_new(path, protocol)
    return protocol


def checked_protocol(path):
    protocol = json.loads(Path(path).read_text(encoding='utf-8'))
    if protocol.get('version') != VERSION or digest({k: v for k, v in protocol.items() if k != 'sha256'}) != protocol.get('sha256'):
        raise ValueError('Protocol digest/version mismatch.')
    seeds = protocol['seeds']
    if not seeds or len(seeds) != len(set(seeds)) or any(type(s) is not int for s in seeds):
        raise ValueError('Protocol seeds must be distinct integers.')
    if benchmark.source_hashes() != protocol['source_sha256']:
        raise ValueError('Evaluation source changed after freeze. Do not run this protocol or relabel it as fresh.')
    if benchmark.observer.VERSION != protocol['pipeline_version']:
        raise ValueError('Assessor version changed after freeze.')
    return protocol


def run(path):
    path = Path(path)
    protocol = checked_protocol(path)
    claim_path = path.with_name(path.stem+'-claim.json')
    output = path.with_name(path.stem+'-run')
    claim = {'run_id': 'EVAL-'+uuid.uuid4().hex, 'started_at': timestamp(),
             'protocol_sha256': protocol['sha256'], 'scope': SCOPE}
    # Exclusive creation is the one-run gate, including failed or interrupted runs.
    write_new(claim_path, claim)
    output.mkdir(exist_ok=False)
    try:
        report, forecasts, decisions = benchmark.evaluate('prospective_synthetic', seeds=protocol['seeds'],
            protocol_binding={'sha256': protocol['sha256'], 'run_id': claim['run_id'],
                              'started_at': claim['started_at'], 'protocol_file': path.name})
        checked_protocol(path)
        if report['source_sha256'] != protocol['source_sha256']:
            raise ValueError('Report source differs from the frozen protocol.')
        write_new(output/'benchmark.json', report)
        for name, rows in [('forecasts.csv', forecasts), ('decisions.csv', decisions)]:
            if not rows: raise ValueError('Evaluation emitted no scoring records.')
            with (output/name).open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        manifest = {**claim, 'completed_at': timestamp(), 'status': 'complete',
                    'source_sha256': protocol['source_sha256'],
                    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())},
                    'note': 'Protocol, claim and report bind one local run. Hashes detect changes against retained '
                            'copies, not authorship. The result is now known; do not tune and rerun these seeds as fresh.'}
        manifest['sha256'] = digest(manifest)
        write_new(output/'manifest.json', manifest)
        return manifest
    except BaseException as error:
        write_new(output/'failed.json', {**claim, 'failed_at': timestamp(), 'status': 'failed_or_interrupted',
                                       'error_type': type(error).__name__,
                                       'note': 'The claim remains consumed. Preserve this failure; no automatic retry or seed replacement.'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    make = commands.add_parser('freeze'); make.add_argument('--protocol', type=Path, required=True); make.add_argument('--seeds', type=int, default=24)
    execute = commands.add_parser('run'); execute.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    result = freeze(args.protocol, count=args.seeds) if args.action == 'freeze' else run(args.protocol)
    print(json.dumps(result, indent=2, allow_nan=False))
