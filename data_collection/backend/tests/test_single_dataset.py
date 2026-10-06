"""
Single dataset (runbook W2 Backend + Amendment, 2026-10-06).

Replaces the Dataset A tests. One dataset of admin-prepped paper clips
(public footage) rated by validated raters: 1 rater per video, 3 on a random
inter-rater-reliability overlap subset. Raters label all three lenses
(Strategy included) independently and never see each other's rows. The old
self-upload flow survives as the dormant "community" source type behind
SELF_UPLOAD_ENABLED.

Cast: an admin who preps clips, three validated raters, and one unvalidated
user. Every clip the admin readies carries full provenance and an adult
athlete, or the ready gate refuses it.
"""
import csv
import io
import uuid

import pytest
from fastapi.testclient import TestClient

from src.labeling.exporter import LONG_COLUMNS, FULL_ID_COLUMNS, Exporter
from src.labeling.models import TAXONOMY_VERSION, HOLD_SLOTS
from src.web import api as api_module
from tests.conftest import requires_db
from tests.test_api_scoping import (
    POSE_CSV, WORKER_SECRET, auth, create_move, register_video, ready_video,
)

pytestmark = requires_db

EVENT_DATE = '2026-05-10'
SOURCE_URL = 'https://www.youtube.com/watch?v=example'


# ==================== FIXTURES / HELPERS ====================

@pytest.fixture
def client(clean_db, fake_r2, enqueued, monkeypatch, self_upload_off):
    """Production defaults: self-upload off. `enqueued` stubs the pose
    worker; `ready_video` plays the worker so a clip has its pose CSV."""
    monkeypatch.setattr(api_module, '_db', clean_db)
    monkeypatch.setattr(api_module, '_exporter', None)
    monkeypatch.setattr(api_module, '_admin_exporter', None)
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', WORKER_SECRET)
    monkeypatch.delenv('IRR_OVERLAP_RATE', raising=False)
    with TestClient(api_module.app) as test_client:
        yield test_client


@pytest.fixture
def admin(client, clean_db) -> str:
    """A user with a profile flagged is_admin (the way Jolie will do it: SQL)."""
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, 'Admin')
    with clean_db.get_connection() as conn:
        conn.execute('UPDATE rater_profiles SET is_admin = true WHERE user_id = %s', (user_id,))
    return user_id


def _validated_rater(client, admin, name):
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, name)
    res = client.put(f'/api/admin/raters/{user_id}',
                     json={'is_validated': True, 'validation_note': 'coach'},
                     headers=auth(admin))
    assert res.status_code == 200, res.text
    return user_id


@pytest.fixture
def rater_a(client, admin) -> str:
    return _validated_rater(client, admin, 'Rater A')


@pytest.fixture
def rater_b(client, admin) -> str:
    return _validated_rater(client, admin, 'Rater B')


@pytest.fixture
def rater_c(client, admin) -> str:
    return _validated_rater(client, admin, 'Rater C')


@pytest.fixture
def newcomer(client) -> str:
    """Signed in, profile made, not validated."""
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, 'Newcomer')
    return user_id


def make_profile(client, user_id, name='Someone'):
    res = client.post(
        '/api/me/profile',
        json={'display_name': name, 'years_climbing': 5, 'highest_grade': 'V6',
              'research_background': False},
        headers=auth(user_id),
    )
    assert res.status_code == 201, res.text
    return res.json()


def make_athlete(client, admin, birth_year=1995, height_cm=172, url=None):
    res = client.post(
        '/api/admin/athletes',
        json={'ifsc_profile_url': url or f'https://ifsc.results.info/athlete/{uuid.uuid4()}',
              'height_cm': height_cm, 'birth_year': birth_year, 'category': 'women'},
        headers=auth(admin),
    )
    assert res.status_code == 201, res.text
    return res.json()


def set_provenance(client, admin, video_id, athlete_id, **overrides):
    body = {'source_type': 'public_broadcast', 'source_url': SOURCE_URL,
            'clip_start_ms': 723500, 'clip_end_ms': 761000, 'license': 'Standard YouTube',
            'event_name': 'IFSC World Cup Example 2026', 'event_date': EVENT_DATE,
            'athlete_id': athlete_id}
    body.update(overrides)
    res = client.put(f'/api/admin/videos/{video_id}/metadata', json=body, headers=auth(admin))
    assert res.status_code == 200, res.text
    return res.json()


def create_hold(client, user_id, video_id, x=0.4):
    res = client.post(
        '/api/holds',
        json={'video_id': video_id, 'bbox_x': x, 'bbox_y': 0.5,
              'bbox_w': 0.06, 'bbox_h': 0.05, 'source': 'manual'},
        headers=auth(user_id),
    )
    assert res.status_code == 201, res.text
    return res.json()


def assign(client, admin, video_id, rater):
    res = client.post('/api/admin/assignments',
                      json={'video_id': video_id, 'rater_user_id': rater},
                      headers=auth(admin))
    assert res.status_code == 201, res.text
    return res.json()


def set_overlap(client, admin, video_id, value):
    return client.put(f'/api/admin/videos/{video_id}/overlap',
                      json={'irr_overlap': value}, headers=auth(admin))


def mark_ready(client, admin, video_id):
    res = client.post(f'/api/admin/videos/{video_id}/ready', headers=auth(admin))
    assert res.status_code == 200, res.text
    assert res.json()['prep_status'] == 'ready'
    return res.json()


def prepped_video(client, admin, n_moves=3, overlap=False, athlete=None):
    """Admin uploads (pose extracted), sets provenance, draws one hold,
    defines n canonical moves, fixes the overlap flag, marks ready."""
    video = ready_video(client, admin, filename='prep.mp4')
    athlete = athlete or make_athlete(client, admin)
    set_provenance(client, admin, video['id'], athlete['athlete_id'])
    hold = create_hold(client, admin, video['id'])
    moves = [create_move(client, admin, video['id']) for _ in range(n_moves)]
    assert set_overlap(client, admin, video['id'], overlap).status_code == 200
    ready = mark_ready(client, admin, video['id'])
    assert ready['irr_overlap'] is overlap
    return ready, hold, moves


def post_strategy(client, user_id, move_id, approach='dynamic', tags=('dyno',), size='large',
                  form_quality=4, confidence='high'):
    return client.post(
        '/api/strategies',
        json={'move_id': move_id, 'approach': approach, 'move_tags': list(tags),
              'size': size, 'form_quality': form_quality, 'confidence': confidence},
        headers=auth(user_id),
    )


def post_env(client, user_id, move_id, hold_id=None, wall_angle='steep', hold_type='jug'):
    return client.post(
        '/api/environments',
        json={'move_id': move_id, 'wall_angle': wall_angle,
              'start_left': {'hold_id': hold_id, 'hold_type': hold_type,
                             'hold_quality': ['incut', 'small']}},
        headers=auth(user_id),
    )


def post_outcome(client, user_id, move_id, result='success'):
    return client.post(
        '/api/outcomes',
        json={'move_id': move_id, 'result': result,
              'reach_detail': 'reached_controlled', 'confidence': 'high'},
        headers=auth(user_id),
    )


def post_tag(client, user_id, move_id, frame=1):
    return client.post(
        '/api/frame-tags',
        json={'move_id': move_id, 'frame_number': frame, 'timestamp_ms': 33.0,
              'tag_type': 'sharp_pain', 'side': 'left', 'level': 6,
              'locations': ['left_shoulder', 'left_elbow'], 'note': 'tweak'},
        headers=auth(user_id),
    )


def label_all(client, hold, moves, rater, approach='dynamic', wall_angle='steep', result='success'):
    for m in moves:
        assert post_strategy(client, rater, m['id'], approach=approach).status_code == 201
        assert post_env(client, rater, m['id'], hold['id'], wall_angle).status_code == 201
        assert post_outcome(client, rater, m['id'], result).status_code == 201


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


# ==================== SCHEMA ====================

def test_migration_dropped_the_two_dataset_columns(clean_db):
    with clean_db.get_connection() as conn:
        cols = {
            (r['table_name'], r['column_name'])
            for r in conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ).fetchall()
        }
    for gone in [('videos', 'dataset'), ('videos', 'climber_height_cm'),
                 ('videos', 'climber_ape_index_cm'), ('videos', 'climber_experience'),
                 ('videos', 'gym'), ('video_assignments', 'cohort'), ('rater_profiles', 'tier')]:
        assert gone not in cols, gone
    for new in [('videos', 'irr_overlap'), ('videos', 'irr_overlap_set_by'), ('videos', 'source_type'),
                ('videos', 'source_url'), ('videos', 'clip_start_ms'), ('videos', 'clip_end_ms'),
                ('videos', 'license'), ('videos', 'event_name'), ('videos', 'event_date'),
                ('videos', 'athlete_id'), ('rater_profiles', 'is_validated'),
                ('athletes', 'height_cm'), ('athletes', 'birth_year'), ('strategies', 'approach')]:
        assert new in cols, new
    # The athletes table has no name column, by design.
    assert not any(t == 'athletes' and 'name' in c for t, c in cols)


# ==================== PROFILE / CONFIG ====================

def test_new_profile_is_unvalidated_and_cannot_validate_itself(client):
    user = str(uuid.uuid4())
    assert client.get('/api/me/profile', headers=auth(user)).status_code == 404
    created = make_profile(client, user, 'New Rater')
    assert created['is_validated'] is False
    assert created['is_admin'] is False
    assert 'tier' not in created

    res = client.put('/api/me/profile',
                     json={'display_name': 'Renamed', 'is_validated': True, 'is_admin': True,
                           'validation_note': 'me'},
                     headers=auth(user))
    assert res.status_code == 200, res.text
    assert res.json()['display_name'] == 'Renamed'
    assert res.json()['is_validated'] is False
    assert res.json()['is_admin'] is False
    assert res.json()['validation_note'] is None
    assert client.post('/api/me/profile', json={'display_name': 'x'}, headers=auth(user)).status_code == 409


def test_profile_bio_round_trip_and_length_limit(client):
    user = str(uuid.uuid4())
    res = client.post('/api/me/profile',
                      json={'display_name': 'Bio Person', 'bio': '  Coach, V8.  '},
                      headers=auth(user))
    assert res.status_code == 201 and res.json()['bio'] == 'Coach, V8.'
    assert client.put('/api/me/profile', json={'bio': 'x' * 1001}, headers=auth(user)).status_code == 422
    assert client.put('/api/me/profile', json={'bio': ''}, headers=auth(user)).json()['bio'] is None


def test_config_exposes_version_and_self_upload_flag(client, monkeypatch, newcomer):
    body = client.get('/api/config', headers=auth(newcomer)).json()
    assert body['version'] == TAXONOMY_VERSION
    assert body['self_upload_enabled'] is False
    assert body['source_types'] == ['public_broadcast', 'cc_license', 'research_dataset']
    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    assert client.get('/api/config', headers=auth(newcomer)).json()['self_upload_enabled'] is True


# ==================== ADMIN GUARDS ====================

ADMIN_ROUTES = [
    ('get', '/api/admin/videos', None),
    ('put', '/api/admin/videos/1/metadata', {'notes': 'x'}),
    ('post', '/api/admin/videos/1/ready', None),
    ('put', '/api/admin/videos/1/overlap', {'irr_overlap': True}),
    ('post', '/api/admin/videos/1/close', None),
    ('post', '/api/admin/videos/1/reopen', None),
    ('get', '/api/admin/assignments', None),
    ('post', '/api/admin/assignments', {'video_id': 1, 'rater_user_id': 'x'}),
    ('delete', '/api/admin/assignments/1', None),
    ('get', '/api/admin/raters', None),
    ('put', '/api/admin/raters/x', {'is_validated': True}),
    ('get', '/api/admin/athletes', None),
    ('post', '/api/admin/athletes', {'height_cm': 170}),
    ('put', f'/api/admin/athletes/{uuid.uuid4()}', {'height_cm': 170}),
    ('get', '/api/admin/export/long', None),
    ('get', '/api/admin/export/full', None),
]


@pytest.mark.parametrize('method,path,body', ADMIN_ROUTES)
def test_admin_routes_are_403_for_non_admins(client, rater_a, method, path, body):
    """Validated raters are not admins."""
    res = client.request(method.upper(), path, json=body, headers=auth(rater_a))
    assert res.status_code == 403, f'{method} {path}: {res.status_code} {res.text}'
    res = client.request(method.upper(), path, json=body, headers=auth(str(uuid.uuid4())))
    assert res.status_code == 403


def test_admin_validates_and_unvalidates_a_rater(client, admin, newcomer):
    res = client.put(f'/api/admin/raters/{newcomer}',
                     json={'is_validated': True, 'validation_note': 'coach, 10y'},
                     headers=auth(admin))
    assert res.status_code == 200
    assert res.json()['is_validated'] is True and res.json()['validation_note'] == 'coach, 10y'
    res = client.put(f'/api/admin/raters/{newcomer}', json={'is_validated': False}, headers=auth(admin))
    assert res.json()['is_validated'] is False
    assert client.put(f'/api/admin/raters/{uuid.uuid4()}', json={'is_validated': True},
                      headers=auth(admin)).status_code == 404


# ==================== ATHLETES ====================

def test_athlete_crud_and_validation(client, admin):
    url = 'https://ifsc.results.info/athlete/1234'
    created = make_athlete(client, admin, birth_year=1999, height_cm=165, url=url)
    assert created['height_source'] == 'ifsc_profile'
    assert created['ifsc_profile_url'] == url
    assert set(created) == {'athlete_id', 'ifsc_profile_url', 'height_cm', 'height_source',
                            'birth_year', 'category', 'created_at'}  # no name field

    # Same profile URL twice is a conflict.
    assert client.post('/api/admin/athletes', json={'ifsc_profile_url': url},
                       headers=auth(admin)).status_code == 409
    # Height missing -> 'missing'; bad category / out-of-range height refused.
    res = client.post('/api/admin/athletes', json={'birth_year': 2000}, headers=auth(admin))
    assert res.status_code == 201 and res.json()['height_source'] == 'missing'
    assert client.post('/api/admin/athletes', json={'category': 'open'},
                       headers=auth(admin)).status_code == 400
    assert client.post('/api/admin/athletes', json={'height_cm': 40},
                       headers=auth(admin)).status_code == 422
    assert client.post('/api/admin/athletes', json={'height_source': 'ifsc_profile'},
                       headers=auth(admin)).status_code == 400

    # Update: height later found on the profile.
    missing_id = res.json()['athlete_id']
    res = client.put(f'/api/admin/athletes/{missing_id}', json={'height_cm': 180}, headers=auth(admin))
    assert res.status_code == 200
    assert res.json()['height_cm'] == 180 and res.json()['height_source'] == 'ifsc_profile'
    assert client.put(f'/api/admin/athletes/{uuid.uuid4()}', json={'height_cm': 180},
                      headers=auth(admin)).status_code == 404
    assert client.put('/api/admin/athletes/not-a-uuid', json={'height_cm': 180},
                      headers=auth(admin)).status_code == 404
    listed = client.get('/api/admin/athletes', headers=auth(admin)).json()
    assert [a['athlete_id'] for a in listed] == [created['athlete_id'], missing_id]


# ==================== METADATA / READY GATE ====================

def test_metadata_sets_and_clears_source_fields(client, admin):
    video = register_video(client, admin)
    assert video['source_type'] == 'public_broadcast'
    athlete = make_athlete(client, admin)
    body = set_provenance(client, admin, video['id'], athlete['athlete_id'])
    assert body['source_url'] == SOURCE_URL
    assert body['clip_start_ms'] == 723500 and body['clip_end_ms'] == 761000
    assert body['event_date'] == EVENT_DATE
    assert body['athlete_id'] == athlete['athlete_id']
    for gone in ('dataset', 'gym', 'climber_height_cm', 'climber_ape_index_cm', 'climber_experience'):
        assert gone not in body

    res = client.put(f'/api/admin/videos/{video["id"]}/metadata',
                     json={'athlete_id': '', 'event_date': '', 'notes': 'n'}, headers=auth(admin))
    assert res.status_code == 200
    assert res.json()['athlete_id'] is None and res.json()['event_date'] is None
    assert res.json()['source_url'] == SOURCE_URL  # untouched

    url = f'/api/admin/videos/{video["id"]}/metadata'
    assert client.put(url, json={'source_type': 'community'}, headers=auth(admin)).status_code == 400
    assert client.put(url, json={'source_type': 'tv'}, headers=auth(admin)).status_code == 400
    assert client.put(url, json={'athlete_id': str(uuid.uuid4())}, headers=auth(admin)).status_code == 400
    assert client.put(url, json={'event_date': '10/05/2026'}, headers=auth(admin)).status_code == 400
    assert client.put(url, json={'clip_start_ms': 900000}, headers=auth(admin)).status_code == 400  # > end
    assert client.put(url, json={'clip_start_ms': -1}, headers=auth(admin)).status_code == 422
    assert client.put('/api/admin/videos/999999/metadata', json={}, headers=auth(admin)).status_code == 404


def test_metadata_accepts_the_clip_prep_sidecar_keys(client, admin):
    """The admin form imports scripts/prepare_clip.py's JSON as-is; extra keys
    (fps, sha256, ...) are ignored rather than refused."""
    video = register_video(client, admin)
    athlete = make_athlete(client, admin)
    sidecar = {
        'source_type': 'cc_license', 'source_url': 'https://vimeo.com/1', 'clip_start_ms': 0,
        'clip_end_ms': 5000, 'license': 'CC BY 4.0', 'event_name': 'Gym session',
        'event_date': '2025-11-02', 'athlete_id': athlete['athlete_id'], 'notes': None,
        'fps': '30/1', 'width': 1280, 'height': 720, 'duration_ms': 5000, 'frame_count': 150,
        'sha256': 'ab' * 32, 'prepared_at': '2026-10-06T12:00:00Z', 'script_version': '1.0.0',
    }
    res = client.put(f'/api/admin/videos/{video["id"]}/metadata', json=sidecar, headers=auth(admin))
    assert res.status_code == 200, res.text
    assert res.json()['source_type'] == 'cc_license' and res.json()['license'] == 'CC BY 4.0'


def _video_with(client, admin, athlete, **provenance):
    video = ready_video(client, admin, filename='gate.mp4')
    set_provenance(client, admin, video['id'], athlete['athlete_id'] if athlete else None, **provenance)
    return video


def test_ready_gate_requires_provenance_and_an_adult(client, admin):
    adult = make_athlete(client, admin, birth_year=1990)

    # Missing pieces, each refused with a reason.
    v = ready_video(client, admin, filename='bare.mp4')
    res = client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin))
    assert res.status_code == 422
    problems = ' '.join(res.json()['problems'])
    assert 'source_url' in problems and 'event_date' in problems and 'athlete' in problems
    assert client.get(f'/api/videos/{v["id"]}', headers=auth(admin)).json()['prep_status'] == 'draft'

    no_birth_year = make_athlete(client, admin, birth_year=None)
    v = _video_with(client, admin, no_birth_year)
    res = client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin))
    assert res.status_code == 422 and 'birth_year' in res.json()['detail']

    # 2026 - 2008 = 18: may still be 17 on the day -> refused (conservative).
    maybe_minor = make_athlete(client, admin, birth_year=2008)
    v = _video_with(client, admin, maybe_minor)
    res = client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin))
    assert res.status_code == 422 and 'under 18' in res.json()['detail']

    # 2026 - 2007 = 19: certainly 18+ -> allowed.
    v = _video_with(client, admin, make_athlete(client, admin, birth_year=2007))
    assert client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin)).status_code == 200

    # research_dataset: a license stands in for a URL.
    v = _video_with(client, admin, adult, source_type='research_dataset', source_url='')
    assert client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin)).status_code == 200
    v = _video_with(client, admin, adult, source_type='public_broadcast', source_url='')
    assert client.post(f'/api/admin/videos/{v["id"]}/ready', headers=auth(admin)).status_code == 422


# ==================== OVERLAP SUBSET ====================

class _FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_overlap_is_drawn_at_random_on_first_ready(client, admin, monkeypatch):
    athlete = make_athlete(client, admin)
    monkeypatch.setenv('IRR_OVERLAP_RATE', '0.25')

    monkeypatch.setattr(api_module, '_overlap_rng', _FixedRng(0.10))   # < 0.25 -> in subset
    v1 = _video_with(client, admin, athlete)
    body = mark_ready(client, admin, v1['id'])
    assert body['irr_overlap'] is True and body['irr_overlap_set_by'] == 'random'
    assert body['rater_target'] == 3

    monkeypatch.setattr(api_module, '_overlap_rng', _FixedRng(0.90))   # >= 0.25 -> single
    v2 = _video_with(client, admin, athlete)
    body = mark_ready(client, admin, v2['id'])
    assert body['irr_overlap'] is False and body['irr_overlap_set_by'] == 'random'
    assert body['rater_target'] == 1

    # Reopen + re-ready keeps the first draw: no re-rolling.
    client.post(f'/api/admin/videos/{v1["id"]}/reopen', headers=auth(admin))
    monkeypatch.setattr(api_module, '_overlap_rng', _FixedRng(0.99))
    assert mark_ready(client, admin, v1['id'])['irr_overlap'] is True


def test_overlap_rate_env_is_respected_and_clamped(client, admin, monkeypatch):
    athlete = make_athlete(client, admin)
    monkeypatch.setattr(api_module, '_overlap_rng', _FixedRng(0.5))
    monkeypatch.setenv('IRR_OVERLAP_RATE', '1')
    assert mark_ready(client, admin, _video_with(client, admin, athlete)['id'])['irr_overlap'] is True
    monkeypatch.setenv('IRR_OVERLAP_RATE', '0')
    assert mark_ready(client, admin, _video_with(client, admin, athlete)['id'])['irr_overlap'] is False
    monkeypatch.setenv('IRR_OVERLAP_RATE', 'lots')   # garbage -> default 0.25
    assert mark_ready(client, admin, _video_with(client, admin, athlete)['id'])['irr_overlap'] is False
    assert api_module.irr_overlap_rate() == 0.25
    monkeypatch.setenv('IRR_OVERLAP_RATE', '7')
    assert api_module.irr_overlap_rate() == 1.0


def test_overlap_rng_is_the_system_rng():
    """A cryptographic source: nobody can predict or steer the subset."""
    import secrets
    assert isinstance(api_module._overlap_rng, secrets.SystemRandom)


def test_overlap_override_only_before_any_assignment(client, admin, rater_a):
    athlete = make_athlete(client, admin)
    v = _video_with(client, admin, athlete)
    # An override before ready is kept by the ready step.
    res = set_overlap(client, admin, v['id'], True)
    assert res.status_code == 200 and res.json()['irr_overlap_set_by'] == 'admin_override'
    assert mark_ready(client, admin, v['id'])['irr_overlap'] is True

    assert set_overlap(client, admin, v['id'], False).json()['irr_overlap'] is False
    assign(client, admin, v['id'], rater_a)
    assert set_overlap(client, admin, v['id'], True).status_code == 409
    assert set_overlap(client, admin, 999999, True).status_code == 404


# ==================== ASSIGNMENTS ====================

def test_assignment_cap_one_rater_or_three_on_overlap(client, admin, rater_a, rater_b, rater_c):
    single, _, _ = prepped_video(client, admin, overlap=False)
    assign(client, admin, single['id'], rater_a)
    res = client.post('/api/admin/assignments', json={'video_id': single['id'], 'rater_user_id': rater_b},
                      headers=auth(admin))
    assert res.status_code == 409 and '1 rater' in res.json()['detail']

    overlap, _, _ = prepped_video(client, admin, overlap=True)
    for rater in (rater_a, rater_b, rater_c):
        assign(client, admin, overlap['id'], rater)
    fourth = _validated_rater(client, admin, 'Rater D')
    res = client.post('/api/admin/assignments', json={'video_id': overlap['id'], 'rater_user_id': fourth},
                      headers=auth(admin))
    assert res.status_code == 409 and '3 raters' in res.json()['detail']

    rows = {v['video']['id']: v for v in client.get('/api/admin/videos', headers=auth(admin)).json()}
    assert rows[single['id']]['assignment_count'] == 1 and rows[single['id']]['video']['rater_target'] == 1
    assert rows[overlap['id']]['assignment_count'] == 3 and rows[overlap['id']]['video']['rater_target'] == 3


def test_assignment_rules(client, admin, rater_a, newcomer):
    video, _, _ = prepped_video(client, admin, overlap=True)
    url = '/api/admin/assignments'

    # Unvalidated rater, missing video, missing profile.
    assert client.post(url, json={'video_id': video['id'], 'rater_user_id': newcomer},
                       headers=auth(admin)).status_code == 409
    assert client.post(url, json={'video_id': 999999, 'rater_user_id': rater_a},
                       headers=auth(admin)).status_code == 404
    assert client.post(url, json={'video_id': video['id'], 'rater_user_id': str(uuid.uuid4())},
                       headers=auth(admin)).status_code == 404

    a = assign(client, admin, video['id'], rater_a)
    assert a['status'] == 'assigned' and 'cohort' not in a
    assert client.post(url, json={'video_id': video['id'], 'rater_user_id': rater_a},
                       headers=auth(admin)).status_code == 409

    # A draft video cannot be assigned yet (its overlap draw has not happened).
    draft = ready_video(client, admin, filename='draft.mp4')
    res = client.post(url, json={'video_id': draft['id'], 'rater_user_id': rater_a}, headers=auth(admin))
    assert res.status_code == 409 and 'ready' in res.json()['detail']

    queue = client.get('/api/me/assignments', headers=auth(rater_a)).json()
    assert len(queue) == 1 and queue[0]['video']['access_role'] == 'rater'
    assert queue[0]['move_count'] == 3
    assert client.delete(f'/api/admin/assignments/{a["id"]}', headers=auth(admin)).status_code == 204
    assert client.get('/api/me/assignments', headers=auth(rater_a)).json() == []


def test_queue_is_empty_until_validated(client, clean_db, admin, newcomer):
    """Even an assignment row (e.g. made before a rater was un-validated)
    does not surface while the profile is unvalidated."""
    video, _, _ = prepped_video(client, admin)
    with clean_db.get_connection() as conn:
        conn.execute('INSERT INTO video_assignments (video_id, rater_user_id) VALUES (%s, %s)',
                     (video['id'], newcomer))
    assert client.get('/api/me/assignments', headers=auth(newcomer)).json() == []
    client.put(f'/api/admin/raters/{newcomer}', json={'is_validated': True}, headers=auth(admin))
    assert len(client.get('/api/me/assignments', headers=auth(newcomer)).json()) == 1


# ==================== RATER SCOPING ====================

def test_rater_reads_assigned_video_and_not_unassigned(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin)
    other, _, _ = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)

    res = client.get(f'/api/videos/{video["id"]}', headers=auth(rater_a))
    assert res.status_code == 200 and res.json()['access_role'] == 'rater'
    assert [h['id'] for h in client.get(f'/api/videos/{video["id"]}/holds', headers=auth(rater_a)).json()] == [hold['id']]
    assert len(client.get(f'/api/videos/{video["id"]}/moves', headers=auth(rater_a)).json()) == 3
    assert client.get(f'/api/videos/{video["id"]}/csv', headers=auth(rater_a),
                      follow_redirects=False).status_code == 307

    for path in (f'/api/videos/{other["id"]}', f'/api/videos/{other["id"]}/holds',
                 f'/api/videos/{other["id"]}/moves', f'/api/videos/{other["id"]}/csv'):
        assert client.get(path, headers=auth(rater_a), follow_redirects=False).status_code == 404, path
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.get(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.get('/api/videos', headers=auth(rater_a)).json() == []


def test_raters_never_see_each_others_labels_including_strategy(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=1, overlap=True)
    assign(client, admin, video['id'], rater_a)
    assign(client, admin, video['id'], rater_b)
    move_id = moves[0]['id']

    s_a = post_strategy(client, rater_a, move_id, approach='static')
    assert s_a.status_code == 201, s_a.text
    env_a = post_env(client, rater_a, move_id, hold['id'], 'steep')
    out_a = post_outcome(client, rater_a, move_id, 'success')
    assert env_a.status_code == 201 and out_a.status_code == 201

    for path in (f'/api/moves/{move_id}/strategy', f'/api/moves/{move_id}/environment',
                 f'/api/moves/{move_id}/outcome'):
        assert client.get(path, headers=auth(rater_b)).status_code == 404, path
    assert client.put(f'/api/strategies/{s_a.json()["id"]}', json={'approach': 'dynamic'},
                      headers=auth(rater_b)).status_code == 404
    assert client.delete(f'/api/strategies/{s_a.json()["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.put(f'/api/environments/{env_a.json()["id"]}', json={'wall_angle': 'slab'},
                      headers=auth(rater_b)).status_code == 404

    # B labels the same move independently.
    assert post_strategy(client, rater_b, move_id, approach='coordination').status_code == 201
    assert client.get(f'/api/moves/{move_id}/strategy', headers=auth(rater_a)).json()['approach'] == 'static'
    assert client.get(f'/api/moves/{move_id}/strategy', headers=auth(rater_b)).json()['approach'] == 'coordination'
    # The canonical move row is untouched by either.
    assert client.get(f'/api/moves/{move_id}', headers=auth(admin)).json()['approach'] == 'dynamic'
    assert post_strategy(client, rater_b, move_id).status_code == 409

    queue = client.get('/api/me/assignments', headers=auth(rater_a)).json()
    assert queue[0]['assignment']['status'] == 'in_progress'


def test_strategy_crud_and_validation(client, admin, rater_a):
    video, _, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    move_id = moves[0]['id']

    assert client.get(f'/api/moves/{move_id}/strategy', headers=auth(rater_a)).status_code == 404
    assert post_strategy(client, rater_a, move_id, approach='flying').status_code == 400
    assert post_strategy(client, rater_a, move_id, size='huge').status_code == 400
    assert post_strategy(client, rater_a, move_id, tags=('teleport',)).status_code == 400
    assert post_strategy(client, rater_a, move_id, confidence='certain').status_code == 400
    assert post_strategy(client, rater_a, move_id, form_quality=6).status_code == 422
    res = client.post('/api/strategies', json={'move_id': move_id, 'approach': 'static', 'size': 'small',
                                               'form_quality': 3, 'effort_level': 9},
                      headers=auth(rater_a))
    assert res.status_code == 201, res.text
    body = res.json()
    assert 'effort_level' not in body
    assert body['move_tags'] == [] and body['taxonomy_version'] == TAXONOMY_VERSION

    res = client.put(f'/api/strategies/{body["id"]}', json={'move_tags': ['mantle', 'technical'],
                                                           'form_quality': 2}, headers=auth(rater_a))
    assert res.status_code == 200
    assert res.json()['move_tags'] == ['mantle', 'technical'] and res.json()['form_quality'] == 2
    assert client.put(f'/api/strategies/{body["id"]}', json={'approach': 'nope'},
                      headers=auth(rater_a)).status_code == 400
    assert client.delete(f'/api/strategies/{body["id"]}', headers=auth(rater_a)).status_code == 204
    assert client.get(f'/api/moves/{move_id}/strategy', headers=auth(rater_a)).status_code == 404


def test_rater_cannot_mutate_holds_or_moves(client, admin, rater_a):
    video, hold, moves = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)
    assert client.post('/api/holds', json={'video_id': video['id'], 'bbox_x': 0.1, 'bbox_y': 0.1,
                                           'bbox_w': 0.1, 'bbox_h': 0.1}, headers=auth(rater_a)).status_code == 403
    assert client.put(f'/api/holds/{hold["id"]}', json={'bbox_x': 0.9}, headers=auth(rater_a)).status_code == 403
    assert client.put(f'/api/moves/{moves[0]["id"]}', json={'description': 'x'},
                      headers=auth(rater_a)).status_code == 403
    assert client.delete(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_a)).status_code == 403


def test_closed_video_blocks_rater_label_writes(client, admin, rater_a):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    strategy = post_strategy(client, rater_a, moves[0]['id'])
    assert strategy.status_code == 201
    client.post(f'/api/admin/videos/{video["id"]}/close', headers=auth(admin))
    assert post_outcome(client, rater_a, moves[0]['id']).status_code == 403
    assert client.put(f'/api/strategies/{strategy.json()["id"]}', json={'size': 'small'},
                      headers=auth(rater_a)).status_code == 403
    assert client.get(f'/api/moves/{moves[0]["id"]}/strategy', headers=auth(rater_a)).status_code == 200


# ==================== COMPLETE VALIDATION ====================

def test_complete_requires_all_three_lenses_but_not_sensation_or_effort(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=2)
    a = assign(client, admin, video['id'], rater_a)
    assert client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_b)).status_code == 404

    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.status_code == 422
    assert res.json()['missing'] == [
        {'move_id': m['id'], 'move_index': i, 'missing': ['strategy', 'environment', 'outcome']}
        for i, m in enumerate(moves)
    ]

    label_all(client, hold, moves[:1], rater_a)
    assert post_env(client, rater_a, moves[1]['id'], hold['id']).status_code == 201
    assert post_outcome(client, rater_a, moves[1]['id']).status_code == 201
    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.json()['missing'] == [{'move_id': moves[1]['id'], 'move_index': 1, 'missing': ['strategy']}]

    # No frame tags anywhere: still completes.
    assert post_strategy(client, rater_a, moves[1]['id']).status_code == 201
    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.status_code == 200 and res.json()['status'] == 'done'
    # Done is final: label writes are refused before any duplicate check.
    assert post_strategy(client, rater_a, moves[0]['id']).status_code == 403
    assert post_outcome(client, rater_a, moves[0]['id']).status_code == 403


# ==================== SELF-UPLOAD FLAG ====================

def test_self_upload_off_blocks_non_admin_upload_and_owner_flow(client, clean_db, admin, newcomer, monkeypatch):
    res = client.post('/api/videos/register', json={'filename': 'mine.mp4'}, headers=auth(newcomer))
    assert res.status_code == 403 and 'SELF_UPLOAD_ENABLED' in res.json()['detail']

    # Admins upload regardless; their videos are paper footage.
    video = register_video(client, admin)
    assert video['source_type'] == 'public_broadcast'

    # A community video left over from when the flag was on: its owner can
    # read it but neither upload nor edit nor label while the flag is off.
    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    community = register_video(client, newcomer, filename='mine.mp4')
    move = create_move(client, newcomer, community['id'])
    monkeypatch.delenv('SELF_UPLOAD_ENABLED')
    assert client.get(f'/api/videos/{community["id"]}', headers=auth(newcomer)).status_code == 200
    assert client.post(f'/api/videos/{community["id"]}/upload-url',
                       json={'filename': 'mine.mp4', 'content_type': 'video/mp4'},
                       headers=auth(newcomer)).status_code == 403
    assert client.post(f'/api/videos/{community["id"]}/confirm-upload', json={},
                       headers=auth(newcomer)).status_code == 403
    assert client.post('/api/holds', json={'video_id': community['id'], 'bbox_x': 0.1, 'bbox_y': 0.1,
                                           'bbox_w': 0.1, 'bbox_h': 0.1}, headers=auth(newcomer)).status_code == 403
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'x'},
                      headers=auth(newcomer)).status_code == 403
    assert post_outcome(client, newcomer, move['id']).status_code == 403


def test_self_upload_on_creates_community_videos_excluded_from_paper_exports(
        client, admin, rater_a, newcomer, monkeypatch):
    paper, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, paper['id'], rater_a)
    label_all(client, hold, moves, rater_a)

    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    community = ready_video(client, newcomer, filename='mine.mp4')
    assert community['source_type'] == 'community'
    move = create_move(client, newcomer, community['id'])
    assert post_outcome(client, newcomer, move['id'], 'fall').status_code == 201
    assert post_tag(client, newcomer, move['id']).status_code == 201

    default = parse_csv(client.get('/api/admin/export/long', headers=auth(admin)).text)
    assert {r['video_id'] for r in default} == {str(paper['id'])}
    widened = parse_csv(client.get('/api/admin/export/long?include_community=true', headers=auth(admin)).text)
    community_rows = [r for r in widened if r['video_id'] == str(community['id'])]
    assert {r['source_type'] for r in community_rows} == {'community'}
    # The owner's own labels: strategy from the move row (with effort), sensation tags.
    assert {r['lens'] for r in community_rows} == {'strategy', 'outcome', 'frame_tags'}
    assert any(r['field'] == 'effort_level' and r['value'] == '7' for r in community_rows)

    full = parse_csv(client.get('/api/admin/export/full', headers=auth(admin)).text)
    assert {r['video_id'] for r in full} == {str(paper['id'])}


def test_owner_locked_out_of_structure_once_ready_admin_can_reopen(client, admin, newcomer, monkeypatch):
    """Community flow (flag on): a non-admin owner loses hold/move edits at ready."""
    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    video = register_video(client, newcomer)
    hold = create_hold(client, newcomer, video['id'])
    move = create_move(client, newcomer, video['id'])
    mark_ready(client, admin, video['id'])  # community: no provenance gate

    assert client.put(f'/api/holds/{hold["id"]}', json={'bbox_x': 0.9}, headers=auth(newcomer)).status_code == 403
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'x'}, headers=auth(newcomer)).status_code == 403
    assert post_outcome(client, newcomer, move['id']).status_code == 201
    client.post(f'/api/admin/videos/{video["id"]}/reopen', headers=auth(admin))
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'again'},
                      headers=auth(newcomer)).status_code == 200


# ==================== EXPORTS ====================

def test_long_export_shape_and_provenance(client, admin, rater_a, rater_b, rater_c):
    athlete = make_athlete(client, admin, birth_year=1996, height_cm=168,
                           url='https://ifsc.results.info/athlete/secret-key')
    video, hold, moves = prepped_video(client, admin, n_moves=3, overlap=True, athlete=athlete)
    for rater in (rater_a, rater_b, rater_c):
        assign(client, admin, video['id'], rater)
    label_all(client, hold, moves, rater_a, approach='static', wall_angle='steep', result='success')
    label_all(client, hold, moves, rater_b, approach='static', wall_angle='slab', result='fall')
    label_all(client, hold, moves, rater_c, approach='dynamic', wall_angle='steep', result='success')

    single, s_hold, s_moves = prepped_video(client, admin, n_moves=1, overlap=False, athlete=athlete)
    assign(client, admin, single['id'], rater_a)
    label_all(client, s_hold, s_moves, rater_a)

    res = client.get('/api/admin/export/long', headers=auth(admin))
    assert res.status_code == 200 and res.headers['content-type'].startswith('text/csv')
    assert 'secret-key' not in res.text  # the IFSC profile URL never leaves the admin view
    rows = parse_csv(res.text)
    assert list(rows[0].keys()) == LONG_COLUMNS
    for gone in ('dataset', 'cohort', 'rater_tier'):
        assert gone not in rows[0]

    n_env = 1 + 3 * len(HOLD_SLOTS)
    n_strategy, n_outcome = 5, 3   # approach, move_tags, size, form_quality, confidence (no effort)
    per = n_env + n_strategy + n_outcome
    overlap_rows = [r for r in rows if r['video_id'] == str(video['id'])]
    assert len(overlap_rows) == 3 * 3 * per
    assert {r['irr_overlap'] for r in overlap_rows} == {'true'}
    assert {r['irr_overlap'] for r in rows if r['video_id'] == str(single['id'])} == {'false'}
    assert not any(r['field'] == 'effort_level' for r in rows)

    first = overlap_rows[0]
    assert first['source_type'] == 'public_broadcast' and first['source_url'] == SOURCE_URL
    assert first['clip_start_ms'] == '723500' and first['clip_end_ms'] == '761000'
    assert first['event_date'] == EVENT_DATE and first['event_name'] == 'IFSC World Cup Example 2026'
    assert first['athlete_id'] == athlete['athlete_id']
    assert first['height_cm'] == '168' and first['height_source'] == 'ifsc_profile'

    approach = {(r['rater_user_id'], r['value']) for r in overlap_rows if r['field'] == 'approach'}
    assert approach == {(rater_a, 'static'), (rater_b, 'static'), (rater_c, 'dynamic')}

    # overlap_only narrows to the subset; video_id to one video.
    only = parse_csv(client.get('/api/admin/export/long?overlap_only=true', headers=auth(admin)).text)
    assert {r['video_id'] for r in only} == {str(video['id'])}
    assert len(parse_csv(client.get(f'/api/admin/export/long?video_id={single["id"]}',
                                    headers=auth(admin)).text)) == per

    keys = [(int(r['video_id']), int(r['move_index']), r['rater_user_id'], r['lens'], r['field'], r['value'])
            for r in rows]
    assert keys == sorted(keys)
    assert client.get('/api/admin/export/long', headers=auth(admin)).text == res.text

    # Feeds scripts/irr_alpha.py: overlap subset only, strategy now varies.
    pytest.importorskip('krippendorff')
    from scripts import irr_alpha
    subset = [r for r in rows if r['irr_overlap'] == 'true']
    alpha = {(r['lens'], r['field']): r for r in irr_alpha.compute(subset)}
    assert alpha[('strategy', 'approach')]['n_raters'] == 3
    assert alpha[('strategy', 'approach')]['alpha'] < 1.0
    assert alpha[('outcome', 'result')]['n_units'] == 3


def test_full_export_columns_and_rater_strategy(client, fake_r2, admin, rater_a):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    label_all(client, hold, moves, rater_a, approach='coordination')
    assert post_tag(client, rater_a, moves[0]['id'], frame=0).status_code == 201

    rows = parse_csv(client.get('/api/admin/export/full', headers=auth(admin)).text)
    pose_columns = ['frame_number', 'timestamp_ms', 'left_elbow_angle']
    assert list(rows[0].keys()) == FULL_ID_COLUMNS + pose_columns + Exporter.label_columns()
    assert len(rows) == POSE_CSV.count('\n') - 1
    first = rows[0]
    assert first['rater_user_id'] == rater_a and first['owner_user_id'] == admin
    assert first['irr_overlap'] == 'false' and first['source_url'] == SOURCE_URL
    # The rater's own strategy, not the canonical move row's 'dynamic'.
    assert first['approach'] == 'coordination' and first['effort_level'] == ''
    assert first['wall_angle'] == 'steep' and first['start_left_hold_bbox'] == '0.4,0.5,0.06,0.05'
    assert first['tag_types'] == 'sharp_pain'


def test_admin_full_export_gates_on_pose(client, fake_r2, admin, rater_a):
    done_video, _, _ = prepped_video(client, admin, n_moves=1)
    assign(client, admin, done_video['id'], rater_a)
    pending = register_video(client, admin, filename='pending.mp4')
    create_move(client, admin, pending['id'])

    res = client.get(f'/api/admin/export/full?video_id={pending["id"]}', headers=auth(admin))
    assert res.status_code == 409
    assert client.get('/api/admin/export/full?video_id=999999', headers=auth(admin)).status_code == 404
    rows = parse_csv(client.get('/api/admin/export/full', headers=auth(admin)).text)
    assert {r['video_id'] for r in rows} == {str(done_video['id'])}  # drafts excluded by default
    assert client.get(f'/api/admin/export/long?video_id={pending["id"]}', headers=auth(admin)).status_code == 200


def test_taxonomy_version_is_stamped(client, clean_db, admin, rater_a):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    strategy = post_strategy(client, rater_a, moves[0]['id']).json()
    env = post_env(client, rater_a, moves[0]['id'], hold['id']).json()
    out = post_outcome(client, rater_a, moves[0]['id']).json()
    for row in (strategy, env, out):
        assert row['taxonomy_version'] == TAXONOMY_VERSION and row['is_gold'] is False


# ==================== PLAYBACK / POSE ====================

def test_playback_url_for_rater_and_admin_404_otherwise(client, admin, rater_a, rater_b):
    unuploaded = register_video(client, admin, filename='later.mp4')
    assert client.get(f'/api/videos/{unuploaded["id"]}/video-url', headers=auth(admin)).status_code == 404
    video, _, _ = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)
    for user in (admin, rater_a):
        res = client.get(f'/api/videos/{video["id"]}/video-url', headers=auth(user))
        assert res.status_code == 200 and res.json()['url'].startswith('http')
    assert client.get(f'/api/videos/{video["id"]}/video-url', headers=auth(rater_b)).status_code == 404


def test_rater_can_poll_pose_status_but_not_retry(client, admin, rater_a, rater_b, enqueued):
    video, _, _ = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)
    assert client.get(f'/api/videos/{video["id"]}/status', headers=auth(rater_a)).json()['pose_status'] == 'done'
    assert client.get(f'/api/videos/{video["id"]}/status', headers=auth(rater_b)).status_code == 404
    client.post(f'/api/videos/{video["id"]}/pose-result', json={'status': 'failed', 'error': 'gpu'},
                headers={'X-Webhook-Secret': WORKER_SECRET})
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(rater_a)).status_code == 403
    enqueued.clear()
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(admin)).status_code == 200
    assert [c['video_id'] for c in enqueued] == [video['id']]


# ==================== REVIEW HARDENING ====================

def test_exports_ignore_unassigned_labelers_and_drafts(client, clean_db, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    label_all(client, hold, moves, rater_a)
    # A row written around the API by someone not assigned (or since unassigned).
    with clean_db.get_connection() as conn:
        conn.execute("INSERT INTO strategies (move_id, user_id, approach, size, form_quality) "
                     "VALUES (%s, %s, 'static', 'small', 1)", (moves[0]['id'], rater_b))
    rows = parse_csv(client.get('/api/admin/export/long', headers=auth(admin)).text)
    assert {r['rater_user_id'] for r in rows} == {rater_a}

    # A draft (mid-prep, or failed the gate) is not exported unless asked for,
    # and a paper clip with nobody assigned contributes no "rater" rows.
    draft = ready_video(client, admin, filename='draft.mp4')
    create_move(client, admin, draft['id'])
    rows = parse_csv(client.get('/api/admin/export/long', headers=auth(admin)).text)
    assert {r['video_id'] for r in rows} == {str(video['id'])}
    rows = parse_csv(client.get('/api/admin/export/long?include_drafts=true', headers=auth(admin)).text)
    assert {r['video_id'] for r in rows} == {str(video['id'])}  # draft has no assigned rater
    full = parse_csv(client.get('/api/admin/export/full?include_drafts=true', headers=auth(admin)).text)
    assert {r['video_id'] for r in full} == {str(video['id'])}


def test_provenance_is_locked_once_ready(client, admin):
    video, _, _ = prepped_video(client, admin, n_moves=1)
    url = f'/api/admin/videos/{video["id"]}/metadata'
    minor = make_athlete(client, admin, birth_year=2012)
    res = client.put(url, json={'athlete_id': minor['athlete_id']}, headers=auth(admin))
    assert res.status_code == 409 and 'reopen' in res.json()['detail']
    for field, value in (('event_date', '2030-01-01'), ('source_url', 'https://x'), ('clip_end_ms', 999999)):
        assert client.put(url, json={field: value}, headers=auth(admin)).status_code == 409, field
    # Non-provenance prep notes are still editable.
    assert client.put(url, json={'notes': 'fine'}, headers=auth(admin)).status_code == 200

    client.post(f'/api/admin/videos/{video["id"]}/reopen', headers=auth(admin))
    assert client.put(url, json={'athlete_id': minor['athlete_id']}, headers=auth(admin)).status_code == 200
    res = client.post(f'/api/admin/videos/{video["id"]}/ready', headers=auth(admin))
    assert res.status_code == 422 and 'under 18' in res.json()['detail']


def test_athlete_birth_year_change_cannot_make_a_ready_clip_underage(client, admin):
    athlete = make_athlete(client, admin, birth_year=1995)
    prepped_video(client, admin, n_moves=1, athlete=athlete)
    url = f'/api/admin/athletes/{athlete["athlete_id"]}'
    res = client.put(url, json={'birth_year': 2010}, headers=auth(admin))
    assert res.status_code == 409
    assert client.put(url, json={'birth_year': 1996}, headers=auth(admin)).status_code == 200


def test_raters_do_not_see_prep_strategy_or_the_overlap_flag(client, admin, rater_a):
    video, _, moves = prepped_video(client, admin, n_moves=1, overlap=True)
    client.put(f'/api/admin/videos/{video["id"]}/metadata', json={'notes': 'prepper note'},
               headers=auth(admin))
    assign(client, admin, video['id'], rater_a)

    listed = client.get(f'/api/videos/{video["id"]}/moves', headers=auth(rater_a)).json()[0]
    single = client.get(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_a)).json()
    for move in (listed, single):
        assert move['approach'] == '' and move['size'] == '' and move['move_tags'] == []
        assert move['effort_level'] == 0 and move['description'] == ''
        assert move['frame_start'] == 0 and move['frame_end'] == 2
    assert client.get(f'/api/moves/{moves[0]["id"]}', headers=auth(admin)).json()['approach'] == 'dynamic'

    for body in (client.get(f'/api/videos/{video["id"]}', headers=auth(rater_a)).json(),
                 client.get('/api/me/assignments', headers=auth(rater_a)).json()[0]['video']):
        assert body['irr_overlap'] is False and body['rater_target'] == 1
        assert body['irr_overlap_set_by'] is None and body['notes'] is None
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(admin)).json()['irr_overlap'] is True


def test_retry_pose_needs_the_flag_for_a_non_admin_owner(client, newcomer, monkeypatch, enqueued):
    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    video = register_video(client, newcomer, filename='mine.mp4')
    from tests.test_api_scoping import upload_video
    upload_video(client, newcomer, video)
    client.post(f'/api/videos/{video["id"]}/pose-result', json={'status': 'failed', 'error': 'x'},
                headers={'X-Webhook-Secret': WORKER_SECRET})
    monkeypatch.delenv('SELF_UPLOAD_ENABLED')
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(newcomer)).status_code == 403
