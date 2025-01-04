from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import Dict, Optional
from pathlib import Path
import uvicorn
import logging
from datetime import datetime
import pytz
from sqlalchemy.orm import Session
from sqlalchemy import desc

from utils.customs_computation import (
    calculate_cif,
    get_tax_rates,
    calculate_custom_charges,
    determine_caf_rate
)
from utils.fx_rates_scraper import check_and_update_fx_rates
from utils.database import SessionLocal, engine, Base, init_db, FXRate

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Customs Calculator API")

# Mount static files directory if needed
static_dir = Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount data directory for tax rates
data_dir = Path("data")
if data_dir.exists():
    app.mount("/data", StaticFiles(directory="data"), name="data")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CIFRequest(BaseModel):
    product_price: float = Field(..., gt=0)
    product_currency: str
    freight_charges: float = Field(..., ge=0)
    freight_currency: str
    mode_of_transportation: str

class CustomsRequest(BaseModel):
    hs_code: str
    transaction_type: str
    package_type: str
    product_price: float = Field(..., gt=0)
    product_currency: str
    freight_charges: float = Field(..., ge=0)
    freight_currency: str
    mode_of_transportation: str

@app.on_event("startup")
async def startup_event():
    """Initialize database and validate currency data on startup"""
    try:
        # Create database tables
        Base.metadata.create_all(bind=engine)
        
        # Initialize database with tax rates if needed
        init_db()
        
        # Validate currency data
        db = SessionLocal()
        try:
            # Check if we have any FX rates
            latest_date = db.query(FXRate.date).order_by(desc(FXRate.date)).first()
            if not latest_date:
                logger.warning("No FX rates found in database!")
            else:
                logger.info(f"Latest FX rates date: {latest_date[0]}")
            
            # Update FX rates
            await check_and_update_fx_rates(db)
            
        finally:
            db.close()
            
        logger.info("Startup tasks completed successfully")
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the index.html template."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/calculate-cif")
async def calculate_cif_endpoint(
    request: CIFRequest,
    db: Session = Depends(get_db)
):
    try:
        result = calculate_cif(
            product_price=request.product_price,
            product_currency=request.product_currency,
            freight_charges=request.freight_charges,
            freight_currency=request.freight_currency,
            mode_of_transportation=request.mode_of_transportation,
            db=db  # Pass the database session
        )
        return result
    except Exception as e:
        logger.error(f"Error calculating CIF: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/calculate-customs")
async def calculate_customs_endpoint(
    request: CustomsRequest,
    db: Session = Depends(get_db)
):
    try:
        # Calculate CIF
        cif_result = calculate_cif(
            product_price=request.product_price,
            product_currency=request.product_currency,
            freight_charges=request.freight_charges,
            freight_currency=request.freight_currency,
            mode_of_transportation=request.mode_of_transportation,
            db=db  # Pass the database session
        )
        
        # Get tax rates
        tax_rates = get_tax_rates(request.hs_code, db)  # Pass the database session
        if not tax_rates:
            raise HTTPException(
                status_code=404,
                detail=f"No tax rates found for HS code: {request.hs_code}"
            )
        
        # Calculate CAF
        caf = determine_caf_rate(
            transaction_type=request.transaction_type,
            package_type=request.package_type,
            cif_value=cif_result['cif_usd'],
            input_currency='USD',
            db=db  # Pass the database session
        )
        
        # Calculate customs charges
        charges, rates = calculate_custom_charges(tax_rates, cif_result['cif_jmd'], caf)
        
        return {
            "cif_details": cif_result,
            "tax_rates": rates,
            "charges": charges,
            "total_custom_charges": charges['total_custom_charges']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating customs charges: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/update-fx-rates")
async def update_fx_rates_endpoint(db: Session = Depends(get_db)):
    """Endpoint to manually trigger FX rates update"""
    try:
        await check_and_update_fx_rates(db)
        return {"message": "FX rates updated successfully"}
    except Exception as e:
        logger.error(f"Error updating FX rates: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update FX rates"
        )

def start():
    """Startup function for the application"""
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    start()