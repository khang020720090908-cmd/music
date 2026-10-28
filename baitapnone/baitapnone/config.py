import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Cấu hình ứng dụng Flask Học Tập SmartStudy."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "smartstudy-super-secret-key-2026-vn")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'smartstudy.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    QUESTIONS_DIR = os.path.join(BASE_DIR, "data", "questions")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # Giới hạn upload JSON tối đa 5MB
    WTF_CSRF_ENABLED = True
