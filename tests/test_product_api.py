"""Internal product service. The real response format has not been seen yet (the service is only
reachable on the Ferguson network); these tests cover two plausible shapes and the safety rules."""
import requests

from app import product_api
from app.config import Settings
from app.lookup import ALIASES, LIST_FIELDS, Lookup
from app.models import Evidence


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


def service(monkeypatch, responder, **env):
    monkeypatch.setenv('RFQ_PRODUCT_API', 'true')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    calls = []
    def post(self, url, json=None, timeout=None, verify=None):
        calls.append(json['productIds'])
        return responder(json['productIds'])
    monkeypatch.setattr(requests.Session, 'post', post)
    return product_api.ProductService(), calls


LIST_SHAPE = lambda ids: FakeResponse({'products': [
    {'productId': pid, 'attributes': [{'name': 'Thickness', 'value': '5 mil'},
                                      {'name': 'Material', 'value': 'Aluminum Foil, Plastic'},
                                      {'name': 'Internal Cost Code', 'value': 'X9'}],
     'Color Finish Name': 'Blue'} for pid in ids if pid != '9999999']})


def test_batches_of_100_and_maps_only_known_labels(monkeypatch):
    svc, calls = service(monkeypatch, LIST_SHAPE)
    ids = [str(5000000 + i) for i in range(250)] + ['MTX-4409-XQ']
    svc.prefetch(ids)
    assert [len(c) for c in calls] == [100, 100, 50]           # competitor code never sent
    values, snapshot = svc.fields('5000001', ALIASES, LIST_FIELDS)
    assert values == {'Thickness': '5 mil', 'Material': 'Aluminum Foil|Plastic', 'Color Finish': 'Blue'}
    assert 'Internal Cost Code' in snapshot                     # unknown labels kept for the agent only


def test_response_keyed_by_product_id(monkeypatch):
    svc, _ = service(monkeypatch, lambda ids: FakeResponse({pid: {'Weight': '14.25 lb'} for pid in ids}))
    svc.prefetch(['5106912'])
    assert svc.fields('5106912', ALIASES, LIST_FIELDS)[0] == {'Weight': '14.25 lb'}


def test_outage_disables_service_for_the_run(monkeypatch):
    def down(ids):
        raise requests.ConnectionError('Failed to resolve feidtifaks001.feiaz.ferguson.com')
    svc, calls = service(monkeypatch, down)
    svc.prefetch([str(5000000 + i) for i in range(150)])
    assert len(calls) == 1 and 'ConnectionError' in svc.error
    values, info = svc.fields('5000001', ALIASES, LIST_FIELDS)
    assert values is None and 'unavailable' in info


def test_tls_verified_by_default_and_opt_out(monkeypatch):
    svc, _ = service(monkeypatch, LIST_SHAPE)
    assert isinstance(svc.session.get_adapter('https://x.ferguson.com'), product_api.TrustStoreAdapter)
    svc, _ = service(monkeypatch, LIST_SHAPE, RFQ_PRODUCT_API_VERIFY='false')
    assert not isinstance(svc.session.get_adapter('https://x.ferguson.com'), product_api.TrustStoreAdapter)


def test_priority_service_then_website_then_catalog(monkeypatch):
    service(monkeypatch, lambda ids: FakeResponse({'products': [
        {'productId': '5106912', 'Thickness': '6 mil', 'Lettering': 'From service'}]}))
    lookup = Lookup(Settings(pdfs=False))
    lookup.prefetch(['5106912'])
    monkeypatch.setattr(lookup, 'live', lambda *_: {'Thickness': Evidence('5 mil', 'ferguson_page', 'page'),
                                                    'Width': Evidence('6 in', 'ferguson_page', 'page')})
    result = lookup.lookup('5106912')
    assert result.fields['Thickness'].value == '6 mil'                   # product service wins
    assert any(c.field == 'Thickness' and c.alternative.source_type == 'ferguson_page' for c in result.conflicts)
    assert result.fields['Width'].source_type == 'ferguson_page'         # website fills the gap
    assert result.fields['Lettering'].source_type == 'ferguson_api'
    assert result.fields['ASTM'].source_type == 'catalog'                # catalog only for what is left
    assert 'ferguson_api' in result.snapshots
    lookup.close()


def test_service_alone_finds_product_when_website_is_blocked(monkeypatch):
    service(monkeypatch, LIST_SHAPE)
    lookup = Lookup(Settings(pdfs=False))
    lookup.prefetch(['9677533'])  # not in the backup catalog
    def blocked(*_):
        raise TimeoutError('Access Denied')
    monkeypatch.setattr(lookup, 'live', blocked)
    result = lookup.lookup('9677533')
    assert result.found and result.fields['Thickness'].source_type == 'ferguson_api'
    lookup.close()
