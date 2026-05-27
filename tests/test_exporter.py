from app.models import EntityCandidate, EntityQuery, EvidenceItem, PlatformResult, ProfileCandidate, SearchResponse
from app.services.exporter import build_export_payload_from_search, rows_to_csv_bytes


def test_search_export_payload_flattens_platform_rows():
    response = SearchResponse(
        query=EntityQuery(name="Barbie", entity_type="movie"),
        selected_entity=EntityCandidate(
            candidate_id="1",
            label="Barbie",
            canonical_name="Barbie",
            description="Movie result from TMDB",
            source_url="https://www.themoviedb.org/movie/346698",
            source_domain="www.themoviedb.org",
            source_metadata={
                "metadata_source": "TMDB",
                "official_website": "https://www.barbiethemovie.com",
                "release_type": "Wide",
                "studio_type": "Major",
                "genre": "Comedy, Adventure",
                "release_date": "2023-07-21",
                "network": "Warner Bros. Pictures",
            },
        ),
        platform_results=[
            PlatformResult(
                platform="Instagram",
                status="found",
                primary=ProfileCandidate(
                    platform="Instagram",
                    url="https://instagram.com/barbiethemovie",
                    handle="barbiethemovie",
                    display_name="Barbie",
                    status="found",
                    confidence_score=78,
                    confidence_label="High",
                    evidence=[EvidenceItem(summary="Exact display name match", weight=35)],
                    account_labels=["official"],
                ),
            )
        ],
        notes=["Confidence is heuristic and should be reviewed before reuse."],
    )

    payload = build_export_payload_from_search(response)
    assert len(payload.rows) == 1
    assert payload.rows[0].platform == "Instagram"
    assert payload.rows[0].display_name == "Barbie"
    assert payload.rows[0].metadata_source == "TMDB"
    assert payload.rows[0].official_website == "https://www.barbiethemovie.com"
    assert payload.rows[0].release_type == "Wide"
    assert payload.rows[0].studio_type == "Major"
    assert payload.rows[0].genre == "Comedy, Adventure"
    assert payload.rows[0].release_date == "2023-07-21"
    assert payload.rows[0].network == "Warner Bros. Pictures"


def test_csv_export_contains_headers_and_row_data():
    response = SearchResponse(
        query=EntityQuery(name="Sony Pictures"),
        selected_entity=EntityCandidate(
            candidate_id="1",
            label="Sony Pictures",
            canonical_name="Sony Pictures",
            description="Entertainment company",
            source_url="https://en.wikipedia.org/wiki/Sony_Pictures",
            source_domain="en.wikipedia.org",
        ),
        platform_results=[],
    )

    payload = build_export_payload_from_search(response)
    csv_bytes = rows_to_csv_bytes(payload)
    decoded = csv_bytes.decode("utf-8-sig")
    assert "Entity Query,Matched Entity" in decoded
    assert "Metadata Source,Official Website,Release Type,Studio Type,Genre,Release Date,Network / Studio" in decoded
