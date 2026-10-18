import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from app import store
from app.config import ROOT, Settings
from app.pipeline import build


def sample(number):
    return next((ROOT / 'emails').glob(f'email-{number}-*.eml')).read_bytes()


def message(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


def record(number, tmp_path, monkeypatch, sent=True):
    # Workbooks must live under out/ to be downloadable; point ROOT/out checks at tmp.
    raw = sample(number)
    request_id = store.start('gmail', message(raw), Settings(offline=True))
    result = build(raw, tmp_path / f'email-{number}', Settings(offline=True))
    store.built(request_id, result)
    if sent:
        store.replied(request_id, '<reply@example.com>')
    return request_id


def test_lifecycle_and_metrics(tmp_path, monkeypatch):
    first = record(1, tmp_path, monkeypatch)
    record(3, tmp_path, monkeypatch, sent=False)
    store.skipped('gmail', message(sample(2)), 'automated sender')
    failed = store.start('gmail', message(sample(4)), Settings(offline=True))
    store.failed(failed, 'TimeoutError: SMTP')

    totals = store.metrics(days=3650)['totals']
    assert totals['received'] == 4
    assert totals['replied'] == 1
    assert totals['skipped'] == 1 and totals['failed'] == 1
    assert totals['products'] == 6 + 7
    assert totals['not_found'] == 3

    detail = store.request_detail(first)
    assert [p['product_id'] for p in detail['products']][:2] == ['5106912', '5106935']
    assert all(p['status'] == 'Found' and p['from_catalog'] > 0 for p in detail['products'])
    assert detail['reply_message_id'] == '<reply@example.com>'
    assert 'workbook_path' not in detail

    sources = store.metrics(days=3650)['sources']
    assert sources['catalog'] > 0 and sources['website'] == 0  # offline: catalog only

    # A retry of the failed email reuses its row instead of adding one per poll.
    assert store.start('gmail', message(sample(4)), Settings(offline=True)) == failed
    assert store.metrics(days=3650)['totals']['received'] == 4


def test_workbook_download_only_inside_out_folder(tmp_path, monkeypatch):
    outside = record(1, tmp_path, monkeypatch)
    assert store.workbook_for(outside) is None  # tmp_path is not the project's out/ folder
    monkeypatch.setattr(store, 'ROOT', tmp_path)  # now tmp_path/out is "the project's out/"
    inside = record(1, tmp_path / 'out', monkeypatch)
    assert store.workbook_for(inside).name == 'RFQ.xlsx'
    assert store.workbook_for(outside) is None
    # The drawer's download button depends on this flag.
    assert store.request_detail(inside)['has_workbook'] == 1
    assert store.request_detail(outside)['has_workbook'] == 0
    assert store.request_detail(inside)['response_s'] is not None


def test_recording_failure_never_breaks_the_rfq(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_DB', str(tmp_path))  # a directory: sqlite cannot open it
    assert store.start('gmail', message(sample(1)), Settings(offline=True)) is None
    monkeypatch.setenv('RFQ_DB', 'off')
    assert store.start('gmail', message(sample(1)), Settings(offline=True)) is None


@pytest.fixture
def server():
    from app.dashboard_api import Handler
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()
    httpd.server_close()


def test_api_endpoints(tmp_path, monkeypatch, server):
    request_id = record(1, tmp_path, monkeypatch)
    metrics = json.load(urlopen(f'{server}/api/metrics?days=7'))
    assert metrics['totals']['replied'] == 1 and len(metrics['daily']) == 7
    rows = json.load(urlopen(f'{server}/api/requests?source=gmail'))
    assert rows[0]['id'] == request_id and rows[0]['status'] == 'replied'
    detail = json.load(urlopen(f'{server}/api/requests/{request_id}'))
    assert len(detail['products']) == 6
    with pytest.raises(HTTPError) as bad:
        urlopen(f'{server}/api/requests?source=evil')
    assert bad.value.code == 400
    with pytest.raises(HTTPError) as missing:
        urlopen(f'{server}/api/requests/{request_id}/rfq.xlsx')  # workbook outside out/
    assert missing.value.code == 404
