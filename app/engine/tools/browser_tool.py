import httpx
from langchain.tools import tool


@tool
def browser_search(query: str) -> str:
    """Search the web for information. Returns a summary of top results for the given query."""
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AgenticFactory/1.0)"}
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params=params,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        if data.get("AbstractText"):
            results.append(f"Summary: {data['AbstractText']}")
        if data.get("AbstractURL"):
            results.append(f"Source: {data['AbstractURL']}")

        for item in data.get("RelatedTopics", [])[:3]:
            if isinstance(item, dict) and item.get("Text"):
                results.append(f"- {item['Text']}")

        return "\n".join(results) if results else f"No direct results found for: {query}"
    except httpx.TimeoutException:
        return f"Search timed out for query: {query}"
    except Exception as e:
        return f"Search failed: {str(e)}"
