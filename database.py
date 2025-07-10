from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class Paper(Base):
    __tablename__ = 'papers'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    authors = Column(String)  # Stored as a comma-separated string
    venue = Column(String)
    year = Column(Integer)
    abstract = Column(Text)
    pdf_path = Column(String)
    arxiv_id = Column(String)
    dblp_url = Column(String)
    google_scholar_url = Column(String)
    notes = Column(Text)
    paper_type = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Paper(title='{self.title}', authors='{self.authors}', year={self.year})>"

DATABASE_URL = "sqlite:///./papers.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Database initialized and tables created.")
