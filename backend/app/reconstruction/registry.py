import hashlib
import json

from app.schemas.reconstruction import EvidenceRef, ReconstructionFact, ReconstructionRelation


def fingerprint(namespace: str, value: str) -> str:
    return namespace + ':' + hashlib.sha256(value.encode()).hexdigest()[:32]


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)


class FactRegistry:
    def __init__(self):
        self.facts: dict[str, ReconstructionFact] = {}
        self.evidence: dict[str, EvidenceRef] = {}
        self.relations: dict[str, ReconstructionRelation] = {}

    def evidence_ref(self, *, source_type, excerpt, entity_ids=(), content_ids=(), platform=None, url=None):
        data = dict(source_type=source_type, excerpt=excerpt[:280], source_entity_ids=sorted(set(entity_ids)),
                    source_content_ids=sorted(set(content_ids)), platform=platform, url=url)
        key = fingerprint('evidence', canonical(data))
        self.evidence[key] = EvidenceRef(id=key, **data)
        return key

    def _provenance(self, refs):
        evidence = [self.evidence[ref] for ref in sorted(set(refs))]
        return dict(evidence_refs=sorted(set(refs)), evidence_count=len(evidence),
                    evidence_types=sorted({e.source_type for e in evidence}),
                    source_entity_ids=sorted({v for e in evidence for v in e.source_entity_ids}),
                    source_content_ids=sorted({v for e in evidence for v in e.source_content_ids}))

    def fact(self, *, id, kind, label, basis, group, ring, refs, **kwargs):
        previous = self.facts.get(id)
        if previous:
            refs = [*previous.evidence_refs, *refs]
            basis = 'DECLARED' if previous.basis == 'DECLARED' or basis == 'DECLARED' else previous.basis
            # Canonical facts keep the same safe display independent of input order.
            label = min(previous.label, label)
        fact = ReconstructionFact(id=id, kind=kind, label=label[:160], basis=basis, group=group, ring=ring,
                                  **self._provenance(refs), **kwargs)
        self.facts[id] = fact
        return id

    def relate(self, source, target, type, basis, why, refs):
        if source == target or source not in self.facts or target not in self.facts or not refs:
            return
        key = fingerprint('edge', f'{type}:{source}:{target}')
        previous = self.relations.get(key)
        self.relations[key] = ReconstructionRelation(
            id=key, source=source, target=target, type=type, basis=basis, why=why,
            **self._provenance([*(previous.evidence_refs if previous else []), *refs]),
        )
