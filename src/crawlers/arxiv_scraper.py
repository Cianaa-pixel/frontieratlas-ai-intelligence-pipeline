import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import feedparser


ARXIV_URL = (
    "https://export.arxiv.org/api/query"
    "?search_query=cat:cs.AI"
    "&start={start}"
    "&max_results={max_results}"
    "&sortBy=submittedDate"
    "&sortOrder=descending"
)

OUTPUT_FILE = Path("data/research_papers.csv")


async def fetch_arxiv(session, start=0, max_results=100):
    url = ARXIV_URL.format(
        start=start,
        max_results=max_results,
    )

    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


def parse_entries(xml_text):
    feed = feedparser.parse(xml_text)

    records = []

    for entry in feed.entries:
        authors = [
            author.name
            for author in entry.get("authors", [])
        ]

        published = entry.get("published")

        records.append({
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "source_name": "arXiv",
            "source_url": entry.get("id"),
            "title": entry.get("title", "").strip().replace("\n", " "),
            "authors": "; ".join(authors),
            "paper_url": entry.get("id"),
            "github_url": "",
            "github_stars": 0,
            "published_date": published,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        })

    return records


async def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    all_records = []

    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "FrontierAtlasResearchPipeline/1.0"
        }
    ) as session:

        for start in range(0, 1000, 100):
            print(f"Fetching papers {start + 1} - {start + 100}...")

            xml = await fetch_arxiv(
                session,
                start=start,
                max_results=100,
            )

            records = parse_entries(xml)
            all_records.extend(records)

            await asyncio.sleep(1)

    # Deduplicate by paper URL
    unique = {}

    for record in all_records:
        unique[record["paper_url"]] = record

    records = list(unique.values())

    with OUTPUT_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=records[0].keys(),
        )

        writer.writeheader()
        writer.writerows(records)

    print()
    print("=" * 60)
    print(f"Saved {len(records)} research papers")
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())