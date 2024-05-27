import re
from enum import Enum, IntEnum
from urllib.parse import urlparse

import numpy as np
from pydantic import BaseModel, model_validator
from pydantic.networks import IPvAnyAddress


class AppCommandActions(Enum):
    """Enum class to define command actions to set AppSensorReader state."""

    START: int = 0
    STOP: int = 1
    SEND_CONFIG: int = 2
    EXIT: int = 3


class SensorTypesSupported(IntEnum):
    INFRARED = 0
    ENVIRONMENTAL = 1
    LIDAR = 2


class RegisterInfo(BaseModel):
    type: SensorTypesSupported


class ConfigInfrared(BaseModel):
    id: int | None = None
    freq_update_data: float
    param_2: int


class ConfigEnvironmental(BaseModel):
    id: int | None = None
    freq_update_data: float
    param_2: int
    param_3: str | None = None


class ConfigLidar(BaseModel):
    id: int
    freq_update_data: float
    param_2: int
    param_3: list
    param_4: str
    param_optional_5: list | None = None


class Command(BaseModel):
    type: AppCommandActions
    data: ConfigInfrared | ConfigEnvironmental | ConfigLidar | None = None


class PayloadInfrared(BaseModel):
    id: int
    values: list[int]
    field_optional: str | None = None


class PayloadEnvironmental(BaseModel):
    id: int
    temperature: float
    humidity: float
    voc: int  # [ppm]
    nox: list[int]  # [ppm]
    field_optional: str | None = None


class PayloadLidar(BaseModel):
    id: int
    range: float
    field_2: list[float]
    field_3: dict
    field_optional_4: str | None = None
    field_optional_5: int | None = None


class Sensor(BaseModel):
    id: int | None = None
    type: SensorTypesSupported
    config: None = None
    payload: PayloadInfrared | PayloadEnvironmental | None = None


class UrlConstraints(BaseModel):
    """Class model to define generic URLs format parameters."""

    max_length: int = 2083
    allowed_schemes: list = ["nats"]


class NatsUrl(BaseModel):
    """Class model to define NATS URLs."""

    url: str

    @model_validator(mode="after")
    def _validate_format(self):
        constraints = UrlConstraints(max_length=2083, allowed_schemes=["nats"])
        if len(self.url) > constraints.max_length:
            raise ValueError("URL length exceeds max. limit.")

        # Parse the URL to get components
        parsed_url = urlparse(self.url)

        if parsed_url.scheme not in constraints.allowed_schemes:
            raise ValueError("URL header is incorrect. Must be nats://.")

        # Check if there's an IP and port in the netloc
        if ":" in parsed_url.netloc:
            ip, port = parsed_url.netloc.split(":")

            # Validate IP
            ip = ip.strip()
            ip_pattern = re.compile(
                r"^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\."
                r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\."
                r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\."
                r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
            )
            flag_valid_ip = bool(ip_pattern.match(ip) or ip == "localhost")

            if not flag_valid_ip:
                raise ValueError("Invalid IP format.")

            # Validate port
            port = int(port)
            if not (0 <= port <= 65535):
                raise ValueError("Port must be between 0 and 65535.")

            return self
        # If no IP and port are found, raise an error
        raise ValueError("Invalid IP or port.")


class IPAddressWithPort(BaseModel):
    """Class model to define addresses defined by combination of IP and port."""

    uri: str
    ip: IPvAnyAddress | None = None
    port: int | None = None

    @model_validator(mode="after")
    def _validate_uri(self):
        if ":" in self.uri:
            ip, port = self.uri.split(":")

            # Validate IP
            ip = ip.strip()
            try:
                IPvAnyAddress._validate(ip)
            except ValueError:
                if ip != "localhost":
                    raise ValueError("Invalid IP address or localhost")

            # Validate port
            port = int(port)
            if not (0 <= port <= 65535):
                raise ValueError("Port must be between 0 and 65535.")

            self.ip, self.port = ip, port
            return self

        # If no IP and port are found, raise an error
        raise ValueError("Invalid IP or port.")
