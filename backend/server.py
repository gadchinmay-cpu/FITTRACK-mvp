from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

import os, sqlite3, secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
import bcrypt, jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.environ["SQLITE_DB_PATH"]
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

def conn():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def now(): return datetime.now(IST).isoformat(timespec="seconds")
def today(): return datetime.now(IST).date()
def rows(cur): return [dict(r) for r in cur.fetchall()]

def status_for(expiry):
    days = (date.fromisoformat(expiry) - today()).days
    return ("EXPIRED" if days < 0 else "EXPIRING SOON" if days <= 7 else "ACTIVE"), days

def init_db():
    db = conn()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS membership_plans(id INTEGER PRIMARY KEY, name TEXT NOT NULL, duration_months INTEGER NOT NULL, price REAL NOT NULL, description TEXT, is_active INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, member_id TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, date_of_birth TEXT, gender TEXT, address TEXT, joining_date TEXT NOT NULL, emergency_contact TEXT, trainer TEXT, notes TEXT, archived INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS memberships(id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), plan_id INTEGER NOT NULL REFERENCES membership_plans(id), start_date TEXT NOT NULL, expiry_date TEXT NOT NULL, total_price REAL NOT NULL, created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), membership_id INTEGER REFERENCES memberships(id), amount REAL NOT NULL CHECK(amount > 0), payment_date TEXT NOT NULL, payment_method TEXT NOT NULL, transaction_reference TEXT, notes TEXT, created_by INTEGER REFERENCES users(id), created_at TEXT);
    CREATE TABLE IF NOT EXISTS activity_logs(id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, entity_type TEXT, entity_id INTEGER, description TEXT, created_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_members_search ON members(member_id, phone, full_name); CREATE INDEX IF NOT EXISTS idx_memberships_expiry ON memberships(expiry_date); CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
    """)
    user = db.execute("SELECT id FROM users WHERE email=?", (ADMIN_EMAIL,)).fetchone()
    if not user:
        db.execute("INSERT INTO users(name,email,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("Gym Admin", ADMIN_EMAIL, bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode(), "admin", now(), now()))
    if db.execute("SELECT COUNT(*) c FROM membership_plans").fetchone()[0] == 0:
        for p in [("1 Month",1,1500,"Flexible monthly access"),("3 Months",3,4000,"Best for consistency"),("6 Months",6,7000,"Half-year commitment"),("12 Months",12,12000,"Best value")]: db.execute("INSERT INTO membership_plans(name,duration_months,price,description,created_at,updated_at) VALUES(?,?,?,?,?,?)", (*p,now(),now()))
    if db.execute("SELECT COUNT(*) c FROM members").fetchone()[0] == 0:
        demo_names=["Rahul Sharma","Priya Mehta","Arjun Nair","Sneha Kapoor","Vikram Singh","Ananya Rao","Kabir Malhotra","Ishita Shah","Rohan Desai","Neha Iyer","Aditya Joshi","Meera Pillai","Sahil Khan","Tanya Verma","Karan Bhat"]
        for i,name in enumerate(demo_names):
            created=(datetime.now(IST)-timedelta(days=i*5)).isoformat(timespec="seconds"); phone=f"98{10000000+i:08d}"[:10]
            c=db.execute("INSERT INTO members(member_id,full_name,phone,joining_date,created_at,updated_at) VALUES(?,?,?,?,?,?)",(f"GYM-{1001+i}",name,phone,(today()-timedelta(days=120+i*7)).isoformat(),created,created))
            plan_id=(i%4)+1; start=today()-timedelta(days=30+i*8); expiry=start+timedelta(days=round(365.25*[1,3,6,12][plan_id-1]/12))
            if i%5==0: expiry=today()-timedelta(days=12+i)
            if i%5==1: expiry=today()+timedelta(days=3+i)
            price=[1500,4000,7000,12000][plan_id-1]; mc=db.execute("INSERT INTO memberships(member_id,plan_id,start_date,expiry_date,total_price,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(c.lastrowid,plan_id,start.isoformat(),expiry.isoformat(),price,created,created))
            if i%3!=0: db.execute("INSERT INTO payments(member_id,membership_id,amount,payment_date,payment_method,created_at) VALUES(?,?,?,?,?,?)",(c.lastrowid,mc.lastrowid,price if i%2 else price/2,(today()-timedelta(days=i)).isoformat(),("UPI" if i%2 else "Cash"),created))
            db.execute("INSERT INTO activity_logs(action,entity_type,entity_id,description,created_at) VALUES(?,?,?,?,?)",("created","member",c.lastrowid,f"New member {name}",created))
    db.commit(); db.close()

app = FastAPI(title="IronCore Gym Management")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")

class Login(BaseModel): email: str; password: str
class MemberIn(BaseModel): full_name: str; phone: str = Field(min_length=10); email: Optional[EmailStr]=None; date_of_birth: Optional[str]=None; gender: Optional[str]=None; address: Optional[str]=None; joining_date: str; emergency_contact: Optional[str]=None; trainer: Optional[str]=None; notes: Optional[str]=None
class PlanIn(BaseModel): name: str; duration_months: int = Field(gt=0, le=60); price: float = Field(ge=0); description: Optional[str]=None; is_active: bool=True
class MembershipIn(BaseModel): plan_id: int; start_date: str; total_price: Optional[float]=None
class PaymentIn(BaseModel): amount: float = Field(gt=0); payment_date: str; payment_method: str; transaction_reference: Optional[str]=None; notes: Optional[str]=None

def auth(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Authentication required")
    try: return jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError: raise HTTPException(401, "Invalid or expired session")

def token(user): return jwt.encode({"sub":str(user["id"]),"email":user["email"],"role":user["role"],"exp":datetime.now(IST)+timedelta(hours=8)}, JWT_SECRET, algorithm="HS256")
def member_view(db, m):
    latest=db.execute("SELECT * FROM memberships WHERE member_id=? ORDER BY expiry_date DESC LIMIT 1",(m["id"],)).fetchone()
    if not latest: return {**m,"status":"NO MEMBERSHIP","days_remaining":None,"total_price":0,"paid":0,"pending":0}
    paid=db.execute("SELECT COALESCE(SUM(amount),0) v FROM payments WHERE membership_id=?",(latest["id"],)).fetchone()["v"]
    status, days=status_for(latest["expiry_date"])
    return {**m,"membership_id":latest["id"],"plan_id":latest["plan_id"],"start_date":latest["start_date"],"expiry_date":latest["expiry_date"],"total_price":latest["total_price"],"paid":paid,"pending":max(0,latest["total_price"]-paid),"status":status,"days_remaining":days}

@api.post("/auth/login")
def login(data: Login):
    db=conn(); u=db.execute("SELECT * FROM users WHERE email=?",(data.email.lower(),)).fetchone(); db.close()
    if not u or not bcrypt.checkpw(data.password.encode(), u["password_hash"].encode()): raise HTTPException(401,"Invalid email or password")
    return {"token":token(u),"user":{"name":u["name"],"email":u["email"],"role":u["role"]}}
@api.get("/auth/me")
def me(user=Depends(auth)): return user
@api.post("/auth/logout")
def logout(user=Depends(auth)): return {"message":"Logged out"}

@api.get("/dashboard")
def dashboard(user=Depends(auth)):
    db=conn(); members=[member_view(db,m) for m in rows(db.execute("SELECT * FROM members WHERE archived=0 ORDER BY created_at DESC"))]; month=today().strftime("%Y-%m")
    revenue=db.execute("SELECT COALESCE(SUM(amount),0) v FROM payments WHERE substr(payment_date,1,7)=?",(month,)).fetchone()["v"]
    activities=rows(db.execute("SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 8")); db.close()
    return {"stats":{"total_members":len(members),"active":sum(x["status"]=="ACTIVE" for x in members),"expired":sum(x["status"]=="EXPIRED" for x in members),"expiring_7":sum(x["days_remaining"] is not None and 0<=x["days_remaining"]<=7 for x in members),"expiring_30":sum(x["days_remaining"] is not None and 0<=x["days_remaining"]<=30 for x in members),"revenue_month":revenue,"pending":sum(x["pending"] for x in members),"new_this_month":sum(x["created_at"].startswith(month) for x in members)},"activities":activities}

@api.get("/members")
def list_members(q: str="", status: str="all", user=Depends(auth)):
    db=conn(); data=[member_view(db,m) for m in rows(db.execute("SELECT * FROM members WHERE archived=0 AND (full_name LIKE ? OR phone LIKE ? OR member_id LIKE ?) ORDER BY created_at DESC",(f"%{q}%",f"%{q}%",f"%{q}%")))]; db.close()
    if status!="all": data=[m for m in data if m["status"]==status]
    return data
@api.post("/members")
def create_member(data: MemberIn, user=Depends(auth)):
    db=conn(); mid="GYM-"+secrets.token_hex(3).upper(); cur=db.execute("INSERT INTO members(member_id,full_name,phone,email,date_of_birth,gender,address,joining_date,emergency_contact,trainer,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(mid,*data.model_dump().values(),now(),now())); db.execute("INSERT INTO activity_logs(user_id,action,entity_type,entity_id,description,created_at) VALUES(?,?,?,?,?,?)",(user["sub"],"created","member",cur.lastrowid,f"New member {data.full_name}",now())); db.commit(); out=member_view(db,db.execute("SELECT * FROM members WHERE id=?",(cur.lastrowid,)).fetchone()); db.close(); return out
@api.get("/members/{member_id}")
def get_member(member_id:int,user=Depends(auth)):
    db=conn(); m=db.execute("SELECT * FROM members WHERE id=?",(member_id,)).fetchone()
    if not m: raise HTTPException(404,"Member not found")
    out=member_view(db,m); out["payments"]=rows(db.execute("SELECT * FROM payments WHERE member_id=? ORDER BY payment_date DESC",(member_id,))); db.close(); return out
@api.put("/members/{member_id}")
def update_member(member_id:int,data:MemberIn,user=Depends(auth)):
    db=conn(); vals=data.model_dump(); db.execute("UPDATE members SET full_name=?,phone=?,email=?,date_of_birth=?,gender=?,address=?,joining_date=?,emergency_contact=?,trainer=?,notes=?,updated_at=? WHERE id=?",(*vals.values(),now(),member_id)); db.commit(); m=db.execute("SELECT * FROM members WHERE id=?",(member_id,)).fetchone(); db.close(); return m
@api.delete("/members/{member_id}")
def archive_member(member_id:int,user=Depends(auth)): db=conn(); db.execute("UPDATE members SET archived=1,updated_at=? WHERE id=?",(now(),member_id)); db.commit(); db.close(); return {"ok":True}

@api.get("/plans")
def plans(user=Depends(auth)): db=conn(); x=rows(db.execute("SELECT * FROM membership_plans ORDER BY duration_months")); db.close(); return x
@api.post("/plans")
def create_plan(data:PlanIn,user=Depends(auth)): db=conn(); c=db.execute("INSERT INTO membership_plans(name,duration_months,price,description,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(*data.model_dump().values(),now(),now())); db.commit(); x=dict(db.execute("SELECT * FROM membership_plans WHERE id=?",(c.lastrowid,)).fetchone()); db.close(); return x
@api.post("/members/{member_id}/memberships")
def add_membership(member_id:int,data:MembershipIn,user=Depends(auth)):
    db=conn(); p=db.execute("SELECT * FROM membership_plans WHERE id=?",(data.plan_id,)).fetchone()
    if not p: raise HTTPException(404,"Plan not found")
    start=date.fromisoformat(data.start_date); expiry=start + timedelta(days=round(365.25*p["duration_months"]/12)); price=p["price"] if data.total_price is None else data.total_price
    c=db.execute("INSERT INTO memberships(member_id,plan_id,start_date,expiry_date,total_price,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(member_id,p["id"],start.isoformat(),expiry.isoformat(),price,now(),now())); db.commit(); x=dict(db.execute("SELECT * FROM memberships WHERE id=?",(c.lastrowid,)).fetchone()); db.close(); return x
@api.post("/members/{member_id}/payments")
def add_payment(member_id:int,data:PaymentIn,user=Depends(auth)):
    db=conn(); m=member_view(db,db.execute("SELECT * FROM members WHERE id=?",(member_id,)).fetchone())
    if data.amount>m["pending"]: raise HTTPException(400,f"Payment exceeds pending amount ₹{m['pending']:.0f}")
    c=db.execute("INSERT INTO payments(member_id,membership_id,amount,payment_date,payment_method,transaction_reference,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(member_id,m.get("membership_id"),*data.model_dump().values(),user["sub"],now())); db.commit(); x=dict(db.execute("SELECT * FROM payments WHERE id=?",(c.lastrowid,)).fetchone()); db.close(); return x
@api.get("/expiring")
def expiring(filter:str="30",user=Depends(auth)):
    db=conn(); data=[member_view(db,m) for m in rows(db.execute("SELECT * FROM members WHERE archived=0"))]; db.close(); return [m for m in data if (filter=="expired" and m["status"]=="EXPIRED") or (filter in ("7","30") and m["days_remaining"] is not None and 0<=m["days_remaining"]<=int(filter))]
@api.get("/reports")
def reports(user=Depends(auth)):
    db=conn(); payments=rows(db.execute("SELECT payment_method, COUNT(*) count, SUM(amount) total FROM payments GROUP BY payment_method")); monthly=rows(db.execute("SELECT substr(payment_date,1,7) month,SUM(amount) total,COUNT(*) count FROM payments GROUP BY month ORDER BY month DESC LIMIT 12")); total=db.execute("SELECT COALESCE(SUM(amount),0) v FROM payments").fetchone()["v"]; db.close(); return {"total_revenue":total,"payments":payments,"monthly":monthly}

app.include_router(api)
@app.on_event("startup")
def startup(): init_db()