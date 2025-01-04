# test_currency.py
from utils.database import SessionLocal, FXRate
from sqlalchemy import desc
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_currency_rate(currency_code):
    """Fetch currency rate with JMD handling"""
    # Special case for JMD since it's the base currency
    if currency_code.upper() == 'JMD':
        print("Base currency (JMD) - using rate of 1.0")
        return 1.0
        
    db = SessionLocal()
    try:
        # Define direct mapping for currency codes
        currency_names = {
            'USD': ['U.S. DOLLAR'],
            'EUR': ['EURO'],
            'GBP': ['GREAT BRITAIN POUND']
        }
        
        # Get the possible names for this currency
        possible_names = currency_names.get(currency_code.upper(), [])
        print(f"\nLooking for {currency_code} using these possible names: {possible_names}")
        
        # Try each possible name
        for curr_name in possible_names:
            latest_fx = (
                db.query(FXRate)
                .filter(FXRate.currency == curr_name)
                .order_by(desc(FXRate.date))
                .first()
            )
            
            if latest_fx:
                print(f"Found match using name: {curr_name}")
                return latest_fx.selling_rate
                
        print(f"No matches found for {currency_code}")
        return None
            
    finally:
        db.close()

def test_rates():
    """Test currency rate fetching"""
    currencies = ['USD', 'EUR', 'GBP', 'JMD']
    
    print("\nTesting currency rates:")
    print("-" * 40)
    
    for currency in currencies:
        print(f"\nChecking {currency}:")
        rate = fetch_currency_rate(currency)
        if rate is not None:
            print(f"✓ {currency}: {rate}")
        else:
            print(f"✗ {currency}: No rate found")

if __name__ == "__main__":
    test_rates()