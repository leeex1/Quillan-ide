"""34-seat council deliberation with provider-backed proposals and judge synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Config
from .models import Message
from .providers.registry import ProviderRegistry

SEATS: list[tuple[str, str, str]] = [
    ("C1", "ASTRA", "pattern recognition and anomaly detection"),
    ("C2", "VIR", "ethics, rectitude and veto"),
    ("C3", "SOLACE", "emotional resonance and grounding"),
    ("C4", "PRAXIS", "planning and execution lifecycle"),
    ("C5", "ECHO", "memory continuity and recall"),
    ("C6", "OMNIS", "meta-analysis and perspective rotation"),
    ("C7", "LOGOS", "deductive logic and premise audit"),
    ("C8", "METASYNTH", "cross-domain synthesis"),
    ("C9", "AETHER", "semantics and latent connection"),
    ("C10", "CODEWEAVER", "code architecture and deterministic implementation"),
    ("C11", "HARMONIA", "balance and consensus"),
    ("C12", "SOPHIAE", "wisdom and long-horizon consequence"),
    ("C13", "WARDEN", "threat modeling and perimeter defense"),
    ("C14", "KAIDO", "efficiency and waste elimination"),
    ("C15", "LUMINARIS", "clarity and introspective structure"),
    ("C16", "VOXUM", "articulation and rhetoric"),
    ("C17", "NULLION", "paradox and contradiction holding"),
    ("C18", "SHEPHERD", "truth verification and grounding"),
    ("C19", "VIGIL", "identity integrity and anti-drift"),
    ("C20", "ARTIFEX", "tool orchestration and actuation"),
    ("C21", "ARCHON", "deep research and evidence mining"),
    ("C22", "AURELION", "aesthetic form and proportion"),
    ("C23", "CADENCE", "rhythm, timing and synchronization"),
    ("C24", "SCHEMA", "data modeling and contracts"),
    ("C25", "PROMETHEUS", "hypothesis and falsification"),
    ("C26", "TECHNE", "engineering constraints and hardware"),
    ("C27", "CHRONICLE", "narrative and chronological coherence"),
    ("C28", "CALCULUS", "mathematical proof and quantification"),
    ("C29", "NAVIGATOR", "ecosystem routing and platform handshake"),
    ("C30", "TESSERACT", "high-dimensional manifold mapping"),
    ("C31", "NEXUS", "coordination and asynchronous bus"),
    ("C32", "AEON", "simulation and causal rollforward"),
    ("C33", "TYPIST", "formatting and zero-loss expression"),
    ("C34", "PREDATOR", "adversarial stress-testing and weak-assumption hunt"),
]

ProviderFactory = Callable[[int, tuple[str, str, str]], Any]


@dataclass
class Proposal:
    seat: str
    name: str
    domain: str
    content: str


@dataclass
class CouncilResult:
    question: str
    proposals: list[Proposal] = field(default_factory=list)
    synthesis: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "proposals": [p.__dict__ for p in self.proposals],
            "synthesis": self.synthesis,
            "confidence": self.confidence,
        }


class Council:
    def __init__(
        self,
        config: Config | None = None,
        *,
        provider_factory: ProviderFactory | None = None,
        judge_provider: Any = None,
    ) -> None:
        self.config = config or Config.load()
        self.registry = ProviderRegistry(self.config)
        self.provider_factory = provider_factory
        self.judge_provider = judge_provider

    def seats_for(self, n: int) -> list[tuple[str, str, str]]:
        n = max(1, min(int(n), len(SEATS)))
        return SEATS[:n]

    @staticmethod
    def _seat_prompt(seat: tuple[str, str, str], question: str) -> list[Message]:
        sid, name, domain = seat
        return [
            Message(
                role="system",
                content=(
                    f"You are {sid}-{name}, the {domain} seat of a 34-member council. "
                    "Answer only from your domain. Be concise, concrete and falsifiable. "
                    "Prefix your answer with your seat id."
                ),
            ),
            Message(role="user", content=question),
        ]

    def deliberate(self, question: str, agents: int | None = None) -> CouncilResult:
        agents = agents or int(self.config.get("council.agents", 3))
        seats = self.seats_for(agents)
        result = CouncilResult(question=question)
        for i, seat in enumerate(seats):
            if self.provider_factory is not None:
                adapter = self.provider_factory(i, seat)
            else:
                adapter = self.registry.get()
            reply = adapter.complete(self._seat_prompt(seat, question), [])
            result.proposals.append(
                Proposal(
                    seat=seat[0],
                    name=seat[1],
                    domain=seat[2],
                    content=reply.content,
                )
            )

        judge = self.judge_provider
        if judge is None:
            judge_name = str(self.config.get("council.judge", "default"))
            try:
                judge = self.registry.get(
                    judge_name if judge_name != "default" else None
                )
            except Exception:
                judge = None
        if judge is not None:
            transcript = "\n\n".join(
                f"[{p.seat}-{p.name}] {p.content}" for p in result.proposals
            )
            synthesis = judge.complete(
                [
                    Message(
                        role="system",
                        content=(
                            "You are the sovereign arbiter. Synthesize the council proposals into one "
                            "decision. Preserve points of agreement; resolve conflicts explicitly; "
                            "state the single most important caveat."
                        ),
                    ),
                    Message(
                        role="user",
                        content=f"Question: {question}\n\nCouncil transcript:\n{transcript}",
                    ),
                ],
                [],
            ).content
        else:
            synthesis = self._deterministic_synthesis(result)
        result.synthesis = synthesis
        result.confidence = self._confidence(result.proposals)
        return result

    @staticmethod
    def _deterministic_synthesis(result: CouncilResult) -> str:
        lines = [
            "## Council synthesis (offline judge)",
            "",
            f"Question: {result.question}",
            "",
        ]
        lines.extend(
            f"- **{p.seat}-{p.name}** ({p.domain}): {p.content}"
            for p in result.proposals
        )
        lines.append("")
        lines.append(
            f"Coverage: {len(result.proposals)} independent seats consulted. "
            "No network judge available; proposals are reported verbatim."
        )
        return "\n".join(lines)

    @staticmethod
    def _confidence(proposals: list[Proposal]) -> float:
        if not proposals:
            return 0.0
        unique = len({p.content.strip() for p in proposals if p.content.strip()})
        agreement = unique / len(proposals)
        return round(0.5 + 0.5 * (1.0 - agreement), 3)
