import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app import simulate


@pytest.fixture
def smtp(monkeypatch):
    sent = []

    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, user, password): sent.append(('login', user))
        def send_message(self, message): sent.append(('send', message))

    monkeypatch.setattr(simulate.smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setenv('BOT_EMAIL', 'bot@example.com')
    monkeypatch.setenv('SIM_SENDER_EMAIL', 'buyer@example.com')
    monkeypatch.setenv('SIM_SENDER_PASSWORD', 'abcd efgh ijkl mnop')
    monkeypatch.delenv('RFQ_ALLOWED_SENDERS', raising=False)
    simulate._sent_times.clear()
    return sent


def test_sends_only_to_the_bot_with_optional_sample_attachment(smtp):
    result = simulate.send('RFQ: test', '5106912\n5106935', attach=True)
    message = smtp[-1][1]
    assert message['To'] == 'bot@example.com' and message['From'] == 'buyer@example.com'
    assert result['message_id'] == message['Message-ID']
    assert [a.get_filename() for a in message.iter_attachments()] == ['rfq_items.xlsx']
    assert smtp[0] == ('login', 'buyer@example.com')


def test_rate_limit_and_validation(smtp):
    simulate.send('RFQ one', '5106912')
    with pytest.raises(simulate.SimulationError, match='Wait'):
        simulate.send('RFQ two', '5106912')
    simulate._sent_times.clear()
    with pytest.raises(simulate.SimulationError, match='Subject'):
        simulate.send('   ', '5106912')
    with pytest.raises(simulate.SimulationError, match='product IDs'):
        simulate.send('RFQ', '', attach=False)


def test_setup_problems_are_reported(smtp, monkeypatch):
    monkeypatch.setenv('SIM_SENDER_EMAIL', 'BOT@example.com')
    config = simulate.config()
    assert not config['enabled'] and 'must differ' in config['problems'][0]
    assert len(config['presets']) == 4 and config['presets'][1]['attach'] is True
    with pytest.raises(simulate.SimulationError):
        simulate.send('RFQ', '5106912')
    assert smtp == []


@pytest.fixture
def server():
    from app.dashboard_api import Handler
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()
    httpd.server_close()


def post(url, payload, headers):
    request = Request(url, data=json.dumps(payload).encode(), method='POST', headers=headers)
    return urlopen(request)


def test_api_sends_from_dashboard_but_blocks_other_sites(smtp, server):
    body = {'subject': 'RFQ api', 'body': '5106912'}
    ok = post(f'{server}/api/simulate', body,
              {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8000'})
    assert ok.status == 201 and json.load(ok)['to'] == 'bot@example.com'
    for headers in ({'Content-Type': 'application/json', 'Origin': 'https://evil.example'},
                    {'Content-Type': 'text/plain', 'Origin': 'http://127.0.0.1:8000'}):
        with pytest.raises(HTTPError) as blocked:
            post(f'{server}/api/simulate', body, headers)
        assert blocked.value.code == 403
    assert sum(1 for kind, _ in smtp if kind == 'send') == 1
