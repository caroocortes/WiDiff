import csv

def preprocess_csv(input_file, output_file, delimiter=';'):
    """
    Read CSV with mixed quotes and write with standardized double quotes
    """
    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8', newline='') as outfile:
        
        # Read with Python's csv module (handles mixed quotes)
        reader = csv.reader(infile, delimiter=delimiter)
        
        # Write with standard double quotes
        writer = csv.writer(outfile, delimiter=delimiter, quotechar='"', 
                          quoting=csv.QUOTE_MINIMAL)
        
        for row in reader:
            writer.writerow(row)
    
    print(f"Preprocessed CSV saved to {output_file}")


def copy_from_csv(conn, csv_file_path, table_name, columns, primary_keys, delimiter=','):
    temp_table = f"{table_name}_temp"

    with conn.cursor() as cur:
        
        cur.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = '{table_name}'
            );
        """)
        exists = cur.fetchone()[0]
        
    conn.commit()

    if not exists:

        with conn.cursor() as cur:
            cols_definition = ', '.join([f"{col} VARCHAR" for col in columns])
            cur.execute(f"CREATE TEMP TABLE {temp_table} ({cols_definition});")
            
            cols = ','.join(columns)
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                next(f)  # skip header
                cur.copy_expert(f"""
                    COPY {temp_table} ({cols})
                    FROM STDIN
                    WITH (
                        FORMAT csv, 
                        HEADER FALSE, 
                        DELIMITER '{delimiter}', 
                        QUOTE '"', 
                        ESCAPE '"',
                        NULL 'NULL'  -- Explicitly handle the string 'NULL' as actual NULL
                    );
                """, f)
            
            print(f"Loaded data into temp table. Removing duplicates...")
            
            cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT DISTINCT * FROM {temp_table};")

            update_query = """
                UPDATE gold_standard
                SET 
                    change_target = COALESCE(change_target, ''),
                    new_value = COALESCE(new_value, ''),
                    old_value = COALESCE(old_value, ''),
                    new_value_label = COALESCE(new_value_label, ''),
                    old_value_label = COALESCE(old_value_label, '')
                """
            cur.execute(update_query)

            # add PK
            if primary_keys:
                
                pk_cols_str = ', '.join(primary_keys)
                # remove duplicates based on primary key columns
                print("Removing duplicates...")
                cur.execute(f"""
                    DELETE FROM {table_name} a
                    USING {table_name} b
                    WHERE a.ctid < b.ctid
                    AND {' AND '.join([f'a.{col} = b.{col}' for col in primary_keys])};
                """)

                print("Adding PK")
                cur.execute(f"ALTER TABLE {table_name} ADD PRIMARY KEY ({pk_cols_str});")
        conn.commit()
    else:
        print(f"Table {table_name} already exists. Skipping loading data.")

    return exists

def get_time_unit(elapsed_time):
    """
    Convert elapsed time in seconds to appropriate unit.
    Returns (value, unit)
    """
    if elapsed_time >= 86400:  # 60*60*24 = 86400 seconds in a day
        return elapsed_time / 86400, 'days'
    elif elapsed_time >= 3600:  # 60*60 = 3600 seconds in an hour
        return elapsed_time / 3600, 'hours'
    elif elapsed_time >= 60:
        return elapsed_time / 60, 'minutes'
    else:
        return elapsed_time, 'seconds'
    
def print_select_results(results, columns):
    print(" | ".join(columns))
    for row in results: # row is a tuple
        for elem in row:
            print(elem, end=' | ')
        print('\n')