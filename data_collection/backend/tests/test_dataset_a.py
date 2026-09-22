"""
Dataset A (runbook W1 Backend): prep/rating split, assignments, rater
profiles, admin routes, long-format export.

Three users throughout: an admin who preps a video, and two raters who label
it independently. Every test asserts the scoping rules from
claude-ops/runbook-w1-backend.md, plus that the Dataset B self-upload flow is
untouched (tests/test_api_scoping.py keeps covering that directly).
"""
import csv
import io
import uuid

import pytest
from fastapi.testclient import TestClient

from src.labeling.exporter import LONG_COLUMNS, FULL_ID_COLUMNS, Exporter
from src.labeling.models import TAXONOMY_VERSION, HOLD_SLOTS
from src.web import api as api_module
from tests.conftest import make_jwt, requires_db
from tests.test_api_scoping import (
    POSE_CSV, auth, create_move, register_video,
)

pytestmark = requires_db


# ==================== FIXTURES / HELPERS ====================

@pytest.fixture
def client(clean_db, fake_r2, monkeypatch):
    monkeypatch.setattr(api_module, '_db', clean_db)
    monkeypatch.setattr(api_module, '_exporter', None)
    monkeypatch.setattr(api_module, '_admin_exporter', None)
    with TestClient(api_module.app) as test_client:
        yield test_client


@pytest.fixture
def admin(client, clean_db) -> str:
    """A user with a profile flagged is_admin (the way Jolie will do it: SQL)."""
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, 'Admin')
    with clean_db.get_connection() as conn:
        conn.execute(
            'UPDATE rater_profiles SET is_admin = true WHERE user_id = %s', (user_id,)
        )
    return user_id


@pytest.fixture
def rater_a(client) -> str:
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, 'Rater A')
    return user_id


@pytest.fixture
def rater_b(client) -> str:
    user_id = str(uuid.uuid4())
    make_profile(client, user_id, 'Rater B')
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


def create_hold(client, user_id, video_id, x=0.4):
    res = client.post(
        '/api/holds',
        json={'video_id': video_id, 'bbox_x': x, 'bbox_y': 0.5,
              'bbox_w': 0.06, 'bbox_h': 0.05, 'source': 'manual'},
        headers=auth(user_id),
    )
    assert res.status_code == 201, res.text
    return res.json()


def assign(client, admin, video_id, rater, cohort='validated'):
    res = client.post(
        '/api/admin/assignments',
        json={'video_id': video_id, 'rater_user_id': rater, 'cohort': cohort},
        headers=auth(admin),
    )
    assert res.status_code == 201, res.text
    return res.json()


def mark_ready(client, admin, video_id):
    res = client.post(f'/api/admin/videos/{video_id}/ready', headers=auth(admin))
    assert res.status_code == 200, res.text
    assert res.json()['prep_status'] == 'ready'
    assert res.json()['dataset'] == 'A'
    return res.json()


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


def prepped_video(client, admin, n_moves=3):
    """Admin uploads, draws one hold, defines n canonical moves, marks ready."""
    video = register_video(client, admin, filename='prep.mp4')
    hold = create_hold(client, admin, video['id'])
    moves = [create_move(client, admin, video['id']) for _ in range(n_moves)]
    mark_ready(client, admin, video['id'])
    return video, hold, moves


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


# ==================== PROFILE GATE ====================

def test_profile_404_until_created_then_409_on_repeat(client):
    user = str(uuid.uuid4())
    assert client.get('/api/me/profile', headers=auth(user)).status_code == 404

    created = make_profile(client, user, 'New Rater')
    assert created['tier'] == 'open'
    assert created['is_admin'] is False
    assert created['validation_note'] is None

    assert client.get('/api/me/profile', headers=auth(user)).status_code == 200
    again = client.post('/api/me/profile', json={'display_name': 'x'}, headers=auth(user))
    assert again.status_code == 409


def test_profile_self_update_cannot_touch_admin_fields(client):
    user = str(uuid.uuid4())
    assert client.put('/api/me/profile', json={'display_name': 'x'}, headers=auth(user)).status_code == 404
    make_profile(client, user)

    res = client.put(
        '/api/me/profile',
        json={'display_name': 'Renamed', 'years_climbing': 9, 'coaching_cert': '',
              'tier': 'validated', 'is_admin': True, 'validation_note': 'me'},
        headers=auth(user),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['display_name'] == 'Renamed'
    assert body['years_climbing'] == 9
    assert body['coaching_cert'] is None
    assert body['tier'] == 'open'
    assert body['is_admin'] is False
    assert body['validation_note'] is None


def test_config_exposes_taxonomy_version(client, rater_a):
    res = client.get('/api/config', headers=auth(rater_a))
    assert res.status_code == 200
    assert res.json()['version'] == TAXONOMY_VERSION


# ==================== ADMIN GUARDS ====================

ADMIN_ROUTES = [
    ('get', '/api/admin/videos', None),
    ('put', '/api/admin/videos/1/metadata', {'gym': 'x'}),
    ('post', '/api/admin/videos/1/ready', None),
    ('post', '/api/admin/videos/1/close', None),
    ('post', '/api/admin/videos/1/reopen', None),
    ('get', '/api/admin/assignments', None),
    ('post', '/api/admin/assignments', {'video_id': 1, 'rater_user_id': 'x', 'cohort': 'validated'}),
    ('delete', '/api/admin/assignments/1', None),
    ('get', '/api/admin/raters', None),
    ('put', '/api/admin/raters/x', {'tier': 'validated'}),
    ('get', '/api/admin/export/long', None),
    ('get', '/api/admin/export/full', None),
]


@pytest.mark.parametrize('method,path,body', ADMIN_ROUTES)
def test_admin_routes_are_403_for_non_admins(client, rater_a, method, path, body):
    res = client.request(method.upper(), path, json=body, headers=auth(rater_a))
    assert res.status_code == 403, f'{method} {path}: {res.status_code} {res.text}'
    # A user with no profile at all is refused the same way.
    res = client.request(method.upper(), path, json=body, headers=auth(str(uuid.uuid4())))
    assert res.status_code == 403


def test_admin_can_promote_and_validate_a_rater(client, admin, rater_a):
    res = client.put(
        f'/api/admin/raters/{rater_a}',
        json={'tier': 'validated', 'validation_note': 'coach, 10y'},
        headers=auth(admin),
    )
    assert res.status_code == 200, res.text
    assert res.json()['tier'] == 'validated'
    assert res.json()['validation_note'] == 'coach, 10y'

    raters = client.get('/api/admin/raters', headers=auth(admin)).json()
    assert {r['user_id'] for r in raters} == {admin, rater_a}

    assert client.put(f'/api/admin/raters/{rater_a}', json={'tier': 'elite'},
                      headers=auth(admin)).status_code == 400
    assert client.put(f'/api/admin/raters/{uuid.uuid4()}', json={'tier': 'open'},
                      headers=auth(admin)).status_code == 404


# ==================== ASSIGNMENT CRUD ====================

def test_assignment_crud(client, admin, rater_a, rater_b):
    video, _, _ = prepped_video(client, admin)

    a = assign(client, admin, video['id'], rater_a, 'validated')
    assert a['status'] == 'assigned' and a['cohort'] == 'validated'
    assert a['completed_at'] is None

    # Duplicate, bad cohort, missing video, rater without a profile.
    dup = client.post('/api/admin/assignments',
                      json={'video_id': video['id'], 'rater_user_id': rater_a, 'cohort': 'overlap'},
                      headers=auth(admin))
    assert dup.status_code == 409
    assert client.post('/api/admin/assignments',
                       json={'video_id': video['id'], 'rater_user_id': rater_b, 'cohort': 'nope'},
                       headers=auth(admin)).status_code == 400
    assert client.post('/api/admin/assignments',
                       json={'video_id': 999999, 'rater_user_id': rater_b, 'cohort': 'overlap'},
                       headers=auth(admin)).status_code == 404
    assert client.post('/api/admin/assignments',
                       json={'video_id': video['id'], 'rater_user_id': str(uuid.uuid4()),
                             'cohort': 'overlap'},
                       headers=auth(admin)).status_code == 404

    b = assign(client, admin, video['id'], rater_b, 'overlap')
    listed = client.get(f'/api/admin/assignments?video_id={video["id"]}', headers=auth(admin)).json()
    assert [x['id'] for x in listed] == [a['id'], b['id']]

    # Admin video list shows the count.
    admin_videos = client.get('/api/admin/videos', headers=auth(admin)).json()
    row = next(v for v in admin_videos if v['video']['id'] == video['id'])
    assert row['assignment_count'] == 2 and row['done_count'] == 0

    # Rater queue.
    queue = client.get('/api/me/assignments', headers=auth(rater_a)).json()
    assert len(queue) == 1
    assert queue[0]['assignment']['id'] == a['id']
    assert queue[0]['video']['id'] == video['id']
    assert queue[0]['video']['access_role'] == 'rater'
    assert queue[0]['move_count'] == 3

    assert client.delete(f'/api/admin/assignments/{b["id"]}', headers=auth(admin)).status_code == 204
    assert client.delete(f'/api/admin/assignments/{b["id"]}', headers=auth(admin)).status_code == 404
    assert client.get('/api/me/assignments', headers=auth(rater_b)).json() == []


# ==================== RATER SCOPING ====================

def test_rater_reads_assigned_video_and_not_unassigned(client, fake_r2, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin)
    other, _, _ = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)

    # Assigned: video, holds, moves, csv.
    res = client.get(f'/api/videos/{video["id"]}', headers=auth(rater_a))
    assert res.status_code == 200
    assert res.json()['access_role'] == 'rater'
    assert res.json()['owner_user_id'] == admin
    assert [h['id'] for h in client.get(f'/api/videos/{video["id"]}/holds', headers=auth(rater_a)).json()] == [hold['id']]
    assert len(client.get(f'/api/videos/{video["id"]}/moves', headers=auth(rater_a)).json()) == 3
    assert client.get(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_a)).status_code == 200
    csv_res = client.get(f'/api/videos/{video["id"]}/csv', headers=auth(rater_a), follow_redirects=False)
    assert csv_res.status_code == 307

    # Unassigned video: 404 everywhere, not 403.
    for path in (f'/api/videos/{other["id"]}', f'/api/videos/{other["id"]}/holds',
                 f'/api/videos/{other["id"]}/moves', f'/api/videos/{other["id"]}/csv'):
        assert client.get(path, headers=auth(rater_a), follow_redirects=False).status_code == 404, path
    # And rater_b, assigned to nothing, sees nothing.
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.get(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_b)).status_code == 404

    # The video does not show up in "My videos" (that list is owner-only).
    assert client.get('/api/videos', headers=auth(rater_a)).json() == []


def test_raters_never_see_each_others_labels(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    assign(client, admin, video['id'], rater_b, 'overlap')
    move_id = moves[0]['id']

    env_a = post_env(client, rater_a, move_id, hold['id'], 'steep')
    assert env_a.status_code == 201, env_a.text
    out_a = post_outcome(client, rater_a, move_id, 'success')
    assert out_a.status_code == 201, out_a.text
    tag_a = post_tag(client, rater_a, move_id)
    assert tag_a.status_code == 201, tag_a.text

    # Rater B sees none of A's rows on the same move.
    assert client.get(f'/api/moves/{move_id}/environment', headers=auth(rater_b)).status_code == 404
    assert client.get(f'/api/moves/{move_id}/outcome', headers=auth(rater_b)).status_code == 404
    assert client.get(f'/api/moves/{move_id}/frame-tags', headers=auth(rater_b)).json() == []
    assert client.get(f'/api/videos/{video["id"]}/moves', headers=auth(rater_b)).json()[0]['frame_tag_count'] == 0

    # ...and cannot touch them by id.
    assert client.put(f'/api/environments/{env_a.json()["id"]}', json={'wall_angle': 'slab'},
                      headers=auth(rater_b)).status_code == 404
    assert client.delete(f'/api/environments/{env_a.json()["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.put(f'/api/outcomes/{out_a.json()["id"]}', json={'result': 'fall'},
                      headers=auth(rater_b)).status_code == 404
    assert client.delete(f'/api/outcomes/{out_a.json()["id"]}', headers=auth(rater_b)).status_code == 404
    assert client.delete(f'/api/frame-tags/{tag_a.json()["id"]}', headers=auth(rater_b)).status_code == 404

    # B can write their own on the same move (UNIQUE(move_id, user_id)).
    env_b = post_env(client, rater_b, move_id, hold['id'], 'slab')
    assert env_b.status_code == 201, env_b.text
    assert post_outcome(client, rater_b, move_id, 'fall').status_code == 201
    assert client.get(f'/api/moves/{move_id}/environment', headers=auth(rater_b)).json()['wall_angle'] == 'slab'
    assert client.get(f'/api/moves/{move_id}/environment', headers=auth(rater_a)).json()['wall_angle'] == 'steep'
    # A second environment by the same rater is still a conflict.
    assert post_env(client, rater_b, move_id).status_code == 409

    # Rater A's first write moved the assignment to in_progress.
    queue = client.get('/api/me/assignments', headers=auth(rater_a)).json()
    assert queue[0]['assignment']['status'] == 'in_progress'


def test_rater_cannot_mutate_holds_or_moves(client, admin, rater_a):
    video, hold, moves = prepped_video(client, admin)
    assign(client, admin, video['id'], rater_a)

    res = client.post('/api/holds', json={'video_id': video['id'], 'bbox_x': 0.1, 'bbox_y': 0.1,
                                          'bbox_w': 0.1, 'bbox_h': 0.1}, headers=auth(rater_a))
    assert res.status_code == 403
    assert client.post(f'/api/videos/{video["id"]}/holds',
                       json={'holds': [{'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.1, 'bbox_h': 0.1}]},
                       headers=auth(rater_a)).status_code == 403
    assert client.put(f'/api/holds/{hold["id"]}', json={'bbox_x': 0.9}, headers=auth(rater_a)).status_code == 403
    assert client.delete(f'/api/holds/{hold["id"]}', headers=auth(rater_a)).status_code == 403

    res = client.post('/api/moves', json={
        'video_id': video['id'], 'frame_start': 0, 'frame_end': 1,
        'timestamp_start_ms': 0.0, 'timestamp_end_ms': 33.0,
        'approach': 'dynamic', 'size': 'large', 'move_tags': [], 'form_quality': 3,
        'effort_level': 3, 'confidence': 'high', 'description': ''}, headers=auth(rater_a))
    assert res.status_code == 403
    assert client.put(f'/api/moves/{moves[0]["id"]}', json={'description': 'x'},
                      headers=auth(rater_a)).status_code == 403
    assert client.delete(f'/api/moves/{moves[0]["id"]}', headers=auth(rater_a)).status_code == 403

    # Nothing changed.
    assert len(client.get(f'/api/videos/{video["id"]}/holds', headers=auth(admin)).json()) == 1
    assert len(client.get(f'/api/videos/{video["id"]}/moves', headers=auth(admin)).json()) == 3


def test_owner_locked_out_of_structure_once_ready_admin_can_reopen(client, admin, rater_a):
    """A non-admin owner (Dataset B uploader) loses hold/move edits at ready."""
    owner = rater_a
    video = register_video(client, owner)
    hold = create_hold(client, owner, video['id'])
    move = create_move(client, owner, video['id'])

    mark_ready(client, admin, video['id'])

    assert client.put(f'/api/holds/{hold["id"]}', json={'bbox_x': 0.9}, headers=auth(owner)).status_code == 403
    assert client.delete(f'/api/holds/{hold["id"]}', headers=auth(owner)).status_code == 403
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'x'}, headers=auth(owner)).status_code == 403
    assert client.delete(f'/api/moves/{move["id"]}', headers=auth(owner)).status_code == 403
    assert client.post('/api/holds', json={'video_id': video['id'], 'bbox_x': 0.1, 'bbox_y': 0.1,
                                           'bbox_w': 0.1, 'bbox_h': 0.1}, headers=auth(owner)).status_code == 403
    # The owner can still read and still label their own video.
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(owner)).json()['prep_status'] == 'ready'
    assert post_outcome(client, owner, move['id']).status_code == 201

    # Admin edits through the lock, then reopens for the owner.
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'admin fix'},
                      headers=auth(admin)).status_code == 200
    res = client.post(f'/api/admin/videos/{video["id"]}/reopen', headers=auth(admin))
    assert res.status_code == 200 and res.json()['prep_status'] == 'draft'
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'owner again'},
                      headers=auth(owner)).status_code == 200


def test_closed_video_blocks_rater_label_writes(client, admin, rater_a):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    env = post_env(client, rater_a, moves[0]['id'], hold['id'])
    assert env.status_code == 201

    res = client.post(f'/api/admin/videos/{video["id"]}/close', headers=auth(admin))
    assert res.status_code == 200 and res.json()['prep_status'] == 'closed'

    assert post_outcome(client, rater_a, moves[0]['id']).status_code == 403
    assert post_tag(client, rater_a, moves[0]['id']).status_code == 403
    assert client.put(f'/api/environments/{env.json()["id"]}', json={'wall_angle': 'slab'},
                      headers=auth(rater_a)).status_code == 403
    assert client.delete(f'/api/environments/{env.json()["id"]}', headers=auth(rater_a)).status_code == 403
    # Reads still work.
    assert client.get(f'/api/moves/{moves[0]["id"]}/environment', headers=auth(rater_a)).status_code == 200


# ==================== COMPLETE VALIDATION ====================

def test_complete_validates_every_move_then_succeeds(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=3)
    a = assign(client, admin, video['id'], rater_a)

    # Someone else's assignment id is 404.
    assert client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_b)).status_code == 404

    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.status_code == 422, res.text
    assert res.json()['missing'] == [
        {'move_id': m['id'], 'move_index': i, 'missing': ['environment', 'outcome']}
        for i, m in enumerate(moves)
    ]

    assert post_env(client, rater_a, moves[0]['id'], hold['id']).status_code == 201
    assert post_outcome(client, rater_a, moves[0]['id']).status_code == 201
    assert post_env(client, rater_a, moves[1]['id'], hold['id']).status_code == 201
    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.status_code == 422
    assert res.json()['missing'] == [
        {'move_id': moves[1]['id'], 'move_index': 1, 'missing': ['outcome']},
        {'move_id': moves[2]['id'], 'move_index': 2, 'missing': ['environment', 'outcome']},
    ]

    assert post_outcome(client, rater_a, moves[1]['id']).status_code == 201
    assert post_env(client, rater_a, moves[2]['id'], hold['id']).status_code == 201
    assert post_outcome(client, rater_a, moves[2]['id']).status_code == 201
    res = client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a))
    assert res.status_code == 200, res.text
    assert res.json()['status'] == 'done'
    assert res.json()['completed_at']

    # Done is final: no more label writes, complete is idempotent.
    assert post_tag(client, rater_a, moves[0]['id']).status_code == 403
    assert client.post(f'/api/assignments/{a["id"]}/complete', headers=auth(rater_a)).status_code == 200
    assert client.post(f'/api/assignments/{a["id"]}/start', headers=auth(rater_a)).status_code == 403

    admin_videos = client.get('/api/admin/videos', headers=auth(admin)).json()
    row = next(v for v in admin_videos if v['video']['id'] == video['id'])
    assert row['done_count'] == 1


def test_start_moves_assignment_to_in_progress(client, admin, rater_a):
    video, _, _ = prepped_video(client, admin, n_moves=1)
    a = assign(client, admin, video['id'], rater_a)
    res = client.post(f'/api/assignments/{a["id"]}/start', headers=auth(rater_a))
    assert res.status_code == 200 and res.json()['status'] == 'in_progress'
    # Idempotent.
    assert client.post(f'/api/assignments/{a["id"]}/start', headers=auth(rater_a)).json()['status'] == 'in_progress'


# ==================== EXPORTS ====================

def _label_everything(client, hold, moves, rater, wall_angle, result, tags_per_move=1):
    for m in moves:
        assert post_env(client, rater, m['id'], hold['id'], wall_angle).status_code == 201
        assert post_outcome(client, rater, m['id'], result).status_code == 201
        for i in range(tags_per_move):
            assert post_tag(client, rater, m['id'], frame=i).status_code == 201


def test_long_export_shape(client, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=3)
    assign(client, admin, video['id'], rater_a, 'validated')
    assign(client, admin, video['id'], rater_b, 'overlap')
    client.put(f'/api/admin/raters/{rater_a}', json={'tier': 'validated'}, headers=auth(admin))
    _label_everything(client, hold, moves, rater_a, 'steep', 'success', tags_per_move=1)
    _label_everything(client, hold, moves, rater_b, 'slab', 'fall', tags_per_move=2)

    res = client.get('/api/admin/export/long', headers=auth(admin))
    assert res.status_code == 200, res.text
    assert res.headers['content-type'].startswith('text/csv')
    rows = parse_csv(res.text)
    assert list(rows[0].keys()) == LONG_COLUMNS

    n_env = 1 + 3 * len(HOLD_SLOTS)   # wall_angle + id/type/quality per slot
    n_strategy, n_outcome = 6, 3
    per_rater_per_move = n_env + n_strategy + n_outcome
    expected = 3 * (2 * per_rater_per_move + 1 + 2)  # + frame_tags rows (1 for A, 2 for B)
    assert len(rows) == expected

    # Rectangular per field: every (move, rater) has every strategy/env/outcome field.
    for lens, fields in (('strategy', 6), ('environment', n_env), ('outcome', n_outcome)):
        for m_idx in range(3):
            for rater in (rater_a, rater_b):
                got = [r for r in rows if r['lens'] == lens and r['move_index'] == str(m_idx)
                       and r['rater_user_id'] == rater]
                assert len(got) == fields, (lens, m_idx, rater)

    a_rows = [r for r in rows if r['rater_user_id'] == rater_a]
    assert {r['rater_tier'] for r in a_rows} == {'validated'}
    assert {r['cohort'] for r in a_rows} == {'validated'}
    assert {r['cohort'] for r in rows if r['rater_user_id'] == rater_b} == {'overlap'}
    assert {r['dataset'] for r in rows} == {'A'}
    assert {r['taxonomy_version'] for r in rows} == {TAXONOMY_VERSION}
    assert {r['is_gold'] for r in rows} == {'false'}

    wall = {(r['rater_user_id'], r['value']) for r in rows if r['field'] == 'wall_angle'}
    assert wall == {(rater_a, 'steep'), (rater_b, 'slab')}
    quality = {r['value'] for r in rows if r['field'] == 'start_left_hold_quality'}
    assert quality == {'incut|small'}
    move_tags = {r['value'] for r in rows if r['field'] == 'move_tags'}
    assert move_tags == {'dyno|technical'}

    tag_rows = [r for r in rows if r['lens'] == 'frame_tags']
    assert {r['field'] for r in tag_rows} == {'sharp_pain'}
    assert '0:6:left:left_shoulder|left_elbow' in {r['value'] for r in tag_rows}

    # Deterministic: same bytes twice.
    assert client.get('/api/admin/export/long', headers=auth(admin)).text == res.text
    # Sorted by video, move, rater, lens, field.
    keys = [(int(r['video_id']), int(r['move_index']), r['rater_user_id'], r['lens'], r['field'], r['value'])
            for r in rows]
    assert keys == sorted(keys)

    # ?video_id= narrows; ?dataset=all widens to B videos too.
    assert len(parse_csv(client.get(f'/api/admin/export/long?video_id={video["id"]}',
                                    headers=auth(admin)).text)) == expected
    b_video = register_video(client, rater_b, filename='mine.mp4')
    create_move(client, rater_b, b_video['id'])
    default_rows = parse_csv(client.get('/api/admin/export/long', headers=auth(admin)).text)
    assert {r['video_id'] for r in default_rows} == {str(video['id'])}
    all_rows = parse_csv(client.get('/api/admin/export/long?dataset=all', headers=auth(admin)).text)
    b_rows = [r for r in all_rows if r['video_id'] == str(b_video['id'])]
    assert len(b_rows) == 6  # strategy only, rater = the owner
    assert {r['rater_user_id'] for r in b_rows} == {rater_b}
    assert client.get('/api/admin/export/long?dataset=C', headers=auth(admin)).status_code == 400


def test_full_export_covers_every_user(client, fake_r2, admin, rater_a, rater_b):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    _label_everything(client, hold, moves, rater_a, 'steep', 'success')
    b_video = register_video(client, rater_b, filename='mine.mp4')
    b_move = create_move(client, rater_b, b_video['id'])
    assert post_outcome(client, rater_b, b_move['id'], 'fall').status_code == 201

    res = client.get('/api/admin/export/full', headers=auth(admin))
    assert res.status_code == 200, res.text
    rows = parse_csv(res.text)
    columns = list(rows[0].keys())
    pose_columns = ['frame_number', 'timestamp_ms', 'left_elbow_angle']
    assert columns == FULL_ID_COLUMNS + pose_columns + Exporter.label_columns()

    frames_per_video = POSE_CSV.count('\n') - 1
    # video A: rater_a only (assigned + labeled); video B: its owner.
    assert len(rows) == 2 * frames_per_video
    a_rows = [r for r in rows if r['video_id'] == str(video['id'])]
    assert {r['rater_user_id'] for r in a_rows} == {rater_a}
    assert {r['owner_user_id'] for r in a_rows} == {admin}
    assert {r['dataset'] for r in a_rows} == {'A'}
    assert a_rows[0]['wall_angle'] == 'steep' and a_rows[0]['result'] == 'success'
    assert a_rows[0]['left_elbow_angle'] == '170.0'
    assert a_rows[0]['start_left_hold_bbox'] == '0.4,0.5,0.06,0.05'
    assert a_rows[0]['tag_types'] == 'sharp_pain'
    b_rows = [r for r in rows if r['video_id'] == str(b_video['id'])]
    assert {r['rater_user_id'] for r in b_rows} == {rater_b}
    assert {r['dataset'] for r in b_rows} == {'B'}
    assert b_rows[0]['result'] == 'fall' and b_rows[0]['cohort'] == ''

    assert len(parse_csv(client.get('/api/admin/export/full?dataset=B', headers=auth(admin)).text)) == frames_per_video


def test_taxonomy_version_is_stamped(client, clean_db, admin, rater_a):
    video, hold, moves = prepped_video(client, admin, n_moves=1)
    assign(client, admin, video['id'], rater_a)
    env = post_env(client, rater_a, moves[0]['id'], hold['id']).json()
    out = post_outcome(client, rater_a, moves[0]['id']).json()
    tag = post_tag(client, rater_a, moves[0]['id']).json()
    for row in (env, out, tag):
        assert row['taxonomy_version'] == TAXONOMY_VERSION
        assert row['is_gold'] is False

    # An older row (pre-versioning) stays distinguishable until rewritten.
    with clean_db.get_connection() as conn:
        conn.execute("UPDATE outcomes SET taxonomy_version = DEFAULT WHERE id = %s", (out['id'],))
    assert client.get(f'/api/moves/{moves[0]["id"]}/outcome', headers=auth(rater_a)).json()['taxonomy_version'] == 'pre-3.1'
    res = client.put(f'/api/outcomes/{out["id"]}', json={'result': 'fall'}, headers=auth(rater_a))
    assert res.json()['taxonomy_version'] == TAXONOMY_VERSION


# ==================== DATASET B UNCHANGED ====================

def test_dataset_b_self_upload_defaults(client, rater_a):
    video = register_video(client, rater_a)
    assert video['dataset'] == 'B'
    assert video['prep_status'] == 'draft'
    assert video['owner_user_id'] == rater_a
    assert video['access_role'] == 'owner'
    move = create_move(client, rater_a, video['id'])
    hold = create_hold(client, rater_a, video['id'])
    assert post_env(client, rater_a, move['id'], hold['id']).status_code == 201
    assert client.put(f'/api/moves/{move["id"]}', json={'description': 'still mine'},
                      headers=auth(rater_a)).status_code == 200
    assert client.delete(f'/api/holds/{hold["id"]}', headers=auth(rater_a)).status_code == 204


def test_admin_metadata_update(client, admin):
    video = register_video(client, admin)
    res = client.put(f'/api/admin/videos/{video["id"]}/metadata',
                     json={'route_grade': 'V5', 'gym': 'BKB', 'climber_height_cm': 172,
                           'camera_angle': 'side', 'notes': 'n'},
                     headers=auth(admin))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['route_grade'] == 'V5' and body['gym'] == 'BKB' and body['climber_height_cm'] == 172
    res = client.put(f'/api/admin/videos/{video["id"]}/metadata', json={'gym': ''}, headers=auth(admin))
    assert res.json()['gym'] is None and res.json()['route_grade'] == 'V5'
    assert client.put(f'/api/admin/videos/{video["id"]}/metadata', json={'dataset': 'Z'},
                      headers=auth(admin)).status_code == 400
    assert client.put('/api/admin/videos/999999/metadata', json={}, headers=auth(admin)).status_code == 404
