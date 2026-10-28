from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """Model người dùng lưu thông tin tài khoản, XP, streak và quyền hạn."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(120), default="🎓")
    role = db.Column(db.String(20), default="user")  # 'user' hoặc 'admin'
    xp = db.Column(db.Integer, default=0)
    streak_days = db.Column(db.Integer, default=0)
    last_study_date = db.Column(db.Date, nullable=True)
    daily_goal = db.Column(db.Integer, default=10)
    questions_done_today = db.Column(db.Integer, default=0)
    total_questions_answered = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attempts = db.relationship("QuizAttempt", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    wrong_questions = db.relationship("WrongQuestion", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    bookmarks = db.relationship("Bookmark", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    badges = db.relationship("UserBadge", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    reviews = db.relationship("Review", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    reports = db.relationship("QuestionReport", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    messages = db.relationship("ChatMessage", backref="user", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def level_title(self) -> str:
        """Tính danh hiệu Cấp bậc (Level) theo XP."""
        if self.xp >= 3000:
            return "Huyền thoại 🏆"
        elif self.xp >= 1500:
            return "Cao thủ 💎"
        elif self.xp >= 600:
            return "Học giả 📘"
        elif self.xp >= 200:
            return "Chăm chỉ 🌱"
        return "Tân binh 🐣"

    @property
    def next_level_xp(self) -> int:
        if self.xp < 200:
            return 200
        elif self.xp < 600:
            return 600
        elif self.xp < 1500:
            return 1500
        elif self.xp < 3000:
            return 3000
        return 5000


class QuizSessionServer(db.Model):
    """Lưu phiên làm bài trên server để chống lộ đáp án xuống client."""
    __tablename__ = "quiz_sessions_server"

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    subject_file = db.Column(db.String(100), nullable=False)
    subject_name = db.Column(db.String(120), nullable=False)
    mode = db.Column(db.String(30), default="practice")  # 'practice', 'exam', 'wrong_review'
    ignore_accents = db.Column(db.Boolean, default=False)
    time_limit_seconds = db.Column(db.Integer, default=900)
    payload_json = db.Column(db.Text, nullable=False)  # Chứa danh sách câu hỏi đã trộn & đáp án chuẩn
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False)


class QuizAttempt(db.Model):
    """Lịch sử kết quả mỗi lần hoàn thành bài làm."""
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_file = db.Column(db.String(100), nullable=False, index=True)
    subject_name = db.Column(db.String(120), nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    score = db.Column(db.Float, nullable=False)  # Điểm hệ 100
    correct_count = db.Column(db.Integer, nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    time_taken = db.Column(db.Integer, nullable=False)  # Giây
    xp_earned = db.Column(db.Integer, default=0)
    details_json = db.Column(db.Text, nullable=False)  # Chi tiết từng câu để xem lại
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class WrongQuestion(db.Model):
    """Lưu các câu người dùng làm sai để ôn tập lại (Spaced Repetition đơn giản)."""
    __tablename__ = "wrong_questions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_file = db.Column(db.String(100), nullable=False)
    question_id = db.Column(db.String(80), nullable=False)
    wrong_count = db.Column(db.Integer, default=1)
    correct_streak = db.Column(db.Integer, default=0)  # Đúng liên tiếp 2 lần sẽ xóa khỏi danh sách sai
    last_wrong_at = db.Column(db.DateTime, default=datetime.utcnow)


class Bookmark(db.Model):
    """Lưu câu hỏi yêu thích (Bookmark) của người dùng."""
    __tablename__ = "bookmarks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_file = db.Column(db.String(100), nullable=False)
    question_id = db.Column(db.String(80), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    topic = db.Column(db.String(120), default="")
    explanation = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserBadge(db.Model):
    """Lưu huy hiệu thành tích người dùng đạt được."""
    __tablename__ = "user_badges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    badge_code = db.Column(db.String(50), nullable=False)
    badge_name = db.Column(db.String(100), nullable=False)
    badge_icon = db.Column(db.String(30), nullable=False)
    badge_desc = db.Column(db.String(255), nullable=False)
    awarded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Review(db.Model):
    """Đánh giá 1-5 sao và bình luận cho từng bộ đề."""
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_file = db.Column(db.String(100), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuestionReport(db.Model):
    """Báo lỗi câu hỏi từ người dùng gửi cho Admin."""
    __tablename__ = "question_reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    subject_file = db.Column(db.String(100), nullable=False)
    question_id = db.Column(db.String(80), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(30), default="pending")  # 'pending', 'resolved'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    """Lưu lịch sử tin nhắn phòng chat chung (giữ tối đa 100 tin gần nhất)."""
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
