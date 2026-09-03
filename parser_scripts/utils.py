import requests
import bz2
from pathlib import Path
import re
import psycopg2
from bs4 import BeautifulSoup
import json
import hashlib
from urllib.parse import urljoin
import sys
from io import StringIO
from dateutil import parser
from io import StringIO
import os
import pandas as pd
import os
import psutil
import nltk
from nltk.corpus import stopwords
import unicodedata

from parser_scripts.const import WIKIDATA_SERVICE_URL, DOWNLOAD_LINKS_FILE_PATH, WD_STRING_TYPES, WD_ENTITY_TYPES, ALL_DATATYPES, STOP_WORDS

def total_memory_usage():
    """Get total memory including all child processes in MB"""
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss
    
    for child in process.children(recursive=True):
        try:
            mem += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return mem / (1024 * 1024)  # to MB

def get_time_unit(elapsed_time):
    """
    Convert elapsed time in seconds to appropriate unit.
    Returns (value, unit)
    """
    if elapsed_time >= 86400:  # 60*60*24 = 86400 seconds in a day
        return elapsed_time / 86400, 'days'
    elif elapsed_time >= 3600:  # 60*60 = 3600 seconds in an hour
        return elapsed_time / 3600, 'hours'
    elif elapsed_time >= 60:
        return elapsed_time / 60, 'minutes'
    else:
        return elapsed_time, 'seconds'

def insert_rows_copy(conn, table_name, rows, columns, conflict_column=None):
    """
    Insert rows with conflict handling
    
    Args:
        conflict_column: Primary key column(s) for conflict detection
        update_columns: Columns to update on conflict (None = skip updates, DO NOTHING)
    """
    if not rows:
        return
    
    cursor = conn.cursor()
    buffer = StringIO()
    try:
        temp_table = f"{table_name}_temp_{os.getpid()}"
        
        # Create temp table
        cursor.execute(f"""
            CREATE TEMP TABLE {temp_table} 
            (LIKE {table_name} INCLUDING DEFAULTS)
            ON COMMIT DROP
        """)
        
        # COPY to temp table
        for row in rows:
            line_items = []
            for i, val in enumerate(row):
                if val is None:
                    line_items.append('\\N')
                elif val == '':
                    line_items.append('')
                else:
                    val_str = str(val)
                    val_str = val_str.replace('\\', '\\\\')
                    val_str = val_str.replace('"', '\\"')
                    val_str = val_str.replace('\t', '\\t')
                    val_str = val_str.replace('\n', '\\n')
                    val_str = val_str.replace('\r', '\\r')
                    line_items.append(val_str)
            buffer.write('\t'.join(line_items) + '\n')
        
        buffer.seek(0)
        column_names = ', '.join(columns)
        copy_query = f"COPY {temp_table} ({column_names}) FROM STDIN"
        cursor.copy_expert(copy_query, buffer)
        
        # Insert with conflict handling
        if conflict_column:
            if isinstance(conflict_column, list):
                conflict_cols = ', '.join(conflict_column)
            else:
                conflict_cols = conflict_column
            
            
            if 'entity_stat' not in table_name:
                # DO NOTHING on conflict
                # if it's not an entity_stats, then I don't need to update existing rows
                insert_query = f"""
                    INSERT INTO {table_name} ({column_names})
                    SELECT {column_names} FROM {temp_table}
                    ON CONFLICT ({conflict_cols}) DO NOTHING
                """
            else:
            # if it's an entity_stats then I need to update existing rows, because I want to update the counts
            # update only the non-conflict columns (no key columns)
                insert_query = f"""
                    INSERT INTO {table_name} ({column_names})
                    SELECT {column_names} FROM {temp_table}
                    ON CONFLICT ({conflict_cols}) DO UPDATE SET         
                    {', '.join([f'{col} = EXCLUDED.{col}' for col in columns if col not in conflict_column])}
                """
        else:
            insert_query = f"""
                INSERT INTO {table_name} ({column_names})
                SELECT {column_names} FROM {temp_table}
                ON CONFLICT ({conflict_cols}) DO NOTHING
            """
        
        cursor.execute(insert_query)
        rows_affected = cursor.rowcount
        
        conn.commit()
        
        return rows_affected
        
    except Exception as e:
        conn.rollback()
        print(f"COPY failed for {table_name}: {e}")
        raise
    finally:
        cursor.close()
        buffer.close()


def create_db_schema(set_up):
    base_dir = Path(__file__).resolve().parent.parent
    
    change_extraction_filters = set_up['change_extraction_filters']

    re_interpretation = set_up.get('re_interpretation', False)

    change_schema_file_path = f"{base_dir}/table_schemas/change_schema.sql"
    updates_file_path = f"{base_dir}/table_schemas/updates_schema.sql"
    datatype_metadata_file_path = f"{base_dir}/table_schemas/datatype_metadata_schema.sql"
    
    with open(change_schema_file_path, "r", encoding="utf-8") as f:
        change_schema_template = f.read()

    with open(updates_file_path, "r", encoding="utf-8") as f:
        updates_file_template = f.read()

    with open(datatype_metadata_file_path, "r", encoding="utf-8") as f:
        datatype_metadata_schema_template = f.read()
    
    base_query = change_schema_template.replace("{suffix}", "")

    filters_rest = change_extraction_filters.get('rest', {})
    if re_interpretation:
        # load schema for rest features
        query_fe_rest = updates_file_template.replace("{suffix}", "")
        base_query += "\n" + query_fe_rest

    if filters_rest.get('datatype_metadata_extraction', False):
        # load schema for datatype metadata
        query_dm = datatype_metadata_schema_template.replace("{suffix}", "")
        base_query += "\n" + query_dm

    #  ---------------------------------------------
    #  Scholarly articles
    #  ---------------------------------------------
    filters_sa = change_extraction_filters.get('scholarly_articles_filter', {})
    if filters_sa.get('extract', False):
        # load schema for scholarly articles
        query_sa = change_schema_template.replace("{suffix}", "_sa")
        base_query += "\n" + query_sa

        if re_interpretation:
            # load feature extraction schema for scholarly articles
            query_fe_sa = updates_file_template.replace("{suffix}", "_sa")
            base_query += "\n" + query_fe_sa

        if filters_sa.get('datatype_metadata_extraction', False):
            # load schema for datatype metadata
            query_dm_sa = datatype_metadata_schema_template.replace("{suffix}", "_sa")
            base_query += "\n" + query_dm_sa

    #  ---------------------------------------------
    #  Astronomical objects
    #  ---------------------------------------------
    filters_ao = change_extraction_filters.get('astronomical_objects_filter', {})
    if filters_ao.get('extract', False):
        # load schema for astronomical objects
        query_ao = change_schema_template.replace("{suffix}", "_ao")
        base_query += "\n" + query_ao

        if re_interpretation:
            # load feature extraction schema for astronomical objects
            query_fe_ao = updates_file_template.replace("{suffix}", "_ao")
            base_query += "\n" + query_fe_ao

        if filters_ao.get('datatype_metadata_extraction', False):
            # load schema for datatype metadata
            query_dm_ao = datatype_metadata_schema_template.replace("{suffix}", "_ao")
            base_query += "\n" + query_dm_ao
    
    #  ---------------------------------------------
    #  Less than X value & rank changes
    #  ---------------------------------------------
    filters_less = change_extraction_filters.get('less_filter', {})
    if filters_less.get('extract', False):
        # load schema for less
        query_less = change_schema_template.replace("{suffix}", "_less")
        base_query += "\n" + query_less

        if re_interpretation:
            # load feature extraction schema for less
            query_fe_less = updates_file_template.replace("{suffix}", "_less")
            base_query += "\n" + query_fe_less

        if filters_less.get('datatype_metadata_extraction', False):
            # load schema for datatype metadata
            query_dm_less = datatype_metadata_schema_template.replace("{suffix}", "_less")
            base_query += "\n" + query_dm_less

    enum_query = f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_enum') THEN
                CREATE TYPE action_enum AS ENUM ('CREATE', 'UPDATE', 'DELETE');
            END IF;
        END$$;

        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'datatype_enum') THEN
                CREATE TYPE datatype_enum AS ENUM ({', '.join(f"'{dt}'" for dt in ALL_DATATYPES)});
            END IF;
        END$$;

        CREATE TABLE IF NOT EXISTS file_paths (
            file_id INT PRIMARY KEY,
            file_path TEXT
        );
    """

    try:
        script_dir = Path(__file__).parent
        db_config_path = script_dir.parent / set_up.get("database_config_path", "config/db_config.json")
        print('DB CONFIG PATH:', db_config_path, flush=True)
        with open(db_config_path) as f:
            config = json.load(f)

        conn = psycopg2.connect(
            dbname=config["DB_NAME"],
            user=config["DB_USER"],
            password=config["DB_PASS"], 
            host=config["DB_HOST"],
            port=config["DB_PORT"]
        )

        cursor = conn.cursor()

        cursor.execute(query=enum_query)

        conn.commit()

        cursor.execute(query=base_query)

        conn.commit()
        cursor.close()

    except Exception as e:
        print(f'Error when saving or connecting to DB: {e}')
        sys.exit(1)


""" Other utility methods """
def human_readable_size(size, decimal_places=2):
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024

def print_exception_details(e, file_path):
    # Get the error position
    err_line = e.getLineNumber()
    err_col = e.getColumnNumber()

    print(f"Error at line {err_line}, column {err_col}")

    # Reopen the file and get surrounding lines
    with bz2.open(file_path, 'rt', encoding='utf-8') as f_err:
        lines = []
        for i, line in enumerate(f_err, start=1):
            if i >= err_line - 14 and i <= err_line + 4:  # 14 lines before, 4 after
                lines.append((i, line.rstrip("\n")))
            if i > err_line + 1:
                break

    print("\n--- XML snippet around error ---")
    for ln, txt in lines:
        prefix = ">>" if ln == err_line else "  "
        print(f"{prefix} Line {ln}: {txt}")
    print("-------------------------------")

def get_dump_links():
    #  Get list of .bz2 files from the wikidata dump service (Scrapper)
    response = requests.get(WIKIDATA_SERVICE_URL)
    soup = BeautifulSoup(response.text, "html.parser")

    bz2_links = []
    for link in soup.find_all("a"):
        href = link.get("href", "")
        if "pages-meta-history" in href and href.endswith(".bz2"):
            full_url = urljoin(WIKIDATA_SERVICE_URL, href)
            bz2_links.append(full_url)

    print(f"Found {len(bz2_links)} .bz2 dump files.")
    print(f"Saving download links to {DOWNLOAD_LINKS_FILE_PATH}")
    with open(DOWNLOAD_LINKS_FILE_PATH, 'w', encoding='utf-8') as f:
        for file in bz2_links:
            f.write(f"{file}\n")
    
    return bz2_links

def id_to_int(wd_id):
    """
    Converts Wikidata ID like Q38830 or P31 to integer.
    """
    return int(wd_id[1:])

def make_sah1_value_id(value_json):
    # creates a sha1 hash from the json representation of the value
    # to uniquely identify it

    # sha1 always returns the same hash for the same input
    norm = json.dumps(value_json, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()

def get_time_feature(timestamp, option='year'):

    if isinstance(timestamp, str):
        dt = parser.parse(timestamp)
    else:
        dt = timestamp  
    
    if option == 'year':
        return str(dt.year)
    
    elif option == 'year_month':
        return dt.strftime('%Y-%m')  # e.g., '2017-09'
    
    elif option == 'week':
        # ISO week number with year
        return dt.strftime('%Y-W%V')  # e.g., '2017-W37'
    else:
        return timestamp


def query_to_df(conn, query):
    
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            
            if cur.description is not None:
                # Get column names
                colnames = [desc[0] for desc in cur.description]
                # Fetch all rows
                rows = cur.fetchall()
                # Return as Pandas DataFrame
                return pd.DataFrame(rows, columns=colnames)
            else:
                print('Query did not return any rows')
                return pd.DataFrame()
    except Exception as e:
        raise e
    


def generate_stopwords():
    """
    Generates a frozen set of English stopwords from NLTK and prints it in a format suitable for inclusion in code.
    """
    nltk.download("stopwords")

    words = sorted(stopwords.words("english"))
    print('SAVE TO const.py')
    print(words)


def has_adjacent_swap(old, new):
    """
        Check if two strings differ by an adjacent character swap
        e.g. "tent" vs "tetn" -> return 1
    """
    if len(old) != len(new):
        # different length -> there's a char addition or deletion
        return 0
    
    diffs = []
    for i in range(len(old)):
        # get charactes that differ in order
        if old[i] != new[i]:
            diffs.append(i)
        # old: caro old[2]=r old[3]=o
        # new: caor new[2]=o new[3]=r
        # diffs = [2,3]

    if len(diffs) == 2:
        i, j = diffs
        # check the difference is adjacent (j = i+1) and swapped
        if j == i + 1 and old[i] == new[j] and old[j] == new[i]:
            return 1
    return 0

def strip_accents(text):
    """'Varejão' -> 'Varejao', 'José' -> 'Jose'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

def plural_forms(word):
    """Given a word assumed singular, return the set of forms it could
    plausibly pluralize to for English rules:
    - most nouns: +s                     (cat -> cats)
    - ends in s/x/z/ch/sh: +es           (bus -> buses, box -> boxes)
    - ends in consonant+y: y -> ies      (baby -> babies, city -> cities)
    - ends in vowel+y: +s                (boy -> boys - covered by the +s rule above)
    - ends in f: f -> ves                (leaf -> leaves)
    - ends in fe: fe -> ves              (knife -> knives)

    NOTE: there can be "wrong" cases like buss, but buses will also be there and we check if the other word
    is in the set so it's ok
    """

    VOWELS = set("aeiou")
    forms = {word + "s"}
    if word.endswith(("s", "x", "z", "ch", "sh")):
        forms.add(word + "es")
    if len(word) > 1 and word[-1] == "y" and word[-2] not in VOWELS:
        forms.add(word[:-1] + "ies")
    if word.endswith("f"):
        forms.add(word[:-1] + "ves")
    if word.endswith("fe"):
        forms.add(word[:-2] + "ves")
    return forms

def is_plural_pair(w1, w2):
    """True if w1/w2 are the same word differing only by pluralization,
    checked in both directions."""

    if w1 == w2:
        return False
    return w2 in plural_forms(w1) or w1 in plural_forms(w2)

def normalize_for_residual(text):
    """Strips accents, case, and every non-alphanumeric character
    (including whitespace) - used to compute a 'residual' edit
    distance that isolates real content changes from pure
    formatting noise (case/punctuation/whitespace/accents)."""

    text = strip_accents(text).lower()
    return ''.join(c for c in text if c.isalnum() or c.isspace())

def strip_stopwords(value):
    """Removes stopword tokens in place from the original string"""

    STOPWORD_PATTERN = re.compile(
        r'\b(' + '|'.join(re.escape(w) for w in STOP_WORDS) + r')\b',
        re.IGNORECASE
    )
    new_value, n_subs = STOPWORD_PATTERN.subn('', value)
    new_value = re.sub(r'\s+', ' ', new_value).strip()
    return new_value, n_subs > 0
