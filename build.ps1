<#
BookSoul Factory Build Helper
Сборка и деплой двух сервисов: webhook | worker
Использование:
  .\build.ps1 webhook
  .\build.ps1 worker
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("webhook","worker")]
    [string]$target
)

$project = "booksoulv2"
$region  = "europe-central2"
$serviceAccount = "booksoul-factory-agent@$project.iam.gserviceaccount.com"

function Build-Webhook {
    Write-Host "`n==> Build: BookSoul Webhook" -ForegroundColor Cyan
    gcloud builds submit --config=cloudbuild.webhook.yaml
    if ($LASTEXITCODE -ne 0) { throw "Cloud Build (webhook) failed." }

    Write-Host "`n==> Deploy: BookSoul Webhook" -ForegroundColor Cyan
    gcloud run deploy booksoul-webhook2 `
      --image gcr.io/$project/booksoul-webhook2 `
      --region $region `
      --allow-unauthenticated `
      --service-account=$serviceAccount
    if ($LASTEXITCODE -ne 0) { throw "Cloud Run deploy (webhook) failed." }
}

function Build-Worker {
    Write-Host "`n==> Build: BookSoul Worker" -ForegroundColor Yellow
    gcloud builds submit --config=cloudbuild.worker.yaml
    if ($LASTEXITCODE -ne 0) { throw "Cloud Build (worker) failed." }

    Write-Host "`n==> Deploy: BookSoul Worker" -ForegroundColor Yellow
    gcloud run deploy booksoul-worker `
      --image gcr.io/$project/booksoul-worker `
      --region $region `
      --allow-unauthenticated `
      --service-account=$serviceAccount
    if ($LASTEXITCODE -ne 0) { throw "Cloud Run deploy (worker) failed." }
}

switch ($target) {
  "webhook" { Build-Webhook }
  "worker"  { Build-Worker  }
}
