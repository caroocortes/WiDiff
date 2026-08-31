--- #####################################################
--      FEATURE TABLES
--- #####################################################

CREATE TABLE IF NOT EXISTS updates_text{suffix} (
    revision_id BIGINT,
    property_id INT,
    value_id TEXT,

    -- For calculating semantic similarity features
    old_value JSONB,
    new_value JSONB,

    PRIMARY KEY (revision_id, property_id, value_id),
    FOREIGN KEY (revision_id, property_id, value_id) REFERENCES value_change{suffix}(revision_id, property_id, value_id)
);

CREATE TABLE IF NOT EXISTS updates_entity{suffix} (
    revision_id BIGINT,
    property_id INT,
    value_id TEXT,
    
    old_value JSONB,
    new_value JSONB,
    old_value_label TEXT,  -- this is the label or the alias if label == ''
    new_value_label TEXT, -- this is the label or the alias if label == ''
    
    old_value_description TEXT,
    new_value_description TEXT,

    PRIMARY KEY (revision_id, property_id, value_id),
    FOREIGN KEY (revision_id, property_id, value_id) REFERENCES value_change{suffix}(revision_id, property_id, value_id)
);
