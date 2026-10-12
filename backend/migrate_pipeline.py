from database import engine
from sqlalchemy import text, inspect

insp = inspect(engine)
cols = [c["name"] for c in insp.get_columns("repos")]
print("Existing cols:", cols)

with engine.connect() as conn:
    if "pipeline_status" not in cols:
        conn.execute(text("ALTER TABLE repos ADD COLUMN pipeline_status VARCHAR NOT NULL DEFAULT 'DONE'"))
        print("Added pipeline_status")
    if "pipeline_error" not in cols:
        conn.execute(text("ALTER TABLE repos ADD COLUMN pipeline_error TEXT"))
        print("Added pipeline_error")
    if "pipeline_meta" not in cols:
        conn.execute(text("ALTER TABLE repos ADD COLUMN pipeline_meta TEXT"))
        print("Added pipeline_meta")
    conn.commit()
print("Migration done")
