import os
from flask import Flask, jsonify, request
import pymysql
import redis

app = Flask(__name__)

# Configuration (Variables d'environnement avec valeurs de repli par défaut)
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DB = os.getenv("MYSQL_DATABASE", "mysql")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Initialisation du client Redis
# decode_responses=True est crucial en Python 3 pour manipuler des chaînes (str) et non des bytes
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True
)


def get_db_connection():
    """Crée et retourne une connexion vers la base MySQL."""
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        port=MYSQL_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


@app.route("/")
def index():
    return jsonify({
        "status": "online",
        "message": "Multi-container Pod Demo API"
    }), 200


@app.route("/init")
def init_db():
    """Initialise la table 'users' dans MySQL."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS users")
            cursor.execute(
                """
                CREATE TABLE users (
                    uid VARCHAR(64) PRIMARY KEY,
                    user VARCHAR(255) NOT NULL
                )
                """
            )
        conn.close()
        return jsonify({"message": "Database initialized successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/users/add", methods=["POST"])
def add_user():
    """Ajoute un utilisateur dans MySQL et met à jour le cache Redis."""
    data = request.get_json(silent=True)
    if not data or "uid" not in data or "user" not in data:
        return jsonify({"error": "Invalid payload. 'uid' and 'user' are required."}), 400

    uid = str(data["uid"])
    user = str(data["user"])

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Insertion avec requête paramétrée pour éviter les injections SQL
            cursor.execute(
                "INSERT INTO users (uid, user) VALUES (%s, %s) ON DUPLICATE KEY UPDATE user = %s",
                (uid, user, user)
            )
        conn.close()

        # Invalidation ou mise à jour du cache Redis
        r.set(uid, user)

        return jsonify({"message": "User added/updated successfully", "uid": uid, "user": user}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/users/<uid>", methods=["GET"])
def get_user(uid: str):
    """
    Récupère un utilisateur :
    - Vérifie d'abord dans le cache Redis local (ajoute '(c)' pour marquer le cache).
    - Si absent, va chercher dans MySQL puis alimente le cache.
    """
    try:
        # 1. Vérification dans le cache Redis
        cached_user = r.get(uid)
        if cached_user:
            return jsonify({
                "uid": uid,
                "user": f"{cached_user} (c)"
            }), 200

        # 2. Requête dans MySQL si absent du cache
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT user FROM users WHERE uid = %s", (uid,))
            result = cursor.fetchone()
        conn.close()

        if result:
            user_name = result["user"]
            # Mise en cache dans Redis
            r.set(uid, user_name)
            return jsonify({
                "uid": uid,
                "user": user_name
            }), 200
        else:
            return jsonify({"error": "User not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)