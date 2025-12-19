import asyncio
import uvicorn
import json
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

app = FastAPI()
shared_page = None 
data_queue = asyncio.Queue()
is_processing = False

# --- QUẢN LÝ WEBSOCKET ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except: pass

manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- CÁC HÀM TỰ ĐỘNG HÓA ---

async def fill_select2(page, container_selector, search_text):
    """Hàm chọn dropdown có tìm kiếm (Select2)"""
    if not search_text: return
    
    # Thêm try/except cục bộ để bắt lỗi tìm không thấy nhưng không làm chết chương trình ngay
    try:
        await page.wait_for_selector(container_selector, state="visible", timeout=3000)
        await page.click(container_selector)
        
        search_input = ".select2-container--open input.select2-search__field"
        await page.wait_for_selector(search_input, state="visible", timeout=2000)
        await page.fill(search_input, search_text)
        await asyncio.sleep(0.5) 
        
        # XPath tìm chính xác hoặc gần đúng
        result_xpath = f"//li[contains(@class, 'select2-results__option') and (normalize-space(text())='{search_text}' or contains(.,'{search_text}'))]"
        
        # Nếu không tìm thấy trong 3s -> Quăng lỗi để hàm cha xử lý
        await page.wait_for_selector(result_xpath, state="visible", timeout=3000)
        await page.click(result_xpath)
        
        # Đợi dropdown đóng
        try:
            await page.wait_for_selector(".select2-container--open", state="hidden", timeout=1000)
        except:
            await page.keyboard.press("Escape")
            
    except Exception as e:
        # Nếu lỗi (ví dụ sai tên xã), nhấn ESC để đóng dropdown nếu nó đang mở
        await page.keyboard.press("Escape")
        raise Exception(f"Không tìm thấy dữ liệu Select2: {search_text}") # Ném lỗi ra ngoài

async def auto_fill_location_and_open_form():
    """Tự động điền thông tin cơ sở lưu trú ban đầu"""
    global shared_page
    try:
        print("\n[INIT] Đang mở form thêm mới...")
        btn_add = "a#btnAddPersonLT" 
        await shared_page.wait_for_selector(btn_add, state="visible", timeout=5000)
        await shared_page.click(btn_add)
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=5000)
        print("[INIT] Form đã sẵn sàng.")
    except Exception as e:
        print(f"[INIT LỖI] Không mở được form: {e}")

async def fill_guest_data(task_item):
    """Xử lý nhập liệu cho 1 người"""
    global shared_page
    data = task_item['data']
    idx = task_item['index']
    
    if not shared_page: return

    try:
        # 1. Báo trạng thái ĐANG XỬ LÝ (Vàng)
        await manager.broadcast({"type": "PROCESSING", "index": idx})
        print(f"\n>>> [{idx}] Bắt đầu: {data.get('ho_ten')}")

        # Kiểm tra nếu form chưa mở thì mở lại
        if not await shared_page.is_visible("#addpersonLT"):
             await shared_page.click("a#btnAddPersonLT")
             await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=3000)

        # --- ĐIỀN DỮ LIỆU ---
        await shared_page.fill("input#guest_txtCITIZENNAME", data.get('ho_ten', '').upper())
        await shared_page.fill("input#guest_txtIDCARD_NUMBER", data.get('cccd', ''))

        dob = data.get('ngay_birth', '')
        if dob:
            await shared_page.evaluate(f"$('#guest_txtDOB').datepicker('update', '{dob}');")

        # Các dropdown dễ gây lỗi (Nếu lỗi sẽ nhảy xuống except)
        await fill_select2(shared_page, "#select2-guest_cboGENDER_ID-container", data.get('gioi_tinh', ''))
        await fill_select2(shared_page, "#select2-guest_cboRDPROVINCE_ID-container", data.get('tinh', ''))
        await fill_select2(shared_page, "#select2-guest_cboRDADDRESS_ID-container", data.get('xa', '')) # <-- Lỗi thường ở đây
        
        # Các trường text khác
        await shared_page.fill("input#guest_txtROOM", data.get('so_phong', ''))
        await shared_page.fill("textarea#guest_txtREASON", data.get('ly_do', ''))
        
        # Ngày tháng
        sd = data.get('thoi_gian_luu_tru', '')
        if sd: await shared_page.evaluate(f"document.getElementById('guest_txtSTART_DATE').value = '{sd}'")
        ed = data.get('luu_tru_den', '')
        if ed: await shared_page.evaluate(f"document.getElementById('guest_txtEND_DATE').value = '{ed}'")

        # Lưu
        await shared_page.click("#btnSaveNLT")
        await asyncio.sleep(1) # Chờ animation đóng modal

        # 2. Báo trạng thái THÀNH CÔNG (Xanh)
        await manager.broadcast({"type": "COMPLETED", "index": idx})
        print(f"    [OK] Xong: {data.get('ho_ten')}")

        # Chuẩn bị cho người sau: Mở lại form
        await shared_page.click("a#btnAddPersonLT")
        await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=5000)

    except Exception as e:
        # 3. Báo trạng thái LỖI (Đỏ) - QUAN TRỌNG: KHÔNG DỪNG QUEUE
        error_msg = str(e)
        # Làm sạch thông báo lỗi cho dễ đọc hơn nếu là lỗi Timeout của Playwright
        if "Timeout" in error_msg and "exceeded" in error_msg:
             error_msg = "Hết thời gian chờ (Timeout) - Không tìm thấy phần tử."
        
        print(f"    [!!!] LỖI tại người {idx}: {error_msg}")
        await manager.broadcast({"type": "ERROR", "index": idx, "message": error_msg})
        
        # --- LOGIC PHỤC HỒI (RECOVERY) ---
        print("    -> Đang reset form để nhập người tiếp theo...")
        try:
            # Nhấn ESC đề phòng dropdown đang kẹt
            await shared_page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            
            # Refresh form bằng cách bấm nút Thêm Mới lại (hoặc đóng modal rồi mở lại)
            # Giả sử nút Thêm mới luôn click được để reset
            if await shared_page.is_visible("a#btnAddPersonLT"):
                 await shared_page.click("a#btnAddPersonLT")
            
            # Đợi form hiện lên lại để sẵn sàng cho vòng lặp sau
            await shared_page.wait_for_selector("#addpersonLT", state="visible", timeout=5000)
            
        except Exception as recover_err:
            print(f"    [FATAL] Không thể phục hồi form: {recover_err}")

async def process_queue():
    global is_processing
    is_processing = True
    print("\n--- BẮT ĐẦU XỬ LÝ DANH SÁCH ---")
    
    while not data_queue.empty():
        # Lấy từng người ra
        task_item = await data_queue.get()
        
        # Chạy hàm nhập liệu (đã bao bọc try/except ở trên nên sẽ không crash)
        await fill_guest_data(task_item)
        
        # Đánh dấu xong task này
        data_queue.task_done()
    
    is_processing = False
    print("--- HOÀN TẤT DANH SÁCH ---\n")

@app.post("/send-to-web")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    items = data.get("items", [])
    for idx, item in enumerate(items):
        await data_queue.put({"index": idx, "data": item})
    
    if not is_processing:
        background_tasks.add_task(process_queue)
    
    return {"status": "started", "message": f"Đã nhận {len(items)} khách. Đang chạy..."}

async def main():
    global shared_page
    async with async_playwright() as p:
        try:
            # Kết nối Chrome debug
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            shared_page = context.pages[0] if context.pages else await context.new_page()
            
            # Nếu chưa vào web, tự vào
            if "dichvucong" not in shared_page.url:
                await shared_page.goto("https://dichvucong.bocongan.gov.vn/")
            
            print("[SẴN SÀNG] Backend đang chạy tại port 8000...")
            config = uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            server = uvicorn.Server(config)
            await server.serve()
            
        except Exception as e:
            print(f"LỖI KHỞI ĐỘNG: {e}")
            print("Hãy chắc chắn bạn đã chạy Chrome với lệnh: chrome.exe --remote-debugging-port=9222")

if __name__ == "__main__":
    asyncio.run(main())