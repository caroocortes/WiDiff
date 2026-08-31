CREATE TABLE IF NOT EXISTS datatype_metadata_change{suffix} (
    revision_id BIGINT,
    property_id INT,
    value_id TEXT,
    old_value JSONB,  -- change of the datatype metadata (e.g. oldvalue of upperBound for quantity)
    new_value JSONB, -- change of the datatype metadata (e.g. newvalue of upperBound for quantity)
    old_datatype datatype_enum,
    new_datatype datatype_enum,
    change_target TEXT, --name of datatype metadata (e.g. 'upperBound' for quantity)
    action action_enum,
    target TEXT,
    timestamp TIMESTAMP WITH TIME ZONE,
    label TEXT,
    entity_id INT,
    PRIMARY KEY (revision_id, property_id, value_id, change_target),
    FOREIGN KEY (revision_id) REFERENCES revision{suffix}(revision_id)
);