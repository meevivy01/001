import os
import base64
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from rich.console import Console

console = Console()

class PDFManager:
    def __init__(self, key_json_str):
        self.service = None
        try:
            if key_json_str:
                creds_dict = json.loads(key_json_str)
                scopes = ['https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                self.service = build('drive', 'v3', credentials=creds)
                console.print("✅ เชื่อมต่อ Google Drive Service สำเร็จ", style="green")
            else:
                console.print("⚠️ ไม่พบ Google Service Account Key", style="yellow")
        except Exception as e:
            console.print(f"❌ Google Drive Init Error: {e}", style="red")

    def save_page_as_pdf(self, driver, person_id, save_folder="resume_pdfs"):
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        filename = f"Resume_{person_id}.pdf"
        filepath = os.path.join(save_folder, filename)
        try:
            # สั่ง Chrome ให้ Print ผ่าน DevTools Protocol
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
            # ลบไฟล์ในเครื่องทิ้งเสมอ
            if os.path.exists(filepath):
                try: os.remove(filepath)
                except: pass
        return drive_link
