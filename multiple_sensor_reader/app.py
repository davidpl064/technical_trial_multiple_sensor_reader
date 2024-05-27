import asyncio
import json
import sys
from collections.abc import Coroutine
from datetime import datetime
from typing import get_type_hints

import fire
import nats
from loguru import logger
from nats.aio.msg import Msg
from nats.errors import ConnectionClosedError, NoServersError, TimeoutError

from multiple_sensor_reader.data.custom_types import (
    AppCommandActions,
    Command,
    ConfigEnvironmental,
    ConfigInfrared,
    ConfigLidar,
    NatsUrl,
    PayloadEnvironmental,
    PayloadInfrared,
    PayloadLidar,
    RegisterInfo,
    Sensor,
    SensorTypesSupported,
)
from multiple_sensor_reader.db.db_client import PostgresDbClient
from tests.mocks.sensor_environmental import SensorEnvironmental
from tests.mocks.sensor_infrared import SensorInfrared


class AppMultipleSensorReader:
    """
    Class to capture sensor data and pyblish it to several services including: NATS server,
    PostgreSQL.
    """

    def __init__(self, uri_db_server: str):
        self.flag_on_standby = False
        self.flag_exit = False
        self.sleep_on_standby = 0.2
        self.sensor_data_array_length = 64
        self.last_sensor_data: list[int] | None = None

        self.topic_registering = "registering"
        self.topic_config = "config"
        self.topic_command = "app_command"
        self.topic_payload_data = "payload"

        self.uri_message_server = NatsUrl(url="nats://localhost:4222")

        self.db_client = PostgresDbClient(uri_db_server)

        # List of registered sensors, assign unique id for each new entry
        self.sensors_registered: list[Sensor] = []

        # Event flag to exit main loop
        self.stop_event = asyncio.Event()

    async def connect_to_message_server(self):
        """
        Connect to set NATS server.

        Returns:
            bool: result of the connection. True if successfull connection, False otherwise.
        """
        flag_connected: bool = False
        while not flag_connected:
            # Connect to local NATS server
            try:
                self.nats_client = await nats.connect(
                    self.uri_message_server.url,
                    connect_timeout=10,
                    error_cb=self.connect_errors_handler,
                )
                flag_connected = True
            except Exception as err:
                logger.error(f"Cannot connect to NATS message server: {err}")
                await asyncio.sleep(2)

        logger.success(
            f"Successfully connected to NATS server on URI: {self.uri_message_server.url}"
        )

        # Subscribe to topic for sensor registering
        self.sub_registering = await self.nats_client.subscribe(
            self.topic_registering, cb=self.handler_register_messages
        )

        # Subscribe to app command topic
        self.sub_app_command = await self.nats_client.subscribe(
            self.topic_command, cb=self.handler_command_messages
        )

        # Subscribe to topic for sensor reading data
        self.sub_payload_data = await self.nats_client.subscribe(
            self.topic_payload_data, cb=self.handler_payload_messages
        )

        return flag_connected

    async def connect_errors_handler(
        self, err: ConnectionClosedError | NoServersError | TimeoutError
    ):
        """Callback to handle connection errors to NATS server.

        Args:
            err (ConnectionClosedError, NoServersError, TimeoutError): encountered error in connection to NATS server.
        """
        logger.error(f"Cannot connect to NATS message server: {err}")

    async def connect_to_db(self):
        """Connect to set database.

        Returns:
            bool: result of the connection. True if successfull connection, False otherwise.
        """
        flag_connected = False
        while not flag_connected:
            logger.info(
                f"Trying to connect to database server on URI: {self.db_client.address_db_server.uri}"
            )
            db_conn, error_code = self.db_client.connect()

            if error_code is None:
                flag_connected = True
            else:
                await asyncio.sleep(2)

        logger.success(
            f"Successfully connected to database server on URI: {self.db_client.address_db_server.uri}"
        )

        # Setup basic data structure
        self.db_client.setup_data_structure()

        return flag_connected

    async def handler_register_messages(self, msg: Msg):
        """Callback to handle sensors request to be registered.
        New registered sensor has to be assigned a new id.
        """
        subject = msg.subject
        reply = msg.reply

        try:
            register_info = RegisterInfo(**json.loads(msg.data.decode("utf-8")))
        except Exception as err:
            logger.error(f"Registering information is not valid: {err}.")

        # Check validity of registering request and generate ID
        new_id = self.process_registering_request(register_info)

        # Get data fields and types to save in database
        data_fields, data_types = self.get_payload_structure(register_info.type)

        # Create new database table for new registered sensor
        new_table_name = f"sensor_{new_id}"
        self.db_client.create_new_table(new_table_name, data_fields, data_types)

        # Send ID to sender sensor, in order to add it to future payload messages for recognition
        if reply:
            await self.nats_client.publish(reply, str(new_id).encode())

    def process_registering_request(self, register_info: RegisterInfo):
        """Process information provided by the sensor and generate
            new id for it.

        Args:
            register_info (RegisterInfo): information of the sensor, like type.
                Sensor type must be in the list of compatible devices
                for this sensor reader.
        """
        # Count sensors to define new id
        new_id = len(self.sensors_registered)

        # Store new sensor in the list of registered sensors
        self.sensors_registered.append(
            Sensor(**{"id": new_id, "type": register_info.type})
        )
        logger.success(
            f"New sensor has been registered: Assigned ID -> {new_id}, type -> {register_info.type.name}"
        )

        return new_id

    def get_payload_structure(self, sensor_type: SensorTypesSupported):
        data_fields = []
        data_types = []
        match sensor_type:
            case SensorTypesSupported.INFRARED:
                payload_class = PayloadInfrared
            case SensorTypesSupported.ENVIRONMENTAL:
                payload_class = PayloadEnvironmental
            case SensorTypesSupported.LIDAR:
                payload_class = PayloadLidar

        for field_name, field_type in get_type_hints(payload_class).items():
            data_fields.append(field_name)
            data_types.append(field_type)

        return data_fields, data_types

    async def handler_command_messages(self, msg: Msg):
        """Callback to handle command messages that control app state.

        Args:
            msg (Msg): command message setting state of the app. Three execution modes
                ares currently supported:
                    1. AppCommandActions.START: start capturing and publushind data from sensors.
                    2. AppCommandActions.STOP: stop capturing and publushind data from sensors.
                    Sets the app on standby state.
                    3. AppCommandActions.EXIT: stop all functionalities and exits app main loop.
        """
        subject = msg.subject
        command = Command(**json.loads(msg.data.decode("utf-8")))
        logger.debug(f"Received a message on '{subject}' topic: {command}")

        # Parse command data
        match command.type:
            case AppCommandActions.START:
                self.flag_on_standby = False
                logger.info("Restarting sensor data capturing and processing.")

            case AppCommandActions.STOP:
                self.flag_on_standby = True
                logger.info("Stopping sensor data capturing and processing.")

            case AppCommandActions.SEND_CONFIG:
                logger.debug("Sending config to specified sensor.")
                await self.publish_config_to_sensor(command.data)

            case AppCommandActions.EXIT:
                logger.info("Closing app ...")
                await self.close()

    async def publish_config_to_sensor(
        self, sensor_config: ConfigInfrared | ConfigEnvironmental | ConfigLidar
    ):
        """Publish captured sensor data to a NATS topic.

        Args:
            last_sensor_data (list[int] | None): raw data from sensor. None in case of corrupted data.
        """
        await self.nats_client.publish(
            self.topic_config, json.dumps(sensor_config.model_dump()).encode("utf-8")
        )

    async def handler_payload_messages(self, msg: Msg):
        """Callback to handle messages containing raw data from sensors.

        Args:
            msg (Msg): message containing raw data from infrared sensor.
        """
        subject = msg.subject

        try:
            raw_payload_data = json.loads(msg.data.decode("utf-8"))
        except json.decoder.JSONDecodeError as err:
            logger.error(f"Sensor raw data couldn't be read: {err}.")

        if raw_payload_data["id"] is None:
            logger.error("Received payload data without ID.")
            return

        # Try to identify sensor sender
        sensor = self.get_sensor_from_id(raw_payload_data["id"])

        if not sensor:
            # Sensor is not registered, discard data
            logger.warning("Discarding payload from non registered sensor.")
            return

        # Parse data of the sensor according to its type
        data_parsed = self.parse_sensor_data(sensor, raw_payload_data)

        if not data_parsed:
            return

        # Assign data to sensor
        sensor.payload = data_parsed

        # Send data to be store in database
        self.db_client.save_data(sensor.payload)

    def get_sensor_from_id(self, id: int):
        """Get corresponding registered sensor from id defined in payload data.

        Args:
            id (int): ID associated to payload data.

        Returns:
            Sensor: corresponding registered sensor to received payload data.
        """
        for index, sensor in enumerate(self.sensors_registered):
            if sensor.id == id:
                logger.debug(f"Match registered sensor width ID: {id}.")
                return sensor

        return None

    def parse_sensor_data(self, sensor: Sensor, raw_data: dict):
        """Parse sensor raw data according to its type.

        Args:
            sensor (Sensor): sensor obejct containing related data.
            raw_data (dict): raw data from the sensor.

        Returns:
            PayloadInfrared | PayloadAmbiental | PayloadLidar: parsed data according to its sensor type.
        """
        try:
            match sensor.type:
                case SensorTypesSupported.INFRARED:
                    data_parsed = PayloadInfrared(**raw_data)
                case SensorTypesSupported.ENVIRONMENTAL:
                    data_parsed = PayloadEnvironmental(**raw_data)
                case SensorTypesSupported.LIDAR:
                    data_parsed = PayloadLidar(**raw_data)
                case _:
                    # Type is not supported
                    logger.error(f"Sensor type is not supported: id = {sensor.id}")
                    return None
        except Exception as err:
            logger.error(f"Couldn't parse payload information: {err}.")
            return None

        logger.info(
            f"Parsed payload data from sensor: ID -> {sensor.id}, type -> {sensor.type}\n"
            f"Payload: {data_parsed}"
        )

        return data_parsed

    async def run(self):
        """Run main loop of the app."""
        await self.connect_to_message_server()
        await self.connect_to_db()

        await self.stop_event.wait()

        logger.info("All closed, exiting")

    async def disconnect_from_message_server(self):
        """Disconnect from NATS server and unsubscribe from capturing and command topics."""
        # Remove interest in subscription.
        await self.sub_payload_data.unsubscribe()
        await self.sub_app_command.unsubscribe()

        # Close connection to NATS server after processing remaining messages
        await self.nats_client.drain()

    async def close(self):
        """Close all connections to external services and update app status to exit."""
        # Update app state to exiting
        self.stop_event.set()

        # Close connection to NATS server
        await self.disconnect_from_message_server()

        # Close database connection
        self.db_client.disconnect()


async def run_concurrent_tasks(tasks: list[Coroutine]):
    """Run input tasks concurrently.

    Args:
        tasks (list[Coroutine]): list of tasks to be run concurrently.
    """
    await asyncio.gather(*tasks)


def main(
    uri_db_server: str,
    number_sensors_each_type: list[int] | None = None,
    sensor_types: list[int] | None = None,
    min_range_value: int | None = None,
    max_range_value: int | None = None,
    log_level: str = "INFO",
):
    """Main method to run main lopp of AppMultipleSensorReader and mock passed sensors.

    Args:
        sensor_type (str): type of input infrared sensor. Can be mock or real.
        freq_read_data (int): frequency at which raw sensor data is read.
        uri_db_server (str): URI to database server.
        min_range_value (int | None, optional): min. value returned by input sensor. Defaults to None.
        max_range_value (int | None, optional): max. value returned by input sensor. Defaults to None.
        log_level (str, optional): level of logging messages. Defaults to "INFO".
    """
    # Configure logging level
    logger.configure(handlers=[{"sink": sys.stderr, "level": log_level}])

    # Mock set sensors
    tasks = []
    if number_sensors_each_type:
        for index_sensor, number_sensors_same_type in enumerate(
            number_sensors_each_type
        ):
            for repeat in range(number_sensors_same_type):
                uri_message_server = "nats://localhost:4222"
                match SensorTypesSupported(sensor_types[index_sensor]):
                    case SensorTypesSupported.INFRARED:
                        mock_sensor = SensorInfrared(
                            min_range_value, max_range_value, uri_message_server  # type: ignore
                        )
                    case SensorTypesSupported.ENVIRONMENTAL:
                        mock_sensor = SensorEnvironmental(
                            min_range_value, max_range_value, uri_message_server  # type: ignore
                        )

                # Append sensor to be mocked as tasks
                tasks.append(mock_sensor.run())

    app_multiple_sensor_reader = AppMultipleSensorReader(uri_db_server)
    tasks.append(app_multiple_sensor_reader.run())

    asyncio.run(run_concurrent_tasks(tasks))


if __name__ == "__main__":
    fire.Fire(main)
