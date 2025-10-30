<#
BookSoul Factory Build Helper
Скрипт для сборки и деплоя сервисов: webhook или worker.
Использование:
  .\build.ps1 webhook
  .\build.ps1 worker
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("webhook", "worker")]
    [string]$target
)

$project = "booksoulv2"
$region  = "europe-central2"
$serviceAccount = "booksoul-factory-agent@$project.iam.gserviceaccount.com"

function Build-Webhook {
    Write-Host "`n==> Build: BookSoul Webhook" -ForegroundColor Cyan
    gcloud builds submit --config=cloudbuild.yaml --substitutions=_DOCKERFILE=Dockerfile,_IMAGE=gcr.io/$project/booksoul-webhook2 .
    Write-Host "`n==> Deploy: BookSoul Webhook" -ForegroundColor Cyan
    gcloud run deploy booksoul-webhook2 `
        --image "gcr.io/$project/booksoul-webhook2" `
        --region $region `
        --allow-unauthenticated `
        --service-account=$serviceAccount
}

function Build-Worker {
    Write-Host "`n==> Build: BookSoul Worker" -ForegroundColor Yellow
    gcloud builds submit --config=cloudbuild.yaml --substitutions=_DOCKERFILE=Dockerfile.worker,_IMAGE=gcr.io/$project/booksoul-worker .
    Write-Host "`n==> Deploy: BookSoul Worker" -ForegroundColor Yellow
    gcloud run deploy booksoul-worker `
        --image "gcr.io/$project/booksoul-worker" `
        --region $region `
        --allow-unauthenticated `
        --service-account=$serviceAccount
}

switch ($target) {
    "webhook" { Build-Webhook }
    "worker"  { Build-Worker }
}
