import os
import csv
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

try:
    UTC = ZoneInfo("UTC")
except ZoneInfoNotFoundError as e:
    logging.warning("UTC time zone not found. Defaulting to UTC: %s", e)
    UTC = timezone.utc
TIMESTAMP = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")

# Logging
LOG_FILENAME = f"debug_{TIMESTAMP}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def get_location():
    """Return the user's location using ipinfo.io or 'Unknown' if unavailable."""
    try:
        resp = requests.get("https://ipinfo.io/json", timeout=5)
        resp.raise_for_status()
        info = resp.json()
        city = info.get("city")
        region = info.get("region")
        if city and region:
            return f"{city}, {region}"
        return region or city or "Unknown"
    except Exception as e:
        logging.warning("Location detection failed: %s", e)

# Selectors and constants remain the same...
CSV_FILENAME = f"{TIMESTAMP}_Cards_Main.csv"

class TCGScraper:
    def __init__(self, website_link, location, driver=None):
        self.website_link = website_link
        self.location = location
        self.run_date = datetime.now(UTC).strftime("%Y-%m-%d")
        self.run_time = datetime.now(UTC).strftime("%H:%M:%S")
        self.driver = driver if driver else self.init_driver()
        self.verified_clicked = False
        self.page_size_set = False

    def init_driver(self):
        options = Options()
        options.headless = True
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
        try:
            spotlight = self.driver.find_element(By.CLASS_NAME, "spotlight")
            logging.info("Buy Box found.")
        except NoSuchElementException:
            logging.warning("No Buy Box found.")
        seller = self.get_element_text(By.CLASS_NAME, 'spotlight__seller', 'Buy Box Seller')
        if seller.startswith("Sold by "):
            seller = seller[len("Sold by "):]

        # quantity from spotlight seller is also a bit wonky
        qty_txt = ""
        try:
            qty_el = WebDriverWait(spotlight, 15).until(
                lambda el: el.find_element(By.CSS_SELECTOR, "span.add-to-cart__available")
            )
            qty_txt = qty_el.text.strip()
        except TimeoutException:
            logging.warning("Can't find element: Buy Box Quantity")
        qty = qty_txt.split()[-1] if qty_txt else ""
        cond = self.get_element_text(By.CSS_SELECTOR, '.spotlight__condition', 'Buy Box Condition')
        price = self.get_element_text(By.CSS_SELECTOR, '.spotlight__price', 'Buy Box Price')
        ship = self.get_element_text(By.CSS_SELECTOR, '.spotlight__shipping', 'Buy Box Shipping')

        # these are not present in the buybox, we will find them from the regular seller listings below
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
        name = self.safe_find_text(listing, ".seller-info__name", "Seller Name")
        cond = self.safe_find_text(listing, '.listing-item__listing-data__info__condition a', "Condition")
        price = self.safe_find_text(listing, '.listing-item__listing-data__info__price', "Price")
        qty_txt = self.safe_find_text(listing, ".add-to-cart__available", "Quantity")
        qty = qty_txt.split()[-1] if qty_txt else ""

        direct = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Direct Seller']") else "FALSE"
        hobby  = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Certified Hobby Shop']") else "FALSE"
        gold   = "TRUE" if listing.find_elements(By.CSS_SELECTOR, "img[alt='Gold Star Seller']") else "FALSE"

        rating_txt = self.safe_find_text(listing, ".seller-info__rating", "Seller Rating")
        sales_txt  = self.safe_find_text(listing, ".seller-info__sales", "Total Sales")
        sales = sales_txt.replace("(", "").replace(")", "") if sales_txt else "Not Available"
        # this element doesnt have a unique class, so we have to use try to find an element that has the word shipping in it
        # even items with free shipping have that text in an element
        ship = ""
        try:
            # Prefer scoping to the info block that contains condition/price/shipping
            info = listing.find_element(By.CSS_SELECTOR, ".listing-item__listing-data__info")
        except NoSuchElementException:
            info = listing  # fallback

        # 1) Try: find a leaf-ish span containing "shipping" (case-insensitive)
        ship = self.safe_find_text(
            info,
            ".//span[contains(translate(normalize-space(.), 'SHIPPING', 'shipping'), 'shipping')]",
            "Shipping Price",
            by=By.XPATH
        ).strip()

        # 2) Fallback: any element containing "shipping" (in case it's not a span)
        if not ship:
            ship = self.safe_find_text(
                info,
                ".//*[contains(translate(normalize-space(.), 'SHIPPING', 'shipping'), 'shipping')]",
                "Shipping Price (fallback)",
                by=By.XPATH
            ).strip()

        # Optional: normalize if you want "Free Shipping" -> "0" or similar (leave as text if not)
        # if ship and "free" in ship.lower() and "shipping" in ship.lower():
        #     ship = "Free Shipping"
        # --- end Shipping ---

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
                    'Date','Time (UTC)','VPN Location'
                ])
            for r in rows:
                w.writerow(r + [self.run_date, self.run_time, self.location])

    def set_listings_per_page_50(self, timeout=10):
        wait = WebDriverWait(self.driver, timeout)

        # 1) Locate the specific toolbar section for "listings per page"
        container = wait.until(EC.presence_of_element_located((
            By.CLASS_NAME,
            'product-details__listings-toolbar__options-listings-per-page'
        )))
        logging.info("Listings per page container found.")

        # 2) Find the combobox trigger INSIDE this container (generic again)
        trigger = wait.until(lambda d: container.find_element(
            By.CSS_SELECTOR,
            ".tcg-input-select__trigger[role='combobox'][aria-controls]"
        ))

        # 3) Open dropdown if needed
        if trigger.get_attribute("aria-expanded") != "true":
            # Some UIs only open reliably by clicking the toggle button
            try:
                btn = container.find_element(By.CSS_SELECTOR, "button[aria-label='Toggle listbox']")
                self.driver.execute_script("arguments[0].click()", btn)
            except Exception:
                self.driver.execute_script("arguments[0].click()", trigger)

            wait.until(lambda d: trigger.get_attribute("aria-expanded") == "true")

        # 4) Locate listbox by the ID provided in aria-controls (do NOT assume it's inside container)
        listbox_id = trigger.get_attribute("aria-controls")

        listbox = wait.until(EC.presence_of_element_located((By.ID, listbox_id)))

        # 5) Click option 50 by aria-label or text
        opt50 = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            f"//ul[@id='{listbox_id}' and @role='listbox']"
            f"//li[@role='option' and (@aria-label='50' or normalize-space(.)='50')]"
        )))
        self.driver.execute_script("arguments[0].click()", opt50)

        # 6) Confirm selection applied
        wait.until(lambda d: trigger.text.strip() == "50")
        logging.info("Listings per page set to 50.")
    
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

        # set listings per page to 50 to speed up scraping
        if not self.page_size_set:
            try:
                self.set_listings_per_page_50(timeout=10)
                logging.info("Page size set to 50.")
                self.page_size_set = True
            except Exception as e:
                logging.error("Page size selection error: %s", e)
            
        # Normal printing filter is currently disabled
        #try:
        #    for xp in ['//*[@id="Printing-Normal-filter"]']:
        #        cb = self.driver.find_element(By.XPATH, xp)
        #        self.driver.execute_script("arguments[0].click()", cb)
        #        time.sleep(1)
        #       logging.info("Normal printing filters applied.")
        #except Exception as e:
        #    logging.error("Filter error: %s", e)

    def scrape(self):
        try:
            self.driver.get(self.website_link)
            self.wait_for_element(By.CLASS_NAME, 'product-details__name')
            card = self.get_element_text(
                By.CLASS_NAME,
                'product-details__name',
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
                listings = self.driver.find_elements(By.CSS_SELECTOR, "div.product-details__listings-results section.listing-item")
                data = [[card] + self.get_listing_data(l, bb_name) for l in listings]
                self.save_to_csv(data)
                logging.info("Scraped listing page %d", page_number)

                try:
                    nxt = WebDriverWait(self.driver, 20).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[aria-label='Next page']"))
                    )
                    if nxt.get_attribute("aria-disabled") == "true":
                        logging.info("Next is disabled; done.")
                        break
                    nxt.click()
                    self.wait_for_element(By.CSS_SELECTOR, "div.product-details__listings-results section.listing-item")
                    time.sleep(2)
                    page_number += 1
                except (NoSuchElementException, TimeoutException):
                    logging.info("No Next button; done.")
                    break

            logging.info("Finished scraping %s", card)
        except Exception as e:
            logging.error("Error in scrape(): %s", e)
            raise

def main():
    VPN = get_location()
    logging.info("Using detected location: %s", VPN)
    urls = [
        "https://www.tcgplayer.com/product/576520/magic-duskmourn-house-of-horror-hushwood-verge?page=1&Language=English",        #magic
        "https://www.tcgplayer.com/product/576530/magic-duskmourn-house-of-horror-thornspire-verge?Language=English&page=1",
        "https://www.tcgplayer.com/product/576512/magic-duskmourn-house-of-horror-blazemire-verge?page=1&Language=English",
        "https://www.tcgplayer.com/product/576518/magic-duskmourn-house-of-horror-gloomlake-verge?Language=English&page=1",
        "https://www.tcgplayer.com/product/576514/magic-duskmourn-house-of-horror-floodfarm-verge?page=1&Language=English",
        "https://www.tcgplayer.com/product/592008/lorcana-tcg-azurite-sea-sail-the-azurite-sea?Language=English&page=1",       #lorcana
        "https://www.tcgplayer.com/product/506836/lorcana-tcg-the-first-chapter-rapunzel-gifted-with-healing?Language=English&page=1",
        "https://www.tcgplayer.com/product/561975/lorcana-tcg-shimmering-skies-pete-games-referee?Language=English&page=1",
        "https://www.tcgplayer.com/product/538726/lorcana-tcg-into-the-inklands-ursula-deceiver-of-all?Language=English&page=1",
        "https://www.tcgplayer.com/product/527238/lorcana-tcg-rise-of-the-floodborn-strength-of-a-raging-fire?Language=English&page=1",
        "https://www.tcgplayer.com/product/488071/pokemon-sv01-scarlet-and-violet-base-set-arven-166-198?page=1&Language=English",       #pokemon
        "https://www.tcgplayer.com/product/632946/pokemon-sv10-destined-rivals-arvens-mabosstiff-ex-139-182?Language=English&page=1",
        "https://www.tcgplayer.com/product/560372/pokemon-sv-shrouded-fable-night-stretcher?page=1&Language=English",
        "https://www.tcgplayer.com/product/632982/pokemon-sv10-destined-rivals-team-rockets-energy?Language=English&page=1",
        "https://www.tcgplayer.com/product/630823/pokemon-sv10-destined-rivals-marnies-grimmsnarl-ex?Language=English&page=1"
    ]
    MAX_RETRIES = 3
    RETRY_DELAY = 5 

    options = Options()
    options.headless = True
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

    driver.quit()

if __name__ == "__main__":
    main()
