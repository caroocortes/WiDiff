import yaml
import os
import time

from classifiers.ml.ml_classifier import MLClassifier
from classifiers.llm.llm_classifier import LLMClassifier
from classifiers.llm.const import LLM_RESULTS_DIR
import pandas as pd

if __name__ == "__main__":

    with open('ml_classify_setup.yml', 'r') as f:
        set_up = yaml.safe_load(f)

    classifier_type = set_up['classification']['classifier_type']
    
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
        datatypes = ['text']
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
        classifier = MLClassifier(config_path=ml_config_path)
        for datatype in datatypes:
            if classifier_type == 'ml':
                table_prefix = set_up['classification_ml']['table_prefix']
                max_batches = set_up['classification_ml']['max_batches']
                db_config_path = set_up['config']['db_config_path']
                classifier.classify_changes(datatype, table_prefix, db_config_path, max_batches=max_batches)