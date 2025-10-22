import requests
import json

# -------------------------
# 환경 설정
# -------------------------
TEI_URL = "http://127.0.0.1:8081"       # Docker TEI 외부 포트
QDRANT_URL = "http://127.0.0.1:6333"    # Docker Qdrant 외부 포트
RAG_API_URL = "http://127.0.0.1:8000"   # RAG 서버 API 포트
OLLAMA_URL = "http://127.0.0.1:11434"   # 호스트 Ollama

COLLECTION_NAME = "test_docs"

# -------------------------
# 1️⃣ 샘플 문서 생성
# -------------------------
docs = [
    {
        "id": "doc1",
        "text": "The quick brown fox jumps over the lazy dog."
    },
    {
        "id": "doc2",
        "text": "OpenAI develops state-of-the-art AI models."
    }
]

# -------------------------
# 2️⃣ TEI 임베딩 생성
# -------------------------
def get_embeddings(text_list):
    payload = {"text": text_list}
    resp = requests.post(f"{TEI_URL}/embed", json=payload)
    resp.raise_for_status()
    return resp.json()["embeddings"]

embeddings = get_embeddings([d["text"] for d in docs])
print("✅ 임베딩 생성 완료")

# -------------------------
# 3️⃣ Qdrant에 벡터 저장
# -------------------------
def upsert_vectors(docs, embeddings):
    vectors = [
        {"id": d["id"], "vector": embeddings[i], "payload": {"text": d["text"]}}
        for i, d in enumerate(docs)
    ]
    payload = {"points": vectors}
    resp = requests.put(f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points?wait=true", json=payload)
    if resp.status_code == 404:
        # 컬렉션이 없는 경우 생성
        schema = {
            "name": COLLECTION_NAME,
            "vectors": {"size": len(embeddings[0]), "distance": "Cosine"}
        }
        requests.put(f"{QDRANT_URL}/collections/{COLLECTION_NAME}", json=schema)
        resp = requests.put(f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points?wait=true", json=payload)
    resp.raise_for_status()
    return resp.json()

upsert_vectors(docs, embeddings)
print("✅ Qdrant에 벡터 업로드 완료")

# -------------------------
# 4️⃣ RAG API 질의 테스트
# -------------------------
query = "Who develops AI models?"

payload = {
    "query": query,
    "top_k": 2
}

resp = requests.post(f"{RAG_API_URL}/rag/query", json=payload)
if resp.status_code == 200:
    result = resp.json()
    print("✅ RAG 질의 결과:")
    print(json.dumps(result, indent=2))
else:
    print("❌ RAG 질의 실패", resp.text)

# -------------------------
# 5️⃣ Ollama 직접 테스트 (optional)
# -------------------------
completion_payload = {
    "model": "gpt-oss:20b",
    "prompt": "Hello from test script",
    "max_tokens": 20
}

resp = requests.post(f"{OLLAMA_URL}/v1/completions", json=completion_payload)
if resp.status_code == 200:
    print("✅ Ollama 테스트 성공:", resp.json()["choices"][0]["text"])
else:
    print("❌ Ollama 테스트 실패", resp.text)
