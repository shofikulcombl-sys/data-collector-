import os
import sys
import re
import hashlib
import requests
from bs4 import BeautifulSoup
from huggingface_hub import HfApi
from multiprocessing import Process, Queue, Manager

# Configurations
TARGET_URL = os.getenv("TARGET_URL", "https://archive.org")
HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = "shofikul-1234/my_data_sate"

MAX_TOTAL_SIZE_BYTES = 5 * 1024 * 1024 * 1024      # 5 GB Total
PART_LIMIT_BYTES = 100 * 1024 * 1024               # 100 MB Layer Limit
CHUNK_LIMIT_BYTES = 5 * 1024 * 1024                # 5 MB Loop Break Limit

def get_hf_file_metadata(filename):
    api = HfApi(token=HF_TOKEN)
    try:
        files = api.list_repo_files(repo_id=REPO_ID, repo_type="dataset")
        if filename in files:
            file_metadata = api.dataset_info(repo_id=REPO_ID)
            for sibling in file_metadata.siblings:
                if sibling.rfilename == filename:
                    return sibling.size if sibling.size else 0
    except Exception:
        pass
    return 0

def fetch_metadata_log():
    url = f"https://huggingface.co{REPO_ID}/raw/main/metadata_log.txt"
    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {HF_TOKEN}"})
        if res.status_code == 200:
            return set(res.text.splitlines())
    except Exception:
        pass
    return set()

def update_metadata_log(new_hashes):
    if not new_hashes:
        return
    api = HfApi(token=HF_TOKEN)
    existing = fetch_metadata_log()
    existing.update(new_hashes)
    final_content = "\n".join(existing).encode("utf-8")
    try:
        api.upload_file(
            path_or_fileobj=final_content,
            path_in_repo="metadata_log.txt",
            repo_id=REPO_ID,
            repo_type="dataset"
        )
    except Exception:
        pass

def append_to_hf(filename, tokens_list):
    if not tokens_list:
        return
    api = HfApi(token=HF_TOKEN)
    new_content = " ".join(tokens_list)
    
    existing_content = ""
    try:
        url = f"https://huggingface.co{REPO_ID}/raw/main/{filename}"
        res = requests.get(url, headers={"Authorization": f"Bearer {HF_TOKEN}"})
        if res.status_code == 200:
            existing_content = res.text + " "
    except Exception:
        pass
        
    final_content = existing_content + new_content
    try:
        api.upload_file(
            path_or_fileobj=final_content.encode("utf-8"),
            path_in_repo=filename,
            repo_id=REPO_ID,
            repo_type="dataset"
        )
    except Exception as e:
        print(f"HF Upload Error: {e}")

def get_current_part_suffix(lang_prefix):
    part = 1
    while True:
        filename = f"{lang_prefix}_dataset_part_{part}.txt"
        size = get_hf_file_metadata(filename)
        if size < PART_LIMIT_BYTES:
            return part, size
        part += 1

# Multiprocessing Worker 1: Bangla Processor
def bangla_worker(paragraphs, bn_queue, metadata_set):
    local_tokens = []
    local_hashes = []
    bytes_processed = 0
    
    for text in paragraphs:
        if bool(re.search(r'[\u0980-\u09FF]', text)):
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            if text_hash in metadata_set:
                continue
                
            clean_text = re.sub(r'\s+', ' ', text).strip()
            tokens = clean_text.split(' ')
            if tokens and tokens != ['']:
                local_tokens.extend(tokens)
                local_hashes.append(text_hash)
                bytes_processed += len(clean_text.encode('utf-8'))
                
                if bytes_processed >= CHUNK_LIMIT_BYTES:
                    break
                    
    bn_queue.put((local_tokens, local_hashes, bytes_processed))

# Multiprocessing Worker 2: English Processor
def english_worker(paragraphs, en_queue, metadata_set):
    local_tokens = []
    local_hashes = []
    bytes_processed = 0
    
    for text in paragraphs:
        if bool(re.search(r'[a-zA-Z]', text)) and not bool(re.search(r'[\u0980-\u09FF]', text)):
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            if text_hash in metadata_set:
                continue
                
            clean_text = re.sub(r'\s+', ' ', text).strip()
            tokens = clean_text.split(' ')
            if tokens and tokens != ['']:
                local_tokens.extend(tokens)
                local_hashes.append(text_hash)
                bytes_processed += len(clean_text.encode('utf-8'))
                
                if bytes_processed >= CHUNK_LIMIT_BYTES:
                    break
                    
    en_queue.put((local_tokens, local_hashes, bytes_processed))

def main():
    if not HF_TOKEN:
        print("Missing HF_TOKEN")
        sys.exit(1)

    metadata_set = fetch_metadata_log()

    try:
        response = requests.get(TARGET_URL, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        paragraphs = [p.get_text() for p in soup.find_all(['p', 'div', 'span'])]
    except Exception as e:
        print(f"Network error: {e}")
        sys.exit(1)

    bn_queue = Queue()
    en_queue = Queue()

    # Launch Parallel Multiprocessing Workers
    p1 = Process(target=bangla_worker, args=(paragraphs, bn_queue, metadata_set))
    p2 = Process(target=english_worker, args=(paragraphs, en_queue, metadata_set))
    
    p1.start()
    p2.start()
    
    p1.join()
    p2.join()

    bn_tokens, bn_hashes, bn_bytes = bn_queue.get()
    en_tokens, en_hashes, en_bytes = en_queue.get()

    total_chunk_bytes = bn_bytes + en_bytes
    print(f"Processed Chunk Size: {total_chunk_bytes / (1024*1024):.2f} MB")

    # Upload & Layer Router for Bangla
    if bn_tokens:
        bn_part, _ = get_current_part_suffix("bangla")
        append_to_hf(f"bangla_dataset_part_{bn_part}.txt", bn_tokens)
        update_metadata_log(bn_hashes)

    # Upload & Layer Router for English
    if en_tokens:
        en_part, _ = get_current_part_suffix("english")
        append_to_hf(f"english_dataset_part_{en_part}.txt", en_tokens)
        update_metadata_log(en_hashes)

    # Force Disconnect Trigger for GitHub Engine Loop if 5MB budget met
    if total_chunk_bytes >= CHUNK_LIMIT_BYTES:
        print("Chunk threshold exceeded. Disconnecting script to refresh IP and bypass limits.")
        sys.exit(0)

if __name__ == "__main__":
    main()
