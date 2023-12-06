from enum import Enum
import logging
from contextlib import contextmanager

from aiohttp import ClientSession
from fastapi import FastAPI, Query, Header, HTTPException
from bs4 import BeautifulSoup
import requests
import random
import re
from urllib.parse import urljoin, urlencode
from typing import Optional, List, Dict

HTML_PARSER = 'html5lib'
INDENTATION = 2

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

async def fetch_page(session: ClientSession, url: str) -> List[Dict]:
    async with session.get(url) as response:
        if response.status == 200:
            soup = BeautifulSoup(await response.text(), 'html5lib')
            items = soup.find_all(class_='item-card')
            return items  

        logger.error(f"Failed to fetch page {url}. Status Code: {response.status}")
        return []

async def get_catalog_page(session: ClientSession, search_url: str, limit: int, item_type: ItemType) -> List[Dict]:
    data = []  # List to store item data

    # Asynchronously fetch the first page to extract total pages
    async with session.get(search_url) as response:
        if response.status == 200:
            soup = BeautifulSoup(await response.text(), 'html.parser')
            page_info = soup.find('p', class_='ms-2 me-2 text-white')
            total_pages = extract_total_pages(page_info.text) if page_info else 1
        else:
            return data  # Return empty data if the first page fails to load

    # Asynchronously fetch each page and process items
    for page_number in range(1, total_pages + 1):
        page_url = f"{search_url}&page={page_number}"
        items = await fetch_page(session, page_url)

        for item in items:
            processed_item = process_item(item)  # Ensure process_item is suitable for your data structure

            # Filter by item type
            if processed_item and item_type_filter(processed_item, item_type):
                data.append(processed_item)

                # Check if the limit is reached after each item is processed
                if len(data) >= limit:
                    return data[:limit]

    return data

# It's a good practice to separate the filtering logic into its own function
def item_type_filter(processed_item: Dict, item_type: ItemType) -> bool:
    return (
        item_type == ItemType.all or
        (item_type == ItemType.limited and processed_item['limited_info']['type'] == 'limited') or
        (item_type == ItemType.limited_u and processed_item['limited_info']['type'] == 'limited u') or
        (item_type == ItemType.free and processed_item['item_price'] == 'Free')
    )

@app.get("/catalog")
async def get_catalog(
    session_cookie: str = Header('eyJjc3JmX3Rva2VuIjoiYmE0NDQ3MDUzM2FhNzFjOTZiMjQ3NjRlYmM4ZDJjNzAwMDU4NTY5MCJ9.ZW_8EA.Pw1spJO8Mss-8D7r18A71-a72to', description="User session cookie"),
    security_cookie: str = Header('sAnHbclLJht1JilJR17QvWo9uHc2sqdLy61dB5RWKlZhAHlJ6SAT3epf3I5V992QzeX07K1y3wqAKIkb0N9L8SzHDez6wj2SqqKGw8DZCOXOn0y6Yhu9xIsiLV0b665GD5dUXqQq0T4EFXmsRy4fFkcASElaVGFpDsrK2zJ9vGuqkYWSIVWM0NWaW3eEdavemkqaikR9oltRKLGUu2y0Ub8iPuVqdsCs3nerpLbA9XCN5ZbaALJ4TbRfUDUNjl1sdK3SfsYup7LyysQTQqQmWYLikYHvHaGkhtFDREApkKQMKvRqIstt2PnsXH4uYFJtVkxbIAonRpyFcqoaAz6kYBuHovDMES61rq8WW65LFUJFgndcpiWb0liCw7N5KziQuA5m3OerXrrp3ELB0cxQnmr1GjqVlxRb7OvC9YlRJ4kjWqnSFxEMIyPXjoxfGcPeGevC3cKMhJprDH8KkF6hu1BZDldllTKfIEgq5tn55dZFcxEK2xfChJSDnkJwR4Tz', description="Security cookie"),
    user_agent: Optional[str] = Header(None, description="User agent string"),
    q: Optional[str] = None,
    category: Optional[int] = Query(0, description="Category number", ge=0, le=len(CATEGORY_DICT) - 1),
    sort: Optional[int] = Query(0, description="Sort order number", ge=0, le=len(SORT_DICT) - 1),
    limit: Optional[int] = Query(10, description="Maximum number of results to return", gt=0),
    item_type: Optional[ItemType] = Query(ItemType.all, description="Item type to filter (all, limited, limited_u, free)")
):
    category_name = process_category(category)
    sort_name = process_sort(sort)

    # Set up the headers with the session and security cookies
    headers = {
        'User-Agent': user_agent,
        'Cookie': f'.ROBLOSECURITY={security_cookie}; session={session_cookie}'
    }

    # Create an aiohttp ClientSession with the headers
    async with ClientSession(headers=headers) as session:
        # Construct the base URL
        base_url = "https://www.syntax.eco/catalog/"

        # Construct the query parameters
        params = {
            'q': q,
            'category': category,
            'sort': sort,
            'limit': limit,
            'item_type': item_type.value if item_type else None,
        }

        # Remove parameters with None values
        params = {k: v for k, v in params.items() if v is not None}

        # Construct the search URL with query parameters
        search_url = f"{base_url}?{urlencode(params)}" if params else base_url

        # Make a GET request to the search URL
        async with session.get(search_url) as response:
            if response.status == 200:
                # Parse the response content if needed
                # soup = BeautifulSoup(await response.text(), 'html.parser')

                # Use the function to handle pagination
                data = await get_catalog_page(session, search_url, limit, item_type)

                # Return the collected data with the limited number of results
                return {"data": data, "category": category_name, "sort": sort_name, "item_type": item_type}
            else:
                logger.error(f"Failed to fetch the search page. Status Code: {response.status}")
                return {"error": f"Failed to fetch the search page. Status Code: {response.status}"}

def extract_game_passes(response_text):
    soup = BeautifulSoup(response_text, HTML_PARSER)

    game_pass_container = soup.find('div', class_='tab-pane', id='nav-store')

    if game_pass_container:
        game_passes = []
        for game_pass in game_pass_container.find_all('div', class_='p-1'):
            image = game_pass.find('img')['src']
            name = game_pass.find('h5').text
            price_text = game_pass.find('p', class_='text-robux').text.strip()

            # Use regex to remove "R$" from the price
            price = re.sub(r'[^\d.]', '', price_text)

            game_passes.append({
                'image': image,
                'name': name,
                'price': price
            })

        return game_passes
    else:
        return []


def process_game_details(game):
    try:
        game_title = game.find('h1', class_='m-0').get_text(strip=True)
        creator_name = game.find('p', class_='m-0').find('a').get_text(strip=True)
        favorites_count = int(
            game.find('div', class_='icon-favorite').find_next('span', class_='text-favorite').get_text(strip=True))
        likes_count = int(
            game.find('div', class_='upvote').find_next('span', class_='vote-up-text').get_text(strip=True))
        dislikes_count = int(game.find('span', class_='vote-down-text').text)
        description = game.find('div', class_='ms-2').get_text(strip=True)
        builder_club_required = "Yes" if game.find('p',
                                                   string='A Builders Club membership is required to join this game') else "No"
        thumbnail_source = game.find('img', class_='rounded')['src']
        active_players = int(game.find('div', class_='col').find_next('h2').get_text(strip=True))
        visits_count = int(
            game.find('div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True))
        created_date = game.find('div', class_='col').find_next('div', class_='col').find_next('div',
                                                                                               class_='col').find_next(
            'h2').get_text(strip=True)
        updated_date = game.find('div', class_='col').find_next('div', class_='col').find_next('div',
                                                                                               class_='col').find_next(
            'div', class_='col').find_next('h2').get_text(strip=True)
        server_size = int(
            game.find('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next(
                'div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True))

        game_passes = extract_game_passes(game.prettify())

        game_info = {
            "Game Title": game_title,
            "Creator Name": creator_name,
            "Favorites Count": favorites_count,
            "Likes Count": likes_count,
            "Dislikes Count": dislikes_count,
            "Description": description,
            "Builder Club Required": builder_club_required,
            "Thumbnail Source": thumbnail_source,
            "Active Players": active_players,
            "Visits Count": visits_count,
            "Created Date": created_date,
            "Updated Date": updated_date,
            "Server Size": server_size,
            "Game Passes": game_passes,
        }

        return game_info

    except Exception as e:
        logger.error(f"Error processing game details: {e}")
        return None


async def get_game_page(session: ClientSession, url: str, limit: int) -> List:
    data = []  # List to store detailed game information
    async with session.get(url) as response:
        if response.status == 200:
            content = await response.text()
            soup = BeautifulSoup(content, 'html5lib')

            # Find the element containing information about total pages
            page_info = soup.find('p', class_=re.compile('m-0 ms-2 me-2 text-white'))
            total_pages = extract_total_pages(page_info.text) if page_info else 1

            for page_number in range(1, total_pages + 1):
                if len(data) >= limit:
                    break  # Exit the loop if the limit is reached

                page_url = f"{url}?page={page_number}"
                async with session.get(page_url) as games_page_response:
                    games_page_content = await games_page_response.text()
                    games_page_soup = BeautifulSoup(games_page_content, 'html5lib')

                    games = games_page_soup.find_all('a', class_='text-decoration-none p-1 col-xxl-2 col-lg-3 col-md-4 col-sm-6')

                    for game in games:
                        if len(data) >= limit:
                            break  # Exit the loop if the limit is reached

                        game_url_relative = game.get('href', '').strip()
                        game_url = f"https://www.syntax.eco{game_url_relative}" if game_url_relative else None

                        async with session.get(game_url) as game_page_response:
                            game_page_content = await game_page_response.text()
                            game_page_soup = BeautifulSoup(game_page_content, 'html5lib')

                            # Process the game details
                            processed_game = process_game_details(game_page_soup)

                            if processed_game:
                                data.append(processed_game)
        else:
            logger.error(f"Failed to fetch the game page {url}. Status Code: {response.status}")

    return data[:limit]  # Return the data up to the limit


@app.get("/games")
async def get_games(
    session_cookie: str = Header('eyJjc3JmX3Rva2VuIjoiYmE0NDQ3MDUzM2FhNzFjOTZiMjQ3NjRlYmM4ZDJjNzAwMDU4NTY5MCJ9.ZW_8EA.Pw1spJO8Mss-8D7r18A71-a72to', description="User session cookie"),
    security_cookie: str = Header('sAnHbclLJht1JilJR17QvWo9uHc2sqdLy61dB5RWKlZhAHlJ6SAT3epf3I5V992QzeX07K1y3wqAKIkb0N9L8SzHDez6wj2SqqKGw8DZCOXOn0y6Yhu9xIsiLV0b665GD5dUXqQq0T4EFXmsRy4fFkcASElaVGFpDsrK2zJ9vGuqkYWSIVWM0NWaW3eEdavemkqaikR9oltRKLGUu2y0Ub8iPuVqdsCs3nerpLbA9XCN5ZbaALJ4TbRfUDUNjl1sdK3SfsYup7LyysQTQqQmWYLikYHvHaGkhtFDREApkKQMKvRqIstt2PnsXH4uYFJtVkxbIAonRpyFcqoaAz6kYBuHovDMES61rq8WW65LFUJFgndcpiWb0liCw7N5KziQuA5m3OerXrrp3ELB0cxQnmr1GjqVlxRb7OvC9YlRJ4kjWqnSFxEMIyPXjoxfGcPeGevC3cKMhJprDH8KkF6hu1BZDldllTKfIEgq5tn55dZFcxEK2xfChJSDnkJwR4Tz', description="Security cookie"),
    user_agent: Optional[str] = Header(None, description="User agent string"),
    q: Optional[str] = None,
    limit: Optional[int] = Query(10, description="Maximum number of results to return", gt=0),
):
    # Set up the headers with the session and security cookies
    headers = {
        'User-Agent': user_agent,
        'Cookie': f'.ROBLOSECURITY={security_cookie}; session={session_cookie}'
    }

    # Create an aiohttp ClientSession with the headers
    async with ClientSession(headers=headers) as session:
        # Construct the base URL
        base_url = "https://www.syntax.eco/games/popular/view"

        # Construct the query parameters
        params = {
            'q': q,
            'limit': limit,
        }

        # Remove parameters with None values
        params = {k: v for k, v in params.items() if v is not None}

        # Construct the search URL with query parameters
        search_url = f"{base_url}?{urlencode(params)}" if params else base_url
        logger.info("Cookies before request:")
        for cookie in session.cookie_jar:
            logger.info(
                f"Name: {cookie.key}, Value: {cookie.value}, Domain: {cookie['domain']}, Path: {cookie['path']}")
        # Use the new async function to handle pagination and fetch game details
        data = await get_game_page(session, search_url, limit)

        # Return the collected data with the limited number of results
        return {"data": data, "query": q}