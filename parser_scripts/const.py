WIKIDATA_SERVICE_URL = "https://dumps.wikimedia.org/wikidatawiki/20250601/"

# --------------------------------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------------------------------
DOWNLOAD_LINKS_FILE_PATH = 'auxiliary_data/xml_download_links.txt'
LOGS_DIR = 'logs'
CLAIMED_FILES_PATH = "logs/claimed_files.txt"
LOCK_FILE_PATH = "logs/file_claim.lock"
PROCESSED_FILES_PATH = 'logs/processed_files.txt'
SETUP_PATH = 'setup.yml'
PARSER_LOG_FILES_PATH = 'parser_log_files.csv'
ERROR_REVISION_TEXT_PATH = "logs/error_revision_text.txt"
REVISION_NO_CLAIMS_TEXT_PATH = "logs/revision_no_claims.txt"
PROPERTY_LABELS_PATH = f'auxiliary_data/property_labels.csv'
ENTITY_LABEL_ALIAS_PATH = f'auxiliary_data/labels_aliases.csv'
SUBCLASS_OF_PATH = f'auxiliary_data/p279_entity_types.csv'
INSTANCE_OF_PATH = f'auxiliary_data/p31_entity_types.csv'

TRANSITIVE_CLOSURE_PICKLE_FILE_PATH = 'auxiliary_data/transitive_closures/transitive_closure_cache.pkl'
TRANSITIVE_CLOSURE_STATS_PICKLE_FILE_PATH = 'auxiliary_data/transitive_closures/transitive_closure_stats.pkl'

DATA_PATH = 'auxiliary_data'

# --------------------------------------------------------------------------------------------------------------
# PATH TO SUBCLASSES OF ASTRONOMICAL OBJECTS AND SCHOLARLY ARTICLES
# It is used to identify entities of these types
# --------------------------------------------------------------------------------------------------------------
ASTRONOMICAL_OBJECT_TYPES_PATH = f'auxiliary_data/subclassof_astronomical_object.csv'
SCHOLARLY_ARTICLE_TYPES_PATH = 'auxiliary_data/subclassof_scholarly_article.csv'

# --------------------------------------------------------------------------------------------------------------
# LOG PATHS
# --------------------------------------------------------------------------------------------------------------
SCHOLARLY_ARTICLE_STATS_FILE_PATH = 'logs/stats/scholarly_article_stats.csv'
ASTRONOMICAL_OBJECT_STATS_FILE_PATH = 'logs/stats/astronomical_object_stats.csv'
LESS20_STATS_FILE_PATH = 'logs/stats/less20_stats.csv'
STATS_FILE_PATH = 'logs/stats/stats.csv'

# --------------------------------------------------------------------------------------------------------------
# NAMESPACES
# --------------------------------------------------------------------------------------------------------------
WD = "http://www.wikidata.org/entity/"
WD_PROP = "http://www.wikidata.org/prop/"
WD_STATEMENT = "http://www.wikidata.org/entity/statement/"
NS = "https://example.org/schema#"

# --------------------------------------------------------------------------------------------------------------
# CHANGE TYPES
# --------------------------------------------------------------------------------------------------------------
CREATE_PROPERTY_VALUE = "CREATE"
UPDATE_PROPERTY_VALUE = "UPDATE"
DELETE_PROPERTY_VALUE = "DELETE"
UPDATE_PROPERTY_DATATYPE_METADATA = "UPDATE"
UPDATE_RANK = "UPDATE"
CREATE_QUALIFIER_VALUE = "CREATE"
DELETE_QUALIFIER_VALUE = "DELETE"
DELETE_REFERENCE_VALUE = "DELETE"
CREATE_REFERENCE_VALUE = "CREATE"

# --------------------------------------------------------------------------------------------------------------
# CSV PATHS FOR TRANSITIVE CLOSURES
# --------------------------------------------------------------------------------------------------------------
CSV_PATHS = {
    'subclass_transitive': 'auxiliary_data/transitive_closures/subclass_of_transitive.csv',
    'part_of_transitive': 'auxiliary_data/transitive_closures/part_of_transitive.csv',
    'has_part_transitive': 'auxiliary_data/transitive_closures/has_parts_transitive.csv',
    'located_in_transitive': 'auxiliary_data/transitive_closures/located_in_transitive.csv',
}

# ------------------------------------------------------------------------------------------------------------------------------
# Label and description aren't considered "properties" with their own P-id's so we create our own
# ------------------------------------------------------------------------------------------------------------------------------
LABEL_PROP_ID = -1
DESCRIPTION_PROP_ID = -2
REVISION_THRESHOLD = 10
RV_KEYWORDS = ['revert', 'rv', 'undid', 'restore', 'rvv', 'vandal', 'undo']

# ------------------------------------------------------------------------------------------------------------------------------
# Queue size for file processing
# ------------------------------------------------------------------------------------------------------------------------------
QUEUE_SIZE = 10000
BATCH_SIZE = 5000

# ------------------------------------------------------------------------------------------------------------------------------
# Wikidata's special values
# ------------------------------------------------------------------------------------------------------------------------------
NO_VALUE = 'novalue'
SOME_VALUE = 'somevalue'

STOP_WORDS = {'a', 'about', 'above', 'after', 'again', 'against', 'ain', 'all', 'am', 'an', 'and', 'any', 'are', 'aren', "aren't", 'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'can', 'couldn', "couldn't", 'd', 'did', 'didn', "didn't", 'do', 'does', 'doesn', "doesn't", 'doing', 'don', "don't", 'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had', 'hadn', "hadn't", 'has', 'hasn', "hasn't", 'have', 'haven', "haven't", 'having', 'he', "he'd", "he'll", "he's", 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', "i'd", "i'll", "i'm", "i've", 'if', 'in', 'into', 'is', 'isn', "isn't", 'it', "it'd", "it'll", "it's", 'its', 'itself', 'just', 'll', 'm', 'ma', 'me', 'mightn', "mightn't", 'more', 'most', 'mustn', "mustn't", 'my', 'myself', 'needn', "needn't", 'no', 'nor', 'not', 'now', 'o', 'of', 'off', 'on', 'once', 'only', 'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 're', 's', 'same', 'shan', "shan't", 'she', "she'd", "she'll", "she's", 'should', "should've", 'shouldn', "shouldn't", 'so', 'some', 'such', 't', 'than', 'that', "that'll", 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 'these', 'they', "they'd", "they'll", "they're", "they've", 'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 've', 'very', 'was', 'wasn', "wasn't", 'we', "we'd", "we'll", "we're", "we've", 'were', 'weren', "weren't", 'what', 'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'will', 'with', 'won', "won't", 'wouldn', "wouldn't", 'y', 'you',"you'd", "you'll", "you're", "you've", 'your', 'yours', 'yourself', 'yourselves'}

# ------------------------------------------------------------------------------------------------------------------------------
# Wikidata's XML namespace
# ------------------------------------------------------------------------------------------------------------------------------
NS = "http://www.mediawiki.org/xml/export-0.11/"

WIKIDATA_SANDBOXES = ['Q4115189', 'Q13406268', 'Q15397819', 'Q112795079', 'Q16943273', 'Q17339402']

# ------------------------------------------------------------------------------------------------------------------------------
# Wikidata's datatypes
# ------------------------------------------------------------------------------------------------------------------------------
WD_STRING_TYPES = ['string', 'external-id', 'url', 'commonsMedia', 'geo-shape', 'tabular-data', 'math', 'musical-notation']
WD_ENTITY_TYPES = ['wikibase-item', 'wikibase-entityid', 'wikibase-property', 'wikibase-lexeme', 'wikibase-sense', 'wikibase-form', 'entity-schema']

ALL_DATATYPES = WD_STRING_TYPES + WD_ENTITY_TYPES + ['monolingualtext', 'globecoordinate', 'quantity', 'time', 'bad', 'unknown-values']

# ------------------------------------------------------------------------------------------------------------------------------
# TABLE COLUMNS
# ------------------------------------------------------------------------------------------------------------------------------
REVISION_COLS = ['prev_revision_id', 'revision_id', 'entity_id', 'timestamp', 'user_id', 
                 'username', 'user_type', 'comment', 'file_id', 'q_id_redirect']
REVISION_PK = ['revision_id']

VALUE_CHANGE_COLS = ['revision_id', 'property_id', 'value_id', 'old_value', 
                     'new_value', 'old_datatype', 'new_datatype', 
                     'action', 'timestamp', 'label', 'branch', 'entity_id', 
                     'is_reverted', 'reversion', 'reversion_timestamp', 'revision_id_reversion']
VALUE_CHANGE_PK = ['revision_id', 'property_id', 'value_id']

RANK_CHANGE_COLS = ['revision_id', 'property_id', 'value_id', 'old_value', 
                     'new_value',  'action', 'timestamp', 'label', 'entity_id', 
                     'is_reverted', 'reversion', 'reversion_timestamp', 'revision_id_reversion']
RANK_CHANGE_PK = ['revision_id', 'property_id', 'value_id']

QUALIFIER_CHANGE_COLS = ['revision_id', 'property_id', 'value_id', 'qual_property_id', 
                         'value_hash', 'old_value', 'new_value', 'old_datatype', 'new_datatype',
                         'action', 'timestamp', 'entity_id', 'label']
QUALIFIER_CHANGE_PK = ['revision_id', 'property_id', 'value_id', 'qual_property_id', 'value_hash']

REFERENCE_CHANGE_COLS = ['revision_id', 'property_id', 'value_id', 'ref_property_id', 'ref_hash', 'value_hash', 
                         'old_value', 'new_value', 'old_datatype', 'new_datatype', 
                         'action', 'timestamp', 'entity_id', 'label']
REFERENCE_CHANGE_PK = ['revision_id', 'property_id', 'value_id', 'ref_property_id', 'value_hash', 'ref_hash']

DATATYPE_METADATA_CHANGE_COLS = ['revision_id', 'property_id', 'value_id', 'old_value', 'new_value', 'old_datatype', 
                                 'new_datatype', 'change_target', 'action', 
                                 'timestamp', 'entity_id']
DATATYPE_METADATA_CHANGE_PK = ['revision_id', 'property_id', 'value_id', 'change_target']

# ------------------------------------------------------------------------------------------------------------------------------
# FEATURE COLUMNS
# ------------------------------------------------------------------------------------------------------------------------------

ENTITY_UPDATES_PK = [
    'revision_id',
    'property_id',
    'value_id',
]

TEXT_UPDATES_PK = [
    'revision_id',
    'property_id',
    'value_id',
]

ENTITY_UPDATES_COLS = [
    'revision_id',
    'property_id',
    'value_id',
    'old_value',
    'new_value',
    'old_value_label',
    'new_value_label',
    'old_value_description',
    'new_value_description'
]

TEXT_UPDATES_COLS = [
    'revision_id',
    'property_id',
    'value_id',
    'old_value',
    'new_value'
]

# ------------------------------------------------------------------------------------------------------------------------------
# STATS COLUMNS
# ------------------------------------------------------------------------------------------------------------------------------
ENTITY_STATS_COLS = [
    'entity_id',
    'qid',
    'entity_label',
    'entity_description',
    'entity_types_31',
    'entity_types_279',
    
    'num_revisions',
    
    'num_value_changes', # this includes all changes to property values (creates, deletes, updates)  !! not rank 
    'num_value_change_creates',
    'num_value_change_deletes',
    'num_value_change_updates',

    'num_rank_changes',
    'num_rank_creates',
    'num_rank_deletes',
    'num_rank_updates',

    'num_qualifier_changes',
    'num_reference_changes',

    'num_datatype_metadata_changes',
    'num_datatype_metadata_creates',
    'num_datatype_metadata_deletes',
    'num_datatype_metadata_updates',
    
    'first_revision_timestamp', 
    'last_revision_timestamp',
    
    'num_bot_edits', 
    'num_anonymous_edits',
    'num_human_edits',
    
    'num_reverted_edits',
    'num_reversions',
    'num_reverted_edits_create',
    'num_reverted_edits_delete',
    'num_reverted_edits_update',

    'file_id',

    'total_xml_parse_time_sec',
    'total_process_time_sec',

    'total_revision_diff_time_sec',
    'num_revisions_timed',
    'total_rev_edit_time_sec',

    'total_feature_creation_sec',
    'num_feature_creations_timed',

    'total_rule_based_classification_sec'
]

ENTITY_STATS_PK = ['entity_id']
