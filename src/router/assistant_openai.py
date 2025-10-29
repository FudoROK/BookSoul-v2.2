import os
import sys
import json

# --- путь к проекту, чтобы работали импорты ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../src/router
SRC_DIR = os.path.dirname(CURRENT_DIR)                         # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                        # .../
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import settings
from openai import OpenAI
from router.tools_router import ToolRouter


ROUTER_SYSTEM_PROMPT = """
Ты — BookSoul Router, директор и художественный редактор фабрики персональных детских книг BookSoul.

Твоя миссия:
1. Понимать просьбу автора (Фудо) и переводить её в понятные, вменяемые задачи для цехов.
2. Контролировать качество на каждом этапе: текст → иллюстрация → стиль → обложка → вёрстка → PDF.
3. Никогда не гнать брак вперёд без утверждения.

Цеха:
- StoryWriter: пишет историю ребёнка и разбивает на сцены (каждая сцена — завершённый момент с эмоцией).
- SceneBuilder: делает визуал по сценам через Nano Banana (Gemini). Отдельно герой (ребёнок), отдельно фон.
- Style Engine: следит за единым стилем (цвета, освещение, возраст героя, настроение).
- Cover Builder: делает обложку (титульную страницу). Лицо ребёнка должно быть тем же самым лицом.
- Layout Engine: вёрстка финальной книги в PDF (A5, 300 DPI). Крупный дружелюбный шрифт, текст не налезает на арт.

Правила Nano Banana (важно):
- В начале и в конце промта для генерации героя обязательно фраза:
  "Keep the same face as in the uploaded photo. Do not distort or change the face."
- Затем блок Face description: сухое визуальное описание лица (форма лица, кожа, волосы, глаза/нос/губы, выражение).
  Без эмо-поэзии, строго визуально.
- Потом блок Scene: кто он, где он, какой свет, какая атмосфера, какая одежда, что он делает.
- В конце снова фраза про сохранение лица.
- Температура генерации 0.1–0.2, чтобы избежать искажений.
- Если герой должен выглядеть как игрушка/фигурка, добавляй:
  "clearly toy-like, made of painted resin or plastic, not alive."

Правила текста:
- Текст должен звучать человечно и тепло, как родитель рассказывает ребёнку, а не как сухой ИИ.
- Каждая сцена читабельна вслух.
- После напряжения всегда даём мягкость и безопасность.
- Финал истории оставляет ощущение уюта и надежды, а не просто "конец."

Правила дизайна:
- На обложке герой смотрит "вперёд", свет тёплый, чувство мечты и надежды.
- Цветовая психология: тёплые тона = безопасность, закат = мечта.
- Вёрстка: поля не слишком узкие, текст не прилипает к краю, не закрывает лицо героя.
- Шрифт крупный, дружелюбный (например Nunito / Comic Neue / шрифт без острых углов).
- Белое пространство — не ошибка, а дыхание страницы.

Процесс управления:
- Если Фудо даёт правку ("сделай фон светлее", "ребёнок должен быть по центру", "обложка темновата"),
  ты фиксируешь это как задачу, и книга не двигается дальше, пока он не скажет "утверждаю".
- Твоя задача — понимать неформальные правки и переводить их в чёткие технические инструкции для соответствующего цеха.
- Перед тем как отправить дальше, ты всегда уточняешь у Фудо, всё ли ок.

Как говорить:
- Коротко, по делу, но по-человечески.
- Ты не извиняешься лишний раз. Ты производственный директор, у тебя спокойствие и уверенность.
- Ты объясняешь, что ты делаешь, так, чтобы Фудо чувствовал контроль.
"""


class OpenAIRouterAgent:
    """
    Router-агент, работающий через Responses API.
    Он умеет говорить с Фудо тоном директора фабрики
    и, через вспомогательные методы, может отдавать короткие формальные инструкции.
    """

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model_name = settings.openai_model_name  # например "gpt-5" или "gpt-5-pro"

    def _call_responses_api(self, messages, temperature: float = 0.3) -> str:
        """
        Внутренний низкоуровневый вызов Responses API.
        messages — это список {role, content}.
        Возвращает слитый текст.
        Поддерживает и новые SDK (inference_config), и старые.
        """
        try:
            response = self.client.responses.create(
                model=self.model_name,
                input=messages,
                inference_config={
                    "temperature": temperature
                }
            )
        except TypeError:
            # версия SDK без inference_config
            response = self.client.responses.create(
                model=self.model_name,
                input=messages
            )

        # собираем текст
        chunks = []
        if hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", None) == "message":
                    for c in getattr(item, "content", []):
                        txt = getattr(c, "text", None)
                        if txt:
                            chunks.append(txt)

        if not chunks and hasattr(response, "output_text"):
            chunks.append(response.output_text)

        return "\n".join(chunks).strip()

    def ask_router(self, user_text: str) -> str:
        """
        Свободный режим. Ты спрашиваешь как человек,
        он отвечает как директор фабрики (редактор).
        Это хорошо для обсуждения стиля, качества, правок.
        """
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        return self._call_responses_api(messages, temperature=0.3)

    def _raw_responses_call(self, system_prompt: str, user_text: str) -> str:
        """
        Специальный режим: просим GPT-5 выдать СТРОГО СТРУКТУРИРОВАННЫЙ ответ,
        например JSON команды для фабрики.
        Здесь мы не делаем красивый человеческий стиль,
        здесь он должен говорить как машина.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        return self._call_responses_api(messages, temperature=0.2)


class Orchestrator:
    """
    Orchestrator = мост между человеком (тобой), GPT-5 и фабрикой BookSoul.
    Логика:
    1. Ты говоришь обычной человеческой фразой.
    2. GPT-5 превращает это в JSON-команду для завода.
    3. Мы исполняем эту команду через ToolRouter (он дёргает BookSoulRouter и Firestore).
    4. Мы формируем понятный ответ для тебя.
    """

    def __init__(self, agent: OpenAIRouterAgent):
        self.agent = agent
        self.tools = ToolRouter()

    def plan_action(self, user_text: str) -> dict:
        """
        Просим GPT-5 сделать план в виде JSON.
        Форматы команд:
        - {"action": "create_book", "author": "Арсен", "theme": "маленький пилот и волшебный самолёт"}
        - {"action": "add_feedback", "book_id": "BKS-2025...", "note": "обложку сделать светлее"}
        - {"action": "get_status", "book_id": "BKS-2025..."}
        Если он не уверен: {"action": "unknown", "question": "..."}
        """

        system_msg = (
            "Ты — планировщик действий для производственной линии BookSoul.\n"
            "Твоя задача — понять запрос человека и вернуть ТОЛЬКО JSON-команду для выполнения.\n"
            "НЕ давать пояснений, НЕ болтать, НЕТ текста вне JSON.\n"
            "\n"
            "Типы команд:\n"
            "1) create_book:\n"
            "   - Создать новую детскую книгу.\n"
            "   - Поля в ответе:\n"
            "     {\n"
            "       \"action\": \"create_book\",\n"
            "       \"author\": \"имя ребёнка\",\n"
            "       \"theme\": \"тема сказки\"\n"
            "     }\n"
            "   - Правило интерпретации: если пользователь говорит 'создай книгу для Арсена',\n"
            "     считай, что author = 'Арсен' (это имя ребёнка / главный герой).\n"
            "   - НЕ задавай уточняющих вопросов, просто поставь это имя как author.\n"
            "\n"
            "2) add_feedback:\n"
            "   {\n"
            "     \"action\": \"add_feedback\",\n"
            "     \"book_id\": \"...\",\n"
            "     \"note\": \"текст правки\"\n"
            "   }\n"
            "\n"
            "3) get_status:\n"
            "   {\n"
            "     \"action\": \"get_status\",\n"
            "     \"book_id\": \"...\"\n"
            "   }\n"
            "\n"
            "Если невозможно определить намерение, верни:\n"
            "{ \"action\": \"unknown\", \"question\": \"что уточнить\" }\n"
        )

        planning_prompt = (
            f"Запрос пользователя:\n'''{user_text}'''\n\n"
            "Верни только один JSON-объект с полями команды, без пояснений."
        )

        raw_plan = self.agent._raw_responses_call(system_msg, planning_prompt)

        try:
            plan = json.loads(raw_plan)
        except json.JSONDecodeError:
            plan = {
                "action": "unknown",
                "raw": raw_plan,
            }

        return plan

    def execute_plan(self, plan: dict) -> dict:
        """
        Выполняем план через внутренние инструменты фабрики.
        ToolRouter сам вызывает BookSoulRouter, который пишет в Firestore и т.д.
        """
        return self.tools.execute(plan)

    def pretty_answer_for_user(self, plan: dict, result: dict) -> str:
        """
        Финальная формулировка для тебя: что сделано, какой ID книги, какой статус.
        Тон: спокойный, уверенный, человеческий.
        """

        if result.get("ok"):
            action = plan.get("action")

            if action == "create_book":
                book_id = result["result"]["book_id"]
                theme = plan.get("theme", "")
                author = plan.get("author", "")
                return (
                    f"Я запустил новую книгу для {author}.\n"
                    f"Тема: {theme}.\n"
                    f"ID книги: {book_id}.\n"
                    "Сценарий уходит в StoryWriter. Дальше я не двину без твоего утверждения текста."
                )

            if action == "add_feedback":
                book_id = plan.get("book_id", "")
                note = plan.get("note", "")
                return (
                    f"Я записал правку к книге {book_id}:\n«{note}».\n"
                    "Производство на этом шаге поставлено на паузу, пока ты не скажешь 'утверждаю'."
                )

            if action == "get_status":
                status = result["result"].get("status")
                return (
                    f"Смотрю статус книги {plan.get('book_id')}.\n"
                    f"Текущий этап: {status}."
                )

            # общее успешное действие
            return "Готово. Команда выполнена."

        # неуспешный случай
        if plan.get("action") == "unknown":
            ask = plan.get("question") or plan.get("raw", "")
            return (
                "Мне не хватает данных, чтобы сделать действие.\n"
                f"Уточни, пожалуйста: {ask}"
            )

        return (
            "Я попробовал выполнить действие, но что-то не так — возможно, не указан book_id "
            "или книга не найдена."
        )

    def run(self, user_text: str) -> str:
        """
        Полный цикл:
        1. GPT-5 планирует действие (возвратит JSON команды).
        2. Мы исполняем его через фабрику.
        3. Я возвращаю тебе нормальный человеческий ответ.
        """
        plan = self.plan_action(user_text)
        result = self.execute_plan(plan)
        answer = self.pretty_answer_for_user(plan, result)
        return answer


def handle_user_message(user_text: str) -> str:
    """
    Публичная обёртка для внешних интерфейсов (Telegram webhook и т.д.).
    Принимает текст пользователя и возвращает готовый человеческий ответ.
    """
    agent = OpenAIRouterAgent()
    orch = Orchestrator(agent)
    return orch.run(user_text)


if __name__ == "__main__":
    # режим А: нормальный "разговорный" ответ директора (чисто описание качества и правил)
    agent = OpenAIRouterAgent()
    sample_freeform = (
        "Опиши финальную обложку для книги про мальчика-пилота 6 лет и его волшебный самолёт. "
        "Она должна быть тёплой, мечтательной, безопасной, как воспоминание детства. "
        "Напомни правила Nano Banana про лицо ребёнка."
    )
    director_view = agent.ask_router(sample_freeform)

    print("=== Режим А / художественный директор ===")
    print(director_view)
    print("=== /конец А ===\n")

    # режим Б: производственное действие (оркестрация)
    orch = Orchestrator(agent)
    user_cmd = "создай книгу. ребёнка зовут Арсен, ему 6 лет. тема: маленький пилот и волшебный самолёт"
    result_for_user = orch.run(user_cmd)

    print("=== Режим Б / производство ===")
    print(result_for_user)
    print("=== /конец Б ===")
