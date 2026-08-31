--- #####################################################
--      Base schemas
--- #####################################################
CREATE TABLE IF NOT EXISTS revision{suffix} (
    prev_revision_id BIGINT,
    revision_id BIGINT,
    entity_id INT,
    timestamp TIMESTAMP WITH TIME ZONE,
    user_id TEXT,
    username TEXT,
    user_type TEXT,
    comment TEXT,
    file_id INT,
    q_id_redirect TEXT,
    PRIMARY KEY (revision_id)
);

CREATE TABLE IF NOT EXISTS value_change{suffix} (
    revision_id BIGINT,
    property_id INT,
    value_id TEXT,
    old_value JSONB,
    new_value JSONB,
    old_datatype datatype_enum,
    new_datatype datatype_enum,
    action action_enum,
    timestamp TIMESTAMP WITH TIME ZONE,
    label TEXT,
    branch TEXT,
    entity_id INT,
    is_reverted INT,
    reversion INT,
    reversion_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    revision_id_reversion BIGINT DEFAULT NULL,
    PRIMARY KEY (revision_id, property_id, value_id)
);

CREATE TABLE IF NOT EXISTS rank_change{suffix} (
    revision_id BIGINT,
    property_id INT,
    value_id TEXT,
    old_value JSONB,
    new_value JSONB,
    action action_enum,
    timestamp TIMESTAMP WITH TIME ZONE,
    label TEXT,
    entity_id INT,
    is_reverted INT,
    reversion INT,
    reversion_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    revision_id_reversion BIGINT DEFAULT NULL,
    PRIMARY KEY (revision_id, property_id, value_id)
);

CREATE TABLE IF NOT EXISTS qualifier_change{suffix} (
    revision_id BIGINT,
    property_id INT, -- statement property id
    value_id TEXT, -- statement value id
    qual_property_id INT, -- qualifier property id
    value_hash TEXT, -- hash of qualifier value. This hash + qual_property_id identify each qualifier value
    old_value JSONB,
    new_value JSONB,
    old_datatype datatype_enum,
    new_datatype datatype_enum,
    action action_enum, -- Will only be CREATE/DELETE, never UPDATE
    timestamp TIMESTAMP WITH TIME ZONE,
    label TEXT,
    entity_id INT,
    PRIMARY KEY (revision_id, property_id, value_id, qual_property_id, value_hash)
    -- NOTE: revision_id, property_id, value_id does not necessarily exist in value_change since a revision could involve only reference/qualifier changes
);

CREATE TABLE IF NOT EXISTS reference_change{suffix} (
    revision_id BIGINT,
    property_id INT, -- statement property id
    value_id TEXT, -- statement value id
    ref_property_id INT, -- reference property id
    ref_hash TEXT, -- identifies the reference (a reference is composed of multiple property - values)
    value_hash TEXT, -- hash of reference value. This hash + ref_property_id identify each reference value
    old_value JSONB,
    new_value JSONB,
    old_datatype datatype_enum,
    new_datatype datatype_enum,
    action action_enum, -- Will only be CREATE/DELETE, never UPDATE
    timestamp TIMESTAMP WITH TIME ZONE,
    label TEXT,
    entity_id INT,
    PRIMARY KEY (revision_id, property_id, value_id, ref_hash, ref_property_id, value_hash)
    -- NOTE: revision_id, property_id, value_id does not necessarily exist in value_change since a revision could involve only reference/qualifier changes
);


--- #####################################################
--      ENTITY STATS TABLES
--- #####################################################
CREATE TABLE IF NOT EXISTS entity_stats{suffix} (
    entity_id INT PRIMARY KEY,
    qid TEXT,
    entity_label TEXT,
    entity_description TEXT,
    entity_types_31 TEXT,
    entity_types_279 TEXT,
    
    num_revisions INT,
    
    num_value_changes INT, -- this includes all changes to property values (creates, deletes, updates) 
    num_value_change_creates INT,
    num_value_change_deletes INT,
    num_value_change_updates INT,

    num_rank_changes INT,
    num_rank_creates INT,
    num_rank_deletes INT,
    num_rank_updates INT,

    num_qualifier_changes INT,
    num_reference_changes INT,

    num_datatype_metadata_changes INT,
    num_datatype_metadata_creates INT,
    num_datatype_metadata_deletes INT,
    num_datatype_metadata_updates INT,
    
    first_revision_timestamp TIMESTAMP WITH TIME ZONE, 
    last_revision_timestamp TIMESTAMP WITH TIME ZONE,
    
    num_bot_edits INT, 
    num_anonymous_edits INT,
    num_human_edits INT,

    num_reverted_edits INT,
    num_reversions INT,
    num_reverted_edits_create INT,
    num_reverted_edits_delete INT,
    num_reverted_edits_update INT,

    file_id INT,

    total_xml_parse_time_sec FLOAT,
    total_process_time_sec FLOAT,

    total_revision_diff_time_sec FLOAT,
    num_revisions_timed INT,

    total_rev_edit_time_sec FLOAT,

    total_feature_creation_sec FLOAT,
    num_feature_creations_timed INT,

    total_rule_based_classification_sec FLOAT
);
