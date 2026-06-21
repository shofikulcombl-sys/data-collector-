import os
import re
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from huggingface_hub import HfApi

# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://archive.org")
HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = "shofikul-1234/my_data_sate"
LOG_FILE = "metadata_log.txt"
LIMIT_MB = 100 * 1024 * 1024  # 100 MB

api = HfApi(token=HF_TOKEN)

def get_hashes():
    return set(open(LOG_FILE, "r").read().splitlines()) if os.path.exists(LOG_FILE) else set()

def update_log(text_hash):
    with open(LOG_FILE, "a") as f:
        f.write(text_hash + "\n")

def upload_data(content, lang, part_id):
    filename = f"{lang}_data_{part_id}_{int(time.time())}.txt"
    api.upload_file(
        path_or_fileobj=content.encode("utf-8"),
        path_in_repo=filename,
        repo_id=REPO_ID,
        repo_type="dataset"
    )
    print(f"Uploaded: {filename}")

def main():
    while True:
        existing_hashes = get_hashes()
        try:
            response = requests.get(TARGET_URL, timeout=30)
            soup = BeautifulSoup(response.text, 'lxml')
            text = soup.get_text(separator=' ', strip=True)

            bn_text = " ".join(re.findall(r'[\u0980-\u09FF\s]+', text))
            en_text = " ".join(re.findall(r'[a-zA-Z\s]+', text))

            # বাংলা চেক
            if len(bn_text.encode('utf-8')) >= LIMIT_MB:
                h = hashlib.md5(bn_text.encode()).hexdigest()
                if h not in existing_hashes:
                    upload_data(bn_text, "bangla", int(time.time()))
                    update_log(h)

            # ইংরেজি চেক
            if len(en_text.encode('utf-8')) >= LIMIT_MB:
                h = hashlib.md5(en_text.encode()).hexdigest()
                if h not in existing_hashes:
                    upload_data(en_text, "english", int(time.time()))
                    update_log(h)

            print("Cycle complete. Sleeping for 1 minute...")
            time.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
