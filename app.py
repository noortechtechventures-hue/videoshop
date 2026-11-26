"""
Simple pay-to-download video shop.

- Visitors see a grid of videos with thumbnails.
- Tapping Download asks for their M-Pesa number, then shows the Till number and amount.
- The owner sees the pending request in /admin, checks the M-Pesa SMS, and taps Approve.
- The visitor's page unlocks the download automatically.

Run:  ADMIN_PASSWORD=yourpassword python app.py
"""
import hmac
import os
import re
import secrets
import sqlite3
import subprocess
import time
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", BASE / "data"))
VIDEOS = DATA / "videos"
THUMBS = DATA / "thumbs"
DB_PATH = DATA / "site.db"

TILL = os.environ.get("TILL_NUMBER", "5196055")
SITE_NAME = os.environ.get("SITE_NAME", "My Videos")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
LINK_HOURS = int(os.environ.get("LINK_HOURS", "72"))  # how long a paid download stays open
MAX_UPLOAD_GB = float(os.environ.get("MAX_UPLOAD_GB", "4"))

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".3gp", ".zip", ".rar", ".7z"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

for d in (VIDEOS, THUMBS):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(MAX_UPLOAD_GB * 1024 ** 3)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS") == "1"

_key_file = DATA / "secret.key"
if not _key_file.exists():
    _key_file.write_text(secrets.token_hex(32))
app.secret_key = _key_file.read_text().strip()


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'video',
            price INTEGER NOT NULL,
            filename TEXT NOT NULL,
            thumb TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            ref TEXT NOT NULL,
            video_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created REAL NOT NULL,
            approved_at REAL,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        );
        """
    )
    conn.commit()
    conn.close()


init_db()


# ---------- helpers ----------
def norm_phone(raw):
    """Return Kenyan number as 2547XXXXXXXX / 2541XXXXXXXX, or None."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("254") and len(d) == 12:
        pass
    elif d.startswith("0") and len(d) == 10:
        d = "254" + d[1:]
    elif len(d) == 9 and d[0] in "71":
        d = "254" + d
    else:
        return None
    return d if d[3] in "71" else None


def show_phone(p):
    return "0" + p[3:] if p and p.startswith("254") else p


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def new_ref():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(5))


def expires_at(order):
    return (order["approved_at"] or 0) + LINK_HOURS * 3600


def make_thumb(video_path, out_path):
    """Try to grab a frame with ffmpeg. Returns True on success."""
    for ts in ("00:00:05", "00:00:01", "00:00:00"):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", ts, "-i", str(video_path), "-frames:v", "1",
                 "-vf", "scale=640:-2", str(out_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
            if out_path.exists() and out_path.stat().st_size > 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


app.jinja_env.filters["phone"] = show_phone
app.jinja_env.filters["size"] = human_size


@app.template_filter("when")
def when(ts):
    return time.strftime("%d %b %H:%M", time.localtime(ts)) if ts else ""


@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"site_name": SITE_NAME, "till": TILL, "csrf": session["csrf"], "link_hours": LINK_HOURS,
            "is_admin": session.get("admin") is True}


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            if not hmac.compare_digest(sent, session.get("csrf", "")):
                abort(400)
        return fn(*a, **kw)
    return wrapper


# ---------- public pages ----------
@app.route("/")
def index():
    videos = db().execute("SELECT * FROM videos ORDER BY created DESC").fetchall()
    return render_template("index.html", videos=videos)


@app.route("/thumb/<name>")
def thumb(name):
    return send_from_directory(THUMBS, name, max_age=86400)


@app.route("/get/<int:vid>", methods=["GET", "POST"])
def get_video(vid):
    video = db().execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not video:
        abort(404)
    if request.method == "POST":
        phone = norm_phone(request.form.get("phone"))
        name = (request.form.get("name") or "").strip()[:60]
        if not phone:
            flash("Enter the M-Pesa number you will pay from, e.g. 0712345678.")
            return render_template("get.html", video=video, name=name), 400
        # reuse an open request from the same number for the same video
        existing = db().execute(
            "SELECT * FROM orders WHERE video_id=? AND phone=? AND status IN ('pending','approved') "
            "ORDER BY created DESC", (vid, phone)).fetchall()
        for o in existing:
            if o["status"] == "pending" or time.time() < expires_at(o):
                return redirect(url_for("order_page", key=o["key"]))
        key = secrets.token_urlsafe(16)
        db().execute(
            "INSERT INTO orders (key, ref, video_id, phone, name, created) VALUES (?,?,?,?,?,?)",
            (key, new_ref(), vid, phone, name, time.time()))
        db().commit()
        return redirect(url_for("order_page", key=key))
    return render_template("get.html", video=video, name="")


def load_order(key):
    row = db().execute(
        "SELECT o.*, v.title, v.price, v.kind, v.size, v.thumb FROM orders o "
        "JOIN videos v ON v.id=o.video_id WHERE o.key=?", (key,)).fetchone()
    if not row:
        abort(404)
    return row


def order_state(o):
    if o["status"] == "approved":
        return "approved" if time.time() < expires_at(o) else "expired"
    return o["status"]


@app.route("/order/<key>")
def order_page(key):
    o = load_order(key)
    return render_template("order.html", o=o, state=order_state(o))


@app.route("/order/<key>/status")
def order_status(key):
    return jsonify(state=order_state(load_order(key)))


@app.route("/dl/<key>")
def download(key):
    o = load_order(key)
    if order_state(o) != "approved":
        abort(403)
    video = db().execute("SELECT * FROM videos WHERE id=?", (o["video_id"],)).fetchone()
    path = VIDEOS / video["filename"]
    if not path.exists():
        abort(404)
    ext = path.suffix
    safe = re.sub(r"[^\w\- ]+", "", video["title"]).strip() or "video"
    return send_file(path, as_attachment=True, download_name=f"{safe}{ext}", conditional=True)


# ---------- admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if ADMIN_PASSWORD and hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
            session["admin"] = True
            return redirect(url_for("admin_orders"))
        time.sleep(1)
        flash("Wrong password.")
    if not ADMIN_PASSWORD:
        flash("ADMIN_PASSWORD is not set on the server, so admin login is switched off.")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_orders():
    q = ("SELECT o.*, v.title, v.price FROM orders o JOIN videos v ON v.id=o.video_id "
         "WHERE o.status=? ORDER BY o.created DESC")
    pending = db().execute(q, ("pending",)).fetchall()
    recent = db().execute(
        "SELECT o.*, v.title, v.price FROM orders o JOIN videos v ON v.id=o.video_id "
        "WHERE o.status!='pending' ORDER BY o.created DESC LIMIT 30").fetchall()
    total = db().execute(
        "SELECT COALESCE(SUM(v.price),0) FROM orders o JOIN videos v ON v.id=o.video_id "
        "WHERE o.status='approved'").fetchone()[0]
    return render_template("admin_orders.html", pending=pending, recent=recent, total=total)


@app.route("/admin/order/<int:oid>/<action>", methods=["POST"])
@admin_required
def admin_order_action(oid, action):
    if action not in ("approve", "reject"):
        abort(404)
    status = "approved" if action == "approve" else "rejected"
    db().execute("UPDATE orders SET status=?, approved_at=? WHERE id=?",
                 (status, time.time() if status == "approved" else None, oid))
    db().commit()
    return redirect(url_for("admin_orders"))


@app.route("/admin/videos", methods=["GET", "POST"])
@admin_required
def admin_videos():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:100]
        kind = request.form.get("kind") if request.form.get("kind") in ("movie", "series", "video") else "video"
        try:
            price = int(request.form.get("price", ""))
            assert 1 <= price <= 100000
        except (ValueError, AssertionError):
            flash("Price must be a whole number of shillings.")
            return redirect(url_for("admin_videos"))
        f = request.files.get("video")
        if not title or not f or not f.filename:
            flash("A title and a video file are required.")
            return redirect(url_for("admin_videos"))
        ext = Path(f.filename).suffix.lower()
        if ext not in VIDEO_EXT:
            flash(f"File type {ext or '(none)'} not allowed. Use: " + ", ".join(sorted(VIDEO_EXT)))
            return redirect(url_for("admin_videos"))
        stem = secrets.token_hex(8)
        vpath = VIDEOS / f"{stem}{ext}"
        f.save(vpath)

        thumb_name = None
        t = request.files.get("thumb")
        if t and t.filename:
            text = Path(t.filename).suffix.lower()
            if text in IMAGE_EXT:
                thumb_name = f"{stem}{text}"
                t.save(THUMBS / thumb_name)
        if not thumb_name and ext not in {".zip", ".rar", ".7z"}:
            if make_thumb(vpath, THUMBS / f"{stem}.jpg"):
                thumb_name = f"{stem}.jpg"

        db().execute(
            "INSERT INTO videos (title, kind, price, filename, thumb, size, created) VALUES (?,?,?,?,?,?,?)",
            (title, kind, price, vpath.name, thumb_name, vpath.stat().st_size, time.time()))
        db().commit()
        flash(f"Added “{title}”.")
        return redirect(url_for("admin_videos"))
    videos = db().execute("SELECT * FROM videos ORDER BY created DESC").fetchall()
    return render_template("admin_videos.html", videos=videos, max_gb=MAX_UPLOAD_GB)


@app.route("/admin/video/<int:vid>/delete", methods=["POST"])
@admin_required
def admin_video_delete(vid):
    v = db().execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if v:
        (VIDEOS / v["filename"]).unlink(missing_ok=True)
        if v["thumb"]:
            (THUMBS / v["thumb"]).unlink(missing_ok=True)
        db().execute("DELETE FROM orders WHERE video_id=?", (vid,))
        db().execute("DELETE FROM videos WHERE id=?", (vid,))
        db().commit()
    return redirect(url_for("admin_videos"))


@app.errorhandler(413)
def too_large(_e):
    return f"File too big. The limit is {MAX_UPLOAD_GB:g} GB (change MAX_UPLOAD_GB).", 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threaded=True)
