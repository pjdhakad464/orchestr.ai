import os
import sys
import time
import argparse
from pathlib import Path

# Configured SQLite files that contain dynamic state we want to persist
SYNC_FILES = [
    "data/validation_history.sqlite3",
    "data/wikipedia_cache/wikipedia_cache.sqlite3"
]

def get_hf_credentials():
    repo_id = os.environ.get("HF_DATASET_ID")
    token = os.environ.get("HF_TOKEN")
    return repo_id, token

def download_databases(repo_id: str, token: str):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("Error: 'huggingface_hub' package is not installed. Run 'pip install huggingface_hub'.")
        sys.exit(1)

    print(f"Downloading databases from HF Dataset: {repo_id}...")
    for rel_path in SYNC_FILES:
        local_path = Path(rel_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Download file to local path
            hf_hub_download(
                repo_id=repo_id,
                filename=rel_path,
                repo_type="dataset",
                token=token,
                local_dir=".",
                local_dir_use_symlinks=False
            )
            print(f"  ✓ Successfully downloaded {rel_path}")
        except Exception as e:
            # We catch exceptions because if it's the first run, the files won't exist in the repo
            print(f"  ⚠ Could not download {rel_path} (it may not exist in the dataset yet): {e}")

def upload_file(repo_id: str, token: str, rel_path: str):
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Error: 'huggingface_hub' package is not installed.")
        return

    local_path = Path(rel_path)
    if not local_path.exists():
        print(f"  ✗ Local file {rel_path} does not exist. Skipping upload.")
        return

    print(f"Uploading {rel_path} to HF Dataset: {repo_id}...")
    try:
        api = HfApi(token=token)
        api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=rel_path,
            repo_id=repo_id,
            repo_type="dataset"
        )
        print(f"  ✓ Successfully uploaded {rel_path}")
    except Exception as e:
        print(f"  ✗ Failed to upload {rel_path}: {e}")

def monitor_and_sync(repo_id: str, token: str, check_interval: int = 15, debounce_seconds: int = 10):
    print(f"Starting database monitoring for HF Dataset: {repo_id}...")
    print(f"Watching files: {', '.join(SYNC_FILES)}")
    
    # Initialize trackers
    last_mtimes = {}
    last_changed = {}
    
    for rel_path in SYNC_FILES:
        p = Path(rel_path)
        last_mtimes[rel_path] = p.stat().st_mtime if p.exists() else 0
        last_changed[rel_path] = 0

    while True:
        try:
            time.sleep(check_interval)
            for rel_path in SYNC_FILES:
                p = Path(rel_path)
                if not p.exists():
                    continue
                
                current_mtime = p.stat().st_mtime
                if current_mtime > last_mtimes[rel_path]:
                    print(f"Change detected locally in {rel_path}. Debouncing...")
                    last_mtimes[rel_path] = current_mtime
                    last_changed[rel_path] = time.time()
                
                # Check if debounce time has passed since the last change
                if last_changed[rel_path] > 0 and (time.time() - last_changed[rel_path]) >= debounce_seconds:
                    print(f"Debounce finished. Uploading {rel_path}...")
                    upload_file(repo_id, token, rel_path)
                    last_changed[rel_path] = 0 # reset change tracker
        except KeyboardInterrupt:
            print("Stopping monitor...")
            break
        except Exception as e:
            print(f"Error in monitor loop: {e}")

def main():
    parser = argparse.ArgumentParser(description="Synchronize SQLite databases with a Hugging Face Dataset.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--download", action="store_true", help="Download database files from the HF dataset.")
    group.add_argument("--upload", action="store_true", help="Upload database files to the HF dataset.")
    group.add_argument("--monitor", action="store_true", help="Monitor database files and upload them when changed.")
    
    args = parser.parse_args()
    
    repo_id, token = get_hf_credentials()
    if not repo_id or not token:
        print("Warning: HF_DATASET_ID or HF_TOKEN environment variables not set. Sync skipped.")
        sys.exit(0)
        
    if args.download:
        download_databases(repo_id, token)
    elif args.upload:
        for rel_path in SYNC_FILES:
            upload_file(repo_id, token, rel_path)
    elif args.monitor:
        monitor_and_sync(repo_id, token)

if __name__ == "__main__":
    main()
