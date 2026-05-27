from __future__ import annotations

from app.interfaces import ScoringEngine
from app.models import EntityCandidate, EntityQuery, EvidenceItem, PlatformResult, ProfileCandidate
from app.platforms.base import normalize_tokens


TRUSTED_DOMAINS = ("wikipedia.org", "imdb.com", "www.imdb.com")
NEGATIVE_KEYWORDS = {"fan", "unofficial", "backup", "archive", "parody", "repost", "updates"}
POSITIVE_KEYWORDS = {"official", "verified", "business", "creator", "brand", "page", "channel"}
VALID_CONFIDENCE_THRESHOLD = 60
GENERIC_TOKENS = {
    "official",
    "page",
    "channel",
    "facebook",
    "instagram",
    "youtube",
    "twitter",
    "x",
    "imdb",
    "wikipedia",
}
REGION_TOKENS = {
    "au",
    "aus",
    "uk",
    "in",
    "india",
    "jp",
    "japan",
    "us",
    "usa",
    "ca",
    "canada",
}


class HeuristicScoringEngine(ScoringEngine):
    def score_entity_candidates(
        self, query: EntityQuery, candidates: list[EntityCandidate]
    ) -> list[EntityCandidate]:
        query_tokens = normalize_tokens(query.name)
        scored: list[EntityCandidate] = []

        for candidate in candidates:
            label_tokens = normalize_tokens(candidate.label)
            overlap = len(query_tokens & label_tokens)
            query_coverage = overlap / max(len(query_tokens), 1)
            extra_tokens = label_tokens - query_tokens
            score = candidate.score
            evidence = list(candidate.evidence)

            if query.name.lower() == candidate.label.lower():
                score += 45
                evidence.append(EvidenceItem(summary="Exact entity name match", weight=45))
            elif candidate.label.lower() in query.name.lower() and query_coverage >= 0.8:
                score += 18
                evidence.append(EvidenceItem(summary="Candidate is a near-complete phrase match", weight=18))
            elif query.name.lower() in candidate.label.lower():
                score += 30
                evidence.append(EvidenceItem(summary="Strong entity name match", weight=30))
            elif query_tokens and overlap:
                weight = 8 + query_coverage * 20
                score += weight
                evidence.append(EvidenceItem(summary="Partial token overlap with query", weight=round(weight, 1)))

            if candidate.source_domain.endswith(TRUSTED_DOMAINS):
                score += 15
                evidence.append(EvidenceItem(summary="Trusted reference source", weight=15))

            if query.entity_type and query.entity_type.replace("_", " ") in candidate.description.lower():
                score += 10
                evidence.append(EvidenceItem(summary="Entity type appears in description", weight=10))

            if query.profession and query.profession.lower() in candidate.description.lower():
                score += 12
                evidence.append(EvidenceItem(summary="Profession hint appears in description", weight=12))

            if query.date_of_birth and query.date_of_birth in candidate.description:
                score += 10
                evidence.append(EvidenceItem(summary="Date-of-birth hint appears in description", weight=10))

            if query.country and query.country.lower() in candidate.description.lower():
                score += 8
                evidence.append(EvidenceItem(summary="Country hint appears in description", weight=8))

            if query_coverage < 0.6:
                penalty = round((0.6 - query_coverage) * 45, 1)
                score -= penalty
                evidence.append(
                    EvidenceItem(
                        summary="Candidate misses too many query words",
                        weight=-penalty,
                        kind="negative",
                    )
                )

            if extra_tokens and query_coverage < 1.0:
                penalty = min(10.0, len(extra_tokens) * 2.5)
                score -= penalty
                evidence.append(
                    EvidenceItem(
                        summary="Candidate adds extra words beyond the query",
                        weight=-penalty,
                        kind="negative",
                    )
                )

            candidate.score = round(min(score, 100), 1)
            candidate.evidence = evidence
            scored.append(candidate)

        return sorted(scored, key=lambda item: item.score, reverse=True)

    def score_profile_candidates(
        self,
        query: EntityQuery,
        entity: EntityCandidate,
        platform: str,
        raw_candidates: list[dict],
    ) -> PlatformResult:
        scored_candidates: list[ProfileCandidate] = []
        query_tokens = normalize_tokens(query.name)
        entity_tokens = normalize_tokens(entity.canonical_name)
        target_tokens = (query_tokens | entity_tokens) - GENERIC_TOKENS

        for raw in raw_candidates:
            text_blob = " ".join(
                [
                    raw.get("display_name") or "",
                    raw.get("title") or "",
                    raw.get("snippet") or "",
                    raw.get("handle") or "",
                ]
            ).lower()
            candidate_tokens = normalize_tokens(text_blob) - GENERIC_TOKENS
            overlap_tokens = target_tokens & candidate_tokens
            coverage = len(overlap_tokens) / max(len(target_tokens), 1)
            extra_tokens = candidate_tokens - target_tokens
            score = 18.0
            evidence: list[EvidenceItem] = []

            if entity.canonical_name.lower() == (raw.get("display_name") or "").lower():
                score += 35
                evidence.append(EvidenceItem(summary="Exact display name match", weight=35))
            elif query.name.lower() in text_blob or entity.canonical_name.lower() in text_blob:
                score += 25
                evidence.append(EvidenceItem(summary="Strong name match across search evidence", weight=25))
            else:
                if overlap_tokens:
                    weight = 8 + coverage * 20
                    score += weight
                    evidence.append(EvidenceItem(summary="Partial token overlap with entity", weight=round(weight, 1)))

            if query.entity_type and query.entity_type.replace("_", " ") in text_blob:
                score += 8
                evidence.append(EvidenceItem(summary="Entity type hint matched", weight=8))

            if query.country and query.country.lower() in text_blob:
                score += 6
                evidence.append(EvidenceItem(summary="Country hint matched", weight=6))

            if entity.source_domain.endswith(TRUSTED_DOMAINS):
                score += 7
                evidence.append(EvidenceItem(summary="Consistent with trusted reference source", weight=7))

            for label in raw.get("account_labels", []):
                score += 6
                evidence.append(EvidenceItem(summary=f"Account label detected: {label}", weight=6))

            for keyword in POSITIVE_KEYWORDS:
                if keyword in text_blob:
                    score += 4
                    evidence.append(EvidenceItem(summary=f"Positive keyword found: {keyword}", weight=4))

            if coverage < 0.55:
                penalty = round((0.55 - coverage) * 50, 1)
                score -= penalty
                evidence.append(
                    EvidenceItem(
                        summary="Profile misses too many words from the target entity",
                        weight=-penalty,
                        kind="negative",
                    )
                )

            non_region_extra = {token for token in extra_tokens if token not in REGION_TOKENS}
            if non_region_extra:
                penalty = min(12.0, len(non_region_extra) * 2.5)
                score -= penalty
                evidence.append(
                    EvidenceItem(
                        summary="Profile adds unrelated extra words",
                        weight=-penalty,
                        kind="negative",
                    )
                )

            if not query.country and extra_tokens & REGION_TOKENS:
                score -= 14
                evidence.append(
                    EvidenceItem(
                        summary="Profile appears to be a regional variant",
                        weight=-14,
                        kind="negative",
                    )
                )

            for hint in raw.get("negative_hints", []):
                score -= 18
                evidence.append(EvidenceItem(summary=f"Negative hint found: {hint}", weight=-18, kind="negative"))

            confidence_score = round(max(0.0, min(score, 100.0)), 1)
            confidence_label = self._confidence_label(confidence_score)
            status = (
                "found"
                if confidence_score >= VALID_CONFIDENCE_THRESHOLD
                else "uncertain"
                if confidence_score >= 40
                else "not_found"
            )
            scored_candidates.append(
                ProfileCandidate(
                    platform=platform,
                    url=raw["url"],
                    handle=raw.get("handle"),
                    display_name=raw.get("display_name"),
                    status=status,
                    confidence_score=confidence_score,
                    confidence_label=confidence_label,
                    evidence=evidence[:6],
                    account_labels=raw.get("account_labels", []),
                )
            )

        scored_candidates.sort(key=lambda item: item.confidence_score, reverse=True)
        if not scored_candidates or scored_candidates[0].confidence_score < 40:
            return PlatformResult(platform=platform, primary=None, alternates=[], status="not_found")

        primary = scored_candidates[0]
        alternates = [candidate for candidate in scored_candidates[1:4] if candidate.confidence_score >= 40]
        overall_status = primary.status
        return PlatformResult(platform=platform, primary=primary, alternates=alternates, status=overall_status)

    def _confidence_label(self, score: float) -> str:
        if score >= 80:
            return "Very High"
        if score >= 65:
            return "High"
        if score >= 50:
            return "Medium"
        if score >= 35:
            return "Low"
        return "Very Low"
