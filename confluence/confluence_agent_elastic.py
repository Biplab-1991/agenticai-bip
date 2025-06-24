import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from langchain_community.document_loaders.confluence import ConfluenceLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Load .env
load_dotenv()

# Load env variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ES_URL = os.getenv("ELASTICSEARCH_URL")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")

# Initialize Google Embedding model
embeddings_model = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GOOGLE_API_KEY
)

embedding_dimension = 768  # Fixed for Gemini embeddings
index_name = "gemini-confluence-index"

# Connect to Elasticsearch
es = Elasticsearch(hosts=[ES_URL], api_key=ES_API_KEY)

if not es.ping():
    raise RuntimeError("Could not connect to Elasticsearch")

print("✅ Connected to Elasticsearch")

# Load documents from Confluence
loader = ConfluenceLoader(
    url="https://baislaakshay13.atlassian.net/wiki",
    username="baisla.akshay13@gmail.com",
    api_key="",
    space_key="VZagentica"
)

print("📥 Loading documents from Confluence...")
docs = loader.load()
print(f"✅ Loaded {len(docs)} documents")

# Create index if not exists
if not es.indices.exists(index=index_name):
    es.indices.create(index=index_name, body={
        "mappings": {
            "properties": {
                "content": {"type": "text"},
                "title": {"type": "text"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dimension
                }
            }
        }
    })
    print(f"✅ Created index '{index_name}'")

# Prepare and index documents
print("⚙️ Generating embeddings and preparing for indexing...")

actions = []
# for i, doc in enumerate(docs):
#     content = doc.page_content
#     title = doc.metadata.get("title", f"doc-{i+1}")
#     embedding = embeddings_model.embed_query(content)

#     doc_id = f"confluence-doc-{i+1}"

#     actions.append({
#         "_index": index_name,
#         "_id": doc_id,
#         "_source": {
#             "title": title,
#             "content": content,
#             "embedding": embedding
#         }
#     })

# helpers.bulk(es, actions, refresh=True)
# print(f"✅ Successfully indexed {len(actions)} documents to '{index_name}'")

docs = loader.load()
print(f"Loaded {len(docs)} Confluence documents.")

# 2. Merge all page contents into one long string
merged_content = "\n\n".join(doc.page_content for doc in docs)
merged_title = "Merged_Confluence_Document"

# 3. Generate embedding for the merged content
embedding = embeddings_model.embed_query(merged_content)

# 4. Prepare a single document for Elasticsearch
merged_document = {
    "id": "confluence_merged_doc_1",
    "title": merged_title,
    "content": merged_content,
    "embedding": embedding
}

# 5. Index it
try:
    es.index(index="confluence-index", id=merged_document["id"], document=merged_document)
    print("Successfully indexed merged document.")
except Exception as e:
    print(f"Error indexing merged document: {e}")

# Test one
print("\n🔍 Verifying first document:")
try:
    result = es.get(index=index_name, id="confluence-doc-1")
    print(f"Title: {result['_source']['title']}")
    print(f"Content Snippet: {result['_source']['content'][:100]}...")
    print(f"Embedding size: {len(result['_source']['embedding'])}")
except Exception as e:
    print(f"Failed to fetch document: {e}")
 