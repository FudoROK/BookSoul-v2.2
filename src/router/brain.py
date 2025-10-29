
import os
import sys
import re
from typing import Optional, Dict, Any

# -------------------------------------------------
# ДОБАВЛЯЕМ ПУТИ, ЧТОБЫ ИМПОРТЫ РАБОТАЛИ ПРИ ЛОКАЛЬНОМ ЗАПУСКЕ
# -------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))          # .../src/router
SRC_DIR = os.path.dirname(CURRENT_DIR)                             # .../src
PROJECT_ROOT = os.path.dirname(SRC_DIR)                            # .../ (корень репо)

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# теперь можно делать from router... / from data_layer... без ошибок
from router.main_router import BookSoulRouter


class RouterBrain:
    """
    RouterBrain — это слой "понимания намерений".
    Он решает, что пользователь на самом деле хочет,
    и дергает BookSoulRouter, который управляет фабрикой.

    Потом сюда добавим:
    - вызовы LLM (GPT/Gemini) для StoryWriter, CoverBuilder и т.д.
    - авто-продвижение статусов книги
    """

    def __init__(
        self,
        project_id: str = "booksoulv2",
        credentials_path: str = "serviceAccountKey.json"
    ):
        self.router = BookSoulRouter(
            project_id=project_id,
            credentials_path=credentials_path,
        )

    # ===========================
    # ПУБЛИЧНЫЙ ВХОД (команда текстом)
    # ===========================
    def handle_text_command(self, text: str) -> Dict[str, Any]:
        """
        Это то, что потом будет дергать телеграм-бот.
        Ты ему пишешь человеческим языком,
        а он решает, какое действие запустить.
        """

        # 1. Запрос статуса книги ("статус книги BKS-...").
        status_payload = self._try_parse_status_request(text)
        if status_payload is not None:
            return self._do_status(status_payload)

        # 2. Создание новой книги ("сделай книгу для Имя тема ТЕМА").
        create_payload = self._try_parse_create_request(text)
        if create_payload is not None:
            return self._do_create_book(create_payload)

        # 3. Правка / комментарий ("заметка к книге BKS-...").
        feedback_payload = self._try_parse_feedback_request(text)
        if feedback_payload is not None:
            return self._do_feedback(feedback_payload)

        # 4. Если не поняли.
        return {
            "ok": False,
            "action": "unknown",
            "message": "Не понял команду. Скажи: 'сделай книгу для ИМЯ тема ТЕМА' или 'статус книги BKS-...'"
        }

    # ===========================
    # РАСПОЗНАВАНИЕ КОМАНД
    # ===========================
    def _try_parse_create_request(self, text: str) -> Optional[Dict[str, str]]:
        """
        Парсим типа:
        'сделай книгу для Алисы тема космос'
        'создай книгу для Арсен тема динозавры'
        """
        m = re.search(
            r"(сделай|созда(й|ть))\s+книгу\s+для\s+([А-Яа-яA-Za-z0-9_\-]+)\s+тема\s+(.+)",
            text.strip(),
            re.IGNORECASE
        )
        if not m:
            return None

        child_name = m.group(3).strip()
        theme = m.group(4).strip()

        return {
            "child_name": child_name,
            "theme": theme,
            "language": "ru"
        }

    def _try_parse_status_request(self, text: str) -> Optional[Dict[str, str]]:
        """
        Парсим типа:
        'статус книги BKS-20251028-123045'
        'какой статус у BKS-20251028-123045'
        """
        m = re.search(
            r"(статус|status).*(BKS-[0-9\-]+)",
            text.strip(),
            re.IGNORECASE
        )
        if not m:
            return None

        book_id = m.group(2).strip()
        return {"book_id": book_id}

    def _try_parse_feedback_request(self, text: str) -> Optional[Dict[str, str]]:
        """
        Парсим типа:
        'заметка к книге BKS-... сделай обложку ярче'
        'правка к книге BKS-... сцена 2 не нравится лицо'
        """
        m = re.search(
            r"(заметка|правка).*(BKS-[0-9\-]+)\s+(.+)",
            text.strip(),
            re.IGNORECASE
        )
        if not m:
            return None

        book_id = m.group(2).strip()
        comment_text = m.group(3).strip()

        return {
            "book_id": book_id,
            "comment_text": comment_text
        }

    # ===========================
    # ДЕЙСТВИЯ
    # ===========================
    def _do_create_book(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """
        Создаём новую книгу + ставим job storywriter в очередь.
        """
        result = self.router.create_new_book(
            child_name=payload["child_name"],
            theme=payload["theme"],
            language=payload.get("language", "ru"),
        )

        return {
            "ok": True,
            "action": "create_book",
            "result": result,
            "message": (
                f"Книга создана для {payload['child_name']} с темой '{payload['theme']}'.\n"
                f"ID: {result['book_id']}\n"
                f"Дальше можно спросить: 'статус книги {result['book_id']}'"
            )
        }

    def _do_status(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """
        Получаем текущий статус книги, сцены, ссылки.
        """
        state = self.router.get_book_status(
            book_id=payload["book_id"]
        )
        if not state.get("ok"):
            return {
                "ok": False,
                "action": "status",
                "message": f"Книга {payload['book_id']} не найдена."
            }

        info = state["info"]
        human_text = (
            f"Книга {info['book_id']}\n"
            f"Герой: {info['child_name']}\n"
            f"Тема: {info['theme']}\n"
            f"Статус: {info['status']}\n"
            f"Сцен готово: {info['scenes_count']}\n"
            f"PDF: {info['pdf_url'] or '—'}\n"
            f"Обложка: {info['cover_url'] or '—'}"
        )

        return {
            "ok": True,
            "action": "status",
            "raw": info,
            "message": human_text
        }

    def _do_feedback(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """
        Фиксируем твою правку (это потом увидит Router и передаст в нужный цех).
        """
        self.router.add_feedback(
            book_id=payload["book_id"],
            comment_text=payload["comment_text"]
        )

        return {
            "ok": True,
            "action": "feedback",
            "message": (
                f"Записал правку в книгу {payload['book_id']}:\n"
                f"«{payload['comment_text']}»"
            )
        }


# -------------------------------------------------
# ЛОКАЛЬНЫЙ ТЕСТ
# -------------------------------------------------

if __name__ == "__main__":
    brain = RouterBrain(
        project_id="booksoulv2",
        credentials_path="serviceAccountKey.json",  # если у тебя другой json - поменяй
    )

    # 1. Тест создания книги
    cmd1 = "сделай книгу для Арсен тема маленький пилот и волшебный самолет"
    print("\n>>>", cmd1)
    print(brain.handle_text_command(cmd1))

    # 2. Тест статуса (подставь реальный ID, когда получишь его из create_book)
    cmd2 = "статус книги BKS-20251028-123045"
    print("\n>>>", cmd2)
    print(brain.handle_text_command(cmd2))

    # 3. Тест правки
    cmd3 = "заметка к книге BKS-20251028-123045 сделай обложку ярче и ребёнка крупнее по центру"
    print("\n>>>", cmd3)
    print(brain.handle_text_command(cmd3))
