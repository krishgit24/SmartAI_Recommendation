import os

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.server_api import ServerApi


MONGODB_URL = os.getenv(
    "MONGODB_URL",
    "mongodb://localhost:27017"
)

client = MongoClient(
    MONGODB_URL,
    server_api=ServerApi("1"),
    serverSelectionTimeoutMS=5000
)

db = client["smart_recommendation"]

transactions = db["transactions"]
recommendations = db["recommendations"]
agent_audit_logs = db["agent_audit_logs"]
system_configs = db["system_configs"]


def initialize_database():
    client.admin.command("ping")

    transactions.create_index(
        [("transaction_id", ASCENDING)],
        unique=True
    )

    transactions.create_index(
        [("processing_status", ASCENDING),
         ("createdAt", DESCENDING)]
    )

    recommendations.create_index(
        [("transaction_id", ASCENDING),
         ("createdAt", DESCENDING)]
    )

    recommendations.create_index(
        [("recommendation", ASCENDING),
         ("createdAt", DESCENDING)]
    )

    agent_audit_logs.create_index(
        [("execution_id", ASCENDING)],
        unique=True
    )

    agent_audit_logs.create_index(
        [("transaction_id", ASCENDING),
         ("createdAt", DESCENDING)]
    )

    system_configs.create_index(
        [("config_key", ASCENDING)],
        unique=True
    )

    system_configs.update_one(
        {"config_key": "retry_engine"},
        {
            "$setOnInsert": {
                "config_key": "retry_engine",
                "kill_switch_enabled": False,
                "max_retry_count": 3,
                "max_agent_attempts": 3,
                "max_agent_loops": 5,
                "updated_by": "system"
            }
        },
        upsert=True
    )

    print("MongoDB connected and initialized successfully.")


if __name__ == "__main__":
    initialize_database()