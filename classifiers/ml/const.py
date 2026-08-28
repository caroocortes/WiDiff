ML_MODELS = ['kn', 'random_forest','xgboost']
ML_MODELS_LABELS = ['K-Neighbors', 'Random Forest', 'XGBoost']

# ===============================
#  Paths 
# ===============================
TRAINING_INFO_DIR = 'classifiers/ml/training_info' # stores trained models
FEATURES_DIR = 'classifiers/ml/features'
TRAINING_DATASET_DIR = 'classifiers/ml/training_dataset'
CONFIG_DIR = 'classifiers/ml/config'
LOG_DIR = 'classifiers/ml/logs'
SCRIPT_DIR = 'analysis/scripts'
SQL_SCRIPT_DIR = 'analysis/sql'
RESULTS_DIR = 'analysis/results'
LOGS_DIR = 'analysis/logs'

YAML_SETUP_PATH = 'set_up.yml'

BASE_KEY_TYPES = {
    'revision_id': 'BIGINT',
    'property_id': 'INT',
    'value_id': 'TEXT'
}


BASIC_CHANGE_LABELS = ['textual_change', 're_formatting', 'refinement', 'unrefinement', 'property_value_update', 'link_change', 'rewording']

SOFT_INSERTIONS = 'soft_insertions' # normal/deprecated -> preferred 
SOFT_DELETIONS = 'soft_deletions' # rank deprecation (normal/prefered -> deprecated) + adding end time qualifier

CLASSES_PER_DATATYPE = {
    'text': ['textual_change', 're_formatting', 'refinement', 'unrefinement', 'property_value_update'],
    'quantity': ['refinement', 'unrefinement', 'property_value_update', 're_formatting'],
    'time': ['refinement', 'unrefinement', 'property_value_update'],
    'globecoordinate_latitude': ['refinement', 'unrefinement', 'property_value_update'],
    'globecoordinate_longitude': ['refinement', 'unrefinement', 'property_value_update'],
    'entity': ['refinement', 'unrefinement', 'property_value_update', 'link_change'] 
}

WD_STRING_TYPES = ['monolingualtext', 'string', 'external-id', 'url', 'commonsMedia', 'geo-shape', 'tabular-data', 'math', 'musical-notation', 'unknown-values']
WD_ENTITY_TYPES = ['wikibase-item', 'wikibase-entityid', 'wikibase-property', 'wikibase-lexeme', 'wikibase-sense', 'wikibase-form', 'entity-schema']
WD_BASIC_TYPES = ['globecoordinate_latitude', 'globecoordinate_longitude', 'quantity', 'time']
