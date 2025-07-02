import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from langchain_community.document_loaders.confluence import ConfluenceLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# ========== 1. Load .env Variables ==========
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ES_URL = os.getenv("ELASTICSEARCH_URL")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
CONFLUENCE_API_KEY = os.getenv("RAG_API_KEY")

# ========== 2. Initialize Models ==========
embedding_dimension = 768  # Gemini embedding dim

embeddings_model = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GOOGLE_API_KEY
)

index_name = "confluence-index"

# ========== 3. Connect to Elasticsearch ==========
es = Elasticsearch(hosts=[ES_URL], api_key=ES_API_KEY)
if not es.ping():
    raise RuntimeError("❌ Could not connect to Elasticsearch")
print("✅ Connected to Elasticsearch")

# ========== 4. Load Document from Confluence ==========
loader = ConfluenceLoader(
    url="https://kumargmk25.atlassian.net/wiki",
    username="kumargmk25@gmail.com",
    api_key=CONFLUENCE_API_KEY,
    page_ids=["131194"]
)

print("📥 Loading documents from Confluence...")
docs = loader.load()
print(f"✅ Loaded {len(docs)} documents from Confluence")

# ========== 5. Recreate Index with Correct Mapping ==========
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)
    print(f"🗑️ Deleted old index '{index_name}'")

es.indices.create(index=index_name, body={
    "mappings": {
        "properties": {
            "content": {"type": "text"},
            "title": {"type": "text"},
            "embedding": {"type": "dense_vector", "dims": embedding_dimension}
        }
    }
})
print(f"✅ Recreated index '{index_name}' with correct mapping")

# ========== 6. Merge Content and Index as One Document ==========
from langchain_text_splitters import CharacterTextSplitter

splitter = CharacterTextSplitter(chunk_size=100, chunk_overlap=50)
chunks = splitter.split_documents(docs)

print(f"📄 Splitting into {len(chunks)} chunks for better retrieval...")

for i, chunk in enumerate(chunks):
    chunk_text = chunk.page_content
    chunk_title = chunk.metadata.get("title", f"Chunk-{i+1}")
    chunk_embedding = embeddings_model.embed_query(chunk_text)

    chunk_doc = {
        "title": chunk_title,
        "content": chunk_text,
        "embedding": chunk_embedding
    }

    es.index(index=index_name, id=f"confluence-doc-{i+1}", document=chunk_doc)

print(f"✅ Successfully indexed {len(chunks)} chunks.")

# ========== 7. Verify Indexed Document ==========
print("\n🔍 Verifying indexed document:")
try:
    result = es.get(index=index_name, id="confluence-doc-1")
    print(f"Title: {result['_source']['title']}")
    print(f"Content Snippet: {result['_source']['content'][:100]}...")
    print(f"Embedding size: {len(result['_source']['embedding'])}")
except Exception as e:
    print(f"❌ Failed to fetch document: {e}")
