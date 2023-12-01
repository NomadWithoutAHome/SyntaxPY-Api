from enum import Enum
import logging
from contextlib import contextmanager

from fastapi import FastAPI, Query, Header
from bs4 import BeautifulSoup
import requests
import random
import re
from urllib.parse import urljoin, urlencode
from typing import Optional

from starlette.responses import RedirectResponse

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
]

CATEGORY_DICT = {
    1: "Featured Hats",
    2: "Featured Gears",
    3: "Featured Faces",
    4: "Collectible Items",
    5: "Collectible Hats",
    6: "Collectible Gears",
    7: "Collectible Faces",
    8: "All Clothing",
    9: "Hats",
    10: "Shirts",
    11: "T-Shirts",
    12: "Pants",
    13: "Packages",
    14: "Body Parts",
    15: "Heads",
    16: "Faces"
}

SORT_DICT = {
    0: "Relevance",
    1: "Price ( Low to High )",
    2: "Price ( High to Low )",
    3: "Recently Updated",
    4: "Best Selling"
}

@app.get("/", include_in_schema=False)
def read_root():
    return RedirectResponse(url='/docs')

@contextmanager
def create_session(session_cookie, sec_cookie, user_agents):
    headers = {'User-Agent': random.choice(user_agents),
               'Cookie': f'session={session_cookie}; .ROBLOSECURITY={sec_cookie}'}
    session = requests.Session()
    session.headers.update(headers)

    retry_strategy = requests.packages.urllib3.Retry(
        total=3,
        status_forcelist=[500, 502, 503, 504],
        backoff_factor=1,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    yield session

    session.close()


def extract_total_pages(text):
    match = re.search(r'Page \d+ of (\d+)', text)
    return int(match.group(1)) if match else 1


def process_item(item):
    try:
        item_name = item.find('p', class_='text-secondary').text.strip()
        item_price_robux = item.find('p', class_='text-robux')
        item_price_tickets = item.find('p', class_='text-tickets')

        robux_price = int(re.search(r'\d+', item_price_robux.text).group()) if item_price_robux and re.search(
            r'\d+', item_price_robux.text) else None
        tickets_price = int(
            re.search(r'\d+', item_price_tickets.text).group()) if item_price_tickets and re.search(r'\d+',
                                                                                                    item_price_tickets.text) else None

        price_change_tag = item.find('span', class_='text-secondary fw-normal', string='now')
        price_change_now = int(
            re.search(r'\d+', price_change_tag.next_sibling).group()) if price_change_tag and re.search(r'\d+',
                                                                                                        price_change_tag.next_sibling) else None
        price_change_was_tag = item.find('span', class_='text-secondary fw-normal', string='was')
        price_change_was = int(
            re.search(r'\d+', price_change_was_tag.next_sibling).group()) if price_change_was_tag and re.search(
            r'\d+', price_change_was_tag.next_sibling) else None

        price_change = {
            "was": price_change_was,
            "now": price_change_now
        }

        if all(value is None for value in price_change.values()):
            price_change = "None"
        else:
            if price_change["was"] is None:
                price_change["was"] = "Free"
            if price_change["now"] is None:
                price_change["now"] = "Free"

        if robux_price is None and tickets_price is None:
            item_price_value = "Free"
        else:
            item_price_value = {
                "Robux": str(robux_price) if robux_price is not None else "None",
                "Tickets": str(tickets_price) if tickets_price is not None else "None",
                "price_change": price_change
            }

        limited_tag = item.find('p', class_='position-absolute m-0 fw-bold text-limited')
        limited_u_tag = limited_tag.find('span', class_='text-limitedu') if limited_tag else None

        limited_info = {
            "type": "limited u" if limited_u_tag else ("limited" if limited_tag else "None"),
        }

        item_link_tag = item.find_parent('a', href=True)
        item_link_relative = item_link_tag['href'].strip() if item_link_tag else None
        item_link = f"https://www.syntax.eco{item_link_relative}" if item_link_relative else None

        img_src = item.find('img')['src'].strip()
        item_image = f"https://www.syntax.eco{img_src}" if img_src else None

        item_data = {
            "item_name": item_name,
            "item_price": item_price_value,
            "limited_info": limited_info,
            "item_link": item_link,
            "item_image": item_image,
        }

        return item_data

    except Exception as e:
        logger.error(f"Error processing an item: {e}")
        return None


def process_category(category_num):
    return CATEGORY_DICT.get(category_num, "Unknown Category")


def process_sort(sort_num):
    return SORT_DICT.get(sort_num, "Unknown Sort Order")


class ItemType(str, Enum):
    all = "all"
    limited = "limited"
    limited_u = "limited_u"
    free = "free"


@app.get("/catalog")
async def get_catalog(
        session_cookie: str = Header(..., description="User session cookie"),
        secruity_cookie: str = Header(..., description="Security cookie"),
        user_agent: Optional[str] = None,
        q: Optional[str] = None,
        catergory: Optional[int] = Query(0, description="Category number", ge=0, le=len(CATEGORY_DICT) - 1),
        sort: Optional[int] = Query(0, description="Sort order number", ge=0, le=len(SORT_DICT) - 1),
        limit: Optional[int] = Query(10, description="Maximum number of results to return", gt=0),
        item_type: Optional[ItemType] = Query(ItemType.all, description="Item type to filter (all, limited, limited_u, free)")
):
    category_name = process_category(catergory)
    sort_name = process_sort(sort)

    # Use the provided user agent or choose a random one
    headers = {'User-Agent': user_agent or random.choice(USER_AGENTS),
               'Cookie': f'session={session_cookie}; .ROBLOSECURITY={secruity_cookie}'}

    with create_session(session_cookie, secruity_cookie, USER_AGENTS) as session:
        # Construct the base URL
        base_url = "https://www.syntax.eco/catalog/"

        # Construct the query parameters
        params = {
            'q': q,
            'catergory': catergory,
            'sort': sort,
            'limit': limit,
            'item_type': item_type.value if item_type else None,
        }

        # Remove parameters with None values
        params = {k: v for k, v in params.items() if v is not None}

        # Encode the query parameters
        query_string = urlencode(params)

        # Construct the search URL
        search_url = f"{base_url}?{query_string}" if query_string else base_url

        # Make a request to the search URL
        response = session.get(search_url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find the element containing information about total pages
            page_info = soup.find('p', class_='ms-2 me-2 text-white')
            total_pages = extract_total_pages(page_info.text) if page_info else 1

            data = []  # List to store item data

            for page_number in range(1, total_pages + 1):
                # Construct the URL for each page
                page_url = urljoin(search_url, f"{search_url}&page={page_number}")
                response = session.get(page_url)

                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    items = soup.find_all(class_='item-card')

                    for item in items:
                        processed_item = process_item(item)

                        # Filter by item type
                        if processed_item and (
                                item_type == ItemType.all or
                                (item_type == ItemType.limited and processed_item['limited_info']['type'] == 'limited') or
                                (item_type == ItemType.limited_u and processed_item['limited_info']['type'] == 'limited u') or
                                (item_type == ItemType.free and processed_item['item_price'] == 'Free')
                        ):
                            data.append(processed_item)

                            # Check if the limit is reached
                            if len(data) >= limit:
                                break

                    # Check if the limit is reached
                    if len(data) >= limit:
                        break

                else:
                    logger.error(f"Failed to fetch page {page_number}. Status Code: {response.status_code}")
                    return {"error": f"Failed to fetch page {page_number}. Status Code: {response.status_code}"}

            # Return the collected data with the limited number of results
            return {"data": data[:limit], "category": category_name, "sort": sort_name, "item_type": item_type}

        else:
            logger.error(f"Failed to fetch the search page. Status Code: {response.status_code}")
            return {"error": f"Failed to fetch the search page. Status Code: {response.status_code}"}
