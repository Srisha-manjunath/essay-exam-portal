import pymongo

MONGODB_URI = "mongodb://localhost:27017/"
DB_NAME = "exam_portal"

try:
    client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    print("✅ Connected to MongoDB")
    print("Databases available:", client.list_database_names())
except Exception as e:
    print("❌ Connection failed:", e)
