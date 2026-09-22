"""
Worker hand-off: the enqueue call the backend makes to the Modal endpoint.

httpx is stubbed at the transport level, so these run with no network and
assert the exact wire contract the worker's `enqueue` endpoint checks:
X-Webhook-Secret header, JSON body {video_id, user_id, r2_key}.
"""
import json

import httpx
import pytest

from src.labeling import pose_queue


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('MODAL_ENDPOINT_URL', 'https://example--dynalytix-pose-enqueue.modal.run')
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', 's3cret')


def _stub_post(monkeypatch, handler):
    """Route httpx.post through a MockTransport handler."""
    def fake_post(url, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.post(url, **kwargs)
    monkeypatch.setattr(pose_queue.httpx, 'post', fake_post)


def test_not_configured_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv('MODAL_ENDPOINT_URL', raising=False)
    monkeypatch.delenv('MODAL_WEBHOOK_SECRET', raising=False)
    assert pose_queue.is_configured() is False
    with pytest.raises(pose_queue.PoseQueueNotConfigured, match='worker not configured'):
        pose_queue.enqueue_pose_job(1, 'u', 'videos/u/1/a.mp4')


def test_blank_secret_counts_as_not_configured(monkeypatch):
    monkeypatch.setenv('MODAL_ENDPOINT_URL', 'https://x.modal.run')
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', '   ')
    assert pose_queue.is_configured() is False


def test_enqueue_sends_secret_header_and_json_body(configured, monkeypatch):
    seen = {}

    def handler(request):
        seen['url'] = str(request.url)
        seen['headers'] = request.headers
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json={'accepted': True, 'call_id': 'fc-1'})

    _stub_post(monkeypatch, handler)
    result = pose_queue.enqueue_pose_job(12, 'user-uuid', 'videos/user-uuid/12/clip.mov')

    assert result == {'accepted': True, 'call_id': 'fc-1'}
    assert seen['url'] == 'https://example--dynalytix-pose-enqueue.modal.run'
    assert seen['headers']['x-webhook-secret'] == 's3cret'
    assert 'authorization' not in seen['headers']
    assert seen['body'] == {'video_id': 12, 'user_id': 'user-uuid', 'r2_key': 'videos/user-uuid/12/clip.mov'}


def test_non_2xx_is_a_queue_error_with_the_status(configured, monkeypatch):
    _stub_post(monkeypatch, lambda request: httpx.Response(401, json={'detail': 'bad secret'}))
    with pytest.raises(pose_queue.PoseQueueError, match=r'rejected the job \(401\)'):
        pose_queue.enqueue_pose_job(1, 'u', 'videos/u/1/a.mp4')


def test_transport_failure_is_a_queue_error(configured, monkeypatch):
    def handler(request):
        raise httpx.ConnectError('boom', request=request)

    _stub_post(monkeypatch, handler)
    with pytest.raises(pose_queue.PoseQueueError, match='worker unreachable: ConnectError'):
        pose_queue.enqueue_pose_job(1, 'u', 'videos/u/1/a.mp4')


def test_non_json_2xx_is_accepted(configured, monkeypatch):
    _stub_post(monkeypatch, lambda request: httpx.Response(202, text='ok'))
    assert pose_queue.enqueue_pose_job(1, 'u', 'videos/u/1/a.mp4') == {'accepted': True}
