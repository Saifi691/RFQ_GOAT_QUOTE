import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Tests never write to the real dashboard database in out/rfq.db."""
    monkeypatch.setenv("RFQ_DB", str(tmp_path / "rfq-test.db"))
    monkeypatch.setenv("RFQ_PRODUCT_API", "false")  # tests never call the internal product service
