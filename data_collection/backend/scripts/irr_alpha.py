#!/usr/bin/env python3
"""
Krippendorff's alpha per field from the long-format export.

Reference implementation for the Dataset A inter-rater reliability check.
Reads the CSV produced by GET /api/admin/export/long (one row per
video, move, rater, lens, field), pivots each field into a
raters x units matrix (unit = (video_id, move_id)), and computes alpha with
the `krippendorff` package.

Metric per field:
    ordinal   form_quality, effort_level (integer scales), level of a frame tag
    nominal   everything else (categories, multi-select strings compared as
              whole pipe-joined sets, hold ids)

Missing values (a rater with no row for that unit, or an empty value) are
left as NaN and handled by the package: units rated by fewer than two
raters are dropped, and alpha is undefined (printed as "n/a") when fewer
than two units remain or every value is identical.

Frame tags: the export carries one row per tag with field = tag_type and
value = frame:level:side:locations. Tags are collapsed per (unit, rater)
into "did this rater apply tag_type at all" (nominal yes/no), which is the
question IRR can answer about a free-count annotation; the raw rows are
also summarised by count so the report shows how often each tag was used.

Usage:
    python scripts/irr_alpha.py dynalytix_long.csv
    python scripts/irr_alpha.py dynalytix_long.csv --lens environment
    python scripts/irr_alpha.py dynalytix_long.csv --cohort validated --min-raters 3
    python scripts/irr_alpha.py dynalytix_long.csv --json out.json

Requires: pip install krippendorff numpy
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
    import krippendorff
except ImportError as exc:  # pragma: no cover
    print(f'{exc}. Install with: pip install krippendorff numpy', file=sys.stderr)
    sys.exit(2)

ORDINAL_FIELDS = {'form_quality', 'effort_level'}
FRAME_TAG_LENS = 'frame_tags'

Unit = Tuple[str, str]  # (video_id, move_id)


def read_long(path: str, lens: Optional[str] = None, cohort: Optional[str] = None,
              dataset: Optional[str] = None) -> List[dict]:
    """Rows of the long export, optionally filtered."""
    with open(path, newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    if lens:
        rows = [r for r in rows if r['lens'] == lens]
    if cohort:
        rows = [r for r in rows if r['cohort'] == cohort]
    if dataset:
        rows = [r for r in rows if r['dataset'] == dataset]
    return rows


def pivot(rows: List[dict]) -> Dict[Tuple[str, str], Dict[Unit, Dict[str, str]]]:
    """(lens, field) -> unit -> rater -> value.

    Frame tag rows collapse to presence per tag_type ('1'); absence is
    filled in later for every rater who appears anywhere on that unit.
    """
    table: Dict[Tuple[str, str], Dict[Unit, Dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    raters_on_unit: Dict[Unit, set] = defaultdict(set)

    for r in rows:
        unit = (r['video_id'], r['move_id'])
        raters_on_unit[unit].add(r['rater_user_id'])
        key = (r['lens'], r['field'])
        if r['lens'] == FRAME_TAG_LENS:
            table[key][unit][r['rater_user_id']] = '1'
        else:
            table[key][unit][r['rater_user_id']] = r['value']

    # Frame tags: every rater on the unit who did not apply the tag gets '0'.
    for (lens, _field), units in table.items():
        if lens != FRAME_TAG_LENS:
            continue
        for unit, by_rater in list(units.items()):
            for rater in raters_on_unit[unit]:
                by_rater.setdefault(rater, '0')
    return table


def encode(values: List[Optional[str]], ordinal: bool) -> Tuple[List[float], Dict[str, int]]:
    """Map raw strings to numbers for the package. '' / None -> NaN."""
    if ordinal:
        codes: Dict[str, int] = {}
        out = []
        for v in values:
            if v in (None, ''):
                out.append(np.nan)
            else:
                try:
                    out.append(float(v))
                except ValueError:
                    out.append(np.nan)
        return out, codes
    codes = {}
    out = []
    for v in values:
        if v in (None, ''):
            out.append(np.nan)
            continue
        if v not in codes:
            codes[v] = len(codes)
        out.append(float(codes[v]))
    return out, codes


def alpha_for(units: Dict[Unit, Dict[str, str]], ordinal: bool, min_raters: int = 2) -> dict:
    """Alpha plus the numbers behind it for one field."""
    raters = sorted({r for by_rater in units.values() for r in by_rater})
    kept = {u: v for u, v in units.items() if sum(1 for x in v.values() if x not in (None, '')) >= min_raters}
    summary = {
        'n_units': len(units),
        'n_units_used': len(kept),
        'n_raters': len(raters),
        'metric': 'ordinal' if ordinal else 'nominal',
        'alpha': None,
        'note': '',
    }
    if len(kept) < 2 or len(raters) < 2:
        summary['note'] = 'fewer than 2 units with >=%d raters' % min_raters
        return summary

    unit_order = sorted(kept)
    matrix = []
    codes_all: Dict[str, int] = {}
    for rater in raters:
        row = [kept[u].get(rater) for u in unit_order]
        if ordinal:
            encoded, _ = encode(row, True)
        else:
            # one shared code table across raters
            encoded = []
            for v in row:
                if v in (None, ''):
                    encoded.append(np.nan)
                else:
                    codes_all.setdefault(v, len(codes_all))
                    encoded.append(float(codes_all[v]))
        matrix.append(encoded)

    data = np.array(matrix, dtype=float)
    finite = data[~np.isnan(data)]
    if finite.size == 0 or np.unique(finite).size < 2:
        summary['note'] = 'no variation (every observed value identical)'
        summary['alpha'] = 1.0 if finite.size else None
        return summary
    try:
        value = krippendorff.alpha(
            reliability_data=data,
            level_of_measurement='ordinal' if ordinal else 'nominal',
        )
        summary['alpha'] = None if np.isnan(value) else round(float(value), 4)
    except (ValueError, ZeroDivisionError) as exc:
        summary['note'] = f'undefined: {exc}'
    return summary


def compute(rows: List[dict], min_raters: int = 2) -> List[dict]:
    """One result dict per (lens, field), in export order."""
    results = []
    for (lens, field), units in sorted(pivot(rows).items()):
        ordinal = field in ORDINAL_FIELDS
        summary = alpha_for(units, ordinal, min_raters)
        results.append(dict(lens=lens, field=field, **summary))
    return results


def tag_counts(rows: List[dict]) -> Dict[str, Dict[str, int]]:
    """tag_type -> rater -> number of tags applied (frame_tags lens only)."""
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r['lens'] == FRAME_TAG_LENS:
            counts[r['field']][r['rater_user_id']] += 1
    return counts


def print_table(results: List[dict]) -> None:
    header = f"{'lens':<12} {'field':<28} {'metric':<8} {'alpha':>7} {'units':>6} {'used':>5} {'raters':>6}  note"
    print(header)
    print('-' * len(header))
    for r in results:
        alpha = 'n/a' if r['alpha'] is None else f"{r['alpha']:.3f}"
        print(f"{r['lens']:<12} {r['field']:<28} {r['metric']:<8} {alpha:>7} "
              f"{r['n_units']:>6} {r['n_units_used']:>5} {r['n_raters']:>6}  {r['note']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Krippendorff's alpha per field from the long export")
    parser.add_argument('csv', help='long-format CSV from GET /api/admin/export/long')
    parser.add_argument('--lens', help='only this lens (environment|strategy|outcome|frame_tags)')
    parser.add_argument('--cohort', help="only rows with this cohort (validated|overlap)")
    parser.add_argument('--dataset', help='only this dataset (A|B)')
    parser.add_argument('--min-raters', type=int, default=2,
                        help='drop units rated by fewer raters than this (default 2)')
    parser.add_argument('--json', help='also write the results to this JSON file')
    args = parser.parse_args(argv)

    rows = read_long(args.csv, lens=args.lens, cohort=args.cohort, dataset=args.dataset)
    if not rows:
        print('No rows after filtering.', file=sys.stderr)
        return 1

    results = compute(rows, min_raters=args.min_raters)
    print_table(results)

    counts = tag_counts(rows)
    if counts:
        print('\nFrame tag usage (tags applied per rater):')
        for tag_type, by_rater in sorted(counts.items()):
            per = ', '.join(f'{r[:8]}…={n}' for r, n in sorted(by_rater.items()))
            print(f'  {tag_type:<20} {per}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump({'results': results, 'tag_counts': counts}, handle, indent=2)
        print(f'\nWrote {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
