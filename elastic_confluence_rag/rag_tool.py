from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from elasticsearch import Elasticsearch
import os
from dotenv import load_dotenv

load_dotenv()

ES_URL = os.getenv("ELASTICSEARCH_URL")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

embedding_model = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GOOGLE_API_KEY
)

es = Elasticsearch(
    hosts=[ES_URL],
    api_key=ES_API_KEY
)

@tool
def rag_search_tool(query: str, index_name: str = "confluence-index", top_k: int = 8) -> str:
    """Semantic search over Elasticsearch using Gemini embeddings. Answers based on indexed documents."""
    try:
        query_vector = embedding_model.embed_query(query)
        body = {
            "size": top_k,
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                        "params": {"query_vector": query_vector}
                    }
                }
            }
        }

        results = es.search(index=index_name, body=body)
        hits = results["hits"]["hits"]

        if not hits:
            return "No relevant documents found in Elasticsearch."

        response = []
        for hit in hits:
            score = hit["_score"]
            title = hit["_source"].get("title", "No Title")
            content = hit["_source"].get("content", "")[:300]
            response.append(f"📄 Title: {title}\n🔍 Score: {score:.2f}\n📝 Snippet: {content}...\n")

        return "\n".join(response)

    except Exception as e:
        return f"[Error] while querying Elasticsearch: {e}"
