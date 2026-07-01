from __future__ import annotations

import re
from typing import Literal, Any
from pydantic import BaseModel, Field

class RowHealthScore(BaseModel):
    overall_score: float
    completeness: float
    format_score: float
    consistency: float
    uniqueness: float
    issues: list[str] = Field(default_factory=list)
    grade: Literal["A", "B", "C", "D", "F"]

class WorkbookHealthReport(BaseModel):
    overall_score: float
    grade: Literal["A", "B", "C", "D", "F"]
    average_completeness: float
    average_format: float
    average_consistency: float
    average_uniqueness: float
    total_rows_checked: int = 0
    worst_columns: list[str] = Field(default_factory=list)
    best_columns: list[str] = Field(default_factory=list)
    grade_distribution: dict[str, int] = Field(default_factory=dict)

DEFAULT_FIELD_WEIGHTS = {
    "title": 1.0,
    "TV Show/Movie": 1.0,
    "primary_genre": 0.8,
    "genre": 0.8,
    "released_on": 0.8,
    "imdb_id": 1.0,
    "wikipedia_url": 0.7,
    "network": 0.6,
    "platform": 0.6
}

class MetadataHealthScorer:
    def __init__(self) -> None:
        pass

    def score_row(self, row: dict[str, Any], field_weights: dict[str, float] | None = None) -> RowHealthScore:
        """Scores a single row based on metadata completeness, formats, and consistency."""
        weights = field_weights or DEFAULT_FIELD_WEIGHTS
        issues = []

        # 1. Completeness Score
        total_weight = 0.0
        filled_weight = 0.0
        for col, weight in weights.items():
            # Check if column exists in row
            matching_keys = [k for k in row.keys() if k.casefold() == col.casefold()]
            if matching_keys:
                total_weight += weight
                val = str(row[matching_keys[0]] or "").strip()
                if val and val.casefold() != r"\n" and val.casefold() != "nan":
                    filled_weight += weight
                else:
                    issues.append(f"Missing required field: '{col}'")
                    
        completeness = (filled_weight / total_weight * 100.0) if total_weight > 0 else 100.0

        # 2. Format Score
        format_checks = 0
        passed_format = 0
        
        # Check URLs
        url_cols = [k for k in row.keys() if "url" in k.casefold() or "link" in k.casefold()]
        for col in url_cols:
            val = str(row[col] or "").strip()
            if val:
                format_checks += 1
                if _validate_url_format(val):
                    passed_format += 1
                else:
                    issues.append(f"Invalid URL format in '{col}': {val}")

        # Check IMDb ID
        imdb_cols = [k for k in row.keys() if "imdb" in k.casefold()]
        for col in imdb_cols:
            val = str(row[col] or "").strip()
            if val:
                format_checks += 1
                if _validate_imdb_id(val):
                    passed_format += 1
                else:
                    issues.append(f"Invalid IMDb ID format in '{col}': {val}")

        # Check Dates
        date_cols = [k for k in row.keys() if "date" in k.casefold() or "released" in k.casefold()]
        for col in date_cols:
            val = str(row[col] or "").strip()
            if val:
                format_checks += 1
                if _validate_date_format(val):
                    passed_format += 1
                else:
                    issues.append(f"Invalid date format in '{col}': {val}")

        format_score = (passed_format / format_checks * 100.0) if format_checks > 0 else 100.0

        # 3. Consistency Score
        consistency_checks = 0
        passed_consistency = 0

        # Release year should match released date
        year_keys = [k for k in row.keys() if "year" in k.casefold()]
        rel_keys = [k for k in row.keys() if "released" in k.casefold() or "street" in k.casefold()]
        if year_keys and rel_keys:
            yr_val = str(row[year_keys[0]] or "").strip()
            rel_val = str(row[rel_keys[0]] or "").strip()
            if yr_val and rel_val and len(rel_val) >= 4:
                consistency_checks += 1
                if yr_val in rel_val:
                    passed_consistency += 1
                else:
                    issues.append(f"Year '{yr_val}' does not match release date year in '{rel_val}'")

        # Genres list format (should not have raw formatting tags, trailing newlines)
        genre_keys = [k for k in row.keys() if "genre" in k.casefold()]
        for gk in genre_keys:
            val = str(row[gk] or "").strip()
            if val:
                consistency_checks += 1
                if "\n" in val or "   " in val:
                    issues.append(f"Formatting placeholder issues found in genre field: '{gk}'")
                else:
                    passed_consistency += 1

        # Movie-specific release window and trailer date sequencing consistency checks
        theatrical_keys = [k for k in row.keys() if "theatrical" in k.casefold() or "release_date" in k.casefold()]
        digital_keys = [k for k in row.keys() if "digital" in k.casefold() or "vod" in k.casefold() or "streaming" in k.casefold()]
        trailer_keys = [k for k in row.keys() if "trailer_release" in k.casefold() or "trailer_date" in k.casefold()]

        if theatrical_keys and digital_keys:
            theat_val = str(row[theatrical_keys[0]] or "").strip()
            dig_val = str(row[digital_keys[0]] or "").strip()
            if theat_val and dig_val and theat_val != "nan" and dig_val != "nan":
                # Compare YYYY-MM-DD
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", theat_val) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dig_val):
                    consistency_checks += 1
                    if theat_val <= dig_val:
                        passed_consistency += 1
                    else:
                        issues.append(f"Theatrical date '{theat_val}' is after Digital date '{dig_val}' in row.")

        if theatrical_keys and trailer_keys:
            theat_val = str(row[theatrical_keys[0]] or "").strip()
            trail_val = str(row[trailer_keys[0]] or "").strip()
            if theat_val and trail_val and theat_val != "nan" and trail_val != "nan":
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", theat_val) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", trail_val):
                    consistency_checks += 1
                    if trail_val <= theat_val:
                        passed_consistency += 1
                    else:
                        issues.append(f"Trailer date '{trail_val}' is after Theatrical date '{theat_val}' in row.")

        consistency = (passed_consistency / consistency_checks * 100.0) if consistency_checks > 0 else 100.0

        # 4. Uniqueness Score
        # For a single row, it starts at 100. It is adjusted at sheet level
        uniqueness = 100.0

        # Weights: Completeness (35%), Format (25%), Consistency (20%), Uniqueness (20%)
        overall = (completeness * 0.35) + (format_score * 0.25) + (consistency * 0.20) + (uniqueness * 0.20)
        grade = _get_grade(overall)

        return RowHealthScore(
            overall_score=round(overall, 2),
            completeness=round(completeness, 2),
            format_score=round(format_score, 2),
            consistency=round(consistency, 2),
            uniqueness=round(uniqueness, 2),
            issues=issues,
            grade=grade
        )

    def score_workbook(self, rows: list[dict[str, Any]], field_weights: dict[str, float] | None = None) -> WorkbookHealthReport:
        """Computes aggregate health report for a list of row dicts."""
        if not rows:
            return WorkbookHealthReport(
                overall_score=0.0,
                grade="F",
                average_completeness=0.0,
                average_format=0.0,
                average_consistency=0.0,
                average_uniqueness=0.0
            )

        row_scores = []
        
        # Calculate Uniqueness at workbook level
        # Track duplicate IDs
        seen_ids = {}
        id_keys = []
        if rows:
            id_keys = [k for k in rows[0].keys() if "imdb" in k.casefold() or "id" in k.casefold()]

        for r_idx, row in enumerate(rows):
            for id_key in id_keys:
                val = str(row.get(id_key) or "").strip()
                if val:
                    seen_ids.setdefault((id_key, val), []).append(r_idx)

        # Compute individual row scores
        for r_idx, row in enumerate(rows):
            score = self.score_row(row, field_weights)
            
            # Adjust uniqueness if ID is duplicated
            duplicate_penalty = False
            for id_key in id_keys:
                val = str(row.get(id_key) or "").strip()
                if val and len(seen_ids.get((id_key, val), [])) > 1:
                    duplicate_penalty = True
                    score.issues.append(f"Duplicate identifier found in '{id_key}': '{val}'")
            
            if duplicate_penalty:
                score.uniqueness = 50.0
                score.overall_score = round(
                    (score.completeness * 0.35) + 
                    (score.format_score * 0.25) + 
                    (score.consistency * 0.20) + 
                    (score.uniqueness * 0.20), 2
                )
                score.grade = _get_grade(score.overall_score)
                
            row_scores.append(score)

        # Aggregates
        total = len(rows)
        avg_comp = sum(s.completeness for s in row_scores) / total
        avg_format = sum(s.format_score for s in row_scores) / total
        avg_const = sum(s.consistency for s in row_scores) / total
        avg_uniq = sum(s.uniqueness for s in row_scores) / total

        overall_avg = (avg_comp * 0.35) + (avg_format * 0.25) + (avg_const * 0.20) + (avg_uniq * 0.20)

        # Grade distribution
        grades = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for s in row_scores:
            grades[s.grade] += 1

        # Columns with most issues
        column_issues = {}
        for r_score in row_scores:
            for issue in r_score.issues:
                # Find column name in issue description
                match = re.search(r"'(.*?)'", issue)
                if match:
                    col = match.group(1)
                    column_issues[col] = column_issues.get(col, 0) + 1

        worst_columns = sorted(column_issues, key=column_issues.get, reverse=True)[:3]
        best_columns = []
        if rows:
            best_columns = [col for col in rows[0].keys() if col not in column_issues][:3]

        return WorkbookHealthReport(
            overall_score=round(overall_avg, 2),
            grade=_get_grade(overall_avg),
            average_completeness=round(avg_comp, 2),
            average_format=round(avg_format, 2),
            average_consistency=round(avg_const, 2),
            average_uniqueness=round(avg_uniq, 2),
            total_rows_checked=total,
            worst_columns=worst_columns,
            best_columns=best_columns,
            grade_distribution=grades
        )

def _validate_url_format(url: str) -> bool:
    pattern = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' # domain...
        r'localhost|' # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(pattern.match(url))

def _validate_imdb_id(id_str: str) -> bool:
    return bool(re.fullmatch(r"(tt|nm)\d{7,}", id_str, flags=re.IGNORECASE))

def _validate_date_format(date_str: str) -> bool:
    # Matches common formats: YYYY-MM-DD, YYYY/MM/DD, YYYY
    if re.fullmatch(r"\d{4}", date_str):
        return True
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", date_str):
        return True
    return False

def _get_grade(score: float) -> Literal["A", "B", "C", "D", "F"]:
    if score >= 90.0: return "A"
    if score >= 80.0: return "B"
    if score >= 70.0: return "C"
    if score >= 60.0: return "D"
    return "F"
