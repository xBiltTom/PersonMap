from typing import List
from urllib.parse import quote_plus
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


HEADERS = {
    "User-Agent": "person-map-academic-osint/1.0 (https://github.com/person-map; academic research tool)",
    "Accept": "application/json",
}


class AcademicFinderTool(BaseTool):
    name = "academic_finder"
    description = (
        "Busca publicaciones científicas, tesis, papers y afiliaciones universitarias "
        "en OpenAlex y repositorios académicos abiertos."
    )
    category = ToolCategory.ACADEMIC
    required_inputs = ["full_name", "email"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []

        if not context.full_name:
            return []

        async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
            # 1. Search OpenAlex Authors API
            author_findings = await self._search_openalex_authors(client, context.full_name, context.university)
            findings.extend(author_findings)

            # 2. Search OpenAlex Works API (Papers where target is author)
            works_findings = await self._search_openalex_works(client, context.full_name)
            findings.extend(works_findings)

        return findings

    async def _search_openalex_authors(
        self, client: httpx.AsyncClient, name: str, university: str | None
    ) -> List[ToolFinding]:
        url = f"https://api.openalex.org/authors?search={quote_plus(name)}"
        findings: List[ToolFinding] = []

        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for author in results[:3]:
                    display_name = author.get("display_name")
                    affiliations = author.get("affiliations", [])
                    institutions = [
                        aff.get("institution", {}).get("display_name", "")
                        for aff in affiliations
                        if aff.get("institution")
                    ]
                    orcid = author.get("orcid")
                    works_count = author.get("works_count", 0)
                    cited_by_count = author.get("cited_by_count", 0)
                    openalex_id = author.get("id")

                    # Boost confidence if university matches
                    confidence = 0.60
                    if university and any(university.lower() in inst.lower() for inst in institutions):
                        confidence = 0.90

                    findings.append(
                        ToolFinding(
                            entity_type="academic",
                            platform="openalex_author",
                            value=openalex_id or display_name,
                            display_name=f"{display_name} (Autor Académico)",
                            metadata_info={
                                "author_name": display_name,
                                "institutions": institutions,
                                "orcid": orcid,
                                "works_count": works_count,
                                "citations_count": cited_by_count,
                                "profile_url": openalex_id,
                            },
                            confidence=confidence,
                            evidence_urls=[openalex_id] if openalex_id else [],
                        )
                    )
        except Exception:
            return []

        return findings

    async def _search_openalex_works(self, client: httpx.AsyncClient, name: str) -> List[ToolFinding]:
        url = f"https://api.openalex.org/works?filter=author.search:{quote_plus(name)}"
        findings: List[ToolFinding] = []

        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for work in results[:5]:  # Top 5 works
                    title = work.get("title") or "Sin título"
                    doi = work.get("doi")
                    pub_year = work.get("publication_year")
                    landing_url = work.get("primary_location", {}).get("landing_page_url") or doi

                    findings.append(
                        ToolFinding(
                            entity_type="academic",
                            platform="research_paper",
                            value=doi or title,
                            display_name=f"Paper: {title[:80]}...",
                            metadata_info={
                                "title": title,
                                "doi": doi,
                                "publication_year": pub_year,
                                "url": landing_url,
                            },
                            confidence=0.70,
                            evidence_urls=[landing_url] if landing_url else [],
                        )
                    )
        except Exception:
            return []

        return findings
