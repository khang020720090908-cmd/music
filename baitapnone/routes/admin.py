import os
import json
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User, QuizAttempt, QuestionReport, ChatMessage
from utils import validate_question_json, load_all_subjects

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Decorator kiểm tra quyền Admin."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != "admin":
            flash("Khu vực này chỉ dành cho Quản trị viên (Admin).", "danger")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route("/")
@admin_required
def dashboard():
    """Trang quản trị: Xem thống kê người dùng, báo lỗi câu hỏi, quản lý tin chat, upload bộ đề JSON."""
    total_users = User.query.count()
    total_attempts = QuizAttempt.query.count()
    reports = QuestionReport.query.order_by(QuestionReport.created_at.desc()).limit(50).all()
    chat_messages = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(50).all()
    users = User.query.order_by(User.xp.desc()).limit(30).all()
    subjects = load_all_subjects()

    return render_template(
        "admin.html",
        total_users=total_users,
        total_attempts=total_attempts,
        reports=reports,
        chat_messages=chat_messages,
        users=users,
        subjects=subjects
    )


@admin_bp.route("/upload-json", methods=["POST"])
@admin_required
def upload_json():
    """Upload và kiểm tra cấu trúc file JSON bộ đề mới trước khi lưu vào /data/questions/."""
    file = request.files.get("json_file")
    if not file or not file.filename:
        flash("Vui lòng chọn một file .json để tải lên.", "warning")
        return redirect(url_for("admin.dashboard"))

    filename = secure_filename(file.filename)
    if not filename.endswith(".json"):
        flash("Chỉ chấp nhận định dạng file .json!", "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        raw_content = file.read().decode("utf-8")
        parsed_data = json.loads(raw_content)
    except Exception as e:
        flash(f"File không đúng cú pháp JSON UTF-8: {e}", "danger")
        return redirect(url_for("admin.dashboard"))

    is_valid, msg = validate_question_json(parsed_data)
    if not is_valid:
        flash(f"Cấu trúc JSON không hợp lệ: {msg}", "danger")
        return redirect(url_for("admin.dashboard"))

    save_path = os.path.join(current_app.config["QUESTIONS_DIR"], filename)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, ensure_ascii=False, indent=2)

    flash(f"Đã kiểm tra và lưu thành công bộ đề '{parsed_data['subject']}' ({len(parsed_data['questions'])} câu)!", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/report/<int:report_id>/resolve", methods=["POST"])
@admin_required
def resolve_report(report_id: int):
    """Đánh dấu báo cáo lỗi câu hỏi là đã xử lý."""
    rep = db.session.get(QuestionReport, report_id)
    if rep:
        rep.status = "resolved"
        db.session.commit()
        flash(f"Đã đánh dấu xử lý báo lỗi #{report_id}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/chat/<int:msg_id>/delete", methods=["POST"])
@admin_required
def delete_chat_message(msg_id: int):
    """Xóa tin nhắn chat vi phạm."""
    msg = db.session.get(ChatMessage, msg_id)
    if msg:
        db.session.delete(msg)
        db.session.commit()
        flash("Đã xóa tin nhắn vi phạm.", "info")
    return redirect(url_for("admin.dashboard"))
