import time
import json
import psycopg2
import os
from pathlib import Path
import pandas as pd
import subprocess
import shutil
import logging
import time
import argparse
import tempfile
from urllib.parse import quote

from preflight_check import postgres_preflight, qlever_preflight

WD = "http://www.wikidata.org/entity/"
WD_PROP = "http://www.wikidata.org/prop/"
NS_EXAMPLE = "https://example.org/schema#"
WD_USER = "https://www.wikidata.org/w/index.php?title=User:"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"


WD_STRING_TYPES = ['monolingualtext', 'string', 'external-id', 'url', 'commonsMedia', 'geo-shape', 'tabular-data', 'math', 'musical-notation']
WD_ENTITY_TYPES = ['wikibase-item', 'wikibase-entityid', 'wikibase-property', 'wikibase-lexeme', 'wikibase-sense', 'wikibase-form', 'entity-schema']

SUFFIXES = ['', '_sa', '_ao', '_less']

DATA_DIR = "data"

def collapsed_path(change_type, file_dir, suffix, data_dir=DATA_DIR):
    return os.path.join(data_dir, file_dir, f"{change_type}{suffix}.csv")

def discover_dump_file_dirs(data_dir=DATA_DIR):
    """Each dump file lives in its own subdirectory of data/. A
    directory counts as a dump file dir if it has at least the plain
    (suffix='') revision.csv - every dump dir is guaranteed to have
    that much, even if none of the _sa/_ao/_less parts exist yet."""
    dirs = []
    for entry in sorted(os.listdir(data_dir)):
        full = os.path.join(data_dir, entry)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, "revision.csv")):
            dirs.append(entry)
    return dirs

def discover_processed_units(data_dir=DATA_DIR):
    """[(file_dir, suffix), ...] for every physical source file that's
    already been through this script (i.e. has a *collapsed*
    revision<suffix>.csv, not just the raw revision<suffix>_old.csv) -
    what load_data.py actually loads from."""
    units = []
    for file_dir in discover_dump_file_dirs(data_dir):
        base = os.path.join(data_dir, file_dir)
        for suffix in SUFFIXES:
            if os.path.exists(os.path.join(base, f"revision{suffix}.csv")):
                units.append((file_dir, suffix))
    return units

def setup_logger(log_dir="results", name="run"):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # avoid duplicate handlers if this gets called more than once in a session

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info(f"Logging to {log_path}")
    return logger

logger = setup_logger()

def create_change_ontology():

    ontology_text = [
        ':Change a owl:Class ;',
        'rdfs:comment "An atomic edit to some aspect of a Wikidata statement, one row per revision. Abstract - every change node is exactly one of the four subclasses below, never :Change directly." .',
        ':ValueChange a owl:Class ;',
        'rdfs:subClassOf :Change ;',
        'rdfs:comment "A change to a statement\'s own value (create/update/delete of old_value/new_value)." .',
        ':RankChange a owl:Class ;',
        'rdfs:subClassOf :Change ;',
        'rdfs:comment "A change to a statement\'s rank (preferred/normal/deprecated)." .',
        ':QualifierChange a owl:Class ;',
        'rdfs:subClassOf :Change ;',
        'rdfs:comment "A change to one of a statement\'s qualifier values." .',
        ':ReferenceChange a owl:Class ;',
        'rdfs:subClassOf :Change ;',
        'rdfs:comment "A change to one of a statement\'s reference values." .',
        ':revisionId  a owl:DatatypeProperty ; rdfs:domain :Change ; rdfs:comment "Revision this change occurred in." .',
        ':propertyId  a owl:DatatypeProperty ; rdfs:domain :Change ; rdfs:comment "The statement\'s own property." .',
        ':valueId     a owl:DatatypeProperty ; rdfs:domain :Change ; rdfs:comment "The statement (claim) id this change belongs to." .',
        ':action      a owl:DatatypeProperty ; rdfs:domain :Change ; rdfs:comment "CREATE, UPDATE, or DELETE." .',
        ':oldValue    a owl:DatatypeProperty ; rdfs:domain :Change .',
        ':newValue    a owl:DatatypeProperty ; rdfs:domain :Change .',
        ':qualPropertyId a owl:DatatypeProperty ;',
        'rdfs:domain :QualifierChange ;',
        'rdfs:comment "The qualifier\'s own property, distinct from :propertyId (the statement\'s property)." .',
        ':refPropertyId a owl:DatatypeProperty ;',
        'rdfs:domain :ReferenceChange ;',
        'rdfs:comment "The reference\'s own property, distinct from :propertyId (the statement\'s property)." .',
        ':refHash a owl:DatatypeProperty ;',
        'rdfs:domain :ReferenceChange ;',
        'rdfs:comment "Hash identifying a specific reference." .'                                                
    ]

    return '\n'.join(ontology_text), len(ontology_text)

def create_db_schema(conn):
    schema_sql = f"""

        DROP TABLE IF EXISTS reference_change;
        DROP TABLE IF EXISTS qualifier_change;
        DROP TABLE IF EXISTS value_change;
        DROP TABLE IF EXISTS revision;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS properties;
        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS file_paths;

        DROP TYPE IF EXISTS action_enum;
        DROP TYPE IF EXISTS datatype_enum;

        CREATE TYPE action_enum AS ENUM ('CREATE', 'UPDATE', 'DELETE');
        CREATE TYPE datatype_enum AS ENUM ('monolingualtext', 'string', 'external-id', 'url', 'commonsMedia',
                                            'geo-shape', 'tabular-data', 'math', 'musical-notation',
                                            'wikibase-item', 'wikibase-entityid', 'wikibase-property', 'wikibase-lexeme',
                                            'wikibase-sense', 'wikibase-form', 'entity-schema',
                                            'quantity', 'time', 'globecoordinate', 'unknown-values', 'bad');

        CREATE TABLE IF NOT EXISTS file_paths (
            file_id INT,
            file_path TEXT
        );

        CREATE TABLE IF NOT EXISTS properties (
            property_id INT,
            property_label TEXT
        );

        CREATE TABLE IF NOT EXISTS entities (
            entity_id BIGINT,
            entity_label TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INT,
            username TEXT,
            user_type TEXT
        );

        CREATE TABLE IF NOT EXISTS revision (
            revision_id BIGINT,
            timestamp TIMESTAMP WITH TIME ZONE,
            entity_id BIGINT,
            file_id INT,
            user_id INT,
            comment TEXT,
            q_id_redirect TEXT,
            prev_revision_id BIGINT
        );

        CREATE TABLE IF NOT EXISTS value_change (
            revision_id BIGINT ,
            property_id INT,
            value_id TEXT,
            old_value TEXT,
            new_value TEXT,
            old_datatype datatype_enum,
            new_datatype datatype_enum,
            action action_enum
        );

        CREATE TABLE IF NOT EXISTS rank_change (
            revision_id BIGINT ,
            property_id INT,
            value_id TEXT,
            old_value TEXT,
            new_value TEXT,
            action action_enum
        );

        -- Key order (revision_id, value_id, property_id,
        -- qual_property_id, value_hash) is the caller's definition of
        -- statement identity + which qualifier value changed.
        CREATE TABLE IF NOT EXISTS qualifier_change (
            revision_id BIGINT,
            value_id TEXT,
            property_id INT,
            qual_property_id INT,
            value_hash TEXT,
            old_value TEXT,
            new_value TEXT,
            old_datatype datatype_enum,
            new_datatype datatype_enum,
            action action_enum
        );

        -- Key order (revision_id, value_id, property_id
        -- ref_property_id, ref_hash, value_hash).
        CREATE TABLE IF NOT EXISTS reference_change (
            revision_id BIGINT,
            value_id TEXT,
            property_id INT,
            ref_property_id INT,
            ref_hash TEXT,
            value_hash TEXT,
            old_value TEXT,
            new_value TEXT,
            old_datatype datatype_enum,
            new_datatype datatype_enum,
            action action_enum
        );
    """

    cursor = conn.cursor()

    start_time = time.perf_counter()
    cursor.execute(query=schema_sql)
    end_time = time.perf_counter()
    conn.commit()
    logger.info(f"[POSTGRESQL] - Created database schema in {end_time - start_time:.2f} seconds.")
    
    cursor.close()

def copy_csv_with_psql(csv_path, table_name, columns, db_config_path):

    with open(db_config_path) as f:
        db_config = json.load(f)
 
    csv_path = os.path.abspath(csv_path)
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"{csv_path} not found or not readable by this process")
 
    column_list = ", ".join(columns)
 
    # \copy's own parser is stricter than regular SQL about spanning
    # multiple physical lines - even fed from a script file via -f, a
    # multi-line \copy produces "parse error at end of line" (hit this
    # exact bug building export_test_data.sh earlier in this pilot).
    # Single physical line, no embedded newlines, is the reliable form.
    copy_cmd = (
        f"\\copy {table_name} ({column_list}) FROM '{csv_path}' "
        f"WITH (FORMAT csv, HEADER true)"
    )
 
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
        f.write(copy_cmd + "\n")
        sql_file = f.name
 
    env = os.environ.copy()
    env["PGPASSWORD"] = db_config["DB_PASS"]
 
    try:
        start = time.perf_counter()
        proc = subprocess.run(
            [
                "psql",
                "-h", db_config["DB_HOST"],
                "-p", str(db_config["DB_PORT"]),
                "-U", db_config["DB_USER"],
                "-d", db_config["DB_NAME"],
                "-v", "ON_ERROR_STOP=1",
                "-f", sql_file,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        end = time.perf_counter()
 
        if proc.returncode != 0:
            raise RuntimeError(f"psql \\copy failed (exit {proc.returncode}):\n{proc.stderr}")
 
        return end - start
    finally:
        os.unlink(sql_file)

def turtle_literal(value, datatype=None):

    def escape_literal(s):
        return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")

    text = f'"{escape_literal(value)}"'
    if datatype:
        text += f"^^<{datatype}>"
    return text


def to_xsd_datetime_literal(ts):
    """The source CSVs (and Postgres's own text output) give timestamps
    as '2021-02-07 23:06:16+01' - a space separator and a timezone
    offset that isn't always 2-digit-no-colon (some files use '+02',
    others '+0200' or '+02:00'). That is NOT reliably valid xsd:dateTime
    lexical form (which requires 'T' and '+01:00'), so serializing it as
    a plain untyped string literal (as this used to do) meant any SPARQL
    FILTER comparing it against an xsd:dateTime literal was comparing
    incompatible types and silently matched nothing.

    This used to fix the format with a regex that only recognized the
    2-digit-no-colon case ('+02' -> '+02:00') - anything else (e.g. a
    4-digit '+0200' offset, which shows up in some of the per-suffix
    dump files) silently passed through un-reformatted, producing an
    invalid literal and effectively losing the timezone rather than
    preserving it. Parsing with pandas instead of hand-rolled string
    surgery handles every offset shape pandas/dateutil recognize and
    never drops the offset - it raises loudly if a timestamp truly can't
    be parsed, rather than silently emitting a wrong one."""
    parsed = pd.Timestamp(ts)
    return turtle_literal(parsed.isoformat(), datatype=XSD_DATETIME)

def _add_value_and_datatype_triples(add, action, old_value_raw, new_value_raw, old_datatype=None, new_datatype=None):
    """Shared by value_change/qualifier_change/reference_change: emits
    :oldValue/:newValue (as an entity IRI when the datatype is one of
    WD_ENTITY_TYPES, otherwise a literal) and :oldDatatype/:newDatatype,
    gated on action (CREATE only ever has a new*, DELETE only an old*).
    Kept in one place so the three change types can't drift from each
    other on this logic."""

    # Remove the extra quotes the source CSV wraps JSON string values in
    def _strip_csv_quotes(raw):
        if raw and raw[0] == '"' and raw[-1] == '"':
            return raw[1:-1]
        return raw or ''

    old_value = _strip_csv_quotes(old_value_raw)
    new_value = _strip_csv_quotes(new_value_raw)

    if (old_datatype or new_datatype) and (old_datatype in WD_ENTITY_TYPES or new_datatype in WD_ENTITY_TYPES):
        old_value = f'<{WD}{old_value}>'
        new_value = f'<{WD}{new_value}>'

        if action == 'CREATE':
            add(":newValue", new_value)
        elif action == 'DELETE':
            add(":oldValue", old_value)
        else:  # it's an update
            add(":oldValue", old_value)
            add(":newValue", new_value)
    else:
        if action == 'CREATE':
            add(":newValue", turtle_literal(new_value))
        elif action == 'DELETE':
            add(":oldValue", turtle_literal(old_value))
        else:
            add(":oldValue", turtle_literal(old_value))
            add(":newValue", turtle_literal(new_value))

    if action == 'CREATE' and new_datatype:
        add(":newDatatype", turtle_literal(new_datatype))
    elif action == 'DELETE' and old_datatype:
        add(":oldDatatype", turtle_literal(old_datatype))
    elif action == 'UPDATE' and new_datatype and old_datatype:
        add(":oldDatatype", turtle_literal(old_datatype))
        add(":newDatatype", turtle_literal(new_datatype))


def _turtlestar_block_for_change_multiple_tuples(tuple_, type_='revision'):
    """
        property = (
            property_id,
            property_label
        )

        entity = (
            entity_id,
            entity_label
        )

        user = (
            user_id,
            username,
            user_type
        )

        file_paths = (
            file_id,
            file_path
        )

        change = (
            revision_id, 0
            property_id, 1
            value_id, 2
            old_value, 3
            new_value, 4
            old_datatype, 5
            new_datatype, 6
            action, 7
            entity_id 8
        )

        rank = (
            revision_id, 0
            property_id, 1
            value_id, 2
            old_value, 3
            new_value, 4
            action, 5
            entity_id 6
        )

        revision =
            revision_id, 0
            timestamp, 1
            entity_id, 2
            file_path, 3
            user_id, 4
            username, 5
            comment, 6
            q_id_redirect, 7
            prev_revision_id, 8
            file_id, 9
        )
    """

    triples = []

    def add(predicate, obj):
        if obj is not None:
            triples.append(f" {predicate} {obj}")

    if type_ == 'properties':
        main_triple = f"<{WD_PROP}P{tuple_[0]}>"
        add(":propertyLabel", turtle_literal(tuple_[1]))
        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"
    
    elif type_ == 'entities':
        main_triple = f"<{WD}Q{tuple_[0]}>"
        add(":entityLabel", turtle_literal(tuple_[1]))
        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'file_paths':
        main_triple = f":filePath_{tuple_[0]}"
        add(":filePath", turtle_literal(tuple_[1]))
        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'users':
        # user_id", "username", "user_type"
        main_triple = f"<{WD_USER}{quote(str(tuple_[1]), safe='')}>" # username
        if tuple_[0] is not None and tuple_[0] != '': # anonymous don't have a username
            add(":userId", turtle_literal(int(tuple_[0])))
            add(":userType", turtle_literal(tuple_[2]))
        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'value_change':
        # 'revision_id', 'property_id', 'value_id', 'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action', 'entity_id]
        action = tuple_[7]
        revision_id = tuple_[0]
        property_id = tuple_[1]
        value_id = tuple_[2]
        main_triple = f"<https://example.org/schema#{tuple_[0]}_{tuple_[1]}_{tuple_[2]}>"

        revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{tuple_[8]}&oldid={revision_id}>"

        add(":revisionId", revision_id_iri)
        add(":propertyId", f'<{WD_PROP}P{property_id}>')
        add(":valueId", turtle_literal(value_id))
        add("a", ":ValueChange")

        _add_value_and_datatype_triples(add, action, tuple_[3], tuple_[4], tuple_[5], tuple_[6])

        add(":action", turtle_literal(action))

        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'rank_change':
        # 'revision_id', 'property_id', 'value_id', 'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action', 'entity_id]
        action = tuple_[5]
        revision_id = tuple_[0]
        property_id = tuple_[1]
        value_id = tuple_[2]
        main_triple = f"<https://example.org/schema#{tuple_[0]}_{tuple_[1]}_{tuple_[2]}_rank>"

        revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{tuple_[6]}&oldid={revision_id}>"

        add(":revisionId", revision_id_iri)
        add(":propertyId", f'<{WD_PROP}P{property_id}>')
        add(":valueId", turtle_literal(value_id))
        add("a", ":RankChange")
        _add_value_and_datatype_triples(add, action, tuple_[3], tuple_[4])

        add(":action", turtle_literal(action))

        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'qualifier_change':
        # 'revision_id', 'property_id', 'value_id', 'qual_property_id', 'value_hash', 'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action', 'entity_id'
        revision_id, property_id, value_id, qual_property_id, value_hash, \
            old_value_raw, new_value_raw, old_datatype, new_datatype, action, entity_id = tuple_

        main_triple = (f"<https://example.org/schema#{revision_id}_{property_id}_{value_id}_"
                        f"{qual_property_id}_{value_hash}>")

        revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{entity_id}&oldid={revision_id}>"

        add(":revisionId", revision_id_iri)
        # :propertyId / :valueId identify the parent statement this qualifier
        # belongs to - the same predicates value_change uses, so a query can
        # join a value_change to its qualifier_changes on (propertyId, valueId).
        add(":propertyId", f'<{WD_PROP}P{property_id}>')
        add(":valueId", turtle_literal(value_id))
        add(":qualPropertyId", f'<{WD_PROP}P{qual_property_id}>')
        add(":valueHash", turtle_literal(value_hash))
        add("a", ":QualifierChange")


        _add_value_and_datatype_triples(add, action, old_value_raw, new_value_raw, old_datatype, new_datatype)

        add(":action", turtle_literal(action))

        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    elif type_ == 'reference_change':
        # 'revision_id', 'property_id', 'value_id', 'ref_property_id', 'ref_hash', 'value_hash', 'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action', 'entity_id'
        revision_id, property_id, value_id, ref_property_id, ref_hash, value_hash, \
            old_value_raw, new_value_raw, old_datatype, new_datatype, action, entity_id = tuple_

        main_triple = (f"<https://example.org/schema#{revision_id}_{property_id}_{value_id}_"
                        f"{ref_property_id}_{ref_hash}_{value_hash}>")

        revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{entity_id}&oldid={revision_id}>"

        add(":revisionId", revision_id_iri)
        add(":propertyId", f'<{WD_PROP}P{property_id}>')
        add(":valueId", turtle_literal(value_id))
        add(":refPropertyId", f'<{WD_PROP}P{ref_property_id}>')
        add(":refHash", turtle_literal(ref_hash))
        add(":valueHash", turtle_literal(value_hash))
        add("a", ":ReferenceChange")

        _add_value_and_datatype_triples(add, action, old_value_raw, new_value_raw, old_datatype, new_datatype)

        add(":action", turtle_literal(action))

        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    if type_ == 'revision':
        revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{tuple_[2]}&oldid={tuple_[0]}>"
        main_triple = revision_id_iri
        add(":timestamp", to_xsd_datetime_literal(tuple_[1]))  # see to_xsd_datetime_literal for why this needs real xsd:dateTime typing
        add(":entityId", f'<{WD}Q{tuple_[2]}>')

        # 'revision_id', 'timestamp', 'entity_id','user_id', 'username', 'comment', 'q_id_redirect', 'prev_revision_id', 'file_id'
        if tuple_[4] is not None and tuple_[4] != '':
            add(":userName", f"<{WD_USER}{quote(str(tuple_[4]), safe='')}>")

        add(":comment", turtle_literal(tuple_[5]))
        if tuple_[6] is not None and tuple_[6] != '':
            add(":redirectQid", f'<{WD}Q{tuple_[6]}>')

        if tuple_[7] is not None and tuple_[7] != -1:
            prev_revision_id_iri = f"<https://www.wikidata.org/w/index.php?title=Q{tuple_[2]}&oldid={tuple_[7]}>"
            add(":prevRevId", prev_revision_id_iri)

        add(":fileId", turtle_literal(f':filePath_{tuple_[8]}'))

        block = f"{main_triple} " + " ;\n    ".join(triples) + " .\n"

    return block, len(triples)

def serialize_batch_to_turtle(batch, type_='revision'):
    """
        Creates all triples and saves them to a ttl file.
        Changes are processed in batches to reduce memory consumption.
    """
    triples = []
    total_triples = 0
    for change in batch:
        block, num_triples = _turtlestar_block_for_change_multiple_tuples(change, type_=type_)
        total_triples += num_triples
        triples.append(block)

    batch.clear()  # free memory after processing the batch

    return "\n".join(triples) + "\n", total_triples

def write_ttl_batch(ttl_path, batch, type_='revision', write_prefixes=False):
    """
    Serializes one batch and appends it to ttl_path. Pass
    write_prefixes=True exactly once (the first batch of the run) to
    write the @prefix header.

    Returns (serialization_time, num_triples).
    """
    start_ser = time.time()
    turtle_body, num_triples = serialize_batch_to_turtle(batch, type_=type_)
    end_ser = time.time()

    mode = 'w' if write_prefixes else 'a'
    with open(ttl_path, mode, encoding='utf-8') as f:
        if write_prefixes:
            f.write(f"@prefix : <{NS_EXAMPLE}> .\n")
            f.write(f"@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")
            f.write(f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
            f.write(f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n")
            f.write(f"@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n")

            ontology_text, num_triples_ontology = create_change_ontology()
            f.write(ontology_text + "\n\n")

            num_triples += num_triples_ontology
            
        f.write(turtle_body)

    return end_ser - start_ser, num_triples


def bulk_load_ttl_jena(ttl_path, tdb_loc, tdbloader_cmd='tdb2.tdbloader'):
    """
    The one-shot bulk load for the jena_ttl path: reads the accumulated
    .ttl file from disk (not stdin) and hands it to tdbloader once. Timed
    separately from serialization.
    """
    start_load = time.time()
    proc = subprocess.run(
        [tdbloader_cmd, '--loc', str(tdb_loc), '--syntax', 'Turtle', str(ttl_path)],
        capture_output=True,
    )
    end_load = time.time()

    if proc.returncode != 0:
        raise RuntimeError(f"tdbloader failed (exit {proc.returncode}):\n{proc.stderr.decode(errors='replace')}")

    return end_load - start_load


def load_diffs_postgresql(csv_path, table_name, columns, db_config_path):
    copy_time = copy_csv_with_psql(csv_path, table_name, columns, db_config_path)
    return copy_time

def rows_to_tuples(df, columns=None):
    """Converts a CSV-loaded DataFrame into a list of plain tuples in
    column_order, matching the positional format the parser expects."""

    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV is missing expected columns: {missing}. "
            f"Update CSV_COLUMN_ORDER to match your actual CSV headers."
        )
    df = df[columns].fillna('')

    return [tuple(row) for row in df.itertuples(index=False, name=None)]


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Compares insert to Relational DB vs Jena TDB vs QLever for wikidata change data.')
    parser.add_argument('-db','--db_type', help='Set to "postgresql" or "qlever"', required=True, choices=['postgresql', 'qlever'])
    args = vars(parser.parse_args())

    logger.info(f"DB: {args['db_type']} \n")

    change_cols = ['revision_id', 'property_id', 'value_id', 'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action']
    revision_cols = ['revision_id', 'timestamp', 'entity_id','user_id', 'username', 'comment', 'q_id_redirect', 'prev_revision_id', 'file_id']
    qualifier_change_cols = ['revision_id', 'property_id', 'value_id', 'qual_property_id', 'value_hash',
                              'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action']
    reference_change_cols = ['revision_id', 'property_id', 'value_id', 'ref_property_id', 'ref_hash', 'value_hash',
                              'old_value', 'new_value', 'old_datatype', 'new_datatype', 'action']
    rank_change_cols = ['revision_id', 'property_id', 'value_id', 'old_value', 'new_value', 'action']

    properties_cols = ['property_id', 'property_label']
    entities_cols = ['entity_id', 'entity_label']
    file_paths_cols = ['file_id', 'file_path']
    users_cols = ['user_id', 'username', 'user_type']

    units = discover_processed_units()

    if not units:
        raise SystemExit("No processed units discovered under data/ (looked for data/<dir>/revision*.csv). ")

    def _existing_paths(change_type):
        paths = [collapsed_path(change_type, file_dir, suffix) for file_dir, suffix in units]
        return [p for p in paths if os.path.exists(p)]

    value_change_file_paths = _existing_paths("value_change")
    rank_change_file_paths = _existing_paths("rank_change")
    revision_file_paths = _existing_paths("revision")
    qualifier_change_file_paths = _existing_paths("qualifier_change")
    reference_change_file_paths = _existing_paths("reference_change")

    logger.info(f"Discovered {len(units)} unit(s)")
    logger.info(f"value_change files: {len(value_change_file_paths)}, revision files: {len(revision_file_paths)}, "
                f"rank_change files: {len(rank_change_file_paths)} (of {len(units)} units), "
                f"qualifier_change files: {len(qualifier_change_file_paths)} (of {len(units)} units), "
                f"reference_change files: {len(reference_change_file_paths)} (of {len(units)} units)")
    if len(qualifier_change_file_paths) < len(units) or len(reference_change_file_paths) < len(units):
        logger.warning("Not every unit has a qualifier_change/reference_change CSV yet - "
                        "loading what's available. See data/dimension_build_completeness.json.")

    properties_file_path = "data/properties.csv"
    entities_file_path = "data/entities.csv"
    users_file_path = "data/users.csv"
    files_file_path = "data/file_paths.csv"

    if not os.path.exists("results"):
        os.makedirs("results")

    if "loading_creation_stats.json" in os.listdir("results"):
        with open("results/loading_creation_stats.json", "r") as f:
            json_stats = json.load(f)
    else:
        json_stats = {}

    if args['db_type'] == 'postgresql':

        db_config_path = "config/postgresql_db_config.json"
        with open(db_config_path) as f:
            db_config = json.load(f)            

        try:
            preflight = postgres_preflight(db_config_path, db_name=db_config["DB_NAME"])
            json_stats.setdefault('postgresql', {})['preflight'] = preflight
            if preflight.get('contention_warning'):
                logger.warning(f"[POSTGRESQL] Other databases on this instance have active connections: "
                                f"{preflight['other_databases_with_active_connections']} - "
                                f"timings below may be contaminated by an unrelated workload.")
            logger.info(f"[POSTGRESQL] Preflight: shared_buffers={preflight['settings']['shared_buffers']}, "
                        f"effective_cache_size={preflight['settings']['effective_cache_size']}, "
                        f"work_mem={preflight['settings']['work_mem']}, database_size={preflight['database_size_pretty']}")
        except Exception as e:
            logger.warning(f"[POSTGRESQL] Preflight check failed (continuing anyway): {e}")

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

        create_db_schema(conn)

        df = pd.read_csv(files_file_path,header=0)
        # just load file_path because its incremental id on the db
        lt = load_diffs_postgresql(files_file_path, 'file_paths', file_paths_cols, db_config_path)
        logger.info(f"[POSTGRESQL] - Loaded {len(df)} file paths in {lt:.2f} seconds.")

        json_stats.setdefault('postgresql', {})['file_paths'] = {
            'num_file_paths': len(df),
            'load_time_sec': lt
        }

        df = pd.read_csv(properties_file_path,header=0)
        lt = load_diffs_postgresql(properties_file_path, 'properties', properties_cols, db_config_path)
        logger.info(f"[POSTGRESQL] - Loaded {len(df)} properties in {lt:.2f} seconds.")

        json_stats['postgresql']['properties'] = {
            'num_properties': len(df),
            'load_time_sec': lt
        }

        df = pd.read_csv(entities_file_path,header=0)
        lt = load_diffs_postgresql(entities_file_path, 'entities', entities_cols, db_config_path)
        logger.info(f"[POSTGRESQL] - Loaded {len(df)} entities in {lt:.2f} seconds.")

        json_stats['postgresql']['entities'] = {
            'num_entities': len(df),
            'load_time_sec': lt
        }

        df = pd.read_csv(users_file_path,header=0)
        lt = load_diffs_postgresql(users_file_path, 'users', users_cols, db_config_path)
        logger.info(f"[POSTGRESQL] - Loaded {len(df)} users rows in {lt:.2f} seconds.")

        json_stats['postgresql']['users'] = {
            'num_users': len(df),
            'load_time_sec': lt
        }

        total_revisions = 0
        loading_time_sec = 0
        for revision_file_path in revision_file_paths:
            revision_file_path_postgresql = revision_file_path.split('.')[0] + '_for_postgresql.csv'

            # the triples need the extra entity_id to construct the revision IRI, so I remove it because PostgreSQL doesn't need it 
            df = pd.read_csv(revision_file_path, usecols=revision_cols,header=0)
            if 'username' in df.columns:
                df.drop(columns=['username'], inplace=True)
                revision_cols.pop(revision_cols.index('username'))
            
            df['user_id'] = df['user_id'].astype('Int64')
            
            df[revision_cols].to_csv(revision_file_path_postgresql, index=False, header=True)
            
            if 'username' in revision_cols:
                revision_cols.pop(revision_cols.index('username'))

            df = pd.read_csv(revision_file_path_postgresql, usecols=revision_cols,header=0)
            if len(df) != 0:
                lt = load_diffs_postgresql(revision_file_path_postgresql, 'revision', revision_cols, db_config_path)
                logger.info(f"[POSTGRESQL] - Loaded {len(df)} rows from {revision_file_path_postgresql} in {lt:.2f} seconds.")

                loading_time_sec += lt
                total_revisions += len(df)

            os.remove(revision_file_path_postgresql)

        json_stats['postgresql']['revision'] = {
            'num_revisions': total_revisions,
            'load_time_sec': loading_time_sec
        }

        total_value_changes = 0
        loading_time_sec = 0

        for value_change_file_path in value_change_file_paths:
            value_change_file_path_postgresql = value_change_file_path.split('.')[0] + '_for_postgresql.csv'
            # the triples need the extra entity_id to construct the revision IRI, so I remove it because PostgreSQL doesn't need it 
            df = pd.read_csv(value_change_file_path, usecols=change_cols,header=0)
            df[change_cols].to_csv(value_change_file_path_postgresql, index=False, header=True)
            
            value_change_file_path = value_change_file_path_postgresql
            df = pd.read_csv(value_change_file_path, usecols=change_cols,header=0)
            if len(df) != 0:
                lt = load_diffs_postgresql(value_change_file_path, 'value_change', change_cols, db_config_path)
                logger.info(f"[POSTGRESQL] - Loaded {len(df)} rows from {value_change_file_path} in {lt:.2f} seconds.")

                loading_time_sec += lt
                total_value_changes += len(df)

            os.remove(value_change_file_path_postgresql)

        json_stats['postgresql']['value_change'] = {
            'num_value_changes': total_value_changes,
            'load_time_sec': loading_time_sec
        }

        total_rank_changes = 0
        loading_time_sec = 0
        for rank_change_file_path in rank_change_file_paths:
            rank_change_file_path_postgresql = rank_change_file_path.split('.')[0] + '_for_postgresql.csv'

            # the triples need the extra entity_id to construct the revision IRI, so I remove it because PostgreSQL doesn't need it 
            df = pd.read_csv(rank_change_file_path, usecols=rank_change_cols,header=0)
            df[rank_change_cols].to_csv(rank_change_file_path_postgresql, index=False, header=True)
            
            rank_change_file_path = rank_change_file_path_postgresql
            df = pd.read_csv(rank_change_file_path, usecols=rank_change_cols,header=0)
            if len(df) != 0:
                lt = load_diffs_postgresql(rank_change_file_path, 'rank_change', rank_change_cols, db_config_path)
                logger.info(f"[POSTGRESQL] - Loaded {len(df)} rows from {rank_change_file_path} in {lt:.2f} seconds.")

                loading_time_sec += lt
                total_rank_changes += len(df)

            os.remove(rank_change_file_path_postgresql)

        json_stats['postgresql']['rank_change'] = {
            'num_rank_changes': total_rank_changes,
            'load_time_sec': loading_time_sec
        }

        total_qualifier_changes = 0
        loading_time_sec = 0
        for qualifier_change_file_path in qualifier_change_file_paths:
            qualifier_change_file_path_postgresql = qualifier_change_file_path.split('.')[0] + '_for_postgresql.csv'
            
            df = pd.read_csv(qualifier_change_file_path, usecols=qualifier_change_cols, header=0)
            df[qualifier_change_cols].to_csv(qualifier_change_file_path_postgresql, index=False, header=True)

            df = pd.read_csv(qualifier_change_file_path_postgresql, usecols=qualifier_change_cols, header=0)
            if len(df) != 0:
                lt = load_diffs_postgresql(qualifier_change_file_path_postgresql, 'qualifier_change', qualifier_change_cols, db_config_path)
                logger.info(f"[POSTGRESQL] - Loaded {len(df)} rows from {qualifier_change_file_path_postgresql} in {lt:.2f} seconds.")
                
                loading_time_sec += lt
                total_qualifier_changes += len(df)

            os.remove(qualifier_change_file_path_postgresql)
   
        json_stats['postgresql']['qualifier_change'] = {
            'num_qualifier_changes': total_qualifier_changes,
            'load_time_sec': loading_time_sec,
        }

        total_reference_changes = 0
        loading_time_sec = 0
        for reference_change_file_path in reference_change_file_paths:
            reference_change_file_path_postgresql = reference_change_file_path.split('.')[0] + '_for_postgresql.csv'
            df = pd.read_csv(reference_change_file_path, usecols=reference_change_cols, header=0)
            df[reference_change_cols].to_csv(reference_change_file_path_postgresql, index=False, header=True)

            df = pd.read_csv(reference_change_file_path_postgresql, usecols=reference_change_cols, header=0)
            if len(df) != 0:
                lt = load_diffs_postgresql(reference_change_file_path_postgresql, 'reference_change', reference_change_cols, db_config_path)
                logger.info(f"[POSTGRESQL] - Loaded {len(df)} rows from {reference_change_file_path_postgresql} in {lt:.2f} seconds.")

                total_reference_changes += len(df)
                loading_time_sec += lt

            os.remove(reference_change_file_path_postgresql)

        json_stats['postgresql']['reference_change'] = {
            'num_reference_changes': total_reference_changes,
            'load_time_sec': loading_time_sec,
        }

        # Add indexes for fair comparison
        cursor = conn.cursor()
        start_time = time.perf_counter()
        cursor.execute(
            f"""
                SET max_parallel_maintenance_workers = 8;
                SET max_parallel_workers = 8;

                ALTER TABLE file_paths ADD PRIMARY KEY (file_id);
                ALTER TABLE properties ADD PRIMARY KEY (property_id);
                ALTER TABLE entities ADD PRIMARY KEY (entity_id);
                ALTER TABLE users ADD PRIMARY KEY (user_id);

                ALTER TABLE revision ADD CONSTRAINT revision_pk PRIMARY KEY (revision_id);
                ALTER TABLE revision ADD CONSTRAINT revision_entity_fk FOREIGN KEY (entity_id) REFERENCES entities(entity_id);
                ALTER TABLE revision ADD CONSTRAINT revision_file_fk FOREIGN KEY (file_id) REFERENCES file_paths(file_id);
                ALTER TABLE revision ADD CONSTRAINT revision_user_fk FOREIGN KEY (user_id) REFERENCES users(user_id);
                
                ALTER TABLE value_change ADD CONSTRAINT value_change_pk PRIMARY KEY (revision_id, property_id, value_id);
                ALTER TABLE value_change ADD CONSTRAINT value_change_revision_fk FOREIGN KEY (revision_id) REFERENCES revision(revision_id);

                ALTER TABLE rank_change ADD CONSTRAINT rank_change_pk PRIMARY KEY (revision_id, property_id, value_id);
                ALTER TABLE rank_change ADD CONSTRAINT rank_change_revision_fk FOREIGN KEY (revision_id) REFERENCES revision(revision_id);

                ALTER TABLE qualifier_change ADD CONSTRAINT qualifier_change_pk
                    PRIMARY KEY (revision_id, value_id, property_id, qual_property_id, value_hash);
                ALTER TABLE qualifier_change ADD CONSTRAINT qualifier_change_revision_fk FOREIGN KEY (revision_id) REFERENCES revision(revision_id);

                ALTER TABLE reference_change ADD CONSTRAINT reference_change_pk
                    PRIMARY KEY (revision_id, value_id, property_id, ref_property_id, ref_hash, value_hash);
                ALTER TABLE reference_change ADD CONSTRAINT reference_change_revision_fk FOREIGN KEY (revision_id) REFERENCES revision(revision_id); """)
        
        conn.commit()
        end_time = time.perf_counter()

        cursor.execute("ANALYZE value_change; ANALYZE revision; ANALYZE qualifier_change; ANALYZE reference_change;")
        conn.commit()

        json_stats['postgresql']['index_creation_time_sec'] = end_time - start_time
        logger.info(f"[POSTGRESQL] - Created indexes in {end_time - start_time:.2f} seconds.")
        cursor.close()

        with open("results/loading_creation_stats.json", "w") as f:
            json.dump(json_stats, f, indent=4)

    elif args['db_type'] == 'qlever':

        change_cols = change_cols + ['entity_id']
        rank_change_cols = rank_change_cols + ['entity_id']
        qualifier_change_cols = qualifier_change_cols + ['entity_id']
        reference_change_cols = reference_change_cols + ['entity_id']

        BATCH_SIZE = 5000
        output_file = 'data/triples_ttl.ttl'
        logger.info(f"Writing Turtle output to {output_file} - triples accumulate on memory, one bulk load happens after all batches are written.")

        if os.path.exists(output_file):
            logger.warning(f"Output file {output_file} already exists. Using existing file to load into {args['db_type']}. If you want to start fresh, delete the file first.")
        else:

            # ------------------------------
            # Write triples of users
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            ttl_prefixes_written = False  # tracks whether we've written the @prefix header + created the file yet

            for chunk in pd.read_csv(users_file_path, usecols=users_cols, chunksize=BATCH_SIZE):
                rows_u = rows_to_tuples(chunk, columns=users_cols)
                if len(rows_u) == 0:
                    continue
                st, nt = write_ttl_batch(output_file, rows_u, type_='users', write_prefixes=not ttl_prefixes_written)
                ttl_prefixes_written = True

                num_triples += nt
                serialization_time += st
            
            df = pd.read_csv(users_file_path, usecols=users_cols)

            if not 'triples_creation' in json_stats.keys():
                json_stats['triples_creation'] = {}
            
            json_stats['triples_creation']['users'] = {
                'num_triples': num_triples,
                'num_entities': len(df),
                'serialization_time_sec': serialization_time
            }
            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of users: {len(df)}. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of entities
            # ------------------------------
            serialization_time = 0
            num_triples = 0

            for chunk in pd.read_csv(entities_file_path, usecols=entities_cols, chunksize=BATCH_SIZE):
                rows_ep = rows_to_tuples(chunk, columns=entities_cols)
                if len(rows_ep) == 0:
                    continue
                st, nt = write_ttl_batch(output_file, rows_ep, type_='entities', write_prefixes=not ttl_prefixes_written)
                ttl_prefixes_written = True

                num_triples += nt
                serialization_time += st
            
            df = pd.read_csv(entities_file_path, usecols=entities_cols)
            
            json_stats['triples_creation']['entities'] = {
                'num_triples': num_triples,
                'num_entities': len(df),
                'serialization_time_sec': serialization_time
            }
            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of entities: {len(df)}. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of files
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            for chunk in pd.read_csv(files_file_path, usecols=file_paths_cols, chunksize=BATCH_SIZE):
                rows_fp = rows_to_tuples(chunk, columns=file_paths_cols)
                st, nt = write_ttl_batch(output_file, rows_fp, type_='file_paths', write_prefixes=not ttl_prefixes_written)
                ttl_prefixes_written = True

                num_triples += nt
                serialization_time += st
            
            df = pd.read_csv(files_file_path, usecols=file_paths_cols)
            
            json_stats['triples_creation']['file_paths'] = {
                'num_triples': num_triples,
                'num_files': len(df),
                'serialization_time_sec': serialization_time
            }
            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of files: {len(df)}. \n Serialization time: {serialization_time:.2f}s.")
            
            # ------------------------------
            # Write triples of properties
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            for chunk in pd.read_csv(properties_file_path, usecols=properties_cols, chunksize=BATCH_SIZE):
                rows_props = rows_to_tuples(chunk, columns=properties_cols)
                if len(rows_props) == 0:
                    continue
                st, nt = write_ttl_batch(output_file, rows_props, type_='properties', write_prefixes=not ttl_prefixes_written)
                ttl_prefixes_written = True

                num_triples += nt
                serialization_time += st
            
            df = pd.read_csv(properties_file_path, usecols=properties_cols)
            
            json_stats['triples_creation']['properties'] = {
                'num_triples': num_triples,
                'num_properties': len(df),
                'serialization_time_sec': serialization_time
            }
            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of properties: {len(df)}. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of revisions
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            total_revisions = 0
            for revision_file_path in revision_file_paths:
                print(f"Processing revision file: {revision_file_path}")
                for chunk in pd.read_csv(revision_file_path, usecols=revision_cols, chunksize=BATCH_SIZE):
                    rows_rev = rows_to_tuples(chunk, columns=revision_cols)
                    if len(rows_rev) == 0:
                        continue
                    st, nt = write_ttl_batch(output_file, rows_rev, type_='revision', write_prefixes=not ttl_prefixes_written)
                    ttl_prefixes_written = True

                    num_triples += nt
                    serialization_time += st
                
                df = pd.read_csv(revision_file_path, usecols=revision_cols)
                total_revisions += len(df)
            
            json_stats['triples_creation']['revision'] = {
                'num_triples': num_triples,
                'num_revisions': total_revisions,
                'serialization_time_sec': serialization_time
            }

            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of revisions: {total_revisions} revisions. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of value changes
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            total_changes = 0
            for value_change_file_path in value_change_file_paths:
                print(f"Processing value change file: {value_change_file_path}")
                for chunk in pd.read_csv(value_change_file_path, usecols=change_cols, chunksize=BATCH_SIZE):
                    rows_vc = rows_to_tuples(chunk, columns=change_cols)
                    if len(rows_vc) == 0:
                        continue
                    st, nt = write_ttl_batch(output_file, rows_vc, type_='value_change', write_prefixes=not ttl_prefixes_written)
                    ttl_prefixes_written = True

                    num_triples += nt
                    serialization_time += st
                
                df = pd.read_csv(value_change_file_path, usecols=change_cols)
                total_changes += len(df)

            json_stats['triples_creation']['value_change'] = {
                'num_triples': num_triples,
                'num_value_changes': total_changes,
                'serialization_time_sec': serialization_time
            }

            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of value changes: {total_changes} value changes. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of rank changes
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            total_changes = 0
            for rank_change_file_path in rank_change_file_paths:
                print(f"Processing rank change file: {rank_change_file_path}")
                for chunk in pd.read_csv(rank_change_file_path, usecols=rank_change_cols, chunksize=BATCH_SIZE):
                    rows_rc = rows_to_tuples(chunk, columns=rank_change_cols)
                    if len(rows_rc) == 0:
                        continue
                    st, nt = write_ttl_batch(output_file, rows_rc, type_='rank_change', write_prefixes=not ttl_prefixes_written)
                    ttl_prefixes_written = True

                    num_triples += nt
                    serialization_time += st
                
                df = pd.read_csv(rank_change_file_path, usecols=rank_change_cols)
                total_changes += len(df)

            json_stats['triples_creation']['rank_change'] = {
                'num_triples': num_triples,
                'num_rank_changes': total_changes,
                'serialization_time_sec': serialization_time
            }

            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of rank changes: {total_changes} rank changes. \n Serialization time: {serialization_time:.2f}s.")


            # ------------------------------
            # Write triples of qualifier changes
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            total_changes = 0
            for qualifier_change_file_path in qualifier_change_file_paths:
                print(f"Processing qualifier change file: {qualifier_change_file_path}")
                for chunk in pd.read_csv(qualifier_change_file_path, usecols=qualifier_change_cols, chunksize=BATCH_SIZE):
                    rows_qc = rows_to_tuples(chunk, columns=qualifier_change_cols)
                    if len(rows_qc) == 0:
                        continue
                    st, nt = write_ttl_batch(output_file, rows_qc, type_='qualifier_change', write_prefixes=not ttl_prefixes_written)
                    ttl_prefixes_written = True

                    num_triples += nt
                    serialization_time += st

                df = pd.read_csv(qualifier_change_file_path, usecols=qualifier_change_cols)
                total_changes += len(df)

            json_stats['triples_creation']['qualifier_change'] = {
                'num_triples': num_triples,
                'num_qualifier_changes': total_changes,
                'serialization_time_sec': serialization_time
            }

            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of qualifier changes: {total_changes}. \n Serialization time: {serialization_time:.2f}s.")

            # ------------------------------
            # Write triples of reference changes
            # ------------------------------
            serialization_time = 0
            num_triples = 0
            total_changes = 0
            for reference_change_file_path in reference_change_file_paths:
                print(f"Processing reference change file: {reference_change_file_path}")
                for chunk in pd.read_csv(reference_change_file_path, usecols=reference_change_cols, chunksize=BATCH_SIZE):
                    rows_rc = rows_to_tuples(chunk, columns=reference_change_cols)
                    if len(rows_rc) == 0:
                        continue
                    st, nt = write_ttl_batch(output_file, rows_rc, type_='reference_change', write_prefixes=not ttl_prefixes_written)
                    ttl_prefixes_written = True

                    num_triples += nt
                    serialization_time += st

                df = pd.read_csv(reference_change_file_path, usecols=reference_change_cols)
                total_changes += len(df)

            json_stats['triples_creation']['reference_change'] = {
                'num_triples': num_triples,
                'num_reference_changes': total_changes,
                'serialization_time_sec': serialization_time
            }

            logger.info(f"Wrote to {output_file}: \n Number of triples: {num_triples} \n Number of reference changes: {total_changes}. \n Serialization time: {serialization_time:.2f}s.")

            with open("results/loading_creation_stats.json", "w") as f:
                json.dump(json_stats, f, indent=4)

        if args['db_type'] == 'qlever':
            qlever_config_path = "config/qlever_db_config.json"
            with open(qlever_config_path) as f:
                qlever_config = json.load(f)

            json_stats.setdefault('qlever', {})['preflight'] = qlever_preflight()
            with open("results/loading_creation_stats.json", "w") as f:
                json.dump(json_stats, f, indent=4)

            prev_output_file = output_file.rsplit('/', 1)[1]  # get the file part of the path
            qlever_output_file = qlever_config['DATA_DIR'] + '/' + prev_output_file  # prepend QLever's DATA_DIR to the output file path

            if not os.path.exists(qlever_output_file):
                logger.info(f"Copying {prev_output_file} to QLever's data directory: {qlever_output_file} for index creation.")
                subprocess.run(["cp", output_file, qlever_output_file], check=True)

            if shutil.which("sbatch"):
                logger.info("sbatch found - submitting QLever index creation job via Slurm "
                            "(dedicated, resource-matched to the PostgreSQL benchmark job - see qlever/qlever_index.slurm)")
                subprocess.run(["sbatch", "--wait", "qlever/qlever_index.slurm"], check=True)
            else:
                logger.info("sbatch not found - running QLever index creation directly instead "
                             "of submitting a Slurm job (see qlever/qlever_index.sh).")
                subprocess.run(["bash", "qlever/qlever_index.sh"], check=True)
            