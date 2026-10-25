"""Local web interface for the SMCII Grade System."""

from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import time
from urllib.parse import urlparse

import backend


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
HOST = "127.0.0.1"
PORT = 8765
SESSION_TTL_SECONDS = 60 * 60 * 4
MAX_REQUEST_BYTES = 1024 * 1024
SESSIONS = {}


def public_user(user):
    return {
        "username": user.get("username", ""),
        "full_name": user.get("full_name", ""),
        "role": user.get("role", ""),
    }


def dashboard_data(user):
    role = user.get("role", "").lower()
    school_year = backend.current_school_year()
    semester = backend.current_semester()

    if role == "admin":
        students = backend.users_by_role("Student")
        teachers = backend.users_by_role("Teacher")
        grade_records = backend.all_grade_records()
        return {
            "role": "Admin",
            "school_year": school_year,
            "semester": semester,
            "cards": [
                {"label": "Students", "value": len(students)},
                {"label": "Teachers", "value": len(teachers)},
                {"label": "Grade records", "value": len(grade_records)},
                {"label": "Subjects", "value": len(backend.list_subjects())},
            ],
            "semesters": [
                {
                    "name": name,
                    "status": backend.semester_status_for(name),
                }
                for name in backend.SEMESTER_NAMES
            ],
            "rows": [
                {
                    "student": record.get("student_username", ""),
                    "subject": record.get("subject", ""),
                    "teacher": record.get("teacher_username", ""),
                    "semester": record.get("semester", ""),
                    "final_grade": record.get("final_grade"),
                }
                for record in grade_records[:10]
            ],
            "table_title": "Recent grade records",
            "table_headers": ["Student", "Subject", "Teacher", "Semester", "Final grade"],
        }

    if role == "teacher":
        records = backend.grades_for_teacher(
            user.get("username", ""),
            semester=semester,
            school_year=school_year,
        )
        subjects = backend.subjects_for_teacher(user.get("username", ""))
        return {
            "role": "Teacher",
            "school_year": school_year,
            "semester": semester,
            "cards": [
                {"label": "My subjects", "value": len(subjects)},
                {"label": "Grade records", "value": len(records)},
                {"label": "School year", "value": school_year},
            ],
            "semesters": [],
            "rows": [
                {
                    "student": record.get("student_username", ""),
                    "subject": record.get("subject", ""),
                    "semester": record.get("semester", ""),
                    "final_grade": record.get("final_grade"),
                }
                for record in records[:25]
            ],
            "table_title": "My grade records",
            "table_headers": ["Student", "Subject", "Semester", "Final grade"],
        }

    performance = backend.student_performance(
        user.get("username", ""),
        semester=semester,
        school_year=school_year,
    )
    subjects = performance["subjects"]
    return {
        "role": "Student",
        "school_year": school_year,
        "semester": semester,
        "cards": [
            {
                "label": "General average",
                "value": (
                    performance["general_average"]
                    if performance["general_average"] is not None
                    else "—"
                ),
            },
            {"label": "Subjects", "value": performance["subjects_count"]},
            {"label": "Passed", "value": performance["passed"]},
            {"label": "Needs attention", "value": performance["failed"]},
        ],
        "semesters": [],
        "rows": [
            {
                "subject": subject["subject"],
                "terms": subject["terms"],
                "overall": subject["overall"],
                "status": subject["status"],
            }
            for subject in subjects
        ],
        "table_title": "My academic progress",
        "table_headers": ["Subject", "Prelim", "Midterm", "Semifinal", "Finals", "Overall", "Status"],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SMCIIWeb/1.0"

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}")

    def send_json(self, status, payload=None, headers=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size."})
            return None
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request is too large."})
            return None
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON request."})
            return None
        if not isinstance(payload, dict):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a JSON object."})
            return None
        return payload

    def current_user(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None, None
        session_cookie = cookie.get("smcii_session")
        if session_cookie is None:
            return None, None
        token = session_cookie.value
        session = SESSIONS.get(token)
        if session is None:
            return None, token
        if session["expires_at"] <= time.time():
            del SESSIONS[token]
            return None, token
        session["expires_at"] = time.time() + SESSION_TTL_SECONDS
        user = backend.find_user(session["username"])
        if user is None or not user.get("active", True):
            del SESSIONS[token]
            return None, token
        return user, token

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/session":
            user, _ = self.current_user()
            if user is None:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Sign in to continue."})
                return
            self.send_json(HTTPStatus.OK, {"user": public_user(user)})
            return

        if path == "/api/dashboard":
            user, _ = self.current_user()
            if user is None:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Sign in to continue."})
                return
            self.send_json(HTTPStatus.OK, dashboard_data(user))
            return

        file_names = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.css": "app.css",
            "/app.js": "app.js",
        }
        file_name = file_names.get(path)
        if file_name is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = os.path.join(WEB_DIR, file_name)
        try:
            with open(file_path, "rb") as file:
                body = file.read()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/html; charset=utf-8" if file_name.endswith(".html") else (
            "text/css; charset=utf-8" if file_name.endswith(".css") else
            "text/javascript; charset=utf-8"
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            payload = self.read_json()
            if payload is None:
                return
            username = payload.get("username")
            password = payload.get("password")
            role = payload.get("role")
            if not all(isinstance(value, str) for value in (username, password, role)):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Enter your username, password, and role."})
                return
            user = backend.authenticate_user(username, password, role)
            if user is None:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "The sign-in details were not recognized."})
                return
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = {
                "username": user["username"],
                "expires_at": time.time() + SESSION_TTL_SECONDS,
            }
            self.send_json(
                HTTPStatus.OK,
                {"user": public_user(user)},
                {"Set-Cookie": f"smcii_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL_SECONDS}"},
            )
            return

        if path == "/api/logout":
            _, token = self.current_user()
            if token:
                SESSIONS.pop(token, None)
            self.send_json(
                HTTPStatus.NO_CONTENT,
                headers={"Set-Cookie": "smcii_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"},
            )
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def start():
    """Start the local-only browser dashboard."""
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"SMCII dashboard available at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SMCII dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    start()
