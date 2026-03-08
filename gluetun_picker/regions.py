from __future__ import annotations

REGION_ALL = "all"
REGION_EUROPE = "europe"
REGION_NORTH_AMERICA = "north_america"
REGION_CUSTOM = "custom"

INPUT_REGIONS = (
    REGION_NORTH_AMERICA,
    REGION_EUROPE,
    REGION_ALL,
)

DEFAULT_REGION = REGION_NORTH_AMERICA

REGION_COUNTRIES: dict[str, frozenset[str]] = {
    REGION_EUROPE: frozenset(
        {
            "Albania",
            "Austria",
            "Belgium",
            "Bulgaria",
            "Czech Republic",
            "Denmark",
            "Estonia",
            "Finland",
            "France",
            "Germany",
            "Greece",
            "Hungary",
            "Iceland",
            "Ireland",
            "Italy",
            "Latvia",
            "Netherlands",
            "Norway",
            "Poland",
            "Portugal",
            "Romania",
            "Serbia",
            "Slovakia",
            "Slovenia",
            "Spain",
            "Sweden",
            "Switzerland",
            "Ukraine",
            "United Kingdom",
        }
    ),
    REGION_NORTH_AMERICA: frozenset(
        {
            "Canada",
            "Mexico",
            "USA",
        }
    ),
}
