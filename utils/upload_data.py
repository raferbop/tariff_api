# utils/upload_data.py
import pandas as pd
from pathlib import Path
import logging
import os
import csv
from typing import Tuple, Dict, Set
from collections import defaultdict

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent

def get_data_file_path(filename: str) -> Path:
    """
    Helper function to get the correct path regardless of where script is run from.
    
    Args:
        filename (str): Name of the file to locate
        
    Returns:
        Path: Complete path to the data file
    """
    return Path(os.path.join(PROJECT_ROOT, 'data', filename))

def clean_currency_name(name: str) -> str:
    """Clean currency name by removing special characters and extra spaces."""
    return ' '.join(name.split())

def upload_currencies() -> bool:
    """
    Upload currency data from CSV file to the database with robust error handling.
    Returns bool: True if successful, False otherwise.
    """
    from utils.database import SessionLocal, Currency
    
    db = SessionLocal()
    try:
        # First clear existing data
        db.query(Currency).delete()
        db.commit()
        
        currency_file = get_data_file_path('currency.csv')
        if not currency_file.exists():
            logger.error(f"Currency CSV file not found at {currency_file}")
            return False
            
        successful_rows = 0
        error_rows = 0
        
        # Use csv module for more robust parsing
        with open(currency_file, 'r', encoding='utf-8') as f:
            # Check and log header
            header = f.readline().strip()
            logger.info(f"CSV Header: {header}")
            
            reader = csv.reader(f)
            currencies_to_add = []
            
            for row_idx, row in enumerate(reader, start=2):  # start=2 because we already read header
                try:
                    # Skip empty rows
                    if not row:
                        continue
                        
                    # Handle rows that might have been split incorrectly
                    if len(row) != 6:
                        # Try to detect if this is a split row
                        combined_row = ','.join(row)
                        fields = combined_row.split(',')
                        if len(fields) >= 3:
                            # Take the last three fields for currency data
                            entity = ','.join(fields[:-3])
                            currency_name = fields[-3]
                            code = fields[-2]
                        else:
                            logger.warning(f"Invalid row format at line {row_idx}: {row}")
                            error_rows += 1
                            continue
                    else:
                        # Normal case with 6 columns
                        entity = row[0]
                        currency_name = row[1]
                        code = row[2]
                    
                    # Clean and validate the data
                    entity = str(entity).strip()
                    code = str(code).strip().upper()
                    currency_name = clean_currency_name(str(currency_name))
                    
                    # Validate all required fields
                    if not code or not currency_name or not entity or len(code) > 3:
                        logger.warning(f"Invalid currency data at line {row_idx}: entity='{entity}', code='{code}', name='{currency_name}'")
                        error_rows += 1
                        continue
                    
                    currencies_to_add.append(Currency(
                        entity=entity,
                        code=code,
                        name=currency_name
                    ))
                    successful_rows += 1
                    
                except Exception as e:
                    error_rows += 1
                    logger.warning(f"Error processing currency row {row_idx}: {str(e)}")
                    continue
            
            # Bulk insert all currencies at once
            try:
                db.bulk_save_objects(currencies_to_add)
                db.commit()
                logger.info(f"Successfully uploaded {successful_rows} currencies")
                if error_rows > 0:
                    logger.warning(f"Skipped {error_rows} invalid currency rows")
                return True
            except Exception as e:
                db.rollback()
                logger.error(f"Error bulk inserting currencies: {str(e)}")
                return False
            
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading currencies: {str(e)}")
        return False
    finally:
        db.close()

def parse_rate_value(rate_str: str, tax_id: str, row_idx: int) -> tuple[float, str]:
    """
    Enhanced rate parsing with detailed categorization.
    Returns tuple of (parsed_rate, format_category)
    """
    rate_str = str(rate_str).strip().lower()
    
    # Handle spaces in numbers (e.g., "37. 4845")
    rate_str = ''.join(rate_str.split())
    
    # Special cases handling
    if rate_str in ['-', '', 'nodata', 'nan', 'b']:
        return 0.0, 'no_data'
        
    # Handle SCTS18 specific patterns
    if tax_id == 'SCTS18':
        if 'per lpa' in rate_str:
            try:
                return float(rate_str.replace('j$', '').replace(',', '').split('per')[0].strip()), 'per_lpa'
            except ValueError:
                logger.warning(f"Invalid SCTS18 per LPA format at row {row_idx}: {rate_str}")
                return 0.0, 'error'
        elif 'pergrams/stick' in rate_str or 'pergrams/ stick' in rate_str:
            try:
                # Handle "$X.XX per 0.7 grams/stick" format
                value = rate_str.split('per')[0].replace('$', '').strip()
                return float(value), 'per_stick'
            except ValueError:
                logger.warning(f"Invalid SCTS18 per grams/stick format at row {row_idx}: {rate_str}")
                return 0.0, 'error'
        elif 'perstick' in rate_str:
            try:
                return float(rate_str.split('per')[0].replace('$', '').strip()), 'per_stick'
            except ValueError:
                logger.warning(f"Invalid SCTS18 per stick format at row {row_idx}: {rate_str}")
                return 0.0, 'error'
        elif 'per' in rate_str and ('litre' in rate_str or 'mmbtu' in rate_str):
            try:
                return float(rate_str.split('per')[0].replace('$', '').strip()), 'per_unit'
            except ValueError:
                logger.warning(f"Invalid SCTS18 per unit format at row {row_idx}: {rate_str}")
                return 0.0, 'error'
                
    # Handle ASD05 specific patterns
    elif tax_id == 'ASD05' and 'per litre' in rate_str:
        try:
            return float(rate_str.replace('us$', '').split('per')[0].strip()), 'per_litre'
        except ValueError:
            logger.warning(f"Invalid ASD05 per litre format at row {row_idx}: {rate_str}")
            return 0.0, 'error'
            
    # Handle percentage rates
    if '%' in rate_str:
        try:
            return float(rate_str.rstrip('%').replace(',', '')), 'percentage'
        except ValueError:
            logger.warning(f"Invalid percentage format at row {row_idx}: {rate_str}")
            return 0.0, 'error'
            
    # Handle currency amounts
    if any(curr in rate_str for curr in ['$', '€', '£', 'j$', 'us$']):
        try:
            cleaned_str = ''.join(c for c in rate_str if c.isdigit() or c in ['.', '-'])
            return float(cleaned_str), 'currency'
        except ValueError:
            logger.warning(f"Invalid currency format at row {row_idx}: {rate_str}")
            return 0.0, 'error'
            
    # Handle plain numbers
    try:
        return float(rate_str.replace(',', '')), 'numeric'
    except ValueError:
        logger.warning(f"Unrecognized rate format at row {row_idx}: {rate_str}")
        return 0.0, 'error'

def upload_tax_rates() -> bool:
    """
    Upload tax rates from CSV file to the database with improved rate parsing.
    Returns bool: True if successful, False otherwise.
    """
    from utils.database import SessionLocal, TaxRate
    
    db = SessionLocal()
    try:
        # First clear existing data
        db.query(TaxRate).delete()
        db.commit()
        
        tax_rates_file = get_data_file_path('tax_rates.csv')
        if not tax_rates_file.exists():
            logger.error(f"Tax rates CSV file not found at {tax_rates_file}")
            return False
            
        # Read CSV with specified dtypes
        tax_rates_df = pd.read_csv(tax_rates_file, dtype={
            'HS Code': str,
            'ID': str,
            'Rate': str
        })
        
        # Initialize statistics and tracking
        stats = {
            'total_rows': len(tax_rates_df),
            'successful': 0,
            'errors': 0,
            'formats': defaultdict(int),
            'tax_ids': defaultdict(int),
            'zero_rates': 0
        }
        
        # Track unique combinations to handle duplicates
        seen_combinations = set()
        duplicates = 0
        
        batch_size = 1000
        tax_rates = []
        
        for idx, row in tax_rates_df.iterrows():
            try:
                hs_code = str(row['HS Code']).strip()
                tax_id = str(row['ID']).strip()
                rate_str = str(row['Rate']).strip()
                
                # Skip invalid rows
                if not hs_code or not tax_id:
                    stats['errors'] += 1
                    logger.warning(f"Missing HS code or tax ID at row {idx}")
                    continue
                    
                # Check for duplicates
                combination = (hs_code, tax_id)
                if combination in seen_combinations:
                    duplicates += 1
                    logger.warning(f"Duplicate combination found at row {idx}: {combination}")
                    continue
                seen_combinations.add(combination)
                
                # Parse rate with enhanced function
                rate, format_type = parse_rate_value(rate_str, tax_id, idx)
                
                # Update statistics
                stats['formats'][format_type] += 1
                stats['tax_ids'][tax_id] += 1
                if rate == 0:
                    stats['zero_rates'] += 1
                
                # Create tax rate record
                tax_rate = TaxRate(
                    hs_code=hs_code,
                    tax_id=tax_id,
                    rate=rate
                )
                tax_rates.append(tax_rate)
                stats['successful'] += 1
                
                # Batch commit
                if len(tax_rates) >= batch_size:
                    db.bulk_save_objects(tax_rates)
                    db.commit()
                    tax_rates = []
                    
            except Exception as e:
                stats['errors'] += 1
                logger.warning(f"Error processing row {idx}: {str(e)}")
                continue
        
        # Commit remaining records
        if tax_rates:
            db.bulk_save_objects(tax_rates)
            db.commit()
        
        # Log detailed statistics
        logger.info(f"\nTax Rate Upload Statistics:")
        logger.info(f"Total rows processed: {stats['total_rows']}")
        logger.info(f"Successfully uploaded: {stats['successful']}")
        logger.info(f"Errors encountered: {stats['errors']}")
        logger.info(f"Duplicate combinations: {duplicates}")
        logger.info(f"Zero-rate entries: {stats['zero_rates']}")
        
        logger.info("\nRate Format Distribution:")
        for format_type, count in stats['formats'].items():
            logger.info(f"  - {format_type}: {count} ({(count/stats['total_rows']*100):.2f}%)")
            
        logger.info("\nTax ID Distribution:")
        for tax_id, count in stats['tax_ids'].items():
            logger.info(f"  - {tax_id}: {count}")
        
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading tax rates: {str(e)}")
        return False
    finally:
        db.close()

def upload_all_data() -> Tuple[bool, str]:
    """
    Upload all data to the database.
    Returns tuple: (bool, str) indicating success/failure and message
    """
    try:
        from utils.database import Currency, FXRate, TaxRate
        
        # Initialize any missing tables first
        for Model in [Currency, FXRate, TaxRate]:
            Model.create_table()
            
        # Now initialize the data
        for Model in [Currency, FXRate, TaxRate]:
            Model.initialize_data()
            
        # Finally run the upload process
        currencies_success = upload_currencies()
        tax_rates_success = upload_tax_rates()
        
        if currencies_success and tax_rates_success:
            return True, "Successfully uploaded all data"
        elif not currencies_success and not tax_rates_success:
            return False, "Failed to upload both currencies and tax rates"
        elif not currencies_success:
            return False, "Failed to upload currencies"
        else:
            return False, "Failed to upload tax rates"
            
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

if __name__ == "__main__":
    success, message = upload_all_data()
    if success:
        logger.info(message)
    else:
        logger.error(message)