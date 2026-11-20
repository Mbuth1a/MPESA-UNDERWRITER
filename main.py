import os
import re
import time
import uuid
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, File, UploadFile, Form, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import jwt
from pwdlib import PasswordHash

from analyzer import analyze_statement
from report import generate_report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(BASE_DIR, "reports")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DB_PATH = os.path.join(BASE_DIR, "underwriter.db")
os.makedirs(REPORT_DIR, exist_ok=True)

REPORT_FILENAME_REGEX = re.compile(r"^report_[a-f0-9]{8,16}\.pdf$")
SUBMISSION_TOKEN_REGEX = re.compile(r"^[a-f0-9]{16}$")

TOKEN_TTL_HOURS = 2
REPORT_TTL_SECONDS = 7200

# JWT config — replace SECRET_KEY with the output of `openssl rand -hex 32`
SECRET_KEY = "change-me-to-a-random-64-char-hex-string-openssl-rand-hex-32"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/lender/login")

CONSENT_TEXT = (
    "I consent to the processing of my M-Pesa statement data for the purpose of generating "
    "a financial profile. I understand that:\n"
    "1. This profile will be shared only with lenders I explicitly authorize by providing them my submission token.\n"
    "2. I can revoke access at any time via the Borrower Portal, which will immediately invalidate the token.\n"
    "3. My data will be retained for 90 days and then deleted.\n"
    "4. I have the right to access, correct, or delete my data by contacting the platform.\n"
    "This consent is given under the Kenya Data Protection Act, 2019."
)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            hashed_password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'lender_reviewer',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            metrics_json TEXT NOT NULL,
            report_filename TEXT NOT NULL,
            consent_given INTEGER NOT NULL DEFAULT 0,
            consent_text TEXT,
            consent_timestamp TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lender_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            lender_id INTEGER NOT NULL,
            accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
            ip_address TEXT,
            FOREIGN KEY (submission_id) REFERENCES submissions(id),
            FOREIGN KEY (lender_id) REFERENCES lenders(id)
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_token ON submissions(token);
        CREATE INDEX IF NOT EXISTS idx_lender_access_submission ON lender_access(submission_id);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class LenderRegister(BaseModel):
    email: str
    name: str
    password: str


def get_current_lender(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        lender_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise credentials_exception

    conn = get_db()
    lender = conn.execute(
        "SELECT id, email, name, role, is_active FROM lenders WHERE id = ?",
        (lender_id,),
    ).fetchone()
    conn.close()

    if not lender or not lender["is_active"]:
        raise credentials_exception
    return dict(lender)


def require_role(required_role: str):
    """Dependency factory: enforce a specific lender role."""
    def checker(lender: Annotated[dict, Depends(get_current_lender)]):
        if lender["role"] != required_role and lender["role"] != "admin":
            raise HTTPException(403, f"Requires role: {required_role}")
        return lender
    return checker


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

def cleanup_old_reports(max_age_seconds: int = REPORT_TTL_SECONDS):
    if not os.path.exists(REPORT_DIR):
        return
    now = time.time()
    for fname in os.listdir(REPORT_DIR):
        if not fname.endswith(".pdf"):
            continue
        full_path = os.path.join(REPORT_DIR, fname)
        try:
            if os.path.isfile(full_path) and (now - os.path.getmtime(full_path)) > max_age_seconds:
                os.remove(full_path)
        except OSError:
            pass


def cleanup_expired_submissions():
    conn = get_db()
    now = datetime.utcnow().isoformat()
    expired = conn.execute(
        "SELECT id, report_filename FROM submissions WHERE active = 1 AND expires_at < ?",
        (now,),
    ).fetchall()
    for row in expired:
        conn.execute("UPDATE submissions SET active = 0 WHERE id = ?", (row["id"],))
        report_path = os.path.join(REPORT_DIR, row["report_filename"])
        if os.path.isfile(report_path):
            try:
                os.remove(report_path)
            except OSError:
                pass
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cleanup_old_reports()
    cleanup_expired_submissions()
    yield
    cleanup_old_reports()
    cleanup_expired_submissions()


app = FastAPI(
    title="M-Pesa Cash Flow Underwriter",
    description="Automated cash-flow, risk analysis, and credit profiling from Safaricom M-Pesa statements.",
    version="3.0.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/lender", response_class=HTMLResponse)
async def lender_portal(request: Request):
    return templates.TemplateResponse(request, "lender.html")


# ---------------------------------------------------------------------------
# Lender: register & login
# ---------------------------------------------------------------------------

@app.post("/lender/register")
async def register_lender(payload: LenderRegister):
    email = payload.email.strip().lower()
    name = payload.name.strip()

    if not email or "@" not in email:
        raise HTTPException(400, "A valid email is required.")
    if not name:
        raise HTTPException(400, "Lender institution name is required.")
    if len(payload.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    conn = get_db()
    existing = conn.execute("SELECT id FROM lenders WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "An account with this email already exists.")

    hashed = password_hash.hash(payload.password)
    conn.execute(
        "INSERT INTO lenders (email, name, hashed_password, role) VALUES (?, ?, ?, 'lender_reviewer')",
        (email, name, hashed),
    )
    conn.commit()
    conn.close()
    return {"message": "Lender account created. You can now log in."}


@app.post("/lender/login")
async def login_lender(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    email = form_data.username.strip().lower()
    conn = get_db()
    lender = conn.execute(
        "SELECT id, email, name, hashed_password, role, is_active FROM lenders WHERE email = ?",
        (email,),
    ).fetchone()
    conn.close()

    if not lender or not password_hash.verify(form_data.password, lender["hashed_password"]):
        raise HTTPException(401, "Invalid email or password.")
    if not lender["is_active"]:
        raise HTTPException(403, "Account is deactivated.")

    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode(
        {"sub": str(lender["id"]), "email": lender["email"], "role": lender["role"], "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "lender_name": lender["name"],
        "role": lender["role"],
    }


@app.get("/lender/me")
async def lender_me(lender: Annotated[dict, Depends(get_current_lender)]):
    return {"id": lender["id"], "email": lender["email"], "name": lender["name"], "role": lender["role"]}


# ---------------------------------------------------------------------------
# Borrower: analyze & submit
# ---------------------------------------------------------------------------

@app.post("/analyze")
async def analyze(
    pdf_file: UploadFile = File(...),
    password: str = Form(...),
    consent_given: str = Form(...),
):
    if consent_given != "true":
        return JSONResponse(
            status_code=400,
            content={"error": "You must provide consent to process your statement under the Kenya Data Protection Act."},
        )

    if not pdf_file.filename.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Uploaded file must be a PDF statement."})

    cleanup_old_reports()
    cleanup_expired_submissions()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await pdf_file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = analyze_statement(tmp_path, password)
        if "error" in result:
            return JSONResponse(status_code=400, content={"error": result["error"]})

        report_id = uuid.uuid4().hex[:12]
        report_filename = f"report_{report_id}.pdf"
        report_path = os.path.join(REPORT_DIR, report_filename)
        generate_report(result, report_path)

        lender_token = uuid.uuid4().hex[:16]
        expires_at = (datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)).isoformat()

        conn = get_db()
        conn.execute(
            """INSERT INTO submissions
               (token, metrics_json, report_filename, consent_given, consent_text,
                consent_timestamp, active, expires_at)
               VALUES (?, ?, ?, 1, ?, ?, 1, ?)""",
            (lender_token, json.dumps(result), report_filename, CONSENT_TEXT,
             datetime.utcnow().isoformat(), expires_at),
        )
        conn.commit()
        conn.close()

        return {
            "metrics": result,
            "report_url": f"/download/{report_filename}",
            "lender_token": lender_token,
            "consent_text": CONSENT_TEXT,
            "expires_at": expires_at,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Internal server error: {str(e)}"})
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.post("/submit")
async def submit_for_lender(
    pdf_file: UploadFile = File(...),
    password: str = Form(...),
    consent_given: str = Form(...),
):
    return await analyze(pdf_file=pdf_file, password=password, consent_given=consent_given)


# ---------------------------------------------------------------------------
# Borrower: revoke & access log
# ---------------------------------------------------------------------------

@app.post("/revoke/{token}")
async def revoke_token(token: str):
    safe_token = token.strip().lower()
    if not SUBMISSION_TOKEN_REGEX.match(safe_token):
        raise HTTPException(status_code=400, detail="Invalid token format.")

    conn = get_db()
    row = conn.execute("SELECT id FROM submissions WHERE token = ?", (safe_token,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Token not found.")

    conn.execute("UPDATE submissions SET active = 0 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return {"status": "revoked", "message": "All lender access to this submission has been terminated."}


@app.get("/access-log/{token}")
async def access_log(token: str):
    safe_token = token.strip().lower()
    if not SUBMISSION_TOKEN_REGEX.match(safe_token):
        raise HTTPException(status_code=400, detail="Invalid token format.")

    conn = get_db()
    sub = conn.execute("SELECT id FROM submissions WHERE token = ?", (safe_token,)).fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Token not found.")

    rows = conn.execute(
        """SELECT l.name AS lender_name, la.accessed_at
           FROM lender_access la
           JOIN lenders l ON l.id = la.lender_id
           WHERE la.submission_id = ?
           ORDER BY la.accessed_at DESC""",
        (sub["id"],),
    ).fetchall()
    conn.close()

    return {
        "token": safe_token,
        "accesses": [
            {"lender": r["lender_name"], "accessed_at": r["accessed_at"]}
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Lender: review submission (JWT-authenticated)
# ---------------------------------------------------------------------------

@app.get("/review/{token}")
async def review_submission(
    token: str,
    request: Request,
    lender: Annotated[dict, Depends(get_current_lender)],
):
    safe_token = token.strip().lower()
    if not SUBMISSION_TOKEN_REGEX.match(safe_token):
        raise HTTPException(status_code=400, detail="Invalid submission token format.")

    cleanup_expired_submissions()

    conn = get_db()
    sub = conn.execute("SELECT * FROM submissions WHERE token = ?", (safe_token,)).fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found or has expired.")

    if not sub["active"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Token has been revoked by the borrower.")

    if datetime.utcnow() > datetime.fromisoformat(sub["expires_at"]):
        conn.execute("UPDATE submissions SET active = 0 WHERE id = ?", (sub["id"],))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=403, detail="Token has expired (tokens expire after 2 hours).")

    client_ip = request.client.host if request.client else None
    conn.execute(
        "INSERT INTO lender_access (submission_id, lender_id, ip_address) VALUES (?, ?, ?)",
        (sub["id"], lender["id"], client_ip),
    )
    conn.commit()
    conn.close()

    return {
        "metrics": json.loads(sub["metrics_json"]),
        "report_url": f"/download/{sub['report_filename']}",
        "submitted_at": sub["created_at"],
        "lender_name": lender["name"],
    }


# ---------------------------------------------------------------------------
# Report download
# ---------------------------------------------------------------------------

@app.get("/download/{filename}")
async def download(filename: str):
    safe_name = os.path.basename(filename)
    if not REPORT_FILENAME_REGEX.match(safe_name) and not safe_name.endswith("_report.pdf"):
        raise HTTPException(status_code=400, detail="Invalid report filename.")

    path = os.path.join(REPORT_DIR, safe_name)
    resolved_path = os.path.abspath(path)

    if not resolved_path.startswith(os.path.abspath(REPORT_DIR)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if os.path.isfile(resolved_path):
        return FileResponse(
            resolved_path,
            media_type="application/pdf",
            filename="mpesa_financial_profile.pdf",
        )
    raise HTTPException(status_code=404, detail="Requested report was not found or has expired.")