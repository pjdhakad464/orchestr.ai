from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, Field

class Anomaly(BaseModel):
    row_index: int
    column: str
    value: str
    anomaly_type: Literal["date_outlier", "rare_category", "missing_pattern", "format_violation"]
    severity: Literal["low", "medium", "high"]
    description: str

class ColumnHealth(BaseModel):
    column: str
    missing_pct: float
    cardinality: int
    anomalies_count: int

class AnomalyReport(BaseModel):
    anomalies: list[Anomaly] = Field(default_factory=list)
    column_health: list[ColumnHealth] = Field(default_factory=list)
    total_anomalies: int = 0

class AnomalyDetector:
    def __init__(self) -> None:
        pass

    def detect_date_outliers(self, rows: list[dict[str, Any]], column_name: str) -> list[Anomaly]:
        """Detects date outliers using statistical IQR method on extracted years."""
        anomalies = []
        parsed_years = []
        valid_indices = []

        for idx, row in enumerate(rows):
            val = str(row.get(column_name, "")).strip()
            if val:
                # Find first 4 digit year
                match = re.search(r"\b\d{4}\b", val)
                if match:
                    parsed_years.append(int(match.group()))
                    valid_indices.append(idx)

        if len(parsed_years) < 4:
            return []

        # Simple IQR implementation
        sorted_years = sorted(parsed_years)
        n = len(sorted_years)
        
        # Percentiles
        q1 = sorted_years[int(n * 0.25)]
        q3 = sorted_years[int(n * 0.75)]
        iqr = q3 - q1
        
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        for idx, year in zip(valid_indices, parsed_years):
            if year < lower_bound or year > upper_bound:
                val = str(rows[idx].get(column_name, ""))
                anomalies.append(Anomaly(
                    row_index=idx + 1,
                    column=column_name,
                    value=val,
                    anomaly_type="date_outlier",
                    severity="high" if abs(year - (upper_bound if year > upper_bound else lower_bound)) > 10 else "medium",
                    description=f"Year {year} is a statistical outlier compared to sheet distribution (expected range {int(lower_bound)}-{int(upper_bound)})."
                ))

        return anomalies

    def detect_categorical_anomalies(
        self,
        rows: list[dict[str, Any]],
        column_name: str,
        min_frequency: float = 0.02
    ) -> list[Anomaly]:
        """Flags values that appear with abnormally low frequency in a category column."""
        anomalies = []
        total_rows = len(rows)
        if total_rows < 10:
            return []

        counts = {}
        non_empty = 0
        for row in rows:
            val = str(row.get(column_name, "")).strip().casefold()
            if val:
                counts[val] = counts.get(val, 0) + 1
                non_empty += 1

        if not non_empty:
            return []

        rare_categories = []
        for val, count in counts.items():
            freq = count / non_empty
            if freq < min_frequency and count <= 2:  # Rare, and has low absolute occurrence
                rare_categories.append(val)

        for idx, row in enumerate(rows):
            val = str(row.get(column_name, "")).strip()
            if val and val.casefold() in rare_categories:
                anomalies.append(Anomaly(
                    row_index=idx + 1,
                    column=column_name,
                    value=val,
                    anomaly_type="rare_category",
                    severity="low",
                    description=f"Category '{val}' is extremely rare in this column (occurs in <{min_frequency * 100}% of rows)."
                ))

        return anomalies

    def detect_missing_patterns(self, rows: list[dict[str, Any]]) -> list[ColumnHealth]:
        """Analyzes missing data percentages across all columns."""
        if not rows:
            return []

        columns = list(rows[0].keys())
        total_rows = len(rows)
        column_health = []

        for col in columns:
            missing_count = 0
            unique_vals = set()
            for row in rows:
                val = str(row.get(col, "")).strip()
                if not val or val.casefold() in {r"\n", "nan", "null"}:
                    missing_count += 1
                else:
                    unique_vals.add(val.casefold())

            missing_pct = (missing_count / total_rows) * 100.0
            column_health.append(ColumnHealth(
                column=col,
                missing_pct=round(missing_pct, 2),
                cardinality=len(unique_vals),
                anomalies_count=0
            ))

        return column_health

    def detect_all(
        self,
        rows: list[dict[str, Any]],
        date_columns: list[str] | None = None,
        categorical_columns: list[str] | None = None
    ) -> AnomalyReport:
        """Runs complete anomaly detection suite on spreadsheet data."""
        if not rows:
            return AnomalyReport()

        anomalies = []
        col_health = self.detect_missing_patterns(rows)

        # Defaults
        dates = date_columns or [c.column for c in col_health if "date" in c.column.casefold() or "released" in c.column.casefold()]
        cats = categorical_columns or [c.column for c in col_health if "genre" in c.column.casefold() or "category" in c.column.casefold() or "network" in c.column.casefold()]

        for col in dates:
            anomalies.extend(self.detect_date_outliers(rows, col))

        for col in cats:
            anomalies.extend(self.detect_categorical_anomalies(rows, col))

        # Map anomalies count back to column health
        for health in col_health:
            health.anomalies_count = sum(1 for a in anomalies if a.column == health.column)

        return AnomalyReport(
            anomalies=anomalies,
            column_health=col_health,
            total_anomalies=len(anomalies)
        )
