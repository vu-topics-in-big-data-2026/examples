"""Consumes IoT sensor readings and flags temperature anomalies."""

import json
import os
import time

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
TOPIC = os.environ.get("TOPIC_NAME", "iot-sensors")
TEMP_HIGH = float(os.environ.get("TEMP_HIGH_THRESHOLD", "40.0"))
TEMP_LOW = float(os.environ.get("TEMP_LOW_THRESHOLD", "5.0"))
GROUP_ID = os.environ.get("GROUP_ID", "iot-analyzers")
MAX_RETRIES = int(os.environ.get("CONSUMER_MAX_RETRIES", "5"))
RETRY_DELAY = int(os.environ.get("CONSUMER_RETRY_DELAY", "5"))


def connect(broker: str, topic: str, retries: int = MAX_RETRIES, delay: int = RETRY_DELAY) -> KafkaConsumer:
    """Connect to Kafka broker with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=broker,
                group_id=GROUP_ID,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
            )
            print(f"Connected to broker {broker}, consuming topic '{topic}'")
            return consumer
        except NoBrokersAvailable:
            print(f"Broker not available (attempt {attempt}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    raise SystemExit(f"Could not connect to broker {broker} after {retries} attempts")


def main() -> None:
    consumer = connect(BROKER, TOPIC)
    print(f"Temperature thresholds: LOW < {TEMP_LOW}C | HIGH > {TEMP_HIGH}C")
    try:
        for message in consumer:
            reading = message.value
            temp = reading.get("temperature_c", 0.0)
            sensor = reading.get("sensor_id", "unknown")
            location = reading.get("location", "unknown")
            humidity = reading.get("humidity_pct", 0.0)

            if temp > TEMP_HIGH:
                print(
                    f"ANOMALY HIGH: {sensor} | {location} | "
                    f"{temp}C (> {TEMP_HIGH}C) | humidity {humidity}%"
                )
            elif temp < TEMP_LOW:
                print(
                    f"ANOMALY LOW:  {sensor} | {location} | "
                    f"{temp}C (< {TEMP_LOW}C) | humidity {humidity}%"
                )
            else:
                print(f"OK:           {sensor} | {location} | {temp}C | humidity {humidity}%")
    except KeyboardInterrupt:
        print("Shutting down analyzer.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
