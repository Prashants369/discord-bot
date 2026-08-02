import os
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE_PATH = os.path.join(DATA_DIR, "verifications.json")

if os.path.exists(STORE_PATH):
    try:
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "applications": {}, "meta": {"queue_message_id": None}}, f, indent=2)
        print("[STORE] Store data/verifications.json wiped clean!")
    except Exception as e:
        print(f"[ERROR] Failed to wipe store: {e}")
else:
    print("[STORE] Store file does not exist yet.")
