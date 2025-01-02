# database.py
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, UniqueConstraint, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import pandas as pd
from datetime import datetime
import logging
from pathlib import Path
import socket
import csv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configurations
database_config = {
    'local': {
        'dbname': 'klearr-localhost',
        'user': 'postgres',
        'password': '34_Roehampton_Close',
        'host': 'localhost',
        'port': '5432'
    },
    'server': {
        'dbname': 'auction_scraper',
        'user': 'auction_user',
        'password': 'JalenBrunson11',
        'host': 'localhost',
        'port': '5432'
    }
}

def get_db_params():
    """Return database parameters based on environment"""
    hostname = socket.gethostname()
    return database_config['server'] if 'vmi' in hostname.lower() else database_config['local']

def create_db_url():
    params = get_db_params()
    return f"postgresql://{params['user']}:{params['password']}@{params['host']}:{params['port']}/{params['dbname']}"

# Create engine with connection pooling
engine = create_engine(
    create_db_url(),
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def clean_currency_name(name: str) -> str:
    """Clean currency name by removing special characters and extra spaces."""
    return ' '.join(name.split())

def parse_rate_by_tax_type(rate_str: str, tax_id: str) -> float:
    """
    Parse rate string based on tax type pattern.
    Returns float value of the rate.
    """
    if not rate_str or not tax_id:
        return 0.0
        
    rate_str = str(rate_str).strip().lower()
    tax_id = str(tax_id).strip()
    
    # Handle empty or special cases without logging warnings
    if rate_str in ['-', '', 'no data', 'b', 'nan']:
        return 0.0
    
    # Handle SCTS18 special patterns
    if tax_id == 'SCTS18':
        if 'per lpa' in rate_str:
            # Extract numeric value from "J$ X,XXX per LPA"
            return float(rate_str.replace('j$', '').replace(',', '').split('per')[0].strip())
        elif 'per' in rate_str and 'gram' in rate_str:
            # Handle "$X.XX per 0.7 grams/stick" - extract first number
            return float(rate_str.split('per')[0].replace('$', '').strip())
        elif 'per stick' in rate_str:
            # Handle "$XX per stick"
            return float(rate_str.split('per')[0].replace('$', '').strip())
        elif 'per litre' in rate_str or 'per mmbtu' in rate_str:
            # Handle "$XX.XXXX per litre/mmbtu"
            return float(rate_str.split('per')[0].replace('$', '').strip())
        elif rate_str.startswith('$'):
            # Handle fixed amounts like "$38.3198"
            return float(rate_str.replace('$', '').replace(',', '').strip())
            
    # Handle ASD05 special patterns
    elif tax_id == 'ASD05' and 'per litre' in rate_str:
        # Handle "US$X.XX per litre"
        return float(rate_str.replace('us$', '').split('per')[0].strip())
        
    # Handle percentage rates
    if '%' in rate_str:
        return float(rate_str.rstrip('%').replace(',', ''))
    
    # Handle plain numbers
    try:
        return float(rate_str.replace(',', ''))
    except ValueError:
        logger.warning(f"Could not parse rate '{rate_str}' for tax ID {tax_id}, defaulting to 0.0")
        return 0.0

class BaseMixin:
    """Mixin class to add table creation and initialization functionality to models"""
    @classmethod
    def create_table(cls):
        if not inspect(engine).has_table(cls.__tablename__):
            logger.info(f"Creating table {cls.__tablename__}")
            cls.__table__.create(engine)
            logger.info(f"Table {cls.__tablename__} created successfully")
            return True
        return False

class Currency(Base, BaseMixin):
    """Model for currency information"""
    __tablename__ = 'currencies'
    
    id = Column(Integer, primary_key=True)
    entity = Column(String(100), nullable=False)  
    code = Column(String(3), nullable=False)      
    name = Column(String(100), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('entity', 'code', name='unique_entity_currency'),
    )
    
    @classmethod
    def initialize_data(cls):
        db = SessionLocal()
        try:
            if db.query(cls).first() is None:
                currency_file = Path("data/currency.csv")
                if currency_file.exists():
                    currencies_to_add = []
                    
                    with open(currency_file, 'r', encoding='utf-8') as f:
                        next(f)  # Skip header
                        reader = csv.reader(f)
                        
                        for row in reader:
                            try:
                                if len(row) >= 3:
                                    entity = str(row[0]).strip()
                                    name = clean_currency_name(str(row[1]))
                                    code = str(row[2]).strip().upper()
                                    
                                    if code and name and len(code) <= 3 and entity:
                                        currencies_to_add.append(cls(
                                            entity=entity,
                                            code=code,
                                            name=name
                                        ))
                            except Exception as e:
                                logger.warning(f"Error processing currency row: {e}")
                                continue
                    
                    if currencies_to_add:
                        db.bulk_save_objects(currencies_to_add)
                        db.commit()
                        logger.info(f"Currencies initialized successfully ({len(currencies_to_add)} records)")
        except Exception as e:
            logger.error(f"Error initializing currencies: {e}")
            db.rollback()
        finally:
            db.close()

class FXRate(Base, BaseMixin):
    """Model for foreign exchange rates"""
    __tablename__ = 'fx_rates'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    currency = Column(String(100), nullable=False)
    buying_rate = Column(Float, nullable=False)
    selling_rate = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('date', 'currency', name='unique_daily_rate'),
    )
    
    @classmethod
    def initialize_data(cls):
        db = SessionLocal()
        try:
            if db.query(cls).first() is None:
                fx_rates_file = Path("data/boj_indicative_rates.csv")
                if fx_rates_file.exists():
                    fx_rates_df = pd.read_csv(fx_rates_file)
                    batch_size = 100
                    fx_rates = []
                    
                    for _, row in fx_rates_df.iterrows():
                        try:
                            fx_rate = cls(
                                date=pd.to_datetime(row['Date']).date(),
                                currency=str(row['Currency']).strip(),
                                buying_rate=float(row['Buying']),
                                selling_rate=float(row['Selling']),
                                timestamp=datetime.utcnow()
                            )
                            fx_rates.append(fx_rate)
                            
                            if len(fx_rates) >= batch_size:
                                db.bulk_save_objects(fx_rates)
                                db.commit()
                                fx_rates = []
                        except Exception as e:
                            logger.warning(f"Error processing FX rate row: {e}")
                            continue
                    
                    if fx_rates:
                        db.bulk_save_objects(fx_rates)
                        db.commit()
                    logger.info("FX rates initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing FX rates: {e}")
            db.rollback()
        finally:
            db.close()

class TaxRate(Base, BaseMixin):
    """Model for tax rates associated with HS codes"""
    __tablename__ = 'tax_rates'
    
    id = Column(Integer, primary_key=True)
    hs_code = Column(String(20), nullable=False)
    tax_id = Column(String(20), nullable=False)
    rate = Column(Float, nullable=False)
    
    __table_args__ = (
        UniqueConstraint('hs_code', 'tax_id', name='unique_tax_rate'),
    )
    
    @classmethod
    def initialize_data(cls):
        db = SessionLocal()
        try:
            if db.query(cls).first() is None:
                tax_rates_file = Path("data/tax_rates.csv")
                if tax_rates_file.exists():
                    tax_rates_df = pd.read_csv(tax_rates_file, dtype={
                        'HS Code': str,
                        'ID': str,
                        'Rate': str
                    })
                    
                    batch_size = 1000
                    tax_rates = []
                    successful_rows = 0
                    error_rows = 0
                    
                    for _, row in tax_rates_df.iterrows():
                        try:
                            # Get raw values
                            hs_code = str(row['HS Code']).strip()
                            tax_id = str(row['ID']).strip()
                            rate_str = str(row['Rate']).strip()
                            
                            # Skip rows where tax_id is "No data" or invalid
                            if tax_id.lower() == 'no data' or not tax_id:
                                error_rows += 1
                                continue
                                
                            # Parse rate based on tax type
                            rate = parse_rate_by_tax_type(rate_str, tax_id)
                            
                            if hs_code and tax_id:  # Only proceed if both fields are present
                                tax_rate = cls(
                                    hs_code=hs_code,
                                    tax_id=tax_id,
                                    rate=rate
                                )
                                tax_rates.append(tax_rate)
                                successful_rows += 1
                                
                                if len(tax_rates) >= batch_size:
                                    db.bulk_save_objects(tax_rates)
                                    db.commit()
                                    tax_rates = []
                            else:
                                error_rows += 1
                                logger.warning(f"Missing HS code or tax ID in row")
                                
                        except Exception as e:
                            error_rows += 1
                            logger.warning(f"Error processing tax rate row: {str(e)}")
                            continue
                    
                    if tax_rates:
                        db.bulk_save_objects(tax_rates)
                        db.commit()
                    
                    logger.info(f"Successfully processed {successful_rows} tax rates")
                    if error_rows > 0:
                        logger.warning(f"Encountered {error_rows} errors while processing tax rates")
                    logger.info("Tax rates initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing tax rates: {e}")
            db.rollback()
        finally:
            db.close()
    
    @classmethod
    def get_rates_for_hs_code(cls, hs_code):
        """Get all tax rates for a given HS code"""
        session = SessionLocal()
        try:
            rates = session.query(cls).filter_by(hs_code=hs_code).all()
            return rates
        except Exception as e:
            logger.error(f"Error getting rates for HS code {hs_code}: {str(e)}")
            return []
        finally:
            session.close()
    
    def get_effective_rate(self):
        """Convert rate to decimal format (e.g., 0.15 for 15%)"""
        return self.rate / 100 if self.rate > 1 else self.rate

    def to_dict(self):
        """Convert the tax rate object to a dictionary"""
        return {
            'hs_code': self.hs_code,
            'tax_id': self.tax_id,
            'rate': self.rate,
            'effective_rate': self.get_effective_rate()
        }

    def __repr__(self):
        """String representation of the tax rate"""
        return f"<TaxRate(hs_code='{self.hs_code}', tax_id='{self.tax_id}', rate={self.rate})>"

def get_db():
    """Database dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize database function - ADD THIS HERE
def init_db():
    """Initialize database by creating all tables and seeding initial data if needed"""
    logger.info("Initializing database...")
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Tables created successfully")
        
        # Initialize model data
        Currency.initialize_data()
        FXRate.initialize_data()
        TaxRate.initialize_data()
        logger.info("Data initialization completed")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

# Export commonly used components
__all__ = ['get_db', 'Currency', 'FXRate', 'TaxRate', 'engine', 'SessionLocal', 'init_db']