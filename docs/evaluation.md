# Evaluation checklist

| Area | Points | Evidence to show |
| --- | --- | --- |
| Core flow | 25 | Four sample emails, generated workbooks, correct IDs, sources, unknown rows, threaded reply |
| Agentic arm | 25 | AI Quality Agent inspecting products and flagging issues; `quality-trace.json` and Summary |
| Technical quality | 10 | Automated tests, explicit fallback, confidence notes, safe spreadsheet handling, send journal |
| Azure deployment | 10 | Deployed `/healthz`, authenticated `/rfq`, matching offline output |
| README and GitHub | 10 | Setup guide, spec, deployment guide, code committed to the project repository |
| Business value | 10 | Reduced manual lookup, spreadsheet entry, and response preparation; do not claim unmeasured savings |
| Presentation/demo | 10 | Walk through email input, workbook output, sources, exceptions, and reply |
| Bonus | Up to 10 | Architecture diagram, documentation, validation, error handling, screenshots captured during the real demo |

## Suggested demo

1. Run Email 1 offline and compare the RFQ sheet against the reference.
2. Run Email 2 to demonstrate attachment extraction.
3. Run Emails 3 and 4 to demonstrate unknown codes and deduplication.
4. Show Sources, Notes, and Summary, including historical catalog warnings.
5. Run with `--quality ai` and show actual tool calls. Rules-only mode is not evidence of an AI agent run.
6. Send an RFQ to the configured Gmail inbox and show the threaded response.
7. Show the deployed Azure health check and workbook response.

Live Gmail, AI, and Azure steps require configured credentials. Tests using fakes verify code behavior, not real service access.
