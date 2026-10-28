from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

AVATAR_CHOICES = ["🎓", "🦊", "🐼", "🚀", "🌟", "🐱", "🦉", "⚡", "🍀", "🐉"]


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Trang đăng ký tài khoản mới."""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        avatar = request.form.get("avatar", "🎓").strip()

        if avatar not in AVATAR_CHOICES:
            avatar = "🎓"

        if len(username) < 3 or len(username) > 30 or not username.isalnum():
            flash("Tên đăng nhập phải từ 3–30 ký tự và chỉ gồm chữ cái hoặc chữ số.", "danger")
            return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)

        if len(display_name) < 2 or len(display_name) > 50:
            flash("Tên hiển thị phải từ 2–50 ký tự.", "danger")
            return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)

        if len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)

        if password != confirm_password:
            flash("Mật khẩu xác nhận không khớp.", "danger")
            return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash("Tên đăng nhập này đã được sử dụng. Vui lòng chọn tên khác.", "danger")
            return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)

        new_user = User(
            username=username,
            display_name=display_name,
            avatar=avatar,
            role="user"
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash(f"Chào mừng {new_user.display_name} gia nhập SmartStudy!", "success")
        return redirect(url_for("main.index"))

    return render_template("auth.html", mode="register", avatars=AVATAR_CHOICES)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Trang đăng nhập tài khoản."""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("Tên đăng nhập hoặc mật khẩu không chính xác.", "danger")
            return render_template("auth.html", mode="login", avatars=AVATAR_CHOICES)

        login_user(user, remember=True)
        flash(f"Chào mừng trở lại, {user.display_name}!", "success")
        next_page = request.args.get("next")
        return redirect(next_page or url_for("main.index"))

    return render_template("auth.html", mode="login", avatars=AVATAR_CHOICES)


@auth_bp.route("/logout")
@login_required
def logout():
    """Đăng xuất khỏi hệ thống."""
    logout_user()
    flash("Bạn đã đăng xuất thành công.", "info")
    return redirect(url_for("main.index"))
