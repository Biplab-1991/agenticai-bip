# ingest_confluence_chunks.py

import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from langchain_community.document_loaders.confluence import ConfluenceLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

# 1. Load environment variables
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ES_URL = os.getenv("ELASTICSEARCH_URL")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
CONFLUENCE_API_KEY = os.getenv("RAG_API_KEY")

# 2. Setup Elasticsearch client
es = Elasticsearch(hosts=[ES_URL], api_key=ES_API_KEY)
if not es.ping():
    raise RuntimeError("❌ Could not connect to Elasticsearch")
print("✅ Connected to Elasticsearch")

# 3. Gemini embedding model
embedding_model = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GOOGLE_API_KEY
)
embedding_dimension = 768
index_name = "confluence-index"

# 4. Load documents from Confluence
loader = ConfluenceLoader(
    url="https://kumargmk25.atlassian.net/wiki",
    username="kumargmk25@gmail.com",
    api_key=CONFLUENCE_API_KEY,
    page_ids=["131194"]
)
print("📥 Loading documents from Confluence...")
raw_docs = loader.load()
print(f"✅ Loaded {len(raw_docs)} documents from Confluence")

# 5. Split content into smaller chunks
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100,
    length_function=len,
    is_separator_regex=False
)
chunked_docs = splitter.split_documents(raw_docs)
print(f"✂️ Split into {len(chunked_docs)} chunks")

# 6. Recreate the index with mapping
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)
    print(f"🗑️ Deleted old index '{index_name}'")

mapping = {
    "properties": {
        "content": {"type": "text"},
        "title": {"type": "text"},
        "embedding": {
            "type": "dense_vector",
            "dims": embedding_dimension,
            "index": True,
            "similarity": "cosine"
        }
    }
}
es.indices.create(index=index_name, mappings=mapping)
print(f"📦 Created index '{index_name}' with dense vector support")

# 7. Generate embeddings and prepare for bulk ingestion
actions = []
for i, chunk in enumerate(chunked_docs):
    content = chunk.page_content
    embedding = embedding_model.embed_query(content)
    title = chunk.metadata.get("title", "Untitled")

    doc = {
        "_index": index_name,
        "_id": f"chunk_{i}",
        "_source": {
            "content": content,
            "title": title,
            "embedding": embedding
        }
    }
    actions.append(doc)

# 8. Bulk ingest
print("🚀 Ingesting chunks into Elasticsearch...")
success, failed = helpers.bulk(es, actions, index=index_name, refresh="wait_for")
print(f"✅ Ingested {success} documents successfully.")
if failed:
    print(f"❌ {len(failed)} documents failed to ingest.")

# 9. Sample check
print("\n🔎 Sample document:")
doc = es.get(index=index_name, id="chunk_0")["_source"]
print(f"Title: {doc['title']}")
print(f"Content Snippet: {doc['content'][:100]}...")
print(f"Embedding size: {len(doc['embedding'])}")
