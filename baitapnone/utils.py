import os
import re
import json
import unicodedata
from datetime import date, timedelta
from flask import current_app
from models import db, User, UserBadge

BAD_WORDS = [
    "dm", "dcm", "vcl", "vl", "cc", "ngu", "chửi", "đồ ngu", "fuck", "shit", "bitch"
]

BADGE_DEFINITIONS = [
    {
        "code": "first_quiz",
        "name": "Khởi đầu vững chắc",
        "icon": "🚀",
        "desc": "Hoàn thành bài ôn tập đầu tiên trên hệ thống."
    },
    {
        "code": "perfect_100",
        "name": "Tuyệt đối 100%",
        "icon": "🎯",
        "desc": "Đạt điểm tuyệt đối 100% trong một bài làm (tối thiểu 5 câu)."
    },
    {
        "code": "questions_100",
        "name": "Chiến binh 100 câu",
        "icon": "📚",
        "desc": "Đã trả lời tổng cộng từ 100 câu hỏi trở lên."
    },
    {
        "code": "streak_7",
        "name": "Chuỗi 7 ngày bền bỉ",
        "icon": "🔥",
        "desc": "Duy trì chuỗi học tập liên tiếp 7 ngày không nghỉ."
    },
    {
        "code": "xp_1000",
        "name": "Bậc thầy tri thức",
        "icon": "👑",
        "desc": "Cán mốc 1.000 điểm kinh nghiệm (XP)."
    }
]


def remove_vietnamese_accents(text: str) -> str:
    """Chuyển chuỗi tiếng Việt có dấu thành không dấu."""
    if not text:
        return ""
    text = re.sub(r"[đĐ]", lambda m: "d" if m.group(0) == "đ" else "D", text)
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize_short_answer(text: str, ignore_accents: bool = False) -> str:
    """
    Chuẩn hóa câu trả lời ngắn:
    - Chuyển về chữ thường
    - Bỏ dấu câu (.,;!?"'()-[]{})
    - Bỏ khoảng trắng thừa
    - Tùy chọn bỏ dấu tiếng Việt
    """
    if text is None:
        return ""
    s = str(text).strip().lower()
    if ignore_accents:
        s = remove_vietnamese_accents(s).lower()
    # Bỏ dấu câu, chỉ giữ chữ cái, chữ số và khoảng trắng
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    # Gộp nhiều khoảng trắng liên tiếp thành 1 khoảng trắng
    s = re.sub(r"\s+", " ", s).strip()
    return s


def check_short_answer(user_ans: str, accepted_answers: list, ignore_accents: bool = False) -> bool:
    """Kiểm tra câu trả lời ngắn của người dùng với danh sách đáp án chấp nhận."""
    norm_user = normalize_short_answer(user_ans, ignore_accents=ignore_accents)
    if not norm_user:
        return False
    for ans in accepted_answers:
        norm_target = normalize_short_answer(str(ans), ignore_accents=ignore_accents)
        if norm_user == norm_target:
            return True
    return False


def filter_profanity(text: str) -> str:
    """Lọc từ ngữ xấu cơ bản trong tin nhắn chat."""
    if not text:
        return ""
    result = text
    for word in BAD_WORDS:
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        result = pattern.sub("***", result)
    return result


def validate_question_json(data: dict) -> tuple[bool, str]:
    """Kiểm tra cấu trúc hợp lệ của file JSON bộ đề trước khi lưu."""
    if not isinstance(data, dict):
        return False, "Dữ liệu gốc phải là một JSON Object."
    if "subject" not in data or not isinstance(data["subject"], str) or not data["subject"].strip():
        return False, "Thiếu trường 'subject' (tên môn học/bộ đề)."
    if "description" not in data or not isinstance(data["description"], str):
        return False, "Thiếu trường 'description' (mô tả bộ đề)."
    if "questions" not in data or not isinstance(data["questions"], list) or len(data["questions"]) == 0:
        return False, "Trường 'questions' phải là danh sách có ít nhất 1 câu hỏi."

    seen_ids = set()
    for idx, q in enumerate(data["questions"], start=1):
        if not isinstance(q, dict):
            return False, f"Câu hỏi thứ {idx} không phải là Object."
        for req_key in ("id", "type", "difficulty", "topic", "question", "answer", "explanation"):
            if req_key not in q:
                return False, f"Câu số {idx} thiếu trường bắt buộc '{req_key}'."
        qid = str(q["id"]).strip()
        if not qid or qid in seen_ids:
            return False, f"Câu số {idx} có 'id' rỗng hoặc bị trùng lặp ('{qid}')."
        seen_ids.add(qid)

        qtype = q["type"]
        if qtype not in ("multiple_choice", "true_false", "short_answer"):
            return False, f"Câu '{qid}' có type không hợp lệ ('{qtype}')."
        if q["difficulty"] not in ("easy", "medium", "hard"):
            return False, f"Câu '{qid}' có difficulty không hợp lệ (chỉ nhận easy/medium/hard)."

        if qtype == "multiple_choice":
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                return False, f"Câu trắc nghiệm '{qid}' cần danh sách 'options' tối thiểu 2 lựa chọn."
            if not isinstance(q["answer"], int) or not (0 <= q["answer"] < len(opts)):
                return False, f"Câu trắc nghiệm '{qid}' có 'answer' phải là chỉ số nguyên từ 0 đến {len(opts)-1}."
        elif qtype == "true_false":
            if not isinstance(q["answer"], bool):
                return False, f"Câu đúng/sai '{qid}' phải có 'answer' kiểu boolean (true/false)."
        elif qtype == "short_answer":
            if not isinstance(q["answer"], list) or len(q["answer"]) == 0:
                return False, f"Câu trả lời ngắn '{qid}' phải có 'answer' là mảng chứa ít nhất 1 đáp án."

    return True, "Hợp lệ"


def load_all_subjects() -> list[dict]:
    """Đọc toàn bộ danh sách các file JSON bộ đề trong thư mục /data/questions/."""
    q_dir = current_app.config["QUESTIONS_DIR"]
    os.makedirs(q_dir, exist_ok=True)
    subjects = []
    for fname in sorted(os.listdir(q_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(q_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            questions = data.get("questions", [])
            topics = sorted(list({q.get("topic", "Chung") for q in questions if q.get("topic")}))
            mtime = os.path.getmtime(fpath)
            subjects.append({
                "filename": fname,
                "subject": data.get("subject", fname.replace(".json", "")),
                "description": data.get("description", ""),
                "question_count": len(questions),
                "topics": topics,
                "mtime": mtime,
                "questions": questions
            })
        except Exception:
            continue
    return subjects


def load_subject_by_file(filename: str) -> dict | None:
    """Đọc chi tiết 1 bộ đề JSON theo tên file."""
    safe_name = os.path.basename(filename)
    q_dir = current_app.config["QUESTIONS_DIR"]
    fpath = os.path.join(q_dir, safe_name)
    if not os.path.isfile(fpath):
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["filename"] = safe_name
        return data
    except Exception:
        return None


def calculate_xp(questions_graded: list[dict], time_taken: int, streak_days: int) -> int:
    """
    Công thức tính XP:
    XP = Tổng (điểm câu đúng × hệ số độ khó) + Thưởng tốc độ + Thưởng streak
    - Điểm cơ bản mỗi câu đúng: 10 XP
    - Hệ số độ khó: easy = 1.0, medium = 1.5, hard = 2.0
    - Thưởng tốc độ: nếu trung bình mỗi câu đúng < 20 giây và đúng >= 3 câu -> +15 XP
    - Thưởng streak: min(streak_days * 3, 30) XP (nếu có ít nhất 1 câu đúng)
    """
    diff_Multipliers = {"easy": 1.0, "medium": 1.5, "hard": 2.0}
    base_xp = 0.0
    correct_count = 0

    for item in questions_graded:
        if item.get("is_correct"):
            correct_count += 1
            mult = diff_Multipliers.get(item.get("difficulty", "easy"), 1.0)
            base_xp += 10.0 * mult

    if correct_count == 0:
        return 0

    avg_time = time_taken / max(len(questions_graded), 1)
    speed_bonus = 15 if (correct_count >= 3 and avg_time <= 20) else (8 if (correct_count >= 3 and avg_time <= 35) else 0)
    streak_bonus = min(max(streak_days, 1) * 3, 30)
    return int(round(base_xp + speed_bonus + streak_bonus))


def update_user_streak_and_badges(user: User, answered_count: int, score_percent: float, total_quiz_questions: int) -> list[dict]:
    """Cập nhật streak học liên tiếp hằng ngày, mục tiêu ngày và trao huy hiệu mới."""
    today = date.today()
    if user.last_study_date is None:
        user.streak_days = 1
        user.questions_done_today = answered_count
        user.last_study_date = today
    elif user.last_study_date == today:
        user.questions_done_today += answered_count
    elif user.last_study_date == today - timedelta(days=1):
        user.streak_days += 1
        user.questions_done_today = answered_count
        user.last_study_date = today
    else:
        user.streak_days = 1
        user.questions_done_today = answered_count
        user.last_study_date = today

    user.total_questions_answered = (user.total_questions_answered or 0) + answered_count

    existing_codes = {b.badge_code for b in user.badges.all()}
    newly_awarded = []

    def award(code: str):
        if code in existing_codes:
            return
        bdef = next((b for b in BADGE_DEFINITIONS if b["code"] == code), None)
        if bdef:
            ub = UserBadge(
                user_id=user.id,
                badge_code=bdef["code"],
                badge_name=bdef["name"],
                badge_icon=bdef["icon"],
                badge_desc=bdef["desc"]
            )
            db.session.add(ub)
            existing_codes.add(code)
            newly_awarded.append(bdef)

    award("first_quiz")
    if score_percent >= 100.0 and total_quiz_questions >= 5:
        award("perfect_100")
    if user.total_questions_answered >= 100:
        award("questions_100")
    if user.streak_days >= 7:
        award("streak_7")
    if user.xp >= 1000:
        award("xp_1000")

    return newly_awarded
