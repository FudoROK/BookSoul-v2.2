from config import settings

print("GCP project ID:", settings.gcp_project_id)
print("OpenAI model:", settings.openai_model_name)
print("OpenAI key (первые 8 символов):", settings.openai_api_key[:8])
