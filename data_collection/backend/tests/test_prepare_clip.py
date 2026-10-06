"""
scripts/prepare_clip.py on synthetic ffmpeg `testsrc` videos.

No database: nothing here touches the `db`/`dsn` fixtures, so these run with
no TEST_DATABASE_URL set. Skipped entirely when ffmpeg/ffprobe are missing.

Trim accuracy is checked two ways:
  * frame count equals the number of source frames in [start, end) (+-1),
  * the first and last output frames *look like* the expected source frames:
    each is decoded to a small grey image and matched against the source
    frames around the expected index; the best match must be within one
    frame. testsrc changes every frame, so a wrong cut can't hide.
"""
import csv
import json
import shutil
import subprocess
import sys
import uuid
from fractions import Fraction
from pathlib import Path

import pytest

if shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None:
    pytest.skip('ffmpeg/ffprobe not on PATH', allow_module_level=True)

from scripts import prepare_clip as pc  # noqa: E402

THUMB_W, THUMB_H = 64, 48


# ==================== fixtures ====================

def _make_video(path: Path, rate: str, seconds: int, gop: int, bframes: bool = True,
                audio: bool = False) -> Path:
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-y',
           '-f', 'lavfi', '-i', f'testsrc=size=320x240:rate={rate}']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440']
    cmd += ['-t', str(seconds), '-c:v', 'libx264', '-preset', 'ultrafast',
            '-g', str(gop), '-pix_fmt', 'yuv420p']
    if not bframes:
        cmd += ['-bf', '0']
    if audio:
        cmd += ['-c:a', 'aac']
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope='module')
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp('src')
    return {
        # B-frames on, keyframe every second.
        '30': _make_video(d / 'src30.mp4', '30', 8, gop=30),
        '60': _make_video(d / 'src60.mp4', '60', 8, gop=60),
        # NTSC rate: the rational must survive as 30000/1001.
        'ntsc': _make_video(d / 'src2997.mp4', '30000/1001', 8, gop=30),
        # No B-frames + an audio track: a keyframe start can be stream-copied.
        'nob': _make_video(d / 'nob30.mp4', '30', 8, gop=30, bframes=False, audio=True),
    }


def meta(**over):
    base = dict(
        source_type='public_broadcast',
        source_url='https://example.org/broadcast/semi-final',
        license='Broadcast footage; research use, cited by URL + timestamps',
        event_name='Test Cup Semi-final',
        event_date='2026-05-10',
    )
    base.update(over)
    return base


def cli_args(src, start, end, out_dir, *extra, **over):
    m = meta(**over)
    args = [str(src), '--start', str(start), '--end', str(end),
            '--out-dir', str(out_dir)]
    for k, v in m.items():
        if v is not None:
            args += ['--' + k.replace('_', '-'), v]
    return args + list(extra)


# ==================== helpers ====================

def gray_frames(path: Path, first: int = 0, count: int | None = None) -> list[bytes]:
    """Decode frames [first, first+count) of path into small grey images."""
    vf = f'select=gte(n\\,{first}),scale={THUMB_W}:{THUMB_H},format=gray'
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(path),
           '-vf', vf, '-fps_mode', 'passthrough']
    if count is not None:
        cmd += ['-frames:v', str(count)]
    cmd += ['-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    size = THUMB_W * THUMB_H
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]


def mse(a: bytes, b: bytes) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)


def best_match(frame: bytes, src: Path, around: int, radius: int = 3) -> int:
    lo = max(0, around - radius)
    candidates = gray_frames(src, lo, 2 * radius + 1)
    scores = [mse(frame, c) for c in candidates]
    return lo + scores.index(min(scores))


def first_frame_index(ms: int, fps: Fraction) -> int:
    x = Fraction(ms, 1000) * fps
    return -((-x.numerator) // x.denominator)


def assert_trim_accurate(src: Path, out: Path, start_ms: int, end_ms: int, fps: Fraction):
    sidecar = json.loads(out.with_suffix('.json').read_text())
    first = first_frame_index(start_ms, fps)
    last = first_frame_index(end_ms, fps) - 1
    expected = last - first + 1

    assert abs(sidecar['frame_count'] - expected) <= 1, (sidecar['frame_count'], expected)
    expected_ms = expected / fps * 1000
    assert abs(sidecar['duration_ms'] - float(expected_ms)) <= float(1000 / fps) + 1

    out_frames = gray_frames(out)
    assert len(out_frames) == sidecar['frame_count']
    assert abs(best_match(out_frames[0], src, first) - first) <= 1
    assert abs(best_match(out_frames[-1], src, last) - last) <= 1


def run_cli(argv, capsys):
    code = pc.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ==================== timestamps ====================

@pytest.mark.parametrize('text,ms', [
    ('00:12:03.500', 723500),
    ('12:03.5', 723500),
    ('723.5', 723500),
    ('1', 1000),
    ('0.0335', 34),          # sub-ms rounds half-up
    ('1:00:00', 3600000),
    ('0:00:01.001', 1001),
])
def test_parse_timestamp(text, ms):
    assert pc.parse_timestamp(text) == ms


@pytest.mark.parametrize('text', ['', 'abc', '1:2:3:4', '00:61.0', '01:60:00', '-1', '1,5'])
def test_parse_timestamp_rejects(text):
    with pytest.raises(pc.ValidationError):
        pc.parse_timestamp(text)


# ==================== trimming ====================

@pytest.mark.parametrize('key,fps,start,end', [
    ('30', Fraction(30), '00:00:01.250', '00:00:04.100'),     # mid-GOP start
    ('60', Fraction(60), '1.3', '3.75'),
    ('60', Fraction(60), '00:02.000', '00:05.000'),           # keyframe start, B-frames
    ('ntsc', Fraction(30000, 1001), '0:01.500', '4'),
])
def test_trim_accuracy_and_fps(videos, tmp_path, capsys, key, fps, start, end):
    src = videos[key]
    code, out, err = run_cli(cli_args(src, start, end, tmp_path, '--name', 'clip'), capsys)
    assert code == 0, err

    mp4 = tmp_path / 'clip.mp4'
    sidecar = json.loads((tmp_path / 'clip.json').read_text())
    assert sidecar['fps'] == f'{fps.numerator}/{fps.denominator}'
    assert (sidecar['width'], sidecar['height']) == (320, 240)

    # Audio dropped, single video stream.
    streams = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(mp4)],
        check=True, capture_output=True, text=True).stdout.split()
    assert streams == ['video']

    assert_trim_accurate(src, mp4, pc.parse_timestamp(start), pc.parse_timestamp(end), fps)


def test_reencode_settings(videos, tmp_path):
    spec = pc.build_spec(input=videos['30'], start='1.25', end='2.5', **meta())
    r = pc.prepare_clip(spec, tmp_path)
    assert r['mode'] == 'reencode'
    info = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=codec_name,pix_fmt', '-of', 'json', str(r['mp4'])],
        check=True, capture_output=True, text=True).stdout
    s = json.loads(info)['streams'][0]
    assert s['codec_name'] == 'h264'
    assert s['pix_fmt'] == 'yuv420p'


def test_keyframe_start_stream_copies(videos, tmp_path):
    """Start on a keyframe of a stream with no B-frames -> copy, still exact."""
    src = videos['nob']
    assert pc.start_is_keyframe(src, 2000, Fraction(30), 0.0)
    assert not pc.start_is_keyframe(src, 2500, Fraction(30), 0.0)

    spec = pc.build_spec(input=src, start='2', end='5.5', name='kf', **meta())
    r = pc.prepare_clip(spec, tmp_path)
    assert r['mode'] == 'copy'
    assert r['sidecar']['fps'] == '30/1'
    assert_trim_accurate(src, r['mp4'], 2000, 5500, Fraction(30))


def test_keyframe_start_with_inexact_copy_falls_back(videos, tmp_path):
    """B-frames make a copied tail overshoot; the script must notice and re-encode."""
    spec = pc.build_spec(input=videos['60'], start='2', end='4.5', **meta())
    r = pc.prepare_clip(spec, tmp_path)
    assert r['sidecar']['frame_count'] in (149, 150, 151)
    assert not list(tmp_path.glob('.*partial*'))


# ==================== sidecar ====================

def test_sidecar_schema_and_values(videos, tmp_path, capsys):
    athlete = str(uuid.uuid4())
    code, _, err = run_cli(cli_args(
        videos['30'], '00:00:01.000', '00:00:03.000', tmp_path,
        '--athlete-id', athlete, '--notes', 'final, wall 2', '--name', 'semi_wall2'),
        capsys)
    assert code == 0, err
    mp4 = tmp_path / 'semi_wall2.mp4'
    sc = json.loads((tmp_path / 'semi_wall2.json').read_text())

    assert list(sc) == list(pc.SIDECAR_KEYS)
    assert list(sc) == [
        'source_type', 'source_url', 'clip_start_ms', 'clip_end_ms', 'license',
        'event_name', 'event_date', 'athlete_id', 'notes', 'fps', 'width',
        'height', 'duration_ms', 'frame_count', 'sha256', 'prepared_at',
        'script_version',
    ]
    m = meta()
    assert sc['source_type'] == m['source_type']
    assert sc['source_url'] == m['source_url']
    assert sc['license'] == m['license']
    assert sc['event_name'] == m['event_name']
    assert sc['event_date'] == '2026-05-10'
    assert sc['clip_start_ms'] == 1000 and sc['clip_end_ms'] == 3000
    assert sc['athlete_id'] == athlete
    assert sc['notes'] == 'final, wall 2'
    assert sc['fps'] == '30/1'
    assert sc['frame_count'] == 60
    assert sc['duration_ms'] == 2000
    import hashlib
    assert sc['sha256'] == hashlib.sha256(mp4.read_bytes()).hexdigest()
    assert sc['prepared_at'].endswith('Z')
    assert sc['script_version'] == pc.SCRIPT_VERSION
    for k in ('clip_start_ms', 'clip_end_ms', 'width', 'height', 'duration_ms', 'frame_count'):
        assert isinstance(sc[k], int)


def test_optional_fields_null_and_default_name(videos, tmp_path):
    spec = pc.build_spec(input=videos['30'], start='1', end='2', **meta())
    r = pc.prepare_clip(spec, tmp_path)
    assert r['mp4'].name == 'src30_1000-2000.mp4'
    assert r['sidecar']['athlete_id'] is None
    assert r['sidecar']['notes'] is None


def test_refuses_overwrite_without_flag(videos, tmp_path, capsys):
    args = cli_args(videos['30'], '1', '2', tmp_path, '--name', 'x')
    assert run_cli(args, capsys)[0] == 0
    code, _, err = run_cli(args, capsys)
    assert code == pc.EXIT_VALIDATION and 'already exists' in err
    assert run_cli(args + ['--overwrite'], capsys)[0] == 0


# ==================== validation errors ====================

@pytest.mark.parametrize('label,mutate,needle', [
    ('missing input', lambda a: ['/nonexistent/x.mp4'] + a[1:], 'not found'),
    ('end before start', lambda a: _set(a, '--end', '0.5'), 'must be after start'),
    ('end equals start', lambda a: _set(a, '--end', '1'), 'must be after start'),
    ('too long', lambda a: _set(a, '--max-seconds', '0.5'), 'longer than'),
    ('end past source', lambda a: _set(a, '--end', '20'), 'past the end'),
    ('bad timestamp', lambda a: _set(a, '--start', '1:75'), 'bad timestamp'),
    ('bad event date', lambda a: _set(a, '--event-date', '2026-13-01'), 'bad event date'),
    ('event date format', lambda a: _set(a, '--event-date', '10/05/2026'), 'bad event date'),
    ('bad source type', lambda a: _set(a, '--source-type', 'community'), 'not allowed'),
    ('bad url', lambda a: _set(a, '--source-url', 'not a url'), 'http(s) URL'),
    ('bad athlete id', lambda a: a + ['--athlete-id', 'abc'], 'not a UUID'),
    ('missing license', lambda a: _drop(a, '--license'), '--license is required'),
    ('missing event name', lambda a: _drop(a, '--event-name'), '--event-name is required'),
    ('missing start', lambda a: _drop(a, '--start'), '--start is required'),
    ('bad name', lambda a: a + ['--name', '../escape'], 'bad output name'),
])
def test_validation_errors(videos, tmp_path, capsys, label, mutate, needle):
    args = mutate(cli_args(videos['30'], '1', '2', tmp_path))
    code, _, err = run_cli(args, capsys)
    assert code == pc.EXIT_VALIDATION, label
    assert err.startswith('error: ')
    assert needle in err, err
    assert not list(tmp_path.glob('*.mp4'))


def test_default_max_seconds_is_180(videos, tmp_path):
    # 181 s requested from an 8 s file: the length limit fires before probing.
    with pytest.raises(pc.ValidationError, match='180s limit'):
        pc.build_spec(input=videos['30'], start='0', end='181', **meta())


def test_main_is_executable_as_script(videos, tmp_path):
    """Exit codes as seen from a shell."""
    script = Path(pc.__file__)
    bad = subprocess.run(
        [sys.executable, str(script), str(videos['30']), '--start', '2', '--end', '1',
         *sum(([f'--{k.replace("_", "-")}', v] for k, v in meta().items()), [])],
        capture_output=True, text=True)
    assert bad.returncode == 2
    assert 'must be after start' in bad.stderr


def _set(args, flag, value):
    args = list(args)
    if flag in args:
        args[args.index(flag) + 1] = value
    else:
        args += [flag, value]
    return args


def _drop(args, flag):
    args = list(args)
    i = args.index(flag)
    del args[i:i + 2]
    return args


# ==================== batch ====================

def write_batch(path: Path, rows: list[dict]) -> Path:
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(pc.BATCH_COLUMNS))
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in pc.BATCH_COLUMNS})
    return path


def test_batch_mode(videos, tmp_path, capsys):
    # A relative input path resolves against the CSV's directory.
    shutil.copy(videos['60'], tmp_path / 'local60.mp4')
    rows = [
        dict(input=str(videos['30']), start='00:00:01.000', end='00:00:02.500', name='a', **meta()),
        dict(input='local60.mp4', start='1.3', end='3', name='b',
             athlete_id=str(uuid.uuid4()), notes='wide shot', **meta(source_type='cc_license')),
        dict(input=str(videos['ntsc']), start='0:02', end='0:03.5', **meta(source_type='research_dataset')),
    ]
    csv_path = write_batch(tmp_path / 'clips.csv', rows)
    out = tmp_path / 'out'
    code, stdout, err = run_cli(['--batch', csv_path, '--out-dir', out], capsys)
    assert code == 0, err
    assert '3/3 clips prepared' in stdout

    summary = json.loads((out / 'batch_summary.json').read_text())
    assert summary['total'] == 3 and summary['ok'] == 3 and summary['failed'] == 0
    assert [c['name'] for c in summary['clips']] == ['a', 'b', 'src2997_2000-3500']

    a = json.loads((out / 'a.json').read_text())
    b = json.loads((out / 'b.json').read_text())
    c = json.loads((out / 'src2997_2000-3500.json').read_text())
    assert list(a) == list(pc.SIDECAR_KEYS)
    assert a['fps'] == '30/1' and a['frame_count'] == 45
    assert b['fps'] == '60/1' and b['source_type'] == 'cc_license'
    assert b['notes'] == 'wide shot' and b['athlete_id'] == rows[1]['athlete_id']
    assert c['fps'] == '30000/1001' and c['source_type'] == 'research_dataset'
    assert_trim_accurate(tmp_path / 'local60.mp4', out / 'b.mp4', 1300, 3000, Fraction(60))


def test_batch_validates_every_row_before_trimming(videos, tmp_path, capsys):
    rows = [
        dict(input=str(videos['30']), start='1', end='2', name='good', **meta()),
        dict(input=str(videos['30']), start='3', end='2', name='bad_order', **meta()),
        dict(input=str(videos['30']), start='1', end='2', name='bad_type', **meta(source_type='tv')),
        dict(input=str(videos['30']), start='1', end='2', name='good', **meta()),
    ]
    csv_path = write_batch(tmp_path / 'clips.csv', rows)
    out = tmp_path / 'out'
    code, _, err = run_cli(['--batch', csv_path, '--out-dir', out], capsys)
    assert code == pc.EXIT_VALIDATION
    assert '3 invalid row(s)' in err
    assert 'line 3' in err and 'line 4' in err and 'line 5' in err
    assert not out.exists() or not list(out.glob('*.mp4'))


def test_batch_missing_column(tmp_path, capsys):
    p = tmp_path / 'clips.csv'
    p.write_text('input,start,end\nx.mp4,1,2\n')
    code, _, err = run_cli(['--batch', p], capsys)
    assert code == pc.EXIT_VALIDATION and 'missing column' in err


def test_batch_and_input_together_rejected(videos, tmp_path, capsys):
    p = write_batch(tmp_path / 'clips.csv', [])
    code, _, err = run_cli([videos['30'], '--batch', p], capsys)
    assert code == pc.EXIT_VALIDATION and 'not both' in err
