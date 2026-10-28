import time
from datetime import datetime
from markupsafe import escape
from flask import Flask, request
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, emit

from config import Config
from models import db, User, ChatMessage
from utils import filter_profanity

from routes.auth import auth_bp
from routes.main import main_bp
from routes.quiz import quiz_bp
from routes.admin import admin_bp

csrf = CSRFProtect()
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để truy cập trang này."
login_manager.login_message_category = "warning"

# Lưu danh sách socket session_id đang kết nối và thời điểm nhắn tin gần nhất (chống spam)
ONLINE_CLIENTS = set()
LAST_MESSAGE_TIME = {}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app():
    """Khởi tạo ứng dụng Flask, cấu hình Database, Blueprints, CSRF và SocketIO."""
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        _seed_default_accounts()

    return app


def _seed_default_accounts():
    """Tạo sẵn tài khoản Admin và tài khoản Học sinh mẫu khi khởi tạo DB lần đầu."""
    # Chỉ tạo tài khoản mẫu nếu trong DB chưa có bất kỳ người dùng nào
    # (Để khi Admin xóa tài khoản hocsinh thì lần chạy sau không bị tự động tạo lại)
    if User.query.count() == 0:
        admin_user = User(
            username="admin",
            display_name="Quản trị viên",
            avatar="👑",
            role="admin",
            xp=1850,
            streak_days=12,
            daily_goal=15
        )
        admin_user.set_password("admin123")
        db.session.add(admin_user)

        student = User(
            username="hocsinh",
            display_name="Minh Anh 12A1",
            avatar="🦊",
            role="user",
            xp=680,
            streak_days=5,
            daily_goal=10
        )
        student.set_password("hocsinh123")
        db.session.add(student)
        db.session.commit()
    else:
        # Đảm bảo tài khoản admin luôn có quyền 'admin' chuẩn
        admin_user = User.query.filter_by(username="admin").first()
        if admin_user and admin_user.role != "admin":
            admin_user.role = "admin"
            db.session.commit()


# ==================== SỰ KIỆN SOCKET.IO CHO PHÒNG CHAT REALTIME ====================

@socketio.on("connect")
def handle_connect():
    ONLINE_CLIENTS.add(request.sid)
    emit("online_count", {"count": len(ONLINE_CLIENTS)}, broadcast=True)


@socketio.on("disconnect")
def handle_disconnect():
    ONLINE_CLIENTS.discard(request.sid)
    emit("online_count", {"count": len(ONLINE_CLIENTS)}, broadcast=True)


@socketio.on("send_message")
def handle_send_message(data):
    """Xử lý tin nhắn mới: kiểm tra đăng nhập, giới hạn 1 tin/giây, tối đa 300 ký tự, lọc từ xấu, giữ 100 tin."""
    if not current_user.is_authenticated:
        emit("chat_error", {"error": "Bạn cần đăng nhập để gửi tin nhắn vào phòng chat."})
        return

    now_ts = time.time()
    last_ts = LAST_MESSAGE_TIME.get(current_user.id, 0.0)
    if now_ts - last_ts < 1.0:
        emit("chat_error", {"error": "Bạn gửi tin quá nhanh! Vui lòng chờ 1 giây giữa mỗi lần gửi."})
        return

    raw_content = str((data or {}).get("content", "")).strip()
    if not raw_content:
        return
    if len(raw_content) > 300:
        emit("chat_error", {"error": "Tin nhắn không được vượt quá 300 ký tự."})
        return

    LAST_MESSAGE_TIME[current_user.id] = now_ts
    cleaned_content = filter_profanity(raw_content)
    safe_content = str(escape(cleaned_content))

    msg = ChatMessage(
        user_id=current_user.id,
        content=safe_content,
        created_at=datetime.utcnow()
    )
    db.session.add(msg)
    db.session.commit()

    # Giữ tối đa 100 tin nhắn gần nhất trong DB
    total_msgs = ChatMessage.query.count()
    if total_msgs > 100:
        old_msgs = (
            ChatMessage.query.order_by(ChatMessage.created_at.asc())
            .limit(total_msgs - 100)
            .all()
        )
        for om in old_msgs:
            db.session.delete(om)
        db.session.commit()

    emit(
        "new_message",
        {
            "id": msg.id,
            "display_name": str(escape(current_user.display_name)),
            "avatar": str(escape(current_user.avatar)),
            "role": current_user.role,
            "level_title": current_user.level_title,
            "content": safe_content,
            "timestamp": msg.created_at.strftime("%H:%M:%S %d/%m")
        },
        broadcast=True
    )


app = create_app()

if __name__ == "__main__":
    print("🚀 Khởi chạy SmartStudy tại: http://127.0.0.1:5000")
    print("🔑 Tài khoản Admin mẫu: admin / admin123")
    print("🎓 Tài khoản Học sinh mẫu: hocsinh / hocsinh123")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
