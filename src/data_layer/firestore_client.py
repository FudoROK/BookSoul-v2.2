import os
from typing import Optional, Dict, Any, List
from google.cloud import firestore
from datetime import datetime


# Важно:
# - этот модуль — это "официальный канал" общения с Firestore
# - все другие части фабрики (бот, Router, Layout Engine) должны использовать именно его,
#   а не дергать Firestore напрямую, чтобы логика статусов была одинаковой


class FirestoreClient:
    """
    FirestoreClient — обёртка вокруг Firestore для фабрики BookSoul.
    Здесь мы работаем с книгами, сценами, статусами, комментариями.
    """

    def __init__(self,
                 project_id: str = "booksoulv2",
                 credentials_path: str = "serviceAccountKey.json",
                 root_collection: str = "books"):
        # Готовим окружение для google-cloud-firestore
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.db = firestore.Client(project=project_id)
        self.root_collection = root_collection  # обычно "books"

    # ---------------------------------------------------------------------------------
    # КНИГА
    # ---------------------------------------------------------------------------------

    def create_book(
        self,
        book_id: str,
        child_name: str,
        theme: str,
        language: str = "ru",
        status: str = "draft",
        title: Optional[str] = None,
    ) -> None:
        """
        Создаёт запись о книге в коллекции books/{book_id}.
        Используется сразу после того, как пользователь в Telegram дал тему сказки.
        """
        if title is None:
            title = f"История для {child_name}"

        doc_ref = self.db.collection(self.root_collection).document(book_id)
        doc_ref.set({
            "child_name": child_name,
            "title": title,
            "theme": theme,
            "language": language,
            "status": status,  # draft / writing / drawing / styling / cover / layout / approval / ready
            "pdf_url": "",
            "cover_url": "",
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)

    def update_book_status(
        self,
        book_id: str,
        status: str,
    ) -> None:
        """
        Меняет статус книги (например 'writing' -> 'drawing' -> 'styling' ...).
        Вызывается Router-GPT после завершения этапа.
        """
        doc_ref = self.db.collection(self.root_collection).document(book_id)
        doc_ref.update({
            "status": status,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

    def attach_cover_url(
        self,
        book_id: str,
        cover_url: str,
    ) -> None:
        """
        Сохраняет ссылку на финальную обложку.
        """
        doc_ref = self.db.collection(self.root_collection).document(book_id)
        doc_ref.update({
            "cover_url": cover_url,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

    def attach_pdf_url(
        self,
        book_id: str,
        pdf_url: str,
    ) -> None:
        """
        Сохраняет ссылку на финальный PDF.
        """
        doc_ref = self.db.collection(self.root_collection).document(book_id)
        doc_ref.update({
            "pdf_url": pdf_url,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

    def get_book(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает всю инфу по книге (для Telegram: показать статус, ссылки, прогресс).
        """
        doc_ref = self.db.collection(self.root_collection).document(book_id).get()
        if not doc_ref.exists:
            return None
        data = doc_ref.to_dict()
        data["id"] = book_id
        return data

    # ---------------------------------------------------------------------------------
    # СЦЕНЫ
    # ---------------------------------------------------------------------------------

    def add_scene(
        self,
        book_id: str,
        scene_id: str,
        page_number: int,
        text: str,
        prompt_main: str,
        prompt_background: str,
        status: str = "pending",
        image_url: str = "",
    ) -> None:
        """
        Добавляет сцену (страницу книги) в подколлекцию books/{book_id}/scenes/{scene_id}.
        StoryWriter будет вызывать это для каждой сцены.
        """
        scene_ref = (
            self.db.collection(self.root_collection)
            .document(book_id)
            .collection("scenes")
            .document(scene_id)
        )
        scene_ref.set({
            "page": page_number,
            "text": text,
            "image_prompt_main": prompt_main,
            "image_prompt_background": prompt_background,
            "status": status,       # pending / approved / redo
            "image_url": image_url, # GCS URL после генерации иллюстрации
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)

    def update_scene_image_url(
        self,
        book_id: str,
        scene_id: str,
        image_url: str,
        status: Optional[str] = None,
    ) -> None:
        """
        Сохраняет ссылку на сгенерированную картинку для сцены.
        Может также обновлять статус сцены.
        """
        scene_ref = (
            self.db.collection(self.root_collection)
            .document(book_id)
            .collection("scenes")
            .document(scene_id)
        )
        payload = {
            "image_url": image_url,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if status:
            payload["status"] = status
        scene_ref.update(payload)

    def list_scenes(self, book_id: str) -> List[Dict[str, Any]]:
        """
        Возвращает список сцен книги отсортированных по page.
        Нужно Layout Engine для сборки PDF.
        """
        scenes_ref = (
            self.db.collection(self.root_collection)
            .document(book_id)
            .collection("scenes")
        )

        snapshots = scenes_ref.stream()
        scenes = []
        for snap in snapshots:
            d = snap.to_dict()
            d["id"] = snap.id
            scenes.append(d)

        # сортируем по page
        scenes.sort(key=lambda x: x.get("page", 0))
        return scenes

    # ---------------------------------------------------------------------------------
    # ОБРАТНАЯ СВЯЗЬ / КОММЕНТАРИИ
    # ---------------------------------------------------------------------------------

    def add_feedback(
        self,
        book_id: str,
        comment_text: str,
        source: str = "user",
    ) -> None:
        """
        Сохраняет комментарий (правку) от тебя.
        Это будет дублироваться и в Google Sheets.
        """
        feedback_ref = self.db.collection("feedback").document()
        feedback_ref.set({
            "book_id": book_id,
            "comment": comment_text,
            "source": source,  # user / router / style_engine / layout_engine
            "created_at": firestore.SERVER_TIMESTAMP,
        })

    # ---------------------------------------------------------------------------------
    # JOBS (таски фабрики)
    # ---------------------------------------------------------------------------------

    def create_job(
        self,
        book_id: str,
        job_type: str,
        status: str = "pending",
        result_url: str = "",
    ) -> str:
        """
        Создаёт задачу для фабрики (например 'scene_generation', 'cover', 'layout').
        Возвращает ID задачи.
        """
        job_ref = self.db.collection("jobs").document()
        job_ref.set({
            "book_id": book_id,
            "type": job_type,        # scene_generation / style_pass / cover / layout
            "status": status,        # pending / running / done / error
            "result_url": result_url,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        return job_ref.id

    def update_job_status(
        self,
        job_id: str,
        status: str,
        result_url: Optional[str] = None,
    ) -> None:
        """
        Обновляет статус задачи фабрики.
        Например когда обложка готова или PDF собран.
        """
        job_ref = self.db.collection("jobs").document(job_id)
        payload = {
            "status": status,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if result_url is not None:
            payload["result_url"] = result_url
        job_ref.update(payload)

    # ---------------------------------------------------------------------------------
    # УТИЛИТНЫЕ ШТУКИ
    # ---------------------------------------------------------------------------------

    def make_trace_id(self) -> str:
        """
        Генератор ID книги формата BKS-YYYYMMDD-HHMMSS.
        Вызывается при создании новой книги.
        """
        now = datetime.utcnow()
        return "BKS-" + now.strftime("%Y%m%d-%H%M%S")


# Быстрый линейный тест (локально)
if __name__ == "__main__":
    client = FirestoreClient(
        project_id="booksoulv2",
        credentials_path="serviceAccountKey.json",  # поменяй если у тебя другое имя
        root_collection="books",
    )

    # создаём тестовую книгу
    new_book_id = client.make_trace_id()
    client.create_book(
        book_id=new_book_id,
        child_name="Амина",
        theme="волшебный лес и луна",
        language="ru",
        status="draft",
        title="Амина и Лунный Лес",
    )

    # добавляем сцену
    client.add_scene(
        book_id=new_book_id,
        scene_id="scene_001",
        page_number=1,
        text="Амина проснулась и увидела, что её кот разговаривает человеческим голосом...",
        prompt_main="5-year-old girl in pajamas, surprised, holding talking cat",
        prompt_background="warm cozy children's bedroom, moonlight through window, magical mood",
        status="pending",
        image_url="",
    )

    print(f"Создана тестовая книга: {new_book_id}")
    print("Сцены:", client.list_scenes(new_book_id))
