import yaml
import os
import time

from classifiers.ml.ml_classifier import MLClassifier
from classifiers.llm.llm_classifier import LLMClassifier
from classifiers.rule.rule_based_classifier import RuleBasedClassifier
from classifiers.llm.const import LLM_RESULTS_DIR
import pandas as pd
import json
import psycopg2

def separate_non_latin_changes(conn, datatype, table_suffix):
    """
        Separate tables for text and entity labels that contain non-latin characters
        We only classify on the latin ones
    """

    if datatype == 'entity':
        filter_non_latin = r"""
            (old_value_label = '' OR old_value_label IS NULL) OR
            (new_value_label = '' OR new_value_label IS NULL) OR
            old_value_label ~ '[^\u0000-\u036F\u1E00-\u1EFF\u2000-\u206F\u2070-\u218F]' OR
            new_value_label ~ '[^\u0000-\u036F\u1E00-\u1EFF\u2000-\u206F\u2070-\u218F]'
        """
    else:
        filter_non_latin = r"""
            old_value->>0 ~ '[^\u0000-\u036F\u1E00-\u1EFF\u2000-\u206F\u2070-\u218F]' OR
            new_value->>0 ~ '[^\u0000-\u036F\u1E00-\u1EFF\u2000-\u206F\u2070-\u218F]'
        """

    table = f"features_{datatype}{table_suffix}"
    non_latin_table = f"features_{datatype}_non_latin{table_suffix}"
    latin_tmp_table = f"{table}_latin_tmp"

    cursor = conn.cursor()

    cursor.execute(f"DROP TABLE IF EXISTS {non_latin_table};")
    query_non_latin =f"CREATE TABLE {non_latin_table} AS SELECT * FROM {table} WHERE ({filter_non_latin});"
    cursor.execute(query_non_latin)

    print(query_non_latin)

    cursor.execute(f"DROP TABLE IF EXISTS {latin_tmp_table};")
    query_temp_latin = f"CREATE TABLE IF NOT EXISTS {latin_tmp_table} AS SELECT * FROM {table} WHERE NOT ({filter_non_latin});"
    cursor.execute(query_temp_latin)
    print(query_temp_latin)

    cursor.execute(f"DROP TABLE {table};")
    query_rename = f"ALTER TABLE {latin_tmp_table} RENAME TO {table};"
    cursor.execute(query_rename)

    conn.commit()

if __name__ == "__main__":

    set_up_path = 'classifier_setup.yml'
    with open(set_up_path, 'r') as f:
        set_up = yaml.safe_load(f)

    classifier_type = set_up['classifier_type']
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    ml_config_path = os.path.join(SCRIPT_DIR, "classifiers", "ml", "config", "ml_classifier_config.json")
    llm_config_path = os.path.join(SCRIPT_DIR, "classifiers", "llm", "config", "llm_classifier_config.json")

    if classifier_type == 'ml':
            
        ml_classifier = MLClassifier(config_path=ml_config_path)
        if set_up['classification_ml']['train']:
            ml_classifier.train_classifier()
        if set_up['classification_ml']['evaluate']:
            ml_classifier.evaluate_cross_validation()

    if classifier_type == 'llm':
        classifier = LLMClassifier(config_path=llm_config_path)
        datatypes = ['text', 'entity']
        for datatype in datatypes:
            
            path_to_file = set_up['classification_llm'][f'path_to_{datatype}_changes']
            df = pd.read_csv(path_to_file)
            start_time = time.time()
            df_new = classifier._run_batch_classification(df, datatype, 'llm_label')
            end_time = time.time()
            print(f"Time taken for LLM classification of {datatype} changes: {end_time - start_time} seconds")
            os.makedirs(LLM_RESULTS_DIR, exist_ok=True)
            df_new.to_csv(f"{LLM_RESULTS_DIR}/gs_{datatype}_with_llm_labels.csv", index=False)
            classifier.evaluate()

    if classifier_type == 'ml' and set_up['classification_ml']['classify']:
        datatypes = ['entity', 'text']
        table_suffix = set_up['classification_ml']['table_suffix']

        db_config_path =set_up.get("db_config_path", "config/db_config.json")
        with open(db_config_path) as f:
            db_config = json.load(f)

        try:
            conn = psycopg2.connect(
                dbname=db_config["DB_NAME"],
                user=db_config["DB_USER"],
                password=db_config["DB_PASS"],
                host=db_config["DB_HOST"],
                port=db_config["DB_PORT"],
                connect_timeout=30,
                gssencmode='disable'
            )
        except Exception as e:
            print(f"Error connecting to the database: {e}")
            exit(1)

        if set_up['separate_non_latin_text']:
            print(f'Separating non-latin values for datatype: text', flush=True)
            separate_non_latin_changes(conn, 'text', table_suffix)
            print(f'Finished separating non-latin values for datatype: text', flush=True)
            set_up['separate_non_latin_text'] = False
            with open(set_up_path, 'w') as f:
                yaml.dump(set_up, f)

        if set_up['separate_non_latin_entity']:
            print(f'Separating non-latin values for datatype: entity', flush=True)
            separate_non_latin_changes(conn, 'entity', table_suffix)
            print(f'Finished separating non-latin values for datatype: entity', flush=True)
            set_up['separate_non_latin_entity'] = False
            with open(set_up_path, 'w') as f:
                yaml.dump(set_up, f)

        classifier = MLClassifier(config_path=ml_config_path)
        for datatype in datatypes:
            if datatype == 'entity' and set_up.get('update_entity_labels_descriptions', False):
                rb_classifier = RuleBasedClassifier(conn=conn, set_up=set_up)
                print(f'Updating entity labels and descriptions for table suffix: {table_suffix}', flush=True)
                rb_classifier.update_label_description_entity_features(table_suffix)

                # set to False so it doesn't updates hte labels and descriptions again
                set_up['update_entity_labels_descriptions'] = False
                with open(set_up_path, 'w') as f:
                    yaml.dump(set_up, f)
                print(f'Finished updating entity labels and descriptions for table suffix: {table_suffix}', flush=True)

            start = time.perf_counter()
            rb_classifier.entity_rb_classification(table_suffix)
            end_time = time.perf_counter()
            print(f"Total time taken for rule-based classification for {datatype} and suffix {table_suffix}: {end_time - start} seconds")
            conn.close()

            classifier.classify_changes(datatype, table_suffix, db_config_path)