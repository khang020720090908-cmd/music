import json
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, User, QuizAttempt, WrongQuestion, Bookmark, Review, ChatMessage
from utils import load_all_subjects, load_subject_by_file, BADGE_DEFINITIONS

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Trang chủ: Danh sách bộ đề, tìm kiếm, sắp xếp theo độ phổ biến/mới nhất, xem đánh giá."""
    subjects = load_all_subjects()
    search_query = request.args.get("q", "").strip().lower()
    sort_by = request.args.get("sort", "popular")  # 'popular' hoặc 'newest'

    # Thống kê số lượt làm bài và điểm đánh giá trung bình cho mỗi bộ đề
    attempt_counts = dict(
        db.session.query(QuizAttempt.subject_file, func.count(QuizAttempt.id))
        .group_by(QuizAttempt.subject_file)
        .all()
    )
    rating_stats = (
        db.session.query(
            Review.subject_file,
            func.avg(Review.rating),
            func.count(Review.id)
        )
        .group_by(Review.subject_file)
        .all()
    )
    rating_map = {r[0]: (round(float(r[1] or 0), 1), int(r[2])) for r in rating_stats}

    filtered = []
    for s in subjects:
        fname = s["filename"]
        s["attempts_count"] = attempt_counts.get(fname, 0)
        avg_r, cnt_r = rating_map.get(fname, (0.0, 0))
        s["avg_rating"] = avg_r
        s["review_count"] = cnt_r
        s["recent_reviews"] = (
            Review.query.filter_by(subject_file=fname)
            .order_by(Review.created_at.desc())
            .limit(5)
            .all()
        )
        if search_query:
            if (
                search_query not in s["subject"].lower()
                and search_query not in s["description"].lower()
                and not any(search_query in t.lower() for t in s["topics"])
            ):
                continue
        filtered.append(s)

    if sort_by == "newest":
        filtered.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        filtered.sort(key=lambda x: (x["attempts_count"], x["avg_rating"]), reverse=True)

    wrong_count = 0
    if current_user.is_authenticated:
        wrong_count = WrongQuestion.query.filter_by(user_id=current_user.id).count()

    return render_template(
        "index.html",
        subjects=filtered,
        search_query=search_query,
        sort_by=sort_by,
        wrong_count=wrong_count
    )


@main_bp.route("/leaderboard")
def leaderboard():
    """Bảng xếp hạng theo tổng XP hoặc theo từng môn, lọc theo Tuần này / Tháng này / Mọi thời gian."""
    subjects = load_all_subjects()
    selected_subject = request.args.get("subject", "all")
    period = request.args.get("period", "all")  # 'week', 'month', 'all'

    now = datetime.utcnow()
    start_time = None
    if period == "week":
        start_time = now - timedelta(days=7)
    elif period == "month":
        start_time = now - timedelta(days=30)

    # Nếu lọc theo Tất cả các môn và Mọi thời gian -> lấy trực tiếp từ User.xp
    if selected_subject == "all" and period == "all":
        users = User.query.order_by(User.xp.desc(), User.streak_days.desc()).limit(50).all()
        ranking = []
        for idx, u in enumerate(users, start=1):
            ranking.append({
                "rank": idx,
                "user": u,
                "xp": u.xp,
                "attempts": u.attempts.count(),
                "avg_score": round(
                    db.session.query(func.avg(QuizAttempt.score))
                    .filter_by(user_id=u.id)
                    .scalar() or 0.0,
                    1
                )
            })
    else:
        # Tính tổng XP kiếm được từ các lần làm bài thỏa điều kiện lọc
        q = db.session.query(
            QuizAttempt.user_id,
            func.sum(QuizAttempt.xp_earned).label("total_xp"),
            func.count(QuizAttempt.id).label("attempts_cnt"),
            func.avg(QuizAttempt.score).label("avg_score")
        )
        if selected_subject != "all":
            q = q.filter(QuizAttempt.subject_file == selected_subject)
        if start_time is not None:
            q = q.filter(QuizAttempt.created_at >= start_time)

        rows = (
            q.group_by(QuizAttempt.user_id)
            .order_by(func.sum(QuizAttempt.xp_earned).desc(), func.avg(QuizAttempt.score).desc())
            .limit(50)
            .all()
        )
        ranking = []
        for idx, r in enumerate(rows, start=1):
            u = db.session.get(User, r.user_id)
            if u:
                ranking.append({
                    "rank": idx,
                    "user": u,
                    "xp": int(r.total_xp or 0),
                    "attempts": int(r.attempts_cnt or 0),
                    "avg_score": round(float(r.avg_score or 0.0), 1)
                })

    my_rank = None
    if current_user.is_authenticated:
        for item in ranking:
            if item["user"].id == current_user.id:
                my_rank = item
                break

    return render_template(
        "leaderboard.html",
        ranking=ranking,
        subjects=subjects,
        selected_subject=selected_subject,
        period=period,
        my_rank=my_rank
    )


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Trang cá nhân: lịch sử làm bài, biểu đồ tiến bộ Chart.js, thống kê chủ đề mạnh/yếu, huy hiệu, bookmark, đổi mật khẩu."""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_profile":
            new_name = request.form.get("display_name", "").strip()
            new_avatar = request.form.get("avatar", "🎓").strip()
            new_goal = request.form.get("daily_goal", "10", type=int)
            if 2 <= len(new_name) <= 50:
                current_user.display_name = new_name
            current_user.avatar = new_avatar or "🎓"
            current_user.daily_goal = max(5, min(new_goal or 10, 200))
            db.session.commit()
            flash("Đã cập nhật hồ sơ cá nhân và mục tiêu hằng ngày!", "success")
            return redirect(url_for("main.profile"))

        elif action == "change_password":
            old_password = request.form.get("old_password", "")
            new_password = request.form.get("new_password", "").strip()
            confirm_password = request.form.get("confirm_password", "").strip()

            if not current_user.check_password(old_password):
                flash("Mật khẩu hiện tại không chính xác!", "danger")
                return redirect(url_for("main.profile"))

            if len(new_password) < 4:
                flash("Mật khẩu mới phải có ít nhất 4 ký tự!", "danger")
                return redirect(url_for("main.profile"))

            if new_password != confirm_password:
                flash("Mật khẩu xác nhận không khớp!", "danger")
                return redirect(url_for("main.profile"))

            current_user.set_password(new_password)
            db.session.commit()
            flash("Đã đổi mật khẩu thành công!", "success")
            return redirect(url_for("main.profile"))

    attempts = (
        QuizAttempt.query.filter_by(user_id=current_user.id)
        .order_by(QuizAttempt.created_at.desc())
        .limit(30)
        .all()
    )

    # Chuẩn bị dữ liệu biểu đồ tiến bộ (15 bài gần nhất theo thứ tự thời gian)
    recent_chronological = list(reversed(attempts[:15]))
    chart_labels = [a.created_at.strftime("%d/%m %H:%M") for a in recent_chronological]
    chart_scores = [round(a.score, 1) for a in recent_chronological]

    # Thống kê theo môn và theo chủ đề (điểm mạnh / điểm yếu)
    topic_stats = {}
    subject_stats = {}
    for a in attempts:
        sname = a.subject_name
        if sname not in subject_stats:
            subject_stats[sname] = {"attempts": 0, "total_score": 0.0, "correct": 0, "total": 0}
        subject_stats[sname]["attempts"] += 1
        subject_stats[sname]["total_score"] += a.score
        subject_stats[sname]["correct"] += a.correct_count
        subject_stats[sname]["total"] += a.total_count

        try:
            details = json.loads(a.details_json)
            for d in details:
                tname = f"{sname} — {d.get('topic', 'Chung')}"
                if tname not in topic_stats:
                    topic_stats[tname] = {"correct": 0, "total": 0}
                topic_stats[tname]["total"] += 1
                if d.get("is_correct"):
                    topic_stats[tname]["correct"] += 1
        except Exception:
            pass

    topic_list = []
    for tname, st in topic_stats.items():
        acc = round((st["correct"] / st["total"]) * 100, 1) if st["total"] > 0 else 0.0
        topic_list.append({
            "topic": tname,
            "correct": st["correct"],
            "total": st["total"],
            "accuracy": acc
        })
    topic_list.sort(key=lambda x: x["accuracy"], reverse=True)

    strong_topics = [t for t in topic_list if t["accuracy"] >= 70.0]
    weak_topics = [t for t in topic_list if t["accuracy"] < 70.0]

    bookmarks = (
        Bookmark.query.filter_by(user_id=current_user.id)
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    wrong_questions = (
        WrongQuestion.query.filter_by(user_id=current_user.id)
        .order_by(WrongQuestion.wrong_count.desc())
        .all()
    )
    earned_badges = {b.badge_code: b for b in current_user.badges.all()}

    return render_template(
        "profile.html",
        attempts=attempts,
        chart_labels=chart_labels,
        chart_scores=chart_scores,
        subject_stats=subject_stats,
        strong_topics=strong_topics,
        weak_topics=weak_topics,
        bookmarks=bookmarks,
        wrong_questions=wrong_questions,
        all_badges=BADGE_DEFINITIONS,
        earned_badges=earned_badges
    )


@main_bp.route("/chat")
def chat():
    """Phòng chat tổng realtime sử dụng Flask-SocketIO (hiển thị 100 tin nhắn gần nhất)."""
    messages = (
        ChatMessage.query.order_by(ChatMessage.created_at.desc())
        .limit(100)
        .all()
    )
    messages.reverse()
    return render_template("chat.html", messages=messages)
