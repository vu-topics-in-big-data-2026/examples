"""Reads IoT sensor data from CSV and streams it to a Kafka topic."""

import csv
import json
import os
import time

from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import NoBrokersAvailable, TopicAlreadyExistsError

BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
TOPIC = os.environ.get("TOPIC_NAME", "iot-sensors")
NUM_PARTITIONS = int(os.environ.get("NUM_PARTITIONS", "3"))
CSV_PATH = os.environ.get("CSV_PATH", "/data/sensors.csv")
MAX_RETRIES = int(os.environ.get("PRODUCER_MAX_RETRIES", "5"))
RETRY_DELAY = int(os.environ.get("PRODUCER_RETRY_DELAY", "5"))


def connect(broker: str, retries: int = MAX_RETRIES, delay: int = RETRY_DELAY) -> KafkaProducer:
    """Connect to Kafka broker with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=broker,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            print(f"Connected to broker {broker}")
            return producer
        except NoBrokersAvailable:
            print(f"Broker not available (attempt {attempt}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    raise SystemExit(f"Could not connect to broker {broker} after {retries} attempts")


def read_csv(path: str) -> list[dict]:
    """Read sensor data from CSV and return list of row dicts."""
    rows: list[dict] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "sensor_id": row["sensor_id"],
                "timestamp": row["timestamp"],
                "temperature_c": float(row["temperature_c"]),
                "humidity_pct": float(row["humidity_pct"]),
                "location": row["location"],
            })
    return rows


def ensure_topic(broker: str, topic: str, partitions: int) -> None:
    """Create the topic with multiple partitions if it doesn't exist."""
    try:
        admin = KafkaAdminClient(bootstrap_servers=broker)
        admin.create_topics([NewTopic(name=topic, num_partitions=partitions, replication_factor=1)])
        print(f"Created topic '{topic}' with {partitions} partitions")
        admin.close()
    except TopicAlreadyExistsError:
        print(f"Topic '{topic}' already exists")


def main() -> None:
    producer = connect(BROKER)
    ensure_topic(BROKER, TOPIC, NUM_PARTITIONS)
    rows = read_csv(CSV_PATH)
    print(f"Loaded {len(rows)} rows from {CSV_PATH}")
    print(f"Publishing to topic '{TOPIC}' on {BROKER}")
    try:
        while True:
            for row in rows:
                producer.send(TOPIC, key=row["sensor_id"].encode(), value=row)
                print(
                    f"Sent: {row['sensor_id']} | {row['location']} | "
                    f"{row['temperature_c']}C | {row['humidity_pct']}%"
                )
                time.sleep(1)
            print("Reached end of CSV, looping back to start...")
    except KeyboardInterrupt:
        print("Shutting down producer.")
    finally:
        producer.close()


if __name__ == "__main__":
    main()
