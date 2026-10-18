# Ferguson RFQ Automation Agent: Specification

## Overview

An AI-powered RFQ (Request For Quote) automation system. It reads an incoming RFQ email, extracts the product IDs, gathers product information from ferguson.com, specification PDFs, and a fallback catalog, and fills the RFQ Excel template. It then replies to the sender with the completed `RFQ.xlsx` attached.

The solution runs locally and is deployable on Azure Functions (Flex Consumption).

### Business problem

Today RFQs are processed by hand:

1. User receives the email.
2. User extracts the product IDs.
3. User searches for product information.
4. User opens the specification PDFs.
5. User fills the RFQ Excel.
6. User sends the response email.

This is slow and error-prone. The goal is to automate the whole workflow, with every value traceable to its source.

### End-to-end workflow

```
Incoming RFQ email (Gmail)
  ↓
Extract product IDs (body + Excel attachment)
  ↓
Look up product information on ferguson.com   ← live or background mode
  ↓
Download / read specification PDFs
  ↓
Fall back to the local catalog if needed
  ↓
Populate the RFQ template
  ↓
Generate the Sources sheet
  ↓
Generate the Notes sheet
  ↓
RFQ Quality Agent → Summary sheet
  ↓
Create RFQ.xlsx
  ↓
Generate the reply email
  ↓
Send the reply in the same thread with RFQ.xlsx attached
```

---

## Input

### Email

- One RFQ email as a `.eml` file. In Gmail mode, it comes from the team inbox, with "RFQ" in the subject.
- Limits: 15 MB per email, 200 distinct products.
- Product IDs can appear in:
  - **the email body**: plain text, quoted-printable, or a forwarded thread. IDs can sit inside sentences or have a `#` in front.
  - **an Excel attachment** (`.xlsx`): any sheet, read from the item/product ID column. If no such column is found, every cell is read.

Example:

```
5106912
5106914
5106891
```

### ID requirements

- Preserve the order of first appearance.
- Remove duplicates.
- Never drop an ID.
- Process every ID.
- Competitor and customer codes (for example `17783-79-3000`, `MTX-4409-XQ`) are kept exactly as written.

### Supplied files

| File | Purpose |
|---|---|
| `emails/email-1-ids-in-body.eml` | 6 IDs in the body. Output must match the reference. |
| `emails/email-2-ids-in-attachment.eml` | 8 IDs in the `rfq_items.xlsx` attachment. One has the note "older item, check". |
| `emails/email-3-mixed-ferguson-and-competitor.eml` | Ferguson IDs plus competitor part numbers. |
| `emails/email-4-messy-forward.eml` | Forwarded thread, IDs in sentences, `#` prefixes, one ID repeated, one competitor part. |
| `reference/email-1 reference output.xlsx` | The correct output for email 1. |
| `templates/rfq_template.xlsx` | The RFQ template: RFQ sheet, Sources sheet, "How to fill" sheet. |
| `data/product_catalog.json` | Backup catalog: 56 products, collected 2026-09-24. |
| `data/product_catalog_sources.csv` | Source, source type, and confidence for every catalog value. |
| `data/spec_sheet_links.csv` | Spec sheet PDF links for 39 products. |
| `Global Sourcing Process v14 1 (1).vsdx` | Process reference. RFQ fields covered: function and installation, material, finish, general spec, approval and certification, package, annual quantity and MOQ. |

---

## Steps

### 1. Read the email

- Decode the `.eml` with Python's built-in `email` package, including quoted-printable and base64.
- Collect the body text and every `.xlsx` attachment.

### 2. Extract product IDs

- From the body: 6 to 8 digit numbers, including `#5106926` style, plus hyphenated part numbers that contain a digit.
- From the attachment: the item/product ID column. Numeric cells such as `5106912.0` are read as `5106912`.
- Merge both, in first-seen order, and remove duplicates. Every ID becomes one RFQ row.

### 3. Look up each product (fixed priority order)

Sources are always tried in this order. The order is the same in both scraping modes.

| Priority | Source | Provides | How |
|---|---|---|---|
| 1 (highest) | **Ferguson internal product service** (product-info-v3) | Product specifications from Ferguson's own system | `POST {"productIds": [...]}`, at most 100 IDs per call, batched once per RFQ. Ferguson network only, no authentication. TLS checked against the Windows certificate store. Only labels that name an RFQ field are used; the full record is kept for the review agent. If unreachable (off-network, Azure), the run continues and Notes says so. |
| 2 | **ferguson.com product page** | Price, inventory, specifications, product details, image | Python + Playwright driving Chrome. Reads the page's JSON-LD product data and its specification label/value blocks. |
| 3 | **Specification PDF** | Material, thickness, ASTM standards, OSHA standards, manufacturer specs | Download the PDF, extract the text, and parse the fields. Only explicit single values are used: an exact model match is high confidence; a family sheet for the item's part prefix (for example "Base Sku: SD" for SD6105B52) is medium confidence and flagged for review; option lists ("2, 3, 4 mil") are skipped. |
| 4 (fallback) | **Backup catalog** `data/product_catalog.json` | All template fields, with their recorded source and confidence | Fills only what is still blank after the product service, the website and the PDF, including every field when those lookups fail, are blocked, or time out. |

Precedence (applied field by field):

- **Ferguson's product service wins**, then the website: the website fills fields the service left blank, the PDF fills what both left blank. A lower source never overwrites a higher one; differences are recorded as conflicts.
- **The catalog is the fallback.** It fills a field only when neither the website nor the PDF provided it, and never overwrites them. Every catalog-filled field is listed in Notes, with its original evidence on Sources.
- When the website says it has no page for an item, the catalog is not used to revive it: the row is `Not Found`.
- If no source has the product, the row is marked `Not Found`.
- A lookup failure does not prove a product was removed. The Notes sheet says which sources were tried and why each failed.

### 4. Scraping modes: live and background

Both modes scrape the **same sources in the same order** (ferguson.com, then PDF links, then the fallback catalog) and produce the same workbook. The only difference is whether the audience can see the browser.

| | `live` (demo) | `background` |
|---|---|---|
| Purpose | Show the audience the scraping as it happens | Run the same scraping quietly |
| Browser | Visible Chrome window | Chrome window placed off-screen (not visible) |
| How Chrome is reached | Playwright attaches over CDP to the visible Chrome on port 9333 | The app starts a normal `chrome.exe` on port 9334 with its own profile, attaches over CDP, and stops it at the end |
| What the audience sees | Each product page loads on screen, scrolled to its specification block, which is highlighted, with a short pause per product. The console shows each step: `ferguson.com`, `PDF`, `catalog`. | Console log only |
| Sources and order | ferguson.com → PDF → catalog | ferguson.com → PDF → catalog |

Chrome for live mode is started with:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9333 `
  --user-data-dir="$env:TEMP\chrome-rfq" `
  https://www.ferguson.com/
```

Mode rules:

- Select with `--mode live` or `--mode background`, or with `RFQ_MODE=live|background` in `.env`. The flag wins over the variable. Default: `background`.
- Live mode needs Chrome running on port 9333. If it is not, the run stops with a message telling you how to start it. It never switches mode on its own.
- In either mode, a product page that is blocked, hits a bot check, or times out falls back to the PDF, then the catalog. The reason goes to Notes.
- Why not headless: ferguson.com refuses any Chrome that Playwright launches itself (headless gets `ERR_HTTP2_PROTOCOL_ERROR`, a launched window gets "Access Denied"). A normally started Chrome attached over CDP, as the brief prescribes, is served. No bot-check bypass is implemented.
- Page loads are paced (`RFQ_PAGE_PAUSE`, default 2 s). Rapid repeated runs from one profile can still be rate-limited ("Access Denied"); the fallback above then applies.
- `--demo-delay <seconds>` sets the pause per product in live mode. Default: 2.
- `--no-browser` skips Chrome: ferguson.com over HTTPS (usually refused), then PDF, then catalog. Azure runs this way.
- `--offline` makes no network calls and uses the catalog only. It is for the reference test and repeatable checks.
- The mode used is written to the Notes sheet and the console log.

### 5. Fill the RFQ template

- Copy `templates/rfq_template.xlsx`. Keep its columns and order.
- One row per ID, in input order.
- The `Image` column uses `=IMAGE("<picture url>")`. The `Picture` column holds the URL.
- `Lookup Status` is `Found` or `Not Found`.

### 6. Generate the Sources sheet

- One row for every populated value.
- Columns: `product_id`, `column`, `value`, `source_type`, `confidence`, `source`.

| product_id | column | value | source_type | confidence | source |
|---|---|---|---|---|---|
| 5106912 | Material Type | Polyethylene | spec_sheet | high | Spec sheet PDF URL |
| 5106912 | Length | 1000 ft | ferguson_page | high | Ferguson product page URL, read date |

- Source types: `ferguson_page`, `spec_sheet`, `catalog`, `ferguson_rfq_sample`, `validated_rule`, `sibling_products`, `same_product_description`.

### 7. Generate the Notes sheet

The Notes sheet records:

- missing values,
- source conflicts (for example, website versus PDF), with the value that won,
- warnings, including medium-confidence catalog values flagged for review,
- exceptions such as blocked pages, timeouts, PDF read failures, and Not Found products,
- fallbacks used, and the scraping mode of the run.

### 8. Run the RFQ Quality Agent (Agentic Arm, Option B)

It runs after the RFQ is filled and checks the saved workbook:

- **Validate Excel:** template columns are intact, every ID is present once, and every populated cell has a Sources row.
- **Check missing values:** blank fields per product.
- **Normalize units** when the evidence is explicit. `1000 FT`, `1000 Feet` and `1000 ft` all become `1000 ft`. Widths become `in`, thickness `mil`, weight `lb`. Each change is recorded in Notes.
- **Detect suspicious values:** for example, a length outside common roll sizes, a width that disagrees with the description (`6 in` in the description but `3 in` in the Width column), or a value with no source.
- **Generate the Summary sheet:**

  ```
  Products Processed: 10
  Products Found: 8
  Not Found: 2
  Fields Completed: 92%
  Warnings: 3
  ```

- The agent flags and normalizes. It never invents or overwrites a specification value.

#### B+: deeper review (implemented in `app/agent.py`)

The agent judges **every RFQ value against the source it came from**:

| Verdict | Meaning |
|---|---|
| verified | Stated for this exact product: its ferguson.com page, an exact-model spec sheet, or a catalog record taken from Ferguson's page or sample RFQ |
| inferred | Not stated for this exact product: a family spec sheet, sibling products, or a validated rule |
| conflict | Two sources disagree; the RFQ keeps the higher-priority source |
| issue | A check failed |

Tools, shared by two planners:

| Tool | Purpose |
|---|---|
| `inspect_product` | Values, source types, confidence, conflicts |
| `read_source` | The page excerpt, PDF text, or catalog record with its provenance |
| `compare_family` | Family-invariant fields against sibling products |
| `check_standard` | The APWA utility colour code; ASTM/OSHA/ANSI reference formats |
| `record_finding` | Record a problem, with quoted evidence |
| `propose_fix` | Suggest a corrected value |

- **Rules planner (always on, offline and on Azure):** runs every check on every product. Description vs Length/Width mismatches produce a **critical** finding with a proposed fix taken from the description.
- **AI planner (`--quality ai`):** a model chooses which tools to call, reads sources, records findings and proposes fixes.
- **Evidence gate:** a proposed fix is accepted only if the value already appears in one of the product's sources (text or the same measurement). Anything else is rejected with "never guess".
- **Human approval:** fixes are applied only when a reviewer approves them in the dashboard. Approval writes the value with source type `agent_fix` (citing the evidence and the approval time), regenerates RFQ.xlsx, and keeps `RFQ-original.xlsx`.
- **Outputs:** an **Agent Review** sheet (every finding, its evidence, and any proposal with its decision), agent metrics in Summary, `review-state.json`, and every tool call in `quality-trace.json`, shown as the agent trace in the dashboard.
- **Advisory AI:** a failed or unfinished AI review is labelled as such and never blocks the RFQ or the reply.
- **Verified on 2026-10-16:** email 2, live, gpt-5, 30 AI tool calls. Findings include:
  - ferguson.com lists 1432040 "6 in. x 300 ft." with Length "300 in"; a fix was proposed and approved.
  - Green sewer tape lists a Gas application.
  - 9677531 is purple but its catalog legend says water.
  - The AI's reformatted ASTM list was rejected by the evidence gate.

### 9. Save the outputs

Written to `out/<email name>/`:

| File | Contents |
|---|---|
| `RFQ.xlsx` | Sheets: RFQ, Sources, Notes, Summary |
| `reply.eml` | Reply to the sender with `RFQ.xlsx` attached |
| `summary.json` | The Summary numbers, for logs and the Azure response |
| `quality-trace.json` | Quality Agent checks (and AI tool calls, when used) |

### 10. Send the reply (Gmail mode)

- Reply in the original thread, using `In-Reply-To` and `References`.
- Attach `RFQ.xlsx`.
- Mark the request as read only after the reply is sent.

---

## Run

### Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`.env`, which is never committed:

```env
BOT_EMAIL=xxxxx@gmail.com
BOT_PASSWORD=xxxxxxxxxxxxxxxx
RFQ_MODE=background
```

To get the Gmail App Password: Google Account → Security → 2-Step Verification → App Passwords.

### Build one RFQ

```powershell
# Background mode (default): same scraping, no window
python build.py emails/email-1-ids-in-body.eml --out out

# Live demo mode: start the visible Chrome first (command in Steps, section 4), then:
python build.py emails/email-1-ids-in-body.eml --out out --mode live

# Reference check: no network, catalog only
python build.py emails/email-1-ids-in-body.eml --out out --offline

# Optional AI quality review
python build.py emails/email-3-mixed-ferguson-and-competitor.eml --out out --quality ai
```

### Email bot

```powershell
python mailbot.py                         # background mode, polls every 30 s, Ctrl+C to stop
python mailbot.py --mode live             # live demo mode
python mailbot.py --once                  # check the inbox once and exit
python mailbot.py --once --dry-run        # process but do not send
```

Behavior:

- Poll the inbox every 30 seconds.
- Search unread emails from today with "RFQ" in the subject.
- Process the email, generate `RFQ.xlsx`, and reply in the same thread with it attached.
- Skip automated senders and the bot's own emails.

Expected logs:

```
Watching for RFQ emails
New email found
Running RFQ workflow
Generating RFQ.xlsx
Reply sent
```

### Tests

```powershell
python -m pytest -q
```

### Azure Functions (Flex Consumption)

- `function_app.py` exposes `GET /healthz` and an authenticated `POST /rfq` that takes an `.eml` and returns `RFQ.xlsx`.
- Chrome is not available on Azure. The ferguson.com step is recorded as unavailable, and the run continues with PDF links, then the catalog.
- With the same offline inputs and settings, it returns the same output as a local run.
- Credentials live in Azure application settings, never in code.
- Current deployment: `https://travel-planner-10fcc17e22.azurewebsites.net`, health endpoint `/healthz`.

### Project structure

```
project/
├── app/                 # pipeline modules: email, ids, lookup, pdf, catalog, workbook, quality, reply
├── data/                # backup catalog and spec sheet links
├── emails/              # sample RFQ emails
├── out/                 # generated output (git-ignored)
├── reference/           # reference output for email 1
├── templates/           # RFQ template
├── tests/
├── mailbot.py           # Gmail bot
├── build.py             # CLI: one email → RFQ.xlsx + reply.eml
├── function_app.py      # Azure Functions entry point
├── spec.md
├── README.md
├── requirements.txt
└── .env                 # local only, git-ignored
```

---

## Rules

### Data integrity

- **Blank means unknown. Never guess or invent values.** A blank is better than a made-up value.
- **Never drop a product ID.** Preserve every extracted ID in its first-seen order.
- **Unknown products are `Not Found`:** competitor products, invalid or made-up IDs, and removed products. The row keeps the ID exactly as written and its other fields stay blank.
- **Every populated value has a source** on the Sources sheet.
- **Fixed source priority in every mode:** ferguson.com, then PDF, then catalog. A lower source never overwrites a higher one.
- **The catalog is the fallback.** It fills only fields the website and PDF left blank, or everything when the website fails, is blocked, or times out.
- **Catalog values keep their original confidence and source.** Low-confidence (pattern-based) values are left out. Medium-confidence values are kept and flagged in Notes.
- **Catalog prices and availability are historical** (2026-09-24) and are labelled as such.
- **Mode changes visibility only.** It never changes which sources are used or their order.

### Safety

- External text is never written as an Excel formula. The only formula allowed is the app's own validated `=IMAGE(...)`.
- Credentials stay in `.env` locally or in Azure application settings. They never go into source control or logs.
- If an SMTP send is uncertain, it is held for review and not resent automatically.

---

## Done When

### Testing requirements

- **Email 1:** RFQ cell values and `IMAGE` formulas exactly match `reference/email-1 reference output.xlsx`, compared in `--offline` mode. Extra Summary content and extra Sources and Notes rows are allowed. Byte-for-byte workbook equality is not required.
- **Email 2:** IDs are read from the Excel attachment and every one is processed.
- **Emails 3 and 4:** competitor products, made-up IDs, and removed products show `Not Found`. Nothing is guessed. The duplicate in email 4 appears once.

### Success criteria

- [ ] RFQ email processed automatically
- [ ] Product IDs extracted (body and attachment), in order, with no drops
- [ ] ferguson.com, PDF, and catalog sources used, in that priority
- [ ] Live mode shows the scraping in the visible Chrome; background mode runs it with no window
- [ ] `RFQ.xlsx` generated
- [ ] Sources sheet generated, one row for every populated value
- [ ] Notes sheet generated
- [ ] Unknown products marked `Not Found`
- [ ] Agentic Arm (RFQ Quality Agent) implemented, Summary sheet written
- [ ] Gmail reply sent automatically, in the same thread, with the workbook attached
- [ ] Azure deployment working: `/healthz` and an authenticated `/rfq` request
- [ ] README complete
- [ ] GitHub repository available

The Gmail, AI review, and Azure items need live credentials or a deployment. Mocked tests do not prove them.

### Judging criteria

| Area | Item | Points |
|---|---|---|
| Technical (80) | Core flow works | 25 |
| | Agentic Arm | 25 |
| | Technical quality | 10 |
| | Azure deployment | 10 |
| | README + GitHub | 10 |
| Business (20) | Problem / value | 10 |
| | Presentation / demo | 10 |
| Bonus (10) | Architecture diagram, screenshots, detailed documentation, additional validation, strong error handling | 10 |

---

## Open decisions

1. **Bot file name.** The brief says `mailbox.py`. The starter kit ships `mailbot.py`, and the run command uses `mailbot.py`. Proposal: keep `mailbot.py`.
2. **Build location.** The starter `mailbot.py` calls `rfq/build.py`. Proposal: call the root `build.py` instead.
3. **Summary sheet.** The reference has three sheets. Proposal: add Summary as a fourth sheet and keep the first three matching the reference.
