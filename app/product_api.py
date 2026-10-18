"""Ferguson internal product service (product-info-v3): a batch source of product specifications.

POST {"productIds": [...]} with at most 100 IDs per call; no authentication inside the Ferguson
network. TLS is verified against the operating system's certificate store (which holds Ferguson's
internal CA) via `truststore`; RFQ_PRODUCT_API_VERIFY=false turns verification off explicitly.

The response format is read defensively: each product's record is located by its ID, flattened to
label/value pairs, and only labels that name an RFQ field are used. Everything else stays in the
raw snapshot the review agent can read. Nothing is inferred from unknown fields.
"""
import json
import logging
import os
import re
import ssl
from datetime import date

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

DEFAULT_URL = "https://feidtifaks001.feiaz.ferguson.com/tif-developers-devtrunk/product-info-v3/svc/"
BATCH = 100
ID_KEYS = {"productid", "product_id", "productids", "id", "itemnumber", "itemid", "fergusonid", "productnumber"}
NAME_KEYS = ("name", "attributename", "label", "displayname", "key", "attribute")
VALUE_KEYS = ("value", "attributevalue", "values", "displayvalue", "val")


class TrustStoreAdapter(HTTPAdapter):
    """HTTPS verified against the OS certificate store (Ferguson's internal CA lives there)."""
    def init_poolmanager(self, *args, **kwargs):
        import truststore
        kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return super().init_poolmanager(*args, **kwargs)


def settings():
    return {
        "enabled": os.getenv("RFQ_PRODUCT_API", "true").lower() == "true",
        "url": os.getenv("RFQ_PRODUCT_API_URL", DEFAULT_URL),
        "verify": os.getenv("RFQ_PRODUCT_API_VERIFY", "true").lower() == "true",
        "timeout": float(os.getenv("RFQ_PRODUCT_API_TIMEOUT", "20")),
    }


def norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def scalar(value):
    if isinstance(value, list):
        items = [scalar(v) for v in value]
        return ", ".join(i for i in items if i) if all(not isinstance(v, (dict, list)) for v in value) else None
    if isinstance(value, (dict,)) or value is None:
        return None
    return str(value).strip()


def find_records(data, product_id):
    """Dicts in the response that identify themselves as `product_id`."""
    found = []
    def walk(node):
        if isinstance(node, dict):
            if any(norm(k) in ID_KEYS and str(v).strip() == product_id for k, v in node.items()):
                found.append(node)
                return
            for key, value in node.items():
                if norm(key) == norm(product_id) and isinstance(value, dict):  # keyed by product ID
                    found.append(value)
                    return
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(data)
    return found


def pairs(record):
    """Flatten a product record to (label, value) pairs: plain keys and name/value attribute lists."""
    out = []
    def walk(node, label=None):
        if isinstance(node, dict):
            name = next((node[k] for k in node if norm(k) in NAME_KEYS and isinstance(node[k], str)), None)
            value = next((node[k] for k in node if norm(k) in VALUE_KEYS), None)
            if name is not None and value is not None and scalar(value):
                out.append((name, scalar(value)))
                return
            for key, child in node.items():
                if isinstance(child, (dict, list)) and scalar(child) is None:
                    walk(child, key)
                elif scalar(child):
                    out.append((key, scalar(child)))
        elif isinstance(node, list):
            for item in node:
                walk(item, label)
    walk(record)
    return out


class ProductService:
    def __init__(self, timeout=None):
        self.config = settings()
        if timeout:
            self.config["timeout"] = timeout
        self.session = requests.Session()
        if self.config["verify"]:
            self.session.mount("https://", TrustStoreAdapter())
        self.records = {}      # product_id -> (record dict, raw json text)
        self.error = ""

    def prefetch(self, product_ids):
        """Fetch all numeric IDs in batches of 100. One failure disables the service for the run."""
        ids = [p for p in dict.fromkeys(product_ids) if re.fullmatch(r"\d{5,8}", p)]
        if not self.config["enabled"] or not ids:
            return
        for start in range(0, len(ids), BATCH):
            batch = ids[start:start + BATCH]
            try:
                response = self.session.post(self.config["url"], json={"productIds": batch},
                                             timeout=self.config["timeout"], verify=self.config["verify"])
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                self.error = f"{type(exc).__name__}: {str(exc)[:160]}"
                log.warning("Product service unavailable (%s); continuing with other sources", self.error)
                return
            for product_id in batch:
                records = find_records(data, product_id)
                if records:
                    self.records[product_id] = records[0]
            log.info("[product-service] batch of %d IDs -> %d products", len(batch),
                     sum(1 for p in batch if p in self.records))

    def fields(self, product_id, aliases, list_fields):
        """(Evidence-ready values, snapshot text) for one product, or (None, reason)."""
        record = self.records.get(product_id)
        if record is None:
            return None, (f"Product service unavailable: {self.error}" if self.error
                          else "Product service has no record for this ID" if self.config["enabled"] else "")
        values = {}
        for label, value in pairs(record):
            field = aliases.get(norm(label))
            if field and value and field not in values:
                if field in list_fields:
                    value = "|".join(x.strip() for x in re.split(r",|\|", value) if x.strip())
                values[field] = value
        snapshot = (f"Source: Ferguson product service {self.config['url']} (read {date.today().isoformat()})\n"
                    + json.dumps(record, indent=1, default=str))[:8000]
        return values, snapshot

    def close(self):
        self.session.close()
