import os
import csv
import time
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

'''
Author: Alberto Montano Perez
Latest Date: 4/5/2025
Notes: This program only scrapes for a single card at the moment since this project never got far.
       If you wish to implement at a larger scale, add logic to iterate through listings from a home page.
       Make sure to test whether the website will allow for so many requests, if not you will have to find ways out such as a timer in between pulling data
       or using some proxy to get around timeouts.
'''

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Selectors
BUY_BOX_SELLER_XPATH = '//*[@id="app"]/div/div/section[2]/section/div/div[2]/section[2]/section[1]/div/section[3]'
BUY_BOX_QUANTITY_SELECTOR = '.add-to-cart__available'
BUY_BOX_CONDITION_SELECTOR = '.spotlight__condition'
BUY_BOX_PRICE_SELECTOR = '.spotlight__price'
BUY_BOX_SHIPPING_XPATH = '//*[@id="app"]/div/div/section[2]/section/div[2]/div[2]/section[2]/section[1]/div/section[2]/div/span'

SELLER_LISTING_CONTAINER_XPATH = 'div.product-details__listings-results section.listing-item'
SELLER_NAME_SELECTOR = ".seller-info__name"
SELLER_CONDITION_SELECTOR = '.listing-item__listing-data__info__condition a'
SELLER_PRICE_SELECTOR = '.listing-item__listing-data__info__price'
SELLER_QUANTITY_SELECTOR = ".add-to-cart__available"
SELLER_RATING_XPATH = ".//div[1]/div/div/div[1]"
TOTAL_SALES_XPATH = ".//div[1]/div/div/div[2]"
SHIPPING_PRICE_XPATH = ".//div[2]/div[2]"

NEXT_PAGE_BUTTON_XPATH = '/html/body/div[2]/div/div/section[2]/section/section[1]/section/section/section/div[2]/a[2]'

CSV_FILENAME = "_Test3.csv"

class TCGScraper:
    def __init__(self, website_link, location, driver=None):
        self.website_link = website_link
        self.location = location
        self.run_date = datetime.now().strftime("%Y-%m-%d")
        self.run_time = datetime.now().strftime("%H:%M:%S")
        self.driver = driver if driver else self.init_driver()
        self.verified_clicked = False

    def init_driver(self):
        options = Options()
        driver = webdriver.Firefox(options=options)
        driver.maximize_window()
        return driver

    def wait_for_element(self, by, locator, timeout=20):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, locator))
        )

    def get_element_text(self, by, locator, name):
        try:
            return self.driver.find_element(by, locator).text
        except NoSuchElementException:
            logging.warning("Can't find element: %s", name)
            return ""

    def get_buy_box_data(self):
        seller = self.get_element_text(By.XPATH, BUY_BOX_SELLER_XPATH, 'Buy Box Seller')
        if seller.startswith("Sold by "):
            seller = seller[len("Sold by "):]

        qty_txt = self.get_element_text(By.CSS_SELECTOR, BUY_BOX_QUANTITY_SELECTOR, 'Buy Box Quantity')
        qty = qty_txt.split()[-1] if qty_txt else ""
        cond = self.get_element_text(By.CSS_SELECTOR, BUY_BOX_CONDITION_SELECTOR, 'Buy Box Condition')
        price = self.get_element_text(By.CSS_SELECTOR, BUY_BOX_PRICE_SELECTOR, 'Buy Box Price')
        ship = self.get_element_text(By.XPATH, BUY_BOX_SHIPPING_XPATH, 'Buy Box Shipping')

        total_sales = "Not Available"
        hobby = gold = rating = "Not Available"

        try:
            self.driver.find_element(By.CSS_SELECTOR, ".spotlight__banner.direct")
            direct = "TRUE"
        except NoSuchElementException:
            direct = "FALSE"

        return [seller, cond, price, qty, direct, hobby, gold, rating, ship, total_sales]

    def safe_find_text(self, el, locator, name, by=By.CSS_SELECTOR):
        try:
            return el.find_element(by, locator).text
        except NoSuchElementException:
            logging.warning("Listing missing: %s", name)
            return ""

    def get_listing_data(self, listing, buy_box_name):
        name = self.safe_find_text(listing, SELLER_NAME_SELECTOR, "Seller Name")
        cond = self.safe_find_text(listing, SELLER_CONDITION_SELECTOR, "Condition")
        price = self.safe_find_text(listing, SELLER_PRICE_SELECTOR, "Price")
        qty_txt = self.safe_find_text(listing, SELLER_QUANTITY_SELECTOR, "Quantity")
        qty = qty_txt.split()[-1] if qty_txt else ""

        direct = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Direct Seller']") else "FALSE"
        hobby  = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Certified Hobby Shop']") else "FALSE"
        gold   = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Gold Star Seller']") else "FALSE"

        rating_txt = self.safe_find_text(listing, SELLER_RATING_XPATH, "Seller Rating", by=By.XPATH)
        sales_txt  = self.safe_find_text(listing, TOTAL_SALES_XPATH, "Total Sales", by=By.XPATH)
        sales = sales_txt.replace("(", "").replace(")", "") if sales_txt else "Not Available"
        ship = self.safe_find_text(listing, SHIPPING_PRICE_XPATH, "Shipping Price", by=By.XPATH)

        is_bb = (name == buy_box_name)
        return [name, cond, price, qty, direct, hobby, gold, rating_txt, ship, sales, is_bb]

    def save_to_csv(self, rows):
        exists = os.path.isfile(CSV_FILENAME)
        with open(CSV_FILENAME, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if not exists:
                w.writerow([
                    'Card Name','Seller Name','Condition','Price','Quantity Available',
                    'Is Direct Seller','Is Hobby Shop','Is Gold Star Seller',
                    'Seller Rating','Shipping Price','Total Sales','Is Buy Box Seller',
                    'Date','Time','VPN Location'
                ])
            for r in rows:
                w.writerow(r + [self.run_date, self.run_time, self.location])

    def click_checkboxes(self):
        if not self.verified_clicked:
            try: 
                for cid in ['verified-seller-filter']:
                    cb = self.driver.find_element(By.ID, cid)
                    self.driver.execute_script("arguments[0].click()", cb)
                    time.sleep(1)
                    logging.info("Verified Seller filters applied.")
                    self.verified_clicked = True
            except Exception as e:
                logging.error("Filter error: %s", e)
        try:
            for xp in ['//*[@id="Printing-Normal-filter"]']:
                cb = self.driver.find_element(By.XPATH, xp)
                self.driver.execute_script("arguments[0].click()", cb)
                time.sleep(1)
            logging.info("Normal printing filters applied.")
        except Exception as e:
            logging.error("Filter error: %s", e)

    def scrape(self):
        try:
            self.driver.get(self.website_link)
            self.wait_for_element(By.XPATH, '//*[@id="app"]/div/div/section[2]/section/div/div[2]/div/h1')
            card = self.get_element_text(
                By.XPATH,
                '//*[@id="app"]/div/div/section[2]/section/div/div[2]/div/h1',
                "Card Name"
            )
            logging.info("Scraping %s", card)

            self.click_checkboxes()

            # buy box
            bb = self.get_buy_box_data()
            bb_name = bb[0]
            self.save_to_csv([[card] + bb + [True]])

            # listing pages loop
            page_number = 1
            while True:
                listings = self.driver.find_elements(By.CSS_SELECTOR, SELLER_LISTING_CONTAINER_XPATH)
                data = [[card] + self.get_listing_data(l, bb_name) for l in listings]
                self.save_to_csv(data)
                logging.info("Scraped listing page %d", page_number)

                try:
                    nxt = self.driver.find_element(By.XPATH, NEXT_PAGE_BUTTON_XPATH)
                    disabled = (
                        nxt.get_attribute("aria-disabled") == "true"
                    )
                    if disabled:
                        logging.info("Next is disabled; done.")
                        break
                    nxt.click()
                    self.wait_for_element(By.CSS_SELECTOR, SELLER_LISTING_CONTAINER_XPATH)
                    time.sleep(2)
                    page_number += 1
                except NoSuchElementException:
                    logging.info("No Next button; done.")
                    break

            logging.info("Finished scraping %s", card)
        except Exception as e:
            logging.error("Error in scrape(): %s", e)
            raise

def main():
    VPN = "Las Vegas"
    urls = [
        "https://www.tcgplayer.com/product/576520/magic-duskmourn-house-of-horror-hushwood-verge?page=1&Language=English",
        "https://www.tcgplayer.com/product/576530/magic-duskmourn-house-of-horror-thornspire-verge?Language=English&page=1",
        "https://www.tcgplayer.com/product/576512/magic-duskmourn-house-of-horror-blazemire-verge?page=1&Language=English",
        "https://www.tcgplayer.com/product/576518/magic-duskmourn-house-of-horror-gloomlake-verge?Language=English&page=1",
        "https://www.tcgplayer.com/product/576514/magic-duskmourn-house-of-horror-floodfarm-verge?page=1&Language=English",
        "https://www.tcgplayer.com/product/592008/lorcana-tcg-azurite-sea-sail-the-azurite-sea?Language=English&page=1",
        "https://www.tcgplayer.com/product/506836/lorcana-tcg-the-first-chapter-rapunzel-gifted-with-healing?Language=English&page=1",
        "https://www.tcgplayer.com/product/561975/lorcana-tcg-shimmering-skies-pete-games-referee?Language=English&page=1",
        "https://www.tcgplayer.com/product/538726/lorcana-tcg-into-the-inklands-ursula-deceiver-of-all?Language=English&page=1",
        "https://www.tcgplayer.com/product/527238/lorcana-tcg-rise-of-the-floodborn-strength-of-a-raging-fire?Language=English&page=1",
        "https://www.tcgplayer.com/product/488071/pokemon-sv01-scarlet-and-violet-base-set-arven-166-198?page=1&Language=English",
        "https://www.tcgplayer.com/product/632946/pokemon-sv10-destined-rivals-arvens-mabosstiff-ex-139-182?Language=English&page=1",
        "https://www.tcgplayer.com/product/560372/pokemon-sv-shrouded-fable-night-stretcher?page=1&Language=English",
        "https://www.tcgplayer.com/product/632982/pokemon-sv10-destined-rivals-team-rockets-energy?Language=English&page=1",
        "https://www.tcgplayer.com/product/630823/pokemon-sv10-destined-rivals-marnies-grimmsnarl-ex?Language=English&page=1"
    ]

    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds

    # initialize one browser instance
    options = Options()
    driver = webdriver.Firefox(options=options)
    driver.maximize_window()
    scraper = TCGScraper(None, VPN, driver)

    for url in urls:
        attempts = 0
        while attempts < MAX_RETRIES:
            logging.info("Starting scrape for %s (attempt %d/%d)", url, attempts+1, MAX_RETRIES)
            scraper.website_link = url
            try:
                scraper.scrape()
                break
            except Exception:
                attempts += 1
                if attempts < MAX_RETRIES:
                    logging.info("Retrying %s in %d seconds…", url, RETRY_DELAY)
                    time.sleep(RETRY_DELAY)
                else:
                    logging.error("Skipping %s after %d failures.", url, attempts)
        time.sleep(15)

    #driver.quit()

if __name__ == "__main__":
    main()
