"""
Configuration settings for the customs calculator API.
Provides dynamic currency mappings from the database and configuration settings.
"""
from datetime import datetime, date
import pytz
from utils.database import SessionLocal, Currency

class CountryConfig:
    def __init__(self, name, timezone, holidays):
        self.name = name
        self.timezone = pytz.timezone(timezone)
        self.holidays = holidays

class Config:
    """Configuration class for the application"""
    # Default country settings
    DEFAULT_COUNTRY = "Jamaica"
    
    # Country specific configurations
    COUNTRIES = {
        "Jamaica": CountryConfig(
            name="Jamaica",
            timezone="America/Jamaica",
            holidays={
                # 2025 Jamaica Public Holidays
                date(2025, 1, 1): "New Year's Day",
                date(2025, 2, 26): "Ash Wednesday",
                date(2025, 4, 18): "Good Friday",
                date(2025, 4, 21): "Easter Monday",
                date(2025, 5, 23): "Labour Day",
                date(2025, 8, 1): "Emancipation Day",
                date(2025, 8, 6): "Independence Day",
                date(2025, 10, 20): "National Heroes Day",
                date(2025, 12, 25): "Christmas Day",
                date(2025, 12, 26): "Boxing Day",
                
                # 2024 Jamaica Public Holidays
                date(2024, 1, 1): "New Year's Day",
                date(2024, 2, 14): "Ash Wednesday",
                date(2024, 3, 29): "Good Friday",
                date(2024, 4, 1): "Easter Monday",
                date(2024, 5, 23): "Labour Day",
                date(2024, 8, 1): "Emancipation Day",
                date(2024, 8, 6): "Independence Day",
                date(2024, 10, 21): "National Heroes Day",
                date(2024, 12, 25): "Christmas Day",
                date(2024, 12, 26): "Boxing Day",
            }
        )
    }
    
    # BOJ FX rates scraping settings
    BOJ_URL = "https://boj.org.jm/market/foreign-exchange/indicative-rates/"
    CHROME_DRIVER_PATH = None  # Will be set by webdriver manager
    
    # Scraping intervals
    SCRAPE_INTERVAL_MINUTES = 60  # How often to check for new rates
    RETRY_DELAY_SECONDS = 300     # Delay between retries if scraping fails
    MAX_RETRIES = 3              # Maximum number of retry attempts
    
    # Timeouts
    PAGE_LOAD_TIMEOUT = 60       # Seconds to wait for page load
    ELEMENT_WAIT_TIMEOUT = 20    # Seconds to wait for elements
    DATA_LOAD_WAIT = 5          # Seconds to wait for data to settle
    
    # Database settings
    DB_RETRY_ATTEMPTS = 3        # Number of times to retry database operations
    DB_RETRY_DELAY = 5          # Seconds between database retry attempts
    
    # Transportation modes
    TRANSPORT_MODES = {
        'air': 'Air Freight',
        'sea': 'Sea Freight',
        'land': 'Land Transport'
    }

    # Transaction types
    TRANSACTION_TYPES = {
        'commercial': 'Commercial',
        'personal': 'Personal'
    }

    # Default CAF rates (Customs Administration Fee)
    DEFAULT_CAF_RATES = {
        'commercial': 0,    # 0 for commercial
        'personal': 2500    # Fixed rate of 2500 for personal
    }

    @classmethod
    def get_country_config(cls, country_name=None):
        """Get configuration for specified country or default country"""
        country_name = country_name or cls.DEFAULT_COUNTRY
        return cls.COUNTRIES.get(country_name)
    
    @classmethod
    def is_holiday(cls, check_date, country_name=None):
        """Check if given date is a holiday for specified country"""
        country_config = cls.get_country_config(country_name)
        if not country_config:
            return False
        return check_date in country_config.holidays
    
    @classmethod
    def get_holiday_name(cls, check_date, country_name=None):
        """Get holiday name for given date and country"""
        country_config = cls.get_country_config(country_name)
        if not country_config:
            return None
        return country_config.holidays.get(check_date)
    
    @classmethod
    def get_timezone(cls, country_name=None):
        """Get timezone for specified country"""
        country_config = cls.get_country_config(country_name)
        return country_config.timezone if country_config else pytz.UTC

def get_currency_mappings():
    """Get currency mappings from database"""
    db = SessionLocal()
    try:
        currencies = db.query(Currency).all()
        currency_map = {curr.code: curr.name for curr in currencies}
        reverse_currency_map = {curr.name: curr.code for curr in currencies}
        return currency_map, reverse_currency_map
    finally:
        db.close()

# Get currency mappings from database
CURRENCY_MAP, REVERSE_CURRENCY_MAP = get_currency_mappings()