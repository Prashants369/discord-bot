import zipfile
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

files_to_zip = ["bot.py", "store.py", "discloud.config", "requirements.txt", "post_command_guide_panel.py"]
output_zip = "discloud.zip"

with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files_to_zip:
        if os.path.exists(f):
            z.write(f)
            print(f"Added {f} to {output_zip}")

print("✅ discloud.zip ready for upload!")
