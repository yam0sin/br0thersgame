import os
import random
import secrets
import math
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent

CASE_PRICE = 10
TARGET_MULT = 0.60   # было выше — это и даёт “в плюс”
SIGMA = 0.60         # меньше разброс -> реже дорогие
WINDOW_START = 0.20
WINDOW_STEP = 0.15
WINDOW_MAX = 1.00
TARGET_BETA = 0.8
UPGRADE_EDGE = 0.9
RARITIES = [
    "Ширпотреб",
    "Промышленное",
    "Армейское",
    "Запрещённое",
    "Засекреченное",
    "Тайное",
]

ALLOWED_AVATAR_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_AVATAR_SIZE_MB = 3

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(16))
db_url = os.getenv("DATABASE_URL")
if db_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    sqlite_name = os.getenv("SQLITE_DB", "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / sqlite_name}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(BASE_DIR / "static" / "uploads" / "avatars")
app.config["MAX_CONTENT_LENGTH"] = MAX_AVATAR_SIZE_MB * 1024 * 1024
app.config["ENV"] = os.getenv("FLASK_ENV", "production")
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Integer, default=0)
    avatar_path = db.Column(db.String(255), default="")
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Skin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    quality = db.Column(db.String(80), nullable=False)
    rarity = db.Column(db.String(80), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)


class DropHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    skin_id = db.Column(db.Integer, db.ForeignKey("skin.id"), nullable=False)
    skin_name_snapshot = db.Column(db.String(120), nullable=False)
    price_snapshot = db.Column(db.Integer, nullable=False)
    rarity_snapshot = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    skin_id = db.Column(db.Integer, db.ForeignKey("skin.id"), nullable=False)
    status = db.Column(
        db.String(32),
        default="owned",
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    price_snapshot = db.Column(db.Integer, nullable=False)


class UpgradeHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    from_name_snapshot = db.Column(db.String(120), nullable=False)
    from_price_snapshot = db.Column(db.Integer, nullable=False)
    to_name_snapshot = db.Column(db.String(120), nullable=False)
    to_price_snapshot = db.Column(db.Integer, nullable=False)
    chance = db.Column(db.Float, nullable=False)
    result = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class PromoCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    max_uses_total = db.Column(db.Integer, nullable=False)
    uses_count = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class PromoRedemption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    promo_id = db.Column(db.Integer, db.ForeignKey("promo_code.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    redeemed_at = db.Column(db.DateTime, default=utcnow)
    amount_snapshot = db.Column(db.Integer, nullable=False)


class WithdrawalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_item_id = db.Column(
        db.Integer, db.ForeignKey("inventory_item.id"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(32), default="requested", nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    username_snapshot = db.Column(db.String(80), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Ledger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    event_type = db.Column(db.String(80), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    skin_id = db.Column(db.Integer, db.ForeignKey("skin.id"))
    item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"))
    delta_balance = db.Column(db.Integer, default=0)
    delta_pool_count = db.Column(db.Integer, default=0)
    message = db.Column(db.String(500), default="")
    meta_json = db.Column(db.Text)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def ensure_admin_user():
    admin_username = os.getenv("ADMIN_USERNAME", "yamosin")
    admin_password = os.getenv("ADMIN_PASSWORD", "598598598z")

    target_user = User.query.filter_by(username=admin_username).first()
    existing_admin = User.query.filter_by(is_admin=True).first()

    if target_user:
        target_user.is_admin = True
        target_user.password_hash = generate_password_hash(admin_password)
        if existing_admin and existing_admin.id != target_user.id:
            existing_admin.is_admin = False
        db.session.commit()
        return

    if existing_admin:
        existing_admin.username = admin_username
        existing_admin.password_hash = generate_password_hash(admin_password)
        existing_admin.is_admin = True
        db.session.commit()
        return

    admin = User(
        username=admin_username,
        password_hash=generate_password_hash(admin_password),
        balance=0,
        is_admin=True,
    )
    db.session.add(admin)
    db.session.commit()



def allowed_avatar_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_AVATAR_EXTENSIONS


def get_user_stats(user_id):
    openings_count = (
        db.session.query(func.count(DropHistory.id))
        .filter(DropHistory.user_id == user_id)
        .scalar()
        or 0
    )
    received = (
        db.session.query(func.coalesce(func.sum(DropHistory.price_snapshot), 0))
        .filter(DropHistory.user_id == user_id)
        .scalar()
        or 0
    )
    spent = openings_count * CASE_PRICE
    profit = received - spent
    return {
        "openings_count": openings_count,
        "received": received,
        "spent": spent,
        "profit": profit,
    }


def log_ledger(
    event_type,
    actor_user_id=None,
    target_user_id=None,
    skin_id=None,
    item_id=None,
    delta_balance=0,
    delta_pool_count=0,
    message="",
    meta_json=None,
):
    entry = Ledger(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        skin_id=skin_id,
        item_id=item_id,
        delta_balance=delta_balance,
        delta_pool_count=delta_pool_count,
        message=message,
        meta_json=meta_json,
    )
    db.session.add(entry)


def pick_skin():
    candidates = Skin.query.filter(Skin.count > 0, Skin.price > 0).all()
    if not candidates:
        return None
    prices = [skin.price for skin in candidates]
    min_price = min(prices)
    max_price = max(prices)
    if min_price <= 0 or max_price <= 0:
        return random.choice(candidates)
    mu = math.log(CASE_PRICE * TARGET_MULT)
    target_price = math.exp(random.gauss(mu, SIGMA))
    target_price = max(min_price, min(max_price, target_price))

    window_pct = WINDOW_START
    band = []
    while window_pct <= WINDOW_MAX and not band:
        low = target_price * (1 - window_pct)
        high = target_price * (1 + window_pct)
        band = [skin for skin in candidates if low <= skin.price <= high]
        if band:
            break
        window_pct += WINDOW_STEP

    if not band:
        return min(
            candidates,
            key=lambda skin: abs(skin.price - target_price),
        )

    weights = [
        1 / (abs(skin.price - target_price) + 1)
        for skin in band
    ]
    return random.choices(band, weights=weights, k=1)[0]


def admin_required(view_func):
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            flash("Доступ только для администратора.", "error")
            return redirect(url_for("index"))
        return view_func(*args, **kwargs)

    wrapper.__name__ = view_func.__name__
    return wrapper


@app.context_processor
def inject_globals():
    return {
        "case_price": CASE_PRICE,
        "rarities": RARITIES,
    }


@app.route("/")
def index():
    skins = Skin.query.all()
    skins_data = [
        {
            "id": skin.id,
            "name": skin.name,
            "quality": skin.quality,
            "rarity": skin.rarity,
            "image_url": skin.image_url,
            "price": skin.price,
        }
        for skin in skins
    ]
    last_drops = (
        db.session.query(DropHistory, User, Skin)
        .join(User, DropHistory.user_id == User.id)
        .outerjoin(Skin, DropHistory.skin_id == Skin.id)
        .order_by(DropHistory.created_at.desc())
        .limit(10)
        .all()
    )
    chat_messages = ChatMessage.query.order_by(ChatMessage.id.desc()).limit(20).all()
    return render_template(
        "index.html",
        skins_data=skins_data,
        last_drops=last_drops,
        chat_messages=chat_messages,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Заполните логин и пароль.", "error")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("Этот логин уже занят.", "error")
            return redirect(url_for("register"))
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            balance=0,
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Неверный логин или пароль.", "error")
            return redirect(url_for("login"))
        login_user(user)
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        if "avatar" not in request.files:
            flash("Файл не выбран.", "error")
            return redirect(url_for("profile"))
        avatar = request.files["avatar"]
        if avatar.filename == "":
            flash("Файл не выбран.", "error")
            return redirect(url_for("profile"))
        if not allowed_avatar_file(avatar.filename):
            flash("Недопустимый формат файла.", "error")
            return redirect(url_for("profile"))
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        safe_name = secure_filename(avatar.filename)
        filename = f"{current_user.id}_{int(utcnow().timestamp())}_{safe_name}"
        filepath = Path(app.config["UPLOAD_FOLDER"]) / filename
        avatar.save(filepath)
        current_user.avatar_path = f"uploads/avatars/{filename}"
        db.session.commit()
        flash("Аватар обновлён.", "success")
        return redirect(url_for("profile"))

    inventory_items = (
        db.session.query(InventoryItem, Skin)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .filter(
            InventoryItem.user_id == current_user.id,
            InventoryItem.status == "owned",
        )
        .order_by(InventoryItem.created_at.desc())
        .all()
    )
    history = (
        DropHistory.query.filter_by(user_id=current_user.id)
        .order_by(DropHistory.created_at.desc())
        .all()
    )
    stats = get_user_stats(current_user.id)
    stats = {
        "openings_count": stats["openings_count"],
        "spent": stats["spent"],
        "received": stats["received"],
    }
    return render_template(
        "profile.html",
        inventory_items=inventory_items,
        history=history,
        stats=stats,
    )


@app.route("/upgrade")
@login_required
def upgrade():
    inventory_items = (
        db.session.query(InventoryItem, Skin)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .filter(
            InventoryItem.user_id == current_user.id,
            InventoryItem.status == "owned",
        )
        .order_by(InventoryItem.created_at.desc())
        .all()
    )
    burned_items = (
        db.session.query(InventoryItem, Skin)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .filter(
            InventoryItem.user_id == current_user.id,
            InventoryItem.status == "burned",
        )
        .order_by(InventoryItem.created_at.desc())
        .all()
    )
    return render_template(
        "upgrade.html",
        inventory_items=inventory_items,
        burned_items=burned_items,
    )


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


@app.route("/upgrade/pick_target", methods=["POST"])
@login_required
def upgrade_pick_target():
    from_item_id = request.form.get("from_item_id", type=int)
    if not from_item_id:
        return jsonify({"error": "Не выбран предмет."}), 400
    from_item = InventoryItem.query.filter_by(
        id=from_item_id,
        user_id=current_user.id,
        status="owned",
    ).first()
    if not from_item:
        return jsonify({"error": "Предмет не найден."}), 404

    from_skin = db.session.get(Skin, from_item.skin_id)
    if not from_skin:
        return jsonify({"error": "Скин не найден."}), 404

    from_price = from_item.price_snapshot or from_skin.price
    candidates = Skin.query.filter(
        Skin.count > 0,
        Skin.price > from_price,
    ).all()
    if not candidates:
        return jsonify({"error": "Нет доступных целей."}), 400

    weights = [1 / (skin.price**TARGET_BETA) for skin in candidates]
    target_skin = random.choices(candidates, weights=weights, k=1)[0]

    chance = (from_price / target_skin.price) * UPGRADE_EDGE
    chance = _clamp(chance, 0.01, 0.95)

    return jsonify(
        {
            "target_skin": {
                "id": target_skin.id,
                "name": target_skin.name,
                "quality": target_skin.quality,
                "rarity": target_skin.rarity,
                "image_url": target_skin.image_url,
                "price": target_skin.price,
            },
            "chance": chance,
        }
    )


@app.route("/upgrade/attempt", methods=["POST"])
@login_required
def upgrade_attempt():
    from_item_id = request.form.get("from_item_id", type=int)
    target_skin_id = request.form.get("target_skin_id", type=int)
    if not from_item_id or not target_skin_id:
        return jsonify({"error": "Некорректные данные."}), 400

    from_item = InventoryItem.query.filter_by(
        id=from_item_id,
        user_id=current_user.id,
        status="owned",
    ).first()
    if not from_item:
        return jsonify({"error": "Предмет не найден."}), 404

    from_skin = db.session.get(Skin, from_item.skin_id) if from_item.skin_id else None
    if not from_skin:
        history = (
            DropHistory.query.filter_by(user_id=current_user.id)
            .filter(DropHistory.price_snapshot == from_item.price_snapshot)
            .order_by(DropHistory.created_at.desc())
            .first()
        )
        if history:
            from_skin = Skin.query.filter_by(name=history.skin_name_snapshot).first()
    if not from_skin:
        return jsonify({"error": "Скин не найден."}), 404

    target_skin = db.session.get(Skin, target_skin_id)
    if not target_skin:
        return jsonify({"error": "Скин не найден."}), 404

    from_price = from_item.price_snapshot or from_skin.price
    if target_skin.count <= 0 or target_skin.price <= from_price:
        return jsonify({"error": "Цель недоступна."}), 400

    chance = (from_price / target_skin.price) * UPGRADE_EDGE
    chance = _clamp(chance, 0.01, 0.95)
    roll = random.random()
    success = roll <= chance

    from_skin.count += 1
    from_item.status = "consumed"

    if success:
        target_skin.count -= 1
        new_item = InventoryItem(
            user_id=current_user.id,
            skin_id=target_skin.id,
            status="owned",
            price_snapshot=target_skin.price,
        )
        db.session.add(new_item)
        result = "success"
    else:
        result = "fail"

    history = UpgradeHistory(
        user_id=current_user.id,
        from_name_snapshot=from_skin.name,
        from_price_snapshot=from_price,
        to_name_snapshot=target_skin.name,
        to_price_snapshot=target_skin.price,
        chance=chance,
        result=result,
    )
    db.session.add(history)

    message = (
        f"upgrade {from_skin.name} {from_price}★ -> "
        f"{target_skin.name} {target_skin.price}★, "
        f"chance {chance:.3f}, result {result}"
    )
    log_ledger(
        event_type="upgrade_in",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        skin_id=from_skin.id,
        item_id=from_item.id,
        delta_pool_count=1,
        message=message,
    )
    if success:
        log_ledger(
            event_type="upgrade_out",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            skin_id=target_skin.id,
            item_id=new_item.id,
            delta_pool_count=-1,
            message=message,
        )

    db.session.commit()

    response = {
        "result": result,
        "chance": chance,
    }
    if success:
        response["new_item"] = {
            "id": new_item.id,
            "name": target_skin.name,
            "quality": target_skin.quality,
            "rarity": target_skin.rarity,
            "image_url": target_skin.image_url,
            "price": target_skin.price,
        }
    return jsonify(response)



@app.route("/topup", methods=["GET", "POST"])
@login_required
def topup():
    if request.method == "POST":
        code_input = request.form.get("code", "").strip()
        promo = PromoCode.query.filter(
            PromoCode.code == code_input,
        ).first()
        if not promo:
            flash("Промокод не найден.", "error")
            return redirect(url_for("topup"))
        if not promo.enabled:
            flash("Промокод неактивен.", "error")
            return redirect(url_for("topup"))
        if promo.uses_count >= promo.max_uses_total:
            flash("Лимит промокода исчерпан.", "error")
            return redirect(url_for("topup"))
        already_used = PromoRedemption.query.filter_by(
            promo_id=promo.id,
            user_id=current_user.id,
        ).first()
        if already_used:
            flash("Вы уже использовали этот промокод.", "error")
            return redirect(url_for("topup"))
        promo.uses_count += 1
        redemption = PromoRedemption(
            promo_id=promo.id,
            user_id=current_user.id,
            amount_snapshot=promo.amount,
        )
        current_user.balance += promo.amount
        db.session.add(redemption)
        db.session.commit()
        flash(f"Баланс пополнен на {promo.amount}★.", "success")
        return redirect(url_for("topup"))
    return render_template("topup.html")


@app.route("/open_case", methods=["POST"])
@login_required
def open_case():
    if current_user.balance < CASE_PRICE:
        return jsonify({"error": "Недостаточно средств."}), 400
    skin = pick_skin()
    if not skin:
        return jsonify({"error": "Нет доступных скинов."}), 400
    if skin.count <= 0:
        return jsonify({"error": "Скин закончился."}), 400

    current_user.balance -= CASE_PRICE
    skin.count -= 1

    drop = DropHistory(
        user_id=current_user.id,
        skin_id=skin.id,
        skin_name_snapshot=skin.name,
        price_snapshot=skin.price,
        rarity_snapshot=skin.rarity,
    )
    inventory_item = InventoryItem(
        user_id=current_user.id,
        skin_id=skin.id,
        status="owned",
        price_snapshot=skin.price,
    )
    db.session.add(drop)
    db.session.add(inventory_item)
    db.session.flush()
    log_ledger(
        event_type="open_case",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        skin_id=skin.id,
        item_id=inventory_item.id,
        delta_balance=-CASE_PRICE,
        delta_pool_count=-1,
        message=f"case drop {skin.name} {skin.price}\u2605",
    )
    db.session.commit()

    return jsonify(
        {
            "drop_id": drop.id,
            "inventory_item_id": inventory_item.id,
            "skin": {
                "name": skin.name,
                "quality": skin.quality,
                "rarity": skin.rarity,
                "image_url": skin.image_url,
                "price": skin.price,
            },
            "balance": current_user.balance,
        }
    )


@app.route("/sell/<int:item_id>", methods=["POST"])
@login_required
def sell_item(item_id):
    item = InventoryItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item or item.status != "owned":
        flash("Нельзя продать этот предмет.", "error")
        return redirect(url_for("profile"))
    skin = db.session.get(Skin, item.skin_id)
    if skin:
        skin.count += 1
    item.status = "sold"
    current_user.balance += item.price_snapshot
    log_ledger(
        event_type="sell_item",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        skin_id=item.skin_id,
        item_id=item.id,
        delta_balance=item.price_snapshot,
        delta_pool_count=1,
        message=f"sell {skin.name if skin else item.skin_id} {item.price_snapshot}\u2605",
    )
    db.session.commit()
    flash(f"Предмет продан за {item.price_snapshot}★.", "success")
    return redirect(url_for("profile"))


@app.route("/withdraw/<int:item_id>", methods=["POST"])
@login_required
def withdraw_item(item_id):
    item = InventoryItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item or item.status != "owned":
        flash("Нельзя вывести этот предмет.", "error")
        return redirect(url_for("profile"))
    skin = db.session.get(Skin, item.skin_id)
    item.status = "withdraw_requested"
    withdrawal = WithdrawalRequest(
        inventory_item_id=item.id,
        user_id=current_user.id,
        status="requested",
    )
    db.session.add(withdrawal)
    log_ledger(
        event_type="withdraw_request",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        skin_id=item.skin_id,
        item_id=item.id,
        message=f"withdraw request {skin.name if skin else item.skin_id}",
    )
    db.session.commit()
    flash("Заявка на вывод создана.", "success")
    return redirect(url_for("profile"))



@app.route("/chat/send", methods=["POST"])
@login_required
def chat_send():
    message = request.form.get("message", "").strip()
    if not message:
        return jsonify({"error": "Пустое сообщение."}), 400
    if len(message) > 500:
        return jsonify({"error": "Сообщение слишком длинное."}), 400
    chat_message = ChatMessage(
        user_id=current_user.id,
        username_snapshot=current_user.username,
        message=message,
    )
    db.session.add(chat_message)
    db.session.commit()
    return jsonify(
        {
            "id": chat_message.id,
            "username": chat_message.username_snapshot,
            "message": chat_message.message,
            "created_at": chat_message.created_at.isoformat(),
        }
    )


@app.route("/chat/poll")
def chat_poll():
    since_id = request.args.get("since_id", type=int)
    query = ChatMessage.query
    if since_id:
        query = query.filter(ChatMessage.id > since_id)
    messages = query.order_by(ChatMessage.created_at.desc()).limit(50).all()
    messages.reverse()
    return jsonify(
        [
            {
                "id": msg.id,
                "username": msg.username_snapshot,
                "message": msg.message,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ]
    )



@app.route("/admin/chat/clear", methods=["POST"])
@admin_required
def admin_chat_clear():
    ChatMessage.query.delete(synchronize_session=False)
    db.session.commit()
    flash("Чат очищен", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


@app.route("/admin/stats")
@admin_required
def admin_stats():
    pool_total_types = db.session.query(func.count(Skin.id)).scalar() or 0
    pool_units = (
        db.session.query(func.coalesce(func.sum(Skin.count), 0)).scalar() or 0
    )
    pool_value = (
        db.session.query(func.coalesce(func.sum(Skin.price * Skin.count), 0))
        .scalar()
        or 0
    )
    pool_avg_price = db.session.query(func.avg(Skin.price)).scalar()
    pool_weighted_avg = None
    if pool_units > 0:
        pool_weighted_avg = pool_value / pool_units

    total_openings = (
        db.session.query(func.count(DropHistory.id)).scalar() or 0
    )
    avg_drop = (
        db.session.query(func.avg(func.coalesce(DropHistory.price_snapshot, Skin.price)))
        .select_from(DropHistory)
        .join(Skin, DropHistory.skin_id == Skin.id, isouter=True)
        .scalar()
    )
    if total_openings == 0:
        avg_drop = None

    return render_template(
        "admin/stats.html",
        pool_stats={
            "total_types": pool_total_types,
            "units": pool_units,
            "value": pool_value,
            "avg_price": pool_avg_price,
            "weighted_avg": pool_weighted_avg,
        },
        drop_stats={
            "total_openings": total_openings,
            "avg_drop": avg_drop,
        },
    )


@app.route("/admin/logs")
@admin_required
def admin_logs():
    event_type = request.args.get("type", "").strip()
    user_query = request.args.get("user", "").strip()
    search = request.args.get("q", "").strip()
    page = request.args.get("page", type=int) or 1
    per_page = 50
    base_params = request.args.to_dict()
    base_params.pop("page", None)

    query = Ledger.query
    if event_type:
        query = query.filter(Ledger.event_type == event_type)
    if search:
        query = query.filter(Ledger.message.ilike(f"%{search}%"))
    if user_query:
        user = None
        if user_query.isdigit():
            user = db.session.get(User, int(user_query))
        if not user:
            user = User.query.filter(User.username == user_query).first()
        if user:
            query = query.filter(
                or_(
                    Ledger.actor_user_id == user.id,
                    Ledger.target_user_id == user.id,
                )
            )
        else:
            query = query.filter(Ledger.id == -1)

    total = query.count()
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    logs = (
        query.order_by(Ledger.created_at.desc(), Ledger.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    prev_url = None
    next_url = None
    if page > 1:
        prev_url = url_for("admin_logs", **base_params, page=page - 1)
    if page < pages:
        next_url = url_for("admin_logs", **base_params, page=page + 1)

    user_ids = set()
    for entry in logs:
        if entry.actor_user_id:
            user_ids.add(entry.actor_user_id)
        if entry.target_user_id:
            user_ids.add(entry.target_user_id)
    users = User.query.filter(User.id.in_(user_ids)).all() if user_ids else []
    users_by_id = {user.id: user for user in users}

    event_types = [
        row[0]
        for row in db.session.query(Ledger.event_type)
        .distinct()
        .order_by(Ledger.event_type)
        .all()
    ]

    return render_template(
        "admin/logs.html",
        logs=logs,
        users_by_id=users_by_id,
        event_types=event_types,
        current_filters={
            "type": event_type,
            "user": user_query,
            "q": search,
        },
        prev_url=prev_url,
        next_url=next_url,
        page=page,
        pages=pages,
        total=total,
        per_page=per_page,
    )


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    users_with_stats = []
    for user in users:
        stats = get_user_stats(user.id)
        users_with_stats.append((user, stats))
    return render_template("admin/users.html", users_with_stats=users_with_stats)


@app.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    if current_user.id == user_id:
        flash("Нельзя менять роль самому себе.", "error")
        return redirect(url_for("admin_users"))
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("admin_users"))
    if user.is_admin:
        admins_count = User.query.filter_by(is_admin=True).count()
        if admins_count <= 1:
            flash("Нельзя снять админку с последнего администратора.", "error")
            return redirect(url_for("admin_users"))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash("Роль пользователя обновлена.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if current_user.id == user_id:
        flash("Нельзя удалить самого себя.", "error")
        return redirect(url_for("admin_users"))
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("admin_users"))

    WithdrawalRequest.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )
    InventoryItem.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )
    PromoRedemption.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )
    DropHistory.query.filter_by(user_id=user_id).delete(
        synchronize_session=False
    )
    ChatMessage.query.filter_by(user_id=user_id).update(
        {"username_snapshot": "deleted"}, synchronize_session=False
    )
    db.session.delete(user)
    db.session.commit()
    flash("Пользователь удалён.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>")
@admin_required
def admin_user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "error")
        return redirect(url_for("admin_users"))
    history = (
        DropHistory.query.filter_by(user_id=user_id)
        .order_by(DropHistory.created_at.desc())
        .all()
    )
    inventory_items = (
        db.session.query(InventoryItem, Skin)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .filter(InventoryItem.user_id == user_id)
        .order_by(InventoryItem.created_at.desc())
        .all()
    )
    withdrawals = (
        db.session.query(WithdrawalRequest, InventoryItem, Skin)
        .join(InventoryItem, WithdrawalRequest.inventory_item_id == InventoryItem.id)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .filter(WithdrawalRequest.user_id == user_id)
        .all()
    )
    stats = get_user_stats(user_id)
    return render_template(
        "admin/user_detail.html",
        user=user,
        history=history,
        inventory_items=inventory_items,
        withdrawals=withdrawals,
        stats=stats,
    )


@app.route("/admin/skins", methods=["GET", "POST"])
@admin_required
def admin_skins():
    def split_name(raw_name):
        raw = (raw_name or "").strip()
        if " | " in raw:
            weapon_part, pattern_part = raw.split(" | ", 1)
            return weapon_part.strip() or "(без оружия)", pattern_part.strip()
        return "(без оружия)", raw

    def build_name(weapon, pattern, fallback):
        weapon_part = (weapon or "").strip()
        pattern_part = (pattern or "").strip()
        if weapon_part and pattern_part:
            return f"{weapon_part} | {pattern_part}"
        if pattern_part:
            return pattern_part
        if weapon_part:
            return weapon_part
        return (fallback or "").strip()

    if request.method == "POST":
        weapon = request.form.get("weapon", "").strip()
        pattern = request.form.get("pattern", "").strip()
        name = build_name(weapon, pattern, request.form.get("name", ""))
        quality = request.form.get("quality", "").strip()
        rarity = request.form.get("rarity", "").strip()
        image_url = request.form.get("image_url", "").strip()
        price = request.form.get("price", type=int)
        count = request.form.get("count", type=int)
        if not all([name, quality, rarity, image_url]) or price is None or count is None:
            flash("Заполните все поля.", "error")
            return redirect(url_for("admin_skins"))
        skin = Skin(
            name=name,
            quality=quality,
            rarity=rarity,
            image_url=image_url,
            price=price,
            count=count,
        )
        db.session.add(skin)
        db.session.commit()
        flash("Скин добавлен.", "success")
        return redirect(url_for("admin_skins", **request.args))
    q = request.args.get("q", "").strip()
    weapon_filter = request.args.get("weapon", "").strip()
    quality_filter = request.args.get("quality", "").strip()
    rarity_filter = request.args.get("rarity", "").strip()
    in_stock = request.args.get("in_stock", "").strip()
    sort_key = request.args.get("sort", "").strip() or "id"
    sort_order = request.args.get("order", "").strip() or "desc"
    page = max(request.args.get("page", type=int) or 1, 1)
    per_page = 50

    query = Skin.query

    if q:
        query = query.filter(Skin.name.ilike(f"%{q}%"))
    if weapon_filter:
        if weapon_filter == "(Р±РµР· РѕСЂСѓР¶РёСЏ)":
            query = query.filter(~Skin.name.contains(" | "))
        else:
            query = query.filter(
                (Skin.name == weapon_filter)
                | (Skin.name.ilike(f"{weapon_filter} | %"))
            )
    if quality_filter:
        query = query.filter(Skin.quality == quality_filter)
    if rarity_filter:
        query = query.filter(Skin.rarity == rarity_filter)
    if in_stock == "1":
        query = query.filter(Skin.count > 0)

    sort_map = {
        "price": Skin.price,
        "count": Skin.count,
        "name": Skin.name,
        "id": Skin.id,
    }
    sort_column = sort_map.get(sort_key, Skin.id)
    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    total = query.count()
    skins = query.offset((page - 1) * per_page).limit(per_page).all()

    all_skins = Skin.query.order_by(Skin.id.desc()).all()
    weapons_set = set()
    patterns_by_weapon = {}
    for skin in all_skins:
        weapon, pattern = split_name(skin.name)
        weapons_set.add(weapon)
        patterns_by_weapon.setdefault(weapon, set()).add(pattern)
    weapons = sorted(weapons_set)
    patterns_by_weapon = {
        weapon: sorted(list(patterns))
        for weapon, patterns in patterns_by_weapon.items()
    }
    quality_values = sorted(
        {skin.quality for skin in all_skins if skin.quality}
    )
    return render_template(
        "admin/skins.html",
        skins=skins,
        weapons=weapons,
        patterns_by_weapon=patterns_by_weapon,
        quality_values=quality_values,
        q=q,
        weapon_filter=weapon_filter,
        quality_filter=quality_filter,
        rarity_filter=rarity_filter,
        in_stock=in_stock,
        sort_key=sort_key,
        sort_order=sort_order,
        page=page,
        per_page=per_page,
        total=total,
    )


@app.route("/admin/skins/update/<int:skin_id>", methods=["POST"])
@admin_required
def admin_skins_update(skin_id):
    skin = db.session.get(Skin, skin_id)
    if not skin:
        flash("Скин не найден.", "error")
        return redirect(url_for("admin_skins"))
    weapon = request.form.get("weapon", "").strip()
    pattern = request.form.get("pattern", "").strip()
    name_fallback = request.form.get("name", "").strip()
    if weapon and pattern:
        skin.name = f"{weapon} | {pattern}"
    elif pattern:
        skin.name = pattern
    elif weapon:
        skin.name = weapon
    else:
        skin.name = name_fallback
    skin.quality = request.form.get("quality", "").strip()
    skin.rarity = request.form.get("rarity", "").strip()
    skin.image_url = request.form.get("image_url", "").strip()
    skin.price = request.form.get("price", type=int)
    skin.count = request.form.get("count", type=int)
    if not all([skin.name, skin.quality, skin.rarity, skin.image_url]):
        flash("Заполните все поля.", "error")
        return redirect(url_for("admin_skins"))
    db.session.commit()
    flash("Скин обновлён.", "success")
    return redirect(url_for("admin_skins"))


@app.route("/admin/skins/delete/<int:skin_id>", methods=["POST"])
@admin_required
def admin_skins_delete(skin_id):
    skin = db.session.get(Skin, skin_id)
    if not skin:
        flash("Скин не найден.", "error")
        return redirect(url_for("admin_skins"))
    db.session.delete(skin)
    db.session.commit()
    flash("Скин удалён.", "success")
    return redirect(url_for("admin_skins"))


@app.route("/admin/promocodes", methods=["GET", "POST"])
@admin_required
def admin_promocodes():
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        amount = request.form.get("amount", type=int)
        max_uses_total = request.form.get("max_uses_total", type=int)
        if not code or amount is None or max_uses_total is None:
            flash("Заполните все поля.", "error")
            return redirect(url_for("admin_promocodes"))
        if PromoCode.query.filter_by(code=code).first():
            flash("Промокод уже существует.", "error")
            return redirect(url_for("admin_promocodes"))
        promo = PromoCode(
            code=code,
            amount=amount,
            max_uses_total=max_uses_total,
            enabled=True,
        )
        db.session.add(promo)
        db.session.commit()
        flash("Промокод создан.", "success")
        return redirect(url_for("admin_promocodes"))

    promocodes = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    code_filter = request.args.get("code", "").strip()
    redemptions_query = (
        db.session.query(PromoRedemption, User, PromoCode)
        .join(User, PromoRedemption.user_id == User.id)
        .join(PromoCode, PromoRedemption.promo_id == PromoCode.id)
    )
    if code_filter:
        redemptions_query = redemptions_query.filter(PromoCode.code == code_filter)
    redemptions = (
        redemptions_query.order_by(PromoRedemption.redeemed_at.desc()).limit(50).all()
    )
    return render_template(
        "admin/promocodes.html",
        promocodes=promocodes,
        redemptions=redemptions,
        code_filter=code_filter,
    )




@app.route("/admin/promocodes/toggle/<int:promo_id>", methods=["POST"])
@admin_required
def admin_promocodes_toggle(promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if not promo:
        flash("Промокод не найден.", "error")
        return redirect(url_for("admin_promocodes", **request.args))
    promo.enabled = not promo.enabled
    db.session.commit()
    if promo.enabled:
        flash("Промокод активирован.", "success")
    else:
        flash("Промокод деактивирован.", "success")
    return redirect(url_for("admin_promocodes", **request.args))


@app.route("/admin/promocodes/delete/<int:promo_id>", methods=["POST"])
@admin_required
def admin_promocodes_delete(promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if not promo:
        flash("Промокод не найден.", "error")
        return redirect(url_for("admin_promocodes", **request.args))
    PromoRedemption.query.filter_by(promo_id=promo_id).delete(synchronize_session=False)
    db.session.delete(promo)
    db.session.commit()
    flash("Промокод удалён.", "success")
    return redirect(url_for("admin_promocodes", **request.args))


@app.route("/admin/withdrawals", methods=["GET", "POST"])
@admin_required
def admin_withdrawals():
    if request.method == "POST":
        request_id = request.form.get("request_id", type=int)
        withdrawal = db.session.get(WithdrawalRequest, request_id)
        if not withdrawal:
            flash("Заявка не найдена.", "error")
            return redirect(url_for("admin_withdrawals"))
        withdrawal.status = "withdrawn"
        item = db.session.get(InventoryItem, withdrawal.inventory_item_id)
        if item:
            item.status = "withdrawn"
        skin = db.session.get(Skin, item.skin_id) if item else None
        log_ledger(
            event_type="withdraw_done",
            actor_user_id=current_user.id,
            target_user_id=withdrawal.user_id,
            skin_id=item.skin_id if item else None,
            item_id=item.id if item else None,
            message=f"withdraw done {skin.name if skin else ''}",
        )
        db.session.commit()
        flash("Заявка отмечена как выведенная.", "success")
        return redirect(url_for("admin_withdrawals"))

    withdrawals = (
        db.session.query(WithdrawalRequest, User, InventoryItem, Skin)
        .join(User, WithdrawalRequest.user_id == User.id)
        .join(InventoryItem, WithdrawalRequest.inventory_item_id == InventoryItem.id)
        .join(Skin, InventoryItem.skin_id == Skin.id)
        .order_by(WithdrawalRequest.created_at.desc())
        .all()
    )
    return render_template("admin/withdrawals.html", withdrawals=withdrawals)


@app.route("/admin/withdrawals/sell/<int:request_id>", methods=["POST"])
@admin_required
def admin_withdrawals_sell(request_id):
    withdrawal = db.session.get(WithdrawalRequest, request_id)
    if not withdrawal:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("admin_withdrawals"))
    if withdrawal.status == "withdrawn":
        flash("Заявка уже выведена.", "error")
        return redirect(url_for("admin_withdrawals"))
    if withdrawal.status == "sold_by_admin":
        flash("Заявка уже продана.", "error")
        return redirect(url_for("admin_withdrawals"))
    item = db.session.get(InventoryItem, withdrawal.inventory_item_id)
    user = db.session.get(User, withdrawal.user_id)
    skin = db.session.get(Skin, item.skin_id) if item else None
    if not item or not user:
        flash("Связанные данные не найдены.", "error")
        return redirect(url_for("admin_withdrawals"))

    payout = item.price_snapshot
    if not payout and skin:
        payout = skin.price
    payout = payout or 0
    user.balance += payout
    if skin:
        skin.count += 1
    item.status = "sold"
    withdrawal.status = "sold_by_admin"
    log_ledger(
        event_type="withdraw_sell",
        actor_user_id=current_user.id,
        target_user_id=user.id,
        skin_id=item.skin_id,
        item_id=item.id,
        delta_balance=payout,
        delta_pool_count=1,
        message=f"withdraw sell {skin.name if skin else item.skin_id} {payout}\u2605",
    )
    db.session.commit()
    flash("Заявка продана администратором.", "success")
    return redirect(url_for("admin_withdrawals"))


@app.errorhandler(413)
def request_entity_too_large(error):
    flash(f"Файл слишком большой. Лимит {MAX_AVATAR_SIZE_MB}MB.", "error")
    return redirect(url_for("profile"))


def setup_app():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.create_all()
    ensure_admin_user()


with app.app_context():
    setup_app()


if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
