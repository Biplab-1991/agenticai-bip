from langchain_core.tools import tool
from elasticsearch import Elasticsearch
from dotenv import load_dotenv
import os

load_dotenv()

ES_URL = os.getenv("ELASTICSEARCH_URL")
ES_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")

# Initialize Elasticsearch client
es = Elasticsearch(
    hosts=[ES_URL],
    api_key=ES_API_KEY
)

@tool
def keyword_search_tool(query: str, index_name: str = "confluence-index", top_k: int = 5) -> str:
    """Search Elasticsearch using plain keyword matching (no embeddings)."""
    try:
        body = {
            "size": top_k,
            "query": {
                "match": {
                    "content": {
                        "query": query,
                        "operator": "and"  # all keywords must match
                    }
                }
            }
        }

        response = es.search(index=index_name, body=body)
        hits = response["hits"]["hits"]

        if not hits:
            return "No matching content found using keyword search."

        results = []
        for hit in hits:
            score = hit["_score"]
            title = hit["_source"].get("title", "No Title")
            snippet = hit["_source"].get("content", "")[:300]
            results.append(f"📄 {title}\n🔍 Score: {score:.2f}\n📝 Snippet: {snippet}...\n")

        return "\n".join(results)

    except Exception as e:
        return f"Error during keyword search: {e}"
