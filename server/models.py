from pydantic import BaseModel
from typing import List, Optional

class IndexRequest(BaseModel):
    repo_path: str
    branch: Optional[str] = None
    languages: Optional[List[str]] = None

class SearchRequest(BaseModel):
    query: str
    k: int = 8
    repo: Optional[str] = None

class IssueAnalyzeRequest(BaseModel):
    question: str
    k: int = 16
    repo: Optional[str] = None

class Snippet(BaseModel):
    file: str
    start: int
    end: int
    lang: str
    text: str
    score: float

class SearchResponse(BaseModel):
    hits: List[Snippet]