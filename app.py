from flask import Flask, render_template, request
import sqlite3
import requests
import hashlib
from datetime import datetime, timezone

app = Flask(__name__)

DB_NAME = "astronomy.db"

AVAILABLE_PLANETS = [
    "mercury", "venus", "mars", "jupiter", "saturn",
    "uranus", "neptune", "pluto", "moon", "sun"
]

CITIES = {
    "Paris": (48.8566, 2.3522),
    "Moscow": (55.7558, 37.6173),
    "Tokyo": (35.6895, 139.6917),
    "Beijing": (39.9042, 116.4074),
    "New_York": (40.7128, -74.0060),
    "Los_Angeles": (34.0522, -118.2437),
    "Sydney": (-33.8688, 151.2093)
}

# -------------------------
# Инициализация базы данных
# -------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS celestial_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            city TEXT NOT NULL,
            ra REAL NOT NULL,
            dec REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            key_hash TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# -----------------------------------------
# Получение координат (Visible Planets API)
# -----------------------------------------
def fetch_planetary_data_visible(body, latitude, longitude):
    url = "https://api.visibleplanets.dev/v3"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "showCoords": "true"
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    objects = data.get("data", [])
    if not objects:
        raise ValueError("API не вернул ни одного объекта")

    # Пытаемся найти выбранную планету
    for obj in objects:
        if obj.get("name", "").lower() == body.lower():
            ra = obj["rightAscension"]["raw"] * 15.0
            dec = obj["declination"]["raw"]
            return ra, dec, obj["name"]

    # Если не нашли — берём первый доступный объект
    fallback = objects[0]
    ra = fallback["rightAscension"]["raw"] * 15.0
    dec = fallback["declination"]["raw"]

    return ra, dec, fallback["name"]



# -----------------------------
# Запись астрономических данных
# -----------------------------
def insert_data(body, city, ra, dec):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO celestial_data (body, city, ra, dec, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        body, city, ra, dec,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()


# ----------------------------------
# Генерация криптографического ключа
# ----------------------------------
def generate_key(body):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT city, ra, dec, timestamp
        FROM celestial_data
        WHERE body = ?
        ORDER BY id DESC
    """, (body,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise ValueError("Нет данных для генерации ключа")

    source = ""
    for city, ra, dec, timestamp in rows:
        source += f"{city}:{ra:.6f}:{dec:.6f}:{timestamp}|"

    return hashlib.sha256(source.encode()).hexdigest()


# ---------------------------
# Проверка уникальности ключа
# ---------------------------
def check_key_uniqueness(key_hash):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM generated_keys WHERE key_hash = ?",
        (key_hash,)
    )

    exists = cursor.fetchone() is not None
    conn.close()

    return not exists


# ----------------
# Сохранение ключа
# ----------------
def save_generated_key(body, key_hash):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO generated_keys (body, key_hash, timestamp)
            VALUES (?, ?, ?)
        """, (
            body, key_hash,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        conn.close()


# ---
# WEB
# ---
@app.route("/", methods=["GET", "POST"])
def index():
    key = None
    error = None
    message = None

    if request.method == "POST":
        body = request.form.get("planet")

        try:
            for city, (lat, lon) in CITIES.items():
                ra, dec, source = fetch_planetary_data_visible(body, lat, lon)
                insert_data(body, city, ra, dec)

            key = generate_key(body)

            if check_key_uniqueness(key):
                save_generated_key(body, key)
                message = "Ключ сгенерирован и сохранён (уникальный)"
            else:
                message = "Такой ключ уже был сгенерирован ранее"

        except Exception as e:
            error = str(e)

    return render_template(
        "index.html",
        planets=AVAILABLE_PLANETS,
        key=key,
        message=message,
        error=error
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

