# currency_mapping.py

class CurrencyMapper:
    """
    Maps between ISO currency codes and database currency names.
    Handles bidirectional lookup between codes (USD) and names (U.S. DOLLAR).
    """
    
    # Map ISO codes to database names
    CURRENCY_MAPPINGS = {
        # Major currencies
        'USD': 'U.S. DOLLAR',
        'EUR': 'EURO',
        'GBP': 'GREAT BRITAIN POUND',
        'JPY': 'JAPANESE YEN',
        'AUD': 'AUSTRALIAN DOLLAR',
        'CAD': 'CANADIAN DOLLAR',
        'CHF': 'SWISS FRANC',
        'CNY': 'CHINESE YUAN',
        'HKD': 'HONG KONG DOLLAR',
        'NZD': 'NEW ZEALAND DOLLAR',
        
        # Regional currencies
        'INR': 'INDIAN RUPEE',
        'SGD': 'SINGAPORE DOLLAR',
        'THB': 'THAILAND BAHT',
        'AED': 'UAE DIRHAM',
        'ZAR': 'SOUTH AFRICA RAND',
        'BRL': 'BRAZIL REAL',
        'MXN': 'MEXICAN PESO',
        'KRW': 'SOUTH KOREAN WON',
        'IDR': 'INDONESIAN RUPIAH',
        'TRY': 'TURKISH LIRA',
        'SAR': 'SAUDI RIYAL',
        
        # Caribbean currencies
        'TTD': 'T&T DOLLAR',
        'BBD': 'BARBADOS DOLLAR',
        'BSD': 'BAHAMIAN DOLLAR',
        'XCD': 'E.C. DOLLAR',
        'JMD': 'JMD',  # Special case for base currency
        
        # Add more mappings as needed...
    }
    
    # Create reverse mapping (database names to ISO codes)
    REVERSE_MAPPINGS = {v: k for k, v in CURRENCY_MAPPINGS.items()}
    
    @classmethod
    def get_db_name(cls, iso_code: str) -> str:
        """
        Convert ISO currency code to database currency name.
        
        Args:
            iso_code: The ISO currency code (e.g., 'USD')
            
        Returns:
            The corresponding database currency name (e.g., 'U.S. DOLLAR')
            
        Raises:
            ValueError: If the ISO code is not recognized
        """
        iso_code = iso_code.upper()
        if iso_code not in cls.CURRENCY_MAPPINGS:
            raise ValueError(f"Unrecognized currency code: {iso_code}")
        return cls.CURRENCY_MAPPINGS[iso_code]
    
    @classmethod
    def get_iso_code(cls, db_name: str) -> str:
        """
        Convert database currency name to ISO currency code.
        
        Args:
            db_name: The database currency name (e.g., 'U.S. DOLLAR')
            
        Returns:
            The corresponding ISO currency code (e.g., 'USD')
            
        Raises:
            ValueError: If the database name is not recognized
        """
        db_name = db_name.upper()
        if db_name not in cls.REVERSE_MAPPINGS:
            raise ValueError(f"Unrecognized database currency name: {db_name}")
        return cls.REVERSE_MAPPINGS[db_name]
    
    @classmethod
    def is_valid_iso_code(cls, iso_code: str) -> bool:
        """Check if the given ISO code is supported."""
        return iso_code.upper() in cls.CURRENCY_MAPPINGS
    
    @classmethod
    def is_valid_db_name(cls, db_name: str) -> bool:
        """Check if the given database name is supported."""
        return db_name.upper() in cls.REVERSE_MAPPINGS
    
    @classmethod
    def get_all_supported_currencies(cls) -> dict:
        """
        Get all supported currencies with their mappings.
        
        Returns:
            Dictionary with ISO codes as keys and database names as values
        """
        return cls.CURRENCY_MAPPINGS.copy()

# Usage example:
if __name__ == "__main__":
    # Test the mappings
    test_currencies = ['USD', 'EUR', 'GBP', 'JMD']
    
    print("\nTesting currency mappings:")
    print("-" * 40)
    
    for currency in test_currencies:
        try:
            db_name = CurrencyMapper.get_db_name(currency)
            print(f"{currency} -> {db_name}")
            
            # Test reverse mapping
            iso_code = CurrencyMapper.get_iso_code(db_name)
            print(f"{db_name} -> {iso_code}")
            print()
            
        except ValueError as e:
            print(f"Error with {currency}: {str(e)}\n")