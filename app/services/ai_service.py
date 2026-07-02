import openai

from app.services.llm_client import default_client

DEFAULT_MODEL = "gpt-4o"


class AIService:
    def __init__(self, client: openai.OpenAI | None = None) -> None:
        self._client = client or default_client()

    def generate_itinerary(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_completion_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content


ai_service = AIService()
