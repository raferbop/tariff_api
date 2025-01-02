import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time
from dataclasses import dataclass
from typing import List, Optional
import logging

from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .database import SessionLocal, FXRate as FXRateModel
from config.config import Config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class FXRate:
    date: datetime.date
    currency: str
    buying_rate: float
    selling_rate: float
    timestamp: datetime

def get_last_business_day(current_date=None, country=None):
    """
    Get the last business day, taking into account weekends and holidays.
    
    Args:
        current_date: Date to start from (defaults to today)
        country: Country name to check holidays for
    
    Returns:
        datetime.date: Last business day
    """
    if current_date is None:
        current_date = datetime.now(Config.get_timezone(country)).date()
    
    check_date = current_date
    while True:
        # If it's Monday, go back to Friday
        if check_date.weekday() == 0:  # Monday
            check_date -= timedelta(days=3)
        else:
            check_date -= timedelta(days=1)
        
        # Check if it's a business day (not weekend and not holiday)
        if check_date.weekday() < 5 and not Config.is_holiday(check_date, country):
            return check_date
            
        # Safety check to prevent infinite loop
        if (current_date - check_date).days > 10:
            logger.error("Could not find a business day in the last 10 days")
            return current_date

def setup_driver() -> webdriver.Chrome:
    """Configure and initialize Chrome WebDriver"""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(Config.PAGE_LOAD_TIMEOUT)
        
        logger.info("Chrome WebDriver initialized successfully")
        return driver
    
    except Exception as e:
        logger.error(f"Failed to initialize WebDriver: {str(e)}")
        raise

def apply_filters(driver: webdriver.Chrome, date: datetime.date) -> bool:
    """Apply date filters and show all entries"""
    try:
        logger.info(f"Applying filters for date: {date}")
        
        # Wait for filter box
        WebDriverWait(driver, Config.ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "filterBox_table_1"))
        )
        
        # Set date filters
        date_str = date.strftime("%d %b %Y")
        for filter_id in ["table_1_range_from_0", "table_1_range_to_0"]:
            date_input = WebDriverWait(driver, Config.ELEMENT_WAIT_TIMEOUT).until(
                EC.element_to_be_clickable((By.ID, filter_id))
            )
            driver.execute_script('''
                arguments[0].value = "";
                arguments[0].dispatchEvent(new Event("change"));
                arguments[0].value = arguments[1];
                arguments[0].dispatchEvent(new Event("change"));
            ''', date_input, date_str)
        
        # Set show all entries
        show_all_script = '''
            var select = document.querySelector('select[name="table_1_length"]');
            if(select) {
                select.value = "-1";
                select.dispatchEvent(new Event("change", { bubbles: true }));
            }
        '''
        driver.execute_script(show_all_script)
        
        # Click search button
        search_button = WebDriverWait(driver, Config.ELEMENT_WAIT_TIMEOUT).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "wdt-pf-search-filters-button"))
        )
        search_button.click()
        
        # Wait for table update
        WebDriverWait(driver, Config.ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table#table_1 tbody tr"))
        )
        
        time.sleep(Config.DATA_LOAD_WAIT)
        return True
        
    except Exception as e:
        logger.error(f"Error applying filters: {str(e)}")
        return False

def scrape_fx_rates(date: datetime.date, country: str = None) -> List[FXRate]:
    """Scrape FX rates for the given date"""
    driver = None
    
    for attempt in range(Config.MAX_RETRIES):
        try:
            logger.info(f"Scraping attempt {attempt + 1} for date: {date}")
            
            driver = setup_driver()
            driver.get(Config.BOJ_URL)
            
            if not apply_filters(driver, date):
                raise Exception("Failed to apply filters")
            
            # Parse table
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            table = soup.find('table', {'id': 'table_1'})
            if not table:
                raise Exception("FX rates table not found")
            
            rows = table.find_all('tr')
            logger.info(f"Found {len(rows)-1} rows in table")
            
            fx_rates = []
            current_timestamp = datetime.now(Config.get_timezone(country))
            
            for row in rows[1:]:  # Skip header
                try:
                    cols = row.find_all('td')
                    if len(cols) != 4:
                        continue
                    
                    currency = ' '.join(cols[1].text.strip().split())
                    buying_rate_str = cols[2].text.strip()
                    selling_rate_str = cols[3].text.strip()
                    
                    if not all([currency, buying_rate_str, selling_rate_str]):
                        continue
                    
                    buying_rate = float(buying_rate_str.replace(',', ''))
                    selling_rate = float(selling_rate_str.replace(',', ''))
                    
                    fx_rates.append(FXRate(
                        date=date,
                        currency=currency,
                        buying_rate=buying_rate,
                        selling_rate=selling_rate,
                        timestamp=current_timestamp
                    ))
                    
                except Exception as e:
                    logger.warning(f"Error processing row: {str(e)}")
                    continue
            
            if not fx_rates:
                raise Exception("No valid FX rates found")
            
            logger.info(f"Successfully scraped {len(fx_rates)} FX rates")
            return fx_rates
            
        except Exception as e:
            logger.error(f"Scraping attempt {attempt + 1} failed: {str(e)}")
            if attempt < Config.MAX_RETRIES - 1:
                time.sleep(Config.RETRY_DELAY_SECONDS)
                continue
            logger.error("Max retries reached, scraping failed")
            return []
            
        finally:
            if driver:
                driver.quit()

def save_to_database(rates: List[FXRate]) -> tuple[int, int]:
    """
    Save scraped FX rates to database
    
    Args:
        rates: List of FXRate objects containing scraped data
        
    Returns:
        tuple: (number of rates saved, number of rates skipped)
    """
    if not rates:
        logger.warning("No rates to save")
        return 0, 0
        
    db = SessionLocal()
    saved_count = 0
    skipped_count = 0
    
    try:
        for rate in rates:
            try:
                # Check for existing rate
                existing = db.query(FXRateModel).filter_by(
                    date=rate.date,
                    currency=rate.currency
                ).first()
                
                if existing:
                    logger.debug(f"Rate already exists for {rate.currency} on {rate.date}")
                    skipped_count += 1
                    continue
                
                # Create new rate record
                db_rate = FXRateModel(
                    date=rate.date,
                    currency=rate.currency,
                    buying_rate=rate.buying_rate,
                    selling_rate=rate.selling_rate,
                    timestamp=rate.timestamp
                )
                db.add(db_rate)
                db.commit()
                saved_count += 1
                
            except IntegrityError:
                db.rollback()
                skipped_count += 1
                logger.warning(f"Duplicate rate for {rate.currency}")
            except Exception as e:
                db.rollback()
                skipped_count += 1
                logger.error(f"Error saving rate for {rate.currency}: {str(e)}")
                
        logger.info(f"Successfully saved {saved_count} rates, skipped {skipped_count} rates")
        return saved_count, skipped_count
        
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        return 0, len(rates)
    finally:
        db.close()

# Add this function to fx_rates_scraper.py, just before the main() function

async def check_and_update_fx_rates(db: Session) -> None:
    """
    Check and update FX rates in the database.
    This function is used by FastAPI endpoints to trigger FX rate updates.
    
    Args:
        db: SQLAlchemy database session
        
    Raises:
        Exception: If FX rate update process fails
    """
    try:
        country = Config.DEFAULT_COUNTRY
        current_date = datetime.now(Config.get_timezone(country)).date()
        
        if Config.is_holiday(current_date, country):
            holiday_name = Config.get_holiday_name(current_date, country)
            logger.info(f"Current date ({current_date}) is a holiday: {holiday_name}")
            target_date = get_last_business_day(current_date, country)
            logger.info(f"Processing rates for last business day: {target_date}")
        else:
            target_date = current_date
            logger.info(f"Processing rates for current date: {target_date}")
        
        rates = scrape_fx_rates(target_date, country)
        
        if rates:
            saved, skipped = save_to_database(rates)
            logger.info(f"FX rate update complete - Saved: {saved}, Skipped: {skipped}")
            if saved == 0 and skipped > 0:
                logger.info("All rates were already up to date")
        else:
            raise Exception("No rates were retrieved for processing")
            
    except Exception as e:
        logger.error(f"FX rate update failed: {str(e)}")
        raise

def main():
    """Process and save daily FX rates"""
    try:
        country = Config.DEFAULT_COUNTRY
        current_date = datetime.now(Config.get_timezone(country)).date()
        
        if Config.is_holiday(current_date, country):
            holiday_name = Config.get_holiday_name(current_date, country)
            logger.info(f"Current date ({current_date}) is a holiday: {holiday_name}")
            target_date = get_last_business_day(current_date, country)
            logger.info(f"Processing rates for last business day: {target_date}")
        else:
            target_date = current_date
            logger.info(f"Processing rates for current date: {target_date}")
        
        rates = scrape_fx_rates(target_date, country)
        
        if rates:
            saved, skipped = save_to_database(rates)
            logger.info(f"Daily FX rate processing complete - Saved: {saved}, Skipped: {skipped}")
        else:
            logger.warning("No rates were retrieved for processing")
        
    except Exception as e:
        logger.error(f"FX rate processing failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()