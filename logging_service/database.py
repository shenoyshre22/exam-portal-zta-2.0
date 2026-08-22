
#object relation mapping tecnique which interacts with the databse.
#will be used in main.py to connect to the flask 
#Stores events from different service
#filtering by the user as well 
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Create data directory if it doesn't exist
os.makedirs('/app/data', exist_ok=True)

DATABASE_URL = "sqlite:////app/data/logs.db"


# Engine connects to DB
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Session = DB connection instance
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()