import unittest
import os
import json
import datetime
import target_postgres

from nose.tools import assert_raises 
from target_postgres.db_sync import DbSync

try:
    import tests.utils as test_utils
except ImportError:
    import utils as test_utils


METADATA_COLUMNS = [
    '_sdc_extracted_at',
    '_sdc_batched_at',
    '_sdc_deleted_at'
]


class TestIntegration(unittest.TestCase):
    """
    Integration Tests
    """
    @classmethod
    def setUp(self):
        self.config = test_utils.get_test_config()
        postgres = DbSync(self.config)
        if self.config['default_target_schema']:
            postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))


    def remove_metadata_columns_from_rows(self, rows):
        """Removes metadata columns from a list of rows"""
        d_rows = []
        for r in rows:
            # Copy the original row to a new dict to keep the original dict
            # and remove metadata columns
            d_row = r.copy()
            for md_c in METADATA_COLUMNS:
                d_row.pop(md_c, None)

            # Add new row without metadata columns to the new list
            d_rows.append(d_row)

        return d_rows


    def assert_metadata_columns_exist(self, rows):
        """This is a helper assertion that checks if every row in a list has metadata columns"""
        for r in rows:
            for md_c in METADATA_COLUMNS:
                self.assertTrue(md_c in r)


    def assert_metadata_columns_not_exist(self, rows):
        """This is a helper assertion that checks metadata columns don't exist in any row"""
        for r in rows:
            for md_c in METADATA_COLUMNS:
                self.assertFalse(md_c in r)


    def assert_three_streams_are_into_postgres(self, should_metadata_columns_exist=False, should_hard_deleted_rows=False):
        """
        This is a helper assertion that checks if every data from the message-with-three-streams.json
        file is available in Postgres tables correctly.
        Useful to check different loading methods without duplicating assertions
        """
        postgres = DbSync(self.config)
        default_target_schema = self.config.get('default_target_schema', '')
        schema_mapping = self.config.get('schema_mapping', {})

        # Identify target schema name
        target_schema = None
        if default_target_schema is not None and default_target_schema.strip():
            target_schema = default_target_schema
        elif schema_mapping:
            target_schema = os.environ.get("TARGET_POSTGRES_SCHEMA")

        # Get loaded rows from tables
        table_one = postgres.query("SELECT * FROM {}.test_table_one ORDER BY c_pk".format(target_schema))
        table_two = postgres.query("SELECT * FROM {}.test_table_two ORDER BY c_pk".format(target_schema))
        table_three = postgres.query("SELECT * FROM {}.test_table_three ORDER BY c_pk".format(target_schema))


        # ----------------------------------------------------------------------
        # Check rows in table_one
        # ----------------------------------------------------------------------
        expected_table_one = [
            {'c_int': 1, 'c_pk': 1, 'c_varchar': '1'}
        ]

        #self.assertEqual(
        #    self.remove_metadata_columns_from_rows(table_one), expected_table_one)

        # ----------------------------------------------------------------------
        # Check rows in table_tow
        # ----------------------------------------------------------------------
        expected_table_two = []
        if not should_hard_deleted_rows:
            expected_table_two = [
                {'c_int': 1, 'c_pk': 1, 'c_varchar': '1', 'c_date': datetime.datetime(2019, 2, 1, 15, 12, 45)},
                {'c_int': 2, 'c_pk': 2, 'c_varchar': '2', 'c_date': datetime.datetime(2019, 2, 10, 2, 0, 0)}
            ]
        else:
            expected_table_two = [
                {'c_int': 2, 'c_pk': 2, 'c_varchar': '2', 'c_date': datetime.datetime(2019, 2, 10, 2, 0, 0)}
            ]

        #self.assertEqual(
        #    self.remove_metadata_columns_from_rows(table_two), expected_table_two)

        # ----------------------------------------------------------------------
        # Check rows in table_three
        # ----------------------------------------------------------------------
        expected_table_three = []
        if not should_hard_deleted_rows:
            expected_table_three = [
                    {'c_int': 1, 'c_pk': 1, 'c_varchar': '1', 'c_time': datetime.time(4, 0, 0)},
                    {'c_int': 2, 'c_pk': 2, 'c_varchar': '2', 'c_time': datetime.time(7, 15, 0)},
                    {'c_int': 3, 'c_pk': 3, 'c_varchar': '3', 'c_time': datetime.time(23, 0, 3)}
            ]
        else:
            expected_table_three = [
                {'c_int': 1, 'c_pk': 1, 'c_varchar': '1', 'c_time': datetime.time(4, 0, 0)},
                {'c_int': 2, 'c_pk': 2, 'c_varchar': '2', 'c_time': datetime.time(7, 15, 0)}
            ]

        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_three), expected_table_three)

        # ----------------------------------------------------------------------
        # Check if metadata columns exist or not
        # ----------------------------------------------------------------------
        if should_metadata_columns_exist:
            self.assert_metadata_columns_exist(table_one)
            self.assert_metadata_columns_exist(table_two)
            self.assert_metadata_columns_exist(table_three)
        else:
            self.assert_metadata_columns_not_exist(table_one)
            self.assert_metadata_columns_not_exist(table_two)
            self.assert_metadata_columns_not_exist(table_three)


    def test_invalid_json(self):
        """Receiving invalid JSONs should raise an exception"""
        tap_lines = test_utils.get_test_tap_lines('invalid-json.json')
        with assert_raises(json.decoder.JSONDecodeError):
            target_postgres.persist_lines(self.config, tap_lines)


    def test_message_order(self):
        """RECORD message without a previously received SCHEMA message should raise an exception"""
        tap_lines = test_utils.get_test_tap_lines('invalid-message-order.json')
        with assert_raises(Exception):
            target_postgres.persist_lines(self.config, tap_lines)


    def test_loading_tables(self):
        """Loading multiple tables from the same input tap with various columns types"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-three-streams.json')
        target_postgres.persist_lines(self.config, tap_lines)

        self.assert_three_streams_are_into_postgres()


    def test_loading_tables_with_metadata_columns(self):
        """Loading multiple tables from the same input tap with various columns types"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-three-streams.json')

        # Turning on adding metadata columns
        self.config['add_metadata_columns'] = True
        target_postgres.persist_lines(self.config, tap_lines)

        # Check if data loaded correctly and metadata columns exist
        self.assert_three_streams_are_into_postgres(should_metadata_columns_exist=True)


    def test_loading_tables_with_hard_delete(self):
        """Loading multiple tables from the same input tap with deleted rows"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-three-streams.json')

        # Turning on hard delete mode
        self.config['hard_delete'] = True
        target_postgres.persist_lines(self.config, tap_lines)

        # Check if data loaded correctly and metadata columns exist
        self.assert_three_streams_are_into_postgres(
            should_metadata_columns_exist=True,
            should_hard_deleted_rows=True
        )


    def test_loading_with_multiple_schema(self):
        """Loading table with multiple SCHEMA messages"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-multi-schemas.json')

        # Load with default settings
        target_postgres.persist_lines(self.config, tap_lines)

        # Check if data loaded correctly
        self.assert_three_streams_are_into_postgres(
            should_metadata_columns_exist=False,
            should_hard_deleted_rows=False
        )


    def test_loading_unicode_characters(self):
        """Loading unicode encoded characters"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-unicode-characters.json')

        # Load with default settings
        target_postgres.persist_lines(self.config, tap_lines)

        # Get loaded rows from tables
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        table_unicode = postgres.query("SELECT * FROM {}.test_table_unicode ORDER BY c_pk".format(target_schema))

        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_unicode),
            [
                    {'c_int': 1, 'c_pk': 1, 'c_varchar': 'Hello world, Καλημέρα κόσμε, コンニチハ'},
                    {'c_int': 2, 'c_pk': 2, 'c_varchar': 'Chinese: 和毛泽东 <<重上井冈山>>. 严永欣, 一九八八年.'},
                    {'c_int': 3, 'c_pk': 3, 'c_varchar': 'Russian: Зарегистрируйтесь сейчас на Десятую Международную Конференцию по'},
                    {'c_int': 4, 'c_pk': 4, 'c_varchar': 'Thai: แผ่นดินฮั่นเสื่อมโทรมแสนสังเวช'},
                    {'c_int': 5, 'c_pk': 5, 'c_varchar': 'Arabic: لقد لعبت أنت وأصدقاؤك لمدة وحصلتم علي من إجمالي النقاط'},
                    {'c_int': 6, 'c_pk': 6, 'c_varchar': 'Special Characters: [",\'!@£$%^&*()]'}
            ])


    def test_loading_long_text(self):
        """Loading long texts"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-long-texts.json')

        # Load with default settings
        target_postgres.persist_lines(self.config, tap_lines)

        # Get loaded rows from tables
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        table_long_texts = postgres.query("SELECT * FROM {}.test_table_long_texts ORDER BY c_pk".format(target_schema))

        # Test not very long texts by exact match
        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_long_texts)[:3],
            [
                    {'c_int': 1, 'c_pk': 1, 'c_varchar': 'Up to 128 characters: Lorem ipsum dolor sit amet, consectetuer adipiscing elit.'},
                    {'c_int': 2, 'c_pk': 2, 'c_varchar': 'Up to 256 characters: Lorem ipsum dolor sit amet, consectetuer adipiscing elit. Aenean commodo ligula eget dolor. Aenean massa. Cum sociis natoque penatibus et magnis dis parturient montes, nascetur ridiculus mus. Donec quam felis, ultricies.'},
                    {'c_int': 3, 'c_pk': 3, 'c_varchar': 'Up to 1024 characters: Lorem ipsum dolor sit amet, consectetuer adipiscing elit. Aenean commodo ligula eget dolor. Aenean massa. Cum sociis natoque penatibus et magnis dis parturient montes, nascetur ridiculus mus. Donec quam felis, ultricies nec, pellentesque eu, pretium quis, sem. Nulla consequat massa quis enim. Donec pede justo, fringilla vel, aliquet nec, vulputate eget, arcu. In enim justo, rhoncus ut, imperdiet a, venenatis vitae, justo. Nullam dictum felis eu pede mollis pretium. Integer tincidunt. Cras dapibus. Vivamus elementum semper nisi. Aenean vulputate eleifend tellus. Aenean leo ligula, porttitor eu, consequat vitae, eleifend ac, enim. Aliquam lorem ante, dapibus in, viverra quis, feugiat a, tellus. Phasellus viverra nulla ut metus varius laoreet. Quisque rutrum. Aenean imperdiet. Etiam ultricies nisi vel augue. Curabitur ullamcorper ultricies nisi. Nam eget dui. Etiam rhoncus. Maecenas tempus, tellus eget condimentum rhoncus, sem quam semper libero, sit amet adipiscing sem neque sed ipsum.'},
            ])

        # Test very long texts by string length
        record_4k = table_long_texts[3]
        record_32k = table_long_texts[4]
        self.assertEqual(
            [
                {'c_int': int(record_4k.get('c_int')), 'c_pk': int(record_4k.get('c_pk')), 'len': len(record_4k.get('c_varchar'))},
                {'c_int': int(record_32k.get('c_int')), 'c_pk': int(record_32k.get('c_pk')), 'len': len(record_32k.get('c_varchar'))},
            ],
            [
                {'c_int': 4, 'c_pk': 4, 'len': 4017},
                {'c_int': 5, 'c_pk': 5, 'len': 32003},
            ])


    def test_non_db_friendly_columns(self):
        """Loading non-db friendly columns like, camelcase, minus signs, etc."""
        tap_lines = test_utils.get_test_tap_lines('messages-with-non-db-friendly-columns.json')

        # Load with default settings
        target_postgres.persist_lines(self.config, tap_lines)

        # Get loaded rows from tables
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        table_non_db_friendly_columns = postgres.query("SELECT * FROM {}.test_table_non_db_friendly_columns ORDER BY c_pk".format(target_schema))

        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_non_db_friendly_columns),
            [
                    {'c_pk': 1, 'camelcasecolumn': 'Dummy row 1', 'minus-column': 'Dummy row 1'},
                    {'c_pk': 2, 'camelcasecolumn': 'Dummy row 2', 'minus-column': 'Dummy row 2'},
                    {'c_pk': 3, 'camelcasecolumn': 'Dummy row 3', 'minus-column': 'Dummy row 3'},
                    {'c_pk': 4, 'camelcasecolumn': 'Dummy row 4', 'minus-column': 'Dummy row 4'},
                    {'c_pk': 5, 'camelcasecolumn': 'Dummy row 5', 'minus-column': 'Dummy row 5'},
            ])


    def test_nested_schema_unflattening(self):
        """Loading nested JSON objects into JSONB columns without flattening"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-nested-schema.json')

        # Load with default settings - Flattening disabled
        target_postgres.persist_lines(self.config, tap_lines)

        # Get loaded rows from tables - Transform JSON to string at query time
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        unflattened_table = postgres.query("""SELECT * FROM {}.test_table_nested_schema ORDER BY c_pk""".format(target_schema))

        # Should be valid nested JSON strings
        self.assertEqual(
            self.remove_metadata_columns_from_rows(unflattened_table),
            [{
                'c_pk': 1,
                'c_array': [1, 2, 3],
                'c_object': {"key_1": "value_1"},
                'c_object_with_props': {"key_1": "value_1"},
                'c_nested_object': {"nested_prop_1": "nested_value_1", "nested_prop_2": "nested_value_2", "nested_prop_3": {"multi_nested_prop_1": "multi_value_1", "multi_nested_prop_2": "multi_value_2"}}
            }])


    def test_nested_schema_flattening(self):
        """Loading nested JSON objects with flattening and not not flattening"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-nested-schema.json')

        # Turning on data flattening
        self.config['data_flattening_max_level'] = 10

        # Load with default settings - Flattening enabled
        target_postgres.persist_lines(self.config, tap_lines)

        # Get loaded rows from tables
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        flattened_table = postgres.query("SELECT * FROM {}.test_table_nested_schema ORDER BY c_pk".format(target_schema))

        # Should be flattened columns
        self.assertEqual(
            self.remove_metadata_columns_from_rows(flattened_table),
            [{
                'c_pk': 1,
                'c_array': [1, 2, 3],
                'c_object': None,   # Cannot map RECORD to SCHEMA. SCHEMA doesn't have properties that requires for flattening
                'c_object_with_props__key_1': 'value_1',
                'c_nested_object__nested_prop_1': 'nested_value_1',
                'c_nested_object__nested_prop_2': 'nested_value_2',
                'c_nested_object__nested_prop_3__multi_nested_prop_1': 'multi_value_1',
                'c_nested_object__nested_prop_3__multi_nested_prop_2': 'multi_value_2',
            }])


    def test_column_name_change(self):
        """Tests correct renaming of BigQuery columns after source change"""
        tap_lines_before_column_name_change = test_utils.get_test_tap_lines('messages-with-three-streams.json')
        tap_lines_after_column_name_change = test_utils.get_test_tap_lines('messages-with-three-streams-modified-column.json')

        # Load with default settings
        # Load with default settings
        target_postgres.persist_lines(self.config, tap_lines_before_column_name_change)
        target_postgres.persist_lines(self.config, tap_lines_after_column_name_change)

        # Get loaded rows from tables
        postgres = DbSync(self.config)
        target_schema = self.config.get('default_target_schema', '')
        table_one = postgres.query("SELECT * FROM {}.test_table_one ORDER BY c_pk".format(target_schema))
        table_two = postgres.query("SELECT * FROM {}.test_table_two ORDER BY c_pk".format(target_schema))
        table_three = postgres.query("SELECT * FROM {}.test_table_three ORDER BY c_pk".format(target_schema))

        # Get the previous column name from information schema in test_table_two
        previous_column_name = postgres.query("""
            SELECT column_name
              FROM information_schema.columns
             WHERE table_catalog = '{}'
               AND table_schema = '{}'
               AND table_name = 'test_table_two'
               AND ordinal_position = 1
            """.format(
                self.config.get('dbname', '').lower(),
                target_schema.lower()))[0]["column_name"]

        # Table one should have no changes
        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_one),
            [{'c_int': 1, 'c_pk': 1, 'c_varchar': '1'}])

        # Table two should have versioned column
        self.assertEquals(
            self.remove_metadata_columns_from_rows(table_two),
            [
                {previous_column_name: datetime.datetime(2019, 2, 1, 15, 12, 45), 'c_int': 1, 'c_pk': 1, 'c_varchar': '1', 'c_date': None},
                {previous_column_name: datetime.datetime(2019, 2, 10, 2), 'c_int': 2, 'c_pk': 2, 'c_varchar': '2', 'c_date': '2019-02-12 02:00:00'},
                {previous_column_name: None, 'c_int': 3, 'c_pk': 3, 'c_varchar': '2', 'c_date': '2019-02-15 02:00:00'}
            ]
        )

        # Table three should have renamed columns
        self.assertEqual(
            self.remove_metadata_columns_from_rows(table_three),
            [
                {'c_int': 1, 'c_pk': 1, 'c_time': datetime.time(4, 0), 'c_varchar': '1', 'c_time_renamed': None},
                {'c_int': 2, 'c_pk': 2, 'c_time': datetime.time(7, 15), 'c_varchar': '2', 'c_time_renamed': None},
                {'c_int': 3, 'c_pk': 3, 'c_time': datetime.time(23, 0, 3), 'c_varchar': '3', 'c_time_renamed': datetime.time(8, 15)},
                {'c_int': 4, 'c_pk': 4, 'c_time': None, 'c_varchar': '4', 'c_time_renamed': datetime.time(23, 0, 3)}
            ])


    def test_schema_mapping(self):
        """Load stream into a specific schema, create indices and grant permissions"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-three-streams.json')

        # Turning on hard delete mode
        self.config['hard_delete'] = True

        # Remove the default_target_schema and use schema mapping
        del self.config['default_target_schema']

        # ... and define a custom stream to schema mapping
        self.config['schema_mapping'] = {
          "tap_mysql_test": {
              "target_schema": os.environ.get("TARGET_POSTGRES_SCHEMA"),
              "indices": {
                "test_table_one": ["c_varchar"],
                "test_table_two": ["c_varchar", "c_int"]
              }
            }
          }
        target_postgres.persist_lines(self.config, tap_lines)

        # Check if data loaded correctly and metadata columns exist
        self.assert_three_streams_are_into_postgres(
            should_metadata_columns_exist=True,
            should_hard_deleted_rows=True
        )


    def test_grant_privileges(self):
        """Tests GRANT USAGE and SELECT privileges on newly created tables"""
        tap_lines = test_utils.get_test_tap_lines('messages-with-three-streams.json')

        # Create test users and groups
        postgres = DbSync(self.config)
        postgres.query("DROP USER IF EXISTS user_1")
        postgres.query("DROP USER IF EXISTS user_2")
        try:
            postgres.query("DROP GROUP group_1") # DROP GROUP has no IF EXISTS
        except:
            pass
        try:
            postgres.query("DROP GROUP group_2")
        except:
            pass
        postgres.query("CREATE USER user_1 WITH PASSWORD 'Abcdefgh1234'")
        postgres.query("CREATE USER user_2 WITH PASSWORD 'Abcdefgh1234'")
        postgres.query("CREATE GROUP group_1 WITH USER user_1, user_2")
        postgres.query("CREATE GROUP group_2 WITH USER user_2")

        # When grantees is a string then privileges should be granted to single user
        postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))
        self.config['default_target_schema_select_permissions'] = 'group_1'
        target_postgres.persist_lines(self.config, tap_lines)

        # When grantees is a list then privileges should be granted to list of user
        postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))
        self.config['default_target_schema_select_permissions'] = ['group_1', 'group_2']
        target_postgres.persist_lines(self.config, tap_lines)

        # Grant privileges as dict should pass but should be ignored - Dict not supported for target-postgres
        postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))
        self.config['default_target_schema_select_permissions'] = {
            'users': ['user_1', 'user_2'],
            'groups': ['group_1', 'group_2']}
        target_postgres.persist_lines(self.config, tap_lines)

        # Granting not existing group should raise exception
        postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))
        with assert_raises(Exception):
            self.config['default_target_schema_select_permissions'] = 'group_not_exists_1'
            target_postgres.persist_lines(self.config, tap_lines)

        # Granting not existing list of groups should raise exception
        postgres.query("DROP SCHEMA IF EXISTS {} CASCADE".format(self.config['default_target_schema']))
        with assert_raises(Exception):
            self.config['default_target_schema_select_permissions'] = ['group_not_exists_1', 'group_not_exists_2']
            target_postgres.persist_lines(self.config, tap_lines)