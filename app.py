from flask import Flask, request, jsonify
import requests
import mysql.connector
from mysql.connector import Error, IntegrityError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# Create a requests session with retries
session = requests.Session()
retry = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update({"User-Agent": "pincode-verifier/1.0"})

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Str@!pwadri",
        database="pincode_project",
        autocommit=False,
    )

@app.route("/verify", methods=["POST"])
def verify_pincode():
    data = request.get_json(silent=True) or {}
    pincode = str(data.get("pincode", "")).strip()

    # India pincode = 6 digits
    if not pincode.isdigit() or len(pincode) != 6:
        return jsonify({"error": "Pincode must be a 6-digit number"}), 400

    try:
        db = get_db()
        db.ping(reconnect=True, attempts=2, delay=1)
        cursor = db.cursor(dictionary=True)

        # Step 1: check DB first
        cursor.execute("SELECT pincode, city, state FROM pincodes WHERE pincode = %s", (pincode,))
        row = cursor.fetchone()
        if row:
            return jsonify({"source": "database", "data": row}), 200

        # Step 2: call external API
        url = f"https://api.postalpincode.in/pincode/{pincode}"
        try:
            resp = session.get(url, timeout=(5, 12))  # (connect, read)
            resp.raise_for_status()
            api_data = resp.json()
        except requests.exceptions.RequestException as e:
            return jsonify({
                "error": "External API failed",
                "details": str(e)
            }), 502

        if not api_data or api_data[0].get("Status") != "Success" or not api_data[0].get("PostOffice"):
            return jsonify({"error": "Invalid pincode or no data found"}), 400

        office = api_data[0]["PostOffice"][0]
        city = office.get("District")
        state = office.get("State")

        if not city or not state:
            return jsonify({"error": "Incomplete data from external API"}), 502

        # Step 3: insert DB
        try:
            cursor.execute(
                "INSERT INTO pincodes (pincode, city, state) VALUES (%s, %s, %s)",
                (pincode, city, state),
            )
            db.commit()
            source = "external_api"
        except IntegrityError:
            # If another request inserted same pincode concurrently
            db.rollback()
            source = "database (duplicate found)"

        return jsonify({
            "source": source,
            "pincode": pincode,
            "city": city,
            "state": state
        }), 200

    except Error as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        try:
            cursor.close()
            db.close()
        except Exception:
            pass

if __name__ == "__main__":
    app.run(debug=True, port=5002)
 