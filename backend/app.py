import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
MASTER_ADMINS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_MASTER_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = os.environ.get("DB_PATH", "backend/exchange_app.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "backend/uploads")
MAX_RECEIPT_MB = int(os.environ.get("MAX_RECEIPT_MB", "5"))
MAX_RECEIPTS_PER_10MIN = int(os.environ.get("MAX_RECEIPTS_PER_10MIN", "5"))
ALLOW_DEV_BYPASS = os.environ.get("ALLOW_DEV_BYPASS", "0").strip() == "1"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS exchanges (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                welcome_note TEXT DEFAULT '',
                admin_ids TEXT DEFAULT '',
                is_open INTEGER DEFAULT 1,
                is_listed_public INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rates_and_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange_id TEXT NOT NULL,
                pair_label TEXT NOT NULL,
                rate REAL NOT NULL,
                card_number TEXT NOT NULL,
                card_holder TEXT NOT NULL,
                min_amount REAL DEFAULT 0,
                max_amount REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                first_exchange_id TEXT,
                active_exchange_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_code TEXT UNIQUE NOT NULL,
                exchange_id TEXT NOT NULL,
                user_telegram_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                pair_label TEXT NOT NULL,
                amount_paid REAL NOT NULL,
                rate_snapshot REAL NOT NULL,
                amount_receive REAL NOT NULL,
                card_snapshot TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_receipt',
                reject_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (exchange_id) REFERENCES exchanges(id)
            );

            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                exchange_id TEXT NOT NULL,
                user_telegram_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                is_duplicate_suspect INTEGER DEFAULT 0,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
            """
        )

        existing = conn.execute("SELECT COUNT(*) AS c FROM exchanges").fetchone()["c"]
        if existing == 0:
            ts = now_iso()
            admin_str = ",".join(str(x) for x in MASTER_ADMINS)
            conn.execute(
                """
                INSERT INTO exchanges (id, name, welcome_note, admin_ids, is_open, is_listed_public, created_at)
                VALUES (?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    "sarafi_demo",
                    "صرافی نمونه درام",
                    "سفارش خود را ثبت کنید و رسید واریز را بفرستید تا مدیر بررسی کند.",
                    admin_str,
                    ts,
                ),
            )
            conn.execute(
                """
                INSERT INTO rates_and_cards
                (exchange_id, pair_label, rate, card_number, card_holder, min_amount, max_amount, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    "sarafi_demo",
                    "AMD -> USDT",
                    390.0,
                    "9051 1200 3400 5600",
                    "حساب مقصد صرافی",
                    1000.0,
                    5000000.0,
                ),
            )


def verify_telegram_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None

    if ALLOW_DEV_BYPASS and init_data.startswith("DEV_USER:"):
        try:
            raw = init_data.split("DEV_USER:", 1)[1]
            parts = raw.split(":")
            uid = int(parts[0])
            uname = parts[1] if len(parts) > 1 else "dev_user"
            fname = parts[2] if len(parts) > 2 else "Dev"
            return {"id": uid, "username": uname, "first_name": fname}
        except Exception:
            return None

    if not BOT_TOKEN:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        auth_date = int(parsed.get("auth_date", "0"))
        if time.time() - auth_date > 86400:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_raw = parsed.get("user")
        if not user_raw:
            return None
        user_obj = json.loads(user_raw)
        if "id" not in user_obj:
            return None
        return user_obj
    except Exception:
        return None
def get_authenticated_user():
    init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
    if not init_data and request.is_json:
        init_data = (request.get_json(silent=True) or {}).get("init_data", "")
    elif not init_data and request.form:
        init_data = request.form.get("init_data", "")
    return verify_telegram_init_data(init_data)


def is_exchange_admin(conn, user_id: int, exchange_id: str) -> bool:
    if user_id in MASTER_ADMINS:
        return True
    row = conn.execute("SELECT admin_ids FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
    if not row:
        return False
    admin_set = {
        int(x.strip())
        for x in (row["admin_ids"] or "").split(",")
        if x.strip().isdigit()
    }
    return user_id in admin_set


def send_telegram_alert(chat_id: int, text: str):
    if not BOT_TOKEN or not chat_id:
        return
    try:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "exchange-miniapp-backend", "time": now_iso()})


@app.route("/api/bootstrap", methods=["POST"])
def bootstrap():
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    body = request.get_json(silent=True) or {}
    startapp = (body.get("startapp") or "").strip()
    explicit_select = (body.get("select_exchange_id") or "").strip()

    uid = int(user["id"])
    uname = (user.get("username") or "").strip()
    fname = (user.get("first_name") or "").strip()
    ts = now_iso()

    with get_db() as conn:
        u_row = conn.execute(
            "SELECT first_exchange_id, active_exchange_id FROM users WHERE telegram_id = ?",
            (uid,),
        ).fetchone()

        target_exchange_id = None

        if startapp:
            ex = conn.execute(
                "SELECT id FROM exchanges WHERE id = ? AND is_open = 1", (startapp,)
            ).fetchone()
            if ex:
                target_exchange_id = ex["id"]
                first_ex = (
                    u_row["first_exchange_id"]
                    if (u_row and u_row["first_exchange_id"])
                    else target_exchange_id
                )
                if u_row:
                    conn.execute(
                        """
                        UPDATE users
                        SET username = ?, first_name = ?, first_exchange_id = ?, active_exchange_id = ?, updated_at = ?
                        WHERE telegram_id = ?
                        """,
                        (uname, fname, first_ex, target_exchange_id, ts, uid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO users (telegram_id, username, first_name, first_exchange_id, active_exchange_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (uid, uname, fname, first_ex, target_exchange_id, ts, ts),
                    )

        elif explicit_select:
            ex = conn.execute(
                "SELECT id FROM exchanges WHERE id = ? AND is_open = 1", (explicit_select,)
            ).fetchone()
            if ex:
                target_exchange_id = ex["id"]
                first_ex = (
                    u_row["first_exchange_id"]
                    if (u_row and u_row["first_exchange_id"])
                    else target_exchange_id
                )
                if u_row:
                    conn.execute(
                        """
                        UPDATE users
                        SET username = ?, first_name = ?, first_exchange_id = ?, active_exchange_id = ?, updated_at = ?
                        WHERE telegram_id = ?
                        """,
                        (uname, fname, first_ex, target_exchange_id, ts, uid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO users (telegram_id, username, first_name, first_exchange_id, active_exchange_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (uid, uname, fname, first_ex, target_exchange_id, ts, ts),
                    )

        else:
            if u_row:
                conn.execute(
                    "UPDATE users SET username = ?, first_name = ?, updated_at = ? WHERE telegram_id = ?",
                    (uname, fname, ts, uid),
                )
                sticky_id = u_row["active_exchange_id"] or u_row["first_exchange_id"]
                if sticky_id:
                    ex = conn.execute(
                        "SELECT id FROM exchanges WHERE id = ? AND is_open = 1", (sticky_id,)
                    ).fetchone()
                    if ex:
                        target_exchange_id = ex["id"]
            else:
                conn.execute(
                    """
                    INSERT INTO users (telegram_id, username, first_name, first_exchange_id, active_exchange_id, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (uid, uname, fname, ts, ts),
                )

        if target_exchange_id:
            ex_row = conn.execute(
                "SELECT id, name, welcome_note, is_open FROM exchanges WHERE id = ?",
                (target_exchange_id,),
            ).fetchone()
            rates = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, pair_label, rate, card_number, card_holder, min_amount, max_amount
                    FROM rates_and_cards
                    WHERE exchange_id = ? AND is_active = 1
                    """,
                    (target_exchange_id,),
                ).fetchall()
            ]
            my_orders = [
                dict(o)
                for o in conn.execute(
                    """
                    SELECT id, tracking_code, pair_label, amount_paid, rate_snapshot, amount_receive,
                           status, reject_reason, created_at
                    FROM orders
                    WHERE exchange_id = ? AND user_telegram_id = ?
                    ORDER BY id DESC LIMIT 20
                    """,
                    (target_exchange_id, uid),
                ).fetchall()
            ]
            admin_flag = is_exchange_admin(conn, uid, target_exchange_id)
            return jsonify(
                {
                    "ok": True,
                    "mode": "exchange",
                    "user": {"telegram_id": uid, "username": uname, "first_name": fname},
                    "exchange": dict(ex_row),
                    "rates": rates,
                    "orders": my_orders,
                    "is_admin": admin_flag,
                }
            )

        public_exchanges = [
            dict(e)
            for e in conn.execute(
                """
                SELECT id, name, welcome_note
                FROM exchanges
                WHERE is_open = 1 AND is_listed_public = 1
                ORDER BY created_at DESC
                """
            ).fetchall()
        ]
        return jsonify(
            {
                "ok": True,
                "mode": "public_list",
                "user": {"telegram_id": uid, "username": uname, "first_name": fname},
                "exchanges": public_exchanges,
                "is_admin": uid in MASTER_ADMINS,
            }
        )


@app.route("/api/orders", methods=["POST"])
def create_order():
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    body = request.get_json(silent=True) or {}
    exchange_id = (body.get("exchange_id") or "").strip()
    rate_card_id = body.get("rate_card_id")
    amount_paid = float(body.get("amount_paid") or 0)

    if not exchange_id or not rate_card_id or amount_paid <= 0:
        return jsonify({"ok": False, "error": "اطلاعات سفارش ناقص یا نامعتبر است."}), 400

    uid = int(user["id"])
    uname = (user.get("username") or "").strip()

    with get_db() as conn:
        ex = conn.execute(
            "SELECT id, name, is_open FROM exchanges WHERE id = ?", (exchange_id,)
        ).fetchone()
        if not ex or not ex["is_open"]:
            return jsonify({"ok": False, "error": "صرافی در حال حاضر سفارش نمی‌پذیرد."}), 400

        rc = conn.execute(
            """
            SELECT * FROM rates_and_cards
            WHERE id = ? AND exchange_id = ? AND is_active = 1
            """,
            (rate_card_id, exchange_id),
        ).fetchone()
        if not rc:
            return jsonify({"ok": False, "error": "نرخ یا کارت انتخاب‌شده معتبر نیست."}), 400

        if rc["min_amount"] and amount_paid < rc["min_amount"]:
            return jsonify({"ok": False, "error": f"حداقل مبلغ سفارش {rc['min_amount']} است."}), 400
        if rc["max_amount"] and amount_paid > rc["max_amount"]:
            return jsonify({"ok": False, "error": f"حداکثر مبلغ سفارش {rc['max_amount']} است."}), 400

        rate_val = float(rc["rate"])
        amount_receive = round(amount_paid / rate_val, 4) if rate_val > 0 else 0
        tracking_code = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        card_snapshot = f"{rc['card_number']} ({rc['card_holder']})"
        ts = now_iso()

        cur = conn.execute(
            """
            INSERT INTO orders
            (tracking_code, exchange_id, user_telegram_id, username, pair_label,
             amount_paid, rate_snapshot, amount_receive, card_snapshot, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_receipt', ?, ?)
            """,
            (
                tracking_code,
                exchange_id,
                uid,
                uname,
                rc["pair_label"],
                amount_paid,
                rate_val,
                amount_receive,
                card_snapshot,
                ts,
                ts,
            ),
        )
        order_id = cur.lastrowid

    return jsonify(
        {
            "ok": True,
            "order": {
                "id": order_id,
                "tracking_code": tracking_code,
                "exchange_id": exchange_id,
                "pair_label": rc["pair_label"],
                "amount_paid": amount_paid,
                "rate_snapshot": rate_val,
                "amount_receive": amount_receive,
                "card_snapshot": card_snapshot,
                "status": "pending_receipt",
                "created_at": ts,
            },
        }
  )
          @app.route("/api/orders/<int:order_id>/receipt", methods=["POST"])
def upload_receipt(order_id: int):
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    if "receipt" not in request.files:
        return jsonify({"ok": False, "error": "فایل رسید ارسال نشده است."}), 400

    file = request.files["receipt"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "نام فایل نامعتبر است."}), 400

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"ok": False, "error": "فقط فرمت‌های JPG, PNG, WEBP مجاز هستند."}), 400

    raw_bytes = file.read()
    max_bytes = MAX_RECEIPT_MB * 1024 * 1024
    if len(raw_bytes) == 0 or len(raw_bytes) > max_bytes:
        return jsonify({"ok": False, "error": f"حجم رسید باید کمتر از {MAX_RECEIPT_MB} مگابایت باشد."}), 400

    uid = int(user["id"])
    file_hash = hashlib.sha256(raw_bytes).hexdigest()

    with get_db() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_telegram_id = ?",
            (order_id, uid),
        ).fetchone()
        if not order:
            return jsonify({"ok": False, "error": "سفارش پیدا نشد."}), 404

        if order["status"] not in ("pending_receipt", "rejected"):
            return jsonify({"ok": False, "error": "وضعیت این سفارش اجازه ارسال رسید ندارد."}), 400

        ten_min_ago = datetime.fromtimestamp(time.time() - 600, tz=timezone.utc).isoformat()
        recent_count = conn.execute(
            """
            SELECT COUNT(*) AS c FROM receipts
            WHERE user_telegram_id = ? AND uploaded_at >= ?
            """,
            (uid, ten_min_ago),
        ).fetchone()["c"]
        if recent_count >= MAX_RECEIPTS_PER_10MIN:
            return jsonify(
                {
                    "ok": False,
                    "error": "تعداد ارسال رسید در بازه زمانی کوتاه بیش از حد مجاز است. کمی صبر کنید.",
                }
            ), 429

        dup_row = conn.execute(
            "SELECT id FROM receipts WHERE exchange_id = ? AND file_hash = ?",
            (order["exchange_id"], file_hash),
        ).fetchone()
        is_dup = 1 if dup_row else 0

        safe_name = f"rcp_{order['exchange_id']}_{order_id}_{uuid.uuid4().hex[:10]}{ext}"
        ex_folder = os.path.join(UPLOAD_DIR, order["exchange_id"])
        os.makedirs(ex_folder, exist_ok=True)
        save_path = os.path.join(ex_folder, safe_name)
        with open(save_path, "wb") as f:
            f.write(raw_bytes)

        ts = now_iso()
        conn.execute(
            """
            INSERT INTO receipts
            (order_id, exchange_id, user_telegram_id, file_name, file_hash, is_duplicate_suspect, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, order["exchange_id"], uid, safe_name, file_hash, is_dup, ts),
        )
        conn.execute(
            "UPDATE orders SET status = 'under_review', updated_at = ? WHERE id = ?",
            (ts, order_id),
        )

        ex_row = conn.execute(
            "SELECT admin_ids FROM exchanges WHERE id = ?", (order["exchange_id"],)
        ).fetchone()
        admin_ids = {
            int(x.strip())
            for x in ((ex_row["admin_ids"] if ex_row else "") or "").split(",")
            if x.strip().isdigit()
        } | MASTER_ADMINS

    alert_text = (
        f"رسید جدید برای بررسی ({order['exchange_id']})\n"
        f"کد پیگیری: {order['tracking_code']}\n"
        f"مبلغ: {order['amount_paid']} -> {order['amount_receive']} ({order['pair_label']})\n"
        f"هشدار رسید تکراری: {'بله' if is_dup else 'خیر'}"
    )
    for aid in admin_ids:
        send_telegram_alert(aid, alert_text)

    return jsonify(
        {
            "ok": True,
            "order_id": order_id,
            "status": "under_review",
            "duplicate_suspect": bool(is_dup),
        }
    )


@app.route("/api/admin/orders", methods=["GET"])
def admin_list_orders():
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    exchange_id = (request.args.get("exchange_id") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    uid = int(user["id"])

    with get_db() as conn:
        if not exchange_id or not is_exchange_admin(conn, uid, exchange_id):
            return jsonify({"ok": False, "error": "دسترسی مدیریتی مجاز نیست."}), 403

        sql = """
            SELECT o.*, r.file_name AS receipt_file, r.is_duplicate_suspect
            FROM orders o
            LEFT JOIN receipts r ON r.id = (
                SELECT id FROM receipts WHERE order_id = o.id ORDER BY id DESC LIMIT 1
            )
            WHERE o.exchange_id = ?
        """
        params = [exchange_id]
        if status_filter:
            sql += " AND o.status = ?"
            params.append(status_filter)
        sql += " ORDER BY o.id DESC LIMIT 100"

        rows = [dict(x) for x in conn.execute(sql, params).fetchall()]
        return jsonify({"ok": True, "orders": rows})


@app.route("/api/admin/orders/<int:order_id>/decision", methods=["POST"])
def admin_order_decision(order_id: int):
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    body = request.get_json(silent=True) or {}
    decision = (body.get("decision") or "").strip()
    reason = (body.get("reason") or "").strip()
    uid = int(user["id"])

    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "تصمیم نامعتبر است."}), 400

    new_status = "approved" if decision == "approve" else "rejected"
    ts = now_iso()

    with get_db() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return jsonify({"ok": False, "error": "سفارش پیدا نشد."}), 404

        if not is_exchange_admin(conn, uid, order["exchange_id"]):
            return jsonify({"ok": False, "error": "دسترسی مدیریتی مجاز نیست."}), 403

        conn.execute(
            "UPDATE orders SET status = ?, reject_reason = ?, updated_at = ? WHERE id = ?",
            (new_status, reason if new_status == "rejected" else "", ts, order_id),
        )

    send_telegram_alert(
        int(order["user_telegram_id"]),
        f"وضعیت سفارش {order['tracking_code']} تغییر کرد: {new_status}"
        + (f"\nدلیل: {reason}" if reason and new_status == "rejected" else ""),
    )

    return jsonify({"ok": True, "order_id": order_id, "status": new_status})


@app.route("/api/admin/receipts/<exchange_id>/<filename>", methods=["GET"])
def admin_get_receipt(exchange_id: str, filename: str):
    user = get_authenticated_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    uid = int(user["id"])
    with get_db() as conn:
        if not is_exchange_admin(conn, uid, exchange_id):
            return jsonify({"ok": False, "error": "دسترسی مدیریتی مجاز نیست."}), 403

    safe_filename = os.path.basename(filename)
    folder = os.path.abspath(os.path.join(UPLOAD_DIR, exchange_id))
    return send_from_directory(folder, safe_filename)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
                  
