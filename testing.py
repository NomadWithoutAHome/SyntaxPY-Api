import json
import logging
import re

from bs4 import BeautifulSoup
import requests

HTML_PARSER = 'html5lib'
INDENTATION = 2

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



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

def save_to_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, indent=INDENTATION, ensure_ascii=False)

def main():
    url = "https://www.syntax.eco/games/10174/My-Restaurant"
    cookies = {
        'session': 'eyJjc3JmX3Rva2VuIjoiZDY2NDNmZWY0MGM3MGFlNzVlMzUwMjAwNjhjYWZlY2VhY2FmNWIxOSJ9.ZWj0Kw.q-SqkE8K79409I0zbBX7Xqb76XY',
        '.ROBLOSECURITY': 'm0gqq1If80dtxp3NvhDMbs5unlY02UIpk6C1vBlps4ehFpyGsjurFgxJtnWD2IZNJANJLXEhB8uX3NKEPuaHzhpbFA8RAdgHdXlbhQeEx8JDYHg0ZxnZEHGEgK8p6sjFod6PpaaV05kfD7MPE3m4u4lU9X8LeotT09BRYWWfq10KQrxL1y4rtms1NU48YUcrkxJ9Aynyjk9EiduxvbPERUaS3L6EO8ddFuAxJOzLmBSuLrf1GoKslGuwBu5i8oa8LUeQ2u56C7PGfSHdLNcZLkHJK0QQrtD1SjqM1nbB67cPVp1nFyVZt6ZhqeXU28WjUayyKb6deDvHo5hctEbCSwNmhpqwSKW0iNtsvDkVGWQK4CueS49Gm2VZCzSwRvUbbrRLqODJ4kwZuR5yPbomFJyNs7r9McJqqMKjS14m1V5i00vsQdXMdiDrsQG0mUDIeKrZ8smz6iIrAK3LeKQy2YxTgcc8a5xfPL8hCdOVlysu04mteIBi1B3PBHB10Jzv',
    }

    try:
        response = requests.get(url, cookies=cookies)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to retrieve the page. Error: {e}")
        return

    soup = BeautifulSoup(response.content, HTML_PARSER)

    game_info = {
        "Game Title": soup.find('h1', class_='m-0').get_text(strip=True),
        "Creator Name": soup.find('p', class_='m-0').find('a').get_text(strip=True),
        "Favorites Count": int(soup.find('div', class_='icon-favorite').find_next('span', class_='text-favorite').get_text(strip=True)),
        "Likes Count": int(soup.find('div', class_='upvote').find_next('span', class_='vote-up-text').get_text(strip=True)),
        "Dislikes Count": int(soup.find('span', class_='vote-down-text').text),
        "Description": soup.find('div', class_='ms-2').get_text(strip=True),
        "Builder Club Required": "Yes" if soup.find('p', string='A Builders Club membership is required to join this game') else "No",
        "Thumbnail Source": soup.find('img', class_='rounded')['src'],
        "Active Players": int(soup.find('div', class_='col').find_next('h2').get_text(strip=True)),
        "Visits Count": int(soup.find('div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True)),
        "Created Date": soup.find('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True),
        "Updated Date": soup.find('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True),
        "Server Size": int(soup.find('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('div', class_='col').find_next('h2').get_text(strip=True))
    }

    game_passes = extract_game_passes(response.text)
    game_info["Game Passes"] = game_passes

    json_filename = "game_info.json"
    save_to_json(game_info, json_filename)

    logger.info(f"Information saved to {json_filename}")

if __name__ == "__main__":
    main()
