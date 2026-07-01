from __future__ import annotations

import re
from typing import Literal, Any
from pydantic import BaseModel, Field

class DuplicateRow(BaseModel):
    row_index: int
    values: dict[str, str] = Field(default_factory=dict)

class DuplicateGroup(BaseModel):
    group_id: str
    match_type: Literal["exact", "fuzzy", "imdb_id"]
    similarity_score: float
    column_checked: str
    rows: list[DuplicateRow] = Field(default_factory=list)

class DuplicateReport(BaseModel):
    groups: list[DuplicateGroup] = Field(default_factory=list)
    total_duplicates: int = 0
    affected_rows: int = 0

class DuplicateDetector:
    def __init__(self) -> None:
        pass

    def detect_exact_duplicates(self, rows: list[dict[str, Any]], columns: list[str]) -> DuplicateReport:
        """Finds rows that are exact duplicates across a set of columns."""
        groups: list[DuplicateGroup] = []
        seen: dict[tuple, list[int]] = {}

        for idx, row in enumerate(rows):
            key = tuple(str(row.get(col, "")).strip().casefold() for col in columns)
            # If all are empty/blank, skip from deduplication mapping
            if not any(key):
                continue
            seen.setdefault(key, []).append(idx)

        group_counter = 1
        affected_indices = set()
        for key, indices in seen.items():
            if len(indices) > 1:
                duplicate_rows = []
                for idx in indices:
                    affected_indices.add(idx)
                    row_data = rows[idx]
                    duplicate_rows.append(DuplicateRow(
                        row_index=idx + 1,  # 1-indexed for spreadsheet representation
                        values={col: str(row_data.get(col, "")) for col in columns}
                    ))
                
                groups.append(DuplicateGroup(
                    group_id=f"exact_grp_{group_counter}",
                    match_type="exact",
                    similarity_score=1.0,
                    column_checked=", ".join(columns),
                    rows=duplicate_rows
                ))
                group_counter += 1

        return DuplicateReport(
            groups=groups,
            total_duplicates=sum(len(g.rows) for g in groups),
            affected_rows=len(affected_indices)
        )

    def detect_fuzzy_duplicates(self, rows: list[dict[str, Any]], title_column: str, threshold: float = 0.85) -> DuplicateReport:
        """Detects fuzzy duplicates in a specified column using string similarity heuristics."""
        groups: list[DuplicateGroup] = []
        affected_indices = set()
        checked_indices = set()
        group_counter = 1

        for i, row_a in enumerate(rows):
            if i in checked_indices:
                continue
            val_a = str(row_a.get(title_column, "")).strip()
            if not val_a:
                continue
                
            norm_a = _normalize_text(val_a)
            if not norm_a:
                continue

            current_group_rows = []
            group_best_sim = 0.0

            for j in range(i + 1, len(rows)):
                if j in checked_indices:
                    continue
                val_b = str(rows[j].get(title_column, "")).strip()
                if not val_b:
                    continue
                norm_b = _normalize_text(val_b)
                if not norm_b:
                    continue

                sim = _jaro_winkler(norm_a, norm_b)
                if sim >= threshold:
                    group_best_sim = max(group_best_sim, sim)
                    if not current_group_rows:
                        current_group_rows.append(DuplicateRow(
                            row_index=i + 1,
                            values={title_column: val_a}
                        ))
                        checked_indices.add(i)
                        affected_indices.add(i)
                    
                    current_group_rows.append(DuplicateRow(
                        row_index=j + 1,
                        values={title_column: val_b}
                    ))
                    checked_indices.add(j)
                    affected_indices.add(j)

            if current_group_rows:
                groups.append(DuplicateGroup(
                    group_id=f"fuzzy_grp_{group_counter}",
                    match_type="fuzzy",
                    similarity_score=round(group_best_sim, 4),
                    column_checked=title_column,
                    rows=current_group_rows
                ))
                group_counter += 1

        return DuplicateReport(
            groups=groups,
            total_duplicates=sum(len(g.rows) for g in groups),
            affected_rows=len(affected_indices)
        )

    def detect_by_id(self, rows: list[dict[str, Any]], id_column: str) -> DuplicateReport:
        """Finds rows that share the same non-empty identifier (e.g. IMDb ID)."""
        return self.detect_exact_duplicates(rows, [id_column])

def _normalize_text(text: str) -> str:
    cleaned = text.strip().casefold()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()

def _levenshtein_ratio(s1: str, s2: str) -> float:
    """Computes Levenshtein distance ratio between two strings (pure Python)."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    rows = len(s1) + 1
    cols = len(s2) + 1
    dist = [[0 for _ in range(cols)] for _ in range(rows)]

    for i in range(1, rows):
        dist[i][0] = i
    for k in range(1, cols):
        dist[0][k] = k

    for col in range(1, cols):
        for row in range(1, rows):
            if s1[row - 1] == s2[col - 1]:
                cost = 0
            else:
                cost = 1
            dist[row][col] = min(
                dist[row - 1][col] + 1,      # deletion
                dist[row][col - 1] + 1,      # insertion
                dist[row - 1][col - 1] + cost # substitution
            )

    max_len = max(len(s1), len(s2))
    return 1.0 - (dist[rows - 1][cols - 1] / max_len)

def _jaro_winkler(s1: str, s2: str) -> float:
    """Computes Jaro-Winkler similarity between two strings (pure Python)."""
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_bound = max(len1, len2) // 2 - 1
    if match_bound < 0:
        match_bound = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_bound)
        end = min(len2, i + match_bound + 1)
        for j in range(start, end):
            if not s2_matches[j] and s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    transpositions //= 2

    # Jaro Similarity
    jaro = (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0

    # Winkler modification (prefix matching)
    prefix_len = 0
    max_prefix = min(4, min(len1, len2))
    for i in range(max_prefix):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    # Winkler Scaling Factor is standard 0.1
    return jaro + prefix_len * 0.1 * (1.0 - jaro)
