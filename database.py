#!/usr/bin/env .venv/bin/python

import os
from pymongo import MongoClient, ReturnDocument
from dataclasses import dataclass
from config import GAME_CONFIGS
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# Database Config
# -------------------------
DB_CONNECTION = os.getenv("DB_CONNECTION", "mongodb")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", 27017))
DB_DATABASE = os.getenv("DB_DATABASE")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")

if DB_USERNAME and DB_PASSWORD:
    mongo_uri = f"{DB_CONNECTION}://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}?authSource=admin"
else:
    mongo_uri = f"{DB_CONNECTION}://{DB_HOST}:{DB_PORT}/{DB_DATABASE}"

# Connect once at module level
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
db = client[DB_DATABASE]

# -------------------------
# Load colors dynamically from env
# -------------------------
colors = {}
for key, value in os.environ.items():
    if key.isupper() and not key.startswith("DB_") and not key.startswith("PROVIDER_"):
        colors[key] = value.encode("utf-8").decode("unicode_escape")

# -------------------------
# Provider model
# -------------------------
@dataclass
class Provider:
    name: str
    initial: str
    color: str   # store color key as string
    hash: str

# -------------------------
# Load providers dynamically from env (store color key as string)
# -------------------------
provider_keys = [v for k, v in os.environ.items() if k.startswith("PROVIDER_") and k.endswith("_INITIAL")]

PROVIDERS = []
for initial in provider_keys:
    name = os.getenv(f"PROVIDER_{initial}_NAME").strip()
    color_key = os.getenv(f"PROVIDER_{initial}_COLOR").strip()  # keep as string key
    hash_ = os.getenv(f"PROVIDER_{initial}_HASH").strip()
    PROVIDERS.append(Provider(name=name, initial=initial, color=color_key, hash=hash_))

# -------------------------
# Seed PROVIDER collection
# -------------------------
def init_providers():
    col = db["PROVIDER"]
    col.create_index("initial", unique=True)
    for p in PROVIDERS:
        col.update_one(
            {"initial": p.initial},
            {"$setOnInsert": p.__dict__},
            upsert=True
        )
        
    print(f"{colors.get('LCYN','')}✅ PROVIDER collection seeded successfully{colors.get('RES','')}")

# -------------------------
# AUTO INCREMENT FUNCTION
# -------------------------
# def get_next_sequence(name):
#     counter = db["COUNTERS"].find_one_and_update(
#         {"_id": name},
#         {"$inc": {"seq": 1}},
#         upsert=True,
#         return_document=ReturnDocument.AFTER
#     )
#     return counter["seq"]

# -------------------------
# Seed GAME collection
# -------------------------
def init_games():
    games_col = db["GAME"]
    # games_col.create_index("name", unique=True)
    # games_col.create_index("_id", unique=True)

    for name, config in GAME_CONFIGS.items():
        doc = {
            # "_id": get_next_sequence("game_id"),
            "name": name,
            "id": config.id,
            "config": {k: v for k, v in config._asdict().items() if k != "provider"},
            "provider": config.provider
        }

        # games_col.update_one(
        #     {"name": name},
        #     {"$setOnInsert": doc},
        #     upsert=True
        # )
        
        # games_col.update_one(
        #     {"name": name},
        #     {"$set": doc},
        #     upsert=True
        # )

        games_col.insert_one(doc)

    print(f"{colors.get('LCYN','')}✅ GAME collection seeded successfully{colors.get('RES','')}")

# -------------------------
# Main (optional)
# -------------------------
if __name__ == "__main__":
    try:
        client.admin.command("ping")
        client.drop_database(DB_DATABASE) # reset datanase
        print(f"{colors.get('GRE','')}✅ MongoDB connection successful{colors.get('RES','')}")
        init_games()
        init_providers()
    except Exception as e:
        print(f"{colors.get('RED','')}✅ MongoDB connection successful{colors.get('RES','')}")
        exit(1)