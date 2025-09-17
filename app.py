import os
from flask import Flask, render_template, request, redirect, url_for, session
from sqlalchemy import create_engine, text, MetaData, Table, Column, String, Integer, ForeignKey, UniqueConstraint, select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)

# ----- 환경 변수 -----
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# Render의 DATABASE_URL 보정 (postgres:// -> postgresql://)
_raw_db_url = os.environ.get("DATABASE_URL")
if not _raw_db_url:
    raise RuntimeError("DATABASE_URL 환경변수가 필요합니다. Render의 Postgres 연결 문자열을 설정하세요.")
DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql://", 1)

# ----- DB 엔진/스키마 -----
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,            # 죽은 커넥션 자동 감지
    pool_size=5, max_overflow=10,  # 가벼운 풀 설정
)

metadata = MetaData()

courses_t = Table(
    "courses", metadata,
    Column("name", String, primary_key=True),
    Column("capacity", Integer, nullable=False),
)

registrations_t = Table(
    "registrations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("student", String, nullable=False, unique=True),  # 학생 1명 1과목
    Column("course", String, ForeignKey("courses.name"), nullable=False),
    UniqueConstraint("student", name="uq_student")
)

DEFAULT_COURSES = {
    "베이킹":   {"capacity": 3},
    "비즈":     {"capacity": 4},
    "모루인형": {"capacity": 3},
    "슈링클":   {"capacity": 4},
    "꽃꽂이":   {"capacity": 2},
    "뜨개질":   {"capacity": 2},
}

def init_db_and_seed():
    """테이블 생성 및 기본 과목 시드"""
    metadata.create_all(engine)

    with engine.begin() as conn:
        # 과목 테이블이 비어 있으면 기본값 삽입
        count = conn.execute(select(func.count()).select_from(courses_t)).scalar_one()
        if count == 0:
            conn.execute(
                courses_t.insert(),
                [{"name": n, "capacity": v["capacity"]} for n, v in DEFAULT_COURSES.items()]
            )

def get_course_status():
    """템플릿에 주입할 현재 상태 dict로 구성"""
    with engine.connect() as conn:
        rows = conn.execute(select(courses_t.c.name, courses_t.c.capacity)).all()
        status = {}
        for name, capacity in rows:
            registered = conn.execute(
                select(func.count()).select_from(registrations_t).where(registrations_t.c.course == name)
            ).scalar_one()
            students = [r[0] for r in conn.execute(
                select(registrations_t.c.student).where(registrations_t.c.course == name).order_by(registrations_t.c.id.asc())
            ).all()]
            status[name] = {"capacity": capacity, "registered": registered, "students": students}
        return status

def get_my_course(student_name: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(registrations_t.c.course).where(registrations_t.c.student == student_name)
        ).first()
        return row[0] if row else None

# 앱 시작 시 DB 초기화
init_db_and_seed()

# ----- Routes -----
@app.route("/")
def home():
    return redirect(url_for("name_input"))

@app.route("/main")
def main():
    if "name" not in session:
        return redirect(url_for("name_input"))
    name = session["name"]
    return render_template("index.html", name=name, courses=get_course_status())

@app.route("/name_input")
def name_input():
    return render_template("name_input.html")

@app.route("/set_name", methods=["POST"])
def set_name():
    name = request.form.get("name")
    if name:
        session["name"] = name.strip()
    return redirect(url_for("main"))

@app.route("/apply", methods=["POST"])
def apply():
    if "name" not in session:
        return redirect(url_for("name_input"))

    name = session["name"].strip()
    course = request.form.get("course")

    # 트랜잭션 + 행 잠금으로 정원/중복 동시성 보호
    with Session(engine) as s:
        try:
            # 이미 신청했는지 확인 (유니크 제약이 있지만 사용자 친화적 메시지 위해 선확인)
            already = s.execute(
                select(registrations_t.c.id).where(registrations_t.c.student == name)
            ).first()
            if already:
                return render_template("popup.html", message="이미 과목을 신청했습니다.", retry=False)

            # 신청할 과목 행 잠금
            course_row = s.execute(
                select(courses_t.c.name, courses_t.c.capacity)
                .where(courses_t.c.name == course)
                .with_for_update()
            ).first()
            if not course_row:
                return render_template("popup.html", message="존재하지 않는 과목입니다.", retry=True)

            capacity = course_row.capacity
            registered = s.execute(
                select(func.count()).select_from(registrations_t).where(registrations_t.c.course == course)
            ).scalar_one()

            if registered >= capacity:
                return render_template("popup.html", message="정원이 초과되었습니다.", retry=True)

            # 등록 시도
            s.execute(
                registrations_t.insert().values(student=name, course=course)
            )
            s.commit()
            return render_template("popup.html", message="신청 성공!", retry=False)

        except IntegrityError:
            # 동시성 경합으로 UNIQUE(student) 충돌 시
            s.rollback()
            return render_template("popup.html", message="이미 과목을 신청했습니다.", retry=False)

@app.route("/my_course")
def my_course():
    if "name" not in session:
        return redirect(url_for("name_input"))
    name = session["name"]
    return render_template("my_course.html", name=name, course=get_my_course(name))

@app.route("/cancel_course", methods=["POST"])
def cancel_course():
    if "name" not in session:
        return redirect(url_for("name_input"))
    name = session["name"]

    with engine.begin() as conn:
        conn.execute(
            registrations_t.delete().where(registrations_t.c.student == name)
        )
    return render_template("popup.html", message="신청이 취소되었습니다. 다시 신청해주세요.", retry=False)

# -------- 관리자 --------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        else:
            return render_template("popup.html", message="비밀번호가 틀렸습니다.", retry=True)
    return render_template("admin_login.html")

@app.route("/admin")
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html", courses=get_course_status())

@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    course = request.form.get("course")
    student = request.form.get("student")

    with engine.begin() as conn:
        conn.execute(
            registrations_t.delete()
            .where(registrations_t.c.course == course, registrations_t.c.student == student)
        )
    return redirect(url_for("admin"))

@app.route("/admin_logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))

@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    # 전체 초기화: 신청 삭제 + 과목 테이블을 기본값으로 재시드(용량 원복 포함)
    with engine.begin() as conn:
        conn.execute(registrations_t.delete())
        conn.execute(courses_t.delete())
        conn.execute(
            courses_t.insert(),
            [{"name": n, "capacity": v["capacity"]} for n, v in DEFAULT_COURSES.items()]
        )
    return render_template("popup.html", message="모든 수강신청 데이터가 초기화되었습니다.", retry=False)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
