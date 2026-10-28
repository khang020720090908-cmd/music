import os
import json
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import (
    db, User, QuizAttempt, QuizSessionServer,
    WrongQuestion, Bookmark, Review, QuestionReport, ChatMessage
)
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
    """Trang quản trị: Xem thống kê người dùng, báo lỗi câu hỏi, quản lý tin chat, thêm/xóa bộ đề JSON, xóa học sinh và đổi mật khẩu."""
    total_users = User.query.count()
    total_attempts = QuizAttempt.query.count()
    reports = QuestionReport.query.order_by(QuestionReport.created_at.desc()).limit(50).all()
    chat_messages = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(50).all()
    users = User.query.order_by(User.role.asc(), User.xp.desc()).all()
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


@admin_bp.route("/delete-json/<path:filename>", methods=["POST"])
@admin_required
def delete_json(filename: str):
    """Xóa file bộ đề JSON trong /data/questions/."""
    safe_name = secure_filename(os.path.basename(filename))
    if not safe_name.endswith(".json"):
        flash("Tên file không hợp lệ, chỉ cho phép xóa file .json!", "danger")
        return redirect(url_for("admin.dashboard"))

    file_path = os.path.join(current_app.config["QUESTIONS_DIR"], safe_name)
    if not os.path.isfile(file_path):
        flash(f"Không tìm thấy bộ đề '{safe_name}' để xóa.", "warning")
        return redirect(url_for("admin.dashboard"))

    try:
        os.remove(file_path)
        # Dọn dẹp các bản ghi câu sai, bookmark liên quan tới file đề đã xóa
        WrongQuestion.query.filter_by(subject_file=safe_name).delete()
        Bookmark.query.filter_by(subject_file=safe_name).delete()
        Review.query.filter_by(subject_file=safe_name).delete()
        QuestionReport.query.filter_by(subject_file=safe_name).delete()
        db.session.commit()
        flash(f"Đã xóa bộ đề '{safe_name}' thành công!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa file JSON: {e}", "danger")

    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/user/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id: int):
    """Xóa tài khoản học sinh khỏi hệ thống."""
    user = db.session.get(User, user_id)
    if not user:
        flash("Không tìm thấy tài khoản cần xóa.", "warning")
        return redirect(url_for("admin.dashboard"))

    if user.id == current_user.id or user.role == "admin":
        flash("Không thể xóa tài khoản Quản trị viên (Admin)!", "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        uname = user.username
        dname = user.display_name
        QuizSessionServer.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        flash(f"Đã xóa tài khoản học sinh '{dname}' (@{uname}) thành công!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi xóa tài khoản: {e}", "danger")

    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/user/<int:user_id>/change-password", methods=["POST"])
@admin_required
def change_user_password(user_id: int):
    """Admin đổi mật khẩu trực tiếp cho tài khoản học sinh hoặc chính mình."""
    user = db.session.get(User, user_id)
    if not user:
        flash("Không tìm thấy tài khoản người dùng.", "warning")
        return redirect(url_for("admin.dashboard"))

    new_password = request.form.get("new_password", "").strip()
    if len(new_password) < 4:
        flash("Mật khẩu mới phải có ít nhất 4 ký tự!", "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        user.set_password(new_password)
        db.session.commit()
        flash(f"Đã cập nhật mật khẩu mới cho tài khoản '{user.display_name}' (@{user.username})!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi đổi mật khẩu: {e}", "danger")

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
