from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

models = client.models.list()

for m in models.data:
    print(m.id)
