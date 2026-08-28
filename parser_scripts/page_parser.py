import html
import json
from lxml import etree
import sys
import re
import hashlib
import time
from collections import defaultdict
import gc

from classifiers.rule.rule_based_classifier import RuleBasedClassifier
from parser_scripts.utils import get_time_feature, id_to_int
from parser_scripts.const import *

class PageParser():
    def __init__(
            self, 
            file_id, 
            page_elem_str, 
            set_up, 
            astronomical_object_types, 
            scholarly_article_types
        ):
        
        self.rule_based_classifier = RuleBasedClassifier(set_up=set_up)

        # Change storage + metadata storage
        self.changes = []
        self.rank_changes = []
        self.revision = []
        self.qualifier_changes = []
        self.reference_changes = []

        self.set_up = set_up

        change_extraction_filters = self.set_up.get('change_extraction_filters', {})

        self.extract_datatype_metadata_changes = (
            (change_extraction_filters.get('scholarly_articles_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('scholarly_articles_filter', {}).get('extract', False))  or \
            (change_extraction_filters.get('astronomical_objects_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('astronomical_objects_filter', {}).get('extract', False))  or \
            (change_extraction_filters.get('less_filter', {}).get('datatype_metadata_extraction', False) and change_extraction_filters.get('less_filter', {}).get('extract', False))  or \
            (change_extraction_filters.get('rest', {}).get('datatype_metadata_extraction', False)) )
        
        if self.extract_datatype_metadata_changes:
            self.datatype_metadata_changes = []
        
        if self.set_up.get('re_interpretation', False):
            self.updates_entity = []
            self.updates_text = []

        self.language = self.set_up.get('change_extraction_processing', {}).get('language', 'en')

        self.current_revision_redirect = False

        self._value_hash_cache = {}

        self.revision_meta = {}

        self.entity_data = {
            'label': '',
            'alias': '',
            'description': '',
            'p31_types': set(),
            'p279_types': set()
        }

        self.file_id = file_id # file_id of XML where the page is stored

        self.page_elem = etree.fromstring(page_elem_str) # XML page for the entity

        ######### TIME MEASUREMENT #########
        self.total_feature_creation_sec = 0
        self.num_feature_creations_timed = 0

        self.total_rule_based_classification_sec = 0

        self.ASTRONOMICAL_OBJECT_TYPES = astronomical_object_types
        self.SCHOLARLY_ARTICLE_TYPES = scholarly_article_types

        # FOR REVERTED EDIT TAGGING
        self.changes_by_pv = defaultdict(list)  # (property, value, change_target) -> [changes]

        self.entity_stats = {
            'entity_id': None,
            'entity_label': '',
            'entity_types_31': '',

            'num_revisions': 0,
            
            'num_value_changes': 0, # this includes all changes to property values (creates, deletes, updates) 
            'num_value_change_creates': 0,
            'num_value_change_deletes': 0,
            'num_value_change_updates': 0,

            'num_rank_changes': 0,
            'num_rank_creates': 0,
            'num_rank_deletes': 0,
            'num_rank_updates': 0,

            'num_qualifier_changes': 0,
            'num_reference_changes': 0,

            'num_datatype_metadata_changes': 0,
            'num_datatype_metadata_creates': 0,
            'num_datatype_metadata_deletes': 0,
            'num_datatype_metadata_updates': 0,
            
            'first_revision_timestamp': None,  # For calculating entity age
            'last_revision_timestamp': None,
            
            'num_bot_edits': 0, 
            'num_anonymous_edits': 0,
            'num_human_edits': 0
        }

    def update_entity_stats(self, change_target, action):
        if change_target == '':
            self.entity_stats['num_value_changes'] += 1

            if action == 'CREATE':
                self.entity_stats['num_value_change_creates'] += 1
            
            elif action == 'DELETE':
                self.entity_stats['num_value_change_deletes'] += 1
            
            elif action == 'UPDATE':
                self.entity_stats['num_value_change_updates'] += 1

        if change_target == 'rank':
            self.entity_stats['num_rank_changes'] += 1
            if action == 'CREATE':
                self.entity_stats['num_rank_creates'] += 1
            elif action == 'DELETE':
                self.entity_stats['num_rank_deletes'] += 1
            elif action == 'UPDATE':
                self.entity_stats['num_rank_updates'] += 1

    def _parse_json_revision(self, revision_elem, revision_text):
        # TODO: remove revision_elem from args - only for debugging
        """
            Returns the text of a revision as a json
        """

        try:
            # Most of the revisions are HTML escaped, but some aren't, that's why there's a second try/except
            json_text = html.unescape(revision_text.strip())
            
            # normalize to regular quotes & remove control characters so json parsing doesnt break
            json_text = json_text.replace('“', '"').replace('”', '"').replace('„', '"').replace('‟', '"')
            json_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_text)
        
            current_revision = json.loads(json_text)
            return current_revision
        except json.JSONDecodeError as e:
            pass

        try:
            return json.loads(revision_text.strip())
        except json.JSONDecodeError:

            print(f"Error decoding JSON in revision {self.revision_meta['revision_id']} for entity {self.revision_meta['entity_id']}: {e}. Revision skipped. See {ERROR_REVISION_TEXT_PATH} for details.")
            
            with open(ERROR_REVISION_TEXT_PATH, "a") as f:
                f.write(f"-------------------------------------------\n")
                f.write(f"Revision {self.revision_meta['revision_id']} for entity {self.revision_meta['entity_id']}:\n")
                revision_xml_str = etree.tostring(
                    revision_elem,
                    pretty_print=True,
                    encoding="unicode" 
                )
                f.write(revision_xml_str + "\n")
                f.write(f"-------------------------------------------\n")
            return None

    @staticmethod
    def _get_property_mainsnak(stmt, property_=None):
        """
            Returns the value for a property in the mainsnak
        """
        try:
            return stmt["mainsnak"].get(property_, None)
        except (KeyError, TypeError) as e:
            print(f'Error when retrieving property {property_} in statement {stmt}')
            raise e
        
    @staticmethod
    def _safe_get_nested(d, *keys):
        """
            Safely access nested dictionary keys, avoiding issues with unexpected list types.
            Wikidata sets claims, labels and descriptions to [] if there's no value. If some value exists, they turn to dicts ({})

            Example:
                _safe_get_nested(revision, 'labels', 'en', 'value')

            Will return {} if any part of the path is invalid or not a dict.
        """
        default = {}
        current = d
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, default)
            else:
                return default

        if isinstance(current, list):
            return default
        else:
            return current
    
    def get_label_alias_description(self, revision):
        label = PageParser._safe_get_nested(revision, 'labels', self.language, 'value') 

        description = PageParser._safe_get_nested(revision, 'descriptions', self.language, 'value')
        
        if isinstance(revision.get('aliases', None), dict): # there can be multiple aliases for a single language
            aliases_list = revision['aliases'].get(self.language, [])
            alias = aliases_list[0]['value'] if len(aliases_list) > 0 else ''
        else:
            alias = ''

        return label if not isinstance(label, dict) else '', alias, description if not isinstance(description, dict) else ''
    
    @staticmethod
    def parse_datavalue_json(value_json, datatype):

        value = None
        datatype_metadata = {}
        if isinstance(value_json, dict):
            # complex datatypes - time, quantity, globecoordinate, monolingualtext
            # we consider entity as a simple type
            if datatype == 'globecoordinate':
                value = {
                    "longitude": value_json['longitude'],
                    "latitude": value_json['latitude']
                }
            if datatype != 'wikibase-entityid':
                for k, v in value_json.items():
                    # time, amount, text, latitude, longitude hold the actual value of time, quantity, 
                    # monolingualtext and globecoordinate datatypes, the rest is metadata
                    if k not in ("time", "amount", "text", "latitude", "longitude", "altitude", "before", "after", "timezone"): # altitude (DEPRECATED), before, after and timezone (UNUSED)
                        datatype_metadata[k] = v
                    else:
                        if datatype != 'globecoordinate' and k not in ("altitude", "before", "after", "timezone"):
                            value = v
            else:
                if 'id' in value_json:
                    value = value_json.get('id')
                else: # not all entities have numeric-id or id
                    value = 'Q' + str(value_json.get('numeric-id'))
        else:
            value = value_json

        return value, datatype, datatype_metadata

    @staticmethod
    def _parse_datavalue(statement):
        """
            Returns the value, datatype and datatype_metadata of a statement, from the datavalue field
            If datatype == 'globecoordinate', then value is a json with latitude and longitude
        """
        if not statement:
            return None, None, None

        snaktype = PageParser._get_property_mainsnak(statement, 'snaktype')

        if snaktype == 'value':

            datavalue = PageParser._get_property_mainsnak(statement, 'datavalue')
            
            value_json = datavalue.get("value", None)
            datatype = datavalue.get("type", None)

            return PageParser.parse_datavalue_json(value_json, datatype)

        else:
            value = NO_VALUE if snaktype == 'novalue' else SOME_VALUE
            return value, 'unknown-values', None

    @staticmethod
    def _description_label_change_type(old_value, new_value):
        """
            Returns the change type for labels and descriptions (only have one value) 
        """
 
        if not old_value and new_value:
            return CREATE_PROPERTY_VALUE
        elif old_value and not new_value:
            return DELETE_PROPERTY_VALUE
        elif old_value and new_value and old_value != new_value:
            return UPDATE_PROPERTY_VALUE

    
    def save_changes_for_remaining_classification(self, revision_id, property_id, value_id, old_value, new_value, new_datatype):
        
        base_cols = (
            revision_id,
            property_id,
            value_id,
            old_value,
            new_value,
        )
        
        if new_datatype in WD_STRING_TYPES:
            self.updates_text.append(
                base_cols
            )

        if new_datatype in WD_ENTITY_TYPES:
            self.updates_entity.append(
                base_cols + ('', '', '', '',)
            )


    @staticmethod
    def serialize_value(value):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)


    def save_changes(self, property_id, value_id, old_value, new_value, old_datatype, new_datatype, change_target, change_type):
        """
            Store value + datatype metadata (of property value) + rank changes
        """
        old_value = PageParser.serialize_value(old_value) if old_value is not None else '{}' # in the DB can't be NULL because null = null is NULL in postgresql
        new_value = PageParser.serialize_value(new_value) if new_value is not None else '{}'

        action = change_type

        timestamp = self.revision_meta['timestamp']
        entity_id = self.revision_meta['entity_id']
        revision_id = self.revision_meta['revision_id']

        change_target = change_target if change_target else ''
        
        label = ''
        branch = ''

        st = time.perf_counter()
        # Property value tagging
        if self.set_up.get('re_interpretation', False) and change_target == '':
            
            # NOTE: the datatypes could be different but it could be a CREATE or DELETE
            if new_datatype != old_datatype and action == 'UPDATE': 
                label = 'property_value_update'

            # If it's between somevalue / novale it's a property value update by default
            if new_datatype == old_datatype and action == 'UPDATE' and new_datatype == 'unknown-values':
                label = 'property_value_update'

            if action == 'CREATE':
                label = 'statement_insertion'

            if action == 'DELETE':
                label = 'statement_deletion'

        # Soft insertion + deletion 
        if self.set_up.get('re_interpretation', False) and change_target == 'rank' and action == 'UPDATE':
            old_value_filt = old_value.replace('"', '') if old_value else ''
            new_value_filt = new_value.replace('"', '') if new_value else ''

            
            if old_value_filt in ['normal', 'preferred'] and new_value_filt == 'deprecated':
                label = 'soft_deletion'

            if new_value_filt == 'preferred' and old_value_filt in ['deprecated','normal']:
                label = 'soft_insertion'

        self.total_rule_based_classification_sec += (time.perf_counter() - st)

        self.update_entity_stats(change_target, action)

        # stores all changes (rank and value for reverted edits)
        self.changes_by_pv[(property_id, value_id, change_target)].append({
            'timestamp': timestamp,
            'old_value': old_value,
            'new_value': new_value,
            'comment': self.revision_meta['comment'],
            'change_target': change_target,
            'revision_id': revision_id,
            'action': action
        })

        if (self.set_up.get('re_interpretation', False)) and change_target == '' and action == 'UPDATE' and new_datatype == old_datatype:

            if new_datatype == 'globecoordinate':  
                st = time.perf_counter()
                label_lat, branch_lat, label_long, branch_long = self.rule_based_classifier.classify_globecoordinate_changes(old_value, new_value)
                et = time.perf_counter()
                self.total_rule_based_classification_sec += (et - st)

                label = ''
                branch = ''
                if label_lat != '':
                    label += label_lat
                    branch += branch_lat
                if label_long != '':
                    if label != '':
                        label += ','
                        branch += ','
                    label += label_long
                    branch += branch_long

            if new_datatype == 'time':
                st = time.perf_counter()
                label, branch = self.rule_based_classifier.classify_time_changes(old_value, new_value)
                et = time.perf_counter()
                self.total_rule_based_classification_sec += (et - st)

            if new_datatype == 'quantity':
                st = time.perf_counter()
                label, branch = self.rule_based_classifier.classify_quantity_changes(old_value, new_value)
                et = time.perf_counter()
                self.total_rule_based_classification_sec += (et - st)

            if new_datatype in WD_STRING_TYPES:
                st = time.perf_counter()
                label = self.rule_based_classifier.classify_text_changes(old_value, new_value)
                et = time.perf_counter()
                self.total_rule_based_classification_sec += (et - st)

                if label == '':
                    self.save_changes_for_remaining_classification(
                        revision_id,
                        property_id,
                        value_id,
                        old_value,
                        new_value,
                        new_datatype
                    )

            if new_datatype in WD_ENTITY_TYPES:

                self.save_changes_for_remaining_classification(
                    revision_id,
                    property_id,
                    value_id,
                    old_value,
                    new_value,
                    new_datatype
                )
            
        change = (
            revision_id, # 0
            property_id, # 1
            value_id, # 2
            old_value, # 3
            new_value, # 4
            old_datatype, # 5
            new_datatype, # 6
            change_target, # 7
            action, # 8
            timestamp, # 9
            label, # 10
            branch, # 11
            entity_id # 12
        )
        
        self.changes.append(change)

    
    def save_datatype_metadata_changes(self, property_id, value_id, old_value, new_value, old_datatype, new_datatype, change_target, change_type):
        """
            Store value + datatype metadata (of property value) + rank changes
        """
        old_value = PageParser.serialize_value(old_value) if old_value is not None else '{}' # in the DB can't be NULL because null = null is NULL in postgresql
        new_value = PageParser.serialize_value(new_value) if new_value is not None else '{}'

        action = change_type
        timestamp = self.revision_meta['timestamp']

        label = ''
        if self.set_up.get('re_interpretation', False) and action == 'UPDATE':
            label = 'datatype_context_update'

        change = (
            self.revision_meta['revision_id'],
            property_id,
            value_id,
            old_value,
            new_value,
            old_datatype,
            new_datatype,
            change_target if change_target else '', # can't be None since change_target is part of the key of the table
            action,
            timestamp,
            self.revision_meta['entity_id'],
            label
        )

        self.datatype_metadata_changes.append(change)
        
        if action == 'CREATE':
            self.entity_stats['num_datatype_metadata_creates'] += 1
        if action == 'DELETE':
            self.entity_stats['num_datatype_metadata_deletes'] += 1
        elif action == 'UPDATE':
            self.entity_stats['num_datatype_metadata_updates'] += 1

        self.entity_stats['num_datatype_metadata_changes'] += 1
    
    
    def save_qualifier_changes(self, property_id, value_id, qual_property_id, value_hash, old_value, new_value, old_datatype, new_datatype, change_type):
        """
            Store reference/qualifier changes
        """
        old_value = PageParser.serialize_value(old_value) if old_value is not None else '{}'
        new_value = PageParser.serialize_value(new_value) if new_value is not None else '{}'

        action = change_type
        timestamp = self.revision_meta['timestamp']
        
        label = ''
        # -- qualifiers adding end time
        # -- P582 = end time
        # -- P8554 = earliest end date - earliest date on which the statement could have begun to no longer be true
        # -- P12506 = latest end date - latest date beyond which the statement could no longer be true
        # -- end period (P3416)
        
        if self.set_up.get('re_interpretation', False) and action == 'CREATE':
            if qual_property_id in [582, 8554, 12506, 3416]:
                label = 'soft_deletion'
        
        change = (
            self.revision_meta['revision_id'],
            property_id,
            value_id,
            qual_property_id,
            value_hash,
            old_value,
            new_value,
            old_datatype,
            new_datatype,
            action,
            timestamp,
            self.revision_meta['entity_id'],
            label
        )

        self.qualifier_changes.append(change)


    def save_reference_changes(self, property_id, value_id, ref_property_id, ref_hash, value_hash, old_value, new_value, old_datatype, new_datatype, change_type):
        """
            Store reference changes
        """
        old_value = PageParser.serialize_value(old_value) if old_value is not None else '{}'
        new_value = PageParser.serialize_value(new_value) if new_value is not None else '{}'

        action = change_type
        timestamp = self.revision_meta['timestamp']
        label = ''
        change = (
            self.revision_meta['revision_id'],
            property_id,
            value_id,
            ref_property_id,
            ref_hash,
            value_hash,
            old_value,
            new_value,
            old_datatype,
            new_datatype,
            action,
            timestamp,
            self.revision_meta['entity_id'],
            label
        )

        self.reference_changes.append(change)


    def _handle_datatype_metadata_changes(self, old_datatype_metadata, new_datatype_metadata, value_id, old_datatype, new_datatype, property_id, change_type, type_='value'):

        if old_datatype_metadata and not new_datatype_metadata: # deletion
            for key in old_datatype_metadata.keys():
                old_meta = old_datatype_metadata.get(key, None)

                if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                    old_meta = old_meta.split('/')[-1]
                
                if type_ == 'value':

                    self.save_datatype_metadata_changes(
                        id_to_int(property_id),
                        value_id=value_id,
                        old_value=old_meta,
                        new_value=None,
                        old_datatype=old_datatype,
                        new_datatype=new_datatype,
                        change_target=key,
                        change_type=change_type
                    )
            return
        
        if new_datatype_metadata and not old_datatype_metadata: # creation
            for key in new_datatype_metadata.keys():
                new_meta = new_datatype_metadata.get(key, None)

                if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                    new_meta = new_meta.split('/')[-1]
                
                if type_ == 'value':
                    
                    self.save_datatype_metadata_changes(
                        id_to_int(property_id),
                        value_id=value_id,
                        old_value=None,
                        new_value=new_meta,
                        new_datatype=new_datatype,
                        old_datatype=old_datatype,
                        change_target=key,
                        change_type=change_type
                    )
            return

        if old_datatype == new_datatype:
        
            for key in set((old_datatype_metadata or {}).keys()):
                old_meta = (old_datatype_metadata or {}).get(key, None)
                new_meta = (new_datatype_metadata or {}).get(key, None)

                if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                    new_meta = new_meta.split('/')[-1]

                if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                    old_meta = old_meta.split('/')[-1]

                if old_meta != new_meta: # save only what changed
                    
                    if type_ == 'value':
                        self.save_datatype_metadata_changes(
                            id_to_int(property_id),
                            value_id=value_id,
                            old_value=old_meta,
                            new_value=new_meta,
                            old_datatype=old_datatype,
                            new_datatype=new_datatype,
                            change_target=key,
                            change_type=change_type
                        )

        else: # different datatypes

            old_keys_set = set((old_datatype_metadata or {}).keys())
            new_keys_set = set((new_datatype_metadata or {}).keys())

            if len(old_keys_set) > len(new_keys_set):
                big_set = old_keys_set
                small_set = new_keys_set
                big_old = True
            else:
                big_set = new_keys_set
                small_set = old_keys_set
                big_old = False

            keys_to_skip = set()
            for key in small_set:

                if big_old:
                    
                    new_meta = (new_datatype_metadata or {}).get(key, None)
                    if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                        new_meta = new_meta.split('/')[-1]
                    
                    old_meta_key = next((k for k in old_keys_set if k not in keys_to_skip), None)
                    old_meta = (old_datatype_metadata or {}).get(old_meta_key, None)

                    if old_meta_key == 'calendarmodel' or old_meta_key == 'unit': # keep only the Q-id
                        old_meta = old_meta.split('/')[-1]

                    if old_meta_key is not None:
                        keys_to_skip.add(old_meta_key)
                else:
                    old_meta = (old_datatype_metadata or {}).get(key, None)
                    if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                        old_meta = old_meta.split('/')[-1]

                    new_meta_key = next((k for k in new_keys_set if k not in keys_to_skip), None)
                    new_meta = (new_datatype_metadata or {}).get(new_meta_key, None)

                    if new_meta_key == 'calendarmodel' or new_meta_key == 'unit': # keep only the Q-id
                        new_meta = new_meta.split('/')[-1]

                    if new_meta_key is not None:
                        keys_to_skip.add(new_meta_key)
                
                if type_ == 'value':
                    
                    self.save_datatype_metadata_changes(
                        id_to_int(property_id),
                        value_id=value_id,
                        old_value=old_meta,
                        new_value=new_meta,
                        old_datatype=old_datatype,
                        new_datatype=new_datatype,
                        change_target=key,
                        change_type=change_type
                    )
            
            remaining_keys = big_set - keys_to_skip
            for key in remaining_keys:
                
                if big_old:
                    old_meta = (old_datatype_metadata or {}).get(key, None)
                    if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                        old_meta = old_meta.split('/')[-1]

                    new_meta = None
                else:
                    new_meta = (new_datatype_metadata or {}).get(key, None)
                    if key == 'calendarmodel' or key == 'unit': # keep only the Q-id
                        new_meta = new_meta.split('/')[-1]
                        
                    old_meta = None
                
                if type_ == 'value':
                    self.save_datatype_metadata_changes(
                        id_to_int(property_id),
                        value_id=value_id,
                        old_value=old_meta,
                        new_value=new_meta,
                        old_datatype=old_datatype,
                        new_datatype=new_datatype,
                        change_target=key,
                        change_type=change_type
                    )
    
    
    def _handle_value_changes(self, old_datatype, new_datatype, new_value, old_value, value_id, property_id, change_type):

        self.save_changes(
            id_to_int(property_id), 
            value_id=value_id,
            old_value=old_value,
            new_value=new_value,
            old_datatype=old_datatype,
            new_datatype=new_datatype,
            change_target=None,
            change_type=change_type
        )

    @staticmethod
    def homogenize_datavalue(prop_val):

        if 'datavalue' not in prop_val: # fallback for somevalue, novalue
            return prop_val
        
        type_ = prop_val['datavalue']['type']

        # Remove inconsistencies in time values + entities + unused/deprcated fields in time and globecoordinate
        if type_ == 'globecoordinate':
            prop_val['datavalue']['value'].pop("altitude", None)

        if type_ == 'time':
            # remove unused values
            prop_val['datavalue']['value'].pop("before", None)
            prop_val['datavalue']['value'].pop("after", None)
            
            # remove 0's at the beggining
            prop_val['datavalue']['value']['time'] = re.sub(r'^([+-])0*(\d+)', r'\1\2', prop_val['datavalue']['value']['time'])

        if type_ in WD_ENTITY_TYPES:
            # NOTE: From WD's doc, not all entities have a numeric-id
            # however, I've found revisions where the id is not present but the numeric-id is
            # therefore, I normalize and keep only 'id' or generate it from numeric-id
            if not 'id' in prop_val['datavalue']['value']:
                prop_val['datavalue']['value']['id'] = f"Q{prop_val['datavalue']['value']['numeric-id']}"
            
            # remove numeric-id, only keep id
            prop_val['datavalue']['value'].pop("numeric-id", None)

        return prop_val

    @staticmethod
    def _freeze(value):
        if isinstance(value, dict):
            return tuple(sorted(value.items()))
        return value

    def generate_value_hash(self, hom_prop_val):
        if not hom_prop_val:
            return None

        snaktype = hom_prop_val.get('snaktype', None)
        if snaktype in (NO_VALUE, SOME_VALUE):
            """
                For somevalue/novalue the hash can also change:
                {
                    "P560": [
                        {
                        "snaktype": "somevalue",
                        "property": "P560",
                        "hash": "9ecbc7f05cd7804fbce7afedbf6ab6e0daa55df0" <---------- The hash is different, but the value is the same
                        }
                    ]
                    }
                {
                    "P560": [
                        {
                        "snaktype": "somevalue",
                        "property": "P560", 
                        "hash": "e9e7cf1acd494c7e815004015b851bebc2643f09" <---------- The hash is different, but the value is the same
                        }
                    ]
                }
            """
            property_ = hom_prop_val.get('property')
            cache_key = (snaktype, property_)
            cached = self._value_hash_cache.get(cache_key)
            if cached is not None:
                return cached
            result = hashlib.sha1(f"{snaktype}:{property_}".encode('utf-8')).hexdigest()
            self._value_hash_cache[cache_key] = result
            return result

        cache_key = (hom_prop_val['datavalue']['type'], PageParser._freeze(hom_prop_val['datavalue']['value']))
        cached = self._value_hash_cache.get(cache_key)
        if cached is not None:
            return cached

        result = hashlib.sha1(
            json.dumps(hom_prop_val['datavalue'], separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        self._value_hash_cache[cache_key] = result
        return result
    
    @staticmethod
    def _snak_signature(prop_val):
        """ Signature to avoid dict of hashes for qual/ref changes"""
        snaktype = prop_val.get('snaktype')
        if snaktype in (NO_VALUE, SOME_VALUE):
            return (snaktype,prop_val.get('property'))
        hom = PageParser.homogenize_datavalue(prop_val)
        dv = hom.get('datavalue')
        return (snaktype, dv.get('type'), PageParser._freeze(dv.get('value')))

    def _handle_reference_changes(self, stmt_pid, stmt_value_id, prev_stmt, curr_stmt):
        """
        Handles addition/deletion of references by comparing snak value hashes.
        Deduplicates snaks within references and avoids unnecessary CREATE/DELETE.

        Structure of reference:
        "references": [
            {
                "hash": "fa278ebfc458360e5aed63d5058cca83c46134f1",
                "snaks": {
                    "P143": [
                        {
                            "snaktype": "value",
                            "property": "P143",
                            "hash": "e4f6d9441d0600513c4533c672b5ab472dc73694",
                            "datavalue": {
                                "value": {
                                    "entity-type": "item",
                                    "numeric-id": 328,
                                    "id": "Q328"
                                },
                                "type": "wikibase-entityid"
                            }
                        }
                    ]
                },
                "snaks-order": [
                    "P143"
                ]
            }
        ]
        """

        def refs_signature(refs):
            sig = []
            for ref in refs:
                snaks = ref.get('snaks')
                if not isinstance(snaks, dict):
                    continue
                ref_snaks = []
                for pid, vals in snaks.items():
                    for prop_val in vals:
                        ref_snaks.append((pid, PageParser._snak_signature(prop_val)))
                sig.append(frozenset(ref_snaks))  # one signature per reference - preserves grouping
            return frozenset(sig)  # order of references shouldn't matter, so outer frozenset too

        change_detected = False

        prev_refs = prev_stmt.get('references', []) if prev_stmt else []
        curr_refs = curr_stmt.get('references', []) if curr_stmt else []

        # there's no references in old/new -> no need to process
        if not prev_refs and not curr_refs:
            return False
        
        if refs_signature(prev_refs) == refs_signature(curr_refs):
            return False

        # map of (pid, hash): value 
        def build_hash_map(refs):
            hash_map = {}
            for ref in refs:
                # Create a stable "content hash" for the whole reference
                ref_snaks = []
                if isinstance(ref['snaks'], dict):

                    for pid, vals in ref['snaks'].items():
                        for prop_val in vals:
                            hom_prop_val = PageParser.homogenize_datavalue(prop_val)
                            value_hash = self.generate_value_hash(hom_prop_val)
                            ref_snaks.append((pid, value_hash))
                else: 
                    continue
                
                # Sort and hash to get a stable reference-level id
                ref_content_hash = hashlib.sha1(
                    json.dumps(sorted(ref_snaks)).encode("utf-8")
                ).hexdigest()

                # Now map each snak individually
                if isinstance(ref['snaks'], dict):
                    for pid, vals in ref['snaks'].items():
                        for prop_val in vals:
                            hom_prop_val = PageParser.homogenize_datavalue(prop_val)
                            value_hash = self.generate_value_hash(hom_prop_val)
                            hom_prop_val['hash'] = value_hash
                            hash_map[(ref_content_hash, pid, value_hash)] = hom_prop_val
                else: 
                    continue
                        
            return hash_map

        prev_hash_map = build_hash_map(prev_refs)
        curr_hash_map = build_hash_map(curr_refs)

        prev_keys = set(prev_hash_map.keys())
        curr_keys = set(curr_hash_map.keys())

        # Have to compare at the low-level hash (value hash)
        # because the high-level hash can change between revisions, but some of the inner values 
        # remains the same, just because at least one changed
        deleted = prev_keys - curr_keys
        created = curr_keys - prev_keys    

        # deletions
        for ref_hash, pid, value_hash in deleted:

            change_detected = True
            prop_value = prev_hash_map[(ref_hash, pid, value_hash)]

            if prop_value['snaktype'] in (NO_VALUE, SOME_VALUE):
                prev_val, prev_dtype, old_datatype_metadata = (prop_value['snaktype'], 'string', None)
            else:
                dv = prop_value['datavalue']
                prev_val, prev_dtype, old_datatype_metadata = PageParser.parse_datavalue_json(dv['value'], dv['type'])

            self.save_reference_changes(
                property_id=id_to_int(stmt_pid),
                value_id=stmt_value_id,
                ref_property_id=id_to_int(pid),
                ref_hash=ref_hash,
                value_hash=value_hash,
                old_value=prev_val,
                new_value=None,
                old_datatype=prev_dtype,
                new_datatype=None,
                change_type=DELETE_REFERENCE_VALUE
            )

        # creations
        for ref_hash, pid, value_hash in created:

            change_detected = True
            prop_value = curr_hash_map[(ref_hash, pid, value_hash)]

            if prop_value['snaktype'] in (NO_VALUE, SOME_VALUE):
                curr_val, curr_dtype, new_datatype_metadata = (prop_value['snaktype'], 'string', None)
            else:
                dv = prop_value['datavalue']
                curr_val, curr_dtype, new_datatype_metadata = PageParser.parse_datavalue_json(dv['value'], dv['type'])

            self.save_reference_changes(
                property_id=id_to_int(stmt_pid),
                value_id=stmt_value_id,
                ref_property_id=id_to_int(pid),
                ref_hash=ref_hash,
                value_hash=value_hash,
                old_value=None,
                new_value=curr_val,
                old_datatype=None,
                new_datatype=curr_dtype,
                change_type=CREATE_REFERENCE_VALUE
            )
        
        sys.stdout.flush()

        return change_detected

    def _handle_qualifier_changes(self, stmt_pid, stmt_value_id, prev_stmt, curr_stmt):
        """
        Handles addition, deletion of qualifiers values.
        Uses a simple CREATE/DELETE logic based on hashes.

        Structure of qualifiers:
        "qualifiers": {
            "P813": [
                {
                    "snaktype": "value",
                    "property": "P813",
                    "hash": "54358f6e346b19bed53f5b3a57e82a4f562940aa",
                    "datavalue": {
                        "value": {
                            "time": "+2021-12-31T00:00:00Z",
                            "timezone": 0,
                            "before": 0,
                            "after": 0,
                            "precision": 11,
                            "calendarmodel": "http://www.wikidata.org/entity/Q1985727"
                        },
                        "type": "time"
                    }
                }
            ]
        },

        """

        def quals_signature(quals):
            sig = []
            for pid, vals in (quals or {}).items():
                for prop_val in vals:
                    sig.append((pid, PageParser._snak_signature(prop_val)))
            return frozenset(sig)

        change_detected = False

        prev = prev_stmt.get('qualifiers', {}) if prev_stmt else {}
        curr = curr_stmt.get('qualifiers', {}) if curr_stmt else {}

        # if there are no qualifiers, there's no 'qualifiers' in the mainsnak of the statement
        if not prev and not curr:
            return False

        # if the qualifiers are the same, no need to process
        if quals_signature(prev) == quals_signature(curr):
            return False
        
        all_pids = set(prev.keys()).union(curr.keys())

        for pid in all_pids:
            prev_stmts = prev.get(pid, []) # [{ 'snaktype': 'value', 'hash': '...', ...}]
            curr_stmts = curr.get(pid, [])

            # map by hash : stmt
            # we compare hashes because they are created from the actual values, so if the hashes are different, something changed
            
            # Because we are using hashes to identify values, if there are duplicate values we will have duplicate rows inserted
            # deduplicate prev_stmts by hash

            def build_hash_map(pid_values):
                hash_map = {}
                for prop_val in pid_values:
                    prop_val = PageParser.homogenize_datavalue(prop_val)
                    value_hash = self.generate_value_hash(prop_val) 
                    prop_val['hash'] = value_hash # update hash
                    hash_map[value_hash] = prop_val
                return hash_map

            # deduplicate pevstmts by hash
            prev_map = build_hash_map(prev_stmts) # {hash: snak}

            # deduplicate curr_stmts by hash
            curr_map = build_hash_map(curr_stmts)
            
            # hashes are created from the actial values, so if there are different hashes something changed
            prev_hashes = set(prev_map.keys())
            curr_hashes = set(curr_map.keys())

            deleted = prev_hashes - curr_hashes
            added = curr_hashes - prev_hashes

            # --- Deleted values ---
            for h in deleted:
                change_detected = True
                prev_stmt = prev_map[h]

                snaktype = prev_stmt['snaktype']
                if snaktype in (NO_VALUE, SOME_VALUE):
                    prev_val, prev_dtype, old_datatype_metadata = (snaktype, 'string', None)
                else:
                    dv = prev_stmt['datavalue']
                    prev_val, prev_dtype, old_datatype_metadata = PageParser.parse_datavalue_json(dv['value'], dv['type'])
                
                self.save_qualifier_changes(
                    property_id=id_to_int(stmt_pid),
                    value_id=stmt_value_id,
                    qual_property_id=id_to_int(pid),
                    value_hash=h,
                    old_value=prev_val,
                    new_value=None,
                    old_datatype=prev_dtype,
                    new_datatype=None,
                    change_type=DELETE_QUALIFIER_VALUE
                )

            # --- Added values ---
            for h in added:
                change_detected = True
                curr_stmt = curr_map[h]

                snaktype = curr_stmt['snaktype']
                if snaktype in (NO_VALUE, SOME_VALUE):
                    curr_val, curr_dtype, new_datatype_metadata = (snaktype, 'string', None)
                else:
                    dv = curr_stmt['datavalue']
                    curr_val, curr_dtype, new_datatype_metadata = PageParser.parse_datavalue_json(dv['value'], dv['type'])

                self.save_qualifier_changes(
                    property_id=id_to_int(stmt_pid),
                    value_id=stmt_value_id,
                    qual_property_id=id_to_int(pid),
                    value_hash=h,
                    old_value=None,
                    new_value=curr_val,
                    old_datatype=None,
                    new_datatype=curr_dtype,
                    change_type=CREATE_QUALIFIER_VALUE
                )

        return change_detected
            
    def _changes_created_entity(self, revision):

        change_detected = False
        change_detected_qual = False
        change_detected_ref = False
        # Process claims
        claims = PageParser._safe_get_nested(revision, 'claims')
        
        for property_id, property_stmts in claims.items():
            for stmt in property_stmts:
                stmt['mainsnak'] = PageParser.homogenize_datavalue(stmt['mainsnak'])
                value, datatype, datatype_metadata = PageParser._parse_datavalue(stmt)
                value_id = stmt.get('id', None)

                if property_id == 'P31':
                    self.entity_data['p31_types'].add((value_id, value))

                if property_id == 'P279':
                    self.entity_data['p279_types'].add((value_id, value))
                
                old_value = None
                new_value = value

                change_detected = True

                self.save_changes(
                    id_to_int(property_id), 
                    value_id=value_id,
                    old_value=old_value,
                    new_value=new_value,
                    old_datatype=None,
                    new_datatype=datatype,
                    change_target=None,
                    change_type=CREATE_PROPERTY_VALUE
                )

                curr_rank = stmt.get('rank') if stmt else None
                self.save_changes(
                    property_id=id_to_int(property_id),
                    value_id=value_id,
                    old_value=None,
                    new_value=curr_rank,
                    old_datatype=None,
                    new_datatype=datatype,
                    change_target='rank',
                    change_type=CREATE_PROPERTY_VALUE
                )

                if datatype_metadata and self.extract_datatype_metadata_changes:
                    for k, v in datatype_metadata.items():
                        
                        change_detected = True

                        old_value = None
                        new_value = v
                        
                        self.save_datatype_metadata_changes(
                            id_to_int(property_id),
                            value_id=value_id,
                            old_value=old_value,
                            new_value=new_value,
                            old_datatype=None,
                            new_datatype=datatype,
                            change_target=k,
                            change_type=CREATE_PROPERTY_VALUE
                        )

                # qualifier changes
                change_detected_qual = self._handle_qualifier_changes(property_id, value_id, prev_stmt=None, curr_stmt=stmt)

                # references changes
                change_detected_ref = self._handle_reference_changes(property_id, value_id, prev_stmt=None, curr_stmt=stmt)

        # If there's no description or label, the revisions shows them as []
        labels = PageParser._safe_get_nested(revision, 'labels', self.language, 'value')
        descriptions = PageParser._safe_get_nested(revision, 'descriptions', self.language, 'value')

        # Process labels and descriptions (non-claim properties)
        for pid, val in [(LABEL_PROP_ID, labels), (DESCRIPTION_PROP_ID, descriptions)]:
            if val:
                change_detected = True
                old_value = None
                new_value = val

                self.save_changes(
                    pid, 
                    value_id='label' if pid == LABEL_PROP_ID else 'description',
                    old_value=old_value if not isinstance(old_value, dict) else None,
                    new_value=new_value if not isinstance(new_value, dict) else None,
                    old_datatype=None,
                    new_datatype='string',
                    change_target=None,
                    change_type=CREATE_PROPERTY_VALUE
                )
        
        return change_detected or change_detected_qual or change_detected_ref
     
    def _changes_cleaned_entity(self, previous_revision):
        # I pass the previous revision because the current one is empty
        # it was completely cleaned, so i need to know what there was on the entity previously 
        # to save the corresponding deletes
        claims = PageParser._safe_get_nested(previous_revision, 'claims')
        
        for property_id, property_stmts in claims.items():
            for stmt in property_stmts:
                stmt['mainsnak'] = PageParser.homogenize_datavalue(stmt['mainsnak'])
                value, datatype, datatype_metadata = PageParser._parse_datavalue(stmt)
                
                value_id = stmt.get('id', None)

                if property_id == 'P31':
                    self.entity_data['p31_types'].remove((value_id, value))

                if property_id == 'P279':
                    self.entity_data['p279_types'].remove((value_id, value))
                
                old_value = value
                new_value = None
                
                self.save_changes(
                    id_to_int(property_id), 
                    value_id=value_id,
                    old_value=old_value,
                    new_value=new_value,
                    old_datatype=datatype,
                    new_datatype=None,
                    change_target=None,
                    change_type=DELETE_PROPERTY_VALUE
                )

                # rank
                prev_rank = stmt.get('rank') if stmt else None
                self.save_changes(
                    property_id=id_to_int(property_id),
                    value_id=value_id,
                    old_value=prev_rank,
                    new_value=None,
                    old_datatype=datatype,
                    new_datatype=None,
                    change_target='rank',
                    change_type=DELETE_PROPERTY_VALUE
                )

                if datatype_metadata and self.extract_datatype_metadata_changes:
                    for k, v in datatype_metadata.items():
                        old_value = v
                        new_value = None
                        
                        self.save_datatype_metadata_changes(
                            id_to_int(property_id),
                            value_id=value_id,
                            old_value=old_value,
                            new_value=new_value,
                            old_datatype=datatype,
                            new_datatype=None,
                            change_target=k,
                            change_type=DELETE_PROPERTY_VALUE
                        )

                # qualifier changes
                _ = self._handle_qualifier_changes(property_id, value_id, prev_stmt=None, curr_stmt=stmt)

                # references changes
                _ = self._handle_reference_changes(property_id, value_id, prev_stmt=None, curr_stmt=stmt)

        # If there's no description or label, the revisions shows them as []
        labels = PageParser._safe_get_nested(previous_revision, 'labels', self.language, 'value')
        descriptions = PageParser._safe_get_nested(previous_revision, 'descriptions', self.language, 'value')

        # Process labels and descriptions (non-claim properties)
        for pid, val in [(LABEL_PROP_ID, labels), (DESCRIPTION_PROP_ID, descriptions)]:
            if val:
                old_value = val
                new_value = None

                self.save_changes(
                    pid, 
                    value_id='label' if pid == LABEL_PROP_ID else 'description',
                    old_value=old_value if not isinstance(old_value, dict) else None, # _safe_get_nested returns {} instead of None (?why)
                    new_value=new_value if not isinstance(new_value, dict) else None,
                    old_datatype='string',
                    new_datatype=None,
                    change_target=None,
                    change_type=DELETE_PROPERTY_VALUE
                )

    def _handle_description_label_change(self, previous_revision, current_revision):
        """
            Handles changes in labels and descriptions between two revisions.
            Generates new hashes for labels and descriptions when they change.
            Returns True if any change was detected, False otherwise.
        """
        change_detected = False

        # --- Label change ---
        prev_label = None
        if previous_revision:
            prev_label = PageParser._safe_get_nested(previous_revision, 'labels', self.language, 'value')
        curr_label = PageParser._safe_get_nested(current_revision, 'labels', self.language, 'value')
        
        if curr_label != prev_label:
            change_detected = True

            old_value = prev_label if not isinstance(prev_label, dict) else None
            new_value = curr_label if not isinstance(curr_label, dict) else None

            self.save_changes(
                property_id=LABEL_PROP_ID,
                value_id='label',
                old_value=old_value,
                new_value=new_value,
                old_datatype='string' if old_value is not None else None,
                new_datatype='string' if new_value is not None else None,
                change_target=None,
                change_type=PageParser._description_label_change_type(prev_label, curr_label)
            )
            
        # --- Description change ---
        prev_desc = None
        if previous_revision:
            prev_desc = PageParser._safe_get_nested(previous_revision, 'descriptions', self.language, 'value')
        curr_desc = PageParser._safe_get_nested(current_revision, 'descriptions', self.language, 'value')

        if self.revision_meta.get('entity_id') == 25104771 and self.revision_meta.get('revision_id') in [1279154838, 1279154833]:
            print('Current description: ', curr_desc)
            print('Previous description: ', prev_desc)
            print('If check: curr_desc != prev_desc', curr_desc != prev_desc)

        if curr_desc != prev_desc:
            if self.revision_meta.get('entity_id') == 25104771 and self.revision_meta.get('revision_id') in [1279154838, 1279154833]:
                print('Description change detected!')

            change_detected = True
            old_value = prev_desc if not isinstance(prev_desc, dict) else None
            new_value = curr_desc if not isinstance(curr_desc, dict) else None

            self.save_changes(
                property_id=DESCRIPTION_PROP_ID,
                value_id='description',
                old_value=old_value,
                new_value=new_value,
                old_datatype='string' if old_value is not None else None,
                new_datatype='string' if new_value is not None else None,
                change_target=None,
                change_type=PageParser._description_label_change_type(prev_desc, curr_desc)
            )

        return change_detected
    
    def _handle_new_pids(self, new_pids, curr_claims):
        """
            Handles new properties (P-IDs) in the current revision.
        """
        for new_pid in new_pids:
            curr_statements = curr_claims.get(new_pid, [])
            for s in curr_statements:
                s['mainsnak'] = PageParser.homogenize_datavalue(s['mainsnak'])
                new_value, new_datatype, new_datatype_metadata = PageParser._parse_datavalue(s)

                value_id = s.get('id', None)

                # add new type, if it's duplicated it will not be duplicated because we save a set
                if new_pid == 'P31':
                    self.entity_data['p31_types'].add((value_id, new_value))

                if new_pid == 'P279':
                    self.entity_data['p279_types'].add((value_id, new_value))

                self._handle_value_changes(None, new_datatype, new_value, None, value_id, new_pid, CREATE_PROPERTY_VALUE)

                if new_datatype_metadata and self.extract_datatype_metadata_changes:
                    self._handle_datatype_metadata_changes(None, new_datatype_metadata, value_id, None, new_datatype, new_pid, CREATE_PROPERTY_VALUE)

                # rank
                curr_rank = s.get('rank') if s else None
                self.save_changes(
                    property_id=id_to_int(new_pid),
                    value_id=value_id,
                    old_value=None,
                    new_value=curr_rank,
                    old_datatype=None,
                    new_datatype=new_datatype,
                    change_target='rank',
                    change_type=CREATE_PROPERTY_VALUE
                )

                # qualifier changes
                _ = self._handle_qualifier_changes(new_pid, value_id, prev_stmt=None, curr_stmt=s)

                # reference changes
                _ = self._handle_reference_changes(new_pid, value_id, prev_stmt=None, curr_stmt=s)
    
    def _handle_removed_pids(self, removed_pids, prev_claims):
        """
            Handles changes for properties that were removed in the current revision
        """
        for removed_pid in removed_pids:
            prev_statements = prev_claims.get(removed_pid, [])
            
            change_type = DELETE_PROPERTY_VALUE

            for s in prev_statements:
                s['mainsnak'] = PageParser.homogenize_datavalue(s['mainsnak'])
                old_value, old_datatype, old_datatype_metadata = PageParser._parse_datavalue(s)

                value_id = s.get('id', None)

                # add new type, if it's duplicated it will not be duplicated because we save a set
                if removed_pid == 'P31':
                    self.entity_data['p31_types'].remove((value_id, old_value))

                if removed_pid == 'P279':
                    self.entity_data['p279_types'].remove((value_id, old_value))

                self._handle_value_changes(old_datatype, None, None, old_value, value_id, removed_pid, change_type)

                if old_datatype_metadata and self.extract_datatype_metadata_changes:
                    self._handle_datatype_metadata_changes(old_datatype_metadata, {}, value_id, old_datatype, None, removed_pid, change_type)
                
                # rank
                prev_rank = s.get('rank') if s else None
                self.save_changes(
                    property_id=id_to_int(removed_pid),
                    value_id=value_id,
                    old_value=prev_rank,
                    new_value=None,
                    old_datatype=old_datatype,
                    new_datatype=None,
                    change_target='rank',
                    change_type=change_type
                )

                # qualifier changes
                _ = self._handle_qualifier_changes(removed_pid, value_id, prev_stmt=s, curr_stmt=None)

                # references changes
                _ = self._handle_reference_changes(removed_pid, value_id, prev_stmt=s, curr_stmt=None)

    def _handle_rank_changes(self, prev_stmt, curr_stmt, pid, sid, old_datatype, new_datatype):
        prev_rank = prev_stmt.get('rank') if prev_stmt else None
        curr_rank = curr_stmt.get('rank') if curr_stmt else None

        change_detected = False
        if not prev_stmt:
            change_detected = True
            self.save_changes(
                property_id=id_to_int(pid),
                value_id=sid,
                old_value=None,
                new_value=curr_rank,
                old_datatype=old_datatype,
                new_datatype=new_datatype,
                change_target='rank',
                change_type=CREATE_PROPERTY_VALUE
            )
        elif not curr_stmt:
            change_detected = True
            self.save_changes(
                property_id=id_to_int(pid),
                value_id=sid,
                old_value=prev_rank,
                new_value=None,
                old_datatype=old_datatype,
                new_datatype=new_datatype,
                change_target='rank',
                change_type=DELETE_PROPERTY_VALUE
            )
        elif prev_stmt and curr_stmt and prev_rank != curr_rank:
            change_detected = True
            self.save_changes(
                property_id=id_to_int(pid),
                value_id=sid,
                old_value=prev_rank,
                new_value=curr_rank,
                old_datatype=old_datatype,
                new_datatype=new_datatype,
                change_target='rank',
                change_type=UPDATE_RANK
            )
        return change_detected

    def _handle_remaining_pids(self, remaining_pids, prev_claims, curr_claims):
        """
            Handles changes in properties that appear in current and previous revision.
            Returns True if a change was detected, otherwise False.

            Statement structure:
            {
                "claims": {
                    "P17": [
                    {
                        "id": "q60$5083E43C-228B-4E3E-B82A-4CB20A22A3FB",
                        "mainsnak": {},
                        "type": "statement",
                        "rank": "normal",
                        "qualifiers": {
                            "P580": [],
                            "P5436": []
                        },
                        "references": [
                        {
                            "hash": "d103e3541cc531fa54adcaffebde6bef28d87d32",
                            "snaks": []
                        }
                        ]
                    }
                    ]
                }
            }
        """

        change_detected = False

        for pid in remaining_pids:
            # Get statement for the same P-ID in previous and current revision
            prev_statements = prev_claims.get(pid, []) 
            curr_statements = curr_claims.get(pid, [])

            # Map by property-value ID
            prev_by_id = {stmt["id"]: stmt for stmt in prev_statements}
            curr_by_id = {stmt["id"]: stmt for stmt in curr_statements}

            # Get all property-value IDs
            all_statement_ids = set(prev_by_id.keys()).union(curr_by_id.keys())

            for sid in all_statement_ids:
                prev_stmt = prev_by_id.get(sid, None)
                curr_stmt = curr_by_id.get(sid, None)

                if prev_stmt:
                    prev_stmt['mainsnak'] = PageParser.homogenize_datavalue(prev_stmt['mainsnak'])

                if curr_stmt:
                    curr_stmt['mainsnak'] = PageParser.homogenize_datavalue(curr_stmt['mainsnak'])

                new_value, new_datatype, new_datatype_metadata = PageParser._parse_datavalue(curr_stmt)
                old_value, old_datatype, old_datatype_metadata = PageParser._parse_datavalue(prev_stmt)

                # value changes
                if prev_stmt and not curr_stmt:
                    change_detected = True
                    # Property value was removed -> the datatype is the datatype of the old_value

                    if pid == 'P31':
                        self.entity_data['p31_types'].remove((sid, old_value))

                    if pid == 'P279':
                        self.entity_data['p279_types'].remove((sid, old_value))

                    self._handle_value_changes(old_datatype, new_datatype, new_value, old_value, sid, pid, DELETE_PROPERTY_VALUE)

                    if old_datatype_metadata and self.extract_datatype_metadata_changes:
                        # Add change record for the datatype_metadata fields
                        self._handle_datatype_metadata_changes(old_datatype_metadata, new_datatype_metadata, sid, old_datatype, old_datatype, pid, DELETE_PROPERTY_VALUE)

                elif curr_stmt and not prev_stmt:
                    change_detected = True
                    # Property value was created

                    if pid == 'P31':
                        self.entity_data['p31_types'].add((sid, new_value))

                    if pid == 'P279':
                        self.entity_data['p279_types'].add((sid, new_value))

                    self._handle_value_changes(old_datatype, new_datatype, new_value, old_value, sid, pid, CREATE_PROPERTY_VALUE)

                    if new_datatype_metadata and self.extract_datatype_metadata_changes:
                        # Add change record for the datatype_metadata fields
                        self._handle_datatype_metadata_changes(old_datatype_metadata, new_datatype_metadata, sid, None, new_datatype, pid, CREATE_PROPERTY_VALUE)
                elif prev_stmt and curr_stmt:

                    # Property was updated
                    if (old_datatype != new_datatype) or (old_value != new_value):
                        
                        # Datatype change implies a value change
                        if new_datatype == 'time':
                            # don't consider changes like +00002025-10-01T:00:00:00Z to +2025-10-01T:00:00:00Z
                            # this is internal to WD representation
                            old_value_cleaned = re.sub(r'^([+-])0+(?=\d{4}-)', r'\1', old_value)
                            new_value_cleaned = re.sub(r'^([+-])0+(?=\d{4}-)', r'\1', new_value)
                            if old_value_cleaned != new_value_cleaned:
                                change_detected = True
                                self._handle_value_changes(old_datatype, new_datatype, new_value_cleaned, old_value_cleaned, sid, pid, UPDATE_PROPERTY_VALUE)
                        else:
                            change_detected = True
                            self._handle_value_changes(old_datatype, new_datatype, new_value, old_value, sid, pid, UPDATE_PROPERTY_VALUE)

                        if pid == 'P31':
                            self.entity_data['p31_types'].remove((sid, old_value))
                            self.entity_data['p31_types'].add((sid, new_value))

                        if pid == 'P279':
                            self.entity_data['p279_types'].remove((sid, old_value))
                            self.entity_data['p279_types'].add((sid, new_value))

                    if ((old_datatype != new_datatype) or (old_datatype_metadata != new_datatype_metadata)) \
                        and self.extract_datatype_metadata_changes:
                        change_detected = True
                        # Datatype change imples a datatype_metadata change

                        self._handle_datatype_metadata_changes(old_datatype_metadata, new_datatype_metadata, sid, old_datatype, new_datatype, pid, UPDATE_PROPERTY_DATATYPE_METADATA)
                
                # rank changes
                rank_change_detected = self._handle_rank_changes(prev_stmt, curr_stmt, pid, sid, old_datatype, new_datatype)

                # qualifier changes
                qualifier_change_detected = self._handle_qualifier_changes(pid, sid, prev_stmt=prev_stmt, curr_stmt=curr_stmt)

                # reference changes
                reference_change_detected = self._handle_reference_changes(pid, sid, prev_stmt=prev_stmt, curr_stmt=curr_stmt)

                change_detected = change_detected or rank_change_detected or qualifier_change_detected or reference_change_detected

        return change_detected
    
    def get_changes_from_revisions(self, current_revision, previous_revision):
        """
            Extracts changes between cureent_revision and previous_revision
            Returns True if there were changes detected, otherwise False
        """
        change_detected = False # Returns True if there were any changes detected
        if previous_revision is None:
            # Entity was created 
            return self._changes_created_entity(current_revision)
        else:
            
            curr_label = PageParser._safe_get_nested(current_revision, 'labels')
            curr_desc = PageParser._safe_get_nested(current_revision, 'descriptions')
            curr_claims = PageParser._safe_get_nested(current_revision, 'claims')

            if 'redirect' in current_revision:
                self.current_revision_redirect = True
                return True

            if not curr_claims and not curr_label and not curr_desc:
                curr_aliases = PageParser._safe_get_nested(current_revision, 'aliases')
                curr_sitelinks = PageParser._safe_get_nested(current_revision, 'sitelinks')

                if curr_aliases or curr_sitelinks:
                    # skip revision 
                    # Reasons: can be an initial reivsion that only has sitelinks/aliases
                    return False

                # completely empty revision -> the item was cleaned, probably because of a merge
                # the following revision is probably a redirect
                if not curr_aliases and not curr_sitelinks:
                    self._changes_cleaned_entity(previous_revision)
                    return True

            # --- Labels and Description changes ---
            change_detected = self._handle_description_label_change(previous_revision, current_revision)

            # --- Claims (P-IDs) ---
            prev_claims = PageParser._safe_get_nested(previous_revision, 'claims')

            prev_claims_pids = set(prev_claims.keys())
            curr_claims_pids = set(curr_claims.keys())
            
            # --- New properties in current revision ---
            new_pids = curr_claims_pids - prev_claims_pids
            if new_pids:
                change_detected = True
                self._handle_new_pids(new_pids, curr_claims)

            # --- Deleted properties in current revision ---
            removed_pids = prev_claims_pids - curr_claims_pids
            if removed_pids:
                change_detected = True
                self._handle_removed_pids(removed_pids, prev_claims)

            # --- Check updates of statements between revisions ---
            remaining_pids = prev_claims_pids.intersection(curr_claims_pids)
            if remaining_pids:
                change_detected_rem_pids = self._handle_remaining_pids(remaining_pids, prev_claims, curr_claims)

                change_detected = change_detected or change_detected_rem_pids

        return change_detected

    def process_page(self):
        """
            Processes all the revisions in a <page></page> and stores the extracted data in the corresponding tables revision, change and change_metadata
        """

        start_parse_time = time.time()

        # TODO: remove
        title_tag = f"{{{NS}}}title"
        revision_tag = f'{{{NS}}}revision'
        revision_text_tag = f'{{{NS}}}text'

        entity_id = ''

        previous_revision = None

        last_non_deleted_revision_id = -1
        prev_revision_deleted = False

        # TODO get from dict
        # Extract title = entity_id
        title_elem = self.page_elem.find(title_tag)
        if title_elem is not None:
            entity_id = (title_elem.text or '').strip()

        self.entity_stats['qid'] = entity_id

        entity_id = id_to_int(entity_id) # convert Q-ID to integer (remove the 'Q')
        
        self.entity_stats['entity_id'] = entity_id
        
        # For measuring time it takes to calculate full diffs between revisions
        total_revision_diff_time_sec = 0
        num_revisions_timed = 0

        # Iterate over revisions
        for rev_elem in self.page_elem.findall(revision_tag):

            revision_id = int(rev_elem.findtext(f'{{{NS}}}id', '').strip()) # revision id
            revision_text_elem = rev_elem.find(revision_text_tag) # revision <text></text>
            if revision_text_elem is not None:
                # If the revision was deleted the text tag looks like: <text bytes="11179" sha1="ou0t1tihux9rw2wb939kv22axo3h2uh" deleted="deleted"/>
                # and there's no content inside
                
                deleted_attr = revision_text_elem.get("deleted")
                if not deleted_attr: # Revision was not deleted
                    
                    # Extract text, id, timestamp, comment, username, user_id
                    contrib_elem = rev_elem.find(f'{{{NS}}}contributor')

                    prev_revision_id = rev_elem.findtext(f'{{{NS}}}parentid', '').strip()
                    if prev_revision_id and not prev_revision_deleted:
                        prev_revision_id = int(prev_revision_id)
                    elif prev_revision_deleted:
                        prev_revision_id = last_non_deleted_revision_id
                    else:
                        prev_revision_id = None # initial revision

                    if prev_revision_deleted:
                        prev_revision_deleted = False
                
                    if contrib_elem is not None:
                        username = (contrib_elem.findtext(f'{{{NS}}}username') or '').strip()
                        user_id = (contrib_elem.findtext(f'{{{NS}}}id') or '').strip()
                    else:
                        username = ''
                        user_id = ''

                    user_type = ''
                    if 'bot' in username.lower():
                        user_type = 'bot'
                    elif username == '':
                        user_type = 'anonymous'
                    else:
                        user_type = 'human'

                    # Save revision metadata (what will be stored in the revision table)
                    self.revision_meta = {
                        'entity_id': entity_id,
                        'revision_id': revision_id,
                        'prev_revision_id': prev_revision_id if prev_revision_id else '-1', # for the first revision (doesn't have a parentid)
                        'timestamp': rev_elem.findtext(f'{{{NS}}}timestamp', '').strip(),
                        'comment': rev_elem.findtext(f'{{{NS}}}comment', '').strip(),
                        'file_id': self.file_id,
                        'user_id': user_id,
                        'username': username,
                        'user_type': user_type
                    }

                    # decode content inside <text></text>
                    if revision_text_elem.text:
                        current_revision = self._parse_json_revision(rev_elem, (revision_text_elem.text).strip())
                    
                    if current_revision is None or revision_text_elem.text is None:
                        # The json parsing for the revision text failed.
                        change = False
                    else:
                        # update label and description
                        curr_label, curr_alias, curr_desc = self.get_label_alias_description(current_revision)
                        if curr_label and self.entity_data['label'] != curr_label and curr_label != '':
                            self.entity_data['label'] = curr_label

                        if curr_desc and self.entity_data['description'] != curr_desc and curr_desc != '':
                            self.entity_data['description'] = curr_desc

                        if curr_alias and self.entity_data['alias'] != curr_alias and curr_alias != '':
                            self.entity_data['alias'] = curr_alias

                        # get changes for revision
                        start_time_changes = time.time()
                        change = self.get_changes_from_revisions(current_revision, previous_revision)
                        total_revision_diff_time_sec += (time.time() - start_time_changes) # get per revision work (time it takes to claculate diff)
                        num_revisions_timed += 1

                    if change: # store revision if there was any change detected
                        
                        # Because revisions that modify aliases/sitelinks are not stored. Therefore, we store the 
                        # prev_revision_id as the last non deleted revision id that we actually stored in the DB.
                        if last_non_deleted_revision_id != self.revision_meta['prev_revision_id']:
                            prev_rev_id = last_non_deleted_revision_id
                        else:
                            prev_rev_id = self.revision_meta['prev_revision_id']

                        def extract_redirect_qid(rev_text):
                            """
                                The revision text looks like: {"entity":"Q11085307","redirect":"Q4126"}
                            """
                            if not rev_text:
                                return ''
                            redirect_entity = json.loads(rev_text)
                            redirect_entity = redirect_entity.get('redirect', '')

                            return id_to_int(redirect_entity)

                        self.revision.append((
                            prev_rev_id,
                            self.revision_meta['revision_id'],
                            self.revision_meta['entity_id'],
                            self.revision_meta['timestamp'],
                            self.revision_meta['user_id'],
                            self.revision_meta['username'],
                            self.revision_meta['user_type'],
                            self.revision_meta['comment'],
                            self.file_id,
                            extract_redirect_qid((revision_text_elem.text).strip()) if self.current_revision_redirect else ''
                        ))

                        if user_type == 'bot':
                            self.entity_stats['num_bot_edits'] += 1
                        elif user_type == 'anonymous':
                            self.entity_stats['num_anonymous_edits'] += 1
                        else:
                            self.entity_stats['num_human_edits'] += 1

                        if self.current_revision_redirect:
                            previous_revision = None
                            self.current_revision_redirect = False

                        # for revisions that have been deleted
                        # we store prev_revision_id as the last non deleted revision
                        # NOTE: if there are no changes, we don't store revision information, therefore we 
                        # have to update this here
                        last_non_deleted_revision_id = revision_id

                        # if parse_revisions_text returns None then
                        # we only update previous_revision with an actual revision (that has a json in the revision <text></text>)
                        # 
                        if current_revision is not None:
                            previous_revision = current_revision
                    
                else: # revision was deleted
                    prev_revision_deleted = True

            # free memory
            rev_elem.clear()

        end_time_parse = time.time()
        
        # Clear element to free memory
        self.page_elem.clear()
        while self.page_elem.getprevious() is not None:
            del self.page_elem.getparent()[0]

        ## -------------------------------------------------- ##
        # Tag reverted edits
        ## -------------------------------------------------- ##
        t0 = time.time()
        self.changes, self.rank_changes, self.entity_stats = self.rule_based_classifier.tag_reverted_edits(self.changes_by_pv, self.changes, self.entity_stats)
        rev_edit_time = time.time() - t0
        
        ## -------------------------------------------------- ##
        # Filter entities and send them to corresponding tables
        ## -------------------------------------------------- ##
        list_of_types_31 = list(set([type_id for val_id, type_id in self.entity_data['p31_types']]))

        is_scholarly_article = False
        if self.set_up['change_extraction_filters']['scholarly_articles_filter']['extract']:
            if len(list_of_types_31) > 0:
                for et in list_of_types_31:
                    if et in self.SCHOLARLY_ARTICLE_TYPES: # get the value of P31
                        is_scholarly_article = True
                        break
        
        is_astronomical_object = False
        if self.set_up['change_extraction_filters']['astronomical_objects_filter']['extract']:
            if len(list_of_types_31) > 0:
                for et in list_of_types_31:
                    if et in self.ASTRONOMICAL_OBJECT_TYPES: # get the value of P31
                        is_astronomical_object = True
                        break
        
        # only for the remaining entities
        has_less_revisions = False
        if self.set_up['change_extraction_filters']['less_filter']['extract']:
            change_threshold = self.set_up['change_extraction_filters']['less_filter']['threshold']
            if not is_astronomical_object and not is_scholarly_article and self.entity_stats['num_value_changes'] <= change_threshold:
                has_less_revisions = True

        end_time_process = time.time() - start_parse_time

        ## -------------------------------------------------- ##
        # Add entity stats
        ## -------------------------------------------------- ##

        self.entity_stats['num_revisions'] = len(self.revision)

        self.entity_stats['num_qualifier_changes'] = len(self.qualifier_changes)
        self.entity_stats['num_reference_changes'] = len(self.reference_changes)

        self.entity_stats['entity_label'] = self.entity_data['label'] if self.entity_data['label'] else self.entity_data['alias']
        self.entity_stats['entity_description'] = self.entity_data['description'] if self.entity_data['description'] else ''
        
        str_list = ', '.join(list_of_types_31)
        self.entity_stats['entity_types_31'] = str_list
        
        self.entity_stats['first_revision_timestamp'] = self.revision[0][3] if len(self.revision) > 0 else None # timestamp is at position 3 in the tuple
        self.entity_stats['last_revision_timestamp'] = self.revision[-1][3] if len(self.revision) > 0 else None

        ## -------------------------------------------------- ##
        # Throughput metrics
        ## -------------------------------------------------- ##
        self.entity_stats['total_xml_parse_time_sec'] = end_time_parse - start_parse_time # returns full parsing of XML pages for the entity
        
        self.entity_stats['total_process_time_sec'] = end_time_process
        
        self.entity_stats['total_revision_diff_time_sec'] = total_revision_diff_time_sec # returns the time it takes to calculate diffs between revisions (this is part of the full parsing time)
        self.entity_stats['num_revisions_timed'] = num_revisions_timed
        
        self.entity_stats['file_id'] = self.file_id

        self.entity_stats['total_rev_edit_time_sec'] = rev_edit_time
        
        self.entity_stats['total_feature_creation_sec'] = self.total_feature_creation_sec
        self.entity_stats['num_feature_creations_timed'] = self.num_feature_creations_timed

        self.entity_stats['total_rule_based_classification_sec'] = self.total_rule_based_classification_sec

        result = {
            'revision': list(self.revision),
            'value_change': list(self.changes),
            'rank_change': list(self.rank_changes),
            'qualifier_change': list(self.qualifier_changes),
            'reference_change': list(self.reference_changes),
            'datatype_metadata_change': list(self.datatype_metadata_changes) if self.extract_datatype_metadata_changes else [],
            'updates_entity': list(self.updates_entity) if self.set_up.get('re_interpretation', False) else [],
            'updates_text': list(self.updates_text) if self.set_up.get('re_interpretation', False) else [],
            'is_scholarly_article': is_scholarly_article,
            'is_astronomical_object': is_astronomical_object,
            'has_less_revisions': has_less_revisions,
            'entity_stats': [tuple(self.entity_stats.get(col) for col in ENTITY_STATS_COLS)]
        }

        self.changes_by_pv.clear()

        self.changes.clear()
        self.rank_changes.clear()
        self.revision.clear()
        self.qualifier_changes.clear()
        self.reference_changes.clear()

        self.revision_meta.clear()

        if self.set_up.get('change_extraction_filters', {}).get('datatype_metadata_extraction', False):
            self.datatype_metadata_changes.clear()

        if self.set_up.get('re_interpretation', False):
            self.updates_entity.clear()
            self.updates_text.clear()
        
        del self.entity_stats
        del self.entity_data

        return result