import asyncio
import os
from pathlib import Path

import aiohttp
import pandas as pd
from dotenv import load_dotenv


load_dotenv()

INPUT_FILE = Path("data/research_papers.csv")
OUTPUT_FILE = Path("data/research_papers_enriched.csv")

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


async def get_repo_stars(session, github_url):
    """Get current GitHub star count."""

    if not github_url:
        return None

    parts = github_url.rstrip("/").split("/")

    if len(parts) < 2:
        return None

    owner = parts[-2]
    repo = parts[-1]

    url = GITHUB_API.format(
        owner=owner,
        repo=repo,
    )

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FrontierAtlas-AI-Pipeline",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        async with session.get(url, headers=headers) as response:

            if response.status == 200:
                data = await response.json()
                return data.get("stargazers_count")

            if response.status == 404:
                return None

            if response.status == 403:
                print("GitHub rate limit reached.")
                return None

            print(
                f"GitHub returned HTTP {response.status}"
            )
            return None

    except Exception as exc:
        print(f"GitHub request failed: {exc}")
        return None


async def main():

    if not INPUT_FILE.exists():
        print(f"Input file not found: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE)

    print("=" * 60)
    print("GitHub Enrichment")
    print("=" * 60)
    print(f"Input papers: {len(df)}")

    if "github_url" not in df.columns:
        df["github_url"] = None

    if "github_stars" not in df.columns:
        df["github_stars"] = None

    async with aiohttp.ClientSession() as session:

        for index, row in df.iterrows():

            github_url = row.get("github_url")

            if pd.isna(github_url):
                continue

            stars = await get_repo_stars(
                session,
                github_url,
            )

            df.at[index, "github_stars"] = stars

            if (index + 1) % 50 == 0:
                print(
                    f"Processed {index + 1}/{len(df)}"
                )

            await asyncio.sleep(0.2)

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Output: {OUTPUT_FILE}")
    print(
        "GitHub repositories:",
        df["github_url"].notna().sum(),
    )
    print(
        "Star counts:",
        df["github_stars"].notna().sum(),
    )


if __name__ == "__main__":
    asyncio.run(main())