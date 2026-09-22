"""
Resumable multipart upload — the iPhone path.

iOS Safari evicts the page on app switch or lock, so the original video goes
up in independently signed parts: a lock screen costs one part, not the clip.
These tests pin the contract the browser's resumable uploader depends on, and
the scoping guard that keeps one user's parts out of another user's object.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from src.labeling import pose_queue
from src.storage import r2
from src.web import api as api_module
from tests.conftest import make_jwt, requires_db  # noqa: F401 - fixtures live in conftest

WORKER_SECRET = 'test-worker-secret'

pytestmark = requires_db


@pytest.fixture
def client(clean_db, fake_r2, enqueued, monkeypatch):
    monkeypatch.setattr(api_module, '_db', clean_db)
    monkeypatch.setattr(api_module, '_exporter', None)
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', WORKER_SECRET)
    with TestClient(api_module.app) as test_client:
        yield test_client


def auth(user_id: str) -> dict:
    return {'Authorization': f'Bearer {make_jwt(user_id)}'}


def register_video(client, user_id, filename='climb.mov'):
    response = client.post(
        '/api/videos/register',
        json={
            'filename': filename,
            'fps': 30.0,
            'total_frames': 90,
            'duration_ms': 3000.0,
            'width': 1920,
            'height': 1080,
        },
        headers=auth(user_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_multipart(client, user_id, video, content_type='video/quicktime'):
    response = client.post(
        f'/api/videos/{video["id"]}/upload/create-multipart',
        json={'content_type': content_type},
        headers=auth(user_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ==================== CREATE ====================

def test_create_multipart_returns_key_upload_id_and_part_size(client, user_a):
    video = register_video(client, user_a)
    body = create_multipart(client, user_a, video)

    assert body['key'] == f'videos/{user_a}/{video["id"]}/climb.mov'
    assert body['upload_id']
    assert body['part_size'] == r2.MULTIPART_PART_SIZE
    # Every part but the last must clear R2's 5 MiB floor.
    assert body['part_size'] >= 5 * 1024 * 1024


def test_create_multipart_on_another_users_video_is_404(client, user_a, user_b):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/create-multipart',
        json={'content_type': 'video/mp4'},
        headers=auth(user_b),
    )
    assert response.status_code == 404


def test_create_multipart_without_a_token_is_401(client, user_a):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/create-multipart',
        json={'content_type': 'video/mp4'},
    )
    assert response.status_code in (401, 403)


# ==================== SIGN PART ====================

def test_sign_part_returns_a_url_for_that_part(client, user_a):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)

    response = client.post(
        f'/api/videos/{video["id"]}/upload/sign-part',
        json={'key': started['key'], 'upload_id': started['upload_id'], 'part_number': 3},
        headers=auth(user_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['part_number'] == 3
    assert body['url'].startswith('http')
    assert body['expires_in'] > 0


def test_sign_part_is_repeatable_for_a_resume(client, user_a):
    """A resumed upload re-signs the part it left off at; nothing is consumed."""
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)
    payload = {'key': started['key'], 'upload_id': started['upload_id'], 'part_number': 2}

    first = client.post(f'/api/videos/{video["id"]}/upload/sign-part', json=payload, headers=auth(user_a))
    second = client.post(f'/api/videos/{video["id"]}/upload/sign-part', json=payload, headers=auth(user_a))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()['part_number'] == 2


def test_part_number_below_one_is_rejected(client, user_a):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/sign-part',
        json={'key': started['key'], 'upload_id': started['upload_id'], 'part_number': 0},
        headers=auth(user_a),
    )
    assert response.status_code == 422


def test_sign_part_refuses_a_key_from_another_video(client, user_a):
    """The guard that stops parts being assembled into someone else's object."""
    mine = register_video(client, user_a, filename='mine.mov')
    started = create_multipart(client, user_a, mine)

    response = client.post(
        f'/api/videos/{mine["id"]}/upload/sign-part',
        json={
            'key': f'videos/{uuid.uuid4()}/999/theirs.mov',
            'upload_id': started['upload_id'],
            'part_number': 1,
        },
        headers=auth(user_a),
    )
    assert response.status_code == 400
    assert 'does not belong' in response.json()['detail'].lower()


# ==================== COMPLETE ====================

def test_complete_records_the_key_and_enqueues_the_worker(client, user_a, enqueued):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)

    response = client.post(
        f'/api/videos/{video["id"]}/upload/complete-multipart',
        json={
            'key': started['key'],
            'upload_id': started['upload_id'],
            'parts': [
                {'part_number': 1, 'etag': '"aaa"'},
                {'part_number': 2, 'etag': '"bbb"'},
            ],
        },
        headers=auth(user_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # Same post-conditions as confirm-upload: key recorded, job enqueued.
    assert body['pose_status'] == 'pending'
    assert enqueued, 'the pose worker was not enqueued'
    assert enqueued[-1]['r2_key'] == started['key']
    assert enqueued[-1]['video_id'] == video['id']


def test_complete_accepts_parts_out_of_order(client, user_a):
    """The browser finishes parts concurrently; order of report must not matter."""
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)

    response = client.post(
        f'/api/videos/{video["id"]}/upload/complete-multipart',
        json={
            'key': started['key'],
            'upload_id': started['upload_id'],
            'parts': [
                {'part_number': 3, 'etag': '"ccc"'},
                {'part_number': 1, 'etag': '"aaa"'},
                {'part_number': 2, 'etag': '"bbb"'},
            ],
        },
        headers=auth(user_a),
    )
    assert response.status_code == 200, response.text


def test_complete_with_no_parts_is_400(client, user_a):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/complete-multipart',
        json={'key': started['key'], 'upload_id': started['upload_id'], 'parts': []},
        headers=auth(user_a),
    )
    assert response.status_code == 400


def test_complete_on_another_users_video_is_404(client, user_a, user_b):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/complete-multipart',
        json={
            'key': started['key'],
            'upload_id': started['upload_id'],
            'parts': [{'part_number': 1, 'etag': '"a"'}],
        },
        headers=auth(user_b),
    )
    assert response.status_code == 404


# ==================== ABORT ====================

def test_abort_discards_the_upload(client, user_a):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)

    response = client.post(
        f'/api/videos/{video["id"]}/upload/abort-multipart',
        json={'key': started['key'], 'upload_id': started['upload_id']},
        headers=auth(user_a),
    )
    assert response.status_code == 200, response.text
    assert response.json()['aborted'] is True


def test_abort_refuses_a_foreign_key(client, user_a):
    video = register_video(client, user_a)
    started = create_multipart(client, user_a, video)
    response = client.post(
        f'/api/videos/{video["id"]}/upload/abort-multipart',
        json={'key': 'videos/someone-else/1/x.mov', 'upload_id': started['upload_id']},
        headers=auth(user_a),
    )
    assert response.status_code == 400


# ==================== COEXISTENCE ====================

def test_single_shot_upload_url_still_works(client, user_a):
    """The laptop path is untouched: one backend, one UI, two upload strategies."""
    video = register_video(client, user_a)
    presigned = client.post(
        f'/api/videos/{video["id"]}/upload-url',
        json={'content_type': 'video/mp4'},
        headers=auth(user_a),
    )
    assert presigned.status_code == 200, presigned.text
    confirmed = client.post(
        f'/api/videos/{video["id"]}/confirm-upload',
        json={'key': presigned.json()['key']},
        headers=auth(user_a),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['pose_status'] == 'pending'
