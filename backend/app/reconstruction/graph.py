"""Bounded view over the fact registry, preserving parent/evidence hierarchy."""
from collections import Counter

from app.schemas.reconstruction import GraphV2
from app.reconstruction.registry import FactRegistry

SEVERITY = {'high': 0, 'medium': 1, 'low': 2, 'informational': 3, None: 4}


def build_graph(registry: FactRegistry, config: dict) -> GraphV2:
    facts = list(registry.facts.values())
    # Exposure at the same priority as content; top impacts precede weaker ones.
    def priority(f):
        rank = (0 if f.kind == 'subject' else 1 if f.basis == 'DECLARED' else
                2 if f.kind in {'account', 'academic_profile'} else 3)
        return rank, SEVERITY[f.severity], f.ring, f.id
    ordered = sorted(facts, key=priority)
    selected = {}
    counts = Counter()
    relations = sorted(registry.relations.values(), key=lambda e: e.id)
    parents = {}
    for e in relations:
        if e.type in {'PUBLISHED', 'AUTHORED', 'EXPOSED_IN_BREACH', 'EXPOSED_IN_INFOSTEALER', 'ASSOCIATED_WITH'}:
            parents[e.target] = e.source
    limits = {'post': config['graph_max_post_nodes'], 'repository': config['graph_max_post_nodes'],
              'document': config['graph_max_document_nodes'], 'publication': config['graph_max_document_nodes'],
              'exposure': config['graph_max_exposure_nodes']}
    def bucket(kind):
        return 'document' if kind in {'publication', 'document'} else 'post' if kind == 'repository' else kind
    def add(f):
        if f.id in selected:
            return True
        if len(selected) >= config['graph_max_total_nodes']:
            return False
        limit = limits.get(f.kind)
        if limit is not None and counts[bucket(f.kind)] >= limit:
            return False
        parent = parents.get(f.id)
        if parent and not add(registry.facts[parent]):
            return False
        if len(selected) >= config['graph_max_total_nodes']:
            return False
        selected[f.id] = f
        counts[bucket(f.kind)] += 1
        return True
    for fact in ordered:
        if fact.kind == 'exposure':
            # An overlay must cite a visible source; never place an orphan signal.
            linked = [e for e in relations if e.type == 'HAS_EXPOSURE_SIGNAL' and e.target == fact.id]
            if counts['exposure'] >= config['graph_max_exposure_nodes']:
                continue
            if not any(e.source in selected for e in linked):
                for edge in sorted(linked, key=lambda e: (registry.facts[e.source].ring, e.id)):
                    if add(registry.facts[edge.source]):
                        break
                else:
                    continue
        add(fact)
    edges = [e for e in relations if e.source in selected and e.target in selected]
    # If a cap removed all source connections after selection, drop the overlay.
    linked_exposures = {e.target for e in edges if e.type == 'HAS_EXPOSURE_SIGNAL'}
    selected = {k: f for k, f in selected.items() if f.kind != 'exposure' or k in linked_exposures}
    omitted = Counter(f.kind for f in facts if f.id not in selected)
    return GraphV2(nodes=sorted(selected.values(), key=lambda f: (f.ring, f.id)),
                   edges=[e for e in edges if e.source in selected and e.target in selected],
                   omitted_nodes=sum(omitted.values()), omitted_by_type=dict(sorted(omitted.items())))
