param(
    [switch] $VerifyOnly,
    [string] $Location = "centralindia",
    [string] $SubscriptionId = "19c4d206-ce9b-469c-b9b8-3bb610f4da21"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDirectory = Join-Path $ProjectRoot ".azure"
$StatePath = Join-Path $StateDirectory "deployment.json"
$ToolsDirectory = Join-Path $ProjectRoot ".tools"
$CliDirectory = Join-Path $ToolsDirectory "azure-cli"
$PackagePath = Join-Path $ProjectRoot ".packages\func-deploy.zip"
$VerificationWorkbook = Join-Path $ProjectRoot ".packages\azure-rfq-verification.xlsx"
$SampleEmail = Join-Path $ProjectRoot "emails\email-1-ids-in-body.eml"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Get-AzureCliPath {
    $installed = Get-Command az -ErrorAction SilentlyContinue
    if ($installed) { return $installed.Source }

    $portable = Join-Path $CliDirectory "bin\az.cmd"
    if (-not (Test-Path -LiteralPath $portable)) {
        New-Item -ItemType Directory -Force -Path $ToolsDirectory | Out-Null
        $archive = Join-Path $ToolsDirectory "azure-cli.zip"
        Write-Host "Azure CLI is not on PATH; downloading Microsoft's portable Azure CLI."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://aka.ms/installazurecliwindowszipx64" -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $CliDirectory -Force
        Remove-Item -LiteralPath $archive -Force
    }
    if (-not (Test-Path -LiteralPath $portable)) {
        throw "Azure CLI was not found after extracting the portable package to $CliDirectory"
    }
    return $portable
}

function Invoke-Az {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:AzPath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Azure CLI failed: az $($Arguments -join ' ')"
    }
}

function Invoke-AzText {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $result = & $script:AzPath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Azure CLI failed: az $($Arguments -join ' ')"
    }
    return ($result -join "`n")
}

function Test-AzCommand {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:AzPath @Arguments 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Save-DeploymentState {
    $script:DeploymentState | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Get-AppUrl {
    $appJson = Invoke-AzText @(
        "functionapp", "show", "--resource-group", $DeploymentState.resourceGroup,
        "--name", $DeploymentState.functionApp, "--output", "json"
    ) | ConvertFrom-Json
    $hostname = $appJson.properties.defaultHostName
    if (-not $hostname) { $hostname = $appJson.defaultHostName }
    if (-not $hostname -or $hostname -notmatch '^[a-zA-Z0-9.-]+$') {
        throw "Azure did not return a valid Function App hostname."
    }
    return "https://$hostname"
}

function Test-DeployedApp {
    $baseUrl = Get-AppUrl
    $DeploymentState.appUrl = $baseUrl
    Save-DeploymentState

    Write-Host "Checking $baseUrl/healthz (cold start can take several minutes)..."
    $health = $null
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$baseUrl/healthz" -TimeoutSec 30
            if ($health.status -eq "ok") { break }
        } catch {
            if ($attempt -eq 30) { throw }
        }
        Start-Sleep -Seconds 10
    }
    if (-not $health -or $health.status -ne "ok") {
        throw "Health check did not return status=ok."
    }

    $key = Invoke-AzText @(
        "functionapp", "keys", "list", "--resource-group", $DeploymentState.resourceGroup,
        "--name", $DeploymentState.functionApp, "--query", "functionKeys.default", "--output", "tsv"
    )
    $key = $key.Trim()
    if (-not $key) { throw "Azure did not return the default Function key for the /rfq smoke check." }

    $python = $PythonPath
    if (-not (Test-Path -LiteralPath $python)) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if (-not $command) { throw "Python was not found. Create the project .venv before verification." }
        $python = $command.Source
    }
    if (-not (Test-Path -LiteralPath $SampleEmail)) { throw "Sample RFQ email is missing: $SampleEmail" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VerificationWorkbook) | Out-Null

    Write-Host "Posting the sample email to /rfq?offline=true and checking the returned workbook..."
    Invoke-WebRequest -Uri "$baseUrl/rfq?offline=true" -Method Post `
        -Headers @{ "x-functions-key" = $key } `
        -ContentType "message/rfc822" -InFile $SampleEmail -OutFile $VerificationWorkbook | Out-Null

    & $python (Join-Path $ProjectRoot "package_deploy.py") --verify-workbook $VerificationWorkbook
    if ($LASTEXITCODE -ne 0) { throw "The Azure response was not a valid RFQ workbook." }
    Write-Host "Deployment verified. Open: $baseUrl"
    Write-Host "RFQ endpoint: $baseUrl/rfq (Function key required)"
}

New-Item -ItemType Directory -Force -Path $StateDirectory | Out-Null
$env:AZURE_CONFIG_DIR = $StateDirectory
$script:AzPath = Get-AzureCliPath

if (-not (Test-Path -LiteralPath $StatePath)) {
    if ($VerifyOnly) { throw "No deployment state found at $StatePath. Run deploy.ps1 first." }
    $script:DeploymentState = $null
} else {
    $script:DeploymentState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
}

if ($VerifyOnly) {
    if ($SubscriptionId) { Invoke-Az @("account", "set", "--subscription", $SubscriptionId) }
    if (-not $DeploymentState.subscriptionId) { throw "Deployment state has no subscription ID." }
    if (-not $SubscriptionId) { Invoke-Az @("account", "set", "--subscription", $DeploymentState.subscriptionId) }
    Test-DeployedApp
    exit 0
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Project Python environment not found at $PythonPath. Create it and install requirements-dev.txt first."
}
& $PythonPath (Join-Path $ProjectRoot "package_deploy.py")
if ($LASTEXITCODE -ne 0) { throw "Deployment package preparation failed." }

if (-not (Test-AzCommand @("account", "show", "--output", "none"))) {
    Write-Host "Sign in to Azure using the device code shown below."
    & $AzPath login --use-device-code
    if ($LASTEXITCODE -ne 0) { throw "Azure sign-in failed." }
}

if ($DeploymentState) {
    if ($SubscriptionId) { Invoke-Az @("account", "set", "--subscription", $SubscriptionId) }
    elseif ($DeploymentState.subscriptionId) { Invoke-Az @("account", "set", "--subscription", $DeploymentState.subscriptionId) }
} else {
    if ($SubscriptionId) { Invoke-Az @("account", "set", "--subscription", $SubscriptionId) }
    $activeAccount = Invoke-AzText @("account", "show", "--output", "json") | ConvertFrom-Json
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $script:DeploymentState = [PSCustomObject]@{
        subscriptionId = $activeAccount.id
        location = $Location
        resourceGroup = "rg-ferg-rfq-$suffix"
        storageAccount = "stfergrfq$suffix"
        functionApp = "ferg-rfq-$suffix"
        appUrl = $null
    }
    Save-DeploymentState
}

$currentSubscription = Invoke-AzText @("account", "show", "--query", "id", "--output", "tsv")
if ($DeploymentState.subscriptionId -and $currentSubscription.Trim() -ne $DeploymentState.subscriptionId) {
    throw "The active subscription does not match .azure/deployment.json. Select the saved subscription before continuing."
}
$DeploymentState.location = $Location
Save-DeploymentState

$locations = Invoke-AzText @("functionapp", "list-flexconsumption-locations", "--output", "json") | ConvertFrom-Json
$locationNames = @($locations | ForEach-Object { if ($_ -is [string]) { $_ } else { $_.name } })
if ($Location -notin $locationNames) {
    throw "Region '$Location' is not currently listed for Flex Consumption. Choose one from: $($locationNames -join ', ')"
}

foreach ($provider in @("Microsoft.Web", "Microsoft.Storage", "Microsoft.Insights", "Microsoft.OperationalInsights")) {
    Invoke-Az @("provider", "register", "--namespace", $provider, "--wait", "--output", "none")
}

Write-Host "Creating or reusing resource group $($DeploymentState.resourceGroup) in $Location..."
Invoke-Az @(
    "group", "create", "--name", $DeploymentState.resourceGroup,
    "--location", $Location, "--output", "none"
)

$storageExists = Test-AzCommand @(
    "storage", "account", "show", "--name", $DeploymentState.storageAccount,
    "--resource-group", $DeploymentState.resourceGroup, "--output", "none"
)
if (-not $storageExists) {
    Invoke-Az @(
        "storage", "account", "create", "--name", $DeploymentState.storageAccount,
        "--resource-group", $DeploymentState.resourceGroup, "--location", $Location,
        "--sku", "Standard_LRS", "--kind", "StorageV2",
        "--allow-blob-public-access", "false", "--min-tls-version", "TLS1_2", "--output", "none"
    )
}

$appExists = Test-AzCommand @(
    "functionapp", "show", "--name", $DeploymentState.functionApp,
    "--resource-group", $DeploymentState.resourceGroup, "--output", "none"
)
if (-not $appExists) {
    Write-Host "Creating Flex Consumption Function App $($DeploymentState.functionApp)..."
    Invoke-Az @(
        "functionapp", "create", "--name", $DeploymentState.functionApp,
        "--resource-group", $DeploymentState.resourceGroup,
        "--storage-account", $DeploymentState.storageAccount,
        "--flexconsumption-location", $Location,
        "--runtime", "python", "--runtime-version", "3.11",
        "--https-only", "true", "--output", "none"
    )
}

# These are non-secret platform settings. Leave AI/Gmail settings untouched on redeploy.
Invoke-Az @(
    "functionapp", "config", "appsettings", "set",
    "--resource-group", $DeploymentState.resourceGroup,
    "--name", $DeploymentState.functionApp,
    "--settings", "RFQ_BROWSER=false", "RFQ_DB=off", "--output", "none"
)

Write-Host "Uploading the package and asking Azure to build Python dependencies..."
Invoke-Az @(
    "functionapp", "deployment", "source", "config-zip",
    "--name", $DeploymentState.functionApp,
    "--resource-group", $DeploymentState.resourceGroup,
    "--src", $PackagePath, "--build-remote", "true", "--timeout", "900", "--output", "none"
)

Test-DeployedApp
