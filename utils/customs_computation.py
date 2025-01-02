import logging
from sqlalchemy import create_engine, desc
from sqlalchemy.exc import SQLAlchemyError
from utils.database import Currency, FXRate, TaxRate, SessionLocal as db
from config.config import CURRENCY_MAP, REVERSE_CURRENCY_MAP

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_currency_code(currency):
    logger.info(f"Getting currency code for: {currency}")
    
    # Check if the input is already a currency code
    if currency.upper() in CURRENCY_MAP:
        return currency.upper()
    
    # Check if the input matches a full currency name
    if currency.upper() in REVERSE_CURRENCY_MAP:
        return REVERSE_CURRENCY_MAP[currency.upper()]
    
    # If not found, try to match based on partial name
    for code, name in CURRENCY_MAP.items():
        if currency.upper() in name:
            logger.info(f"Found currency code: {code}")
            return code
    
    logger.warning(f"Currency code not found for {currency}")
    return None

def fetch_currency_rate(currency):
    logger.info(f"Fetching rate for currency: {currency}")

    currency_code = get_currency_code(currency)
    logger.info(f"Currency code: {currency_code}")
    
    if not currency_code:
        logger.warning(f"Warning: Currency code not found for {currency}")
        return 1.0  # Default to 1.0 if currency is not found
    
    try:
        # Create a new session
        session = SessionLocal()
        try:
            # Get the most recent date
            latest_date = session.query(FXRate.date).order_by(desc(FXRate.date)).first()
            
            if latest_date:
                # Try to find the rate using the currency code and the most recent date
                fx_rate = session.query(FXRate).filter(
                    FXRate.date == latest_date[0],
                    FXRate.currency == CURRENCY_MAP[currency_code]
                ).first()
                
                logger.info(f"Query result: {fx_rate}")
                
                if fx_rate:
                    rate = fx_rate.selling_rate
                    logger.info(f"Found selling rate for {currency}: {rate}")
                    return rate
                else:
                    logger.warning(f"No exchange rate found for {currency_code} on {latest_date[0]}")
            else:
                logger.warning("No FX rate data available in the database.")
        finally:
            session.close()
    except SQLAlchemyError as e:
        logger.error(f"Database error when querying exchange rate: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error when querying exchange rate: {str(e)}")
    
    logger.warning(f"Warning: Exchange rate not found for {currency} ({currency_code})")
    return 1.0  # Default to 1.0 if rate is not found

def calculate_cif(product_price, product_currency, freight_charges, freight_currency, mode_of_transportation):
    """
    Calculate CIF value in original currency, JMD, and USD.
    
    Parameters:
    product_price (float): The price of the product
    product_currency (str): The currency code of the product price
    freight_charges (float): The freight charges
    freight_currency (str): The currency code of the freight charges
    mode_of_transportation (str): The mode of transportation ('air' or 'ocean')
    
    Returns:
    dict: A dictionary containing CIF values and related information
    """
    logger.info(f"Calculating CIF for: product_price={product_price} {product_currency}, "
                f"freight_charges={freight_charges} {freight_currency}, "
                f"mode_of_transportation={mode_of_transportation}")

    # Fetch exchange rates (now using selling rates)
    jmd_rate = fetch_currency_rate('JMD')
    usd_rate = fetch_currency_rate('USD')
    product_rate = fetch_currency_rate(product_currency)
    freight_rate = fetch_currency_rate(freight_currency)

    logger.info(f"Exchange rates (selling): JMD={jmd_rate}, USD={usd_rate}, "
                f"{product_currency}={product_rate}, {freight_currency}={freight_rate}")

    # Calculate values in JMD
    product_price_jmd = round(product_price * product_rate, 2)
    freight_charges_jmd = round(freight_charges * freight_rate, 2)

    # Calculate values in USD
    product_price_usd = round(product_price_jmd / usd_rate, 2)
    freight_charges_usd = round(freight_charges_jmd / usd_rate, 2)

    # Calculate CIF in original currencies
    cif_original = round(product_price + freight_charges, 2)

    # Calculate insurance in original currency
    if mode_of_transportation.lower() == 'air':
        insurance_original = round(cif_original * 0.01, 2)  # 1% for air cargo
    elif mode_of_transportation.lower() == 'ocean':
        insurance_original = round(cif_original * 0.015, 2)  # 1.5% for ocean cargo
    else:
        insurance_original = 0  # Default to 0 if transportation mode is unknown

    # Calculate insurance in JMD
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
            'JMD': jmd_rate,
            'USD': usd_rate,
            product_currency: round(product_rate, 4),
            freight_currency: round(freight_rate, 4)
        }
    }

    logger.info(f"Insurance in original currency ({product_currency}): {insurance_original:.2f} {product_currency}")
    logger.info(f"Insurance in JMD: {insurance_jmd:.2f} JMD")
    logger.info(f"Exchange rate used for conversion to JMD: {product_rate:.4f}")
    logger.info(f"CIF calculation result: {result}")
    
    return result

def get_tax_rates(hs_code):
    logger.info(f"Fetching tax rates for HS code: {hs_code}")
    try:
        tax_rates = TaxRate.get_rates_for_hs_code(hs_code)
        rates = {}
        if tax_rates:
            for tax_rate in tax_rates:
                rates[tax_rate.tax_id] = tax_rate.rate  # Assuming 'rate' is the column name
            return rates
        else:
            logger.warning(f"No tax rates found for HS code: {hs_code}")
            return {}
    except Exception as e:
        logger.error(f"Error querying tax rates: {str(e)}")
        return {}

def calculate_custom_charges(tax_rates, cif, caf):
    logger.info(f"\nInitial Values:")
    logger.info(f"CIF: {cif:.2f} JMD")
    logger.info(f"CAF: {caf:.2f} JMD")

    # Convert tax rates to decimal form for calculations
    decimal_rates = {k: (v/100 if v > 1 else v) for k, v in tax_rates.items()}

    logger.info(f"\nTax Rates (converted to decimal):")
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

    total_custom_charges = round(ID_01_charge + ASD05_charge + GCT_06_charge + EXC023_charge + SCTA08_charge + SCTS18_charge + SCTF028_charge + SCF90_charge + ENVL20_charge + CAF_charge, 2)
    logger.info(f"\nTotal Custom Charges:")
    logger.info(f"{ID_01_charge:.2f} + {ASD05_charge:.2f} + {GCT_06_charge:.2f} + {EXC023_charge:.2f} + {SCTA08_charge:.2f} + {SCTS18_charge:.2f} + {SCTF028_charge:.2f} + {SCF90_charge:.2f} + {ENVL20_charge:.2f} + {CAF_charge:.2f} = {total_custom_charges:.2f} JMD")

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
    return {k: v for k, v in result.items() if v > 0}, tax_rates

def determine_caf_rate(transaction_type, package_type, cif_value, input_currency):
    """
    Determines the CAF rate based on the transaction type, package type, CIF value, and input currency.

    Parameters:
        transaction_type (str): The type of transaction (e.g., 'IMS4', 'IM4').
        package_type (str): The type of package or product (e.g., 'motor vehicle').
        cif_value (float): The CIF (Cost, Insurance, and Freight) value of the goods.
        input_currency (str): The currency code of the input CIF value.

    Returns:
        float: The determined CAF rate in JMD.
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
    if input_currency.upper() != 'USD':
        usd_rate = fetch_currency_rate('USD')
        input_currency_rate = fetch_currency_rate(input_currency)
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

def calculate_additional_im4_rate(cif_value):
    """
    Placeholder function to calculate additional CAF rate for IM4 transactions based on CIF value.
    Modify this function based on the additional rules for IM4 transactions.
    """
    # Placeholder logic; modify as needed
    return 10000  # Base rate, or more complex calculations