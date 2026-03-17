import os
from dotenv import load_dotenv

import httpx
import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, Query, Header
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import engine, get_db, SessionLocal
from models import Base, DBWebsite, PingLog
from schemas import Website

import io
import pandas as pd
from fastapi.responses import StreamingResponse

Base.metadata.create_all(bind=engine)
# This creates your web server
app = FastAPI(title="My Super Monitorr")


# 2. Pydantic Model: This tells FastAPI exactly what a "Website" should look like

# This tells the server what to do when someone visits the homepage

load_dotenv()
API_KEY_CREDENTIAL = os.getenv("API_KEY_CREDENTIAL")

def verify_api_key(api_key: Annotated[str, Header()] = None):
    if api_key != API_KEY_CREDENTIAL:
        raise HTTPException(status_code=401, detail="Wrong api key. Access denied!")
    return api_key

@app.post("/add-website")
def add_website(site: Website,
                db: Session = Depends(get_db),
                _ : str = Depends(verify_api_key)
                ):
    new_website = DBWebsite(url=site.url)

    try:
        db.add(new_website)
        db.commit()
        return{"message": f"Saved {site.url} permanently to the database!"}

    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Website already exists in our system!")

@app.get("/websites")
def get_websites(db: Session = Depends(get_db)):
    query = select(DBWebsite)
    all_websites = db.execute(query).scalars().all()
    return {"currently_tracking": all_websites}

@app.get("/web")
def get_websites_count(
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    db: Session = Depends(get_db)):
    total_count = db.execute(select(func.count(DBWebsite.id))).scalar()

    if limit > total_count:
        raise HTTPException(
            status_code=400,
            detail=f"Requested {limit} but only {total_count} in database"
        )

    results = db.execute(select(DBWebsite).limit(limit)).scalars().all()
    return {
        "total_available": total_count,
        "returned_count": len(results),
        "data": results
    }

@app.get("/web-by/{id}")
def web_get_by_id(
        id: int,
        db: Session = Depends(get_db)):
        web = db.execute(select(DBWebsite).where(DBWebsite.id == id)).scalar_one_or_none()
        if web is None:
            raise HTTPException(status_code = 404, detail="ID not found")

        return{"message": f"{id} and found {web.url}"}

@app.get("/web-by-url")
def web_by_url(
        url: str,
        db: Session = Depends(get_db)):
    print(url)
    web = db.execute(select(DBWebsite).where(DBWebsite.url == url)).scalar_one_or_none()
    if web is None:
        raise HTTPException(status_code = 404, detail="Web not found")
    return{"message": f"Web found {web.url}"}

@app.get("/check-all")
async def check_all_websites(db: Session = Depends(get_db)):
    websites = db.query(DBWebsite).all()
    results = []

    async with httpx.AsyncClient() as client:
        for site in websites:
            try:
                response = await client.get(f"https://www.{site.url}", timeout=5.0)

                if response.status_code == 200:
                    site.status = "Online 🟢"
                else:
                    site.status = f"Warning 🟠 ({response.status_code})"
            except Exception:
                site.status = "Offline 🔴"

            site.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results.append({"url": site.url, "status": site.status})

        db.commit()
        return {"results": results}

@app.delete("/delete-web")
def delete_web(site: Website, db: Session = Depends(get_db)):
    statement = select(DBWebsite).where(DBWebsite.url == site.url)
    result = db.execute(statement)
    web_del = result.scalar_one_or_none()

    if web_del is None:
        raise HTTPException(status_code=404, detail= "Web not in database")
    try:
        db.delete(web_del)
        db.commit()
        return{"message" : f"Web deleted: {site.url}"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Web deleting error")

async def monitor_loop():

    while True:
        print("Starting automatic scan of webs")

        db = SessionLocal()
        try:
            fake_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            websites = db.execute(select(DBWebsite)).scalars().all()
            async with httpx.AsyncClient() as client:
                for site in websites:
                    try:
                        response = await client.get(f"https://www.{site.url}", timeout=5.0, follow_redirects=True, headers=fake_headers)
                        site.status = "Online 🟢" if response.status_code == 200 else f"Warning 🟠 ({response.status_code})"
                    except Exception:
                        site.status = "Offline 🔴"

                    site.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    new_log = PingLog(timestamp=site.last_checked,
                                      status_code=response.status_code,
                                      )
                    site.logs.append(new_log)
                db.commit()
                print("Automatic scan of webs done")

        finally:
            db.close()

        await asyncio.sleep(60)

@app.get("/web-logs/{log_id}/")
def show_logs(log_id: int, db: Session = Depends(get_db)):
   # log = db.execute(select(PingLog).where(PingLog.id == log_id)).scalar_one_or_none()
    log = db.execute(select(PingLog).join(PingLog.owner).where(PingLog.id == log_id))
    if log:
        return {
            "log_time": log.timestamp,
            "web_url": log.owner.url,
            "all-logs": [l.timestamp for l in log.owner.logs]
        }
    return {"error": "log not found"}

@app.get("/web/{id}/stats")
def show_web_stats(id: int, db: Session = Depends(get_db)):
    web = db.execute(select(DBWebsite).where(DBWebsite.id == id)).scalar_one_or_none()

    if web is None:
        raise HTTPException(status_code=404, detail="Web not found")
    total_pings = len(web.logs)
    total_pings = db.execute(select(func.count(PingLog.id).where(PingLog.website_id == id))
    ).scalar() or 0
    success_pings = db.execute(select(func.count(PingLog.id).where(PingLog.website_id == id).where(PingLog.status_code == 200))).scalar() or 0

    uptime_percentage = success_pings/total_pings * 100

    return {
        "url": web.url,
        "total_checks": total_pings,
        "uptime": f"{uptime_percentage:.2f}%",
        "status": "Healthy" if uptime_percentage > 95 else "Degraded"
    }


@app.patch("/update-web/{web_id}")
def web_url_change(
        web_id: int,
        site_update: Website,
        db: Session = Depends(get_db),
        _ : str = Depends(verify_api_key)
):
    statement = select(DBWebsite).where(DBWebsite.id == web_id)
    web_to_update = db.execute(statement).scalar_one_or_none()

    if web_to_update is None:
        raise HTTPException(status_code=404, detail="Web with this ID doesn't exist")

    old_url = web_to_update.url
    web_to_update.url = site_update.url

    try:
        db.commit()
        db.refresh(web_to_update)

        return {
            "message": f"URL changed from {old_url} to {web_to_update.url}.",
            "web_id": web_to_update.id
        }
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="This url already exists in database")

@app.get("/export-csv/{website_id}")
def export_csv(website_id: int, db: Session = Depends(get_db)):
    stmt = select(PingLog).where(PingLog.website_id == website_id)
    logs = db.execute(stmt).scalars().all()

    data = [{"time": l.timestamp, "status": l.status_code} for l in logs]

    df = pd.DataFrame(data)
    #CSV version
    '''
    stream = io.StringIO()

    df.to_csv(stream, index=False)

    stream.seek(0)

    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pings_{website_id}.csv"}
    )
    '''
    #EXCEL version
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Uptime Report")

        #workbook = writer.book
        worksheet = writer.sheets["Uptime Report"]

        from openpyxl.styles import Font
        header_font = Font(bold=True, color="FFFFFF")
        from openpyxl.styles import PatternFill
        header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")

        for cell in worksheet[1]:
            cell.font = header_font
            cell.fill = header_fill

        for col in worksheet.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
                worksheet.column_dimensions[column].width = max_length + 2


    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=report.xlsx"}
    )


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_loop())

