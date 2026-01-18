import time
import pandas as pd
import undetected_chromedriver as uc
import os
import datetime
import re
import random
import yaml
import json
import smtplib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv
from thefuzz import fuzz 
from dateutil.relativedelta import relativedelta 
import logging
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn, TaskProgressColumn
from rich.theme import Theme
from pdf_manager import PDFManager  # ✅ เพิ่มบรรทัดนี้

# --- SETUP & CONFIG ---
try:
    from fake_useragent import UserAgent
except ImportError:
    UserAgent = None

logging.getLogger("fake_useragent").setLevel(logging.CRITICAL)

def suppress_del_error(self):
    try: self.quit()
    except Exception: pass
uc.Chrome.__del__ = suppress_del_error

ENV_PATH = "User.env"
COMPETITORS_PATH = "compe.yaml"
CLIENTS_PATH = "co.yaml"
TIER1_PATH = "tier1.yaml"
RESUME_IMAGE_FOLDER = "resume_images" 
USE_HEADLESS_JOBTHAI = False 
EMAIL_USE_HISTORY = True       

rec_env = os.getenv("EMAIL_RECEIVER")
MANUAL_EMAIL_RECEIVERS = [rec_env] if rec_env else []

custom_theme = Theme({"info": "dim cyan", "warning": "yellow", "error": "bold red", "success": "bold green"})
console = Console(theme=custom_theme)

load_dotenv(ENV_PATH, override=True)
MY_USERNAME = os.getenv("JOBTHAI_USER")
MY_PASSWORD = os.getenv("JOBTHAI_PASS")

G_SHEET_KEY_JSON = os.getenv("G_SHEET_KEY")
G_SHEET_NAME = os.getenv("G_SHEET_NAME")

TIER1_TARGETS = {}
if os.path.exists(TIER1_PATH):
    try:
        with open(TIER1_PATH, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
            if yaml_data:
                for k, v in yaml_data.items():
                    if v:
                        if isinstance(v, list): TIER1_TARGETS[k] = [str(x).strip() for x in v]
                        else: TIER1_TARGETS[k] = [str(v).strip()]
    except Exception as e: console.print(f"⚠️ Load Tier1 Error: {e}", style="yellow")

TARGET_COMPETITORS_TIER2 = [] 
if os.path.exists(COMPETITORS_PATH):
    try:
        with open(COMPETITORS_PATH, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
            if yaml_data and 'competitors' in yaml_data:
                TARGET_COMPETITORS_TIER2 = [str(x).strip() for x in yaml_data['competitors'] if x]
    except: pass

CLIENTS_TARGETS = {}
if os.path.exists(CLIENTS_PATH):
    try:
        with open(CLIENTS_PATH, "r", encoding="utf-8") as f:
            CLIENTS_TARGETS = yaml.safe_load(f) or {}
            for k in list(CLIENTS_TARGETS.keys()):
                if not CLIENTS_TARGETS[k]: del CLIENTS_TARGETS[k]
                elif not isinstance(CLIENTS_TARGETS[k], list): CLIENTS_TARGETS[k] = [str(CLIENTS_TARGETS[k])]
    except: pass

# --- TARGET CONFIG ---
TARGET_UNIVERSITIES = ["แม่ฟ้าหลวง","มหาลัยแม่ฟ้าหลวง", "Mae Fah Luang University"]  
TARGET_FACULTIES = ["เครื่องสำอาง","Cosmetic"] 
TARGET_MAJORS = ["เครื่องสำอาง", "Cosmetics", "Cosmetic"]
SEARCH_KEYWORDS = ["แม่ฟ้าหลวง เครื่องสำอาง"]

# --- 🟢 เพิ่มชุดนี้ไว้ใต้ SEARCH_KEYWORDS ---
# คีย์เวิร์ดที่อยู่ในกลุ่มเดียวกัน จะใช้ประวัติร่วมกัน (ป้องกันส่งเมลซ้ำ)
MEMORY_GROUPS = {
    "แม่ฟ้าหลวง_Cosmetic": ["แม่ฟ้าหลวง เครื่องสำอาง", "Cosmetic Mae Fah Luang", "เครื่องสำอาง แม่ฟ้าหลวง" , "แม่ฟ้าหลวง เทคโนโลยีความงาม" , "Beauty Mae Fah Luang"],
}


KEYWORDS_CONFIG = {
    "NPD": {"titles": ["NPD", "R&D", "RD", "Research", "Development", "วิจัย", "พัฒนา", "Formulation", "สูตร"]},
    "PCM": {"titles": ["PCM", "Production", "ผลิต", "Manufacturing", "Factory", "โรงงาน", "QA", "QC"]},
    "Sales": {"titles": ["Sale", "Sales", "ขาย", "AE", "BD", "Customer", "Telesale"]},
    "MKT": {"titles": ["MKT", "Marketing", "การตลาด", "Digital", "Content", "Media", "Ads"]},
    "Admin": {"titles": ["Admin", "ธุรการ", "ประสานงาน", "Coordinator", "Document", "เอกสาร"]},
    "HR": {"titles": ["HR", "Recruit", "สรรหา", "บุคคล", "Training", "Payroll"]},
    "SCM": {"titles": ["SCM", "Supply Chain", "Logistic", "ขนส่ง", "Warehouse", "Stock", "Import", "Export"]},
    "PUR": {"titles": ["PUR", "Purchase", "จัดซื้อ", "Sourcing", "Buyer"]},
    "DATA": {"titles": ["Data", "ข้อมูล", "Analyst", "Statistic", "สถิติ"]},
    "Present": {"titles": ["Present", "Speaker", "วิทยากร", "Trainer"]},
    "IT": {"titles": ["IT", "Computer", "Software", "Programmer", "Developer"]},
    "RA": {"titles": ["RA", "Regulatory", "อย.", "FDA", "ขึ้นทะเบียน"]},
    "ACC": {"titles": ["ACC", "Account", "บัญชี", "Finance", "การเงิน", "Audit"]}
}

def analyze_row_department(row):
    scores = {dept: 0 for dept in KEYWORDS_CONFIG.keys()}
    target_cols = ['ตำแหน่งที่ต้องการสมัคร_1', 'ตำแหน่งที่ต้องการสมัคร_2', 'ตำแหน่งที่ต้องการสมัคร_3']
    for col in target_cols:
        if col not in row or pd.isna(row[col]): continue
        text_val = str(row[col]).lower()
        for dept, config in KEYWORDS_CONFIG.items():
            for keyword in config['titles']:
                if keyword.lower() in text_val:
                    scores[dept] += 33
                    break 
    if not scores: return pd.Series(["Uncategorized", 0, ""])
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_dept, max_score = sorted_scores[0]
    return pd.Series([best_dept, int(min(max_score, 100)), ", ".join([f"{k}({v})" for k, v in sorted_scores if v > 0])])

class JobThaiRowScraper:
    def __init__(self):
        console.rule("[bold cyan]🛡️ JobThai Scraper (GitHub Actions Optimized)[/]")
        self.history_file = "notification_history_uni.json" 
        self.history_data = {}
        if not os.path.exists(RESUME_IMAGE_FOLDER): os.makedirs(RESUME_IMAGE_FOLDER, exist_ok=True)
        
        if EMAIL_USE_HISTORY and os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f: self.history_data = json.load(f)
            except: self.history_data = {}

        # --- Driver Configuration ---
        opts = uc.ChromeOptions()
        
        opts.add_argument('--window-size=1920,1080')
        opts.add_argument("--no-sandbox") 
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--disable-gpu") 
        opts.add_argument("--lang=th-TH")
        # ✅ [เพิ่ม] ปิดการแจ้งเตือน Automation เพื่อความเนียน
        opts.add_argument("--disable-blink-features=AutomationControlled") 
      
        
        # ✅ ใช้ Static User Agent
        my_static_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        opts.add_argument(f'--user-agent={my_static_ua}')

        try:
            self.driver = uc.Chrome(options=opts, version_main=None) 
        except Exception as e:
            console.print(f"⚠️ Driver Init Fail (Retry): {e}", style="yellow")
            self.driver = uc.Chrome(options=opts)
        
        self.driver.set_page_load_timeout(60) 
        self.wait = WebDriverWait(self.driver, 20)
        self.total_profiles_viewed = 0 
        self.all_scraped_data = []
        self.ua = None 
        # 🟢 เพิ่มส่วนนี้ท้าย __init__
        self.sheet_client = None
        self.sh = None  # ตัวแปรเก็บไฟล์ Spreadsheet หลัก
        self.current_history_data = {} # เก็บประวัติของกลุ่ม Keyword ที่กำลังรัน
        self.current_history_worksheet = None # เก็บหน้า Tab ประวัติปัจจุบัน
        # ✅ เรียกใช้ PDF Manager (ส่ง Key ชุดเดียวกับ Sheet)
        self.pdf_helper = PDFManager(G_SHEET_KEY_JSON)
        # 🟢 เพิ่มตัวแปรเก็บความจำลิงก์ PDF ของวันนี้
        self.daily_pdf_cache = {}

        try:
            if G_SHEET_KEY_JSON and G_SHEET_NAME:
                creds_dict = json.loads(G_SHEET_KEY_JSON)
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                self.sheet_client = gspread.authorize(creds)
                self.sh = self.sheet_client.open(G_SHEET_NAME)
                console.print(f"✅ เชื่อมต่อ Google Sheet หลักสำเร็จ", style="success")
        except Exception as e:
            console.print(f"❌ เชื่อมต่อ Google Sheet ไม่ได้: {e}", style="error")

    # 🟢 เพิ่มฟังก์ชันใหม่สำหรับโหลดลิงก์ที่เคยอัปโหลดไปแล้ววันนี้
    def load_daily_pdf_cache(self):
        if not self.sh: return
        today_str = datetime.datetime.now().strftime("%d-%m-%Y")
        try:
            ws = self.sh.worksheet(today_str)
            all_rows = ws.get_all_values()
            if len(all_rows) > 1:
                header = all_rows[0]
                try:
                    id_idx = header.index("รหัสใบสมัคร")
                    pdf_idx = header.index("Resume_PDF_Link")
                    # โหลดข้อมูลเข้า Cache: { 'รหัส': 'ลิงก์' }
                    for row in all_rows[1:]:
                        if len(row) > max(id_idx, pdf_idx):
                            c_id = str(row[id_idx]).strip()
                            link = str(row[pdf_idx]).strip()
                            if c_id and link:
                                self.daily_pdf_cache[c_id] = link
                    console.print(f"📦 โหลดความจำ PDF ของวันนี้สำเร็จ ({len(self.daily_pdf_cache)} รายการ)", style="cyan")
                except ValueError:
                    pass # ยังไม่มีคอลัมน์ PDF
        except:
            pass # ยังไม่มี Tab ของวันนี้
            

    def get_history_tab_name(self, keyword):
        """ ค้นหากลุ่มของ Keyword เพื่อระบุชื่อ Tab ประวัติ """
        for group_name, keywords in MEMORY_GROUPS.items():
            if keyword in keywords:
                return f"History_{group_name}"
        # ถ้าไม่มีในกลุ่ม ให้ใช้ชื่อ keyword เอง (ลบอักขระพิเศษ)
        clean_name = re.sub(r'[^\w\sก-๙]', '', keyword).strip()
        return f"History_{clean_name[:20]}"

    def prepare_history_for_keyword(self, keyword):
        """ สลับหน้าประวัติและโหลดข้อมูลตามกลุ่ม Keyword """
        tab_name = self.get_history_tab_name(keyword)
        try:
            try:
                self.current_history_worksheet = self.sh.worksheet(tab_name)
                console.print(f"📖 ใช้ระบบความจำกลุ่ม: [bold yellow]{tab_name}[/]", style="info")
            except:
                self.current_history_worksheet = self.sh.add_worksheet(title=tab_name, rows="1000", cols="3")
                self.current_history_worksheet.append_row(["Candidate_ID", "Last_Sent_Date", "Source_Keyword"])
                console.print(f"🆕 สร้างกลุ่มความจำใหม่: [bold green]{tab_name}[/]", style="success")

            self.current_history_data = {}
            rows = self.current_history_worksheet.get_all_values()
            for row in rows[1:]:
                if len(row) >= 2:
                    self.current_history_data[str(row[0]).strip()] = str(row[1]).strip()
            return True
        except Exception as e:
            console.print(f"⚠️ ระบบประวัติขัดข้อง: {e}", style="red")
            return False

    def update_history_sheet(self, person_id, date_str):
        """ บันทึกประวัติคนที่มีการส่งเมลแล้วลง Google Sheet """
        if self.current_history_worksheet:
            try:
                self.current_history_worksheet.append_row([str(person_id), str(date_str), "Auto-Log"])
                self.current_history_data[str(person_id)] = str(date_str)
            except Exception as e:
                console.print(f"⚠️ บันทึกประวัติลง Sheet ไม่สำเร็จ: {e}", style="red")

    def save_history(self):
        if not EMAIL_USE_HISTORY: return
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f: json.dump(self.history_data, f, ensure_ascii=False, indent=4)
        except: pass

    def set_random_user_agent(self):
        pass 

    def random_sleep(self, min_t=4.0, max_t=7.0): time.sleep(random.uniform(min_t, max_t))

    def wait_for_page_load(self, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except: pass

    def safe_click(self, selector, by=By.XPATH, timeout=10):
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                element = WebDriverWait(self.driver, 2).until(EC.presence_of_element_located((by, selector)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.5)
                element.click()
                return True
            except ElementClickInterceptedException:
                try:
                    element = self.driver.find_element(by, selector)
                    self.driver.execute_script("arguments[0].click();", element)
                    return True
                except: pass
            except: pass
            time.sleep(1)
        return False

    def safe_type(self, selector, text, by=By.CSS_SELECTOR, timeout=10):
        try:
            element = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, selector)))
            try:
                element.click()
                element.clear()
            except: pass
            try:
                element.send_keys(text)
            except:
                self.driver.execute_script("arguments[0].value = arguments[1];", element, text)
            return True
        except: return False

    def human_scroll(self):
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            current_position = 0
            while current_position < total_height:
                scroll_step = random.randint(300, 700)
                current_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                time.sleep(random.uniform(0.1, 0.4))
            time.sleep(0.5)
            self.driver.execute_script("window.scrollTo(0, 0);")
        except: pass

    def parse_thai_date_exact(self, date_str):
        if not date_str: return None
        thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
        try:
            date_str = date_str.strip()
            parts = date_str.split() 
            if len(parts) < 3: return None
            day = int(parts[0])
            month = thai_months.get(parts[1])
            year_be = int(parts[2])
            year_ad = year_be - 543
            return datetime.date(year_ad, month, day)
        except: return None

    def calculate_duration_text(self, date_range_str):
        if not date_range_str: return ""
        thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
        try:
            clean_str = " ".join(date_range_str.split())
            if '-' not in clean_str: return ""
            start_str, end_str = clean_str.split('-')
            def parse_thai_date(d_str):
                d_str = d_str.strip()
                if "ปัจจุบัน" in d_str: return datetime.datetime.now()
                parts = d_str.split()
                if len(parts) < 2: return None
                m = thai_months.get(parts[0])
                if not m: return None
                y = int(parts[1]) - 543
                return datetime.datetime(y, m, 1)
            s_date = parse_thai_date(start_str)
            e_date = parse_thai_date(end_str)
            if s_date and e_date:
                diff = relativedelta(e_date, s_date)
                txt = []
                if diff.years > 0: txt.append(f"{diff.years} ปี")
                if diff.months > 0: txt.append(f"{diff.months} เดือน")
                return " ".join(txt) if txt else "น้อยกว่า 1 เดือน"
            return ""
        except: return ""

    # ==============================================================================
    # 🔥 STEP 1: LOGIN (Dynamic URL Handling)
    # ==============================================================================
    # ==============================================================================
    # 🔥 STEP 1: LOGIN (URL Reconstruction Mode - สร้าง URL ใหม่เอง)
    # ==============================================================================
    def step1_login(self):
        # 1. 🛑 FIX สำคัญ: บังคับขนาดจอและ User-Agent เพื่อแก้หน้าเว็บเพี้ยน
        # 1. เทคนิคแก้จอเพี้ยนบน Linux Headless (ใช้ CDP Command โดยตรง)
        try:
            self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                'width': 1920, 'height': 1080, 'deviceScaleFactor': 1, 'mobile': False
            })
        except: pass

        MAX_RETRIES = 2
        
        for attempt in range(1, MAX_RETRIES + 1):
            # แสดง Header ว่าเป็นรอบที่เท่าไหร่
            console.rule(f"[bold cyan]🔐 Login Process (Attempt {attempt}/{MAX_RETRIES}) - Company Mode[/]")
            
            # 1. เริ่มจากลิงก์ฝั่งบริษัท (Employer) 
            entry_point = "https://www.jobthai.com/login?page=companies&l=th"
            
            # ฟังก์ชันกำจัดสิ่งกีดขวาง (ประกาศไว้บนสุด)
            def kill_blockers():
                try:
                    self.driver.execute_script("document.querySelectorAll('#close-button, .cookie-consent, [class*=\"pdpa\"], [class*=\"popup\"], .modal-backdrop').forEach(b => b.remove());")
                except: pass

            try:
                # ==============================================================================
                # 2️⃣ STEP 2: เข้าหน้าเว็บ -> ดึงค่าทีละตัว -> ประกอบ URL ใหม่ (Company Version)
                # ==============================================================================
                console.print(f"   2️⃣  เริ่มเข้าสู่ระบบจาก: [yellow]{entry_point}[/]", style="dim")
                self.driver.get(entry_point)
                
                console.print("      ⏳ รอเข้าสู่หน้า Auth...", style="dim")
                WebDriverWait(self.driver, 20).until(EC.url_contains("auth.jobthai.com"))

                console.print("      🔧 กำลังแยกชิ้นส่วน URL และประกอบร่างเป็น 'Company Login'...", style="dim")
                
                reconstructed_url = ""
                
                for i in range(10): # ให้เวลา 10 วินาที
                    try:
                        # 1. ใช้ JS ดึงค่า Parameter ทีละตัว
                        params = self.driver.execute_script("""
                            const urlParams = new URLSearchParams(window.location.search);
                            return {
                                client_id: urlParams.get('client_id'),
                                redirect_uri: urlParams.get('redirect_uri'),
                                state: urlParams.get('state'),
                                scope: urlParams.get('scope'),
                                l: urlParams.get('l'),
                                response_type: urlParams.get('response_type')
                            };
                        """)
                        
                        # 2. เช็คว่าได้ค่าสำคัญมาครบไหม
                        if params['client_id'] and params['redirect_uri']:
                            console.print(f"      ✅ ได้ค่า Client ID: {params['client_id'][:10]}...", style="green")
                            
                            # 3. ประกอบร่าง URL ใหม่ (เป้าหมายคือ Company Login)
                            base_url = "https://auth.jobthai.com/companies/login"
                            
                            # สร้าง Query String แบบ Manual
                            query_parts = [
                                f"client_id={params['client_id']}",
                                f"response_type={params.get('response_type', 'code')}", 
                                f"redirect_uri={params['redirect_uri']}",
                                f"scope={params.get('scope', 'login')}",
                                f"l={params.get('l', 'th')}",
                                f"state={params.get('state', '')}",
                                "type=company" # 🛑 Company Mode
                            ]
                            
                            # รวมร่างด้วย &
                            reconstructed_url = f"{base_url}?{'&'.join(query_parts)}"
                            
                            # ลบช่องว่างที่อาจจะเผลอติดมา
                            reconstructed_url = reconstructed_url.replace(" ", "").replace("\n", "").replace("\r", "")
                            
                            console.print(f"      ✨ สร้าง URL บริษัทสำเร็จ (Length: {len(reconstructed_url)})", style="bold cyan")
                            break
                    except Exception as e:
                        console.print(f"      ⚠️ กำลังพยายามดึงค่า... ({e})", style="dim")
                    
                    time.sleep(1)
                
                if not reconstructed_url:
                    raise Exception("ไม่สามารถดึงค่าพารามิเตอร์เพื่อสร้าง URL ได้")

                # 4. สั่งโหลดหน้าเว็บด้วย URL ใหม่
                console.print(f"      🔄 Reload ไปยังหน้า Login บริษัท...", style="bold cyan")
                self.driver.get(reconstructed_url)
                self.wait_for_page_load()
                time.sleep(5)
                console.print(f"      ✅ URL พร้อมใช้งาน (Company Login)", style="green")
                
                # ==============================================================================
                # 3️⃣ STEP 3: กดเลือก "หาคน" (Employer Tab) -> (เก็บ Code เดิมที่ Comment ไว้)
                # ==============================================================================
                '''console.print("   3️⃣  กำลังหาปุ่ม 'หาคน' (Employer Tab)...", style="dim")
                kill_blockers()
                
                # 1. รอให้ปุ่มปรากฏ (เหมือนเดิม)
                try:
                    WebDriverWait(self.driver, 30).until(
                        EC.visibility_of_element_located((By.XPATH, "//*[@id='login_tab_employer']"))
                    )
                except: 
                    console.print("      ⚠️ ไม่เห็นปุ่ม ID login_tab_employer (อาจโดนบัง หรือ Modal ไม่มา)", style="red")

                clicked_tab = False

                # --------------------------------------------------------------------------
                # 🖱️ ATTEMPT 1: ลองใช้เมาส์กดแบบคน (ActionChains)
                # --------------------------------------------------------------------------
                try:
                    # หาปุ่มด้วย ID หลักก่อน
                    mouse_btn = self.driver.find_element(By.XPATH, "//*[@id='login_tab_employer']")
                    if mouse_btn.is_displayed():
                        
                        # 🕵️ DEBUG BEFORE CLICK
                        console.print(f"      🕵️ [Before Click 1] URL: {self.driver.current_url} | Tabs: {len(self.driver.window_handles)}", style="magenta")

                        # ขยับเมาส์ไปหาแล้วคลิก
                        ActionChains(self.driver).move_to_element(mouse_btn).click().perform()
                        console.print("      ✅ กดปุ่ม 'หาคน' สำเร็จ (ด้วยเมาส์ ActionChains)", style="bold green")
                        
                        time.sleep(3) # รอผลลัพธ์

                        # 🕵️ DEBUG AFTER CLICK
                        console.print(f"      🕵️ [After Click 1] URL: {self.driver.current_url} | Tabs: {len(self.driver.window_handles)}", style="magenta")

                        clicked_tab = True
                except Exception as e:
                    console.print(f"      ⚠️ ใช้เมาส์กดไม่ติด ({e}) ... กำลังสลับไปใช้วิธีเดิม", style="dim")

                # --------------------------------------------------------------------------
                # 💉 ATTEMPT 2: วิธีเดิม (JS Script Loop)
                # --------------------------------------------------------------------------
                if not clicked_tab:
                    employer_selectors = [
                        (By.XPATH, "//*[@id='login_tab_employer']"),
                        (By.XPATH, "//span[contains(text(), 'หาคน')]"),
                        (By.CSS_SELECTOR, "div#login_tab_employer")
                    ]

                    for by, val in employer_selectors:
                        try:
                            elem = self.driver.find_element(by, val)
                            if elem.is_displayed():
                                # 🕵️ DEBUG BEFORE CLICK
                                console.print(f"      🕵️ [Before Click 2] URL: {self.driver.current_url}", style="magenta")
                                
                                self.driver.execute_script("arguments[0].click();", elem)
                                console.print(f"      ✅ กดปุ่ม 'หาคน' สำเร็จ (ด้วย Selector: {val})", style="bold green")
                                
                                time.sleep(3) # รอผลลัพธ์

                                # 🕵️ DEBUG AFTER CLICK
                                console.print(f"      🕵️ [After Click 2] URL: {self.driver.current_url} | Tabs: {len(self.driver.window_handles)}", style="magenta")

                                clicked_tab = True
                                break
                        except: continue
                
                if not clicked_tab:
                    raise Exception("หาปุ่ม 'หาคน' ไม่เจอ หรือกดไม่ได้")'''


                # ==============================================================================
                # 4️⃣ STEP 4: กรอกข้อมูล (Hybrid Mode + Retry Logic)
                # ==============================================================================
                console.print("   4️⃣  กำลังฝังข้อมูลเข้าระบบ (JS Injection)...", style="dim")
                
                # สคริปต์ JS สำหรับค้นหาและกรอกข้อมูล (หาทั้งหน้าหลักและ Iframe)
                # สคริปต์นี้จะคืนค่า 'success' ถ้ากรอกได้
                js_inject_script = f"""
                    function tryFill(doc) {{
                        let u = doc.querySelector("input[name='username']") || doc.querySelector("#login-form-username");
                        let p = doc.querySelector("input[name='password']") || doc.querySelector("#login-form-password");
                        let btn = doc.querySelector("#login_company") || doc.querySelector("button[type='submit']");
                        
                        if (u && p) {{
                            u.value = '{MY_USERNAME}';
                            u.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            u.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            
                            p.value = '{MY_PASSWORD}';
                            p.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            p.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            
                            if (btn) {{
                                setTimeout(() => btn.click(), 1000);
                                return 'clicked';
                            }}
                            
                            // ถ้าไม่มีปุ่ม ให้ลองกด Enter ที่รหัสผ่าน
                            let enterEvent = new KeyboardEvent('keydown', {{
                                key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                            }});
                            p.dispatchEvent(enterEvent);
                            return 'filled_enter';
                        }}
                        return 'not_found';
                    }}

                    // 1. ลองหน้าหลัก
                    let res = tryFill(document);
                    if (res !== 'not_found') return res;

                    // 2. ลองวนหาใน Iframe ทุกตัว
                    let frames = document.querySelectorAll("iframe");
                    for (let i = 0; i < frames.length; i++) {{
                        try {{
                            let doc = frames[i].contentDocument || frames[i].contentWindow.document;
                            if (doc) {{
                                let resFrame = tryFill(doc);
                                if (resFrame !== 'not_found') return 'iframe_' + resFrame;
                            }}
                        }} catch(e) {{}}
                    }}
                    return 'failed';
                """

                # รันสคริปต์ (ลองซ้ำ 3 รอบเผื่อเว็ปโหลดช้า)
                fill_status = 'failed'
                for i in range(3):
                    try:
                        fill_status = self.driver.execute_script(js_inject_script)
                        if fill_status != 'failed':
                            console.print(f"      ✅ JS ฝังข้อมูลสำเร็จ! (Status: {fill_status})", style="bold green")
                            break
                    except Exception as e:
                        console.print(f"      ⚠️ JS Error: {e}", style="dim")
                    time.sleep(3)

                if fill_status == 'failed':
                    console.print("      ❌ JS หาช่องไม่เจอ (หน้าเว็บอาจขาวสนิท)", style="red")
                    # ไม้ตายสุดท้าย: ถ้าหน้าขาว ให้ลอง Refresh แล้วทำใหม่ในรอบถัดไป
                    if attempt < MAX_RETRIES:
                        console.print("      🔄 หน้าขาว -> Refresh...", style="yellow")
                        self.driver.refresh()
                        time.sleep(5)
                        continue # วนลูปใหม่
                    else:
                        raise Exception("ไม่สามารถกรอกรหัสได้ (หน้าเว็บเพี้ยนถาวร)")
                        
                # ==============================================================================
                # 5️⃣ STEP 5: ตรวจสอบผลลัพธ์
                # ==============================================================================
                console.print("   5️⃣  ตรวจสอบผลลัพธ์...", style="dim")
                
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: "auth.jobthai.com" not in d.current_url and "login" not in d.current_url
                    )
                except: pass

                curr_url = self.driver.current_url.lower()
                
                is_auth_page = "auth.jobthai.com" in curr_url or "login" in curr_url
                is_success_page = "employer/dashboard" in curr_url or "findresume" in curr_url or ("resume" in curr_url and not is_auth_page)

                if is_success_page and not is_auth_page:
                    console.print(f"🎉 Login สำเร็จ! (URL: {curr_url})", style="bold green")
                    return True # ✅ จบ Loop และ Function ทันทีเมื่อสำเร็จ
                else:
                    error_msg = "หาสาเหตุไม่พบ"
                    try:
                        error_elem = self.driver.execute_script("""
                            return document.querySelector('.text-danger, .error-message, .alert-danger, .ant-form-item-explain-error')?.innerText;
                        """)
                        if error_elem: error_msg = error_elem.strip()
                    except: pass
                    
                    console.print(f"      ⚠️ ยังติดอยู่หน้า Login (URL: {curr_url})", style="bold red")
                    console.print(f"      💬 Alert: [white on red]{error_msg}[/]")
                    raise Exception(f"Login Failed - Stuck at {curr_url}")

            except Exception as e:
                console.print(f"\n[bold red]❌ ขั้นตอนล้มเหลวในรอบที่ {attempt}![/]")
                console.print(f"   สาเหตุ: {e}")
                
                # เช็คว่าควรวนรอบต่อไปไหม
                if attempt < MAX_RETRIES:
                     console.print("   🔄 กำลังเริ่ม Step 1 ใหม่ใน 5 วินาที...", style="bold yellow")
                     self.driver.delete_all_cookies() 
                     time.sleep(5)
                     continue # วนลูปใหม่
                else:
                    timestamp = datetime.datetime.now().strftime("%H%M%S")
                    err_img = f"error_step1_{timestamp}.png"
                    self.driver.save_screenshot(err_img)
                    console.print(f"   📸 ดูภาพหลักฐานได้ที่: [yellow]{err_img}[/]\n")

                    console.print("🚫 หมดความพยายาม -> ใช้ Cookie สำรอง", style="bold red")
                    return self.login_with_cookie()
        
    def login_with_cookie(self):
        cookies_env = os.getenv("COOKIES_JSON")
        if not cookies_env: 
            console.print("❌ ไม่พบ COOKIES_JSON", style="error")
            return False
            
        try:
            console.print("🍪 กำลังโหลด Cookie...", style="info")
            
            # 1. เข้าหน้าเว็บเปล่าๆ ของ Domain นั้นก่อน (สำคัญมาก เพื่อให้ Domain scope ตรงกัน)
            self.driver.get("https://www.jobthai.com/th/employer")
            self.random_sleep(2, 3)
            
            # 2. ลบ Cookie เดิมที่ติดมากับ Session ใหม่ทิ้งให้หมด
            self.driver.delete_all_cookies()
            
            # 3. แปลงและยัด Cookie
            cookies_list = json.loads(cookies_env)
            for cookie in cookies_list:
                # คัดเฉพาะ Key ที่ Selenium รองรับ (ถ้าเอา key แปลกๆ ไปด้วย จะ Error)
                cookie_dict = {
                    'name': cookie.get('name'),
                    'value': cookie.get('value'),
                    'domain': cookie.get('domain'), # สำคัญ: ต้องตรงกับเว็บที่เปิด
                    'path': cookie.get('path', '/'),
                    # 'secure': cookie.get('secure', False), # บางทีใส่ Secure แล้วพัง ถ้าเว็บไม่ strict ให้ comment ออก
                    # 'expiry': cookie.get('expirationDate') # ไม่ต้องใส่ expiry ก็ได้ ถ้าอยากให้เป็น Session Cookie
                }
                
                # Fix Domain: บางที Cookie มาเป็น .jobthai.com แต่เราเข้า www.jobthai.com
                # ให้ตัดจุดข้างหน้าออกเพื่อความชัวร์
                if 'jobthai' in str(cookie_dict['domain']):
                    try:
                        self.driver.add_cookie(cookie_dict)
                    except Exception as e:
                        # ถ้า add ไม่เข้า ข้ามไป (บางอันเป็น 3rd party cookie)
                        pass
            
            console.print("   ✅ ยัด Cookie เสร็จแล้ว -> Refresh หน้าจอ", style="dim")
            
            # 4. Refresh เพื่อให้ Cookie ทำงาน
            self.driver.refresh()
            self.wait_for_page_load()
            self.random_sleep(3, 5)

            # 5. เช็คว่าเข้าได้จริงไหม
            if "login" not in self.driver.current_url and "dashboard" in self.driver.current_url:
                console.print("🎉 Bypass Login สำเร็จด้วย Cookie!", style="success")
                return True
            else:
                # ลองไปหน้า Resume โดยตรงอีกทีเพื่อความชัวร์
                self.driver.get("https://www3.jobthai.com/findresume/findresume.php?l=th")
                self.random_sleep(2, 3)
                if "login" not in self.driver.current_url:
                     console.print("🎉 Bypass Login สำเร็จ! (Check Step 2)", style="success")
                     return True

        except Exception as e:
            console.print(f"❌ Cookie Error: {e}", style="error")
        
        return False

    def step2_search(self, keyword):
        # URL หน้าค้นหา Resume (ระบบเดิม www3)
        search_url = "https://www3.jobthai.com/findresume/findresume.php?l=th"
        console.rule(f"[bold cyan]2️⃣  ขั้นตอนค้นหา: '{keyword}'[/]")
        
        try:
            # 1. เช็คว่าอยู่หน้าค้นหาหรือยัง? ถ้ายัง ให้ Force Navigate
            current_url = self.driver.current_url
            if "findresume.php" not in current_url:
                console.print(f"   🔗 ไม่อยู่หน้าค้นหา (อยู่ที่: {current_url}) -> กำลัง Force Redirect...", style="yellow")
                self.driver.get(search_url)
                self.wait_for_page_load()
                self.random_sleep(3, 5)

            # 2. เช็คว่าโดนดีดกลับหน้า Login หรือไม่?
            if "login" in self.driver.current_url:
                raise Exception("Cookie หลุด/ไม่ครอบคลุม -> ระบบดีดกลับมาหน้า Login")

            # 3. เคลียร์ Popup
            try:
                self.driver.execute_script("document.querySelectorAll('#close-button,.cookie-consent,[class*=\"pdpa\"],.modal-backdrop,iframe').forEach(b=>b.remove());")
            except: pass

            # 4. รีเซ็ตปุ่มค้นหา (ถ้ามี)
            try:
                reset_btn = self.driver.find_element(By.XPATH, '//*[@id="company-search-resume"]')
                if reset_btn.is_displayed():
                    reset_btn.click()
                    time.sleep(2)
            except: pass

            # 5. หาช่องพิมพ์ (รอสูงสุด 20 วินาที)
            console.print("   ✍️ กำลังหาช่องพิมพ์...", style="dim")
            kw_element = WebDriverWait(self.driver, 20).until(
                EC.visibility_of_element_located((By.ID, "KeyWord"))
            )
            
            # 6. พิมพ์คำค้นหา
            kw_element.click()
            kw_element.clear()
            # ใช้ JS พิมพ์เพื่อความชัวร์
            self.driver.execute_script("arguments[0].value = arguments[1];", kw_element, keyword)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", kw_element)
            
            console.print(f"   ✅ พิมพ์ '{keyword}' เรียบร้อย", style="info")
            time.sleep(1)
            
            # 7. กดปุ่มค้นหา
            search_btn = self.driver.find_element(By.ID, "buttonsearch")
            self.driver.execute_script("arguments[0].click();", search_btn)
            console.print("   🔍 กดปุ่มค้นหาแล้ว รอผลลัพธ์...", style="dim")
            
            # 8. รอผลลัพธ์
            WebDriverWait(self.driver, 20).until(
                lambda d: "ResumeDetail" in d.page_source or "ไม่พบข้อมูล" in d.page_source or "No data found" in d.page_source
            )

            # 9. เช็คผลลัพธ์
            if "ไม่พบข้อมูล" in self.driver.page_source or "No data found" in self.driver.page_source:
                console.print(f"   ⚠️ ไม่พบข้อมูล (0 Results) สำหรับ: {keyword}", style="warning")
                return True

            console.print(f"   ✅ เจอผลการค้นหา!", style="success")
            return True

        except Exception as e:
            # =======================================================
            # 🚨 ERROR LOGGING SECTION (ส่วนที่เพิ่มใหม่)
            # =======================================================
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            err_img_name = f"error_search_{keyword}_{timestamp}.png"
            
            curr_url = self.driver.current_url
            curr_title = self.driver.title
            
            console.print(f"\n[bold red]❌ Search Error ({keyword})[/]")
            console.print(f"   📖 คำอธิบาย Error: {e}")
            console.print(f"   🔗 ลิงก์หน้าเว็บปัจจุบัน: {curr_url}")
            console.print(f"   👀 ชื่อหน้าเว็บ (Title): {curr_title}")
            
            # Save Screenshot
            self.driver.save_screenshot(err_img_name)
            console.print(f"   📸 บันทึกหลักฐานภาพถ่ายไว้ที่: [bold yellow]{err_img_name}[/]\n")
            
            return False

    def step3_collect_all_links(self):
        collected_links = []
        page_num = 1
        console.rule("[bold yellow]3️⃣  โหมดเก็บลิงก์[/]")
        
        while True:
            console.print(f"   📄 หน้าที่ {page_num}...", style="info")
            try:
                try: WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'ResumeDetail')]")))
                except: pass 
                
                all_anchors = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'ResumeDetail') or contains(@href, '/resume/')]")
                
                count_before = len(collected_links)
                for a in all_anchors:
                    try:
                        href = a.get_attribute("href")
                        if href and href not in collected_links:
                            collected_links.append(href)
                    except: continue
                
                new_count = len(collected_links) - count_before
                console.print(f"      -> เก็บเพิ่ม: {new_count} (รวม {len(collected_links)})", style="success")

            except Exception as e:
                console.print(f"      ❌ Error เก็บลิงก์: {e}", style="error")

            if len(collected_links) == 0: break
            if new_count == 0: break

            try:
                next_btn_xpath = '//*[@id="content-l"]/div[2]/div[1]/table/tbody/tr/td[8]/a'
                next_btns = self.driver.find_elements(By.XPATH, next_btn_xpath)
                if next_btns and next_btns[0].is_displayed():
                    self.driver.execute_script("arguments[0].click();", next_btns[0])
                    page_num += 1
                    time.sleep(3)
                    self.wait_for_page_load()
                else: break
            except: break
            
        console.print(f"[bold green]📦 สรุปยอดรวม: {len(collected_links)} ลิงก์[/]")
        return collected_links

    def scrape_detail_from_json(self, url, keyword, progress_console=None):
        printer = progress_console if progress_console else console
        self.set_random_user_agent()
        
        max_retries = 3
        load_success = False
        for attempt in range(max_retries):
            try:
                self.driver.get(url)
                self.wait_for_page_load()
                load_success = True
                break 
            except: self.random_sleep(5, 10)

        if not load_success: return None, 999, None
        
        try: self.human_scroll() 
        except: pass
        self.random_sleep(2.0, 5.0)
        
        data = {'Link': url}
        try: full_text = self.driver.find_element(By.CSS_SELECTOR, "#mainTableTwoColumn").text
        except: full_text = ""
        
        def get_val(sel, xpath=False):
            try:
                elem = self.driver.find_element(By.XPATH, sel) if xpath else self.driver.find_element(By.CSS_SELECTOR, sel)
                return elem.text.strip()
            except: return ""

        edu_tables_xpath = '//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[7]/td[2]/table'
        try:
            edu_tables = self.driver.find_elements(By.XPATH, edu_tables_xpath)
            total_degrees = len(edu_tables)
        except: total_degrees = 0
        matched_uni = ""; matched_faculty = ""; matched_major = ""; is_qualified = False
        highest_degree_text = "-"; max_degree_score = -1
        degree_score_map = {"ปริญญาเอก": 3, "ดุษฎีบัณฑิต": 3, "Doctor": 3, "Ph.D": 3, "ปริญญาโท": 2, "มหาบัณฑิต": 2, "Master": 2, "ปริญญาตรี": 1, "บัณฑิต": 1, "Bachelor": 1}
        
        def check_fuzzy(scraped_text, target_list, threshold=85): 
            if not target_list: return True
            if not scraped_text: return False
            best_score = 0
            for target in target_list:
                score = fuzz.partial_ratio(target.lower(), scraped_text.lower())
                if score > best_score: best_score = score
            if best_score >= threshold: return True
            return False 

        debug_edu_list = []

        for i in range(1, total_degrees + 1):
            base_xpath = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[7]/td[2]/table[{i}]'
            curr_uni = get_val(f'{base_xpath}/tbody/tr[2]/td/div', True)
            if not curr_uni: curr_uni = get_val(f'{base_xpath}/tbody/tr[1]/td/div', True)
            
            curr_degree = get_val(f'{base_xpath}//td[contains(., "ระดับการศึกษา")]/following-sibling::td[1]', True)
            if not curr_degree: curr_degree = get_val(f'{base_xpath}/tbody/tr[1]/td', True)
            
            curr_faculty = get_val(f'{base_xpath}//td[contains(., "คณะ")]/following-sibling::td[1]', True)
            curr_major = get_val(f'{base_xpath}//td[contains(., "สาขา")]/following-sibling::td[1]', True)
            
            debug_edu_list.append(f"[{curr_degree}] {curr_uni} / {curr_faculty} / {curr_major}")

            score = 0
            for key, val in degree_score_map.items():
                if key in str(curr_degree): score = val; break
            if score > max_degree_score: max_degree_score = score; highest_degree_text = curr_degree
            elif score == max_degree_score and highest_degree_text == "-": highest_degree_text = curr_degree

            if not is_qualified:
                uni_pass = check_fuzzy(curr_uni, TARGET_UNIVERSITIES)
                fac_pass = check_fuzzy(curr_faculty, TARGET_FACULTIES)
                major_pass = check_fuzzy(curr_major, TARGET_MAJORS)
                if uni_pass and (fac_pass or major_pass):
                    is_qualified = True; matched_uni = curr_uni; matched_faculty = curr_faculty; matched_major = curr_major

        if not is_qualified:
            return None, 999, None
        
        data['ระดับการศึกษา'] = highest_degree_text; 
        data['มหาลัย'] = matched_uni; 
        data['คณะ'] = matched_faculty; 
        data['สาขา'] = matched_major
        data['รหัสใบสมัคร'] = get_val("#ResumeViewDiv [align='left'] span.white")

        try:
            img_element = self.driver.find_element(By.ID, "DefaultPictureResume2Column")
            app_id_clean = data['รหัสใบสมัคร'].strip() if data['รหัสใบสมัคร'] else f"unknown_{int(time.time())}"
            img_filename = f"{app_id_clean}.png"
            save_path = os.path.join(RESUME_IMAGE_FOLDER, img_filename)
            img_element.screenshot(save_path)
            data['รูปภาพ'] = save_path
        except: data['รูปภาพ'] = ""

        raw_update_date = get_val('//*[@id="ResumeViewDiv"]/table/tbody/tr[2]/td[3]/span[2]', xpath=True)
        
        def calculate_last_update(date_str):
            if not date_str: return "-"
            try:
                parts = date_str.split()
                if len(parts) < 3: return "-"
                day = int(parts[0])
                month_str = parts[1]
                year_be = int(parts[2])
                year_ad = year_be - 543
                thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
                month = thai_months.get(month_str, 1)
                update_dt = datetime.datetime(year_ad, month, day)
                diff = relativedelta(datetime.datetime.now(), update_dt)
                txt = []
                if diff.years > 0: txt.append(f"{diff.years}ปี")
                if diff.months > 0: txt.append(f"{diff.months}เดือน")
                if diff.days > 0: txt.append(f"{diff.days}วัน")
                if not txt: return "วันนี้"
                return " ".join(txt)
            except: return "-"
            
        data['อัพเดทล่าสุด'] = calculate_last_update(raw_update_date)

        data['ชื่อ'] = get_val("#mainTableTwoColumn td > span.head1")
        data['นามสกุล'] = get_val("span.black:nth-of-type(3)")
        age_match = re.search(r"อายุ\s*[:]?\s*(\d+)", full_text)
        data['อายุ'] = age_match.group(1) if age_match else ""
        data['เพศ'] = re.search(r"เพศ\s*[:]?\s*(ชาย|หญิง|Male|Female)", full_text).group(1) if re.search(r"เพศ\s*[:]?\s*(ชาย|หญิง|Male|Female)", full_text) else ""
        data['เบอร์โทร'] = get_val("#mainTableTwoColumn div:nth-of-type(6) span.black")
        data['Email'] = get_val("#mainTableTwoColumn a")
        data['ที่อยู่'] = get_val("#mainTableTwoColumn div:nth-of-type(1) span.head1")
        data['จังหวัดที่อยู่'] = get_val("#mainTableTwoColumn table [width][align='left'] div span.headNormal")
        
        pos1 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[2]', xpath=True)
        pos2 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[4]', xpath=True)
        pos3 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[6]', xpath=True)
        data['ตำแหน่งที่ต้องการสมัคร_1'] = pos1; 
        data['ตำแหน่งที่ต้องการสมัคร_2'] = pos2; 
        data['ตำแหน่งที่ต้องการสมัคร_3'] = pos3
        combined_positions = ", ".join([p for p in [pos1, pos2, pos3] if p])
        
        data['เงินเดือนที่ต้องการ'] = get_val("//td[contains(., 'เงินเดือนที่ต้องการ')]/following-sibling::td[1]", True)
        salary_min_txt = "-"
        salary_max_txt = "-"
        raw_salary = data.get('เงินเดือนที่ต้องการ', '')
        try:
            if raw_salary and 'ปิดข้อมูล' not in str(raw_salary):
                s = str(raw_salary).lower().replace(',', '')
                s = re.sub(r'(\d+(\.\d+)?)\s*k', lambda m: str(float(m.group(1)) * 1000), s)
                nums = re.findall(r'\d+(?:\.\d+)?', s)
                nums = [float(n) for n in nums]
                if nums:
                    mn, mx = nums[0], nums[0]
                    if len(nums) >= 2: mn, mx = nums[0], nums[1]
                    if mx > 1000 and mn < 1000 and mn > 0: mn *= 1000
                    salary_min_txt = f"{int(mn):,}"
                    salary_max_txt = f"{int(mx):,}"
        except: pass
        printer.print(f"🔥 เจอ: {highest_degree_text} | มหาลัย: {matched_uni} | อัพเดท: {data.get('อัพเดทล่าสุด')}", style="bold green")
        data['Salary_Min'] = salary_min_txt
        data['Salary_Max'] = salary_max_txt

        found_tier1_companies = set() 
        found_tier2_companies = set()
        found_client_companies = set() 
        all_work_history = [] 
        try:
            if "ประวัติการทำงาน/ฝึกงาน" in full_text:
                history_text = full_text.split("ประวัติการทำงาน/ฝึกงาน")[1].split("ความสามารถ")[0]
            else: history_text = ""
            thai_months_str = "มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม"
            raw_chunks = re.split(f"({thai_months_str})\\s+\\d{{4}}\\s+-\\s+", history_text)
            jobs = []
            if len(raw_chunks) > 1:
                for k in range(1, len(raw_chunks), 2):
                    if k+1 < len(raw_chunks): jobs.append(raw_chunks[k] + raw_chunks[k+1]) 
            
            i = 0
             
            while True:
                check_xpath = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]'
                try:
                    if len(self.driver.find_elements(By.XPATH, check_xpath)) == 0: break
                except: break

                suffix = f"_{i+1}"
                xpath_level = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]/tbody/tr[7]/td[2]/span'
                data[f'ระดับหน้าที่รับผิดชอบ{suffix}'] = get_val(xpath_level, xpath=True)
                xpath_duration = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]/tbody/tr[2]/td/div'
                duration_str = get_val(xpath_duration, xpath=True)
                data[f'ระยะเวลาที่ทำงาน{suffix}'] = duration_str
                data[f'รวมอายุงาน{suffix}'] = self.calculate_duration_text(duration_str)

                xpath_duties_1 = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]/tbody/tr[8]/td/div/span'
                duties_val = get_val(xpath_duties_1, xpath=True)
                data[f'หน้าที่รับผิดชอบ{suffix}'] = duties_val

                comp_xpath_specific = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]/tbody/tr[3]/td/div/span'
                company = get_val(comp_xpath_specific, xpath=True)
                if not company:
                    company_xpath_2 = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]/tbody/tr[3]/td'
                    company = get_val(company_xpath_2, xpath=True)
                
                position = ""; salary = ""
                if i < len(jobs):
                    block = jobs[i]
                    if not company:
                        comp_match = re.search(r"^.*(บริษัท|Ltd|Inc|Group|Organization|หจก|Limited).*$", block, re.MULTILINE | re.IGNORECASE)
                        company = comp_match.group(0).strip() if comp_match else ""
                        if not company:
                             lines = [l.strip() for l in block.split('\n') if l.strip()]
                             if len(lines) > 1: company = lines[1]
                    pos_match = re.search(r"ตำแหน่ง\s+(.*)", block)
                    sal_match = re.search(r"เงินเดือน\s+(.*)", block)
                    position = pos_match.group(1).strip() if pos_match else ""
                    salary = sal_match.group(1).strip() if sal_match else ""

                data[f'ชื่อบริษัทที่เคยทำงาน{suffix}'] = company
                data[f'ตำแหน่งที่เคยเป็น{suffix}'] = position
                data[f'เงินเดือนที่เคยได้{suffix}'] = salary

                if company:
                    clean_name = company.strip()
                    if clean_name and clean_name not in all_work_history:
                        all_work_history.append(clean_name)

                if company:
                    for key, keywords in CLIENTS_TARGETS.items():
                        for kw in keywords:
                            if fuzz.token_set_ratio(kw.lower(), company.lower()) >= 95:
                                found_client_companies.add(key)
                                break
                    for key, keywords in TIER1_TARGETS.items():
                        for kw in keywords:
                            if fuzz.token_set_ratio(kw.lower(), company.lower()) >= 95:
                                found_tier1_companies.add(key)
                                break
                    if TARGET_COMPETITORS_TIER2:
                        for competitor in TARGET_COMPETITORS_TIER2:
                            if fuzz.token_set_ratio(competitor.lower(), company.lower()) >= 95: 
                                found_tier2_companies.add(competitor)
                                break
                i += 1
        except: pass
        
        competitor_str = ", ".join(all_work_history)
        data['เคยทำบริษัทคู่แข่ง'] = competitor_str

        today_date = datetime.date.today()
        update_date = self.parse_thai_date_exact(raw_update_date)
        days_diff = 999
        if update_date: days_diff = (today_date - update_date).days

        app_id = data.get('รหัสใบสมัคร', '').strip()
        full_name = f"{data.get('ชื่อ', '')} {data.get('นามสกุล', '')}"
        
        person_data = {
            "keyword": keyword, 
            "company": competitor_str,
            "degree": highest_degree_text,
            "salary_min": salary_min_txt,
            "salary_max": salary_max_txt,
            "id": app_id,
            "name": full_name,
            "age": data.get('อายุ', '-'),
            "positions": combined_positions, 
            "last_update": data['อัพเดทล่าสุด'],
            "link": url,
            "image_path": data.get('รูปภาพ', '')
        }

        printer.print(f"   🔥 เจอ: {highest_degree_text} | มหาลัย: {matched_uni} | วันที่: {days_diff} วันก่อน", style="bold green")
        return data, days_diff, person_data

    # --- NEW FUNCTION: Clean & Process Data with Pandas ---
    def clean_final_data_with_pandas(self):
        """
        ฟังก์ชันนี้จะดึง self.all_scraped_data มาทำความสะอาดครั้งใหญ่ด้วย Pandas
        และคืนค่ากลับไปเป็น List of List (พร้อม Header) เพื่อเตรียมลง Google Sheets
        """
        if not self.all_scraped_data:
            return None

        # แปลง List of Dicts เป็น DataFrame
        df = pd.DataFrame(self.all_scraped_data)
        
        # --- CLEANING FUNCTIONS (Inner Functions) ---
        def clean_salary_split(val):
            if pd.isna(val) or str(val).strip() == '' or 'ปิดข้อมูล' in str(val): return None, None
            s = str(val).lower().replace(',', '')
            def repl(m):
                try: return str(float(m.group(1)) * 1000)
                except: return m.group(0)
            s = re.sub(r'(\d+(\.\d+)?)\s*k', repl, s)
            nums = re.findall(r'\d+(?:\.\d+)?', s)
            nums = [float(n) for n in nums]
            if not nums: return None, None
            mn, mx = nums[0], nums[0]
            if len(nums) >= 2: mn, mx = nums[0], nums[1]
            if mx > 1000 and mn < 1000 and mn > 0:
                if mx / mn > 100: mn *= 1000
            return int(mn), int(mx)

        def clean_salary_single(val):
            mn, mx = clean_salary_split(val)
            if mn is None: return ""
            if mn != mx: return int((mn + mx) / 2)
            return int(mn)

        def clean_location(val):
            if pd.isna(val) or 'ปิดข้อมูล' in str(val): return '', ''
            s = str(val).strip()
            m = re.search(r'(\d{5})$', s)
            if m:
                zipc = m.group(1)
                prov = s.replace(zipc, '').strip()
                return prov, zipc
            return s, ''

        def clean_address_split(val):
            if pd.isna(val) or 'ปิดข้อมูล' in str(val): return None, None
            val = str(val).replace('จ.', 'จังหวัด').replace('อ.', 'อำเภอ').replace('ต.', 'ตำบล')
            sub_district = None; district = None
            m_sub = re.search(r'(แขวง|ตำบล)\s*([ก-๙]+)', val)
            if m_sub: sub_district = m_sub.group(2)
            m_dist = re.search(r'(เขต|อำเภอ)\s*([ก-๙]+)', val)
            if m_dist: district = m_dist.group(2)
            return district, sub_district

        def clean_phone(val):
            if pd.isna(val) or 'Click' in str(val): return ''
            clean_number = re.sub(r'\D', '', str(val))
            if clean_number: return f"'{clean_number}" 
            return ''
        
        def clean_email(val):
            if pd.isna(val) or 'Click' in str(val): return ''
            return str(val).strip()

        def clean_company_name(val):
            if pd.isna(val): return ""
            s = str(val).strip()
            # ลบ space ระหว่างตัวอักษรไทย (เช่น "บ ริ ษั ท")
            s = re.sub(r'(?<=[\u0E00-\u0E7F])\s+(?=[\u0E00-\u0E7F])', '', s)
            return s

        # --- APPLY CLEANING ---
        if 'เงินเดือนที่ต้องการ' in df.columns:
            salary_split = df['เงินเดือนที่ต้องการ'].apply(lambda x: pd.Series(clean_salary_split(x)))
            df['เงินเดือนที่ต้องการ_Min'] = salary_split[0]
            df['เงินเดือนที่ต้องการ_Max'] = salary_split[1]

        history_salary_cols = [c for c in df.columns if 'เงินเดือนที่เคยได้' in c]
        for c in history_salary_cols:
            df[c] = df[c].apply(clean_salary_single)

        if 'จังหวัดที่อยู่' in df.columns:
            loc_split = df['จังหวัดที่อยู่'].apply(lambda x: pd.Series(clean_location(x)))
            df['จังหวัดที่อยู่'] = loc_split[0]
            df['รหัสไปรษณีย์'] = loc_split[1]

        if 'ที่อยู่' in df.columns:
            addr_split = df['ที่อยู่'].apply(lambda x: pd.Series(clean_address_split(x)))
            df['เขต'] = addr_split[0]
            df['แขวง'] = addr_split[1]

        if 'เบอร์โทร' in df.columns: df['เบอร์โทร'] = df['เบอร์โทร'].apply(clean_phone)
        if 'Email' in df.columns: df['Email'] = df['Email'].apply(clean_email)

        company_cols = [c for c in df.columns if 'ชื่อบริษัทที่เคยทำงาน' in c]
        for c in company_cols:
            df[c] = df[c].apply(clean_company_name)

        # --- REORDER COLUMNS ---
        base_columns = [
            "Link", "Keyword", "รหัสใบสมัคร", "เคยทำบริษัทคู่แข่ง", "รูปภาพ", 
            "อัพเดทล่าสุด", "Resume_PDF_Link",
            "ชื่อ", "นามสกุล", "อายุ", "เพศ", 
            "เบอร์โทร", "Email", "ที่อยู่", "แขวง", "เขต", "จังหวัดที่อยู่", "รหัสไปรษณีย์",
            "ตำแหน่งที่ต้องการสมัคร_1","ตำแหน่งที่ต้องการสมัคร_2","ตำแหน่งที่ต้องการสมัคร_3", 
            "เงินเดือนที่ต้องการ", "เงินเดือนที่ต้องการ_Min", "เงินเดือนที่ต้องการ_Max", 
            "ระดับการศึกษา", "มหาลัย", "คณะ", "สาขา"
        ]
        
        cols_to_keep = [c for c in base_columns if c in df.columns]
        other_cols = [c for c in df.columns if c not in base_columns]
        work_cols = []
        for col in other_cols:
            if any(k in col for k in ["ชื่อบริษัทที่เคยทำงาน", "ตำแหน่งที่เคยเป็น", "เงินเดือนที่เคยได้", "ระดับหน้าที่รับผิดชอบ", "ระยะเวลาที่ทำงาน", "หน้าที่รับผิดชอบ", "รวมอายุงาน"]):
                work_cols.append(col)
        
        # เรียง work_cols ตามเลขท้าย (เช่น _1, _2, _3)
        work_cols.sort(key=lambda x: int(re.search(r'_(\d+)$', x).group(1)) if re.search(r'_(\d+)$', x) else 0)
        
        final_cols = cols_to_keep + work_cols + ["ประสบการณ์ทำงานรวมทั้งหมด", "Analyzed_Department", "Analyzed_Score", "Analyzed_Breakdown"]
        final_cols = [c for c in final_cols if c in df.columns]
        
        df = df[final_cols]
        
        # --- PREPARE FOR GOOGLE SHEETS ---
        # 1. แทนค่า NaN ด้วย "" (เพื่อให้ Sheets ไม่ Error)
        df = df.fillna("")
        
        # 2. แปลงเป็น List of Lists [ [Header], [Row1], [Row2], ... ]
        data_for_sheets = [df.columns.values.tolist()] + df.values.tolist()
        
        return data_for_sheets

    def send_single_email(self, subject_prefix, people_list, col_header="ประวัติบริษัท"):
        sender = os.getenv("EMAIL_SENDER")
        password = os.getenv("EMAIL_PASSWORD")
        receiver_list = []
        
        # จัดการรายชื่อผู้รับ
        if MANUAL_EMAIL_RECEIVERS and len(MANUAL_EMAIL_RECEIVERS) > 0: 
            receiver_list = MANUAL_EMAIL_RECEIVERS
        else:
             rec_env = os.getenv("EMAIL_RECEIVER")
             if rec_env: receiver_list = [rec_env]
        
        if not sender or not password or not receiver_list: return

        # ตั้งชื่อหัวข้ออีเมล
        if "สรุป" in subject_prefix or "HOT" in subject_prefix: 
            subject = subject_prefix
        elif len(people_list) > 1: 
            subject = f"🔥 {subject_prefix} ({len(people_list)} คน)"
        else: 
            subject = subject_prefix 

        # 🟢 จุดที่แก้ไข: เปลี่ยนมาเช็คประวัติจาก current_history_data (จาก Google Sheet)
        footer_note = ""
        if len(people_list) == 1:
            person_id = str(people_list[0]['id'])
            
            # เช็คในความจำของ Keyword ปัจจุบัน
            if person_id in self.current_history_data:
                try:
                    # แปลงวันที่จาก YYYY-MM-DD เป็น D/M/Y
                    raw_date = str(self.current_history_data[person_id])
                    y, m, d = raw_date.split('-')
                    footer_note = f"ℹ️ เคยพบคนนี้ล่าสุดเมื่อ: {d}/{m}/{y}"
                except:
                    footer_note = f"ℹ️ เคยพบคนนี้ล่าสุดเมื่อ: {self.current_history_data[person_id]}"
            else:
                footer_note = "✨ ผู้สมัครรายใหม่ (ไม่เคยพบในระบบ)"
        
        elif len(people_list) > 1:
            footer_note = "📦 อีเมลสรุปรายสัปดาห์ (แสดงสถานะประวัติเฉพาะอีเมลแจ้งเตือนรายบุคคล)"

        # --- HTML & CSS Construction ---
        body_html = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-size: 14px; font-family: 'Sarabun', sans-serif; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f2f2f2; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .btn {{
                background-color: #28a745; color: #ffffff !important; padding: 5px 10px;
                text-align: center; text-decoration: none; display: inline-block;
                border-radius: 4px; font-size: 12px; font-weight: bold;
            }}
            .highlight {{ color: #d9534f; font-weight: bold; }} /* สีแดงสำหรับบริษัทเป้าหมาย */
            .footer-text {{ 
                margin-top: 15px; 
                color: #555; 
                font-size: 14px; 
                font-weight: bold; 
                border-top: 1px solid #eee; 
                padding-top: 10px; 
            }}
        </style>
        </head>
        <body>
            <h3>{subject}</h3>
            <table>
                <tr>
                    <th style="width: 8%;">รูปภาพ</th>
                    <th style="width: 22%;">{col_header}</th> 
                    <th style="width: 10%;">ระดับการศึกษา</th>
                    <th style="width: 10%;">รหัสใบสมัคร</th>
                    <th style="width: 15%;">ชื่อ-นามสกุล</th>
                    <th style="width: 5%;">อายุ</th>
                    <th style="width: 15%;">ตำแหน่งที่สมัคร</th>
                    <th style="width: 8%;">เงินเดือนต่ำสุด</th>
                    <th style="width: 8%;">เงินเดือนสูงสุด</th> 
                    <th style="width: 10%;">อัพเดทล่าสุด</th>
                    <th style="width: 7%;">ลิงก์</th>
                </tr>
        """
        
        images_to_attach = []
        
        for person in people_list:
            # จัดการรูปภาพ (CID Embed)
            cid_id = f"img_{person['id']}"
            if person['image_path'] and os.path.exists(person['image_path']):
                img_html = f'<img src="cid:{cid_id}" width="70" style="border-radius: 5px;">'
                images_to_attach.append({'cid': cid_id, 'path': person['image_path']})
            else:
                img_html = '<span style="color:gray; font-size:12px;">No Image</span>'

            # จัดการ Highlight ชื่อบริษัท (Tier 1 / Client / Tier 2)
            raw_companies = person['company']
            final_company_html = "-"
            
            if raw_companies and raw_companies != "-":
                comp_list = raw_companies.split(", ")
                formatted_list = []
                
                for comp in comp_list:
                    is_target = False
                    comp_clean = comp.strip()
                    
                    # 1. เช็ค Tier 1
                    for key, keywords in TIER1_TARGETS.items():
                        for kw in keywords:
                            if fuzz.token_set_ratio(kw.lower(), comp_clean.lower()) >= 85:
                                is_target = True; break
                        if is_target: break
                    
                    # 2. เช็ค Clients
                    if not is_target:
                        for key, keywords in CLIENTS_TARGETS.items():
                            for kw in keywords:
                                if fuzz.token_set_ratio(kw.lower(), comp_clean.lower()) >= 85:
                                    is_target = True; break
                            if is_target: break
                            
                    # 3. เช็ค Tier 2
                    if not is_target and TARGET_COMPETITORS_TIER2:
                        for kw in TARGET_COMPETITORS_TIER2:
                            if fuzz.token_set_ratio(kw.lower(), comp_clean.lower()) >= 85:
                                is_target = True; break

                    if is_target:
                        formatted_list.append(f"<span class='highlight'>{comp_clean}</span>")
                    else:
                        formatted_list.append(comp_clean)
                
                final_company_html = "<br>".join(formatted_list)

            # 🟢 ส่วนที่แก้ไขใหม่: ดึงค่าเงินเดือนแยกตัวแปร
            s_min = person.get('salary_min', '-')
            s_max = person.get('salary_max', '-')

            # 🟢 [เพิ่มส่วนนี้] สร้างปุ่ม PDF (ถ้ามีลิงก์)
            # [แก้ไขส่วนนี้] สร้างปุ่ม PDF สไตล์โมเดิร์น
            pdf_btn_html = ""
            if person.get('Resume_PDF_Link'):
                pdf_btn_html = f'''<br><br>
                <a href="{person['Resume_PDF_Link']}" target="_blank" 
                   style="background-color: #e74c3c; color: #ffffff; padding: 8px 15px; border-radius: 30px; text-decoration: none; font-size: 13px; font-weight: bold; display: inline-block; border: 1px solid #c0392b; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                   📄 ดูไฟล์ PDF
                </a>'''

            # สร้างแถวในตาราง (เพิ่ม {pdf_btn_html} ลงไป)
            body_html += f"""
                <tr>
                    <td style="text-align: center;">{img_html}</td>
                    <td style="font-size: 13px; line-height: 1.6;">{final_company_html}</td>
                    <td>{person.get('degree', '-')}</td> 
                    <td>{person['id']}</td>
                    <td>{person['name']}</td>
                    <td>{person['age']}</td>
                    <td>{person['positions']}</td>
                    <td>{s_min}</td> 
                    <td>{s_max}</td>
                    <td>{person['last_update']}</td>
                    <td style="text-align: center;">
                        <a href="{person['link']}" target="_blank" class="btn">เปิดดู</a>
                        {pdf_btn_html} 
                    </td>
                </tr>
            """
            
        # 🟢 อย่าลืมแปะ footer_note ลงใน body_html
        body_html += f"</table><div class='footer-text'>{footer_note}</div></body></html>"

        # ส่งอีเมล
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender, password)
            
            msg_root = MIMEMultipart('related')
            msg_root['From'] = sender
            msg_root['Subject'] = subject
            
            msg_alternative = MIMEMultipart('alternative')
            msg_root.attach(msg_alternative)
            msg_alternative.attach(MIMEText(body_html, 'html'))
            
            # แนบรูปภาพ
            # -----------------------------------------------------
            # 🔴 ตัวการที่ทำให้มีไฟล์แนบโผล่มา (ปิดมันซะ!)
            # -----------------------------------------------------
            # for img_data in images_to_attach:
            #     try:
            #         with open(img_data['path'], 'rb') as f:
            #             msg_img = MIMEImage(f.read())  <-- นี่คือคำสั่งสร้างไฟล์แนบ
            #             msg_img.add_header('Content-ID', f"<{img_data['cid']}>")
            #             msg_img.add_header('Content-Disposition', 'inline', filename=os.path.basename(img_data['path']))
            #             msg_root.attach(msg_img)       <-- นี่คือคำสั่งยัดไฟล์ใส่อีเมล
            #     except: pass

            # วนลูปส่งให้ผู้รับทุกคน
            for rec in receiver_list:
                if 'To' in msg_root: del msg_root['To']
                msg_root['To'] = rec
                server.send_message(msg_root)
                console.print(f"   ✅ ส่งเมล '{subject}' -> {rec}", style="success")
            server.quit()
        except Exception as e:
            console.print(f"❌ ส่งอีเมลล้มเหลว: {e}", style="error")

    def send_batch_email(self, batch_candidates, keyword):
        self.send_single_email(f"สรุปผู้สมัครรายสัปดาห์: {keyword} ({len(batch_candidates)} คน)", batch_candidates)

    def save_to_google_sheets(self):
        console.rule("[bold green]📊 Google Sheets Update (Smart Header Check)[/]")
        
        # 1. เตรียมข้อมูลใหม่ที่ Clean แล้ว
        console.print("🧹 กำลังทำความสะอาดข้อมูลและจัดเรียงคอลัมน์...", style="cyan")
        final_data_list = self.clean_final_data_with_pandas()
        
        if not final_data_list:
            console.print("⚠️ ไม่มีข้อมูลใหม่จากการสแกนรอบนี้", style="yellow")
            return

        try:
            if not G_SHEET_KEY_JSON or not G_SHEET_NAME:
                console.print("❌ ไม่พบ Key หรือชื่อไฟล์ Google Sheet ใน Secrets", style="error")
                return

            creds_dict = json.loads(G_SHEET_KEY_JSON)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            
            sheet = client.open(G_SHEET_NAME)
            console.print(f"✅ เชื่อมต่อไฟล์ '{G_SHEET_NAME}' สำเร็จ", style="success")
            
            today_str = datetime.datetime.now().strftime("%d-%m-%Y")
            worksheet = None
            
            # 2. พยายามเข้าถึง Tab ของวันนี้
            try:
                worksheet = sheet.worksheet(today_str)
                console.print(f"ℹ️ พบ Tab '{today_str}' แล้ว", style="info")
            except:
                worksheet = sheet.add_worksheet(title=today_str, rows="100", cols="30")
                console.print(f"🆕 สร้าง Tab ใหม่: '{today_str}'", style="success")
            
            # 3. ดึงข้อมูลเก่า และ ตรวจสอบ Header (ส่วนที่แก้เพิ่ม)
            existing_data = worksheet.get_all_values()
            new_header = final_data_list[0] # Header ที่ถูกต้องจาก Code
            
            # เช็คว่า Sheet ว่าง หรือ บรรทัดแรกไม่ตรงกับ Header ใหม่หรือไม่?
            header_mismatch = False
            if not existing_data:
                header_mismatch = True
            elif len(existing_data) > 0:
                # เทียบ Header ปัจจุบัน กับ Header ใหม่ (เอาแค่ความยาวเท่าที่มี)
                current_header = existing_data[0]
                # ถ้า Header ใน Sheet สั้นกว่า หรือ ไม่ตรงกัน -> ถือว่าผิด
                if len(current_header) < len(new_header) or current_header[:len(new_header)] != new_header:
                    header_mismatch = True

            # ถ้า Header ไม่ตรง ให้เขียน Header ใหม่ทับบรรทัดที่ 1
            if header_mismatch:
                console.print("🔧 ตรวจพบว่า Header หายหรือไม่ตรงรุ่น -> กำลังเขียน Header ใหม่...", style="yellow")
                # update เฉพาะแถวที่ 1
                worksheet.update('A1', [new_header])
                # โหลดข้อมูล existing ใหม่ หลังแก้ Header แล้ว
                existing_data = worksheet.get_all_values()

            # --- เข้าสู่ Logic เดิม: การ Append ข้อมูล ---
            if not existing_data or len(existing_data) <= 1:
                # กรณีเพิ่งสร้าง Header เสร็จ หรือ Sheet โล่ง -> ใส่ข้อมูลใหม่เลย (ตัด Header ออกเพราะใส่ไปแล้วข้างบน)
                rows_to_add = final_data_list[1:]
                if rows_to_add:
                    worksheet.append_rows(rows_to_add)
                    console.print(f"✅ บันทึกข้อมูลตั้งต้น {len(rows_to_add)} รายการ", style="bold green")
            else:
                # กรณีมีข้อมูล Data อยู่แล้ว -> เช็คซ้ำก่อน Append
                id_index = 0
                try:
                    id_index = new_header.index("รหัสใบสมัคร")
                except ValueError: pass
                
                existing_ids = set()
                # existing_data[1:] คือข้าม Header
                for row in existing_data[1:]: 
                    if len(row) > id_index:
                        existing_ids.add(row[id_index])
                
                new_rows_to_add = []
                for row in final_data_list[1:]:
                    candidate_id = row[id_index]
                    if candidate_id not in existing_ids:
                        new_rows_to_add.append(row)
                        existing_ids.add(candidate_id)
                
                if new_rows_to_add:
                    worksheet.append_rows(new_rows_to_add)
                    console.print(f"✅ เพิ่มข้อมูลใหม่ {len(new_rows_to_add)} รายการ", style="bold green")
                else:
                    console.print("✨ ข้อมูลทั้งหมดมีอยู่ใน Sheet แล้ว (ไม่มีรายการใหม่)", style="yellow")
                
        except Exception as e:
            console.print(f"❌ Google Sheets Error: {e}", style="error")

    def run(self):
        self.email_report_list = []
        if not self.step1_login(): return

        # 🟢 1. โหลดความจำจาก Google Sheet ของวันนี้ก่อนเริ่มงาน
        self.load_daily_pdf_cache()
        
        today = datetime.date.today()
        is_friday = (today.weekday() == 4)
        is_manual_run = (os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch")
        
        console.print(f"📅 Status Check: Today is Friday? [{'Yes' if is_friday else 'No'}] | Manual Run? [{'Yes' if is_manual_run else 'No'}]", style="bold yellow")
        
        for index, keyword in enumerate(SEARCH_KEYWORDS):
            # 🟢 [เพิ่ม] 1. เตรียมหน้าประวัติ (Tab) ตามกลุ่มของ Keyword ก่อนเริ่มค้นหา
            self.prepare_history_for_keyword(keyword)

            console.rule(f"[bold magenta]🔍 เริ่มดำเนินการคำค้นที่ {index+1}/{len(SEARCH_KEYWORDS)}: {keyword}[/]")
            
            current_keyword_batch = []
            if self.step2_search(keyword):
                links = self.step3_collect_all_links()
                if links:
                    console.print(f"\n🚀 เริ่มดูดข้อมูลสำหรับ '{keyword}' จำนวน {len(links)} รายการ ...")
                    with Progress(
                        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                        BarColumn(), TaskProgressColumn(), TimeElapsedColumn(), TimeRemainingColumn(),
                        console=console
                    ) as progress:
                        task_id = progress.add_task(f"[cyan]Processing {keyword}...", total=len(links))
                        
                        for i, link in enumerate(links):
                            if self.total_profiles_viewed > 0 and self.total_profiles_viewed % 33 == 0:
                                progress.console.print(f"[yellow]☕ ครบ {self.total_profiles_viewed} คนแล้ว... พักเบรก 4 นาที[/]")
                                time.sleep(240)

                            try:
                                d, days_diff, person_data = self.scrape_detail_from_json(link, keyword, progress_console=progress.console)
                                self.total_profiles_viewed += 1 
                                
                                if d is not None:
                                    d['Keyword'] = keyword
                                    self.all_scraped_data.append(d)

                                    # ==========================================
                                    # 🟢 LOGIC ใหม่: ผูก PDF กับการส่งเมล
                                    # ==========================================
                                    
                                    # 1. คำนวณเงื่อนไข HOT (0-1 วัน)
                                    should_send_hot = False
                                    if days_diff <= 1:
                                        should_send_hot = True
                                        # เช็คประวัติ 1 วัน
                                        if EMAIL_USE_HISTORY and person_data['id'] in self.current_history_data:
                                            try:
                                                last_notify = datetime.datetime.strptime(self.current_history_data[person_data['id']], "%Y-%m-%d").date()
                                                if (today - last_notify).days < 1: should_send_hot = Ture 
                                            except: pass

                                    # 2. คำนวณเงื่อนไข Batch (2-30 วัน)
                                    should_add_to_batch = False
                                    if days_diff <= 30:
                                        should_add_to_batch = True
                                        # เช็คประวัติ 7 วัน
                                        if EMAIL_USE_HISTORY and person_data['id'] in self.current_history_data:
                                            try:
                                                last_notify = datetime.datetime.strptime(self.current_history_data[person_data['id']], "%Y-%m-%d").date()
                                                if (today - last_notify).days < 7: should_add_to_batch = Ture
                                            except: pass

                                    # 3. ตัดสินใจสร้าง PDF (Trigger)
                                    # PDF จะเกิดเมื่อ: (เป็นเคส HOT) หรือ (เป็นเคส Batch และ วันนี้เป็นวันศุกร์/รันมือ)
                                    need_pdf = False
                                    if should_send_hot:
                                        need_pdf = True
                                    elif should_add_to_batch and (is_friday or is_manual_run):
                                        need_pdf = True

                                    # --- เริ่มสร้าง PDF (ถ้าจำเป็น) ---
                                    # 🟢 2. เช็คการสร้าง PDF โดยดูจากความจำรายวัน
                                    if need_pdf:
                                        person_id = str(person_data['id'])
                                        
                                        # ตรวจสอบว่าวันนี้ (ตั้งแต่เที่ยงคืน) เคยอัปโหลดคนนี้หรือยัง
                                        if person_id in self.daily_pdf_cache:
                                            pdf_link = self.daily_pdf_cache[person_id]
                                            progress.console.print(f"   ♻️ ใช้วันเดิม: พบ PDF ของวันนี้แล้ว (ID: {person_id})", style="dim cyan")
                                        else:
                                            pdf_path = self.pdf_helper.save_page_as_pdf(self.driver, person_id)
                                            YOUR_DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID") 
                                            
                                            pdf_link = ""
                                            if YOUR_DRIVE_FOLDER_ID:
                                                pdf_link = self.pdf_helper.upload_to_drive(pdf_path, YOUR_DRIVE_FOLDER_ID)
                                                if pdf_link:
                                                    # เก็บเข้าความจำระหว่างรัน
                                                    self.daily_pdf_cache[person_id] = pdf_link
                                        
                                        if pdf_link:
                                            person_data['Resume_PDF_Link'] = pdf_link
                                            d['Resume_PDF_Link'] = pdf_link
                                    
                                    # ==========================================
                                    # 🟢 ดำเนินการส่งเมล (Logic เดิม)
                                    # ==========================================
                                    
                                    # HOT: ส่งทันที
                                    if should_send_hot:
                                        hot_subject = f"🔥 [HOT] พบผู้สมัครด่วน ({keyword}): {person_data['name']}"
                                        progress.console.print(f"   🚨 พบผู้สมัคร HOT -> ส่งเมลทันที!", style="bold red")
                                        self.send_single_email(hot_subject, [person_data], col_header="ประวัติบริษัท")
                                        self.update_history_sheet(person_data['id'], str(today))

                                    # Batch: เก็บเข้าตะกร้า (ถ้าเป็นวันศุกร์/รันมือ)
                                    if should_add_to_batch:
                                        current_keyword_batch.append(person_data)

                            except Exception as e:
                                progress.console.print(f"[bold red]❌ Error Link {i+1}: {e}[/]")
                            
                            progress.advance(task_id)

                # จบ Loop ใหญ่ของ Keyword นี้ -> ส่ง Batch ถ้าเป็นวันศุกร์
                if current_keyword_batch and (is_friday or is_manual_run):
                    progress.console.print(f"\n[bold green]📨 วันศุกร์/Manual -> ส่งสรุป Batch ({len(current_keyword_batch)} คน)[/]")
                    self.send_batch_email(current_keyword_batch, keyword)
                    if EMAIL_USE_HISTORY:
                        for p in current_keyword_batch: 
                            self.update_history_sheet(p['id'], str(today))

            console.print("⏳ พัก 3 วินาที ก่อนคำต่อไป...", style="dim")
            time.sleep(3)
        
        self.save_to_google_sheets()
        console.rule("[bold green]🏁 จบการทำงาน JobThai (G-Sheet Memory Mode)[/]")
        try: self.driver.quit()
        except: pass

        
if __name__ == "__main__":
    console.print("[bold green]🚀 Starting JobThai Scraper (Google Sheets Edition)...[/]")
    if not MY_USERNAME or not MY_PASSWORD:
        console.print(f"\n[bold red]❌ [CRITICAL ERROR] ไม่พบ User/Pass ในไฟล์ .env[/]")
        exit()
    scraper = JobThaiRowScraper()
    scraper.run()
