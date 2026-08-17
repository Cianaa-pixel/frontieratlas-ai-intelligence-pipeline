import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp
import pandas as pd
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

INPUT_FILE = Path("data/research_papers.csv")
OUTPUT_FILE = Path("data/research_papers_enriched.csv")

GITHUB_API = "https://api.github.com"

# Use your GitHub token from .env if available.
# A token is strongly recommended for 1000+ API requests.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

CONCURRENCY = 10
MAX_RETRIES = 5

REQUEST_TIMEOUT = 30

SAVE_EVERY = 50


# ============================================================
# LOGGING
# ============================================================

def log(message: str):
    print(message, flush=True)


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_title(title: str) -> str:
    """
    Clean a paper title before searching GitHub.
    """
    if not title:
        return ""

    title = str(title)

    # Remove excessive whitespace
    title = re.sub(r"\s+", " ", title)

    # Remove some punctuation that can make GitHub search noisy
    title = title.strip()

    return title


def normalize_repo_url(url: str | None) -> str | None:
    """
    Normalize GitHub repository URLs.
    """
    if not url:
        return None

    url = str(url).strip()

    if not url:
        return None

    # Remove trailing slash
    url = url.rstrip("/")

    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    return url


# ============================================================
# GITHUB HEADERS
# ============================================================

def get_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FrontierAtlas-AI-Intelligence-Pipeline",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


# ============================================================
# GITHUB SEARCH
# ============================================================

async def github_search(
    session: aiohttp.ClientSession,
    title: str,
) -> tuple[str | None, int | None]:

    title = clean_title(title)

    if not title:
        return None, None

    # GitHub search query.
    #
    # We search the title in repositories rather than blindly
    # generating URLs. This prevents hallucinated repositories.
    query = f'"{title}"'

    url = (
        f"{GITHUB_API}/search/repositories"
        f"?q={quote(query)}"
        f"&per_page=5"
        f"&sort=stars"
        f"&order=desc"
    )

    headers = get_headers()

    for attempt in range(MAX_RETRIES):

        try:

            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(
                    total=REQUEST_TIMEOUT
                ),
            ) as response:

                # ------------------------------------------------
                # SUCCESS
                # ------------------------------------------------

                if response.status == 200:

                    data = await response.json()

                    items = data.get("items", [])

                    if not items:
                        return None, None

                    # Choose the most relevant repository.
                    #
                    # GitHub's search ranking is already useful,
                    # but we additionally score title similarity.
                    best_repo = choose_best_repository(
                        title,
                        items,
                    )

                    if not best_repo:
                        return None, None

                    repo_url = normalize_repo_url(
                        best_repo.get("html_url")
                    )

                    stars = best_repo.get(
                        "stargazers_count"
                    )

                    return repo_url, stars


                # ------------------------------------------------
                # RATE LIMIT
                # ------------------------------------------------

                if response.status in (403, 429):

                    retry_after = response.headers.get(
                        "Retry-After"
                    )

                    if retry_after:

                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            wait_time = 10

                    else:

                        # Exponential backoff
                        wait_time = min(
                            60,
                            2 ** attempt
                        )

                    log(
                        f"GitHub rate limit "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}) "
                        f"waiting {wait_time:.1f}s"
                    )

                    await asyncio.sleep(wait_time)

                    continue


                # ------------------------------------------------
                # SERVER ERROR
                # ------------------------------------------------

                if response.status >= 500:

                    wait_time = min(
                        30,
                        2 ** attempt
                    )

                    log(
                        f"GitHub server error "
                        f"{response.status}; "
                        f"retrying in {wait_time}s"
                    )

                    await asyncio.sleep(wait_time)

                    continue


                # ------------------------------------------------
                # OTHER ERROR
                # ------------------------------------------------

                log(
                    f"GitHub request failed: "
                    f"{response.status}"
                )

                return None, None


        except asyncio.TimeoutError:

            wait_time = min(
                30,
                2 ** attempt
            )

            log(
                f"Timeout searching GitHub "
                f"for '{title[:60]}...' "
                f"retrying in {wait_time}s"
            )

            await asyncio.sleep(wait_time)


        except aiohttp.ClientError as exc:

            wait_time = min(
                30,
                2 ** attempt
            )

            log(
                f"Network error: {exc} "
                f"retrying in {wait_time}s"
            )

            await asyncio.sleep(wait_time)


        except Exception as exc:

            log(
                f"Unexpected GitHub error: {exc}"
            )

            return None, None


    return None, None


# ============================================================
# REPOSITORY MATCHING
# ============================================================

def normalize_text(text: str) -> str:
    """
    Normalize text for fuzzy comparison.
    """

    text = str(text).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def similarity_score(
    paper_title: str,
    repo: dict,
) -> float:

    paper = normalize_text(paper_title)

    repo_name = normalize_text(
        repo.get("name", "")
    )

    repo_description = normalize_text(
        repo.get("description", "") or ""
    )

    if not paper:
        return 0.0

    score = 0.0

    # Exact normalized title in repository name
    if paper == repo_name:
        score += 1.0

    # Repository name appears inside title
    if repo_name and repo_name in paper:
        score += 0.7

    # Important title words
    paper_words = set(
        word
        for word in paper.split()
        if len(word) > 3
    )

    repo_words = set(
        word
        for word in (
            repo_name + " " + repo_description
        ).split()
        if len(word) > 3
    )

    if paper_words:

        overlap = (
            len(paper_words & repo_words)
            / len(paper_words)
        )

        score += overlap * 0.5

    return score


def choose_best_repository(
    paper_title: str,
    repositories: list[dict],
) -> dict | None:

    if not repositories:
        return None

    scored = []

    for repo in repositories:

        score = similarity_score(
            paper_title,
            repo
        )

        scored.append(
            (score, repo)
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True
    )

    best_score, best_repo = scored[0]

    # Conservative threshold.
    #
    # We don't want to attach unrelated GitHub projects
    # merely because GitHub returned them.
    if best_score < 0.25:
        return None

    return best_repo


# ============================================================
# WORKER
# ============================================================

async def process_paper(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    index: int,
    title: str,
):

    async with semaphore:

        github_url, github_stars = await github_search(
            session,
            title,
        )

        return (
            index,
            github_url,
            github_stars,
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print("=" * 60)
    print("FrontierAtlas GitHub Paper Enrichment")
    print("=" * 60)
    print()

    # --------------------------------------------------------
    # Check input
    # --------------------------------------------------------

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}"
        )

    # --------------------------------------------------------
    # Load CSV
    # --------------------------------------------------------

    log(f"Loading: {INPUT_FILE}")

    df = pd.read_csv(
        INPUT_FILE
    )

    if "title" not in df.columns:

        raise ValueError(
            "CSV does not contain a 'title' column."
        )

    log(f"Papers: {len(df)}")
    log(f"Concurrency: {CONCURRENCY}")
    print()

    # --------------------------------------------------------
    # IMPORTANT FIX
    #
    # Pandas may infer an entirely-empty GitHub URL column
    # as float64 because it contains only NaN.
    #
    # We explicitly convert it to object/string-compatible
    # dtype before inserting URLs.
    # --------------------------------------------------------

    if "github_url" not in df.columns:

        df["github_url"] = pd.Series(
            [None] * len(df),
            dtype="object"
        )

    else:

        df["github_url"] = (
            df["github_url"]
            .astype("object")
        )

    # --------------------------------------------------------
    # Same treatment for GitHub stars.
    # --------------------------------------------------------

    if "github_stars" not in df.columns:

        df["github_stars"] = pd.Series(
            [None] * len(df),
            dtype="object"
        )

    else:

        df["github_stars"] = (
            df["github_stars"]
            .astype("object")
        )

    # --------------------------------------------------------
    # Ensure collectedAt exists
    # --------------------------------------------------------

    if "collectedAt" not in df.columns:

        df["collectedAt"] = (
            pd.Timestamp.utcnow()
            .isoformat()
        )

    # --------------------------------------------------------
    # HTTP session
    # --------------------------------------------------------

    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT
    )

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=CONCURRENCY,
        ssl=False,
    )

    semaphore = asyncio.Semaphore(
        CONCURRENCY
    )

    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
    ) as session:

        # ----------------------------------------------------
        # Create tasks
        # ----------------------------------------------------

        tasks = []

        for index, row in df.iterrows():

            title = row.get(
                "title",
                ""
            )

            # Skip papers that already have enrichment.
            #
            # This makes the script restartable.
            existing_url = row.get(
                "github_url"
            )

            if (
                pd.notna(existing_url)
                and str(existing_url).strip()
            ):
                continue

            tasks.append(
                asyncio.create_task(
                    process_paper(
                        session,
                        semaphore,
                        index,
                        title,
                    )
                )
            )

        total = len(tasks)

        log(
            f"Repositories to search: {total}"
        )

        if total == 0:

            log(
                "All papers already enriched."
            )

        # ----------------------------------------------------
        # Process results
        # ----------------------------------------------------

        completed = 0
        found_repos = 0
        found_stars = 0

        for future in asyncio.as_completed(tasks):

            index, github_url, github_stars = (
                await future
            )

            completed += 1

            # -----------------------------------------------
            # Store GitHub URL
            # -----------------------------------------------

            if github_url:

                df.at[
                    index,
                    "github_url"
                ] = github_url

                found_repos += 1

            # -----------------------------------------------
            # Store stars
            # -----------------------------------------------

            if github_stars is not None:

                df.at[
                    index,
                    "github_stars"
                ] = int(github_stars)

                found_stars += 1

            # -----------------------------------------------
            # Progress
            # -----------------------------------------------

            if (
                completed % 50 == 0
                or completed == total
            ):

                log(
                    f"Processed "
                    f"{completed}/{total}"
                )

            # -----------------------------------------------
            # Periodic checkpoint
            # -----------------------------------------------

            if (
                completed % SAVE_EVERY == 0
            ):

                # Ensure directory exists
                OUTPUT_FILE.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                df.to_csv(
                    OUTPUT_FILE,
                    index=False
                )

                log(
                    f"Checkpoint saved: "
                    f"{OUTPUT_FILE}"
                )

    # ========================================================
    # FINAL SAVE
    # ========================================================

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    # ========================================================
    # FINAL REPORT
    # ========================================================

    print()
    print("=" * 60)
    print("ENRICHMENT COMPLETE")
    print("=" * 60)

    print(
        f"Total papers: {len(df)}"
    )

    print(
        f"GitHub repositories found: "
        f"{found_repos}"
    )

    print(
        f"GitHub star counts found: "
        f"{found_stars}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print("=" * 60)
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print(
            "Process interrupted by user."
        )

    except Exception as exc:

        print()
        print(
            f"ERROR: {exc}"
        )
        raise