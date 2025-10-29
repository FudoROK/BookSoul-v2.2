# 📚 BookSoul Factory v2.2

### 🧩 Описание
**BookSoul** — это интеллектуальная мини-фабрика, создающая персональные детские книги по фотографии ребёнка.  
Система полностью автоматизирует процесс от идеи до готового печатного PDF, сохраняя возможность ручного контроля на каждом этапе.  
Всё управление — через Telegram-бота, а производство — в облаке Google Cloud (Firestore, GCS, Sheets).

---

### ⚙️ Архитектура проекта

```
booksoul_factory/
  ├── src/
  │   ├── router/              # Главный мозг фабрики (GPT-Router)
  │   ├── storywriter/         # Сценарный цех (тексты и сцены)
  │   ├── scene_builder/       # Художественный цех (Nano Banana / Gemini Image)
  │   ├── style_engine/        # Стилистический контроль (цвет, свет, стиль)
  │   ├── cover_builder/       # Новый цех: создание и оформление обложки книги
  │   ├── layout_engine/       # Вёрстка и PDF (Slides + ReportLab)
  │   ├── telegram_interface/  # Управление и обратная связь через Telegram
  │   ├── data_layer/          # Firestore, GCS, Sheets
  │   ├── utils/               # Логирование и утилиты
  │   └── main.py              # Точка входа проекта
  ├── requirements.txt
  ├── .env.example
  ├── .gitignore
  ├── LICENSE
  └── README.md
```

---

### 🏭 Цепочка фабрики BookSoul

1. **StoryWriter** — пишет сказку по теме, делит на сцены, создаёт описания и промты.  
2. **SceneBuilder** — визуализирует сцены через Nano Banana (Gemini 2.5 Image).  
3. **Style Engine** — приводит все картинки к единому стилю и тону.  
4. **Cover Builder** — создаёт и оформляет обложку книги (герой, фон, заголовок).  
5. **Layout Engine** — собирает книгу, формирует печатный PDF-файл (A5, 300 DPI).  
6. **Telegram Interface** — обеспечивает удобное управление и комментарии.  
7. **Data Layer** — связывает всё с Firestore, Google Sheets и GCS.  
8. **Router** — главный управляющий процессом, распределяет задачи и следит за статусами.

---

### 🔧 Технологический стек

| Компонент | Назначение |
|------------|-------------|
| **FastAPI** | API-сервер фабрики |
| **aiogram** | Телеграм-бот (интерфейс пользователя) |
| **OpenAI / Gemini** | Генерация текстов и изображений |
| **Google Cloud Firestore** | Хранилище данных и статусов |
| **Google Cloud Storage** | Хранилище изображений и PDF |
| **Google Sheets API** | Журнал стадий и комментариев |
| **ReportLab** | Создание финального печатного PDF |
| **Pillow / OpenCV** | Обработка изображений (Style Engine) |
| **python-dotenv** | Работа с переменными окружения |

---

### 🚀 Установка

```bash
pip install -r requirements.txt
```

---

### ▶️ Запуск

```bash
python src/main.py
```

---

### 🔑 Переменные окружения

Создай файл `.env` на основе шаблона `.env.example`:

```
TELEGRAM_BOT_TOKEN=
OPENAI_API_KEY=
GEMINI_API_KEY=
GOOGLE_PROJECT_ID=booksoul-factory
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
GCS_BUCKET=booksoul-bucket
FIRESTORE_COLLECTION=books
SHEETS_ID=
REPORTLAB_FONT=HeiseiMin-W3
```

---

### 📂 Основные директории

| Папка | Описание |
|-------|-----------|
| `router/` | Мозг фабрики, управляет всеми отделами |
| `storywriter/` | Генерация текста и сцен |
| `scene_builder/` | Создание изображений (Nano Banana) |
| `style_engine/` | Стилистическое выравнивание |
| `cover_builder/` | Генерация и оформление обложки |
| `layout_engine/` | Вёрстка книги и экспорт PDF |
| `telegram_interface/` | Работа с пользователем |
| `data_layer/` | Связь с Firestore, Sheets, GCS |
| `utils/` | Вспомогательные функции и логирование |

---

### 📘 Лицензия
MIT License © 2025 **Soul Factory**

---

### 💡 Идея
BookSoul — это не просто генератор книг.  
Это твой персональный книжный завод: ты загружаешь фото и идею, а система превращает это в сказку, иллюстрации и готовую печатную книгу.  
**ИИ, которая дарит людям самый большой актив — время.**
