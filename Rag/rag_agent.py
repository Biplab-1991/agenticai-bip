import cohere
from elasticsearch import Elasticsearch
import numpy as np

# ========== 1. Setup Cohere + Elasticsearch ==========

COHERE_API_KEY = "UdZqKmf7IqpY0Z4hmWxnZxNXp24a24Uh6tTYWWko"
co = cohere.Client(COHERE_API_KEY)

es = Elasticsearch(
    hosts=["https://09770d0628534211837e04cdb6a4ca77.us-central1.gcp.cloud.es.io:443"],
    basic_auth=("elastic", "Ea7BjmAxqDcA7bTovwffGpYl"),
    verify_certs=True
)

# ========== 2. Get Embeddings from Cohere ==========

def get_embedding(text):
    response = co.embed(
        texts=[text],
        model="embed-english-v3.0",  # This model returns 1024-dim embeddings
        input_type="search_query"
    )
    return response.embeddings[0]

# ========== 3. Query Elasticsearch with Cosine Similarity ==========

def retrieve_chunks(index_name, query, top_k=3):
    query_vector = get_embedding(query)

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

    return [
        {
            "content": hit["_source"]["content"],
            "score": hit["_score"],
            "meta": {
                k: v for k, v in hit["_source"].items()
                if k not in ["content", "embedding"]
            }
        }
        for hit in hits
    ]

# ========== 4. Generate Answer with Cohere LLM ==========

def generate_answer(query, chunks):
    context = "\n---\n".join([
        f"{c['content']} (source: {c['meta'].get('title') or c['meta'].get('source')})"
        for c in chunks
    ])

    prompt = f"""You are a helpful assistant. Use the context below to answer the user's question. If you are not getting any relevant information, say "Sorry I don't have a direct answer to your question, please specify more to understand better".

### Context:
{context}

### Question:
{query}

### Answer:"""

    response = co.generate(
        model="command-r-plus",
        prompt=prompt,
        temperature=0.3,
        max_tokens=300
    )
    return response.generations[0].text.strip()

# ========== 5. Full RAG Pipeline ==========

def rag_pipeline(query, index_name, k=3):
    retrieved = retrieve_chunks(index_name, query, top_k=k)
    answer = generate_answer(query, retrieved)
    return {
        "answer": answer,
        "chunks": retrieved
    }

# ========== 6. Example ==========

if __name__ == "__main__":
    user_query = "Tell me about rajesh."
    response = rag_pipeline(user_query, index_name="test-search", k=3)

    print("\n🔍 Top Retrieved Chunks:")
    for idx, chunk in enumerate(response["chunks"], 1):
        print(f"{idx}. {chunk['content'][:100]}...")

    print("\n🤖 Final Answer:\n", response["answer"]) 