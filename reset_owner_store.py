import os
import sys
import json
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

STORE_FILE = "verification_store.json"

if os.path.exists(STORE_FILE):
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Clear applications for test accounts so form can open
        data["applications"] = {}
        data["banned_user_ids"] = []
        
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print("[STORE] Cleared verification store test records successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to reset store: {e}")
else:
    print("[STORE] No store file found.")
