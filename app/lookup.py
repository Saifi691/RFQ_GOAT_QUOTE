"""Product lookup in fixed priority: Ferguson product service, ferguson.com page, spec sheet PDF, backup catalog."""
import csv
import json
import logging
import re
from datetime import date
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.browser import Blocked, Browser, BrowserUnavailable, NotOnSite
from app.product_api import ProductService
from app.config import ROOT
from app.models import Evidence, Product
from app.quality import UNIT_FIELDS, normalize

log = logging.getLogger(__name__)
FIELDS = ["Description", "ANSI", "Application", "Color Finish", "Length", "Lettering",
          "Material", "Material Type", "No of Tools", "Temperature Range", "Thickness",
          "Tool Type", "UL Listed", "Width", "OSHA", "Waterworks Application", "Product details",
          "Weight", "ASTM", "Picture URL", "Brand", "Manufacturer Part #", "Ferguson Part #",
          "UPC", "Price (USD)", "Availability", "Ferguson URL", "Spec Sheet URL"]
ALIASES = {re.sub(r"[^a-z0-9]", "", x.lower()): x for x in FIELDS}
ALIASES.update({"colorfinish": "Color Finish", "colorfinishname": "Color Finish",
                "numberoftoolsincluded": "No of Tools", "numberoftools": "No of Tools",
                "productweight": "Weight", "manufacturerpartnumber": "Manufacturer Part #"})
# ferguson.com shows these as "A, B, C"; the template and catalog separate list items with "|".
LIST_FIELDS = {"Application", "Material", "ASTM"}
DOCUMENT_HOSTS = ("ferguson.com", "ferg-img.com", "fergusonprod.a.bigcontent.io")


def allowed_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    # Sources in this kit are hosted by Ferguson. Untrusted email URLs are never fetched.
    return (parsed.scheme == "https" and not parsed.username and parsed.port in (None, 443)
            and any(host == h or host.endswith("." + h) for h in DOCUMENT_HOSTS))


def fetch(session, url, timeout, limit=12 * 1024 * 1024):
    for _ in range(6):
        if not allowed_url(url):
            raise ValueError("Source URL is outside the configured Ferguson hosts")
        with session.get(url, timeout=timeout, stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Source exceeds download size limit")
                chunks.append(chunk)
            return b"".join(chunks), url
    raise ValueError("Too many source redirects")


def json_products(value):
    if isinstance(value, list):
        for item in value:
            yield from json_products(item)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        if kind == "Product" or isinstance(kind, list) and "Product" in kind:
            yield value
        if "@graph" in value:
            yield from json_products(value["@graph"])


def parse_product(html, url, product_id):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if any(s in text.lower() for s in ("access denied", "verify you are human", "pardon our interruption")):
        raise Blocked("Ferguson blocked automated access")
    candidates = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            candidates.extend(json_products(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
    product = None
    for candidate in candidates:
        identities = [str(candidate.get(k, "")) for k in ("productID", "sku", "url", "@id")]
        if any(re.search(rf"(?<!\d){re.escape(product_id)}(?!\d)", value) for value in identities):
            product = candidate
            break
    # Some pages identify the numeric Ferguson item outside the JSON-LD.
    if product is None and len(candidates) == 1:
        if re.search(rf"\bItem\s*(?:#|No\.?|Number)?\s*{re.escape(product_id)}\b", text, re.I):
            product = candidates[0]
    # Pages without product JSON-LD: the visible "Item #<id>" on the item's own URL is the identity.
    if (product is None and urlparse(url).path.endswith(f"/{product_id}.html")
            and re.search(rf"\bItem\s*#\s*{re.escape(product_id)}\b", text)):
        heading = soup.find("h1")
        image = soup.select_one('meta[property="og:image"]')
        product = {"name": heading.get_text(" ", strip=True) if heading else None,
                   "image": image.get("content") if image else None}
    if product is None:
        raise ValueError("No exact product identity found on the live page")

    values = {"Description": product.get("name"), "Manufacturer Part #": product.get("mpn"),
              "UPC": product.get("gtin12"), "Ferguson URL": url}
    brand = product.get("brand")
    values["Brand"] = brand.get("name") if isinstance(brand, dict) else brand
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    values["Picture URL"] = image
    details = product.get("description")
    if isinstance(details, list):
        details = "|".join(page_text(x) for x in details if page_text(x))
    values["Product details"] = details
    offers = product.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if len(offers) == 1 else {}
    if isinstance(offers, dict):
        if offers.get("priceCurrency") == "USD":
            values["Price (USD)"] = offers.get("price")
        values["Availability"] = str(offers.get("availability", "")).rsplit("/", 1)[-1]

    def add(label, value):
        field = ALIASES.get(re.sub(r"[^a-z0-9]", "", str(label).lower()))
        if field and value is not None and not isinstance(value, (dict, list)) and str(value).strip():
            value = " ".join(str(value).split())
            if field in LIST_FIELDS:
                value = "|".join(x.strip() for x in value.split(",") if x.strip())
            values[field] = value

    properties = product.get("additionalProperty", [])
    if isinstance(properties, dict):
        properties = [properties]
    for prop in properties:
        if isinstance(prop, dict):
            add(prop.get("name", ""), prop.get("value"))
    # ferguson.com specification block: label/value pairs of divs.
    for pair in soup.select(".c-product-details__specs__specsAttributes"):
        cells = pair.find_all("div", recursive=False)
        if len(cells) == 2:
            add(cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            add(cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))
    for term in soup.select("dt"):
        definition = term.find_next_sibling("dd")
        if definition:
            add(term.get_text(" ", strip=True), definition.get_text(" ", strip=True))
    lines = soup.get_text("\n", strip=True)
    for label, field in (("Manufacturer Part #", "Manufacturer Part #"), ("Part #", "Ferguson Part #")):
        match = re.search(rf"(?<![A-Za-z ]){re.escape(label)}\s*([A-Z0-9][A-Z0-9-]+)", lines)
        if match and not values.get(field):
            values[field] = match.group(1)
    for link in soup.select("a[href]"):
        href = urljoin(url, link["href"])
        label = link.get_text(" ", strip=True).lower()
        if (label in ("specification", "specifications", "spec sheet", "specification sheet")
                or "specification" in href.lower()) and allowed_url(href):
            values["Spec Sheet URL"] = href
            break
    source = f"{url} (ferguson.com product page, read {date.today().isoformat()})"
    return {name: Evidence(page_text(value), "ferguson_page", source)
            for name, value in values.items() if value is not None and page_text(value)}


LINK_FIELDS = {"Ferguson URL", "Spec Sheet URL"}  # the same document is served from several addresses


def page_excerpt(html, url):
    """The parts of a product page the RFQ values come from, as plain text for the review agent."""
    soup = BeautifulSoup(html, "html.parser")
    lines = [f"Source: {url}"]
    heading = soup.find("h1")
    if heading:
        lines.append(f"Title: {heading.get_text(' ', strip=True)}")
    text = soup.get_text("\n", strip=True)
    lines += [m.group(0) for m in re.finditer(r"(?:Manufacturer Part|Part|Item) #\s*[A-Z0-9-]+", text)][:3]
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for product in json_products(json.loads(script.get_text())):
                details = product.get("description")
                if isinstance(details, list):
                    lines += ["Product details: " + page_text(x) for x in details]
        except (ValueError, TypeError):
            continue
    for pair in soup.select(".c-product-details__specs__specsAttributes"):
        cells = pair.find_all("div", recursive=False)
        if len(cells) == 2:
            lines.append(f"{cells[0].get_text(' ', strip=True)}: {cells[1].get_text(' ', strip=True)}")
    return "\n".join(lines)[:6000]


def catalog_excerpt(product_id, record, sources):
    lines = [f"Source: data/product_catalog.json#{product_id} (snapshot 2026-09-24)"]
    for name, value in record.items():
        if value:
            origin = sources.get((product_id, name))
            where = f"  [{origin['source_type']}, {origin['confidence']}: {origin['source'][:160]}]" if origin else ""
            lines.append(f"{name}: {value}{where}")
    return "\n".join(lines)[:8000]


def same_value(field, a, b):
    """Equal after unit, number, list and whitespace formatting, so only real conflicts are noted."""
    if field in LINK_FIELDS:
        return True
    def canon(value):
        if field in UNIT_FIELDS:
            value = normalize(value, field, "catalog")
        try:
            return str(float(value))
        except ValueError:
            return re.sub(r"\s*[|,;]\s*", "|", " ".join(value.split())).lower()
    return canon(a) == canon(b)


def page_text(value):
    """ferguson.com product data writes apostrophes as <CQUOTA/>; drop any other markup."""
    value = str(value).replace("<CQUOTA/>", "'")
    return " ".join(re.sub(r"<[^>]{1,40}>", "", value).split())


PDF_LABELS = {"overallthickness": "Thickness", "thickness": "Thickness",
              "material": "Material Type", "materialtype": "Material Type",
              "standardlength": "Length", "length": "Length", "rolllength": "Length",
              "standardwidth": "Width", "width": "Width", "rollwidth": "Width", "weight": "Weight"}
POLYMERS = ("Polyethylene", "Polypropylene", "Polyester", "PVC", "Vinyl", "Nylon")
UNIT_MARKS = {"’": " ft", "'": " ft", "”": " in", '"': " in"}


def labelled_values(text):
    """Collect "Label: value" pairs; the value may sit on the next line."""
    lines = [line.strip() for line in text.splitlines()]
    pairs = {}
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Za-z][A-Za-z ()]{1,40}?)\s*:\s*(.*)$", line)
        if not match:
            continue
        label = re.sub(r"[^a-z]", "", match.group(1).lower().replace("(s)", ""))
        value = match.group(2).strip() or next((x for x in lines[index + 1:index + 3] if x), "")
        pairs.setdefault(label, []).append(value)
    return pairs


def clean_pdf_value(field, value):
    """One explicit value, or None when the sheet lists options (2, 3, 4 mil ...)."""
    value = re.sub(r"(?<=\d),(?=\d{3}\b)", "", value).strip()
    if len(set(re.findall(r"\d+(?:\.\d+)?", value))) > 1 or re.search(r"[|]|\bor\b|&", value):
        return None
    if field == "Material Type":
        found = [p for p in POLYMERS if re.search(rf"\b{p}\b", value, re.I)]
        return found[0] if len(found) == 1 else None
    if not re.search(r"\d", value):
        return None
    for mark, unit in UNIT_MARKS.items():
        value = re.sub(rf"(\d)\s*{mark}", rf"\1{unit}", value)
    return " ".join(value.split())


def parse_pdf_text(text, product_id, manufacturer_part, url):
    """Read explicit single values from the spec sheet Ferguson links to this item.

    An exact item/model match gives high confidence. A family sheet (for example "Base Sku: SD"
    for part SD6105B52) gives medium confidence and a review note. A family sheet for another
    part prefix, option lists, and repeated conflicting labels are not used.
    """
    identities = [product_id] + ([manufacturer_part] if manufacturer_part else [])
    exact = any(re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text, re.I)
                for value in identities)
    base = re.search(r"Base\s*Sku\s*:?\s*([A-Z0-9]+)", text, re.I)
    if not exact and base and not (manufacturer_part or "").upper().startswith(base.group(1).upper()):
        return {}, f"Spec sheet covers part family {base.group(1)}, not {manufacturer_part}; not used."
    confidence = "high" if exact else "medium"
    source = url + (" (spec sheet, exact model match)" if exact
                    else " (family spec sheet linked by Ferguson for this item; verify)")
    values = {}
    for label, found in labelled_values(text).items():
        field = PDF_LABELS.get(label)
        if not field:
            continue
        cleaned = {clean_pdf_value(field, value) for value in found}
        if len(cleaned) == 1 and None not in cleaned:
            values[field] = cleaned.pop()
    standards = {
        "ASTM": ("|", [f"ASTM {a}-{b}" for a, b in re.findall(r"\bASTM\s*([A-Z])\s*-?\s*(\d{2,5})\b", text)]),
        "OSHA": (";", [f"OSHA {x}" for x in re.findall(
            r"OSHA\)?\s*:?\s*(?:Regulation\s*)?(\d{4}[-.]\d+(?:\([a-z0-9]+\))*)", text)]),
        "ANSI": ("|", [f"ANSI {x}" for x in re.findall(r"\bANSI\s+([A-Z]\d+(?:\.\d+)*)", text)]),
    }
    for field, (separator, found) in standards.items():
        if found:
            values[field] = separator.join(dict.fromkeys(found))
    evidence = {name: Evidence(value, "spec_sheet", source, confidence) for name, value in values.items()}
    if not evidence:
        return {}, "Spec sheet read; no explicit single-value specifications found."
    note = "" if exact else ("Review spec sheet values (" + ", ".join(evidence) +
                             "): taken from a family spec sheet, medium confidence.")
    return evidence, note


class Lookup:
    def __init__(self, settings):
        self.settings = settings
        self.catalog = json.loads((ROOT / "data/product_catalog.json").read_text(encoding="utf-8-sig"))
        with (ROOT / "data/product_catalog_sources.csv").open(encoding="utf-8-sig", newline="") as file:
            self.sources = {(r["product_id"], r["column"]): r for r in csv.DictReader(file)}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "FergusonRFQ/1.0"
        self.browser = None
        self.browser_error = ""
        self.last_snapshot = ""
        self.pdf_cache = {}
        self.service = None if settings.offline else ProductService()

    def prefetch(self, product_ids):
        """Ask the internal product service for every ID up front, in batches of 100."""
        if self.service:
            self.service.prefetch(product_ids)

    def open(self):
        """Start Chrome for the selected mode. Live mode raises if the visible Chrome is missing."""
        if self.settings.offline or not self.settings.browser:
            return
        browser = Browser(self.settings)
        try:
            browser.start()
            self.browser = browser
        except BrowserUnavailable as exc:
            if self.settings.mode == "live":
                raise
            self.browser_error = str(exc)
            log.warning("[background] %s; ferguson.com will be tried over HTTPS", exc)

    def close(self):
        self.session.close()
        if self.service:
            self.service.close()
        if self.browser:
            self.browser.close()

    def live(self, product_id, url):
        if self.browser:
            html, final_url = self.browser.product_page(url, product_id)
            if not allowed_url(final_url):
                raise ValueError("Unexpected product redirect")
        else:
            html, final_url = fetch(self.session, url, self.settings.timeout)
        fields = parse_product(html, final_url, product_id)
        self.last_snapshot = page_excerpt(html, final_url)
        return fields

    def read_pdf(self, pdf_url):
        if pdf_url not in self.pdf_cache:
            data, final_url = fetch(self.session, pdf_url, self.settings.timeout)
            if not data.startswith(b"%PDF"):
                raise ValueError("Specification endpoint did not return a PDF")
            reader = PdfReader(BytesIO(data))
            if len(reader.pages) > 50:
                raise ValueError("Specification PDF exceeds 50 pages")
            self.pdf_cache[pdf_url] = ("\n".join(page.extract_text() or "" for page in reader.pages), final_url)
        return self.pdf_cache[pdf_url]

    def lookup(self, product_id):
        result = Product(product_id)
        tag = f"[{self.settings.mode}]" if self.browser else "[lookup]"
        if not re.fullmatch(r"\d{5,8}", product_id):
            result.notes.append("Not Found: competitor/customer code, not a Ferguson item number; "
                                "competitor search is outside the Quality Agent option.")
            log.info("%s %s: competitor/customer code -> Not Found", tag, product_id)
            return result
        catalog = self.catalog.get(product_id, {})
        url = catalog.get("Ferguson URL") or f"https://www.ferguson.com/product/{product_id}.html"
        live_ok = not_on_site = service_ok = False

        # 1. Ferguson internal product service: Ferguson's own product data, highest priority
        if self.service:
            values, info = self.service.fields(product_id, ALIASES, LIST_FIELDS)
            if values is not None:
                source = (f"Ferguson product service {self.service.config['url']} "
                          f"(product-info-v3, read {date.today().isoformat()})")
                result.merge({k: Evidence(v, "ferguson_api", source) for k, v in values.items()})
                result.snapshots["ferguson_api"] = info
                result.found = service_ok = True
                log.info("%s %s: product service -> %d fields", tag, product_id, len(values))
            elif info and not self.service.error:  # an outage is noted once for the run, not per product
                result.notes.append(info)

        # 2. ferguson.com product page: fills what the product service did not provide
        if self.settings.offline:
            result.notes.append("Offline mode: live website and PDF downloads were not attempted.")
        else:
            try:
                self.last_snapshot = ""
                fields = self.live(product_id, url)
                result.merge(fields)
                result.found = live_ok = True
                if self.last_snapshot:
                    result.snapshots["ferguson_page"] = self.last_snapshot
                log.info("%s %s: ferguson.com -> %d fields", tag, product_id, len(fields))
            except NotOnSite as exc:
                not_on_site = True
                result.notes.append(f"ferguson.com: {exc} (checked {date.today().isoformat()}).")
                log.info("%s %s: ferguson.com -> no product page", tag, product_id)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                if not self.browser and self.browser_error:
                    reason += f" (browser unavailable: {self.browser_error[:120]})"
                result.notes.append(f"ferguson.com lookup failed: {reason}")
                log.info("%s %s: ferguson.com failed (%s)", tag, product_id, type(exc).__name__)

        # A product Ferguson's own service knows exists even if the public site has no page for it.
        listed = service_ok or not not_on_site

        # 3. Specification PDF
        pdf_url = result.fields.get("Spec Sheet URL")
        pdf_url = pdf_url.value if pdf_url else catalog.get("Spec Sheet URL")
        if pdf_url and self.settings.pdfs and not self.settings.offline and listed:
            try:
                text, final_url = self.read_pdf(pdf_url)
                part = result.fields.get("Manufacturer Part #")
                fields, note = parse_pdf_text(text, product_id,
                    part.value if part else catalog.get("Manufacturer Part #"), final_url)
                result.merge(fields)
                result.snapshots["spec_sheet"] = f"Source: {final_url}\n{text}"[:8000]
                if note:
                    result.notes.append(note)
                result.notes.append(f"Specification PDF read: {final_url}")
                log.info("%s %s: PDF -> %d fields", tag, product_id, len(fields))
            except Exception as exc:
                result.notes.append(f"PDF unavailable: {type(exc).__name__}: {str(exc)[:160]}")
                log.info("%s %s: PDF failed (%s)", tag, product_id, type(exc).__name__)

        # 4. Backup catalog, last in priority: fills only fields the higher sources left blank,
        # never overrides them, and never revives a product neither the service nor the website lists.
        if listed and catalog:
            result.snapshots["catalog"] = catalog_excerpt(product_id, catalog, self.sources)
            fallback = {}
            for name in FIELDS:
                value = catalog.get(name)
                if not value:
                    continue
                source = self.sources.get((product_id, name), {})
                confidence = source.get("confidence", "high")
                provenance = f"data/product_catalog.json#{product_id}/{name}; snapshot 2026-09-24"
                if source:
                    provenance += f"; original {source['source_type']}: {source['source']}"
                if name in result.fields:
                    kept = result.fields[name]
                    if not same_value(name, kept.value, str(value)):
                        result.add_conflict(name, kept, Evidence(str(value), "catalog", provenance, confidence))
                    continue
                if confidence == "low":
                    result.notes.append(f"Omitted {name}: catalog evidence is low confidence (pattern-based).")
                    continue
                fallback[name] = Evidence(str(value), "catalog", provenance, confidence)
                if confidence == "medium":
                    result.notes.append(f"Review {name}: supplied catalog evidence is medium confidence.")
            result.merge(fallback)
            if fallback:
                result.found = True
                why = ("no higher-priority source (product service, ferguson.com, PDF) showed them"
                       if live_ok or service_ok
                       else "the ferguson.com lookup did not succeed")
                result.notes.append(f"Backup catalog (2026-09-24 snapshot) filled {', '.join(fallback)} "
                                    f"because {why}.")
                if {"Price (USD)", "Availability"} & set(fallback):
                    result.notes.append("Catalog price and availability are historical, not live; confirm before quoting.")
            log.info("%s %s: catalog -> %d more fields", tag, product_id, len(fallback))
        if not result.found:
            result.fields.clear()
            if not not_on_site:
                result.notes.append("Not Found in available sources. If live lookup failed, absence is not confirmed; retry live.")
            log.info("%s %s: Not Found", tag, product_id)
        return result
