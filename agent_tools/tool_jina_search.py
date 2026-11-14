import logging
import os
import sys
from typing import Any

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.agent_context import calling_agent  # noqa: E402
from tools.general_tools import get_config_value  # noqa: E402
from tools.search_filter import allowed_urls, parse_date_to_standard  # noqa: E402,F401  (parse_date_to_standard is re-exported)
from tools.server import run_server  # noqa: E402

logger = logging.getLogger(__name__)


class WebScrapingJinaTool:
    # (connect, read) seconds: a hung request must not hang the tool server
    TIMEOUT = (5, 30)

    def __init__(self):
        self.api_key = os.environ.get("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("Jina API key not provided! Please set JINA_API_KEY environment variable.")

    def _headers(self, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json", **extra}

    def __call__(self, query: str) -> list[dict[str, Any]]:
        print(f"Searching for {query}")
        urls = self._jina_search(query)
        print(f"Found {len(urls)} URLs")
        return [self._jina_scrape(url) for url in urls[:1]]

    def _jina_scrape(self, url: str) -> dict[str, Any]:
        try:
            response = requests.get(
                f"https://r.jina.ai/{url}",
                headers=self._headers(**{"X-Timeout": "10", "X-With-Generated-Alt": "true"}),
                timeout=self.TIMEOUT,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Jina AI Reader Failed for {url}: {response.status_code}")
            data = response.json()["data"]
            return {
                "url": data["url"],
                "title": data["title"],
                "description": data["description"],
                "content": data["content"],
                "publish_time": data.get("publishedTime", "unknown"),
            }
        except (requests.RequestException, RuntimeError, KeyError, ValueError) as e:
            logger.error(str(e))
            return {"url": url, "content": "", "error": str(e)}

    def _jina_search(self, query: str) -> list[str]:
        try:
            # `params` URL-encodes the query: an "&" or "#" in what the model typed must not become a parameter of its own
            response = requests.get(
                "https://s.jina.ai/",
                params={"q": query, "n": 1},
                headers=self._headers(**{"X-Respond-With": "no-content"}),
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
            json_data = response.json()
            if not isinstance(json_data, dict) or not isinstance(json_data.get("data"), list):
                print(f"⚠️ Jina API response format abnormal, query: {query}")
                return []
            urls = allowed_urls(json_data["data"], get_config_value("TODAY_DATE"))
            print(f"Found {len(urls)} URLs after filtering")
            return urls
        except requests.RequestException as e:
            print(f"❌ Jina API request failed: {e}")
            return []
        except ValueError as e:
            print(f"❌ Jina API response parsing failed: {e}")
            return []


mcp = FastMCP("Search")


def _search_and_format(query: str) -> str:
    """Search, read one page and format it for the model; any failure becomes the returned text."""
    try:
        tool = WebScrapingJinaTool()
        results = tool(query)
        
        # Check if results are empty
        if not results:
            return f"⚠️ Search query '{query}' found no results. May be network issue or API limitation."
        
        # Convert results to string format
        formatted_results = []
        for result in results:
            if 'error' in result:
                formatted_results.append(f"Error: {result['error']}")
            else:
                formatted_results.append(f"""
URL: {result['url']}
Title: {result['title']}
Description: {result['description']}
Publish Time: {result['publish_time']}
Content: {result['content'][:1000]}...
""")
        
        if not formatted_results:
            return f"⚠️ Search query '{query}' returned empty results."
        

        # log_file = get_config_value("LOG_FILE")     
        # signature = get_config_value("SIGNATURE")
        # log_entry = {
        #     "signature": signature,
        #     "new_messages": [{"role": "tool:jinasearch", "content": "\n".join(formatted_results)}]
        # }
        # with open(log_file, "a", encoding="utf-8") as f:
        #     f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        return "\n".join(formatted_results)
        
    except Exception as e:
        return f"❌ Search tool execution failed: {str(e)}"


@mcp.tool()
def get_information(query: str) -> str:
    """
    Use search tool to scrape and return main content information related to specified query in a structured way.

    Args:
        query: Key information or search terms you want to retrieve, will search for the most matching results on the internet.

    Returns:
        A string containing several retrieved web page contents, structured content includes:
        - URL: Original web page link
        - Title: Web page title
        - Description: Brief description of the web page
        - Publish Time: Content publication date (if available)
        - Content: Main text content of the web page (first 1000 characters)

        If scraping fails, returns corresponding error information.
    """
    with calling_agent():
        return _search_and_format(query)


if __name__ == "__main__":
    run_server(mcp, "SEARCH_HTTP_PORT", 8001)


