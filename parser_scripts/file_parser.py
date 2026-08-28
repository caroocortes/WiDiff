import cProfile
import sys
import multiprocessing as mp
import time
import queue
import bz2
from lxml import etree
import json
from pathlib import Path
import psycopg2
import pandas as pd
import os
import traceback
import csv
import threading
import gc
from collections import namedtuple

import cProfile
import pstats

from parser_scripts.page_parser import PageParser
from parser_scripts.const import *
from parser_scripts.db_writer import db_writer
from parser_scripts.utils import print_exception_details


RevisionData = namedtuple('RevisionData', [
    'entity_id',
    'revision_id',
    'revision_text',
    'parentid',
    'timestamp',
    'comment',
    'deleted',
    'username',
    'user_id'
])

PageData = namedtuple('PageData', [
    'entity_id',
    'revisions'  # list of RevisionData
])


def process_page_xml(page_elem_str, file_id, set_up, astronomical_object_types, scholarly_article_types):
    
    parser = PageParser(file_id=file_id, page_elem_str=page_elem_str, set_up=set_up, 
                        astronomical_object_types=astronomical_object_types, scholarly_article_types=scholarly_article_types)
    try:
        results = parser.process_page()
        return results

    except Exception as e:
        print('Error in page parser')
        print(e)
        raise e

class FileParser():
    def __init__(self, file_path=None, file_id=None, set_up=None, shared_results_queue=None):
        self.set_up = set_up
        self.file_path = file_path
        self.file_id = file_id
        
        self.batch_size = self.set_up.get('change_extraction_processing', {}).get('db_batch_size', 5000)

        # STATS
        self.total_revisions = 0
        self.num_entities = 0  

        self.num_workers = self.set_up.get('pages_in_parallel', 2) # processes that process pages in parallel

        if self.set_up.get('change_extraction_processing', {}).get('memory_consumption_monitoring', False):
            self.peak_memory_mb = 0.0
            self._stop_memory_monitor = False

            # NOTE: because this runs on a process that will process multiple files, 
            # i get the initial memory in case theres memory that hasn't been freed and it's from a previous file,
            # so i can subtract it from the peak to get the memory used by this file only
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        self.initial_mem = int(line.split()[1]) / 1024
                        break

            self._memory_monitor_thread = threading.Thread(target=self._monitor_memory, daemon=True)
            self._memory_monitor_thread.start()

        # START TIME
        self.start_time = time.time()

        if shared_results_queue is not None:
            self.results_queue = shared_results_queue
            self.owns_writer = False
        else:
            # Fallback for single-file mode
            self.results_queue = mp.Queue()
            self.writer_process = mp.Process(target=db_writer, args=(self.set_up, self.num_workers, self.results_queue))
            self.writer_process.start()
            self.owns_writer = True
        
        self.queue_size = self.set_up.get('change_extraction_processing', {}).get('page_queue_size', 10000)
        
        self.page_queue = mp.Queue(maxsize=self.queue_size) # queue that stores pages as they are read
        self.stop_event = mp.Event()

        # global to all page parsers
        self.ASTRONOMICAL_OBJECT_TYPES = pd.read_csv(ASTRONOMICAL_OBJECT_TYPES_PATH)['s'].tolist()
        self.SCHOLARLY_ARTICLE_TYPES = pd.read_csv(SCHOLARLY_ARTICLE_TYPES_PATH)['s'].tolist()

        # START WORKERS THAT PROCESS PAGES IN PARALLEL
        self.workers = []
        for i in range(self.num_workers):
            p = mp.Process(target=self._worker, args=(i,))
            p.start()
            self.workers.append(p)

    def _save_file_record(self):
        script_dir = Path(__file__).parent
        db_config_path = Path(self.set_up.get('database_config_path', 'config/db_config.json'))
        with open(script_dir.parent / db_config_path) as f:
            db_config = json.load(f)

        conn = psycopg2.connect(
            dbname=db_config["DB_NAME"],
            user=db_config["DB_USER"],
            password=db_config["DB_PASS"],
            host=db_config["DB_HOST"],
            port=db_config["DB_PORT"],
            connect_timeout=30,
            gssencmode='disable',
            client_encoding='UTF8'
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO file_paths (file_id, file_path) VALUES (%s, %s) ON CONFLICT (file_id) DO NOTHING",
                    (self.file_id, self.file_path)
                )
            conn.commit()
        finally:
            conn.close()

    def _monitor_memory(self):
        # VmRSS (Virtual Memory Resident Set Size) returns the exact amount of physical RAM (in kilobytes) that a specific process is currently using
        while not self._stop_memory_monitor:
            try:
                # Collect all PIDs to monitor
                pids = [os.getpid()]  # main process
                pids += [p.pid for p in self.workers if p.pid is not None]
                if hasattr(self, 'writer_process') and self.writer_process.pid is not None:
                    pids.append(self.writer_process.pid)

                total_mem = 0
                for pid in pids:
                    try:
                        with open(f'/proc/{pid}/status') as f:
                            for line in f:
                                if line.startswith('VmRSS:'):
                                    total_mem += int(line.split()[1]) / 1024
                                    break
                    except FileNotFoundError:
                        pass  # process already exited

                if total_mem > self.peak_memory_mb:
                    self.peak_memory_mb = total_mem
            except:
                pass
            time.sleep(0.1)       
    
    def _worker(self, worker_id):
        """
            Process started in init
            Gets pages from queue and calls process_page_xml which processes the page (entity)
        """
        
        pages_processed = 0

        # time spent blocked waiting for a page to show up in page_queue
        # (empty -> reader/upstream is the bottleneck, worker is starved)
        idle_time = 0.0
        # time spent actually parsing + classifying a page
        busy_time = 0.0
        # time spent blocked handing results off to the shared results_queue
        # (large -> db_writer can't keep up, this worker - and every other
        # worker/file sharing that same writer - is being throttled by it)
        writer_blocked_time = 0.0
        last_report = time.time()
        report_interval = self.set_up.get('change_extraction_processing', {}).get('progress_report_interval_sec', 30)

        # profiler = cProfile.Profile()
        # profiler.enable()

        try:

            while not self.stop_event.is_set() or not self.page_queue.empty():
                get_start = time.time()
                try:
                    page_elem_str = self.page_queue.get(timeout=1) # get is atomic -  only one thread can remove an item at a time
                except queue.Empty:
                    idle_time += time.time() - get_start
                    continue
                idle_time += time.time() - get_start

                if page_elem_str is None:  # no more pages to process
                    break

                process_start = time.time()
                results = process_page_xml(
                    page_elem_str,
                    self.file_id,
                    self.set_up,
                    self.ASTRONOMICAL_OBJECT_TYPES,
                    self.SCHOLARLY_ARTICLE_TYPES
                )
                busy_time += time.time() - process_start

                pages_processed += 1

                if results is not None:
                    
                    queue_size = self.results_queue.qsize()
                    print(f"[Worker {worker_id}] Putting results for page {pages_processed} into results_queue (size={queue_size})", flush=True)
                    put_start = time.time()
                    self.results_queue.put(results)
                    end_put = time.time()
                    writer_blocked_time += end_put - put_start
                    
                    put_time = end_put - put_start
                    if put_time > 0.01: 
                        print(f"Slow put: {put_time:.3f}s, queue_size={queue_size}", flush=True)

                    if len(results.get('revision', [])) > 100000:
                        gc.collect()

                    results = None

                if pages_processed % 10000 == 0:  # Every 10000 entities or with more than 100000 revisions
                    gc.collect()

                if time.time() - last_report > report_interval:
                    print(f"[Worker {worker_id}] {pages_processed} pages so far | "
                          f"busy(parse+classify)={busy_time:.1f}s idle(no pages available)={idle_time:.1f}s "
                          f"blocked(handing off to db_writer)={writer_blocked_time:.1f}s", flush=True)
                    last_report = time.time()

        except MemoryError as e:
            print(f"Out of memory processing page in file {self.file_path}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
        except ValueError as e:
            print(f"Value error processing page in file {self.file_path}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
        except Exception as e:
            print(f"Error in worker {worker_id} in file {self.file_path}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
        finally:

            # profiler.disable()
            # profiler.dump_stats(f'profile_worker_{worker_id}.out')

            self.results_queue.put(None)

            print(f"Worker {worker_id} FINAL: {pages_processed} pages | "
                  f"busy(parse+classify)={busy_time:.1f}s idle(no pages available)={idle_time:.1f}s "
                  f"blocked(handing off to db_writer)={writer_blocked_time:.1f}s", flush=True)
            sys.stdout.flush()

            if self.owns_writer:
                self.results_queue.close()
                self.results_queue.join_thread()

            os._exit(0)

    @staticmethod
    def get_page_size(page_elem_str):
        return len(page_elem_str.encode('utf-8'))


    def extract_page_data(page_elem, ns, entity_id):
        """
        Extract all needed data from XML page element.
        Returns PageData or None if should skip.
        """
        revision_tag = f'{{{ns}}}revision'
        revision_text_tag = f'{{{ns}}}text'
        revisions = []
        
        for rev_elem in page_elem.findall(revision_tag):
            revision_id = rev_elem.findtext(f'{{{ns}}}id', '').strip()
            if not revision_id:
                continue
            
            revision_text_elem = rev_elem.find(revision_text_tag)
            if revision_text_elem is None:
                continue
            
            deleted = revision_text_elem.get("deleted")
            
            contrib_elem = rev_elem.find(f'{{{ns}}}contributor')
            username = ''
            user_id = ''
            if contrib_elem is not None:
                username = (contrib_elem.findtext(f'{{{ns}}}username') or '').strip()
                user_id = (contrib_elem.findtext(f'{{{ns}}}id') or '').strip()
            
            parentid = rev_elem.findtext(f'{{{ns}}}parentid', '').strip()
            timestamp = rev_elem.findtext(f'{{{ns}}}timestamp', '').strip()
            comment = rev_elem.findtext(f'{{{ns}}}comment', '').strip()
            revision_text = revision_text_elem.text or None
            
            rev_data = RevisionData(
                entity_id=entity_id,
                revision_id=int(revision_id),
                revision_text=revision_text,
                parentid=parentid,
                timestamp=timestamp,
                comment=comment,
                deleted=deleted,
                username=username,
                user_id=user_id
            )
            revisions.append(rev_data)
        
        if not revisions:
            return None
        
        return PageData(entity_id=entity_id, revisions=revisions)

    def parse_dump(self):
        """
            Reads XML file and extracts pages of entities (title = Q-id).
            Each page is stored in a queue which is accessed by processes in parallel that extract the changes from the revisions
        """

        title_tag = f"{{{NS}}}title"
        revision_tag = f'{{{NS}}}revision'
        revision_text_tag = f'{{{NS}}}text'

        ns = "http://www.mediawiki.org/xml/export-0.11/"
        page_tag = f"{{{ns}}}page"
        title_tag = f"{{{ns}}}title"
        
        try:
            dump_dir = Path(self.set_up.get('change_extraction_processing', {}).get("files_directory", ''))
            with bz2.open(dump_dir / Path(self.file_path), 'rb') as file_obj:

                context = etree.iterparse(file_obj, events=("end",), tag=page_tag, huge_tree=True) # streams the file, doesn't load everything to memory
                
                tostring_time = 0.0
                last_report = time.time()
                start_time_reading = time.time()
                report_interval = self.set_up.get('change_extraction_processing', {}).get('progress_report_interval_sec', 30)
                # time spent blocked on page_queue.put() because it's full,
                # i.e. workers can't drain pages as fast as they're being read
                queue_put_wait = 0.0

                for _, page_elem in context:
                    keep = False
                    entity_id = ""

                    # Get title
                    title_elem = page_elem.find(title_tag)
                    if title_elem is not None:
                        entity_id = title_elem.text or ""
                        if entity_id.startswith("Q") and entity_id not in WIKIDATA_SANDBOXES:
                            keep = True

                    if keep:
                        # Serialize the page element

                        # Extract title = entity_id
                        title_elem = self.page_elem.find(title_tag)
                        if title_elem is not None:
                            entity_id = (title_elem.text or '').strip()




                        ts_start = time.time()
                        page_elem_str = etree.tostring(page_elem, encoding="utf-8")
                        tostring_time += time.time() - ts_start

                        revision_count = page_elem_str.count(b'<revision>')
                        self.total_revisions += revision_count

                        put_start = time.time()
                        self.page_queue.put(page_elem_str)
                        queue_put_wait += time.time() - put_start
                        self.num_entities += 1

                    # Periodic progress report
                    if time.time() - last_report > report_interval:
                        rate = self.num_entities / (time.time() - self.start_time)
                        queue_size = self.page_queue.qsize()
                        alive_workers = sum(1 for p in self.workers if p.is_alive())
                        print(f"Progress: {self.num_entities} entities read, {rate:.1f} entities/sec, "
                            f"page_queue: {queue_size}/{self.queue_size}, "
                            f"time blocked putting into page_queue since last report: {queue_put_wait:.1f}s, "
                            f"workers alive: {alive_workers}/{self.num_workers}", flush=True)

                        sys.stdout.flush()
                        queue_put_wait = 0.0
                        last_report = time.time()

                    # Clear page element to free memory
                    start_clear = time.time()
                    page_elem.clear()
                    while page_elem.getprevious() is not None:
                        del page_elem.getparent()[0]
                    end_clear = time.time()
                    print(f"Clearing page element took {end_clear - start_clear:.4f} seconds", flush=True)

                    if self.stop_event.is_set():
                        break
        except Exception as e:
            print(f"Parsing error in FileParser: {e}")
            print_exception_details(e, self.file_path)
            return 0, 0, self.file_path, "0"
        
        self._save_file_record()

        end_time_file_reading = time.time()

        print('tostring_time={:.1f}s'.format(tostring_time), flush=True)

        # Send stop signals to workers
        for _ in range(self.num_workers):
            self.page_queue.put(None)

        # Wait for workers to finish
        print(f"File reading done in {end_time_file_reading - start_time_reading:.1f}s. "
              f"Waiting for {self.num_workers} worker processes to drain the remaining page_queue "
              f"({self.page_queue.qsize()} pages left).", flush=True)
        worker_drain_start = time.time()
        for i, p in enumerate(self.workers):
            p.join()
        print(f"All workers finished draining page_queue in {time.time() - worker_drain_start:.1f}s "
              f"after file reading completed.", flush=True)

        self.stop_event.set()

        if self.owns_writer:
            print("Waiting for writer process to finish.", flush=True)
            writer_join_start = time.time()
            self.writer_process.join()
            print(f"Writer process finished in {time.time() - writer_join_start:.1f}s "
                  f"after all workers drained page_queue.", flush=True)
            if self.writer_process.exitcode != 0:
                raise Exception(f"DB writer process failed with exit code {self.writer_process.exitcode}")
    
        total_time = time.time() - self.start_time

        if self.set_up.get('memory_consumption_monitoring', False):
            self._stop_memory_monitor = True
            self._memory_monitor_thread.join()

        full_file_path = self.set_up.get('change_extraction_processing', {}).get('files_directory', '') + self.file_path
        file_size = os.path.getsize(full_file_path) / (1024 * 1024)  # convert to MB

        mem_data = {
            'file': self.file_path,
            'file_size_mb': file_size, 
            'num_entities': self.num_entities,
            'processed_revisions': self.total_revisions,
            'avg_revisions_per_entity': (self.total_revisions / self.num_entities) if self.num_entities > 0 else 0,
            'file_reading_sec': end_time_file_reading - start_time_reading,
            'total_process_time_sec': total_time,
            'peak_memory_mb': self.peak_memory_mb - self.initial_mem if self.set_up.get('change_extraction_processing', {}).get('memory_consumption_monitoring', False) else 0
        }

        SCRIPT_DIR = Path(__file__).parent  # /scripts
        PROJECT_DIR = SCRIPT_DIR.parent     # home
        LOGS_DIR = PROJECT_DIR / 'logs'

        csv_file_path = LOGS_DIR / PARSER_LOG_FILES_PATH
        file_exists = csv_file_path.exists()

        with open(csv_file_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=mem_data.keys())
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow(mem_data)

        print(f"\n=== FINAL STATISTICS ===")
        print(f"Total file reading time: {end_time_file_reading - start_time_reading:.1f}s, \n Total processing time: {total_time:.1f}s, \n Total entities processed: {self.num_entities}")
        
        sys.stdout.flush()