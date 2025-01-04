import logging
from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from utils.database import Currency, FXRate, TaxRate, SessionLocal
from utils.currency_mapping import CurrencyMapper

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_currency_rate(currency: str, db: Session) -> float:
    """
    Fetch currency rate from database.
    For foreign currencies, returns how many JMD per unit of foreign currency.
    For JMD returns 1.0 since it's the base currency.
    
    Args:
        currency: ISO currency code (e.g., 'USD') or database currency name
        db: Database session
        
    Returns:
        float: Exchange rate in JMD
    """
    logger.info(f"Fetching rate for currency: {currency}")
    
    # Special case for JMD since it's the base currency
    if currency.upper() == 'JMD':
        logger.info("Base currency (JMD) - using rate of 1.0")
        return 1.0
    
    try:
        # Convert ISO code to database name if necessary
        try:
            db_currency_name = CurrencyMapper.get_db_name(currency)
        except ValueError:
            # If not a valid ISO code, try using it directly (might already be database name)
            if not CurrencyMapper.is_valid_db_name(currency):
                raise ValueError(f"Unrecognized currency: {currency}")
            db_currency_name = currency
            
        # Get the most recent date
        latest_date = db.query(FXRate.date).order_by(desc(FXRate.date)).first()
        if not latest_date:
            raise ValueError("No FX rates available in database")
        
        # Get the rate using exact currency name from database
        fx_rate = db.query(FXRate).filter(
            FXRate.date == latest_date[0],
            FXRate.currency == db_currency_name
        ).first()
        
        if fx_rate:
            rate = fx_rate.selling_rate
            logger.info(f"Found selling rate for {db_currency_name}: {rate}")
            return rate
        else:
            raise ValueError(f"No exchange rate found for {db_currency_name} on {latest_date[0]}")
            
    except Exception as e:
        logger.error(f"Error fetching currency rate: {str(e)}")
        raise

def calculate_cif(
    product_price: float,
    product_currency: str,
    freight_charges: float,
    freight_currency: str,
    mode_of_transportation: str,
    db: Session
):
    """
    Calculate CIF value in original currency, JMD, and USD.
    
    Parameters:
    product_price (float): The price of the product
    product_currency (str): The currency name as it appears in database
    freight_charges (float): The freight charges
    freight_currency (str): The currency name as it appears in database
    mode_of_transportation (str): The mode of transportation ('air' or 'ocean')
    db (Session): Database session for currency rate lookups
    
    Returns:
    dict: A dictionary containing CIF values and related information
    """
    logger.info(f"Calculating CIF for: product_price={product_price} {product_currency}, "
                f"freight_charges={freight_charges} {freight_currency}, "
                f"mode_of_transportation={mode_of_transportation}")

    # Fetch exchange rates (returns JMD per unit of foreign currency)
    product_rate = fetch_currency_rate(product_currency, db)
    freight_rate = fetch_currency_rate(freight_currency, db)
    usd_rate = fetch_currency_rate('U.S. DOLLAR', db)  # For USD conversion

    logger.info(f"Exchange rates: {product_currency}={product_rate}, "
                f"{freight_currency}={freight_rate}, USD={usd_rate}")

    # Calculate values in JMD
    product_price_jmd = round(product_price * product_rate, 2)
    freight_charges_jmd = round(freight_charges * freight_rate, 2)

    # Calculate values in USD (divide by USD rate since rate is JMD per USD)
    product_price_usd = round(product_price_jmd / usd_rate, 2)
    freight_charges_usd = round(freight_charges_jmd / usd_rate, 2)

    # Calculate CIF in original currencies
    cif_original = round(product_price + freight_charges, 2)

    # Calculate insurance based on mode of transportation
    if mode_of_transportation.lower() == 'air':
        insurance_rate = 0.01  # 1% for air cargo
    elif mode_of_transportation.lower() == 'ocean':
        insurance_rate = 0.015  # 1.5% for ocean cargo
    else:
        raise ValueError(f"Invalid mode of transportation: {mode_of_transportation}")

    # Calculate insurance in original currency and JMD
    insurance_original = round(cif_original * insurance_rate, 2)
    insurance_jmd = round(insurance_original * product_rate, 2)

    # Calculate CIF in JMD
    cif_jmd = round(product_price_jmd + freight_charges_jmd + insurance_jmd, 2)

    # Calculate CIF in USD
    cif_usd = round(cif_jmd / usd_rate, 2)

    result = {
        'cif_original': cif_original,
        'cif_original_currency': product_currency if product_currency == freight_currency else 'Mixed',
        'cif_jmd': cif_jmd,
        'cif_usd': cif_usd,
        'product_price_original': round(product_price, 2),
        'product_currency': product_currency,
        'freight_charges_original': round(freight_charges, 2),
        'freight_currency': freight_currency,
        'product_price_jmd': product_price_jmd,
        'freight_charges_jmd': freight_charges_jmd,
        'product_price_usd': product_price_usd,
        'freight_charges_usd': freight_charges_usd,
        'insurance_original_currency': insurance_original,
        'insurance_jmd': insurance_jmd,
        'mode_of_transportation': mode_of_transportation,
        'exchange_rates': {
            'JMD': 1.0,  # Base currency
            'USD': usd_rate,
            product_currency: product_rate,
            freight_currency: freight_rate
        }
    }

    logger.info(f"CIF calculation result: {result}")
    return result

def get_tax_rates(hs_code: str, db: Session):
    """Get tax rates for a given HS code"""
    logger.info(f"Fetching tax rates for HS code: {hs_code}")
    try:
        tax_rates = db.query(TaxRate).filter_by(hs_code=hs_code).all()
        rates = {}
        if tax_rates:
            for tax_rate in tax_rates:
                rates[tax_rate.tax_id] = tax_rate.rate
            return rates
        else:
            logger.warning(f"No tax rates found for HS code: {hs_code}")
            return {}
    except Exception as e:
        logger.error(f"Error querying tax rates: {str(e)}")
        return {}

def determine_caf_rate(
    transaction_type: str,
    package_type: str,
    cif_value: float,
    input_currency: str,
    db: Session
):
    """
    Determines the CAF rate based on the transaction type, package type, CIF value, and input currency.
    """
    if not transaction_type:
        raise ValueError("Transaction type cannot be None")
    
    logger.info(f"Determining CAF rate for: transaction_type={transaction_type}, "
                f"package_type={package_type}, cif_value={cif_value}, input_currency={input_currency}")

    # Check for motor vehicle package type
    if package_type.lower() == 'motor vehicle':
        logger.info("Motor vehicle detected. Returning fixed CAF rate of 57500.0 JMD")
        return 57500.0

    # Convert CIF value to USD if it's not already in USD
    if input_currency != 'U.S. DOLLAR':
        usd_rate = fetch_currency_rate('U.S. DOLLAR', db)
        input_currency_rate = fetch_currency_rate(input_currency, db)
        cif_value_usd = round(cif_value * (input_currency_rate / usd_rate), 2)
        logger.info(f"Converted CIF value from {input_currency} to USD: {cif_value_usd}")
    else:
        cif_value_usd = cif_value
        logger.info(f"CIF value already in USD: {cif_value_usd}")

    # Check for IMS4 transaction type (household items)
    if transaction_type.upper() == 'IMS4':
        if cif_value_usd < 5000:
            logger.info("IMS4 transaction with CIF < 5000 USD. Returning CAF rate of 2500.0 JMD")
            return 2500.0
        else:
            logger.info("IMS4 transaction with CIF >= 5000 USD. Treating as IM4, returning CAF rate of 10000.0 JMD")
            return 10000.0

    # Check for IM4 transaction type (commercial items)
    if transaction_type.upper() == 'IM4':
        logger.info("IM4 transaction. Returning fixed CAF rate of 10000.0 JMD")
        return 10000.0

    # Default case
    logger.warning(f"Unrecognized transaction type: {transaction_type}. Defaulting to 10000.0 JMD CAF.")
    return 10000.0

def calculate_custom_charges(tax_rates: dict, cif: float, caf: float) -> tuple[dict, dict]:
    """
    Calculate custom charges based on tax rates, CIF value, and CAF.
    Only ID-01 needs to be converted from percentage to decimal.
    Other rates are already in decimal form.
    """
    logger.info(f"\nInitial Values:")
    logger.info(f"CIF: {cif:.2f} JMD")
    logger.info(f"CAF: {caf:.2f} JMD")

    # Store original tax rates for return value
    original_rates = tax_rates.copy()

    # Convert all tax rates from percentage to decimal
    decimal_rates = {k: (v/100 if v > 0 else 0) for k, v in tax_rates.items()}

    logger.info(f"\nTax Rates:")
    for tax, rate in decimal_rates.items():
        logger.info(f"{tax}: {rate:.4f}")

    base_value_1 = round(cif, 2)
    logger.info(f"\nBase Value 1 (CIF): {base_value_1:.2f} JMD")

    ID_01_charge = round(base_value_1 * decimal_rates.get("ID-01", 0), 2)
    logger.info(f"ID-01 ({decimal_rates.get('ID-01', 0):.4f}): {base_value_1:.2f} * {decimal_rates.get('ID-01', 0):.4f} = {ID_01_charge:.2f} JMD")

    base_value_2 = round(base_value_1 + ID_01_charge, 2)
    logger.info(f"Base Value 2 (CIF + ID-01): {base_value_1:.2f} + {ID_01_charge:.2f} = {base_value_2:.2f} JMD")

    ASD05_charge = round(base_value_2 * decimal_rates.get("ASD05", 0), 2)
    logger.info(f"ASD05 ({decimal_rates.get('ASD05', 0):.4f}): {base_value_2:.2f} * {decimal_rates.get('ASD05', 0):.4f} = {ASD05_charge:.2f} JMD")

    SCTA08_charge = round(base_value_2 * decimal_rates.get("SCTA08", 0), 2)
    logger.info(f"SCTA08 ({decimal_rates.get('SCTA08', 0):.4f}): {base_value_2:.2f} * {decimal_rates.get('SCTA08', 0):.4f} = {SCTA08_charge:.2f} JMD")

    SCTS18_charge = round(base_value_2 * decimal_rates.get("SCTS18", 0), 2)
    logger.info(f"SCTS18 ({decimal_rates.get('SCTS18', 0):.4f}): {base_value_2:.2f} * {decimal_rates.get('SCTS18', 0):.4f} = {SCTS18_charge:.2f} JMD")

    SCTF028_charge = round(base_value_2 * decimal_rates.get("SCTF028", 0), 2)
    logger.info(f"SCTF028 ({decimal_rates.get('SCTF028', 0):.4f}): {base_value_2:.2f} * {decimal_rates.get('SCTF028', 0):.4f} = {SCTF028_charge:.2f} JMD")

    SCF90_charge = round(base_value_1 * decimal_rates.get("SCF90", 0), 2)
    logger.info(f"SCF90 ({decimal_rates.get('SCF90', 0):.4f}): {base_value_1:.2f} * {decimal_rates.get('SCF90', 0):.4f} = {SCF90_charge:.2f} JMD")

    ENVL20_charge = round(base_value_1 * decimal_rates.get("ENVL20", 0), 2)
    logger.info(f"ENVL20 ({decimal_rates.get('ENVL20', 0):.4f}): {base_value_1:.2f} * {decimal_rates.get('ENVL20', 0):.4f} = {ENVL20_charge:.2f} JMD")

    base_value_3 = round(caf, 2)
    logger.info(f"Base Value 3 (CAF): {base_value_3:.2f} JMD")

    CAF_charge = round(base_value_3 * 1.0, 2)
    logger.info(f"CAF Charge: {CAF_charge:.2f} JMD")

    base_value_4 = round(base_value_2 + ASD05_charge + SCTA08_charge + SCTS18_charge + SCTF028_charge + SCF90_charge + ENVL20_charge + CAF_charge, 2)
    logger.info(f"Base Value 4 (all charges): {base_value_2:.2f} + {ASD05_charge:.2f} + {SCTA08_charge:.2f} + {SCTS18_charge:.2f} + {SCTF028_charge:.2f} + {SCF90_charge:.2f} + {ENVL20_charge:.2f} + {CAF_charge:.2f} = {base_value_4:.2f} JMD")

    GCT_06_charge = round(base_value_4 * decimal_rates.get("GCT 06", 0), 2)
    logger.info(f"GCT 06 ({decimal_rates.get('GCT 06', 0):.4f}): {base_value_4:.2f} * {decimal_rates.get('GCT 06', 0):.4f} = {GCT_06_charge:.2f} JMD")

    EXC023_charge = round(base_value_4 * decimal_rates.get("EXC023", 0), 2)
    logger.info(f"EXC023 ({decimal_rates.get('EXC023', 0):.4f}): {base_value_4:.2f} * {decimal_rates.get('EXC023', 0):.4f} = {EXC023_charge:.2f} JMD")

    total_custom_charges = round(ID_01_charge + ASD05_charge + GCT_06_charge + EXC023_charge + SCTA08_charge + SCTS18_charge + 
                               SCTF028_charge + SCF90_charge + ENVL20_charge + CAF_charge, 2)
    logger.info(f"\nTotal Custom Charges:")
    logger.info(f"{ID_01_charge:.2f} + {ASD05_charge:.2f} + {GCT_06_charge:.2f} + {EXC023_charge:.2f} + {SCTA08_charge:.2f} + "
               f"{SCTS18_charge:.2f} + {SCTF028_charge:.2f} + {SCF90_charge:.2f} + {ENVL20_charge:.2f} + {CAF_charge:.2f} = "
               f"{total_custom_charges:.2f} JMD")

    result = {
        "base_value_1 (CIF)": base_value_1,
        "base_value_2 (CIF + ID-01)": base_value_2,
        "base_value_3 (CAF)": base_value_3,
        "base_value_4 (all charges)": base_value_4,
        "ID-01": ID_01_charge,
        "ASD05": ASD05_charge,
        "GCT 06": GCT_06_charge,
        "EXC023": EXC023_charge,
        "SCTA08": SCTA08_charge,
        "SCTS18": SCTS18_charge,
        "SCTF028": SCTF028_charge,
        "SCF90": SCF90_charge,
        "ENVL20": ENVL20_charge,
        "CAF_charge": CAF_charge,
        "total_custom_charges": total_custom_charges
    }
    
    # Only return charges that are greater than 0
    return {k: v for k, v in result.items() if v > 0}, original_rates