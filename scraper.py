import os
import re
import time
import hashlib
import requests
import sys
from bs4 import BeautifulSoup
from huggingface_hub import HfApi

# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://archive.org")
HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = "shofikul-1234/my_data_sate"
LOG_FILE = "metadata_log.txt"
LIMIT_MB = 100 * 1024 * 1024  # 100 MB

api = HfApi(token=HF_TOKEN)

def get_last_entry_number():
    if not os.path.exists(LOG_FILE):
        return 0
    with open(LOG_FILE, "r") as f:
        content = f.read()
    entries = re.findall(r'\[Entry\s+(\d+)\]', content)
    return max([int(x) for x in entries]) if entries else 0

def get_all_logged_hashes():
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, "r") as f:
        content = f.read()
    return set(re.findall(r'\b[a-fA-F0-9]{32}\b', content))

def remove_last_entry(entry_num):
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    
    start_tag = f"--- [Entry {entry_num}] ---\n"
    new_lines = []
    skip = False
    for line in lines:
        if line == start_tag:
            skip = True
            continue
        if skip and line.startswith("--- End Entry ---"):
            skip = False
            continue
        if not skip:
            new_lines.append(line)
            
    with open(LOG_FILE, "w") as f:
        f.writelines(new_lines)
    print(f"⚠️ Rolled back and deleted [Entry {entry_num}] from local storage.")

def main():
    try:
        response = requests.get(TARGET_URL, timeout=30)
        soup = BeautifulSoup(response.text, 'lxml')
        text = soup.get_text(separator=' ', strip=True)
        
        # সমান্তরাল ৪টি প্রসেস লজিক
        half_len = len(text) // 2
        contents = [text[:half_len], text[half_len:], text[:half_len], text[half_len:]]
        langs = ["bangla", "bangla", "english", "english"]

        for i in range(4):
            current_content = contents[i]
            current_lang = langs[i]
            content_bytes = current_content.encode('utf-8')

            if len(content_bytes) >= LIMIT_MB:
                current_hash = hashlib.md5(content_bytes).hexdigest()
                existing_hashes = get_all_logged_hashes()

                if current_hash not in existing_hashes:
                    next_entry_num = get_last_entry_number() + 1
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    
                    meta_block = (
                        f"--- [Entry {next_entry_num}] ---\n"
                        f"Timestamp: {timestamp}\n"
                        f"Language: {current_lang}\n"
                        f"Process_ID: Parallel_Part_{i}\n"
                        f"Data_Size: {len(content_bytes)} bytes\n"
                        f"Hash: {current_hash}\n"
                        f"--- End Entry ---\n"
                    )
                    
                    # মিলি সেকেন্ডে তাৎক্ষণিক লোকাল ফাইলে রাইট
                    with open(LOG_FILE, "a") as f:
                        f.write(meta_block)
                    print(f"📝 Local Metadata locked for [Entry {next_entry_num}]")

                    # হাগিংফেসে পাঠানো এবং ট্রানজেকশন ভেরিফাই করা
                    filename = f"{current_lang}_data_part_{i}_{int(time.time())}.txt"
                    try:
                        api.upload_file(
                            path_or_fileobj=current_content.encode("utf-8"),
                            path_in_repo=filename,
                            repo_id=REPO_ID,
                            repo_type="dataset"
                        )
                        print(f"✅ Upload Successful: {filename}")
                    except Exception as upload_error:
                        print(f"❌ HF Upload Failed! Reason: {upload_error}")
                        remove_last_entry(next_entry_num)
                        sys.exit(1) # এরর দিয়ে গিটহাবকে ফোর্স স্টপ করবে

    except Exception as e:
        print(f"💥 Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
