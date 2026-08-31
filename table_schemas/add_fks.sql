ALTER TABLE value_change{suffix}
    ADD CONSTRAINT value_change{suffix}_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES revision{suffix}(revision_id) NOT VALID;
ALTER TABLE value_change{suffix} VALIDATE CONSTRAINT value_change{suffix}_revision_id_fkey;

ALTER TABLE rank_change{suffix}
    ADD CONSTRAINT rank_change{suffix}_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES revision{suffix}(revision_id) NOT VALID;
ALTER TABLE rank_change{suffix} VALIDATE CONSTRAINT rank_change{suffix}_revision_id_fkey;

ALTER TABLE qualifier_change{suffix}
    ADD CONSTRAINT qualifier_change{suffix}_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES revision{suffix}(revision_id) NOT VALID;
ALTER TABLE qualifier_change{suffix} VALIDATE CONSTRAINT qualifier_change{suffix}_revision_id_fkey;

ALTER TABLE reference_change{suffix}
    ADD CONSTRAINT reference_change{suffix}_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES revision{suffix}(revision_id) NOT VALID;
ALTER TABLE reference_change{suffix} VALIDATE CONSTRAINT reference_change{suffix}_revision_id_fkey;