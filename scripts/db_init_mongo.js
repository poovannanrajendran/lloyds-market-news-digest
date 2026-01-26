const dbName = process.env.MONGO_DB_NAME || "lloyds_digest_raw";

db = db.getSiblingDB(dbName);

// Raw discovery snapshots
if (!db.getCollectionNames().includes("discovery_snapshots")) {
  db.createCollection("discovery_snapshots");
}

// Fetch cache
if (!db.getCollectionNames().includes("fetch_cache")) {
  db.createCollection("fetch_cache");
}

// Attempts (raw)
if (!db.getCollectionNames().includes("attempts_raw")) {
  db.createCollection("attempts_raw");
}

// Winners
if (!db.getCollectionNames().includes("winners")) {
  db.createCollection("winners");
}

// AI cache
if (!db.getCollectionNames().includes("ai_cache")) {
  db.createCollection("ai_cache");
}

db.fetch_cache.createIndex({ key: 1 }, { unique: true });
db.attempts_raw.createIndex({ created_at: -1 });
db.winners.createIndex({ key: 1 }, { unique: true });
db.ai_cache.createIndex({ key: 1 }, { unique: true });
