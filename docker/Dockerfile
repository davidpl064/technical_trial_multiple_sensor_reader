FROM ubuntu:22.04

ENV URI_DB_SERVER="127.0.0.1:5432"
ENV NUMBER_SENSOR_EACH_TYPE=2,1
ENV SENSOR_TYPES=0,1
ENV MIN_RANGE_VALUE=1
ENV MAX_RANGE_VALUE=5

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y software-properties-common

RUN add-apt-repository ppa:deadsnakes/ppa

# Pre-requisites
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install requirements
ADD ./requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

# Copy project files
WORKDIR /home/multiple_sensor_reader
COPY ./ ./app/
WORKDIR /home/multiple_sensor_reader/app

CMD python3 -m multiple_sensor_reader.app --uri_db_server $URI_DB_SERVER --number_sensors_each_type $NUMBER_SENSOR_EACH_TYPE --sensor_types $SENSOR_TYPES --min_range_value $MIN_RANGE_VALUE --max_range_value $MAX_RANGE_VALUE
