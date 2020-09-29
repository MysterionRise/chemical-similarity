PUT pubchem
{
  "settings": {
    "index": {
      "number_of_shards": 1,
      "number_of_replicas": 0
    },
    "refresh_interval": "5m"
  },
  "mappings": {
    "properties": {
      "fingerprint": {
        "type": "keyword",
        "similarity": "boolean"
      },
      "fingerprint_len": {
        "type": "short"
      },
      "smiles": {
        "type": "text",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 256
          }
        }
      }
    }
  }
}