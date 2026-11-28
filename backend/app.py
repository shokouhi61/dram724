import os
import json
import hmac
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qsl
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "receipts")
DB_PATH = os.path.join(DATA_DIR, "dram724.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SUPER_ADMIN_IDS = {
    x.strip() for x in os.environ.get("SUPER_ADMIN_IDS", "").split(",") if x.strip()
}
MAX_RECEIPT_MB = int(os.environ.get("MAX_RECEIPT_MB", "10"))
MAX_RECEIPTS_PER_10MIN = int(os.environ.get("MAX_RECEIPTS_PER_10MIN", "10"))
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exchanges (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        admin_ids TEXT NOT NULL DEFAULT '',
        rate_amd_to_irt REAL NOT NULL DEFAULT 750,
        rate_irt_to_amd REAL NOT NULL DEFAULT 900,
        rate_usd_to_irt REAL NOT NULL DEFAULT 280000,
        rate_irt_to_usd REAL NOT NULL DEFAULT 310000,
        rate_usd_to_amd REAL NOT NULL DEFAULT 360,
        rate_amd_to_usd REAL NOT NULL DEFAULT 375,
        holder_amd TEXT NOT NULL DEFAULT 'تست درام',
        card_amd TEXT NOT NULL DEFAULT '2050 0011 2233 4455',
        bank_amd TEXT NOT NULL DEFAULT 'Ameria بانک',
        holder_irt TEXT NOT NULL DEFAULT 'تست تومان',
        card_irt TEXT NOT NULL DEFAULT '6104 3377 1234 5678',
        sheba_irt TEXT NOT NULL DEFAULT 'IR120120000000009876543210',
        account_irt TEXT NOT NULL DEFAULT '4712345678',
        bank_irt TEXT NOT NULL DEFAULT 'بانک ملت',
        holder_usd TEXT NOT NULL DEFAULT 'تست دلار',
        card_usd TEXT NOT NULL DEFAULT '4000 1234 5678 9010',
        card_type_usd TEXT NOT NULL DEFAULT 'VISA کارت',
        min_amd REAL NOT NULL DEFAULT 100,
        max_amd REAL NOT NULL DEFAULT 1000000,
        min_irt REAL NOT NULL DEFAULT 10000,
        max_irt REAL NOT NULL DEFAULT 7500000000,
        min_usd REAL NOT NULL DEFAULT 1,
        max_usd REAL NOT NULL DEFAULT 25000,
        address TEXT NOT NULL DEFAULT 'آدرس نمونه',
        working_hours TEXT NOT NULL DEFAULT 'همه‌روزه ۹:۰۰ تا ۲۱:۰۰',
        phone TEXT NOT NULL DEFAULT '+37411111111',
        whatsapp TEXT NOT NULL DEFAULT 'wa.me/+37494055428',
        telegram TEXT NOT NULL DEFAULT 't.me/shokouhi61',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    existing_cols = {
        row["name"] for row in cur.execute("PRAGMA table_info(exchanges)").fetchall()
    }
    new_columns = {
        "admin_ids": "TEXT NOT NULL DEFAULT ''",
        "rate_amd_to_irt": "REAL NOT NULL DEFAULT 750",
        "rate_irt_to_amd": "REAL NOT NULL DEFAULT 900",
        "rate_usd_to_irt": "REAL NOT NULL DEFAULT 280000",
        "rate_irt_to_usd": "REAL NOT NULL DEFAULT 310000",
        "rate_usd_to_amd": "REAL NOT NULL DEFAULT 360",
        "rate_amd_to_usd": "REAL NOT NULL DEFAULT 375",
        "holder_amd": "TEXT NOT NULL DEFAULT 'تست درام'",
        "card_amd": "TEXT NOT NULL DEFAULT '2050 0011 2233 4455'",
        "bank_amd": "TEXT NOT NULL DEFAULT 'Ameria بانک'",
        "holder_irt": "TEXT NOT NULL DEFAULT 'تست تومان'",
        "card_irt": "TEXT NOT NULL DEFAULT '6104 3377 1234 5678'",
        "sheba_irt": "TEXT NOT NULL DEFAULT 'IR120120000000009876543210'",
        "account_irt": "TEXT NOT NULL DEFAULT '4712345678'",
        "bank_irt": "TEXT NOT NULL DEFAULT 'بانک ملت'",
        "holder_usd": "TEXT NOT NULL DEFAULT 'تست دلار'",
        "card_usd": "TEXT NOT NULL DEFAULT '4000 1234 5678 9010'",
        "card_type_usd": "TEXT NOT NULL DEFAULT 'VISA کارت'",
        "min_amd": "REAL NOT NULL DEFAULT 100",
        "max_amd": "REAL NOT NULL DEFAULT 1000000",
        "min_irt": "REAL NOT NULL DEFAULT 10000",
        "max_irt": "REAL NOT NULL DEFAULT 7500000000",
        "min_usd": "REAL NOT NULL DEFAULT 1",
        "max_usd": "REAL NOT NULL DEFAULT 25000",
        "address": "TEXT NOT NULL DEFAULT 'آدرس نمونه'",
        "working_hours": "TEXT NOT NULL DEFAULT 'همه‌روزه ۹:۰۰ تا ۲۱:۰۰'",
        "phone": "TEXT NOT NULL DEFAULT '+37411111111'",
        "whatsapp": "TEXT NOT NULL DEFAULT 'wa.me/+37494055428'",
        "telegram": "TEXT NOT NULL DEFAULT 't.me/shokouhi61'",
        "is_active": "INTEGER NOT NULL DEFAULT 1",
    }
    for col, col_def in new_columns.items():
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE exchanges ADD COLUMN {col} {col_def}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_locks (
        user_id TEXT PRIMARY KEY,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        first_exchange_id TEXT NOT NULL,
        active_exchange_id TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_code TEXT NOT NULL,
        exchange_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        pair_code TEXT NOT NULL,
        from_currency TEXT NOT NULL,
        to_currency TEXT NOT NULL,
        pay_method TEXT NOT NULL DEFAULT 'cash',
        receive_method TEXT NOT NULL DEFAULT 'cash',
        send_amount REAL NOT NULL,
        rate_used REAL NOT NULL,
        receive_amount REAL NOT NULL,
        customer_holder_name TEXT DEFAULT '',
        customer_dest_card TEXT DEFAULT '',
        customer_sheba TEXT DEFAULT '',
        customer_account TEXT DEFAULT '',
        customer_bank_or_card_type TEXT DEFAULT '',
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'awaiting_receipt',
        receipt_filename TEXT DEFAULT '',
        receipt_hash TEXT DEFAULT '',
        duplicate_suspect INTEGER NOT NULL DEFAULT 0,
        admin_note TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    order_cols = {
        row["name"] for row in cur.execute("PRAGMA table_info(orders)").fetchall()
    }
    order_new_cols = {
        "tracking_code": "TEXT NOT NULL DEFAULT ''",
        "pair_code": "TEXT NOT NULL DEFAULT 'AMD_TO_IRT'",
        "from_currency": "TEXT NOT NULL DEFAULT 'AMD'",
        "to_currency": "TEXT NOT NULL DEFAULT 'IRT'",
        "pay_method": "TEXT NOT NULL DEFAULT 'cash'",
        "receive_method": "TEXT NOT NULL DEFAULT 'cash'",
        "send_amount": "REAL NOT NULL DEFAULT 0",
        "rate_used": "REAL NOT NULL DEFAULT 0",
        "receive_amount": "REAL NOT NULL DEFAULT 0",
        "customer_holder_name": "TEXT DEFAULT ''",
        "customer_dest_card": "TEXT DEFAULT ''",
        "customer_sheba": "TEXT DEFAULT ''",
        "customer_account": "TEXT DEFAULT ''",
        "customer_bank_or_card_type": "TEXT DEFAULT ''",
        "note": "TEXT DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'awaiting_receipt'",
        "receipt_filename": "TEXT DEFAULT ''",
        "receipt_hash": "TEXT DEFAULT ''",
        "duplicate_suspect": "INTEGER NOT NULL DEFAULT 0",
        "admin_note": "TEXT DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for col, col_def in order_new_cols.items():
        if col not in order_cols:
            cur.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_def}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipt_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    count = cur.execute("SELECT COUNT(*) AS c FROM exchanges").fetchone()["c"]
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        default_admins = ",".join(sorted(SUPER_ADMIN_IDS))
        cur.execute("""
            INSERT INTO exchanges (
            id, name, admin_ids,
            rate_amd_to_irt, rate_irt_to_amd,
            rate_usd_to_irt, rate_irt_to_usd,
            rate_usd_to_amd, rate_amd_to_usd,
            holder_amd, card_amd, bank_amd,
            holder_irt, card_irt, sheba_irt, account_irt, bank_irt,
            holder_usd, card_usd, card_type_usd,
            min_amd, max_amd, min_irt, max_irt, min_usd, max_usd,
            address, working_hours, phone, whatsapp, telegram,
            is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            "sample",
            "صرافی نمونه",
            default_admins,
            750,
            900,
            280000,
            310000,
            360,
            375,
            "تست درام",
            "2050 0011 2233 4455",
            "Ameria بانک",
            "تست تومان",
            "6104 3377 1234 5678",
            "IR120120000000009876543210",
            "4712345678",
            "بانک ملت",
            "تست دلار",
            "4000 1234 5678 9010",
            "VISA کارت",
            100,
            1000000,
            10000,
            7500000000,
            1,
            25000,
            "آدرس نمونه",
            "همه‌روزه ۹:۰۰ تا ۲۱:۰۰",
            "+37411111111",
            "wa.me/+37494055428",
            "t.me/shokouhi61",
            now,
        ))

    conn.commit()
    conn.close()


init_db()


def verify_telegram_init_data(init_data: str):
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash or not BOT_TOKEN:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items(), key=lambda x: x[0])
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        user_obj = json.loads(user_raw)
    except Exception:
        return None

    return {
        "user_id": str(user_obj.get("id", "")),
        "username": user_obj.get("username", "") or "",
        "first_name": user_obj.get("first_name", "") or "",
        "start_param": parsed.get("start_param", "") or "",
    }


def get_request_user():
    init_data = request.headers.get("X-Telegram-Init-Data", "").strip()
    verified = verify_telegram_init_data(init_data)
    if verified and verified.get("user_id"):
        return verified
    return None


def is_exchange_admin(user_id: str, exchange_row) -> bool:
    if not user_id:
        return False
    if user_id in SUPER_ADMIN_IDS:
        return True
    if not exchange_row:
        return False
    admins = {
        x.strip() for x in (exchange_row["admin_ids"] or "").split(",") if x.strip()
    }
    return user_id in admins


def serialize_exchange(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "admin_ids": row["admin_ids"],
        "rates": {
            "AMD_TO_IRT": float(row["rate_amd_to_irt"]),
            "IRT_TO_AMD": float(row["rate_irt_to_amd"]),
            "USD_TO_IRT": float(row["rate_usd_to_irt"]),
            "IRT_TO_USD": float(row["rate_irt_to_usd"]),
            "USD_TO_AMD": float(row["rate_usd_to_amd"]),
            "AMD_TO_USD": float(row["rate_amd_to_usd"]),
        },
        "payment_accounts": {
            "AMD": {
                "holder": row["holder_amd"],
                "card": row["card_amd"],
                "bank": row["bank_amd"],
            },
            "IRT": {
                "holder": row["holder_irt"],
                "card": row["card_irt"],
                "sheba": row["sheba_irt"],
                "account": row["account_irt"],
                "bank": row["bank_irt"],
            },
            "USD": {
                "holder": row["holder_usd"],
                "card": row["card_usd"],
                "card_type": row["card_type_usd"],
            },
        },
        "limits": {
            "AMD": {"min": float(row["min_amd"]), "max": float(row["max_amd"])},
            "IRT": {"min": float(row["min_irt"]), "max": float(row["max_irt"])},
            "USD": {"min": float(row["min_usd"]), "max": float(row["max_usd"])},
        },
        "contact": {
            "address": row["address"],
            "working_hours": row["working_hours"],
            "phone": row["phone"],
            "whatsapp": row["whatsapp"],
            "telegram": row["telegram"],
        },
        "is_active": int(row["is_active"]),
    }


def compute_and_validate_order(exchange_row, pair_code: str, send_amount: float):
    if send_amount <= 0:
        raise ValueError("مبلغ باید بیشتر از صفر باشد.")

    mapping = {
        "AMD_TO_IRT": ("AMD", "IRT", float(exchange_row["rate_amd_to_irt"]), "mul"),
        "IRT_TO_AMD": ("IRT", "AMD", float(exchange_row["rate_irt_to_amd"]), "div"),
        "USD_TO_IRT": ("USD", "IRT", float(exchange_row["rate_usd_to_irt"]), "mul"),
        "IRT_TO_USD": ("IRT", "USD", float(exchange_row["rate_irt_to_usd"]), "div"),
        "USD_TO_AMD": ("USD", "AMD", float(exchange_row["rate_usd_to_amd"]), "mul"),
        "AMD_TO_USD": ("AMD", "USD", float(exchange_row["rate_amd_to_usd"]), "div"),
    }
    if pair_code not in mapping:
        raise ValueError("نوع تبدیل نامعتبر است.")

    from_cur, to_cur, rate, op = mapping[pair_code]
    if rate <= 0:
        raise ValueError("نرخ این تبدیل معتبر تنظیم نشده است.")

    limits_map = {
        "AMD": (float(exchange_row["min_amd"]), float(exchange_row["max_amd"]), "درام"),
        "IRT": (float(exchange_row["min_irt"]), float(exchange_row["max_irt"]), "تومان"),
        "USD": (float(exchange_row["min_usd"]), float(exchange_row["max_usd"]), "دلار"),
    }

    from_min, from_max, from_fa = limits_map[from_cur]
    if send_amount < from_min:
        raise ValueError(f"مبلغ پرداختی کمتر از حداقل مجاز ({from_min:g} {from_fa}) است.")
    if send_amount > from_max:
        raise ValueError(f"مبلغ پرداختی از حداکثر توان عملیاتی ({from_max:g} {from_fa}) بیشتر است.")

    receive_amount = send_amount * rate if op == "mul" else send_amount / rate
    receive_amount = round(receive_amount, 2)

    to_min, to_max, to_fa = limits_map[to_cur]
    if receive_amount > to_max:
        raise ValueError(f"مبلغ دریافتی ({receive_amount:g} {to_fa}) از حداکثر توان عملیاتی ({to_max:g} {to_fa}) بیشتر است.")

    return from_cur, to_cur, rate, receive_amount


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "dram724"})


@app.route("/api/bootstrap", methods=["GET"])
def bootstrap():
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401
        start_param = (
        request.args.get("startapp", "").strip() or user.get("start_param", "").strip()
    )
    user_id = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    cur = conn.cursor()

    lock = cur.execute(
        "SELECT * FROM user_locks WHERE user_id = ?", (user_id,)
    ).fetchone()

    target_exchange = None
    if start_param:
        target_exchange = cur.execute(
            "SELECT * FROM exchanges WHERE id = ? AND is_active = 1", (start_param,)
        ).fetchone()

    if lock is None:
        if target_exchange is not None:
            cur.execute("""
            INSERT INTO user_locks (user_id, username, first_name, first_exchange_id, active_exchange_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                user["username"],
                user["first_name"],
                target_exchange["id"],
                target_exchange["id"],
                now,
            ))
            conn.commit()
            lock = cur.execute(
                "SELECT * FROM user_locks WHERE user_id = ?", (user_id,)
            ).fetchone()
    else:
        if target_exchange is not None and target_exchange["id"] != lock["active_exchange_id"]:
            cur.execute("""
            UPDATE user_locks
            SET active_exchange_id = ?, username = ?, first_name = ?, updated_at = ?
            WHERE user_id = ?
            """, (
                target_exchange["id"],
                user["username"],
                user["first_name"],
                now,
                user_id,
            ))
            conn.commit()
            lock = cur.execute(
                "SELECT * FROM user_locks WHERE user_id = ?", (user_id,)
            ).fetchone()

    active_exchange = None
    if lock is not None:
        active_exchange = cur.execute(
            "SELECT * FROM exchanges WHERE id = ? AND is_active = 1",
            (lock["active_exchange_id"],),
        ).fetchone()

    public_exchanges = []
    if active_exchange is None:
        rows = cur.execute(
            "SELECT * FROM exchanges WHERE is_active = 1 ORDER BY created_at ASC"
        ).fetchall()
        public_exchanges = [serialize_exchange(r) for r in rows]

    is_super = user_id in SUPER_ADMIN_IDS
    is_admin = is_exchange_admin(user_id, active_exchange) if active_exchange else is_super

    all_exchanges_for_super = []
    if is_super:
        rows = cur.execute("SELECT * FROM exchanges ORDER BY created_at ASC").fetchall()
        all_exchanges_for_super = [serialize_exchange(r) for r in rows]

    conn.close()

    return jsonify({
        "ok": True,
        "user": {
            "user_id": user_id,
            "username": user["username"],
            "first_name": user["first_name"],
            "is_super_admin": is_super,
            "is_admin": is_admin,
        },
        "locked": active_exchange is not None,
        "first_exchange_id": lock["first_exchange_id"] if lock else None,
        "active_exchange": serialize_exchange(active_exchange) if active_exchange else None,
        "public_exchanges": public_exchanges,
        "all_exchanges": all_exchanges_for_super,
    })


@app.route("/api/select-exchange", methods=["POST"])
def select_exchange():
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    data = request.get_json(silent=True) or {}
    exchange_id = str(data.get("exchange_id", "")).strip()
    if not exchange_id:
        return jsonify({"ok": False, "error": "شناسه صرافی ارسال نشده است."}), 400

    conn = get_db()
    cur = conn.cursor()

    lock = cur.execute(
        "SELECT * FROM user_locks WHERE user_id = ?", (user["user_id"],)
    ).fetchone()
    if lock is not None:
        conn.close()
        return jsonify({
            "ok": False,
            "error": "حساب شما قبلاً به یک صرافی متصل شده و امکان تغییر از لیست عمومی وجود ندارد.",
        }), 403

    ex = cur.execute(
        "SELECT * FROM exchanges WHERE id = ? AND is_active = 1", (exchange_id,)
    ).fetchone()
    if not ex:
        conn.close()
        return jsonify({"ok": False, "error": "صرافی پیدا نشد."}), 404

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
    INSERT INTO user_locks (user_id, username, first_name, first_exchange_id, active_exchange_id, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user["user_id"],
        user["username"],
        user["first_name"],
        exchange_id,
        exchange_id,
        now,
    ))
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "active_exchange": serialize_exchange(ex)})


@app.route("/api/orders", methods=["GET", "POST"])
def orders():
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    conn = get_db()
    cur = conn.cursor()

    lock = cur.execute(
        "SELECT * FROM user_locks WHERE user_id = ?", (user["user_id"],)
    ).fetchone()
    if not lock:
        conn.close()
        return jsonify({"ok": False, "error": "ابتدا وارد یک صرافی شوید."}), 400

    ex = cur.execute(
        "SELECT * FROM exchanges WHERE id = ? AND is_active = 1",
        (lock["active_exchange_id"],),
    ).fetchone()
    if not ex:
        conn.close()
        return jsonify({"ok": False, "error": "صرافی فعال یافت نشد."}), 404

    if request.method == "GET":
        rows = cur.execute("""
        SELECT * FROM orders
        WHERE user_id = ? AND exchange_id = ?
        ORDER BY id DESC LIMIT 30
        """, (user["user_id"], ex["id"])).fetchall()
        conn.close()
        return jsonify({"ok": True, "orders": [dict(r) for r in rows]})

    data = request.get_json(silent=True) or {}
    pair_code = str(data.get("pair_code", "")).strip()
    pay_method = "card" if str(data.get("pay_method", "cash")).strip() == "card" else "cash"
    receive_method = "card" if str(data.get("receive_method", "cash")).strip() == "card" else "cash"

    customer_holder_name = str(data.get("customer_holder_name", "")).strip() if receive_method == "card" else ""
    customer_dest_card = str(data.get("customer_dest_card", "")).strip() if receive_method == "card" else ""
    customer_sheba = str(data.get("customer_sheba", "")).strip() if receive_method == "card" else ""
    customer_account = str(data.get("customer_account", "")).strip() if receive_method == "card" else ""
    customer_bank_or_card_type = str(data.get("customer_bank_or_card_type", "")).strip() if receive_method == "card" else ""
    note = str(data.get("note", "")).strip()

    try:
        send_amount = float(data.get("send_amount", 0))
        from_cur, to_cur, rate_used, receive_amount = compute_and_validate_order(
            ex, pair_code, send_amount
        )
    except ValueError as e:
        conn.close()
        return jsonify({"ok": False, "error": str(e)}), 400
    initial_status = "awaiting_receipt" if pay_method == "card" else "under_review"
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    tracking_code = f"DR-{int(now_dt.timestamp()) % 1000000}"

    cur.execute("""
    INSERT INTO orders (
        tracking_code, exchange_id, user_id, username, first_name,
        pair_code, from_currency, to_currency, pay_method, receive_method,
        send_amount, rate_used, receive_amount,
        customer_holder_name, customer_dest_card, customer_sheba, customer_account,
        customer_bank_or_card_type, note, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        tracking_code,
        ex["id"],
        user["user_id"],
        user["username"],
        user["first_name"],
        pair_code,
        from_cur,
        to_cur,
        pay_method,
        receive_method,
        send_amount,
        rate_used,
        receive_amount,
        customer_holder_name,
        customer_dest_card,
        customer_sheba,
        customer_account,
        customer_bank_or_card_type,
        note,
        initial_status,
        now,
        now,
    ))
    order_id = cur.lastrowid
    conn.commit()
    created = cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "order": dict(created)})


@app.route("/api/orders/<int:order_id>/receipt", methods=["POST"])
def upload_receipt(order_id: int):
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    if "receipt" not in request.files:
        return jsonify({"ok": False, "error": "فایل رسید انتخاب نشده است."}), 400

    file = request.files["receipt"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "نام فایل نامعتبر است."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "ok": False,
            "error": "فرمت مجاز نیست. فقط PNG, JPG, WEBP یا PDF مجاز است.",
        }), 400

    raw_bytes = file.read()
    max_bytes = MAX_RECEIPT_MB * 1024 * 1024
    if len(raw_bytes) == 0 or len(raw_bytes) > max_bytes:
        return jsonify({
            "ok": False,
            "error": f"حجم فایل باید بین ۱ بایت تا {MAX_RECEIPT_MB} مگابایت باشد.",
        }), 400

    conn = get_db()
    cur = conn.cursor()

    ten_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    recent_count = cur.execute("""
    SELECT COUNT(*) AS c FROM receipt_logs
    WHERE user_id = ? AND created_at >= ?
    """, (user["user_id"], ten_mins_ago)).fetchone()["c"]

    if recent_count >= MAX_RECEIPTS_PER_10MIN:
        conn.close()
        return jsonify({
            "ok": False,
            "error": f"محدودیت ارسال: حداکثر {MAX_RECEIPTS_PER_10MIN} رسید در ۱۰ دقیقه مجاز است.",
        }), 429

    order = cur.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user["user_id"]),
    ).fetchone()
    if not order:
        conn.close()
        return jsonify({"ok": False, "error": "سفارش پیدا نشد."}), 404

    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    dup_row = cur.execute(
        "SELECT id FROM orders WHERE receipt_hash = ? AND id != ? LIMIT 1",
        (file_hash, order_id),
    ).fetchone()
    duplicate_suspect = 1 if dup_row else 0

    safe_name = secure_filename(f"order_{order_id}_{int(datetime.now().timestamp())}.{ext}")
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(save_path, "wb") as f:
        f.write(raw_bytes)

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
    UPDATE orders
    SET receipt_filename = ?, receipt_hash = ?, duplicate_suspect = ?,
        status = 'under_review', updated_at = ?
    WHERE id = ?
    """, (safe_name, file_hash, duplicate_suspect, now, order_id))

    cur.execute(
        "INSERT INTO receipt_logs (user_id, created_at) VALUES (?, ?)",
        (user["user_id"], now),
    )

    conn.commit()
    updated = cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "order": dict(updated)})


@app.route("/api/receipts/<path:filename>", methods=["GET"])
def serve_receipt(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/admin/orders", methods=["GET"])
def admin_orders():
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    exchange_id = request.args.get("exchange_id", "").strip()
    conn = get_db()
    cur = conn.cursor()

    ex = cur.execute("SELECT * FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
    if not ex or not is_exchange_admin(user["user_id"], ex):
        conn.close()
        return jsonify({"ok": False, "error": "دسترسی مدیر مجاز نیست."}), 403

    rows = cur.execute("""
    SELECT * FROM orders
    WHERE exchange_id = ?
    ORDER BY id DESC LIMIT 50
    """, (exchange_id,)).fetchall()
    conn.close()

    return jsonify({"ok": True, "orders": [dict(r) for r in rows]})


@app.route("/api/admin/orders/<int:order_id>/decision", methods=["POST"])
def admin_order_decision(order_id: int):
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision", "")).strip()
    admin_note = str(data.get("admin_note", "")).strip()

    if decision not in ("approved", "rejected"):
        return jsonify({"ok": False, "error": "وضعیت باید approved یا rejected باشد."}), 400

    conn = get_db()
    cur = conn.cursor()

    order = cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"ok": False, "error": "سفارش پیدا نشد."}), 404

    ex = cur.execute(
        "SELECT * FROM exchanges WHERE id = ?", (order["exchange_id"],)
    ).fetchone()
    if not ex or not is_exchange_admin(user["user_id"], ex):
        conn.close()
        return jsonify({"ok": False, "error": "دسترسی مدیر به این صرافی مجاز نیست."}), 403

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
    UPDATE orders
    SET status = ?, admin_note = ?, updated_at = ?
    WHERE id = ?
    """, (decision, admin_note, now, order_id))
    conn.commit()
    updated = cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "order": dict(updated)})


@app.route("/api/admin/exchange/settings", methods=["POST"])
def admin_update_exchange_settings():
    user = get_request_user()
    if not user:
        return jsonify({"ok": False, "error": "احراز هویت تلگرام نامعتبر است."}), 401

    data = request.get_json(silent=True) or {}
    exchange_id = str(data.get("exchange_id", "")).strip()

    conn = get_db()
    cur = conn.cursor()

    ex = cur.execute("SELECT * FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
    if not ex or not is_exchange_admin(user["user_id"], ex):
        conn.close()
        return jsonify({"ok": False, "error": "دسترسی مدیر مجاز نیست."}), 403

    try:
        r_amd_irt = float(data.get("rate_amd_to_irt", ex["rate_amd_to_irt"]))
        r_irt_amd = float(data.get("rate_irt_to_amd", ex["rate_irt_to_amd"]))
        r_usd_irt = float(data.get("rate_usd_to_irt", ex["rate_usd_to_irt"]))
        r_irt_usd = float(data.get("rate_irt_to_usd", ex["rate_irt_to_usd"]))
        r_usd_amd = float(data.get("rate_usd_to_amd", ex["rate_usd_to_amd"]))
        r_amd_usd = float(data.get("rate_amd_to_usd", ex["rate_amd_to_usd"]))
        if min(r_amd_irt, r_irt_amd, r_usd_irt, r_irt_usd, r_usd_amd, r_amd_usd) <= 0:
            raise ValueError("نرخ‌ها باید مثبت باشند.")

        min_amd = float(data.get("min_amd", ex["min_amd"]))
        max_amd = float(data.get("max_amd", ex["max_amd"]))
        min_irt = float(data.get("min_irt", ex["min_irt"]))
        max_irt = float(data.get("max_irt", ex["max_irt"]))
        min_usd = float(data.get("min_usd", ex["min_usd"]))
        max_usd = float(data.get("max_usd", ex["max_usd"]))

        if min(min_amd, min_irt, min_usd) <= 0:
            raise ValueError("حداقل مبلغ هر ارز باید بزرگ‌تر از صفر باشد.")
        if max_amd < min_amd or max_irt < min_irt or max_usd < min_usd:
            raise ValueError("حداکثر توان عملیاتی هر ارز نباید کمتر از حداقل آن باشد.")
    except ValueError as e:
        conn.close()
        return jsonify({"ok": False, "error": str(e) or "مقادیر عددی نامعتبر است."}), 400
    except Exception:
        conn.close()
        return jsonify({"ok": False, "error": "مقادیر نرخ یا سقف عملیاتی نامعتبر است."}), 400

    name = str(data.get("name", ex["name"])).strip() or ex["name"]

    holder_amd = str(data.get("holder_amd", ex["holder_amd"])).strip()
    card_amd = str(data.get("card_amd", ex["card_amd"])).strip()
    bank_amd = str(data.get("bank_amd", ex["bank_amd"])).strip()

    holder_irt = str(data.get("holder_irt", ex["holder_irt"])).strip()
    card_irt = str(data.get("card_irt", ex["card_irt"])).strip()
    sheba_irt = str(data.get("sheba_irt", ex["sheba_irt"])).strip()
    account_irt = str(data.get("account_irt", ex["account_irt"])).strip()
    bank_irt = str(data.get("bank_irt", ex["bank_irt"])).strip()

    holder_usd = str(data.get("holder_usd", ex["holder_usd"])).strip()
    card_usd = str(data.get("card_usd", ex["card_usd"])).strip()
    card_type_usd = str(data.get("card_type_usd", ex["card_type_usd"])).strip()

    address = str(data.get("address", ex["address"])).strip()
    working_hours = str(data.get("working_hours", ex["working_hours"])).strip()
    phone = str(data.get("phone", ex["phone"])).strip()
    whatsapp = str(data.get("whatsapp", ex["whatsapp"])).strip()
    telegram = str(data.get("telegram", ex["telegram"])).strip()

    admin_ids = ex["admin_ids"]
    if user["user_id"] in SUPER_ADMIN_IDS and "admin_ids" in data:
        admin_ids = str(data.get("admin_ids", "")).strip()

    cur.execute("""
    UPDATE exchanges
    SET name = ?,
        admin_ids = ?,
        rate_amd_to_irt = ?,
        rate_irt_to_amd = ?,
        rate_usd_to_irt = ?,
        rate_irt_to_usd = ?,
        rate_usd_to_amd = ?,
        rate_amd_to_usd = ?,
        holder_amd = ?,
        card_amd = ?,
        bank_amd = ?,
        holder_irt = ?,
        card_irt = ?,
        sheba_irt = ?,
        account_irt = ?,
        bank_irt = ?,
        holder_usd = ?,
        card_usd = ?,
        card_type_usd = ?,
        min_amd = ?,
        max_amd = ?,
        min_irt = ?,
        max_irt = ?,
        min_usd = ?,
        max_usd = ?,
        address = ?,
        working_hours = ?,
        phone = ?,
        whatsapp = ?,
        telegram = ?
    WHERE id = ?
    """, (
        name,
        admin_ids,
        r_amd_irt,
        r_irt_amd,
        r_usd_irt,
        r_irt_usd,
        r_usd_amd,
        r_amd_usd,
        holder_amd,
        card_amd,
        bank_amd,
        holder_irt,
        card_irt,
        sheba_irt,
        account_irt,
        bank_irt,
        holder_usd,
        card_usd,
        card_type_usd,
        min_amd,
        max_amd,
        min_irt,
        max_irt,
        min_usd,
        max_usd,
        address,
        working_hours,
        phone,
        whatsapp,
        telegram,
        exchange_id,
    ))
    conn.commit()
    updated_ex = cur.execute("SELECT * FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "exchange": serialize_exchange(updated_ex)})


@app.route("/api/admin/exchanges", methods=["POST"])
def super_admin_create_exchange():
    user = get_request_user()
    if not user or user["user_id"] not in SUPER_ADMIN_IDS:
        return jsonify({"ok": False, "error": "فقط سوپرادمین مجاز به ایجاد صرافی جدید است."}), 403

    data = request.get_json(silent=True) or {}
    ex_id = str(data.get("id", "")).strip().lower()
    name = str(data.get("name", "")).strip()
    admin_ids = str(data.get("admin_ids", "")).strip()

    if not ex_id or not name:
        return jsonify({"ok": False, "error": "شناسه انگلیسی و نام صرافی الزامی است."}), 400

    conn = get_db()
    cur = conn.cursor()
    exists = cur.execute("SELECT id FROM exchanges WHERE id = ?", (ex_id,)).fetchone()
    if exists:
        conn.close()
        return jsonify({"ok": False, "error": "این شناسه صرافی قبلاً ثبت شده است."}), 400

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
    INSERT INTO exchanges (
        id, name, admin_ids,
        rate_amd_to_irt, rate_irt_to_amd,
        rate_usd_to_irt, rate_irt_to_usd,
        rate_usd_to_amd, rate_amd_to_usd,
        holder_amd, card_amd, bank_amd,
        holder_irt, card_irt, sheba_irt, account_irt, bank_irt,
        holder_usd, card_usd, card_type_usd,
        min_amd, max_amd, min_irt, max_irt, min_usd, max_usd,
        address, working_hours, phone, whatsapp, telegram,
        is_active, created_at
    ) VALUES (?, ?, ?, 750, 900, 280000, 310000, 360, 375, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 100, 1000000, 10000, 7500000000, 1, 25000, ?, ?, ?, ?, ?, 1, ?)
    """, (
        ex_id,
        name,
        admin_ids,
        "تست درام",
        "2050 0011 2233 4455",
        "Ameria بانک",
        "تست تومان",
        "6104 3377 1234 5678",
        "IR120120000000009876543210",
        "4712345678",
        "بانک ملت",
        "تست دلار",
        "4000 1234 5678 9010",
        "VISA کارت",
        "آدرس نمونه",
        "همه‌روزه ۹:۰۰ تا ۲۱:۰۰",
        "+37411111111",
        "wa.me/+37494055428",
        "t.me/shokouhi61",
        now,
    ))
    conn.commit()
    created = cur.execute("SELECT * FROM exchanges WHERE id = ?", (ex_id,)).fetchone()
    conn.close()

    return jsonify({"ok": True, "exchange": serialize_exchange(created)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
    
