# Azure deployment

The app uses the Azure Functions Python v2 model. Local execution and Azure use `app/pipeline.py`.

## Automated deployment

From the project root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

The script packages only the function code, runtime dependencies, product catalog, and RFQ workbook template. It can install Azure CLI into the ignored `.tools/` folder, signs in with a device code when needed, creates a uniquely named Flex Consumption app in `centralindia`, deploys with Azure's remote Python build, then checks `/healthz` and posts the sample email to `/rfq?offline=true`. The latter check validates that Azure returned a workbook with the expected sheets.

Deployment names and the selected subscription are saved under the ignored `.azure/deployment.json` file so later runs reuse the same resources. Keep this file for redeployment. The script defaults to the subscription used by this deployment and `centralindia`; override them with `-SubscriptionId <id>` or `-Location <region>`. These commands create Azure resources and may incur charges.

## Current deployment

Live app: <https://ferg-rfq-43d40eca.azurewebsites.net>

The deployment run verified that `/healthz` returned `status: ok` and that an authenticated offline `POST /rfq?offline=true` returned an RFQ workbook with the expected sheets. The `/rfq` endpoint requires a Function key.

To only check an existing deployment, without packaging, changing settings, or uploading code:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1 -VerifyOnly
```

The deployment keeps the Gmail timer disabled and the rules quality mode as the default. It sets `RFQ_BROWSER=false` and `RFQ_DB=off` because Azure has no Chrome browser or local dashboard database. Optional Gmail and AI settings can be configured separately in Function App settings.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /healthz` | Public health check |
| `POST /rfq` | Function-key protected; accepts raw `.eml` bytes and returns `RFQ.xlsx` |
| `POST /rfq?offline=true` | Reproducible catalog-only output, useful for comparison |
| Gmail timer | Checks every 30 seconds when `RFQ_MAIL_ENABLED=true` |

The HTTP endpoint creates a workbook; the Gmail timer sends replies. Azure does not require Chrome or Playwright.

## Prerequisites

- An Azure subscription and a chosen resource group, region, storage account, and Function App name.
- Azure CLI and Azure Functions Core Tools v4 installed and authenticated.
- Python 3.11 for the deployment environment.
- Use a separate RFQ app unless replacing another application's deployed code is intentional.

## Create a Flex Consumption app

Replace the example names before running. These commands create billable Azure resources.

```powershell
az login
az group create --name rfq-demo-rg --location eastus
az storage account create --name YOURUNIQUESTORAGE --resource-group rfq-demo-rg --location eastus --sku Standard_LRS
az functionapp create --resource-group rfq-demo-rg --name YOURUNIQUEAPP --storage-account YOURUNIQUESTORAGE --flexconsumption-location eastus --runtime python --runtime-version 3.11
az functionapp config appsettings set --resource-group rfq-demo-rg --name YOURUNIQUEAPP --settings RFQ_BROWSER=false RFQ_QUALITY=rules RFQ_MAIL_ENABLED=false
func azure functionapp publish YOURUNIQUEAPP --python
```

Verify that Flex Consumption is available in the selected region. For an existing app, verify its runtime/plan and skip resource creation.

## Verify

```powershell
Invoke-RestMethod https://YOURUNIQUEAPP.azurewebsites.net/healthz
Invoke-WebRequest -Uri 'https://YOURUNIQUEAPP.azurewebsites.net/rfq?offline=true' -Method Post -Headers @{ 'x-functions-key' = $env:RFQ_FUNCTION_KEY } -ContentType 'message/rfc822' -InFile emails/email-1-ids-in-body.eml -OutFile out/Azure-RFQ.xlsx
```

Set `RFQ_FUNCTION_KEY` privately in your shell; never put it in a committed script or URL.

## Enable Gmail and AI

Use Azure application settings or Key Vault references for secrets:

- `BOT_EMAIL` and `BOT_PASSWORD` for the dedicated Gmail inbox.
- `RFQ_STORAGE_CONNECTION`: a storage connection string for the durable mail journal. The code can also use a connection-string `AzureWebJobsStorage`; identity-based host storage alone is not sufficient for this journal implementation.
- `RFQ_MAIL_ENABLED=true` to activate the timer.
- Optional `RFQ_ALLOWED_SENDERS` to limit accepted sender and reply addresses.
- `RFQ_QUALITY=ai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` to activate the AI Quality Agent.

Do not run the local bot and Azure timer against the same inbox at the same time: their default journals are separate.

## Operational limits

- HTTP requests have a platform response timeout. Use small RFQs with HTTP; use the timer for larger or slower jobs. A queue-based submission API is a future extension, not implemented here.
- Each timer poll handles up to three emails. Each job processes products sequentially, with per-source timeouts.
- Azure output files are temporary. The timer emails the workbook; only the mail send journal persists in Blob Storage.
- If a worker stops with a journal entry in `processing` or `sending`, inspect the request and Gmail Sent folder before manually resetting that entry. This deliberately favors avoiding duplicate replies over automatic retries after uncertain delivery.
- Live pages may be blocked, and PDF links may fail. Notes explain fallback and skipped extraction.

## Official references

- [Azure Functions Python developer guide](https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python)
- [Create a Flex Consumption app](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)
- [Timer trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-timer)
