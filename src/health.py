from dataclasses import dataclass, field
import time


@dataclass
class EndpointResult:
    endpoint: str       # e.g. "ladder/summary", "summoner/v4"
    region: str         # e.g. "NA", "EU", "americas", "na1"
    status: int | None  # HTTP status code, or None for network error
    ok: bool
    message: str = ""
    latency_ms: int = 0


@dataclass
class HealthCheckReport:
    service: str                    # "Riot" or "Blizzard"
    results: list[EndpointResult] = field(default_factory=list)
    timestamp: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time())
