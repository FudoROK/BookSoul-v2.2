import os
from google.cloud import firestore

# 1. Указываем путь к ключу сервис-аккаунта, чтобы авторизоваться в GCP
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "booksoulv2-81b8c3368966.json"
os.environ["GOOGLE_CLOUD_PROJECT"] = "booksoulv2"


def init_firestore_structure():
    db = firestore.Client()

    # --- books ---
    books_ref = db.collection("books").document("example_book")
    books_ref.set({
        "title": "Приключения Лейлы и кота Мурзика",
        "theme": "дружба, волшебство",
        "status": "draft",  # draft / writing / images / styling / cover / layout / done
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "pdf_url": "",
        "cover_url": "",
        "child_name": "Лейла",
        "language": "ru"
    })

    # Подколлекция сцен для этой книги (пример страницы сказки)
    scene_ref = books_ref.collection("scenes").document("scene_001")
    scene_ref.set({
        "page": 1,
        "text": "Лейла проснулась в лунном саду. Вокруг ходил кот с золотыми усами.",
        "image_prompt_main": "девочка лет 5-6 с длинными тёмными волосами, в пижаме, рядом магический кот",
        "image_prompt_background": "ночной сад, мягкий лунный свет, фиолетовые листья, свечение травы",
        "image_url": "",
        "status": "pending"  # pending / approved / redo
    })

    # --- jobs ---
    jobs_ref = db.collection("jobs").document("example_job")
    jobs_ref.set({
        "type": "scene_generation",   # scene_generation / style_pass / layout / cover
        "status": "pending",          # pending / running / done / error
        "book_id": "example_book",
        "result_url": "",
        "created_at": firestore.SERVER_TIMESTAMP,
    })

    # --- covers ---
    covers_ref = db.collection("covers").document("example_cover")
    covers_ref.set({
        "book_id": "example_book",
        "prompt": "Обложка детской книги. Лейла и золотой кот стоят вместе, мягкий тёплый свет, сказочная энергия, крупный заголовок.",
        "image_url": "",
        "status": "awaiting_approval"  # awaiting_approval / approved / redo
    })

    # --- feedback ---
    feedback_ref = db.collection("feedback").document("example_feedback")
    feedback_ref.set({
        "book_id": "example_book",
        "comment": "Обложка хорошая, но хочу больше света на лице ребёнка.",
        "created_at": firestore.SERVER_TIMESTAMP,
        "source": "user",  # user / router / style_engine
    })

    # --- users ---
    users_ref = db.collection("users").document("admin_user")
    users_ref.set({
        "role": "admin",
        "name": "Фудо",
        "telegram_id": "",
        "joined_at": firestore.SERVER_TIMESTAMP,
        "active": True
    })

    print("✅ Firestore и стартовые коллекции инициализированы.")


if __name__ == "__main__":
    init_firestore_structure()
