import asyncio
import json

import nats
import numpy as np
from loguru import logger
from nats.aio.msg import Msg
from nats.errors import (
    ConnectionClosedError,
    NoRespondersError,
    NoServersError,
    TimeoutError,
)

from multiple_sensor_reader.data.custom_types import (
    ConfigEnvironmental,
    NatsUrl,
    PayloadEnvironmental,
    RegisterInfo,
    SensorTypesSupported,
)


class SensorEnvironmental:
    def __init__(
        self, min_range_value: int, max_range_value: int, uri_message_server: str
    ):
        data_resolution = 2**16
        assert (
            type(min_range_value) is int
        ), "'min_range_value' needed in case of mocked infrared sensor."
        assert (
            type(max_range_value) is int
        ), "'max_range_value' needed in case of mocked infrared sensor."

        assert (
            min_range_value >= 0 and min_range_value < data_resolution
        ), "'min_range_value' has to be positive and not exceed set sensor resolution 2^16."
        assert (
            max_range_value >= 0 and max_range_value < data_resolution
        ), "'max_range_value' has to be positive and not exceed set sensor resolution 2^16."

        self._min_value_range = min_range_value
        self._max_value_range = max_range_value
        self._last_data = np.random.randint(
            min_range_value, max_range_value + 1, size=64, dtype=np.uint16
        )

        self._timeout_requests = 5

        # Topics for communications
        self._topic_registering = "registering"
        self._topic_payload_data = "payload"
        self._topic_config = "config"

        # Main variables
        self._uri_message_server = NatsUrl(url=uri_message_server)
        self._id: int | None = None  # ID assigned by main app

        # Main configuration
        self.config = ConfigEnvironmental(**{"freq_update_data": 5.0, "param_2": 5})

    def set_config(self, config_data: ConfigEnvironmental):
        self.config = config_data

    async def connect_to_message_server(self):
        """Connect to NATS server."""
        flag_connected = False
        while not flag_connected:
            # Connect to local NATS server
            try:
                self.nats_client = await nats.connect(
                    self._uri_message_server.url,
                    connect_timeout=10,
                    error_cb=self.connect_errors_handler,
                )
                flag_connected = True
            except Exception as err:
                await asyncio.sleep(2)
                logger.debug(f"Cannot connect to NATS server: {err}")

    async def connect_errors_handler(
        self, err: ConnectionClosedError | NoServersError | TimeoutError
    ):
        logger.error(f"Mock sensor cannot connect to NATS message server: {err}")

    async def register_sensor_to_main_app(self):
        register_data = RegisterInfo(type=SensorTypesSupported.ENVIRONMENTAL)
        response = await self.nats_client.request(
            self._topic_registering,
            json.dumps(register_data.model_dump()).encode("utf-8"),
            timeout=self._timeout_requests,
        )

        # Get ID from response
        self._id = int(response.data.decode("utf-8"))

    async def handler_config_messages(self, msg: Msg):
        try:
            config_data = ConfigEnvironmental(**json.loads(msg.data.decode("utf-8")))
        except Exception as err:
            logger.error(f"Configuration data is not valid: {err}.")
            return

        # Check sent configuration is meant for this sensor
        if config_data.id == self.config.id:
            self.set_config(config_data)

    def generate_data_mock(self):
        # Mock sensor data readings as a random process
        # (probably not the real behaviour but enough for testing purposes)

        data = {}
        for field_name, model_field in PayloadEnvironmental.model_fields.items():
            match field_name:
                case "id":
                    data[field_name] = self._id
                case "temperature":
                    data[field_name] = np.random.uniform(
                        low=-50.0, high=50.0, size=(1, 1)
                    )[0][0]
                case "humidity":
                    data[field_name] = np.random.uniform(
                        low=1.0, high=10.0, size=(1, 1)
                    )[0][0]
                case "voc":
                    data[field_name] = np.random.randint(
                        self._min_value_range,
                        self._max_value_range + 1,
                        size=1,
                        dtype=np.uint16,
                    )
                case "nox":
                    data[field_name] = np.random.randint(
                        self._min_value_range,
                        self._max_value_range + 1,
                        size=3,
                        dtype=np.uint16,
                    )
                    data[field_name] = [data_list for data_list in data[field_name]]
                case "field_optional":
                    continue

        self._last_data = PayloadEnvironmental(**data)
        logger.debug(f"New sensor data generated: {self._last_data}")

        return self._last_data

    async def run(self):
        await self.connect_to_message_server()

        # Wait some time for the main app to be ready
        await asyncio.sleep(10)

        await self.register_sensor_to_main_app()

        # Subscribe to configuration topic to be able to receive update to config. parameters
        self.sub_registering = await self.nats_client.subscribe(
            self._topic_config, cb=self.handler_config_messages
        )

        while True:
            # Emulate new data reading and publish them at set frequency
            payload_data = self.generate_data_mock()
            await self.publish_data(payload_data)

            await asyncio.sleep(self.config.freq_update_data)

    async def publish_data(self, payload_data: PayloadEnvironmental):
        await self.nats_client.publish(
            self._topic_payload_data,
            json.dumps(payload_data.model_dump()).encode("utf-8"),
        )
