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
    """লগ ফাইল চেক করে শেষ এন্ট্রি নম্বর (যেমন: Entry 1, Entry 2) বের করে"""
    if not os.path.exists(LOG_FILE):
        return 0
    with open(LOG_FILE, "r") as f:
        content = f.read()
    entries = re.findall(r'\[Entry\s+(\d+)\]', content)
    return max([int(x) for x in entries]) if entries else 0

def get_all_logged_hashes():
    """লগ ফাইলের ভেতর থাকা সমস্ত হ্যাশ ভ্যালু খুঁজে বের করে ডুপ্লিকেট চেকের জন্য"""
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, "r") as f:
        content = f.read()
    # ৩২ অক্ষরের হেক্সাডেসিমেল হ্যাশ ম্যাচ করার রেগুলার এক্সপ্রেশন
    return set(re.findall(r'\b[a-fA-F0-9]{32}\b', content))

def remove_last_entry(entry_num):
    """হাগিংফেসে আপলোড ফেল করলে মেটাডেটা থেকে নির্দিষ্ট এন্ট্রি ব্লকটি সম্পূর্ণ ডিলিট করে"""
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    
    start_tag = f"--- [Entry {entry_num}] ---\n"
    new_lines = []
    skip = False
    for line in lines:
        if line == start_tag:
            skip = True  # ডিলিট করা শুরু
            continue
        if skip and line.startswith("--- End Entry ---"):
            skip = False  # ডিলিট করা শেষ
            continue
        if not skip:
            new_lines.append(line)
            
    with open(LOG_FILE, "w") as f:
        f.writelines(new_lines)
    print(f"⚠️ Successfully rolled back and deleted [Entry {entry_num}] due to upload failure.")

def upload_and_verify(content, lang, part_id, entry_num):
    """হাগিংফেসে ডেটা আপলোড করে এবং ট্রান্সজেকশন ভেরিফাই করে"""
    filename = f"{lang}_data_{part_id}_{int(time.time())}.txt"
    try:
        print(f"🚀 Attempting to upload {filename} to Hugging Face...")
        api.upload_file(
            path_or_fileobj=content.encode("utf-8"),
            path_in_repo=filename,
            repo_id=REPO_ID,
            repo_type="dataset"
        )
        print(f"✅ Upload Successful: {filename}")
    except Exception as e:
        # আপলোড ফেল করলে মেটাডেটা রোলব্যাক করবে এবং সুনির্দিষ্ট এরর দিয়ে প্রসেস বন্ধ করবে
        print(f"❌ CRITICAL ERROR: Hugging Face Upload Failed for {filename}!")
        print(f"Reason for Failure: {str(e)}")
        remove_last_entry(entry_num)
        # গিটহাবে লোকাল কারেকশন পুশ করে স্ক্রিপ্ট বন্ধ করা
        os.system(f"git add {LOG_FILE} && git commit -m 'Rollback Entry {entry_num}' && git push")
        sys.exit(1) # Exit code 1 দিলে গিটহাব অ্যাকশনস লাল বাটন (Failed) দেখাবে

def main():
    while True:
        try:
            response = requests.get(TARGET_URL, timeout=30)
            soup = BeautifulSoup(response.text, 'lxml')
            text = soup.get_text(separator=' ', strip=True)
            
            # আপনার লজিক: ৪টি সমান্তরাল প্রসেস (বাংলা ২টি, ইংরেজি ২টি)
            half_len = len(text) // 2
            contents = [text[:half_len], text[half_len:], text[:half_len], text[half_len:]]
            langs = ["bangla", "bangla", "english", "english"]

            for i in range(4):
                current_content = contents[i]
                current_lang = langs[i]
                content_bytes = current_content.encode('utf-8')

                # ১০০ এমবি সাইজ লিমিট চেক
                if len(content_bytes) >= LIMIT_MB:
                    current_hash = hashlib.md5(content_bytes).hexdigest()
                    existing_hashes = get_all_logged_hashes()

                    # ডুপ্লিকেট চেক
                    if current_hash not in existing_hashes:
                        # ১. স্ক্র্যাপিং এর পরের মিলি সেকেন্ডেই মেটাডেটা এন্ট্রি লক করা শুরু
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
                        
                        # মেটাডেটা ফাইলে তাৎক্ষণিক রাইট এবং গিটহাবে পুশ
                        with open(LOG_FILE, "a") as f:
                            f.write(meta_block)
                        os.system(f"git add {LOG_FILE} && git commit -m 'Logging Entry {next_entry_num} [skip ci]' && git push")
                        print(f"📝 Metadata locked for [Entry {next_entry_num}]")

                        # ২. মেটাডেটা পুশ করার ঠিক পর পরই হাগিংফেসে ডেটা পাঠানো এবং চেক করা
                        upload_and_verify(current_content, current_lang, f"part_{i}", next_entry_num)

            print("🔄 Cycle complete. Sleeping for 1 minute...")
            time.sleep(60)
            
        except requests.exceptions.RequestException as req_err:
            print(f"⚠️ Target URL Connection Error: {req_err}. Retrying in 60s...")
            time.sleep(60)
        except Exception as e:
            print(f"💥 Unexpected System Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
