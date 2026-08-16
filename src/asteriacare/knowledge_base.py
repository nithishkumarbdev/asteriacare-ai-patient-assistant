"""Lightweight retriever over the clinic knowledge base.

Real deployments would back this with a vector store (pgvector, Pinecone,
whatever's already in the stack). This implementation is intentionally
dependency-free — TF-style keyword scoring over markdown documents — so the
whole project runs with `pip install -r requirements.txt` and one API key.
The retrieval *interface* (`retrieve(query, k)`) is what the agent depends
on, so swapping in a real vector store later means changing this file only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    source: str
    heading: str
    text: str


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _split_into_chunks(path: Path) -> list[Chunk]:
    """Split a markdown file into chunks on '## ' headings."""
    raw = path.read_text(encoding="utf-8")
    sections = re.split(r"\n(?=## )", raw)
    chunks: list[Chunk] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading_match = re.match(r"##\s+(.*)", section)
        heading = heading_match.group(1) if heading_match else path.stem
        chunks.append(Chunk(source=path.name, heading=heading, text=section))
    return chunks


class KnowledgeBase:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._chunks: list[Chunk] = []
        self._load()

    def _load(self) -> None:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.md")):
            self._chunks.extend(_split_into_chunks(path))

    def retrieve(self, query: str, k: int = 3) -> list[Chunk]:
        """Return the top-k chunks by token overlap with the query.

        Simple and explainable on purpose — no embedding model, no external
        service, easy to unit test deterministically.
        """
        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []

        scored: list[tuple[float, Chunk]] = []
        for chunk in self._chunks:
            chunk_tokens = _tokenize(chunk.text)
            if not chunk_tokens:
                continue
            overlap = sum(1 for t in chunk_tokens if t in query_tokens)
            if overlap == 0:
                continue
            score = overlap / len(chunk_tokens) ** 0.5  # mild length normalization
            scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [chunk for _, chunk in scored[:k]]

    def format_for_prompt(self, chunks: list[Chunk]) -> str:
        if not chunks:
            return "(no matching knowledge base content found)"
        return "\n\n".join(
            f"[{c.source} — {c.heading}]\n{c.text}" for c in chunks
        )
