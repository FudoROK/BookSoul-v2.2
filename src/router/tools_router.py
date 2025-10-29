"""
tools_router.py — связующее звено между OpenAI Router GPT и локальным BookSoulRouter.
Он выполняет реальные действия (создание книги, добавление заметки, получение статуса)
и возвращает готовый JSON-ответ.
"""

import sys
import os
from typing import Dict, Any

# Подключаем пути к src, чтобы импортировать BookSoulRouter
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from router.main_router import BookSoulRouter


class ToolRouter:
    def __init__(self):
        # инициализируем твой основной роутер фабрики
        self.router = BookSoulRouter()

    def execute(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Принимает словарь вида:
        {"action": "create_book", "author": "Арсен", "theme": "маленький пилот и волшебный самолёт"}
        Возвращает ответ в виде JSON.
        """
        action = command.get("action")

        if action == "create_book":
            author = command.get("author", "Неизвестно")
            theme = command.get("theme", "Без темы")
            result = self.router.create_new_book(author, theme)
            return {
                "ok": True,
                "action": "create_book",
                "result": result,
                "message": f"Книга создана для {author} с темой '{theme}'."
            }

        elif action == "add_feedback":
            book_id = command.get("book_id")
            note = command.get("note")
            result = self.router.add_feedback(book_id, note)
            return {
                "ok": True,
                "action": "add_feedback",
                "message": f"Добавил заметку к книге {book_id}: {note}",
                "result": result,
            }

        elif action == "get_status":
            book_id = command.get("book_id")
            result = self.router.get_status(book_id)
            return {
                "ok": True,
                "action": "get_status",
                "result": result,
                "message": f"Статус книги {book_id}: {result.get('status')}"
            }

        else:
            return {
                "ok": False,
                "message": f"Неизвестное действие: {action}"
            }


if __name__ == "__main__":
    # Локальная проверка работы
    tools = ToolRouter()

    demo_cmds = [
        {"action": "create_book", "author": "Арсен", "theme": "маленький пилот и волшебный самолёт"},
        {"action": "add_feedback", "book_id": "BKS-20251028-111405", "note": "Сделай фон теплее"},
        {"action": "get_status", "book_id": "BKS-20251028-111405"}
    ]

    for cmd in demo_cmds:
        print("\n>>>", cmd)
        print(tools.execute(cmd))
