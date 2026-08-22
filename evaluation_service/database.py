from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,declarative_base
import os

# Create data directory if it doesn't exist
os.makedirs('/app/data', exist_ok=True)

#NOW this helps to create the database automatically
DATABASE_URL = "sqlite:////app/data/evaluation.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
#session= DB connection handler
SessionLocal=sessionmaker(bind=engine,autocommit=False,autoflush=False)
#making base class for models
Base=declarative_base()
