import psycopg2
from loguru import logger
from psycopg2.extensions import connection, cursor

from multiple_sensor_reader.data.custom_types import IPAddressWithPort


class PostgresDbClient:
    """Class to define database client interface based on PostgreSQL."""

    def __init__(self, uri_db_server: str):
        self.db_name = "postgres"
        self.username = "sensor_reader"
        self.password = "1234"  # Password should not be hardcoded here
        self.address_db_server = IPAddressWithPort(uri=uri_db_server)

        self.timeout_connect = 10  # [s]
        self.db_conn: connection | None = None
        self.table_name = "sensor_data"

    def connect(self):
        """Connect to set PostgreSQL server.

        Returns:
            connection: connection to database server.
            [psycopg2.Error | None]: error code of the connection process.
        """
        try:
            self.db_conn: connection = psycopg2.connect(
                database=self.db_name,
                user=self.username,
                password=self.password,
                host=self.address_db_server.ip,
                port=self.address_db_server.port,
                connect_timeout=self.timeout_connect,
            )

        except psycopg2.Error as err:
            logger.error(f"Cannot connect to database: {err}")
            return self.db_conn, err

        return self.db_conn, None

    def setup_data_structure(self):
        """Set table data structure in case there was no previous existing data."""
        # Check previous existing data
        self.cursor = self.db_conn.cursor()

    def create_new_table(
        self, table_name: str, data_fields: list[str], data_types: list
    ):
        """Create a new table in the database, using each data field as a column."""
        # Not correctly implemented yet, check commented code for a schema of how to
        # dynamically create a table for each sensor.
        # Each registered sensor should have its own table,
        # and the columns should be the fields defined on each Payload type.
        pass

        # # Define basic structure of the database table
        # # Common header
        # query = (f"""CREATE TABLE {table_name}
        #     (id serial  PRIMARY KEY,"""
        # )

        # # Add columns for each data field
        # for index, (data_field, data_type) in enumerate(zip(data_fields, data_types)):
        #     if index < range(len(data_fields)):
        #         query += f"\n{data_field} {data_type} NOT NULL,"
        #     else:
        #         query += f"\n{data_field} {data_type} NOT NULL);"
        # self.cursor.execute(query)

        # self.db_conn.commit()

    def save_data(self, payload):
        """Save data to corresponding table
        Args:
            data (list[int]): data to be stored.
            timestamp (int): timestamp of the data.
        """
        # Not implemented, should save data to corresponding table according to each sensor.
        pass

        # self.cursor.execute(
        #     f"INSERT INTO {self.table_name} (value, timestamp) VALUES (%s, %s)",
        #     (data, timestamp),
        # )
        # self.db_conn.commit()  # type: ignore

    def disconnect(self):
        """Close cursor and connection to server database."""
        self.cursor.close()
        self.db_conn.close()
