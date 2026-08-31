import cProfile
import os
import time
from argparse import ArgumentParser
from pathlib import Path
import concurrent.futures
import json
import sys
import fcntl
import traceback
import multiprocessing as mp
import gc
import yaml

from parser_scripts.utils import create_db_schema
from parser_scripts.file_parser import FileParser
from parser_scripts.const import PROCESSED_FILES_PATH, CLAIMED_FILES_PATH, LOCK_FILE_PATH, SETUP_PATH, LOGS_DIR

with open(SETUP_PATH, 'r') as f:
    set_up = yaml.safe_load(f)

def log_file_process(file_path):
    if not isinstance(file_path, Path):
        file_path = Path(file_path) 
    try:
        if not os.path.exists(PROCESSED_FILES_PATH):
            with open(PROCESSED_FILES_PATH, "w") as f:
                pass
        with open(PROCESSED_FILES_PATH, "a") as f: 
            f.write(f"{file_path.resolve()}\n") 
    except Exception as e:
        print(f"Error logging processed file to processed_files.txt {file_path}: {e}")

def process_file(file_id, file_path):
    """
    Process a single .xml.bz2 file, parse it, and log the results.
    """
    input_bz2 = os.path.basename(file_path)

    file_parser = FileParser(file_path=input_bz2, file_id=file_id, set_up=set_up)
    
    print(f"Processing: {file_path}")
    sys.stdout.flush()

    start_process = time.time()
    file_parser.parse_dump()
    end_process = time.time()
    process_time = end_process - start_process

    num_entities = file_parser.num_entities

    del file_parser
    gc.collect() 

    print(f"Processed {input_bz2} in {process_time:.2f} secs, {num_entities} entities")
    sys.stdout.flush()
    
    log_file_process(file_path)
    return 0


def claim_files(available_files, num_files_to_claim):
    """
    Claim X files from the the directiory by writing them to claimed_files.txt
    Returns the list of files this process claimed.
    """
    claimed_by_me = []
    pid = os.getpid()
    
    lock_file = Path(LOCK_FILE_PATH)
    lock_file.touch(exist_ok=True)
    
    with open(lock_file, 'r') as lock:
        try:
            print(f"[PID {pid}] Acquiring lock...")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            print(f"[PID {pid}] Lock acquired")
            
            claimed_path = Path(CLAIMED_FILES_PATH)
            already_claimed = set()
            next_file_id = 1
            if claimed_path.exists():
                with claimed_path.open() as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        file_path_str, _, file_id_str = line.rpartition(',')
                        already_claimed.add(file_path_str)
                        if file_id_str.isdigit():
                            next_file_id = max(next_file_id, int(file_id_str) + 1)
            
            print(f"Already claimed: {len(already_claimed)} files")

            unclaimed = [f for f in available_files if str(f.resolve()) not in already_claimed]
            
            print(f"Unclaimed: {len(unclaimed)} files")
            
            if len(unclaimed) == 0:
                print(f"[PID {pid}] No unclaimed files available.")
                return []
            
            to_claim = unclaimed[:num_files_to_claim]
            
            with claimed_path.open('a') as f:
                for i, file_path in enumerate(to_claim):
                    file_id = next_file_id + i
                    f.write(f"{file_path.resolve()},{file_id}\n")
                    claimed_by_me.append((file_path, file_id))
            
            print(f"[PID {pid}] Successfully claimed {len(claimed_by_me)} files for processing")
            
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            print(f"[PID {pid}] Lock released")
    
    return claimed_by_me

if __name__ == "__main__":
    arg_parser = ArgumentParser()
    arg_parser.add_argument("-f", "--file", help="name of the file to process (e.g., example.xml.bz2), not the path.", metavar="FILE")
    arg_parser.add_argument("-n", "--max_files", help='Maximum number of files to process', type=int, default=None)
    args = arg_parser.parse_args()
    
    dump_dir = Path(set_up.get('change_extraction_processing', {}).get("files_directory", ''))
    if not dump_dir.exists():
        print(f"The dump directory {dump_dir} doesn't exist")
        raise SystemExit(1)
    
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    processed_log = Path(PROCESSED_FILES_PATH)

    processed_files = set()
    if processed_log.exists():
        with processed_log.open() as f:
            processed_files = set(line.strip() for line in f)
        print(f'Found {len(processed_files)} files that have already been processed')
    else:
        open(processed_log, 'w').close()
        processed_files = set()

    # CLAIMED files and LOCK file are used to coordinate between processes when claiming files to process in parallel.
    if not Path(CLAIMED_FILES_PATH).exists():
        open(CLAIMED_FILES_PATH, 'w').close()
        
    if not Path(LOCK_FILE_PATH).exists():
        open(LOCK_FILE_PATH, 'w').close()

    # Creating DB schema
    create_db_schema(set_up)

    if args.file:
        # Single file processing
        input_bz2 = args.file
        if input_bz2 in processed_files:
            print(f"{input_bz2} has already been processed.")
        else:
            claimed = claim_files([Path(dump_dir / input_bz2)], 1)
            if claimed:
                file_path, file_id = claimed[0]
                print(f"Claimed {input_bz2} for processing with file_id={file_id}")
                process_file(file_id, file_path)
            else:
                print(f"{input_bz2} is already claimed by another process.")
                raise SystemExit(1)
            
    else:
        all_files = [f.resolve() for f in dump_dir.iterdir() if f.is_file() and f.suffix == '.bz2']
        files_sorted = sorted(all_files, key=lambda f: f.stat().st_mtime)
        files_to_parse = [f for f in files_sorted if str(f) not in processed_files]

        max_workers = set_up.get('change_extraction_processing', {}).get('files_in_parallel', 5)
        
        if args.max_files is not None:
            max_files = args.max_files
        
        if max_files < max_workers:
            max_workers = max_files

        print(f"Found {len(files_to_parse)} unprocessed .bz2 files in {dump_dir}, processing up to {max_files} files with {max_workers} files in parallel.")
        
        if len(files_to_parse) == 0:
            print("No new files to process. Exiting.")
            raise SystemExit(0)
        
        print("Claiming files...")
        files_to_parse = claim_files(files_to_parse, max_files)
        if len(files_to_parse) == 0:
            print("No files to process after claiming. Exiting.")
            raise SystemExit(0)
        
        print(f"Successfully claimed {len(files_to_parse)} files. Starting processing...")

        files_in_parallel = max_workers
        workers_per_file = set_up.get('change_extraction_processing', {}).get('pages_in_parallel', 2)
        total_workers = len(files_to_parse) * workers_per_file
        
        print(f"Starting shared db_writer expecting {total_workers} workers")
        

        try:

            executor = concurrent.futures.ProcessPoolExecutor(
                max_workers=max_workers,
            )

            futures = {}
            for file_path, file_id in files_to_parse:
                futures[executor.submit(process_file, file_id, file_path)] =  file_path
                
            for future in concurrent.futures.as_completed(futures):
                file_path = futures[future]
                try:
                    result = future.result(timeout=7200)
                
                except concurrent.futures.TimeoutError:
                    print(f"Timeout processing {file_path}", flush=True)
                    print(traceback.format_exc(), flush=True)
                    executor.shutdown(wait=True)
                    break
                except MemoryError as e:
                    print(f"MemoryError processing {file_path}: {e}", flush=True)
                    print(traceback.format_exc(), flush=True)
                    executor.shutdown(wait=True)
                    break
                except Exception as e:
                    print(f"Error processing {file_path}: {e}", flush=True)
                    print(traceback.format_exc(), flush=True)
                    executor.shutdown(wait=True)
                    break
                sys.stdout.flush()

        except Exception as e:
            print(f"Fatal error in processing: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            executor.shutdown(wait=True)
        
        executor.shutdown(wait=True)

        