# Run the RFQ agent

## Local setup

Install `requirements-dev.txt` in a virtual environment, then copy `.env.example` to `.env` if no `.env` exists. The application loads `.env` automatically. Keep credentials out of screenshots and Git.

`python build.py --offline` requires no credentials or network. It creates an Email 1 workbook and reply draft.

## Scraping modes

Both modes read ferguson.com, then the spec sheet PDF, then the backup catalog. Only visibility differs.

**Live (demo):** the audience watches each product page load. Start the visible Chrome first, then run:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1 --user-data-dir="$env:TEMP\chrome-rfq" https://www.ferguson.com/
python build.py emails/email-1-ids-in-body.eml --mode live --demo-delay 2
```

Each page is scrolled to its specification block, which is highlighted, and held for `--demo-delay` seconds. The app opens one tab and closes it at the end; your Chrome stays open. If Chrome is not running on port 9333, the run stops with these instructions.

**Background (default):** `python build.py emails/email-1-ids-in-body.eml --mode background`. The app starts its own Chrome (port 9334, profile `%TEMP%\chrome-rfq-background`) with the window off-screen, and stops it at the end. Set `CHROME_PATH` if Chrome is not in the standard location. If Chrome is missing, the run continues with HTTPS, PDFs and catalog, and Notes says so.

Headless Chrome is not used: ferguson.com refuses any Chrome that Playwright launches itself. Page loads are paced by `RFQ_PAGE_PAUSE` (default 2 s). Many runs in quick succession can still be rate-limited ("Access Denied"); affected products fall back to PDF and catalog, and products missing from the catalog show `Not Found` with a "retry live" note. Before a demo, avoid repeated bulk runs from the same profile.

`--no-browser` skips Chrome entirely (as on Azure).

No automated CAPTCHA solving or access-control bypass is implemented. A blocked or unparseable product page falls back to the catalog and records why.

## Gmail

Use a dedicated team inbox. Enable Google 2-Step Verification and create an App Password if your account supports it. Put the address and App Password in `.env`:

```dotenv
BOT_EMAIL=your-team-inbox@gmail.com
BOT_PASSWORD=your-app-password
```

First preview the result without sending:

```powershell
python mailbot.py --once --dry-run --offline
```

Then start the bot:

```powershell
python mailbot.py
```

It checks unread messages whose subject contains `RFQ` every 30 seconds, including older unread RFQs. It replies to Reply-To or From, retains threading headers, attaches `RFQ.xlsx`, and marks the request read after sending. It skips self-messages, automated senders, and bulk mail.

Optional: set `RFQ_ALLOWED_SENDERS=buyer@example.com,teammate@example.com` to limit accepted sender and reply addresses. This address check is not a substitute for email authentication.

### Delivery failures

The local send journal is in `out/mail/mail-journal/`.

- Failure before SMTP sending: the email remains unread and can retry.
- Confirmed send: the journal prevents a second send even if marking the email read fails.
- Uncertain send or interrupted processing: the journal holds the request for manual review. Check Gmail Sent mail before resetting the entry. Never delete the entire journal to retry one email.

SMTP cannot guarantee exactly-once delivery. This implementation avoids automatic retries when the delivery result is uncertain.

## AI Quality Agent

Choose an available Responses-compatible model and configure:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-id
RFQ_QUALITY=ai
```

The model receives product values, sources, and quality findings, not the raw email or Gmail password. It can call:

1. `inspect_product`: retrieve specifications and evidence.
2. `flag_issue`: append an advisory warning for a product it has inspected.

It cannot browse, send email, or overwrite product data. The review runs after the workbook is generated and validated; its findings are added to Notes and Summary. Tool calls are saved in `quality-trace.json`.

The model may make several tool calls per turn; the number of turns scales with the RFQ (at most 30), and each request has a 120 s timeout (`OPENAI_TIMEOUT`), since reasoning models can be slow. AI mode requires a key and model. The review is advisory: if the API fails or the turn limit is reached, the RFQ and reply are still produced, and Summary labels the review `FAILED` or `INCOMPLETE` rather than presenting it as complete. Verified with `gpt-5` on 2026-10-16: 32 tool calls on Email 3. Use `--quality rules` to run without AI. `--offline` cannot be combined with AI mode because AI calls require network access.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Product marked Not Found | Read Notes; live access may have failed. Retry live before concluding the product is removed. |
| PDF fields blank | The document may be a family sheet or have ambiguous/unlabelled values. Review it manually rather than guessing. |
| Gmail authentication fails | Check the dedicated account's App Password and account policy. |
| No product IDs extracted | Use numeric IDs or hyphenated product codes in the body, or a labelled product ID column in XLSX. |
| Formula/unsupported attachment error | Replace the attachment with an XLSX containing literal product IDs. |
| Catalog price differs from website | The catalog is a 2026-09-24 snapshot. Live values have priority. |
| IMAGE formula displays an error | Use a compatible Excel version or follow the Picture URL column. |

## Implementation references

- [Playwright CDP connection](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)
- [Google Workspace Gmail client settings](https://support.google.com/a/answer/9003945)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
