import os
import base64
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from rich.console import Console

console = Console()

class PDFManager:
    def __init__(self, key_json_str=None): 
        # รับค่า key_json_str ไว้เฉยๆ เพื่อให้เข้ากับ Git1.py แต่จะดึงค่าจาก OAuth แทน
        self.service = None
        try:
            # ดึงค่าจาก GitHub Secrets (Environment Variables)
            client_id = os.getenv("DRIVE_CLIENT_ID")
            client_secret = os.getenv("DRIVE_CLIENT_SECRET")
            refresh_token = os.getenv("DRIVE_REFRESH_TOKEN")

            if client_id and client_secret and refresh_token:
                # สร้าง Credential จาก Refresh Token เพื่อล็อกอินในนามของคุณ
                creds = Credentials(
                    None, 
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.service = build('drive', 'v3', credentials=creds)
                console.print("✅ เชื่อมต่อ Google Drive (OAuth Mode) สำเร็จ", style="green")
            else:
                console.print("⚠️ ไม่พบ OAuth Credentials ใน Secret", style="yellow")
        except Exception as e:
            console.print(f"❌ Google Drive Init Error: {e}", style="red")

    def save_page_as_pdf(self, driver, person_id, save_folder="resume_pdfs"):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        filename = f"Resume_{person_id}.pdf"
        filepath = os.path.join(save_folder, filename)
        try:
            print_options = {
                'landscape': False, 'displayHeaderFooter': False,
                'printBackground': True, 'preferCSSPageSize': True,
                'paperWidth': 8.27, 'paperHeight': 11.69
            }
            result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(result['data']))
            return filepath
        except Exception as e:
            console.print(f"❌ Print PDF Error: {e}", style="red")
            return None

    def upload_to_drive(self, filepath, folder_id):
        if not self.service or not folder_id: return ""
        drive_link = ""
        try:
            file_metadata = {'name': os.path.basename(filepath), 'parents': [folder_id]}
            media = MediaFileUpload(filepath, mimetype='application/pdf')
            file = self.service.files().create(
                body=file_metadata, media_body=media, fields='id, webViewLink'
            ).execute()
            console.print(f"☁️ อัปโหลด PDF แล้ว (ID: {file.get('id')})", style="bold green")
            drive_link = file.get('webViewLink')
        except Exception as e:
            console.print(f"❌ Upload Error: {e}", style="red")
        finally:
            if os.path.exists(filepath):
                try: os.remove(filepath)
                except: pass
        return drive_link
