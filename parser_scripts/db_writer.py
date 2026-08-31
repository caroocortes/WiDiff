
import traceback
import time
import json
import psycopg2
import queue
from pathlib import Path
import gc
import os

from parser_scripts.const import *
from parser_scripts.utils import insert_rows_copy

def batch_insert(conn, batch, set_up, table_suffix=''):
    """Function to insert into DB in parallel."""

    change_extraction_filters = set_up.get('change_extraction_filters', {})
    if table_suffix == '_ao':
        re_interpretation = set_up.get('re_interpretation', False) and change_extraction_filters.get('astronomical_objects_filter', {}).get('extract', False)
        extract_datatype_metadata_changes = change_extraction_filters.get('astronomical_objects_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('astronomical_objects_filter', {}).get('extract', False)

    if table_suffix == '_sa':
        re_interpretation = set_up.get('re_interpretation', False) and change_extraction_filters.get('scholarly_articles_filter', {}).get('extract', False)
        extract_datatype_metadata_changes = change_extraction_filters.get('scholarly_articles_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('scholarly_articles_filter', {}).get('extract', False)

    if table_suffix == '_less':
        re_interpretation = set_up.get('re_interpretation', False) and change_extraction_filters.get('less_filter', {}).get('extract', False)
        extract_datatype_metadata_changes = change_extraction_filters.get('less_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('less_filter', {}).get('extract', False)

    if table_suffix == '':
        re_interpretation = set_up.get('re_interpretation', False)
        extract_datatype_metadata_changes = change_extraction_filters.get('rest', {}).get('datatype_metadata_extraction', False)

    try:
        if len(batch['revision']) > 0:
            insert_rows_copy(conn, f'revision{table_suffix}', batch['revision'], REVISION_COLS, REVISION_PK)
        
        if len(batch['value_change']) > 0:
            insert_rows_copy(conn, f'value_change{table_suffix}', batch['value_change'], VALUE_CHANGE_COLS, VALUE_CHANGE_PK)
            
        if len(batch['rank_change']) > 0:
            insert_rows_copy(conn, f'rank_change{table_suffix}', batch['rank_change'], RANK_CHANGE_COLS, RANK_CHANGE_PK)
            
        if len(batch['qualifier_change']) > 0:
            insert_rows_copy(conn, f'qualifier_change{table_suffix}', batch['qualifier_change'], QUALIFIER_CHANGE_COLS, QUALIFIER_CHANGE_PK)
        
        if len(batch['reference_change']) > 0:
            insert_rows_copy(conn, f'reference_change{table_suffix}', batch['reference_change'], REFERENCE_CHANGE_COLS, REFERENCE_CHANGE_PK)
        
        if extract_datatype_metadata_changes and len(batch['datatype_metadata_change']) > 0:
            insert_rows_copy(conn, f'datatype_metadata_change{table_suffix}', batch['datatype_metadata_change'], DATATYPE_METADATA_CHANGE_COLS, DATATYPE_METADATA_CHANGE_PK)
        
        if re_interpretation:
            if len(batch['updates_entity']) > 0:
                insert_rows_copy(conn, f'updates_entity{table_suffix}', batch['updates_entity'], ENTITY_UPDATES_COLS, ENTITY_UPDATES_PK)
        
            if len(batch['updates_text']) > 0:
                insert_rows_copy(conn, f'updates_text{table_suffix}', batch['updates_text'], TEXT_UPDATES_COLS, TEXT_UPDATES_PK)
        
        if len(batch['entity_stats']) > 0:
            insert_rows_copy(conn, f'entity_stats{table_suffix}', batch['entity_stats'], ENTITY_STATS_COLS, ENTITY_STATS_PK)

    except Exception as e:
        print(f'There was an error when batch inserting revisions and changes: {e}', flush=True)
        print(traceback.format_exc(), flush=True)
        raise e


def db_writer(set_up, num_workers, results_queue):

    print(f"[DB_WRITER] Starting - Num workers: {num_workers}", flush=True)

    script_dir = Path(__file__).parent
    with open(script_dir.parent / set_up.get('database_config_path', 'config/db_config.json')) as f:
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

    print(f"[DB_WRITER] Database connection established", flush=True)

    base_table_names = [
        'revision',
        'value_change',
        'rank_change',
        'qualifier_change',
        'reference_change',
        'datatype_metadata_change',
        'updates_entity',
        'updates_text',
        'entity_stats'
    ]

    batches = {
        '': {table: [] for table in base_table_names},
        '_sa': {table: [] for table in base_table_names},
        '_ao': {table: [] for table in base_table_names},
        '_less': {table: [] for table in base_table_names}
    }

    workers_finished = 0
    last_write = time.time()

    total_rows_written = 0
    num_batch_inserts = 0
    last_status_report = time.time()
    status_report_interval = 60

    batch_size = set_up.get('change_extraction_processing', {}).get('db_batch_size', 5000)

    try:
        while workers_finished < num_workers:
            try:

                result = results_queue.get(timeout=60)

                if result is None:
                    # Worker finished
                    workers_finished += 1
                    print(f"[DB_WRITER] Worker finished, total finished: {workers_finished}/{num_workers}", flush=True)
                    continue

                if result['is_scholarly_article']:
                    table_suffix = '_sa'

                if result['is_astronomical_object']:
                    table_suffix = '_ao'
                
                if not result['is_astronomical_object'] and not result['is_scholarly_article'] and result['has_less_revisions']:
                    table_suffix = '_less'
                
                if not result['is_astronomical_object'] and not result['is_scholarly_article'] and not result['has_less_revisions']:
                    table_suffix = ''
                
                for table_name in base_table_names:
                    if table_name in batches[table_suffix]:
                        batches[table_suffix][table_name].extend(result.get(table_name, []))
                
                current_batch_size = len(batches[table_suffix]['revision'])
                time_since_write = time.time() - last_write
                
                if len(batches[table_suffix]['revision']) >= batch_size or (time_since_write > 15 and current_batch_size > 0):

                    batch_insert(conn, batches[table_suffix], set_up, table_suffix=table_suffix)
                    num_batch_inserts += 1
                    total_rows_written += current_batch_size

                    # Clear this batch
                    for table in batches[table_suffix]:
                        batches[table_suffix][table] = []

                    last_write = time.time()

                if time.time() - last_status_report > status_report_interval:
                    try:
                        qsize = results_queue.qsize()
                    except NotImplementedError:
                        qsize = -1  # not supported on this platform
                    print(f"[DB_WRITER] Status: {num_batch_inserts} batches / {total_rows_written} rows written so far, "
                        f"queue backlog~{qsize}, workers finished={workers_finished}/{num_workers}", flush=True)
                    last_status_report = time.time()

                gc.collect(generation=0)

            except queue.Empty:
                print(f"[DB_WRITER] Queue empty timeout - flushing batches", flush=True)
                for suffix, batch in batches.items():
                    if any(len(v) > 0 for v in batch.values()):
                        rows = len(batch['revision'])

                        batch_insert(conn, batch, set_up, table_suffix=suffix)
                        num_batch_inserts += 1
                        total_rows_written += rows
                        print(f"[DB_WRITER] Flushed batch{suffix or ''}: {rows} revisions", flush=True)
                        for table in batch:
                            batch[table] = []

        for suffix, batch in batches.items():
            if any(len(v) > 0 for v in batch.values()):
                rows = len(batch['revision'])
                batch_insert(conn, batch, set_up, table_suffix=suffix)
                num_batch_inserts += 1
                total_rows_written += rows

        print(f"[DB_WRITER] Completed successfully - {num_batch_inserts} batches, {total_rows_written} rows written", flush=True)

    except Exception as e:
        print(f'Error in DB writer: {e}', flush=True)
        print(traceback.format_exc(), flush=True)
        raise e
    finally:
        print(f"[DB_WRITER] Closing connection", flush=True)
        try:
            conn.close()
        except:
            pass
        print(f"[DB_WRITER] Exiting", flush=True)
