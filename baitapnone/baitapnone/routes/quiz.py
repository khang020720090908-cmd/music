import json
import uuid
import random
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import current_user, login_required
from models import (
    db, QuizSessionServer, QuizAttempt, WrongQuestion,
    Bookmark, Review, QuestionReport
)
from utils import (
    load_all_subjects, load_subject_by_file, check_short_answer,
    calculate_xp, update_user_streak_and_badges
)

quiz_bp = Blueprint("quiz", __name__, url_prefix="/quiz")


def _prepare_randomized_question(q: dict, subject_file: str) -> tuple[dict, dict]:
    """
    Xáo trộn vị trí các đáp án A/B/C/D đối với câu trắc nghiệm.
    Trả về:
      - server_q: lưu ở DB server (có chứa đáp án đúng sau khi đã xáo trộn)
      - client_q: gửi xuống trình duyệt (TUYỆT ĐỐI KHÔNG chứa trường 'answer' hay 'explanation')
    """
    q_type = q["type"]
    server_q = {
        "id": q["id"],
        "subject_file": subject_file,
        "type": q_type,
        "difficulty": q.get("difficulty", "easy"),
        "topic": q.get("topic", "Chung"),
        "question": q["question"],
        "explanation": q.get("explanation", "")
    }
    client_q = {
        "id": q["id"],
        "subject_file": subject_file,
        "type": q_type,
        "difficulty": q.get("difficulty", "easy"),
        "topic": q.get("topic", "Chung"),
        "question": q["question"]
    }

    if q_type == "multiple_choice":
        original_options = list(q["options"])
        correct_original_idx = int(q["answer"])
        # Tạo danh sách cặp (chỉ số gốc, nội dung đáp án) rồi xáo trộn ngẫu nhiên
        indexed_opts = list(enumerate(original_options))
        random.shuffle(indexed_opts)

        shuffled_options = []
        new_correct_idx = 0
        for new_idx, (orig_idx, opt_text) in enumerate(indexed_opts):
            shuffled_options.append(opt_text)
            if orig_idx == correct_original_idx:
                new_correct_idx = new_idx

        server_q["options"] = shuffled_options
        server_q["answer"] = new_correct_idx
        client_q["options"] = shuffled_options
    else:
        server_q["answer"] = q["answer"]

    return server_q, client_q


def _grade_single_question(server_q: dict, user_answer, ignore_accents: bool = False) -> tuple[bool, str, str]:
    """
    Chấm điểm 1 câu hỏi trên server.
    Trả về (is_correct, user_answer_display, correct_answer_display)
    """
    q_type = server_q["type"]
    correct_ans = server_q["answer"]

    if q_type == "multiple_choice":
        opts = server_q.get("options", [])
        letters = ["A", "B", "C", "D", "E", "F"]
        correct_disp = f"{letters[correct_ans]}. {opts[correct_ans]}" if 0 <= correct_ans < len(opts) else str(correct_ans)
        if user_answer is None or user_answer == "":
            return False, "Chưa trả lời", correct_disp
        try:
            u_idx = int(user_answer)
        except (ValueError, TypeError):
            return False, "Không hợp lệ", correct_disp
        user_disp = f"{letters[u_idx]}. {opts[u_idx]}" if 0 <= u_idx < len(opts) else str(u_idx)
        return (u_idx == correct_ans), user_disp, correct_disp

    elif q_type == "true_false":
        correct_bool = bool(correct_ans)
        correct_disp = "Đúng" if correct_bool else "Sai"
        if user_answer is None or user_answer == "":
            return False, "Chưa trả lời", correct_disp
        if isinstance(user_answer, bool):
            u_bool = user_answer
        else:
            u_bool = str(user_answer).lower() in ("true", "1", "đúng", "dung")
        user_disp = "Đúng" if u_bool else "Sai"
        return (u_bool == correct_bool), user_disp, correct_disp

    elif q_type == "short_answer":
        accepted = correct_ans if isinstance(correct_ans, list) else [str(correct_ans)]
        correct_disp = " / ".join(str(a) for a in accepted)
        if user_answer is None or str(user_answer).strip() == "":
            return False, "Chưa trả lời", correct_disp
        u_str = str(user_answer).strip()
        is_ok = check_short_answer(u_str, accepted, ignore_accents=ignore_accents)
        return is_ok, u_str, correct_disp

    return False, "Không xác định", ""


@quiz_bp.route("/setup/<path:filename>")
def setup(filename: str):
    """Trang cấu hình bộ lọc trước khi bắt đầu làm bài."""
    subject_data = load_subject_by_file(filename)
    if not subject_data:
        flash("Không tìm thấy bộ đề yêu cầu.", "danger")
        return redirect(url_for("main.index"))

    questions = subject_data.get("questions", [])
    topics = sorted(list({q.get("topic", "Chung") for q in questions if q.get("topic")}))
    reviews = (
        Review.query.filter_by(subject_file=subject_data["filename"])
        .order_by(Review.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template("quiz.html", stage="setup", subject=subject_data, topics=topics, reviews=reviews)


@quiz_bp.route("/start", methods=["POST"])
def start_quiz():
    """Khởi tạo phiên làm bài: lọc câu hỏi, RANDOM thứ tự câu và RANDOM vị trí đáp án."""
    mode = request.form.get("mode", "practice")  # 'practice', 'exam', 'wrong_review'
    ignore_accents = request.form.get("ignore_accents") == "on"

    selected_questions_raw = []
    subject_file = request.form.get("subject_file", "")
    subject_name = "Ôn tập tổng hợp"

    if mode == "wrong_review":
        if not current_user.is_authenticated:
            flash("Vui lòng đăng nhập để sử dụng chế độ Ôn câu sai.", "warning")
            return redirect(url_for("auth.login"))

        wrong_records = WrongQuestion.query.filter_by(user_id=current_user.id).all()
        if not wrong_records:
            flash("Tuyệt vời! Bạn hiện không có câu hỏi nào trong danh sách làm sai.", "success")
            return redirect(url_for("main.index"))

        all_subjects = {s["filename"]: s for s in load_all_subjects()}
        for wr in wrong_records:
            s_data = all_subjects.get(wr.subject_file)
            if not s_data:
                continue
            for q in s_data.get("questions", []):
                if q["id"] == wr.question_id:
                    q_copy = dict(q)
                    q_copy["_subject_file"] = wr.subject_file
                    selected_questions_raw.append(q_copy)
                    break

        subject_file = "wrong_review"
        subject_name = "Ôn tập các câu từng làm sai"
    else:
        subject_data = load_subject_by_file(subject_file)
        if not subject_data:
            flash("Bộ đề không tồn tại.", "danger")
            return redirect(url_for("main.index"))

        subject_name = subject_data.get("subject", subject_file)
        pool = list(subject_data.get("questions", []))

        difficulty = request.form.get("difficulty", "all")
        q_type = request.form.get("q_type", "all")
        topic = request.form.get("topic", "all")
        num_questions_str = request.form.get("num_questions", "all")

        if difficulty != "all":
            pool = [q for q in pool if q.get("difficulty") == difficulty]
        if q_type != "all":
            pool = [q for q in pool if q.get("type") == q_type]
        if topic != "all":
            pool = [q for q in pool if q.get("topic") == topic]

        if not pool:
            flash("Không có câu hỏi nào khớp với bộ lọc bạn chọn. Hãy thử mở rộng điều kiện lọc!", "warning")
            return redirect(url_for("quiz.setup", filename=subject_file))

        # Xáo trộn ngẫu nhiên thứ tự câu hỏi
        random.shuffle(pool)

        if num_questions_str != "all":
            try:
                limit_n = int(num_questions_str)
                pool = pool[:limit_n]
            except ValueError:
                pass

        for q in pool:
            q_copy = dict(q)
            q_copy["_subject_file"] = subject_file
            selected_questions_raw.append(q_copy)

    if not selected_questions_raw:
        flash("Không tìm thấy câu hỏi phù hợp để bắt đầu.", "warning")
        return redirect(url_for("main.index"))

    random.shuffle(selected_questions_raw)

    server_questions = []
    client_questions = []
    for q in selected_questions_raw:
        s_file = q.get("_subject_file", subject_file)
        sq, cq = _prepare_randomized_question(q, s_file)
        server_questions.append(sq)
        client_questions.append(cq)

    # Thời gian thi thử: mặc định 45 giây / câu (tối thiểu 3 phút)
    time_limit_seconds = max(len(server_questions) * 45, 180)
    session_id = uuid.uuid4().hex

    quiz_session = QuizSessionServer(
        id=session_id,
        user_id=current_user.id if current_user.is_authenticated else None,
        subject_file=subject_file,
        subject_name=subject_name,
        mode=mode,
        ignore_accents=ignore_accents,
        time_limit_seconds=time_limit_seconds,
        payload_json=json.dumps(server_questions, ensure_ascii=False),
        completed=False
    )
    db.session.add(quiz_session)
    db.session.commit()

    bookmarked_ids = set()
    if current_user.is_authenticated:
        bms = Bookmark.query.filter_by(user_id=current_user.id).all()
        bookmarked_ids = {b.question_id for b in bms}

    return render_template(
        "quiz.html",
        stage="doing",
        quiz_session=quiz_session,
        client_questions=client_questions,
        bookmarked_ids=list(bookmarked_ids)
    )


@quiz_bp.route("/api/check-question", methods=["POST"])
def api_check_question():
    """
    API chấm điểm tức thì từng câu ở chế độ Luyện tập (Practice) hoặc Ôn câu sai.
    Ở chế độ Thi thử (Exam), API này từ chối tiết lộ đáp án để chống gian lận.
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    question_id = data.get("question_id", "")
    user_answer = data.get("answer")

    qs = db.session.get(QuizSessionServer, session_id)
    if not qs:
        return jsonify({"ok": False, "error": "Phiên làm bài không hợp lệ."}), 404

    if qs.mode == "exam":
        return jsonify({"ok": False, "error": "Chế độ Thi thử chỉ công bố đáp án sau khi nộp bài."}), 403

    server_questions = json.loads(qs.payload_json)
    target_q = next((q for q in server_questions if q["id"] == question_id), None)
    if not target_q:
        return jsonify({"ok": False, "error": "Không tìm thấy câu hỏi."}), 404

    is_correct, user_disp, correct_disp = _grade_single_question(
        target_q, user_answer, ignore_accents=qs.ignore_accents
    )

    return jsonify({
        "ok": True,
        "is_correct": is_correct,
        "user_answer_display": user_disp,
        "correct_answer_display": correct_disp,
        "correct_raw": target_q["answer"],
        "explanation": target_q.get("explanation", "")
    })


@quiz_bp.route("/submit/<session_id>", methods=["POST"])
def submit_quiz(session_id: str):
    """Nộp bài làm, chấm toàn bộ trên server, tính XP, cập nhật Streak, Huy hiệu và Câu sai."""
    qs = db.session.get(QuizSessionServer, session_id)
    if not qs:
        flash("Không tìm thấy phiên làm bài.", "danger")
        return redirect(url_for("main.index"))

    answers_json_str = request.form.get("answers_json", "{}")
    time_taken = request.form.get("time_taken", 0, type=int)
    try:
        user_answers_map = json.loads(answers_json_str)
    except Exception:
        user_answers_map = {}

    server_questions = json.loads(qs.payload_json)
    graded_details = []
    correct_count = 0

    for sq in server_questions:
        qid = sq["id"]
        u_ans = user_answers_map.get(qid)
        is_ok, u_disp, c_disp = _grade_single_question(sq, u_ans, ignore_accents=qs.ignore_accents)
        if is_ok:
            correct_count += 1

        graded_details.append({
            "id": qid,
            "subject_file": sq.get("subject_file", qs.subject_file),
            "type": sq["type"],
            "difficulty": sq.get("difficulty", "easy"),
            "topic": sq.get("topic", "Chung"),
            "question": sq["question"],
            "options": sq.get("options", []),
            "is_correct": is_ok,
            "user_answer_display": u_disp,
            "correct_answer_display": c_disp,
            "explanation": sq.get("explanation", "")
        })

        # Cập nhật bảng WrongQuestion (Spaced Repetition đơn giản) nếu người dùng đã đăng nhập
        if current_user.is_authenticated and not qs.completed:
            s_file = sq.get("subject_file", qs.subject_file)
            wq = WrongQuestion.query.filter_by(
                user_id=current_user.id,
                subject_file=s_file,
                question_id=qid
            ).first()
            if not is_ok:
                if not wq:
                    wq = WrongQuestion(
                        user_id=current_user.id,
                        subject_file=s_file,
                        question_id=qid,
                        wrong_count=1,
                        correct_streak=0
                    )
                    db.session.add(wq)
                else:
                    wq.wrong_count += 1
                    wq.correct_streak = 0
                    wq.last_wrong_at = datetime.utcnow()
            else:
                if wq:
                    wq.correct_streak += 1
                    if wq.correct_streak >= 2 or qs.mode == "wrong_review":
                        db.session.delete(wq)

    total_count = len(server_questions)
    score_percent = round((correct_count / max(total_count, 1)) * 100.0, 1)
    xp_earned = 0
    new_badges = []

    if current_user.is_authenticated and not qs.completed:
        xp_earned = calculate_xp(graded_details, time_taken, current_user.streak_days)
        current_user.xp = (current_user.xp or 0) + xp_earned
        new_badges = update_user_streak_and_badges(
            current_user,
            answered_count=total_count,
            score_percent=score_percent,
            total_quiz_questions=total_count
        )

        attempt = QuizAttempt(
            user_id=current_user.id,
            subject_file=qs.subject_file,
            subject_name=qs.subject_name,
            mode=qs.mode,
            score=score_percent,
            correct_count=correct_count,
            total_count=total_count,
            time_taken=max(time_taken, 1),
            xp_earned=xp_earned,
            details_json=json.dumps(graded_details, ensure_ascii=False)
        )
        db.session.add(attempt)
        qs.completed = True
        db.session.commit()
    else:
        qs.completed = True
        db.session.commit()

    return render_template(
        "result.html",
        quiz_session=qs,
        score=score_percent,
        correct_count=correct_count,
        total_count=total_count,
        time_taken=max(time_taken, 1),
        xp_earned=xp_earned,
        new_badges=new_badges,
        details=graded_details
    )


@quiz_bp.route("/attempt/<int:attempt_id>")
@login_required
def view_attempt(attempt_id: int):
    """Xem lại chi tiết một bài làm trong lịch sử."""
    attempt = db.session.get(QuizAttempt, attempt_id)
    if not attempt or attempt.user_id != current_user.id:
        flash("Không tìm thấy lịch sử bài làm này.", "danger")
        return redirect(url_for("main.profile"))

    details = json.loads(attempt.details_json)
    return render_template(
        "result.html",
        quiz_session=attempt,
        score=attempt.score,
        correct_count=attempt.correct_count,
        total_count=attempt.total_count,
        time_taken=attempt.time_taken,
        xp_earned=attempt.xp_earned,
        new_badges=[],
        details=details
    )


@quiz_bp.route("/api/bookmark", methods=["POST"])
@login_required
def api_toggle_bookmark():
    """API thêm hoặc bỏ lưu câu hỏi yêu thích (Bookmark)."""
    data = request.get_json(silent=True) or {}
    subject_file = data.get("subject_file", "").strip()
    question_id = data.get("question_id", "").strip()
    question_text = data.get("question_text", "").strip()
    topic = data.get("topic", "").strip()

    if not question_id:
        return jsonify({"ok": False, "error": "Thiếu mã câu hỏi."}), 400

    existing = Bookmark.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"ok": True, "bookmarked": False, "message": "Đã bỏ lưu câu hỏi."})

    # Tìm giải thích từ file JSON nếu có
    explanation = ""
    s_data = load_subject_by_file(subject_file)
    if s_data:
        for q in s_data.get("questions", []):
            if q["id"] == question_id:
                explanation = q.get("explanation", "")
                if not question_text:
                    question_text = q.get("question", "")
                break

    bm = Bookmark(
        user_id=current_user.id,
        subject_file=subject_file or "unknown.json",
        question_id=question_id,
        question_text=question_text or "Câu hỏi đã lưu",
        topic=topic,
        explanation=explanation
    )
    db.session.add(bm)
    db.session.commit()
    return jsonify({"ok": True, "bookmarked": True, "message": "Đã lưu vào danh sách câu hỏi yêu thích!"})


@quiz_bp.route("/api/report-question", methods=["POST"])
def api_report_question():
    """API báo lỗi câu hỏi (sai đáp án, sai chính tả...) ngay trên từng câu."""
    data = request.get_json(silent=True) or {}
    subject_file = data.get("subject_file", "").strip()
    question_id = data.get("question_id", "").strip()
    reason = data.get("reason", "").strip()

    if not question_id or not reason:
        return jsonify({"ok": False, "error": "Vui lòng nhập nội dung mô tả lỗi."}), 400

    rep = QuestionReport(
        user_id=current_user.id if current_user.is_authenticated else None,
        subject_file=subject_file or "unknown.json",
        question_id=question_id,
        reason=reason[:500]
    )
    db.session.add(rep)
    db.session.commit()
    return jsonify({"ok": True, "message": "Cảm ơn bạn! Báo cáo lỗi đã được gửi tới Quản trị viên."})


@quiz_bp.route("/review/<path:subject_file>", methods=["POST"])
@login_required
def submit_review(subject_file: str):
    """Gửi đánh giá 1-5 sao và bình luận sau khi làm xong bộ đề."""
    rating = request.form.get("rating", 5, type=int)
    comment = request.form.get("comment", "").strip()
    rating = max(1, min(rating, 5))

    if not comment:
        flash("Vui lòng nhập nội dung nhận xét cho bộ đề.", "warning")
        return redirect(url_for("main.index"))

    rev = Review(
        user_id=current_user.id,
        subject_file=subject_file,
        rating=rating,
        comment=comment[:500]
    )
    db.session.add(rev)
    db.session.commit()
    flash("Cảm ơn bạn đã gửi đánh giá cho bộ đề!", "success")
    return redirect(url_for("main.index"))
