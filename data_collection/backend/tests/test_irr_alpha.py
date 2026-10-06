"""
scripts/irr_alpha.py on a hand-built long export: perfect agreement is 1,
disagreement is lower, missing values and single-rater units are handled,
and only the random overlap subset (irr_overlap = true) counts by default.
"""
import csv
import io

import pytest

krippendorff = pytest.importorskip('krippendorff')

from scripts import irr_alpha  # noqa: E402
from src.labeling.exporter import LONG_COLUMNS  # noqa: E402


def long_rows(entries, overlap=True):
    """entries: (video_id, move_id, rater, lens, field, value)."""
    rows = []
    for video_id, move_id, rater, lens, field, value in entries:
        rows.append({
            'video_id': str(video_id), 'irr_overlap': 'true' if overlap else 'false',
            'source_type': 'public_broadcast', 'move_id': str(move_id),
            'move_index': str(move_id), 'rater_user_id': rater,
            'lens': lens, 'field': field, 'value': value,
            'taxonomy_version': '3.1.0', 'is_gold': 'false',
        })
    return rows


def write_csv(tmp_path, rows, columns=None, name='long.csv'):
    path = tmp_path / name
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or LONG_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def test_perfect_and_partial_agreement(tmp_path):
    entries = []
    for move in range(1, 7):
        for rater in ('r1', 'r2', 'r3'):
            # wall_angle: everyone agrees, alternating by move.
            entries.append((1, move, rater, 'environment', 'wall_angle', 'steep' if move % 2 else 'slab'))
            # result: r3 disagrees on half the moves.
            value = 'success' if move % 2 else 'fall'
            if rater == 'r3' and move in (2, 4, 6):
                value = 'success'
            entries.append((1, move, rater, 'outcome', 'result', value))
            # form_quality (ordinal): r2 always one step off.
            base = 2 + (move % 3)
            entries.append((1, move, rater, 'strategy', 'form_quality',
                            str(base + (1 if rater == 'r2' else 0))))
    path = write_csv(tmp_path, long_rows(entries))
    rows = irr_alpha.read_long(path)
    by_field = {(r['lens'], r['field']): r for r in irr_alpha.compute(rows)}

    wall = by_field[('environment', 'wall_angle')]
    assert wall['alpha'] == 1.0 and wall['metric'] == 'nominal'
    assert wall['n_units'] == 6 and wall['n_raters'] == 3

    result = by_field[('outcome', 'result')]
    assert result['alpha'] is not None and result['alpha'] < 1.0

    form = by_field[('strategy', 'form_quality')]
    assert form['metric'] == 'ordinal'
    assert form['alpha'] is not None and 0 < form['alpha'] < 1.0


def test_missing_values_and_frame_tags(tmp_path):
    entries = []
    for move in range(1, 5):
        entries.append((1, move, 'r1', 'outcome', 'result', 'success'))
        if move != 4:  # r2 skipped move 4 entirely
            entries.append((1, move, 'r2', 'outcome', 'result', 'success'))
        entries.append((1, move, 'r1', 'outcome', 'reach_detail', ''))  # empty value
        entries.append((1, move, 'r2', 'outcome', 'reach_detail', 'reached_controlled'))
        # frame tags: both raters flag pain on moves 1-2, only r1 on move 3.
        if move in (1, 2):
            entries.append((1, move, 'r1', 'frame_tags', 'sharp_pain', f'{move}:6:left:left_shoulder'))
            entries.append((1, move, 'r2', 'frame_tags', 'sharp_pain', f'{move}:5:left:left_shoulder'))
        if move == 3:
            entries.append((1, move, 'r1', 'frame_tags', 'sharp_pain', '3:6:left:left_shoulder'))
    path = write_csv(tmp_path, long_rows(entries))
    rows = irr_alpha.read_long(path)
    by_field = {(r['lens'], r['field']): r for r in irr_alpha.compute(rows)}

    result = by_field[('outcome', 'result')]
    assert result['n_units'] == 4 and result['n_units_used'] == 3  # move 4 has one rater
    assert result['alpha'] == 1.0

    reach = by_field[('outcome', 'reach_detail')]
    assert reach['alpha'] is None  # only r2 has values: nothing to compare
    assert reach['n_units_used'] == 0

    tags = by_field[('frame_tags', 'sharp_pain')]
    assert tags['n_units'] == 3  # moves 1-3 had at least one tag
    assert tags['alpha'] is not None and tags['alpha'] < 1.0  # r2 missed move 3

    counts = irr_alpha.tag_counts(rows)
    assert counts['sharp_pain'] == {'r1': 3, 'r2': 2}


def test_cli_prints_table_and_writes_json(tmp_path, capsys):
    entries = [(1, m, r, 'environment', 'wall_angle', 'steep') for m in (1, 2, 3) for r in ('a', 'b')]
    path = write_csv(tmp_path, long_rows(entries))
    out = tmp_path / 'alpha.json'
    assert irr_alpha.main([path, '--json', str(out)]) == 0
    printed = capsys.readouterr().out
    assert 'wall_angle' in printed and 'nominal' in printed
    assert out.exists()
    assert irr_alpha.main([path, '--lens', 'outcome']) == 1  # nothing left after filter


def test_only_the_overlap_subset_counts_by_default(tmp_path, capsys):
    """Single-rater videos carry no agreement information; they are dropped
    unless --all-videos. Here a disagreeing 'pair' on a single-rated video
    (impossible in practice, but it proves the filter) would lower alpha."""
    agree = [(1, m, r, 'outcome', 'result', 'success' if m % 2 else 'fall')
             for m in (1, 2, 3) for r in ('a', 'b', 'c')]
    noise = [(2, m, r, 'outcome', 'result', 'success' if r == 'a' else 'fall')
             for m in (1, 2, 3) for r in ('a', 'b')]
    path = write_csv(tmp_path, long_rows(agree) + long_rows(noise, overlap=False))

    subset = irr_alpha.read_long(path)
    assert {r['video_id'] for r in subset} == {'1'}
    assert irr_alpha.coverage(subset) == {'n_videos': 1, 'n_moves': 3, 'n_raters': 3}
    assert irr_alpha.compute(subset)[0]['alpha'] == 1.0

    everything = irr_alpha.read_long(path, overlap_only=False)
    assert {r['video_id'] for r in everything} == {'1', '2'}
    assert irr_alpha.compute(everything)[0]['alpha'] < 1.0

    assert irr_alpha.main([path]) == 0
    assert 'overlap subset - 1 videos, 3 moves, 3 raters' in capsys.readouterr().out
    assert irr_alpha.main([path, '--all-videos']) == 0
    assert 'all videos - 2 videos' in capsys.readouterr().out


def test_old_export_without_irr_overlap_is_refused(tmp_path, capsys):
    entries = [(1, m, r, 'outcome', 'result', 'success') for m in (1, 2) for r in ('a', 'b')]
    old_columns = [c for c in LONG_COLUMNS if c != 'irr_overlap']
    path = write_csv(tmp_path, long_rows(entries), columns=old_columns, name='old.csv')
    with pytest.raises(ValueError, match='irr_overlap'):
        irr_alpha.read_long(path)
    assert irr_alpha.main([path]) == 2
    assert irr_alpha.main([path, '--all-videos']) == 0
