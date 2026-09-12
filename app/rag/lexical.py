"""增量 BM25：仅为新文档分词，维护词频、文档频率与倒排表。"""
import logging
import math
from collections import Counter, defaultdict
from threading import RLock

import jieba

jieba.setLogLevel(logging.WARNING)


def tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Index:
    """使用正值 Robertson IDF，避免小语料负分导致零召回。"""

    def __init__(self):
        self._corpus = []
        self._lengths = []
        self._postings = defaultdict(dict)
        self._total_length = 0
        self._lock = RLock()
        self.k1, self.b = 1.5, 0.75

    @property
    def ready(self):
        with self._lock:
            return bool(self._postings)

    @staticmethod
    def prepare(texts):
        return [(text, Counter(tokenize(text))) for text in texts]

    def add_prepared(self, prepared):
        with self._lock:
            for text, counts in prepared:
                index = len(self._corpus)
                length = sum(counts.values())
                self._corpus.append(text)
                self._lengths.append(length)
                self._total_length += length
                for term, freq in counts.items():
                    self._postings[term][index] = freq

    def add_documents(self, texts):
        self.add_prepared(self.prepare(texts))

    def search(self, query, top_k):
        with self._lock:
            n = len(self._corpus)
            if not n or not self._total_length or top_k <= 0:
                return []
            avg = self._total_length / n
            scores = defaultdict(float)
            for term in tokenize(query):
                postings = self._postings.get(term, {})
                df = len(postings)
                idf = math.log1p((n - df + 0.5) / (df + 0.5))
                for index, freq in postings.items():
                    norm = self.k1 * (1 - self.b + self.b * self._lengths[index] / avg)
                    scores[index] += idf * freq * (self.k1 + 1) / (freq + norm)
            return sorted(scores, key=lambda i: (-scores[i], i))[:top_k]
