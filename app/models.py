from dataclasses import asdict, dataclass, field


@dataclass
class Evidence:
    value: str
    source_type: str
    source: str
    confidence: str = "high"


@dataclass
class Conflict:
    """Two sources disagree on a field; `kept` is in the RFQ by source priority."""
    field: str
    kept: Evidence
    alternative: Evidence


@dataclass
class Product:
    product_id: str
    fields: dict[str, Evidence] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    found: bool = False
    # Text of each source as read (page excerpt, PDF text, catalog record), for the review agent.
    snapshots: dict[str, str] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)

    def merge(self, incoming: dict[str, Evidence]):
        """Call in priority order. Existing values always win."""
        for name, evidence in incoming.items():
            if not evidence.value:
                continue
            previous = self.fields.get(name)
            if previous and previous.value != evidence.value:
                self.add_conflict(name, previous, evidence)
            elif not previous:
                self.fields[name] = evidence

    def add_conflict(self, name, kept, alternative):
        self.conflicts.append(Conflict(name, kept, alternative))
        self.notes.append(
            f"Conflict for {name}: kept {kept.value!r} from {kept.source_type}; "
            f"alternative {alternative.value!r} from {alternative.source_type} ({alternative.source})."
        )

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            product_id=data["product_id"],
            fields={k: Evidence(**v) for k, v in data["fields"].items()},
            notes=list(data["notes"]),
            found=data["found"],
            snapshots=dict(data.get("snapshots", {})),
            conflicts=[Conflict(c["field"], Evidence(**c["kept"]), Evidence(**c["alternative"]))
                       for c in data.get("conflicts", [])],
        )


VERDICTS = ("verified", "inferred", "conflict", "issue")
SEVERITIES = ("critical", "warning", "info")


@dataclass
class Finding:
    """One judgement by the review agent, always with the evidence it rests on."""
    product_id: str
    field: str
    verdict: str              # verified | inferred | conflict | issue
    severity: str             # critical | warning | info
    message: str
    evidence: str
    current_value: str = ""
    proposed_value: str = ""  # only values that already appear in a source
    proposed_source: str = ""
    found_by: str = "rules"   # rules | ai
    decision: str = ""        # "" | approved | rejected (set by a person)

    def to_dict(self):
        return asdict(self)
