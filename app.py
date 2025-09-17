import os
import json
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)

# 환경변수에서 값을 가져오고, 없으면 기본값 사용
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# 데이터 저장 파일 경로
DATA_FILE = 'courses_data.json'

# 초기 과목 설정 (기본값)
DEFAULT_COURSES = {
    "베이킹": {"capacity": 3, "students": []},
    "비즈": {"capacity": 4, "students": []},
    "모루인형": {"capacity": 3, "students": []},
    "슈링클": {"capacity": 4, "students": []},
    "꽃꽂이": {"capacity": 2, "students": []},
    "뜨개질": {"capacity": 2, "students": []},
}

def load_courses_data():
    """JSON 파일에서 과목 데이터 로드"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"데이터 로드 성공: {len(data)} 과목")
                return data
        else:
            print("데이터 파일이 존재하지 않음. 기본값 사용.")
            return DEFAULT_COURSES.copy()
    except Exception as e:
        print(f"데이터 로드 실패: {e}. 기본값 사용.")
        return DEFAULT_COURSES.copy()

def save_courses_data():
    """과목 데이터를 JSON 파일에 저장"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(courses, f, ensure_ascii=False, indent=2)
        print(f"데이터 저장 성공: {len(courses)} 과목")
    except Exception as e:
        print(f"데이터 저장 실패: {e}")

# 앱 시작 시 데이터 로드
courses = load_courses_data()

@app.route("/")
def home():
    # 기능 1: 항상 이름 입력 페이지부터 시작
    return redirect(url_for("name_input"))

@app.route("/main")
def main():
    # 이름이 입력되지 않았으면 이름 입력 페이지로
    if "name" not in session:
        return redirect(url_for("name_input"))

    name = session["name"]
    course_status = {
        c: {"capacity": data["capacity"], "registered": len(data["students"]), "students": data["students"]}
        for c, data in courses.items()
    }
    return render_template("index.html", name=name, courses=course_status)

@app.route("/name_input")
def name_input():
    return render_template("name_input.html")

@app.route("/set_name", methods=["POST"])
def set_name():
    name = request.form.get("name")
    if name:
        session["name"] = name
    return redirect(url_for("main"))

@app.route("/apply", methods=["POST"])
def apply():
    if "name" not in session:
        return redirect(url_for("name_input"))

    name = session["name"]
    course = request.form.get("course")

    # 이미 신청한 과목이 있으면 중복 신청 불가
    for c, data in courses.items():
        if name in data["students"]:
            return render_template("popup.html", message="이미 과목을 신청했습니다.", retry=False)

    # 정원 확인
    if len(courses[course]["students"]) >= courses[course]["capacity"]:
        return render_template("popup.html", message="정원이 초과되었습니다.", retry=True)

    # 수강신청 처리
    courses[course]["students"].append(name)
    
    # 데이터 저장
    save_courses_data()
    
    return render_template("popup.html", message="신청 성공!", retry=False)

@app.route("/my_course")
def my_course():
    if "name" not in session:
        return redirect(url_for("name_input"))

    name = session["name"]
    my_course = None
    for c, data in courses.items():
        if name in data["students"]:
            my_course = c
            break
    return render_template("my_course.html", name=name, course=my_course)

# 기능 2: 수강신청 정정 기능
@app.route("/cancel_course", methods=["POST"])
def cancel_course():
    if "name" not in session:
        return redirect(url_for("name_input"))

    name = session["name"]
    
    # 해당 사용자의 신청 내역 삭제
    for c, data in courses.items():
        if name in data["students"]:
            data["students"].remove(name)
            break
    
    # 데이터 저장
    save_courses_data()
    
    return render_template("popup.html", message="신청이 취소되었습니다. 다시 신청해주세요.", retry=False)

# ----------- 관리자 기능 ------------
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

    course_status = {
        c: {"capacity": data["capacity"], "registered": len(data["students"]), "students": data["students"]}
        for c, data in courses.items()
    }
    return render_template("admin.html", courses=course_status)

@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    course = request.form.get("course")
    student = request.form.get("student")

    if course in courses and student in courses[course]["students"]:
        courses[course]["students"].remove(student)
        
        # 데이터 저장
        save_courses_data()

    return redirect(url_for("admin"))

@app.route("/admin_logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))

# 관리자 전용: 모든 데이터 초기화
@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    
    global courses
    courses = DEFAULT_COURSES.copy()
    save_courses_data()
    
    return render_template("popup.html", message="모든 수강신청 데이터가 초기화되었습니다.", retry=False)

if __name__ == "__main__":
    # 배포 환경에서는 debug=False로 설정
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
