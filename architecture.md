# RFQ Workflow Architecture

The file-based CLI, Gmail bot, and Azure Functions entry points converge on the shared RFQ pipeline. Product values retain their source evidence, and lower-priority sources only fill fields left blank by higher-priority sources.

```mermaid
flowchart TD
    subgraph Inputs["Request entry points"]
        FILE["build.py<br/>Local .eml file"]
        GMAIL["mailbot.py<br/>Poll Gmail via IMAP"]
        HTTP["Azure Function<br/>POST /rfq"]
        TIMER["Optional Azure timer<br/>Gmail polling"]
    end

    FILE --> PIPE
    GMAIL --> PIPE
    HTTP --> PIPE
    TIMER --> PIPE

    subgraph Pipeline["Shared RFQ processing — app.pipeline.build"]
        PIPE["Read email and attachments"]
        EXTRACT["Extract product IDs<br/>from message body and XLSX<br/>Deduplicate; preserve order"]
        LOOKUP["Look up each product"]
        WEB["Ferguson product page<br/>Chrome or HTTPS"]
        PDF["Linked specification PDFs"]
        CATALOG["Backup product catalog"]
        MERGE["Merge fields by source priority<br/>Ferguson → PDF → catalog<br/>Keep evidence and provenance"]
        UNKNOWN["Unknown or unavailable product<br/>Mark Not Found"]
        QUALITY["Rules review<br/>Normalize units and check values"]
        AI["Optional AI Quality Agent<br/>Reviews evidence and records findings<br/>Does not change specifications"]
        WORKBOOK["Generate RFQ.xlsx<br/>RFQ · Sources · Notes · Summary · Agent Review"]
        ARTIFACTS["Save reply.eml, summary.json,<br/>quality-trace.json, and review state"]

        PIPE --> EXTRACT --> LOOKUP
        LOOKUP --> WEB
        WEB --> PDF
        PDF --> CATALOG
        WEB --> MERGE
        PDF --> MERGE
        CATALOG --> MERGE
        LOOKUP -. "No product found" .-> UNKNOWN
        MERGE --> QUALITY
        QUALITY --> AI
        QUALITY -. "Rules-only mode" .-> WORKBOOK
        AI --> WORKBOOK
        UNKNOWN --> WORKBOOK
        WORKBOOK --> ARTIFACTS
    end

    subgraph Delivery["Output and delivery"]
        DRAFT["CLI: save workbook and reply draft"]
        SMTP["Gmail: send threaded reply<br/>with RFQ.xlsx attached"]
        RESPONSE["Azure: return RFQ.xlsx"]
    end

    ARTIFACTS --> DRAFT
    ARTIFACTS --> SMTP
    WORKBOOK --> RESPONSE

    subgraph Review["Local dashboard and human review"]
        DB["SQLite request and finding data"]
        API["Local Python dashboard API"]
        UI["React dashboard"]
        DECIDE["Reviewer approves or rejects<br/>a proposed fix"]
        REBUILD["Approved evidence-based fix<br/>regenerates RFQ.xlsx"]
    end

    GMAIL -. "Request status and findings" .-> DB
    FILE -. "Request status and findings" .-> DB
    DB --> API --> UI
    UI --> DECIDE --> REBUILD
    REBUILD --> WORKBOOK
```

## Workflow notes

- Lookup order is Ferguson product page, specification PDF, then the backup catalog. Source precedence is applied field by field.
- Rules-based quality checks run every time. AI review is optional and advisory; it cannot overwrite product specifications.
- The CLI saves a reply draft. The Gmail bot sends the threaded reply and attached workbook. Azure's HTTP route returns the workbook.
- The local dashboard reads request data from SQLite. A reviewer-approved fix is applied only when supported by existing evidence, then the workbook is regenerated.
