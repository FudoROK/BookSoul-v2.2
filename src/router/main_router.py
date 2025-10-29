import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from data_layer.firestore_client import FirestoreClient


class BookSoulRouter:
    """
    BookSoulRouter = 'начальник цеха'.
    Он управляет жизненным циклом книги:
    - создаёт новую книгу
    - обновляет статус этапа
    - регистрирует сцены
    - возвращает сводку прогресса
    - пишет служебные записи в Firestore (через FirestoreClient)

    Важно: это бизнес-логика. Никаких Telegram, никакого FastAPI здесь.
    Потом мы будем вызывать эти методы из бота и из HTTP.
    """

    def __init__(self,
                 project_id: str = "booksoulv2",
                 credentials_path: str = "serviceAccountKey.json"):
        self.fs = FirestoreClient(
            project_id=project_id,
            credentials_path=credentials_path,
            root_collection="books"
        )

    # -------------------------------------------------------------------------
    # ВСПОМОГАТЕЛЬНОЕ
    # -------------------------------------------------------------------------

    def _make_trace_id(self) -> str:
        """
        Унифицированный ID книги.
        Пример: BKS-20251028-123045
        """
        return self.fs.make_trace_id()

    # -------------------------------------------------------------------------
    # СОЗДАНИЕ КНИГИ
    # -------------------------------------------------------------------------

    def create_new_book(
        self,
        child_name: str,
        theme: str,
        language: str = "ru",
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Создать новую книгу в системе.
        Это вызывается, когда ты (или бот) говоришь: "сделай сказку про X".
        Возвращает инфу о книге.
        """

        book_id = self._make_trace_id()

        self.fs.create_book(
            book_id=book_id,
            child_name=child_name,
            theme=theme,
            language=language,
            status="draft",
            title=title
        )

        # Можно сразу создать задачу первого этапа (StoryWriter)
        job_id = self.fs.create_job(
            book_id=book_id,
            job_type="storywriter",
            status="pending",
            result_url=""
        )

        return {
            "book_id": book_id,
            "job_id": job_id,
            "status": "draft",
            "message": f"Книга создана. ID: {book_id}. Начинаем сценарий."
        }

    # -------------------------------------------------------------------------
    # СЦЕНЫ
    # -------------------------------------------------------------------------

    def register_scene(
        self,
        book_id: str,
        page_number: int,
        text: str,
        prompt_main: str,
        prompt_background: str,
        scene_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        StoryWriter вызывает это после генерации одной сцены.
        То есть этот метод добавляет сцену в Firestore.
        """

        if scene_id is None:
            scene_id = f"scene_{page_number:03d}"

        self.fs.add_scene(
            book_id=book_id,
            scene_id=scene_id,
            page_number=page_number,
            text=text,
            prompt_main=prompt_main,
            prompt_background=prompt_background,
            status="pending",   # ещё не сгенерили картинку
            image_url=""
        )

        # создадим job для художки этой сцены
        job_id = self.fs.create_job(
            book_id=book_id,
            job_type="scene_generation",
            status="pending",
            result_url=""
        )

        return {
            "ok": True,
            "scene_id": scene_id,
            "job_id": job_id,
            "message": f"Сцена {scene_id} добавлена и отправлена в очередь художке."
        }

    # -------------------------------------------------------------------------
    # ОБНОВЛЕНИЕ СТАТУСА КНИГИ
    # -------------------------------------------------------------------------

    def advance_status(
        self,
        book_id: str,
        new_status: str
    ) -> Dict[str, Any]:
        """
        Мануальное или автоматическое продвижение состояния книги.
        Пример: writing → drawing → styling → cover → layout → approval → ready
        """

        self.fs.update_book_status(book_id, new_status)

        return {
            "book_id": book_id,
            "status": new_status,
            "message": f"Статус книги обновлён на '{new_status}'."
        }

    # -------------------------------------------------------------------------
    # ОБЛОЖКА / PDF
    # -------------------------------------------------------------------------

    def attach_cover(
        self,
        book_id: str,
        cover_url: str
    ) -> Dict[str, Any]:
        """
        Вызывается CoverBuilder после генерации финальной обложки.
        """
        self.fs.attach_cover_url(book_id, cover_url)
        self.fs.create_job(
            book_id=book_id,
            job_type="cover",
            status="done",
            result_url=cover_url
        )
        return {
            "book_id": book_id,
            "cover_url": cover_url,
            "message": "Обложка прикреплена."
        }

    def attach_pdf(
        self,
        book_id: str,
        pdf_url: str
    ) -> Dict[str, Any]:
        """
        Вызывается LayoutEngine, когда финальный PDF готов.
        """
        self.fs.attach_pdf_url(book_id, pdf_url)
        self.fs.create_job(
            book_id=book_id,
            job_type="layout",
            status="done",
            result_url=pdf_url
        )
        return {
            "book_id": book_id,
            "pdf_url": pdf_url,
            "message": "PDF готов и прикреплён."
        }

    # -------------------------------------------------------------------------
    # ФИДБЕК (ТВОИ ПРАВКИ)
    # -------------------------------------------------------------------------

    def add_feedback(
        self,
        book_id: str,
        comment_text: str
    ) -> Dict[str, Any]:
        """
        Любой комментарий от тебя (типа 'перегенерить сцену 2, лицо кривое').
        Он пишется в feedback коллекцию и потом Router может это читать.
        """
        self.fs.add_feedback(
            book_id=book_id,
            comment_text=comment_text,
            source="user"
        )
        return {
            "book_id": book_id,
            "message": "Комментарий зафиксирован."
        }

    # -------------------------------------------------------------------------
    # СТАТУС КНИГИ ДЛЯ ТЕБЯ
    # -------------------------------------------------------------------------

    def get_book_status(self, book_id: str) -> Dict[str, Any]:
        """
        Возвращает полную сводку, чтобы отправить в Telegram.
        Тут мы соберём: текущий статус книги, сцены, ссылки.
        """

        book_doc = self.fs.get_book(book_id)
        if not book_doc:
            return {
                "ok": False,
                "error": "book_not_found",
                "message": f"Книга с ID {book_id} не найдена."
            }

        scenes = self.fs.list_scenes(book_id)

        # делаем удобный ответ
        info = {
            "book_id": book_id,
            "title": book_doc.get("title", ""),
            "child_name": book_doc.get("child_name", ""),
            "theme": book_doc.get("theme", ""),
            "status": book_doc.get("status", ""),
            "pdf_url": book_doc.get("pdf_url", ""),
            "cover_url": book_doc.get("cover_url", ""),
            "scenes_count": len(scenes),
            "scenes": [
                {
                    "page": s.get("page"),
                    "status": s.get("status"),
                    "has_image": bool(s.get("image_url")),
                } for s in scenes
            ]
        }

        return {
            "ok": True,
            "info": info
        }


# -----------------------------------------------------------------------------
# ЛОКАЛЬНЫЙ ТЕСТ (чтобы проверить, что Router реально живой)
# Запускается вот так:
#   python .\src\router\main_router.py
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    router = BookSoulRouter(
        project_id="booksoulv2",
        credentials_path="serviceAccountKey.json",  # поменяй если ключ называется иначе
    )

    # 1. создаём новую книгу
    new_book = router.create_new_book(
        child_name="Алиса",
        theme="маленькая исследовательница космоса и дружелюбный робот",
        language="ru",
        title="Алиса и Звёздный Робот"
    )
    print("📗 create_new_book ->", new_book)

    new_book_id = new_book["book_id"]

    # 2. регистрируем первую сцену
    scene_resp = router.register_scene(
        book_id=new_book_id,
        page_number=1,
        text="Алиса нашла старого робота в своём шкафу. Он сказал: 'Я прилетел из космоса за тобой.'",
        prompt_main="6-year-old girl in pajamas, holding hand-made robot friend, warm bedroom light, excited expression",
        prompt_background="kid's bedroom, night, soft star projector glow, cozy blankets, toys scattered"
    )
    print("🎬 register_scene ->", scene_resp)

    # 3. меняем статус книги на 'writing'
    step1_status = router.advance_status(
        book_id=new_book_id,
        new_status="writing"
    )
    print("🔄 advance_status ->", step1_status)

    # 4. достаём полный статус книги
    status = router.get_book_status(new_book_id)
    print("📊 get_book_status ->", status)
